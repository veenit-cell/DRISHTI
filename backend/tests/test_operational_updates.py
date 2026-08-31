import pytest

from app.updates import OperationalUpdateType, UpdateEvent, UpdateFeed, UpdatePublish


EVENT_TYPES: tuple[OperationalUpdateType, ...] = (
    "shelter_state_changed",
    "route_condition_changed",
    "incident_phase_changed",
    "recommendation_changed",
    "resource_readiness_changed",
    "task_status_changed",
    "verification_priority_changed",
    "communication_gap_detected",
    "communication_gap_recovered",
)


def test_operational_events_have_bounded_public_envelope() -> None:
    feed = UpdateFeed()
    feed.publish(
        "tenant-a",
        "workspace-a",
        "shelter_state_changed",
        {"id": "shelter-1", "freshness_state": "fresh", "raw_report": "must not ship"},
        "2026-09-03T10:00:00Z",
        source="shelter_state_api",
        affected_entity_type="shelter",
        affected_entity_id="shelter-1",
    )

    event = feed.poll("tenant-a", "workspace-a", None)["items"][0]
    assert set(event) == {
        "event_type",
        "cursor",
        "occurred_at",
        "source",
        "source_class",
        "correlation_id",
        "affected_entity_type",
        "affected_entity_id",
        "payload",
    }
    assert event["payload"] == {"id": "shelter-1", "freshness_state": "fresh"}
    UpdateEvent.model_validate(event)


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_supported_event_types_are_typed(event_type: OperationalUpdateType) -> None:
    event = UpdatePublish(event_type=event_type, aggregate_id="entity-1")
    assert event.event_type == event_type


def test_feed_filters_events_by_both_tenant_and_workspace() -> None:
    feed = UpdateFeed()
    feed.publish("tenant-a", "workspace-a", "task_status_changed", {"id": "task-a"}, "t1")
    feed.publish("tenant-b", "workspace-a", "task_status_changed", {"id": "task-b"}, "t2")
    feed.publish("tenant-a", "workspace-b", "task_status_changed", {"id": "task-c"}, "t3")

    page = feed.poll("tenant-a", "workspace-a", None)
    assert [item["affected_entity_id"] for item in page["items"]] == ["task-a"]


def test_legacy_feed_cursor_continuation_remains_stable() -> None:
    feed = UpdateFeed()
    feed.publish("tenant-a", "workspace-a", "legacy_event", {"id": "one"}, "t1")
    first = feed.poll("tenant-a", "workspace-a", None, limit=1)
    feed.publish("tenant-a", "workspace-a", "communication_gap_detected", {"id": "gap-1"}, "t2")

    resumed = feed.poll("tenant-a", "workspace-a", first["next_cursor"])
    assert [item["event_type"] for item in resumed["items"]] == ["communication_gap_detected"]


def test_idempotent_publish_does_not_duplicate_event() -> None:
    feed = UpdateFeed()
    first = feed.publish(
        "tenant-a", "workspace-a", "task_status_changed", {"id": "task-1"}, "t1", idempotency_key="cmd-1"
    )
    replay = feed.publish(
        "tenant-a", "workspace-a", "task_status_changed", {"id": "task-1"}, "t2", idempotency_key="cmd-1"
    )

    assert replay == first
    assert len(feed.poll("tenant-a", "workspace-a", None)["items"]) == 1
