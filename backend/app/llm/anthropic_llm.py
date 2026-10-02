"""Claude, through Anthropic's own Messages API and SDK.

Differences from the OpenAI-compatible adapter that matter for an agent loop:
- Claude's turns can carry thinking blocks. Within one run they are replayed exactly as received
  (the conversation is append-only), which keeps them valid and keeps the prompt cache warm.
- Top-level automatic prompt caching is on, so each tool step re-reads the previous steps from the
  cache instead of paying for them again.
- On models that support it, a declined request is retried server-side on Anthropic's recommended
  fallback model (`fallbacks: "default"`).
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.llm.base import (
    AssistantTurn,
    LLMUnavailableError,
    Message,
    ToolCall,
    ToolChoice,
    ToolSpec,
    Usage,
    parse_arguments,
)

logger = logging.getLogger(__name__)

REFUSAL_REPLY = "Claude declined to help with this request. Try rephrasing it, or pick a different model."
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept `fallbacks: "default"` and the `effort` setting.
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
_EFFORT_PREFIXES = ("claude-opus-", "claude-fable-", "claude-sonnet-5", "claude-sonnet-4-6", "claude-mythos-")
# Content blocks of a declined partial answer that must not be replayed or acted on.
_DROP_BEFORE_FALLBACK = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}


class AnthropicLLM:
    def __init__(self, api_key: str, max_tokens: int, effort: str | None = "high"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._max_tokens = max_tokens
        self._effort = effort

    async def complete(
        self,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: ToolChoice = "auto",
    ) -> AssistantTurn:
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": to_anthropic_messages(messages),
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            request["tools"] = [to_anthropic_tool(t) for t in tools]
            request["tool_choice"] = {"type": tool_choice}
        if self._effort and model.startswith(_EFFORT_PREFIXES):
            request["output_config"] = {"effort": self._effort}
        if model in _FALLBACK_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        try:
            response = await self._client.beta.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailableError(
                "Anthropic rejected the API key", "Anthropic rejected the API key. Check ANTHROPIC_API_KEY in .env."
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMUnavailableError(f"Permission denied: {exc}", f"This Anthropic key can't use '{model}'.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMUnavailableError(f"Model not found: {exc}", f"Anthropic has no model called '{model}'.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError(
                f"Rate limit: {exc}", "Anthropic is rate limiting requests. Wait a minute and try again."
            ) from exc
        except anthropic.BadRequestError as exc:
            text = str(exc).lower()
            if "credit balance" in text:
                raise LLMUnavailableError(
                    f"No credits: {exc}", "Your Anthropic account has no credits left. Add some in the Claude Console."
                ) from exc
            if "prompt is too long" in text or ("context" in text and "exceed" in text):
                raise LLMUnavailableError(
                    f"Too long: {exc}", "The conversation is too long for this model. Start a new chat."
                ) from exc
            raise LLMUnavailableError(
                f"Bad request: {exc}", f"Anthropic rejected the request: {exc.message[:300]}"
            ) from exc
        except anthropic.APIStatusError as exc:  # 5xx and overloaded, after the SDK's own retries
            raise LLMUnavailableError(
                f"Anthropic error {exc.status_code}: {exc}", "Claude is overloaded or unavailable. Try again shortly."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(f"Can't reach Anthropic: {exc}", "Can't reach the Anthropic API.") from exc

        usage = _usage(response.usage)
        if response.stop_reason == "refusal":
            return AssistantTurn(text=REFUSAL_REPLY, usage=usage)
        content = replayable_content(list(response.content))
        text = "\n\n".join(b.text for b in content if b.type == "text" and b.text).strip()
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=parse_arguments(b.input)) for b in content if b.type == "tool_use"
        ]
        return AssistantTurn(text=text, tool_calls=calls, usage=usage, raw=content)

    async def list_models(self) -> list[str] | None:
        return None  # the suggestions in providers.py are enough; any model id can be typed


def replayable_content(content: list[Any]) -> list[Any]:
    """After a mid-answer fallback, drop the declined model's thinking and tool calls before the switch."""
    last = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    return [b for i, b in enumerate(content) if i > last or b.type not in _DROP_BEFORE_FALLBACK]


def to_anthropic_tool(tool: ToolSpec) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert to Claude's shape: tool results are user-turn blocks, and consecutive user content merges."""
    out: list[dict[str, Any]] = []

    def add_user_blocks(blocks: list[dict[str, Any]]) -> None:
        if out and out[-1]["role"] == "user":
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": "user", "content": blocks})

    for m in messages:
        if m["role"] == "user":
            add_user_blocks([{"type": "text", "text": m["content"]}])
        elif m["role"] == "tool":
            add_user_blocks(
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": m["tool_call_id"],
                        "content": m["content"] or "(no output)",
                        "is_error": bool(m.get("is_error")),
                    }
                ]
            )
        elif m["role"] == "assistant":
            if m.get("raw") is not None:
                out.append({"role": "assistant", "content": m["raw"]})  # this run's own turn, unchanged
                continue
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for call in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
    return out


def _usage(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return Usage(
        input_tokens=(usage.input_tokens or 0) + cached + written,
        output_tokens=usage.output_tokens or 0,
        cached_tokens=cached,
    )
