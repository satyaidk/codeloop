"""HTTP layer: routes, dependency wiring, request guards and the app lifecycle.

Run locally with:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent import SCRATCH, AgentRequest, AgentService, LearnResult, ProjectBrief, present
from app.config import Settings, get_settings
from app.llm.base import LLMUnavailableError
from app.llm.providers import PROVIDER_IDS, ProviderRegistry
from app.memory import HindsightMemoryStore, MemoryStore, make_hindsight_client
from app.prompts import TEST_METHODS
from app.schemas import (
    PROJECT_ID_PATTERN,
    AgentRunBody,
    AppInfo,
    CloneBody,
    HealthResponse,
    LearnResponse,
    MemoriesResponse,
    ProjectOut,
    ProjectStatus,
    ProviderOut,
)
from app.workspace import Project, ProjectRegistry, WorkspaceError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("codeloop")

# The React app (frontend/) builds into this folder; `npm run build` fills it.
STATIC_DIR = Path(__file__).parent / "static"
_COMMIT = re.compile(r"^[0-9a-f]{4,40}$")


@dataclass
class Services:
    agent: AgentService
    memory: MemoryStore
    providers: ProviderRegistry
    projects: ProjectRegistry
    info: AppInfo


def build_services(settings: Settings) -> Services:
    memory = HindsightMemoryStore(
        client=make_hindsight_client(settings),
        bank_prefix=settings.bank_prefix,
        recall_budget=settings.recall_budget,
        recall_max_tokens=settings.recall_max_tokens,
        recall_max_notes=settings.recall_max_notes,
    )
    providers = ProviderRegistry(settings)
    projects = ProjectRegistry(
        settings.workspace_root, settings.command_allowlist_set(), settings.command_timeout_seconds
    )
    agent = AgentService(
        memory, providers, projects, settings.max_steps, settings.max_history_messages, settings.allow_commands
    )
    info = AppInfo(
        default_provider=settings.default_provider,
        workspace_root=str(projects.root),
        max_steps=settings.max_steps,
        max_history_messages=settings.max_history_messages,
        commands_enabled=settings.allow_commands,
        command_allowlist=sorted(settings.command_allowlist_set()),
        test_methods={key: label for key, (label, _) in TEST_METHODS.items()},
    )
    return Services(agent, memory, providers, projects, info)


class WebAppFiles(StaticFiles):
    """The built web app. Files in assets/ have a content hash in their name, so browsers may keep them forever."""

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        if path.replace("\\", "/").startswith("assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


NOT_BUILT_PAGE = """<!doctype html><meta charset="utf-8"><title>CodeLoop</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
<h1>CodeLoop's server is running</h1>
<p>The web app hasn't been built yet. In the <code>frontend</code> folder run <code>npm install</code> and
<code>npm run build</code>, then reload this page. For live editing, run <code>npm run dev</code> and open
<a href="http://localhost:5173">localhost:5173</a>.</p><p>API docs: <a href="/docs">/docs</a>.</p></body>"""


def create_app(
    services: Services | None = None,
    static_dir: Path = STATIC_DIR,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    """App factory. Tests pass in services built on fakes; production builds the real ones from settings."""
    settings = get_settings()
    hosts = allowed_hosts if allowed_hosts is not None else settings.allowed_host_list()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services or build_services(settings)
        logger.info("workspace: %s", app.state.services.projects.root)
        yield
        await app.state.services.agent.drain()
        await app.state.services.memory.close()

    app = FastAPI(
        title="CodeLoop",
        description="A coding agent with long-term project memory, built on Hindsight.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Only accept requests addressed to this machine (blocks DNS rebinding), and refuse state-changing
    # requests sent by other websites' pages (their Origin header names another host).
    if "*" not in hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def guard_and_log(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and "*" not in hosts:
            if (urlparse(origin).hostname or "") not in {h.strip("[]") for h in hosts}:
                return JSONResponse({"detail": "Requests from other websites are not allowed."}, status_code=403)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        logger.info("%s %s -> %s in %.0fms", request.method, request.url.path, response.status_code, elapsed)
        return response

    def svc(request: Request) -> Services:
        return request.app.state.services

    def project_or_404(request: Request, project_id: str) -> Project:
        project = svc(request).projects.get(project_id)
        if project is None:
            raise HTTPException(404, f"No project called '{project_id}' in the workspace.")
        return project

    def scope_or_404(request: Request, scope: str) -> str:
        return scope if scope == SCRATCH else project_or_404(request, scope).id

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz(request: Request) -> HealthResponse:
        ok = await svc(request).memory.is_healthy()
        return HealthResponse(status="ok" if ok else "degraded", memory=ok)

    @app.get("/api/info", response_model=AppInfo)
    async def app_info(request: Request) -> AppInfo:
        return svc(request).info

    @app.get("/api/providers", response_model=list[ProviderOut])
    async def providers(request: Request) -> list[ProviderOut]:
        registry = svc(request).providers

        async def describe(status) -> ProviderOut:
            spec = status.spec
            models, installed = list(spec.suggested_models), None
            if status.configured and (spec.local or spec.id == "custom"):
                listed = await registry.get(spec.id).list_models()
                installed = listed is not None
                if listed:
                    models = listed
            if status.default_model and status.default_model not in models and installed is not True:
                models.insert(0, status.default_model)
            return ProviderOut(
                id=spec.id, label=spec.label, kind=spec.kind, configured=status.configured, local=spec.local,
                default_model=status.default_model, models=models, installed=installed, hint=status.hint,
            )  # fmt: skip

        return list(await asyncio.gather(*(describe(s) for s in registry.statuses())))

    # ---- projects ----

    def project_out(registry: ProjectRegistry, project: Project) -> ProjectOut:
        """A project with its git state (runs git, so call it in a worker thread)."""
        out = ProjectOut(id=project.id, name=project.name, is_git=project.is_git)
        if project.is_git:
            ws = registry.workspace(project)
            out.branch = ws.git("rev-parse", "--abbrev-ref", "HEAD")
            last = ws.git("log", "-1", "--format=%h%x1f%s%x1f%cI")
            if last and last.count("\x1f") == 2:
                out.head, out.subject, out.committed_at = last.split("\x1f")
        return out

    @app.get("/api/projects", response_model=list[ProjectOut])
    async def projects(request: Request) -> list[ProjectOut]:
        registry = svc(request).projects
        return list(await asyncio.gather(*(asyncio.to_thread(project_out, registry, p) for p in registry.list())))

    @app.post("/api/projects", response_model=ProjectOut, status_code=201)
    async def clone_project(body: CloneBody, request: Request) -> ProjectOut:
        registry = svc(request).projects
        try:
            project = await asyncio.to_thread(registry.clone, body.git_url, body.name)
        except WorkspaceError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await asyncio.to_thread(project_out, registry, project)

    @app.get("/api/projects/{project_id}/status", response_model=ProjectStatus)
    async def project_status(
        request: Request,
        project_id: str = PathParam(pattern=PROJECT_ID_PATTERN),
        since: str | None = Query(default=None, max_length=40, description="A commit to count new commits from"),
    ) -> ProjectStatus:
        registry = svc(request).projects
        project = project_or_404(request, project_id)
        out = await asyncio.to_thread(project_out, registry, project)
        commits_since = None
        if since and _COMMIT.match(since) and project.is_git:
            counted = await asyncio.to_thread(registry.workspace(project).git, "rev-list", "--count", f"{since}..HEAD")
            commits_since = int(counted) if counted and counted.isdigit() else None
        try:
            notes: int | None = await svc(request).memory.count(project.id)
        except Exception:
            logger.warning("couldn't count memories", exc_info=True)
            notes = None
        return ProjectStatus(project=out, notes=notes, commits_since=commits_since)

    @app.post("/api/projects/{project_id}/learn", response_model=LearnResponse)
    async def learn(request: Request, project_id: str = PathParam(pattern=PROJECT_ID_PATTERN)) -> LearnResponse:
        project = project_or_404(request, project_id)
        try:
            result: LearnResult = await svc(request).agent.learn(project)
        except Exception as exc:
            logger.exception("learning the project failed")
            raise HTTPException(503, "Memory service unavailable, so the project couldn't be learned.") from exc
        return LearnResponse(**result.__dict__)

    # ---- memory (per project, or "scratch" for chats without a project) ----

    @app.get("/api/memory/{scope}", response_model=MemoriesResponse)
    async def memories(
        request: Request,
        scope: str = PathParam(pattern=PROJECT_ID_PATTERN),
        q: str | None = Query(default=None, max_length=500, description="Search by relevance; omit to list all"),
    ) -> MemoriesResponse:
        scope = scope_or_404(request, scope)
        try:
            found, total = await svc(request).agent.memories(scope, q)
        except Exception as exc:
            logger.exception("memory lookup failed")
            raise HTTPException(503, "Memory service unavailable") from exc
        return MemoriesResponse(memories=present(found), total=total)

    @app.get("/api/memory/{scope}/brief", response_model=ProjectBrief)
    async def brief(request: Request, scope: str = PathParam(pattern=PROJECT_ID_PATTERN)) -> ProjectBrief:
        scope = scope_or_404(request, scope)
        try:
            return await svc(request).agent.brief(scope)
        except Exception as exc:
            logger.exception("brief failed")
            raise HTTPException(503, "Memory service unavailable") from exc

    @app.delete("/api/memory/{scope}", status_code=204)
    async def forget(request: Request, scope: str = PathParam(pattern=PROJECT_ID_PATTERN)) -> Response:
        scope = scope_or_404(request, scope)
        try:
            await svc(request).agent.forget(scope)
        except Exception as exc:
            logger.exception("forget failed")
            raise HTTPException(503, "Memory service unavailable") from exc
        logger.info("deleted the long-term memory of %s", scope)
        return Response(status_code=204)

    # ---- the agent ----

    @app.post("/api/agent")
    async def run_agent(body: AgentRunBody, request: Request) -> StreamingResponse:
        services_ = svc(request)
        project = project_or_404(request, body.project_id) if body.project_id else None
        provider = body.provider or services_.info.default_provider
        if provider not in PROVIDER_IDS:
            raise HTTPException(422, f"Unknown provider '{provider}'. Known: {', '.join(PROVIDER_IDS)}.")
        run = AgentRequest(
            project=project,
            message=body.message,
            provider=provider,
            model=body.model or None,
            mode=body.mode,
            history=[turn.model_dump() for turn in body.history],
            test_methods=list(body.test_methods),
            use_memory=body.use_memory,
            allow_edits=body.allow_edits and project is not None,
            allow_commands=body.allow_commands and project is not None,
        )

        async def events() -> AsyncIterator[str]:
            try:
                async for event in services_.agent.run(run):
                    yield json.dumps(event) + "\n"
            except LLMUnavailableError as exc:
                yield json.dumps({"type": "error", "message": exc.user_message}) + "\n"
            except Exception:
                logger.exception("agent run failed")
                message = "The agent hit an unexpected error. The details are in the server log."
                yield json.dumps({"type": "error", "message": message}) + "\n"

        # One JSON event per line, sent as soon as it happens.
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(events(), media_type="application/x-ndjson", headers=headers)

    # ---- the web app ----

    @app.get("/", include_in_schema=False)
    async def web_app() -> Response:
        index = static_dir / "index.html"
        page = FileResponse(index) if index.is_file() else HTMLResponse(NOT_BUILT_PAGE)
        page.headers["Cache-Control"] = "no-cache"  # always check for a newer build
        return page

    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/", WebAppFiles(directory=static_dir), name="web")  # last: a mount at "/" matches everything
    return app


app = create_app()
