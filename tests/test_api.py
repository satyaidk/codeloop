"""API tests: the real FastAPI routes, with fake memory and a scripted model."""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent import AgentService
from app.main import create_app
from app.memory import Reflection
from tests.fakes import ScriptedLLM, answer, call

HOSTS = ["testserver", "localhost"]


@pytest.fixture
def web_dir(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<title>CodeLoop</title><div id=root></div>", encoding="utf-8")
    (web / "assets" / "app-1a2b.js").write_text("console.log(1)", encoding="utf-8")
    return web


@pytest.fixture
def client(services, web_dir):
    with TestClient(create_app(services, static_dir=web_dir, allowed_hosts=HOSTS)) as c:
        yield c


def stream(client, **body):
    res = client.post("/api/agent", json=body)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in res.text.splitlines() if line]


def test_agent_streams_events_for_a_project_chat(client, llm):
    llm.script = [call("search_code", pattern="def total"), answer("It's in src/cart.py:1.")]

    events = stream(client, project_id="shop-api", message="Where is the total computed?")

    assert [e["type"] for e in events] == ["start", "memory", "tool_start", "tool_end", "answer"]
    assert events[0]["model"] == "qwen3:4b-instruct"  # the server default for Ollama
    assert events[3]["summary"] == "1 match for “def total”"
    assert events[-1]["text"] == "It's in src/cart.py:1."


def test_agent_uses_the_requested_model(client, llm):
    stream(client, message="hi", provider="ollama", model="qwen2.5-coder:7b")
    assert llm.calls[0]["model"] == "qwen2.5-coder:7b"


def test_edits_and_commands_are_never_offered_without_a_project(client, llm):
    stream(client, message="hi", allow_edits=True, allow_commands=True)
    assert set(llm.calls[0]["tools"]) == {"recall_memory", "save_note"}


def test_agent_reports_an_unconfigured_provider_in_the_stream(client):
    events = stream(client, message="hi", provider="openai")
    assert events == [{"type": "error", "message": "OpenAI isn't set up. Add OPENAI_API_KEY to .env."}]


def test_agent_rejects_unknown_projects_and_providers(client):
    assert client.post("/api/agent", json={"project_id": "nope", "message": "x"}).status_code == 404
    assert client.post("/api/agent", json={"message": "x", "provider": "skynet"}).status_code == 422
    assert client.post("/api/agent", json={"project_id": "../etc", "message": "x"}).status_code == 422
    assert client.post("/api/agent", json={"message": ""}).status_code == 422


def test_unexpected_errors_end_the_stream_cleanly(client, services, monkeypatch):
    async def explode(req):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(services.agent, "run", explode)
    events = stream(client, message="hi")
    assert events == [
        {"type": "error", "message": "The agent hit an unexpected error. The details are in the server log."}
    ]


def test_projects_lists_workspace_folders_with_git_state(client, git_project):
    projects = client.get("/api/projects").json()

    assert projects[0]["id"] == "shop-api" and projects[0]["is_git"] is True
    assert projects[0]["branch"] == "main" and projects[0]["subject"] == "Add cart"


def test_project_status_counts_notes_and_new_commits(client, git_project, memory):
    head = client.get("/api/projects").json()[0]["head"]
    memory.banks["shop-api"] = ["fact one", "fact two"]

    status = client.get("/api/projects/shop-api/status", params={"since": head}).json()

    assert status["notes"] == 2 and status["commits_since"] == 0


def test_clone_rejects_unsafe_urls(client):
    res = client.post("/api/projects", json={"git_url": "file:///etc/passwd"})
    assert res.status_code == 400 and "https://" in res.json()["detail"]


def test_learn_writes_a_snapshot_into_project_memory(client, memory):
    res = client.post("/api/projects/shop-api/learn")

    assert res.status_code == 200
    body = res.json()
    assert body["files_scanned"] >= 5 and body["characters"] > 100
    snapshot = memory.banks["shop-api"][0]
    assert "# Project snapshot: shop-api" in snapshot and "src/" in snapshot
    assert "sk_live_secret" not in snapshot  # secrets never leave the machine
    assert memory.contexts == ["project snapshot"]


def test_memory_list_search_and_forget(client, memory):
    memory.banks["shop-api"] = ["Cart totals live in src/cart.py", "Uses pytest"]

    listed = client.get("/api/memory/shop-api").json()
    searched = client.get("/api/memory/shop-api", params={"q": "where are cart totals"}).json()
    deleted = client.delete("/api/memory/shop-api")

    assert listed["total"] == 2 and listed["memories"][0]["text"] == "Cart totals live in src/cart.py"
    assert [m["text"] for m in searched["memories"]] == ["Cart totals live in src/cart.py"]
    assert deleted.status_code == 204 and "shop-api" not in memory.banks


def test_scratch_memory_needs_no_project(client, memory):
    memory.banks["scratch"] = ["Prefers type hints"]
    assert client.get("/api/memory/scratch").json()["total"] == 1
    assert client.get("/api/memory/unknown-project").status_code == 404


def test_brief_returns_structured_output(client, memory):
    memory.reflect_result = Reflection(
        text="",
        structured={"summary": "A shop API.", "stack": ["Python"], "structure": ["src/cart.py: totals"],
                    "commands": ["pytest -q"], "conventions": [], "open_issues": []},
    )  # fmt: skip
    brief = client.get("/api/memory/shop-api/brief").json()
    assert brief["summary"] == "A shop API." and brief["commands"] == ["pytest -q"]


def test_brief_falls_back_to_text(client, memory):
    memory.reflect_result = Reflection(text="Not much is known yet.")
    assert client.get("/api/memory/shop-api/brief").json()["summary"] == "Not much is known yet."


def test_memory_outage_is_a_503(client, services, monkeypatch):
    async def down(*args, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(services.agent, "memories", down)
    assert client.get("/api/memory/shop-api").status_code == 503


def test_providers_list_every_provider_and_installed_local_models(client):
    providers = {p["id"]: p for p in client.get("/api/providers").json()}

    assert set(providers) >= {
        "ollama",
        "anthropic",
        "openai",
        "gemini",
        "groq",
        "openrouter",
        "deepseek",
        "mistral",
        "custom",
    }
    assert providers["ollama"]["installed"] is True
    assert providers["ollama"]["models"] == ["qwen3:4b-instruct", "qwen2.5-coder:7b"]
    assert providers["anthropic"]["configured"] is False
    assert providers["anthropic"]["hint"] == "Add ANTHROPIC_API_KEY to .env"
    assert providers["anthropic"]["models"][0] == "claude-opus-5-5"


def test_providers_marks_an_offline_ollama(client, llm):
    llm.models = None
    assert {p["id"]: p for p in client.get("/api/providers").json()}["ollama"]["installed"] is False


def test_info_and_health(client):
    info = client.get("/api/info").json()
    assert info["default_provider"] == "ollama" and "pytest" in info["command_allowlist"]
    assert info["test_methods"]["property"] == "Property-based"
    assert client.get("/healthz").json() == {"status": "ok", "memory": True}


def test_foreign_hosts_are_refused(services, web_dir):
    with TestClient(create_app(services, static_dir=web_dir, allowed_hosts=["localhost"])) as c:
        assert c.get("/api/info").status_code == 400  # Host: testserver


def test_requests_from_other_websites_are_refused(client):
    res = client.post("/api/agent", json={"message": "hi"}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    ok = client.post("/api/agent", json={"message": "hi"}, headers={"Origin": "http://localhost:5173"})
    assert ok.status_code == 200


def test_web_app_is_served_with_cache_headers(client):
    page = client.get("/")
    asset = client.get("/assets/app-1a2b.js")
    assert page.headers["cache-control"] == "no-cache" and "CodeLoop" in page.text
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_shutdown_waits_for_memory_writes_and_closes_memory(services, web_dir, memory):
    services.agent = AgentService(memory, services.providers, services.projects)
    services.providers.override("ollama", ScriptedLLM(answer("ok")))
    with TestClient(create_app(services, static_dir=web_dir, allowed_hosts=HOSTS)) as c:
        stream(c, project_id="shop-api", message="remember this please")
    assert memory.banks["shop-api"] and memory.closed
