"""Test doubles for Hindsight and the model providers.

They implement the same interfaces as the real classes, so the agent can't tell the difference, but they
run instantly, cost nothing and need no network.
"""

from __future__ import annotations

from typing import Any

from app.llm.base import AssistantTurn, LLMUnavailableError, Message, ToolCall, ToolSpec, Usage
from app.memory import Memory, Reflection


class FakeMemoryStore:
    def __init__(self, healthy: bool = True, fail_recall: bool = False):
        self.banks: dict[str, list[str]] = {}
        self.contexts: list[str] = []
        self.healthy = healthy
        self.fail_recall = fail_recall
        self.reflect_result = Reflection(text="", structured=None)
        self.closed = False

    async def remember(self, scope: str, content: str, context: str) -> None:
        self.banks.setdefault(scope, []).append(content)
        self.contexts.append(context)

    async def recall(self, scope: str, query: str) -> list[Memory]:
        if self.fail_recall:
            raise ConnectionError("hindsight is down")
        # Crude word overlap is enough to exercise the flow; real Hindsight does much more.
        words = {w.lower().strip("?.,!`") for w in query.split() if len(w) > 3}
        return [Memory(text=m) for m in self.banks.get(scope, []) if words & set(m.lower().replace("`", "").split())]

    async def list_all(self, scope: str, limit: int = 200) -> list[Memory]:
        if self.fail_recall:
            raise ConnectionError("hindsight is down")
        return [Memory(text=m) for m in self.banks.get(scope, [])][:limit]

    async def count(self, scope: str) -> int:
        return len(self.banks.get(scope, []))

    async def forget(self, scope: str) -> None:
        self.banks.pop(scope, None)

    async def reflect(self, scope: str, question: str, schema: dict[str, Any] | None = None) -> Reflection:
        return self.reflect_result

    async def is_healthy(self) -> bool:
        return self.healthy

    async def close(self) -> None:
        self.closed = True


class ScriptedLLM:
    """Plays back a script of turns and records every call it receives.

    Each script item is an AssistantTurn, or an Exception to raise. When the script runs out it answers "Done.".
    """

    def __init__(self, *script: AssistantTurn | Exception, models: list[str] | None = None):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.models = models

    async def complete(
        self, model: str, system: str, messages: list[Message], tools: list[ToolSpec], tool_choice: str = "auto"
    ) -> AssistantTurn:
        self.calls.append(
            {
                "model": model,
                "system": system,
                "messages": list(messages),
                "tools": [t.name for t in tools],
                "tool_choice": tool_choice,
            }
        )
        if not self.script:
            return AssistantTurn(text="Done.", usage=Usage(10, 5))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def list_models(self) -> list[str] | None:
        return self.models


def call(name: str, **arguments: Any) -> AssistantTurn:
    """A turn in which the model calls one tool."""
    return AssistantTurn(
        text="", tool_calls=[ToolCall(id=f"c-{name}", name=name, arguments=arguments)], usage=Usage(100, 20, 40)
    )


def answer(text: str) -> AssistantTurn:
    return AssistantTurn(text=text, usage=Usage(120, 30, 60))


DOWN = LLMUnavailableError("connection refused", "Can't reach Ollama.")
