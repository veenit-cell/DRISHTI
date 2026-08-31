from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.offline_sync import OfflineCommand, SyncBatch
from app.operations import InMemoryOperationsStore
from app.updates import publish_communication_gap_event


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def make_client() -> TestClient:
    return TestClient(
        create_app(
            Settings(app_environment="test", dev_identity_enabled=True),
            operations_store=InMemoryOperationsStore(),
            clock=FixedClock(NOW),
        ),
        raise_server_exceptions=False,
    )


def operator_headers(key: str, correlation_id: str = "phase5-workflow") -> dict[str, str]:
    return {
        "X-Dev-Identity": "operator",
        "Idempotency-Key": key,
        "X-Correlation-ID": correlation_id,
    }


def test_complete_scoped_workflow_publishes_and_reconciles_without_duplicates() -> None:
    client = make_client()

    assert client.get("/api/v1/command/operational-snapshot").status_code == 401
    assert client.get(
        "/api/v1/command/operational-snapshot",
        headers=operator_headers("snapshot-empty"),
    ).status_code == 200

    incident = client.post(
        "/api/v1/command/incidents",
        headers=operator_headers("incident-create"),
        json={
            "name": "North district flood",
            "hazard_type": "flood",
            "severity": "high",
            "summary": "River corridor impacted",
            "event_time": NOW.isoformat(),
        },
    )
    assert incident.status_code == 201
    incident_id = incident.json()["incident_id"]
    assert client.post(
        f"/api/v1/command/incidents/{incident_id}/roles",
        headers=operator_headers("incident-role"),
        json={"role": "incident_commander", "actor_id": "operator"},
    ).status_code == 200
    assert client.patch(
        f"/api/v1/command/incidents/{incident_id}",
        headers=operator_headers("incident-activate"),
        json={"status": "active", "phase": "size_up"},
    ).status_code == 200

    replay = client.post(
        "/api/v1/decision-loop/demo/replay",
        headers=operator_headers("incident-signal-replay"),
    )
    assert replay.status_code == 200
    recommendation = client.post(
        "/api/v1/decision-loop/recommendations",
        headers=operator_headers("recommendation-create"),
    )
    assert recommendation.status_code == 200
    recommendation_body = recommendation.json()
    resource_id = recommendation_body["compatible_resources"][0]["id"]

    decision_path = f"/api/v1/decision-loop/recommendations/{recommendation_body['id']}/decision"
    approval_payload = {"decision": "approve", "resource_id": resource_id}
    approved = client.post(
        decision_path,
        headers=operator_headers("recommendation-approve"),
        json=approval_payload,
    )
    duplicate_approval = client.post(
        decision_path,
        headers=operator_headers("recommendation-approve"),
        json=approval_payload,
    )
    assert approved.status_code == duplicate_approval.status_code == 200
    assert approved.json()["queue_item_id"] == duplicate_approval.json()["queue_item_id"]
    queue_id = approved.json()["queue_item_id"]

    route = client.post(
        "/api/v1/route-observations",
        headers=operator_headers("route-observation"),
        json={
            "destination": "North Sector",
            "state": "passable",
            "observed_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "source": "commander_confirmation",
        },
    )
    assert route.status_code == 201

    task = client.post(
        f"/api/v1/response-queue/{queue_id}/approve",
        headers=operator_headers("task-assignment"),
        json={
            "resource_id": resource_id,
            "approved": True,
            "approval_note": "Commander approved assignment",
        },
    )
    assert task.status_code == 200
    task_body = task.json()

    snapshot = client.get(
        "/api/v1/command/operational-snapshot",
        headers=operator_headers("snapshot-final"),
    )
    assert snapshot.status_code == 200
    snapshot_body = snapshot.json()
    assert snapshot_body["active_incident"]["incident_id"] == incident_id
    assert snapshot_body["active_tasks"]["count"] == 1
    assert snapshot_body["active_tasks"]["items"][0]["id"] == task_body["id"]
    assert snapshot_body["active_tasks"]["items"][0]["resource_id"] == resource_id
    assert snapshot_body["mode"] == "synthetic"
    assert snapshot_body["generated_at"] == NOW.isoformat()

    publish_communication_gap_event(
        client.app.state.update_feed,
        "org_demo",
        "evt_demo",
        "gateway-demo",
        True,
        NOW.isoformat(),
        "phase5-communication-gap",
        "communication-gap-event",
    )
    client.app.state.update_feed.publish(
        "org_other",
        "evt_other",
        "task_status_changed",
        {"id": "other-task", "status": "assigned"},
        NOW.isoformat(),
        source="other-workspace",
        idempotency_key="other-event",
    )

    events: list[dict] = []
    cursor: str | None = None
    for _ in range(20):
        query = "?limit=2" if cursor is None else f"?limit=2&cursor={cursor}"
        page = client.get(f"/api/v1/updates{query}", headers=operator_headers("events-read"))
        assert page.status_code == 200
        body = page.json()
        events.extend(body["items"])
        next_cursor = body["next_cursor"]
        if next_cursor == cursor or not body["items"]:
            break
        cursor = next_cursor

    event_types = {event["event_type"] for event in events}
    assert {
        "route_condition_changed",
        "incident_phase_changed",
        "communication_gap_detected",
        "task_status_changed",
    } <= event_types
    assert all(
        event["source"]
        and event["source_class"]
        and event["correlation_id"]
        and event["affected_entity_type"]
        and event["affected_entity_id"]
        and event["occurred_at"]
        for event in events
    )
    assert not any(event["affected_entity_id"] == "other-task" for event in events)

    offline_command = OfflineCommand(
        command_id="phase5-offline-1",
        aggregate_id=task_body["id"],
        sequence=1,
        kind="acknowledgement",
        client_timestamp=NOW,
        payload={"status": "acknowledged"},
        tenant_id="org_demo",
        workspace_id="evt_demo",
    )
    offline_batch = SyncBatch(commands=[offline_command])
    first_sync = client.post(
        "/api/v1/offline-sync",
        headers=operator_headers("offline-reconcile"),
        json=offline_batch.model_dump(mode="json"),
    )
    duplicate_sync = client.post(
        "/api/v1/offline-sync",
        headers=operator_headers("offline-reconcile"),
        json=offline_batch.model_dump(mode="json"),
    )
    assert first_sync.status_code == duplicate_sync.status_code == 200
    assert first_sync.json()["reconciliation"]["accepted"] == 1
    assert duplicate_sync.json() == first_sync.json()

