"""The provider-neutral shape of a conversation with a model.

The agent loop only ever sees these types. Each adapter (openai_compat.py, anthropic_llm.py) translates
them to and from its own API, so adding a provider never touches the agent.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call: a name, what it does, and a JSON Schema for its arguments."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0  # part of input_tokens that came from the provider's prompt cache

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_tokens += other.cached_tokens


@dataclass
class AssistantTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    # The provider's own content for this turn (e.g. Claude's thinking blocks), replayed unchanged on
    # the next call of the same run. Other adapters ignore it.
    raw: Any = None


# Messages in a run. Plain dicts keep them easy to build, log and test:
#   {"role": "user", "content": str}
#   {"role": "assistant", "content": str, "tool_calls": [ToolCall], "raw": provider payload or None}
#   {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}
Message = dict[str, Any]
ToolChoice = Literal["auto", "none"]


class LLMUnavailableError(Exception):
    """The model couldn't be reached or refused the request (network, key, credits, model name, outage).

    The exception message is for logs; `user_message` is safe to show in the browser.
    """

    def __init__(self, detail: str, user_message: str = "The model is unavailable right now"):
        super().__init__(detail)
        self.user_message = user_message


class ToolsUnsupportedError(LLMUnavailableError):
    """The chosen model can't call tools (common with small local models)."""


class LLM(Protocol):
    async def complete(
        self,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        tool_choice: ToolChoice = "auto",
    ) -> AssistantTurn: ...

    async def list_models(self) -> list[str] | None: ...


# Some local models write their reasoning or their tool calls as text instead of using the API's fields.
_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)
_TEXT_TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def strip_thinking(text: str) -> str:
    return _THINK.sub("", text).strip()


def parse_text_tool_calls(text: str, tool_names: set[str]) -> tuple[str, list[ToolCall]]:
    """Recover tool calls a model wrote as `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` text."""
    calls: list[ToolCall] = []
    for match in _TEXT_TOOL_CALL.finditer(text):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        name = data.get("name")
        args = data.get("arguments", data.get("parameters", {}))
        if name in tool_names and isinstance(args, dict):
            calls.append(ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=name, arguments=args))
    if not calls:
        return text, []
    return _TEXT_TOOL_CALL.sub("", text).strip(), calls


def parse_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string (OpenAI style) or an object; bad JSON becomes {}."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
