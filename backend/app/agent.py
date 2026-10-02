"""The agent loop: recall -> (think -> act)* -> answer -> retain.

This is the business logic. It knows nothing about HTTP (main.py) or about any particular model or memory
vendor (llm/, memory.py), which is what makes it testable with fakes.

`run()` is an async generator of events, so the web app can show each step as it happens:
  start, memory, thought, tool_start, tool_end, notice, then exactly one of answer or error.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.llm.base import LLM, LLMUnavailableError, Message, ToolsUnsupportedError, Usage
from app.memory import Memory, MemoryStore, display_text
from app.prompts import BRIEF_QUESTION, STEP_LIMIT, build_system_prompt, format_turn
from app.snapshot import take_snapshot
from app.tools import Toolbox, ToolResult
from app.workspace import Project, ProjectRegistry

logger = logging.getLogger(__name__)

SCRATCH = "scratch"  # memory scope for chats that aren't about a project
Event = dict[str, Any]


class Providers(Protocol):
    def get(self, provider_id: str) -> LLM: ...

    def default_model(self, provider_id: str) -> str: ...


class ProjectBrief(BaseModel):
    """Structured output we ask Hindsight's reflect() to fill in."""

    summary: str = Field(description="Two or three sentences: what this project is and does.")
    stack: list[str] = Field(description="Languages, frameworks and key libraries.")
    structure: list[str] = Field(description="Key folders and files and what each is for.")
    commands: list[str] = Field(description="Commands to install, build, run, lint and test, exactly as typed.")
    conventions: list[str] = Field(description="Coding conventions and patterns the project follows.")
    open_issues: list[str] = Field(description="Known bugs, risks or unfinished work.")


@dataclass
class AgentRequest:
    project: Project | None
    message: str
    provider: str
    model: str | None = None
    mode: str = "ask"
    history: list[Message] = field(default_factory=list)
    test_methods: list[str] = field(default_factory=list)
    use_memory: bool = True
    allow_edits: bool = False
    allow_commands: bool = False
    remember: bool = True  # evaluation runs pass False so they don't write into the memory they measure


@dataclass
class RunRecord:
    """What a run touched; shown under the answer and written into memory."""

    files_read: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commands: list[tuple[str, int | None]] = field(default_factory=list)
    notes_saved: int = 0

    def add(self, result: ToolResult) -> None:
        if result.file_read and result.file_read not in self.files_read:
            self.files_read.append(result.file_read)
        if result.file_changed and result.file_changed not in self.files_changed:
            self.files_changed.append(result.file_changed)
        if result.command:
            self.commands.append((result.command, result.exit_code))
        if result.note_saved:
            self.notes_saved += 1


@dataclass
class LearnResult:
    files_scanned: int
    characters: int
    head: str | None
    branch: str | None
    learned_at: str


class AgentService:
    def __init__(
        self,
        memory: MemoryStore,
        providers: Providers,
        projects: ProjectRegistry,
        max_steps: int = 12,
        max_history: int = 12,
        commands_enabled: bool = True,
    ):
        self._memory = memory
        self._providers = providers
        self._projects = projects
        self._max_steps = max_steps
        self._max_history = max_history
        self._commands_enabled = commands_enabled
        self._background: set[asyncio.Task] = set()

    async def run(self, req: AgentRequest) -> AsyncIterator[Event]:
        started = time.monotonic()
        scope = req.project.id if req.project else SCRATCH
        model = req.model or self._providers.default_model(req.provider)
        try:
            llm = self._providers.get(req.provider)
        except LLMUnavailableError as exc:
            yield {"type": "error", "message": exc.user_message}
            return
        yield {"type": "start", "provider": req.provider, "model": model, "project": scope, "mode": req.mode}

        # 1. RECALL what this project's memory knows that is relevant to the question.
        notes: list[Memory] = []
        memory_ok = True
        if req.use_memory:
            try:
                notes = await self._memory.recall(scope, req.message)
            except Exception:
                logger.exception("recall failed; answering without memory")
                memory_ok = False
            yield {"type": "memory", "available": memory_ok, "notes": present(notes)}

        workspace = self._projects.workspace(req.project) if req.project else None
        toolbox = Toolbox(
            workspace=workspace,
            memory=self._memory if req.use_memory and memory_ok else None,
            scope=scope,
            allow_edits=req.allow_edits,
            allow_commands=req.allow_commands and self._commands_enabled,
            allow_notes=req.remember,
        )
        tools = toolbox.specs()
        allowlist = sorted(workspace.allowlist) if workspace else []
        # A small map of the project saves the model a round of exploring (and each round re-sends everything).
        layout = (await asyncio.to_thread(workspace.list_tree, ".", 2, 80))[0] if workspace else None

        def system_prompt() -> str:
            return build_system_prompt(
                req.mode,
                req.project.name if req.project else None,
                {t.name for t in tools},
                notes if req.use_memory else None,
                req.test_methods,
                allowlist,
                layout,
                memory_down=req.use_memory and not memory_ok,
            )

        system = system_prompt()
        messages: list[Message] = [
            *trim_history(req.history, self._max_history),
            {"role": "user", "content": req.message},
        ]
        usage = Usage()
        record = RunRecord()
        steps = 0

        # 2. THINK and ACT until the model answers without calling a tool, or the step limit is reached.
        while True:
            final = steps >= self._max_steps
            try:
                turn = await llm.complete(model, system, messages, tools, "none" if final else "auto")
            except ToolsUnsupportedError as exc:
                if not tools:
                    yield {"type": "error", "message": exc.user_message}
                    return
                yield {"type": "notice", "message": exc.user_message}
                tools = []
                system = system_prompt()
                continue
            except LLMUnavailableError as exc:
                logger.error("model call failed: %s", exc)
                yield {"type": "error", "message": exc.user_message}
                return
            usage.add(turn.usage)
            if final or not turn.tool_calls:
                answer = turn.text
                break

            messages.append({"role": "assistant", "content": turn.text, "tool_calls": turn.tool_calls, "raw": turn.raw})
            if turn.text:
                yield {"type": "thought", "text": turn.text}
            for call in turn.tool_calls:
                yield {"type": "tool_start", "id": call.id, "name": call.name, "label": toolbox.label(call)}
                result = await toolbox.run(call)
                record.add(result)
                yield {
                    "type": "tool_end",
                    "id": call.id,
                    "name": call.name,
                    "ok": result.ok,
                    "summary": result.summary,
                    "detail": result.detail,
                    "kind": result.kind,
                }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": result.content,
                        "is_error": not result.ok,
                    }
                )
            steps += 1
            if steps >= self._max_steps:
                messages.append({"role": "user", "content": STEP_LIMIT})

        if not answer.strip():
            answer = "I couldn't put together an answer. Try asking again, or break the question into smaller steps."

        # 3. REPLY, with what the run used and cost.
        yield {
            "type": "answer",
            "text": answer,
            "steps": steps,
            "usage": {"input": usage.input_tokens, "output": usage.output_tokens, "cached": usage.cached_tokens},
            "files_read": record.files_read,
            "files_changed": record.files_changed,
            "notes_saved": record.notes_saved,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

        # 4. RETAIN this exchange in the background; the developer never waits for it.
        if req.use_memory and memory_ok and req.remember:
            content = format_turn(
                req.mode, req.message, answer, record.files_read, record.files_changed, record.commands
            )
            self._in_background(self._memory.remember(scope, content, context=f"coding session ({req.mode})"))

    # ---- project memory ----

    async def learn(self, project: Project) -> LearnResult:
        workspace = self._projects.workspace(project)
        snapshot = await asyncio.to_thread(take_snapshot, workspace, project.name)
        await self._memory.remember(project.id, snapshot.text, context="project snapshot")
        return LearnResult(
            files_scanned=snapshot.files_scanned,
            characters=len(snapshot.text),
            head=snapshot.head,
            branch=snapshot.branch,
            learned_at=datetime.now(UTC).isoformat(),
        )

    async def brief(self, scope: str) -> ProjectBrief:
        reflection = await self._memory.reflect(scope, BRIEF_QUESTION, schema=ProjectBrief.model_json_schema())
        if reflection.structured:
            try:
                return ProjectBrief.model_validate(reflection.structured)
            except ValueError:
                logger.warning("brief didn't match the schema; returning the text")
        return ProjectBrief(
            summary=reflection.text, stack=[], structure=[], commands=[], conventions=[], open_issues=[]
        )

    async def memories(self, scope: str, query: str | None = None) -> tuple[list[Memory], int]:
        if query:
            found = await self._memory.recall(scope, query)
            return found, len(found)
        found = await self._memory.list_all(scope)
        return found, await self._memory.count(scope)

    async def forget(self, scope: str) -> None:
        await self._memory.forget(scope)

    # ---- background work ----

    def _in_background(self, work) -> None:
        async def guarded() -> None:
            try:
                await work
            except Exception:
                logger.exception("saving to memory failed; this exchange won't be remembered")

        task = asyncio.create_task(guarded())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def drain(self, timeout: float = 10) -> None:
        """Let pending memory writes finish (called on shutdown and by tests)."""
        if self._background:
            await asyncio.wait(set(self._background), timeout=timeout)


def present(memories: list[Memory]) -> list[dict[str, Any]]:
    """Notes as the web app shows them: readable text, each fact once, original order. Hindsight often stores a
    fact and the matching observation with only punctuation between them, so those count as one."""
    seen: set[str] = set()
    out = []
    for memory in memories:
        text = display_text(memory.text)
        key = text.lower().rstrip(" .!;:")
        if text and key not in seen:
            seen.add(key)
            out.append({"text": text, "type": memory.type, "occurred_at": memory.occurred_at})
    return out


def trim_history(history: list[Message], limit: int) -> list[Message]:
    """The most recent turns, starting on a developer turn so the model never sees half an exchange."""
    trimmed = history[-limit:] if limit > 0 else []
    while trimmed and trimmed[0]["role"] != "user":
        trimmed = trimmed[1:]
    return trimmed
