"""Request and response shapes for the HTTP API.

FastAPI validates every request against these before our code runs, and uses them for the docs at /docs.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.prompts import TEST_METHODS

# A project id becomes part of a Hindsight bank id, so only a safe character set is allowed.
PROJECT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,39}$"
Mode = Literal["ask", "write", "debug", "review", "test"]
TestMethod = Literal[tuple(TEST_METHODS)]  # type: ignore[valid-type]


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=24_000)


class AgentRunBody(BaseModel):
    project_id: str | None = Field(default=None, pattern=PROJECT_ID_PATTERN)
    message: str = Field(min_length=1, max_length=40_000, description="The question, with any pasted code")
    history: list[Turn] = Field(default_factory=list, max_length=40)
    mode: Mode = "ask"
    test_methods: list[TestMethod] = Field(default_factory=list, max_length=len(TEST_METHODS))
    provider: str = Field(default="", max_length=40, description="Provider id; empty for the server default")
    model: str | None = Field(default=None, max_length=200)
    use_memory: bool = True
    allow_edits: bool = False
    allow_commands: bool = False


class MemoryOut(BaseModel):
    text: str
    type: str | None = None
    occurred_at: str | None = None


class MemoriesResponse(BaseModel):
    memories: list[MemoryOut]
    total: int


class ProviderOut(BaseModel):
    id: str
    label: str
    kind: str
    configured: bool
    local: bool
    default_model: str
    models: list[str]
    installed: bool | None = Field(default=None, description="For local servers: whether they answered")
    hint: str


class ProjectOut(BaseModel):
    id: str
    name: str
    is_git: bool
    branch: str | None = None
    head: str | None = None
    subject: str | None = None
    committed_at: str | None = None


class ProjectStatus(BaseModel):
    project: ProjectOut
    notes: int | None = Field(description="Facts in this project's memory; null when memory is unreachable")
    commits_since: int | None = Field(default=None, description="Commits since the `since` commit, if given")


class CloneBody(BaseModel):
    git_url: str = Field(max_length=500, examples=["https://github.com/satyaidk/learnloop.git"])
    name: str | None = Field(default=None, max_length=60)


class LearnResponse(BaseModel):
    files_scanned: int
    characters: int
    head: str | None
    branch: str | None
    learned_at: str


class AppInfo(BaseModel):
    version: str = "0.1.0"
    default_provider: str
    workspace_root: str
    max_steps: int
    max_history_messages: int
    commands_enabled: bool
    command_allowlist: list[str]
    test_methods: dict[str, str]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    memory: bool
