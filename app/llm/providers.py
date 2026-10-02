"""Which model providers exist, which are set up, and one client per provider.

A provider is "configured" when its key is in the environment (Ollama needs none). The web app shows
every provider, so a missing key is a visible, fixable state rather than a hidden one.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.llm.anthropic_llm import AnthropicLLM
from app.llm.base import LLM, LLMUnavailableError
from app.llm.openai_compat import OpenAICompatLLM


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    kind: str  # "openai" (OpenAI-compatible API) or "anthropic"
    base_url: str | None
    key_env: str | None  # the environment variable that holds its key
    suggested_models: tuple[str, ...]
    local: bool = False
    token_param: str = "max_tokens"


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "ollama",
        "Ollama",
        "openai",
        None,
        None,
        ("qwen3:4b-instruct", "qwen3-coder:30b", "qwen2.5-coder:7b"),
        local=True,
    ),
    ProviderSpec(
        "anthropic",
        "Anthropic",
        "anthropic",
        None,
        "ANTHROPIC_API_KEY",
        ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "claude-fable-5-1"),
    ),
    ProviderSpec(
        "openai",
        "OpenAI",
        "openai",
        None,
        "OPENAI_API_KEY",
        ("gpt-5-mini", "gpt-5"),
        token_param="max_completion_tokens",
    ),
    ProviderSpec(
        "gemini",
        "Google Gemini",
        "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "GEMINI_API_KEY",
        ("gemini-2.5-flash", "gemini-2.5-pro"),
    ),
    ProviderSpec(
        "groq",
        "Groq",
        "openai",
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        ("openai/gpt-oss-120b", "qwen/qwen3-32b", "llama-3.3-70b-versatile"),
    ),
    ProviderSpec(
        "openrouter",
        "OpenRouter",
        "openai",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        ("qwen/qwen3-coder", "openai/gpt-5-mini", "deepseek/deepseek-chat"),
    ),
    ProviderSpec(
        "deepseek",
        "DeepSeek",
        "openai",
        "https://api.deepseek.com",
        "DEEPSEEK_API_KEY",
        ("deepseek-chat", "deepseek-reasoner"),
    ),
    ProviderSpec(
        "mistral",
        "Mistral",
        "openai",
        "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY",
        ("codestral-latest", "mistral-large-latest"),
    ),
    ProviderSpec("custom", "Custom server", "openai", None, "CODELOOP_CUSTOM_BASE_URL", ()),
)
PROVIDER_IDS = tuple(p.id for p in PROVIDERS)


@dataclass(frozen=True)
class ProviderStatus:
    spec: ProviderSpec
    configured: bool
    default_model: str
    hint: str  # what to do when it isn't configured


class ProviderRegistry:
    """Builds each provider's client on first use and keeps it for the life of the process."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._clients: dict[str, LLM] = {}

    def statuses(self) -> list[ProviderStatus]:
        return [self.status(p) for p in PROVIDERS]

    def status(self, spec: ProviderSpec) -> ProviderStatus:
        s = self._settings
        if spec.id == "ollama":
            return ProviderStatus(spec, True, s.ollama_model, "Install Ollama, then run: ollama pull " + s.ollama_model)
        if spec.id == "custom":
            configured = bool(s.custom_base_url and s.custom_model)
            hint = "Set CODELOOP_CUSTOM_BASE_URL and CODELOOP_CUSTOM_MODEL in .env"
            return ProviderStatus(spec, configured, s.custom_model or "", hint)
        key = getattr(s, f"{spec.id}_api_key")
        return ProviderStatus(spec, key is not None, getattr(s, f"{spec.id}_model"), f"Add {spec.key_env} to .env")

    def default_model(self, provider_id: str) -> str:
        return self.status(_spec(provider_id)).default_model

    def override(self, provider_id: str, llm: LLM) -> None:
        """Use this client for a provider (tests use it to plug in a fake model)."""
        self._clients[provider_id] = llm

    def get(self, provider_id: str) -> LLM:
        if provider_id in self._clients:
            return self._clients[provider_id]
        spec = _spec(provider_id)
        status = self.status(spec)
        if not status.configured:
            raise LLMUnavailableError(f"{provider_id} is not configured", f"{spec.label} isn't set up. {status.hint}.")
        client = self._build(spec)
        self._clients[provider_id] = client
        return client

    def _build(self, spec: ProviderSpec) -> LLM:
        s = self._settings
        if spec.kind == "anthropic":
            return AnthropicLLM(s.anthropic_api_key.get_secret_value(), s.max_tokens, s.anthropic_effort or None)
        if spec.id == "ollama":
            # Ollama ignores the key, but the client library needs some value.
            return OpenAICompatLLM("ollama", spec.label, "ollama", s.ollama_base_url, s.max_tokens)
        if spec.id == "custom":
            key = s.custom_api_key.get_secret_value() if s.custom_api_key else "none"
            return OpenAICompatLLM("custom", spec.label, key, s.custom_base_url, s.max_tokens)
        key = getattr(s, f"{spec.id}_api_key").get_secret_value()
        effort = s.openai_effort if spec.id == "openai" else None
        return OpenAICompatLLM(spec.id, spec.label, key, spec.base_url, s.max_tokens, effort, spec.token_param)


def _spec(provider_id: str) -> ProviderSpec:
    for spec in PROVIDERS:
        if spec.id == provider_id:
            return spec
    raise LLMUnavailableError(f"unknown provider {provider_id}", f"Unknown provider '{provider_id}'.")
