"""Shared fixtures: a small sample project on disk, and the app's services built on fakes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agent import AgentService
from app.config import Settings
from app.llm.providers import ProviderRegistry
from app.main import Services, build_services
from app.workspace import ProjectRegistry, Workspace
from tests.fakes import FakeMemoryStore, ScriptedLLM

ALLOW = frozenset({"python", "git", "pytest"})


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """A workspace with one project, "shop-api", holding a few realistic files."""
    root = tmp_path / "workspace"
    project = root / "shop-api"
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "node_modules" / "left-pad").mkdir(parents=True)
    (project / "README.md").write_text(
        "# Shop API\nA tiny API for an online shop.\n\nRun tests: pytest -q\n", encoding="utf-8"
    )
    (project / "src" / "cart.py").write_text(
        "def total(items):\n    return sum(i['price'] * i['qty'] for i in items)\n\n\ndef empty():\n    return []\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_cart.py").write_text(
        "from src.cart import total\n\n\ndef test_total():\n    assert total([{'price': 2, 'qty': 3}]) == 6\n",
        encoding="utf-8",
    )
    (project / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1\n", encoding="utf-8")
    (project / ".env").write_text("STRIPE_KEY=sk_live_secret\n", encoding="utf-8")
    (project / ".env.example").write_text("STRIPE_KEY=\nDATABASE_URL=postgres://localhost/shop\n", encoding="utf-8")
    (project / "package.json").write_text(
        '{"name": "shop-web", "scripts": {"test": "vitest run"}, "dependencies": {"react": "^19"}}', encoding="utf-8"
    )
    return root


@pytest.fixture
def project_dir(workspace_root: Path) -> Path:
    return workspace_root / "shop-api"


@pytest.fixture
def workspace(project_dir: Path) -> Workspace:
    return Workspace(project_dir, ALLOW, timeout=30)


@pytest.fixture
def git_project(project_dir: Path) -> Path:
    """The sample project as a git repository with one commit."""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}  # fmt: skip
    import os

    full_env = {**os.environ, **env}
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "Add cart"]):
        subprocess.run(["git", *args], cwd=project_dir, check=True, env=full_env, capture_output=True)
    return project_dir


@pytest.fixture
def memory() -> FakeMemoryStore:
    return FakeMemoryStore()


def isolated_settings(**overrides) -> Settings:
    """Settings that ignore any .env file and any provider keys set on this machine."""
    keys = {
        f"{p}_api_key": None for p in ("openai", "anthropic", "gemini", "groq", "openrouter", "deepseek", "mistral")
    }
    return Settings(_env_file=None, **{**keys, **overrides})


@pytest.fixture
def settings(workspace_root: Path) -> Settings:
    return isolated_settings(
        workspace_root=workspace_root, command_allowlist="python,git,pytest", default_provider="ollama", max_steps=4
    )


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM(models=["qwen3:4b-instruct", "qwen2.5-coder:7b"])


@pytest.fixture
def services(settings: Settings, memory: FakeMemoryStore, llm: ScriptedLLM) -> Services:
    built = build_services(settings)
    built.providers.override("ollama", llm)
    built.memory = memory
    built.agent = AgentService(memory, built.providers, built.projects, max_steps=4, max_history=12)
    return built


def make_agent(memory, llm, root: Path, max_steps: int = 4, commands: bool = True) -> AgentService:
    providers = ProviderRegistry(isolated_settings())
    providers.override("ollama", llm)
    return AgentService(memory, providers, ProjectRegistry(root, ALLOW, 30), max_steps, 12, commands)
