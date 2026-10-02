"""Application settings, loaded from environment variables (or a local .env file).

Every tunable lives in this one typed class, so the same code runs on a laptop, in Docker and in CI
with nothing but different environment variables.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _key(name: str) -> Any:
    # Provider keys use their standard names (OPENAI_API_KEY, ...) so they work with other tools too;
    # a CODELOOP_ prefixed copy is accepted as well.
    return Field(default=None, validation_alias=AliasChoices(name, f"CODELOOP_{name}"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CODELOOP_", extra="ignore")

    # --- Workspace: the folder whose sub-folders are the projects the agent can open ---
    workspace_root: Path = Path("workspace")
    # Commands the agent may run when a chat allows it. The first word of a command must be one of these.
    command_allowlist: str = (
        "pytest,python,python3,py,npm,npx,pnpm,yarn,node,bun,deno,go,cargo,mvn,gradle,gradlew,dotnet,"
        "java,ruff,mypy,black,flake8,pylint,bandit,eslint,tsc,vitest,jest,playwright,make,git"
    )
    command_timeout_seconds: int = 180
    # Set to false to switch off command running for every chat, whatever the web app asks for.
    allow_commands: bool = True

    # --- Who may talk to the server. Requests with any other Host header are refused, which blocks
    # DNS-rebinding attacks from web pages you visit. "*" switches the check off. ---
    allowed_hosts: str = "localhost,127.0.0.1,[::1]"

    # --- Hindsight (long-term memory) ---
    hindsight_url: str = "http://localhost:8888"
    hindsight_api_key: SecretStr | None = None
    bank_prefix: str = "codeloop"
    recall_budget: str = "mid"  # "low" | "mid" | "high": how hard recall searches
    recall_max_tokens: int = 2500
    recall_max_notes: int = 8

    # --- Models ---
    default_provider: str = "ollama"
    max_tokens: int = 8000  # per model call
    max_steps: int = 12  # tool-using steps per question before the agent must answer
    max_history_messages: int = 12  # short-term memory: recent turns sent by the browser
    openai_effort: str | None = "low"  # reasoning effort for OpenAI reasoning models; empty to omit
    anthropic_effort: str = "high"  # low | medium | high | xhigh | max

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:4b-instruct"

    openai_api_key: SecretStr | None = _key("OPENAI_API_KEY")
    openai_model: str = "gpt-5-mini"
    anthropic_api_key: SecretStr | None = _key("ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-opus-5-5"
    gemini_api_key: SecretStr | None = _key("GEMINI_API_KEY")
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: SecretStr | None = _key("GROQ_API_KEY")
    groq_model: str = "openai/gpt-oss-120b"
    openrouter_api_key: SecretStr | None = _key("OPENROUTER_API_KEY")
    openrouter_model: str = "qwen/qwen3-coder"
    deepseek_api_key: SecretStr | None = _key("DEEPSEEK_API_KEY")
    deepseek_model: str = "deepseek-chat"
    mistral_api_key: SecretStr | None = _key("MISTRAL_API_KEY")
    mistral_model: str = "codestral-latest"

    # Any other OpenAI-compatible server: LM Studio, vLLM, llama.cpp, Together, ...
    custom_base_url: str | None = None
    custom_api_key: SecretStr | None = None
    custom_model: str | None = None

    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def command_allowlist_set(self) -> frozenset[str]:
        return frozenset(c.strip().lower() for c in self.command_allowlist.split(",") if c.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
