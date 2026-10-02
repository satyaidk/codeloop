"""The Hindsight adapter, against a stand-in for the Hindsight client (no server needed)."""

from types import SimpleNamespace
from typing import Any, cast

from hindsight_client_api.exceptions import NotFoundException

from app.memory import HindsightMemoryStore, display_text


def store_for(client: "FakeClient", prefix: str = "codeloop") -> HindsightMemoryStore:
    return HindsightMemoryStore(client=cast(Any, client), bank_prefix=prefix)


class FakeOperations:
    def __init__(self, jobs: dict[str, list[str]]):
        self.jobs = jobs  # status -> operation ids
        self.cancelled: list[str] = []

    async def list_operations(self, bank_id: str, status: str = "", limit: int = 100):
        return SimpleNamespace(operations=[SimpleNamespace(id=i) for i in self.jobs.get(status, [])])

    async def cancel_operation(self, bank_id: str, operation_id: str):
        self.cancelled.append(operation_id)


class FakeClient:
    def __init__(self, jobs=None, bank_exists=True):
        self.operations = FakeOperations(jobs or {})
        self.deleted: list[str] = []
        self.bank_exists = bank_exists
        self.calls: list[str] = []

    async def adelete_bank(self, bank_id):
        self.calls.append("delete")
        if not self.bank_exists:
            raise NotFoundException(status=404, reason="Not Found")
        self.deleted.append(bank_id)

    async def acreate_bank(self, bank_id: str, **missions: str):
        self.calls.append(f"create {bank_id}")


async def test_forget_cancels_queued_and_running_note_taking_before_deleting():
    client = FakeClient(jobs={"pending": ["op-1"], "processing": ["op-2"]})
    store = store_for(client)

    await store.forget("shop-api")

    assert client.operations.cancelled == ["op-1", "op-2"]
    assert client.deleted == ["codeloop-shop-api"]


async def test_forget_a_project_never_stored_is_fine():
    store = store_for(FakeClient(bank_exists=False))
    await store.forget("never-used")  # no exception


async def test_banks_are_configured_once_and_again_after_forget():
    client = FakeClient()
    store = store_for(client)

    await store._ensure_bank("api")
    await store._ensure_bank("api")
    await store.forget("api")
    await store._ensure_bank("api")

    assert client.calls == ["create codeloop-api", "delete", "create codeloop-api"]


def test_display_text_drops_hindsight_annotations():
    assert display_text("Tests run with pytest | When: 2026-10-01 | Involving: developer") == "Tests run with pytest"
    assert display_text("Each learner has a bank | To prevent leakage between users") == "Each learner has a bank"
    assert display_text("No annotations here.") == "No annotations here."


def test_display_text_keeps_a_pipe_inside_a_command():
    fact = "Logs are read with `docker logs app | grep ERROR` | To find failures quickly"
    assert display_text(fact) == "Logs are read with `docker logs app | grep ERROR`"
