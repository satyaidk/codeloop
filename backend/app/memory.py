"""Long-term memory: what the agent knows about each project, kept in Hindsight.

`MemoryStore` is an interface (a typing.Protocol); the rest of the app never talks to Hindsight directly.
Tests use an in-memory fake, and changing memory vendors would only change this file.

Each project gets its own Hindsight *bank*, so facts about one codebase never leak into another.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from hindsight_client import Hindsight
from hindsight_client_api.exceptions import NotFoundException

from app.config import Settings

logger = logging.getLogger(__name__)

# Steers what Hindsight extracts on retain(). Without it, it would store every detail of every chat.
RETAIN_MISSION = (
    "You are the long-term memory of a coding agent that works inside one software project. Extract durable "
    "facts about the codebase and how the developer works on it: architecture and what each module or file is "
    "responsible for, where things live (exact file paths), languages, frameworks and versions, the commands "
    "that build, run, lint and test it and whether they passed, coding conventions, known bugs and their root "
    "causes, fixes that were applied (file and what changed), design decisions and why, and the developer's "
    "preferences. Keep file paths, function names and commands exact. Ignore greetings, generic programming "
    "explanations and anything that only mattered for a moment."
)

REFLECT_MISSION = (
    "You are a senior engineer briefing a teammate who is new to this codebase. Be specific and concise, "
    "ground every statement in the stored facts, and say plainly when something isn't known yet."
)


@dataclass
class Memory:
    text: str
    type: str | None = None  # "world" | "experience" | "observation"
    occurred_at: str | None = None


@dataclass
class Reflection:
    text: str
    structured: dict[str, Any] | None = None


class MemoryStore(Protocol):
    async def remember(self, scope: str, content: str, context: str) -> None: ...

    async def recall(self, scope: str, query: str) -> list[Memory]: ...

    async def list_all(self, scope: str, limit: int = 200) -> list[Memory]: ...

    async def count(self, scope: str) -> int: ...

    async def forget(self, scope: str) -> None: ...

    async def reflect(self, scope: str, question: str, schema: dict[str, Any] | None = None) -> Reflection: ...

    async def is_healthy(self) -> bool: ...

    async def close(self) -> None: ...


# Hindsight appends annotations to a fact after " | ": labelled ones ("| When: 2026-09-28") and, in newer
# versions, the reason the fact matters ("| To prevent leakage between users"). They help the model (prompts
# keep them) but read as clutter to a person.
_SEPARATOR = re.compile(r"\s+\|\s+")


def display_text(text: str) -> str:
    """A fact as a person should read it: everything from the first annotation separator on is removed. A " | "
    inside backticks is part of the fact (a shell pipe in a command), so it is kept."""
    for match in _SEPARATOR.finditer(text):
        if text.count("`", 0, match.start()) % 2 == 0:
            return text[: match.start()].strip()
    return text.strip()


def make_hindsight_client(settings: Settings) -> Hindsight:
    """One place that builds the client, so the server and the scripts pass the same URL and key."""
    key = settings.hindsight_api_key.get_secret_value() if settings.hindsight_api_key else None
    return Hindsight(base_url=settings.hindsight_url, api_key=key)


@dataclass
class HindsightMemoryStore:
    client: Hindsight
    bank_prefix: str = "codeloop"
    recall_budget: str = "mid"
    recall_max_tokens: int = 2500
    recall_max_notes: int = 8
    _configured_banks: set[str] = field(default_factory=set)

    def bank_id(self, scope: str) -> str:
        return f"{self.bank_prefix}-{scope}"

    async def _ensure_bank(self, scope: str) -> str:
        """Set the bank's missions once per process (create_bank is create-or-update, so this is safe)."""
        bank_id = self.bank_id(scope)
        if bank_id not in self._configured_banks:
            await self.client.acreate_bank(bank_id, retain_mission=RETAIN_MISSION, reflect_mission=REFLECT_MISSION)
            self._configured_banks.add(bank_id)
        return bank_id

    async def remember(self, scope: str, content: str, context: str) -> None:
        bank_id = await self._ensure_bank(scope)
        # retain_async: Hindsight extracts facts in the background; this call returns once it's queued.
        await self.client.aretain(
            bank_id=bank_id, content=content, context=context, timestamp=datetime.now(UTC), retain_async=True
        )

    async def recall(self, scope: str, query: str) -> list[Memory]:
        bank_id = await self._ensure_bank(scope)
        response = await self.client.arecall(
            bank_id=bank_id, query=query, budget=self.recall_budget, max_tokens=self.recall_max_tokens
        )
        best = response.results[: self.recall_max_notes]  # ranked, most relevant first
        return [Memory(text=r.text, type=r.type, occurred_at=r.occurred_start) for r in best]

    async def list_all(self, scope: str, limit: int = 200) -> list[Memory]:
        bank_id = await self._ensure_bank(scope)
        response = await self.client.alist_memories(bank_id=bank_id, limit=limit)
        return [
            Memory(text=item.text, type=item.fact_type, occurred_at=item.occurred_start or item.mentioned_at)
            for item in response.items
            if item.text and item.state != "invalidated"
        ]

    async def count(self, scope: str) -> int:
        bank_id = await self._ensure_bank(scope)
        response = await self.client.alist_memories(bank_id=bank_id, limit=1)
        return response.total or 0

    async def forget(self, scope: str) -> None:
        bank_id = self.bank_id(scope)
        await self._cancel_pending(bank_id)
        try:
            await self.client.adelete_bank(bank_id)
        except NotFoundException:
            pass  # nothing stored yet, so nothing to forget
        self._configured_banks.discard(bank_id)

    async def _cancel_pending(self, bank_id: str) -> None:
        """Stop note-taking still queued for this bank. Deleting a bank alone leaves a running job going, and on a
        local model one project scan can keep the model busy for many minutes."""
        for status in ("pending", "processing"):
            try:
                listed = await self.client.operations.list_operations(bank_id, status=status, limit=100)
            except NotFoundException:
                return
            except Exception:
                logger.warning("couldn't list %s memory jobs for %s", status, bank_id, exc_info=True)
                continue
            for op in listed.operations:
                try:
                    await self.client.operations.cancel_operation(bank_id, op.id)
                except Exception:
                    logger.warning("couldn't cancel memory job %s", op.id, exc_info=True)

    async def reflect(self, scope: str, question: str, schema: dict[str, Any] | None = None) -> Reflection:
        bank_id = await self._ensure_bank(scope)
        response = await self.client.areflect(bank_id=bank_id, query=question, budget="mid", response_schema=schema)
        return Reflection(text=response.text, structured=response.structured_output)

    async def is_healthy(self) -> bool:
        try:
            await self.client.aget_version()
            return True
        except Exception as exc:  # a health check reports failure; it never raises
            # One line, not a traceback: while Hindsight boots this runs every 30 seconds.
            logger.warning("Hindsight isn't reachable: %s", exc or type(exc).__name__)
            return False

    async def close(self) -> None:
        await self.client.aclose()
