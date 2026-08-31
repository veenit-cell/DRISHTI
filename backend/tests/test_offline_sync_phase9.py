# ruff: noqa: E501

from datetime import UTC, datetime, timedelta

from app.offline_sync import OfflineCommand, OfflineSyncStore, SyncBatch

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def command(command_id: str, sequence: int, *, client_timestamp: datetime = NOW, tenant_id: str = "t1", workspace_id: str = "w1", payload: dict | None = None) -> OfflineCommand:
    return OfflineCommand(
        command_id=command_id,
        aggregate_id="task-1",
        sequence=sequence,
        kind="acknowledgement",
        client_timestamp=client_timestamp,
        payload=payload or {"status": "acknowledged"},
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )


def test_duplicate_is_replayed_idempotently_and_content_change_is_rejected():
    store = OfflineSyncStore()
    first = store.reconcile(SyncBatch(commands=[command("cmd-1", 1)]), "t1", "w1", NOW)
    replay = store.reconcile(SyncBatch(commands=[command("cmd-1", 1)]), "t1", "w1", NOW + timedelta(minutes=1))
    changed = store.reconcile(SyncBatch(commands=[command("cmd-1", 1, payload={"status": "completed"})]), "t1", "w1", NOW + timedelta(minutes=2))

    assert first["reconciliation"]["accepted"] == 1
    assert replay["results"][0]["status"] == "replayed"
    assert replay["results"][0]["server_timestamp"] == first["results"][0]["server_timestamp"]
    assert changed["results"][0]["status"] == "rejected"


def test_out_of_order_commands_are_explained_and_can_reconnect_in_order():
    store = OfflineSyncStore()
    out_of_order = store.reconcile(SyncBatch(commands=[command("cmd-2", 2)]), "t1", "w1", NOW)
    reconnect = store.reconcile(SyncBatch(commands=[command("cmd-1", 1), command("cmd-2", 2)]), "t1", "w1", NOW + timedelta(minutes=1))

    assert out_of_order["results"][0]["status"] == "conflict"
    assert out_of_order["results"][0]["expected_sequence"] == 1
    assert out_of_order["results"][0]["conflict_explanation"]
    assert out_of_order["reconciliation"]["blocked"] == 1
    assert [item["status"] for item in reconnect["results"]] == ["accepted", "accepted"]
    assert reconnect["reconciliation"]["expected_sequence_number"] == {"task-1": 3}


def test_rejected_commands_are_counted_and_never_change_sequence():
    store = OfflineSyncStore()
    rejected = store.reconcile(SyncBatch(commands=[command("cross-tenant", 1, tenant_id="other")]), "t1", "w1", NOW)
    rejected_workspace = store.reconcile(SyncBatch(commands=[command("cross-workspace", 1, workspace_id="other")]), "t1", "w1", NOW)
    accepted = store.reconcile(SyncBatch(commands=[command("cmd-1", 1)]), "t1", "w1", NOW)

    assert rejected["results"][0]["status"] == "rejected"
    assert rejected["results"][0]["conflict_explanation"]
    assert rejected["reconciliation"]["rejected"] == 1
    assert rejected_workspace["results"][0]["status"] == "rejected"
    assert accepted["results"][0]["status"] == "accepted"


def test_older_offline_timestamp_is_blocked_without_overwriting_newer_state():
    store = OfflineSyncStore()
    store.reconcile(SyncBatch(commands=[command("cmd-1", 1, client_timestamp=NOW + timedelta(hours=1))]), "t1", "w1", NOW)
    stale = store.reconcile(SyncBatch(commands=[command("cmd-2", 2, client_timestamp=NOW)]), "t1", "w1", NOW + timedelta(minutes=1))

    assert stale["results"][0]["status"] == "blocked"
    assert stale["results"][0]["reason"] == "older client timestamp than reconciled state"
    assert stale["reconciliation"]["blocked"] == 1
    assert stale["reconciliation"]["expected_sequence_number"] == {"task-1": 2}


def test_same_command_id_isolated_between_scopes():
    store = OfflineSyncStore()
    first = store.reconcile(SyncBatch(commands=[command("shared-id", 1)]), "t1", "w1", NOW)
    other_scope = store.reconcile(SyncBatch(commands=[command("shared-id", 1, tenant_id="t2", workspace_id="w2")]), "t2", "w2", NOW)

    assert first["results"][0]["status"] == "accepted"
    assert other_scope["results"][0]["status"] == "accepted"
    assert other_scope["results"][0]["status"] != "replayed"
