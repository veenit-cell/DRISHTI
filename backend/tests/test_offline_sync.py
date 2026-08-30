# ruff: noqa: E501

from datetime import UTC, datetime

import pytest

from app.offline_sync import OfflineCommand, OfflineSyncStore, SyncBatch

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def command(command_id: str, sequence: int, **kwargs) -> OfflineCommand:
    values = {"tenant_id": "t1", "workspace_id": "w1", **kwargs}
    return OfflineCommand(command_id=command_id, aggregate_id="task-1", sequence=sequence, kind="acknowledgement", client_timestamp=NOW, payload={}, **values)


def test_ordered_duplicate_partial_failure_and_conflict_retention():
    store = OfflineSyncStore()
    first = store.reconcile(SyncBatch(commands=[command("cmd1", 1), command("bad", 3), command("blocked", 4)]), "t1", "w1", NOW)
    assert [item["status"] for item in first["results"]] == ["accepted", "conflict", "conflict"]
    assert store.reconcile(SyncBatch(commands=[command("cmd1", 1)]), "t1", "w1", NOW)["results"][0]["status"] == "replayed"
    assert store.reconcile(SyncBatch(commands=[command("cmd2", 2)]), "t1", "w1", NOW)["results"][0]["status"] == "accepted"


def test_scope_and_batch_bound():
    store = OfflineSyncStore()
    assert store.reconcile(SyncBatch(commands=[command("cross", 1, tenant_id="other")]), "t1", "w1", NOW)["results"][0]["status"] == "rejected"
    with pytest.raises(ValueError):
        SyncBatch(commands=[command(str(index), index) for index in range(1, 22)])
