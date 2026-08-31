from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore
from app.updates import UpdateFeed, publish_communication_gap_event


NOW = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
HEADERS = {"X-Dev-Identity": "operator"}


def test_update_feed_sanitizes_provenance_and_paginates_by_cursor() -> None:
    feed = UpdateFeed()
    first = feed.publish(
        "tenant-a",
        "workspace-a",
        "route_condition_changed",
        {"id": "route-1", "state": "blocked", "private_note": "do not ship", "device_key": "secret"},
        "2026-09-04T10:00:00Z",
        source="route_observation_api",
        source_class="operator_report",
        correlation_id="corr-route",
        idempotency_key="route-command-1",
    )
    feed.publish(
        "tenant-a",
        "workspace-a",
        "communication_gap_detected",
        {"id": "gap-1", "freshness_state": "silent"},
        "2026-09-04T10:01:00Z",
        source="lorawan_adapter",
        correlation_id="corr-gap",
        idempotency_key="gap-command-1",
    )
    page = feed.poll("tenant-a", "workspace-a", None, limit=1)
    event = page["items"][0]
    assert event["cursor"] == first
    assert event["source_class"] == "operator_report"
    assert event["correlation_id"] == "corr-route"
    assert "private_note" not in event["payload"]
    assert "device_key" not in event["payload"]
    resumed = feed.poll("tenant-a", "workspace-a", page["next_cursor"])
    assert resumed["items"][0]["event_type"] == "communication_gap_detected"


def test_update_feed_scopes_and_prevents_duplicate_events() -> None:
    feed = UpdateFeed()
    first = feed.publish("tenant-a", "workspace-a", "incident_phase_changed", {"id": "inc-1"}, "t1", idempotency_key="same")
    replay = feed.publish("tenant-a", "workspace-a", "incident_phase_changed", {"id": "inc-1"}, "t2", idempotency_key="same")
    feed.publish("tenant-b", "workspace-a", "incident_phase_changed", {"id": "inc-2"}, "t3", idempotency_key="same")
    assert replay == first
    assert len(feed.poll("tenant-a", "workspace-a", None)["items"]) == 1
    assert [item["affected_entity_id"] for item in feed.poll("tenant-b", "workspace-a", None)["items"]] == ["inc-2"]


def test_communication_gap_detection_and_recovery_are_typed_and_idempotent() -> None:
    feed = UpdateFeed()
    publish_communication_gap_event(feed, "tenant-a", "workspace-a", "gateway-1", True, "t1", "corr-1", "gap-1")
    first_recovery = publish_communication_gap_event(feed, "tenant-a", "workspace-a", "gateway-1", False, "t2", "corr-2", "gap-2")
    replay_recovery = publish_communication_gap_event(feed, "tenant-a", "workspace-a", "gateway-1", False, "t3", "corr-3", "gap-2")
    assert replay_recovery == first_recovery
    assert [item["event_type"] for item in feed.poll("tenant-a", "workspace-a", None)["items"]] == [
        "communication_gap_detected",
        "communication_gap_recovered",
    ]


def test_route_change_and_incident_phase_publish_scoped_events() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(NOW),
    )
    client = TestClient(app)
    route = client.post(
        "/api/v1/route-observations",
        headers={**HEADERS, "Idempotency-Key": "route-api-1"},
        json={
            "destination": "North Sector",
            "state": "blocked",
            "observed_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "source": "field_operator",
        },
    )
    assert route.status_code == 201
    incident = client.post(
        "/api/v1/command/incidents",
        headers={**HEADERS, "Idempotency-Key": "incident-api-1"},
        json={
            "name": "Flood response",
            "hazard_type": "flood",
            "severity": "high",
            "summary": "River corridor impacted",
            "event_time": NOW.isoformat(),
        },
    ).json()
    incident_id = incident["incident_id"]
    assert client.post(
        f"/api/v1/command/incidents/{incident_id}/roles",
        headers={**HEADERS, "Idempotency-Key": "role-api-1"},
        json={"role": "incident_commander", "actor_id": "operator"},
    ).status_code == 200
    assert client.patch(
        f"/api/v1/command/incidents/{incident_id}",
        headers={**HEADERS, "Idempotency-Key": "transition-api-1"},
        json={"status": "active", "phase": "size_up"},
    ).status_code == 200
    events = client.get("/api/v1/updates", headers=HEADERS).json()["items"]
    assert {event["event_type"] for event in events} >= {"route_condition_changed", "incident_phase_changed"}
    assert all(event["correlation_id"] for event in events)
