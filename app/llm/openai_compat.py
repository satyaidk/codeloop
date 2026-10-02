"""Any model behind an OpenAI-compatible chat API.

That covers OpenAI itself and, through their compatible endpoints, Ollama on your own computer, Google
Gemini, Groq, OpenRouter, DeepSeek, Mistral and servers like LM Studio or vLLM. Only the base URL, key
and model name differ.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import openai

from app.llm.base import (
    AssistantTurn,
    LLMUnavailableError,
    Message,
    ToolCall,
    ToolChoice,
    ToolSpec,
    ToolsUnsupportedError,
    Usage,
    parse_arguments,
    parse_text_tool_calls,
    strip_thinking,
)

logger = logging.getLogger(__name__)

REFUSAL_REPLY = "The model declined to answer this one. Try rephrasing, or pick a different model."


class OpenAICompatLLM:
    def __init__(
        self,
        provider_id: str,
        label: str,
        api_key: str,
        base_url: str | None,
        max_tokens: int,
        effort: str | None = None,
        token_param: str = "max_tokens",
    ):
        # Local models can take minutes on a laptop; give them time instead of failing at 10 minutes.
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url or None, timeout=900)
        self._provider_id = provider_id
        self._label = label
        self._server = base_url or "https://api.openai.com/v1"
        self._max_tokens = max_tokens
        self._effort = effort
        self._token_param = token_param

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
            "messages": [{"role": "system", "content": system}, *to_openai_messages(messages)],
            self._token_param: self._max_tokens,
        }
        if tools:
            request["tools"] = [to_openai_tool(t) for t in tools]
            request["tool_choice"] = tool_choice
        if self._effort:
            request["reasoning_effort"] = self._effort
        try:
            response = await self._client.chat.completions.create(**request)
        except openai.APIConnectionError as exc:
            hint = " Check that Ollama is running." if self._provider_id == "ollama" else ""
            raise LLMUnavailableError(
                f"Can't reach {self._server}: {exc}", f"Can't reach {self._label} at {self._server}.{hint}"
            ) from exc
        except openai.NotFoundError as exc:
            pull = f" Download it with: ollama pull {model}" if self._provider_id == "ollama" else ""
            raise LLMUnavailableError(
                f"Model {model!r} not found: {exc}", f"{self._label} has no model called '{model}'.{pull}"
            ) from exc
        except openai.AuthenticationError as exc:
            raise LLMUnavailableError(
                f"{self._label} rejected the API key",
                f"{self._label} rejected the API key. Check it in your .env file.",
            ) from exc
        except openai.RateLimitError as exc:
            if exc.code in ("insufficient_quota", "credit_balance_exhausted") or exc.type == "insufficient_quota":
                raise LLMUnavailableError(
                    f"{self._label} has no credits: {exc}", f"Your {self._label} account has no credits left."
                ) from exc
            raise LLMUnavailableError(
                f"Rate limit: {exc}", f"{self._label} is rate limiting requests. Wait a minute and try again."
            ) from exc
        except openai.BadRequestError as exc:
            text = str(exc).lower()
            if (
                "does not support tools" in text
                or "tool use is not supported" in text
                or "tools are not supported" in text
            ):
                raise ToolsUnsupportedError(
                    f"{model} can't use tools: {exc}", f"'{model}' can't use tools, so it answers without reading code."
                ) from exc
            if "context" in text and ("length" in text or "window" in text or "too long" in text):
                raise LLMUnavailableError(
                    f"Context too long: {exc}",
                    "The conversation is too long for this model. Start a new chat or lower the history length.",
                ) from exc
            raise LLMUnavailableError(
                f"Bad request: {exc}", f"{self._label} rejected the request: {_short(exc)}"
            ) from exc
        except openai.APIError as exc:  # the SDK already retried 5xx errors
            raise LLMUnavailableError(f"Model request failed: {exc}", f"{self._label} failed: {_short(exc)}") from exc

        choice = response.choices[0].message
        if getattr(choice, "refusal", None):
            return AssistantTurn(text=REFUSAL_REPLY, usage=_usage(response))
        text = strip_thinking(choice.content or "")
        calls = [
            ToolCall(id=c.id or f"call_{i}", name=c.function.name, arguments=parse_arguments(c.function.arguments))
            for i, c in enumerate(choice.tool_calls or [])
            if getattr(c, "function", None)
        ]
        if not calls and tools:
            text, calls = parse_text_tool_calls(text, {t.name for t in tools})
        return AssistantTurn(text=text, tool_calls=calls, usage=_usage(response))

    async def list_models(self) -> list[str] | None:
        """The server's models, or None when it can't be asked (offline, or no listing endpoint)."""
        try:
            page = await self._client.with_options(timeout=4, max_retries=0).models.list()
        except Exception:
            logger.info("couldn't list models for %s", self._provider_id, exc_info=True)
            return None
        return sorted(m.id for m in page.data)


def to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
    }


def to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                entry["tool_calls"] = [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                    for c in m["tool_calls"]
                ]
            elif entry["content"] is None:
                entry["content"] = ""
            out.append(entry)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    return out


def _usage(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    details = getattr(usage, "prompt_tokens_details", None)
    return Usage(
        input_tokens=usage.prompt_tokens or 0,
        output_tokens=usage.completion_tokens or 0,
        cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
    )


def _short(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    return message[:300]
