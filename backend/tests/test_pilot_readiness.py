from datetime import UTC, datetime, timedelta

import pytest

from app.core.context import RequestContext
from app.pilot_readiness import (
    InMemoryPilotStore,
    OfficialFeedEnvelope,
    PilotConfigCreate,
    PilotConflictError,
    retention_preview,
    run_tabletop_exercise,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
CONTEXT = RequestContext("operator", "operator", "org_demo", "evt_demo", frozenset(), "test")


def config() -> PilotConfigCreate:
    return PilotConfigCreate(
        agency_name="District Emergency Operations Centre",
        district_name="Kamrup Metropolitan",
        country_code="IN",
        approved_feed_ids=["district_control_room"],
        hazard_playbooks={"flood": "flood_v1"},
    )


def envelope(summary: str = "Bridge inspection reports approach blocked") -> OfficialFeedEnvelope:
    return OfficialFeedEnvelope(
        feed_id="district_control_room",
        external_event_id="route-001",
        kind="route_status",
        observed_at=NOW,
        received_at=NOW,
        summary=summary,
    )


def test_configuration_and_official_feed_boundary_are_scoped_and_idempotent() -> None:
    store = InMemoryPilotStore()
    stored = store.configure(CONTEXT, config(), NOW)
    assert stored["district_name"] == "Kamrup Metropolitan"
    event, replayed = store.ingest_feed(CONTEXT, envelope(), NOW)
    assert event["provenance"] == "configured_official_feed_boundary"
    assert replayed is False
    same, replayed = store.ingest_feed(CONTEXT, envelope(), NOW)
    assert same["event_id"] == event["event_id"] and replayed is True
    with pytest.raises(PilotConflictError, match="reused"):
        store.ingest_feed(CONTEXT, envelope("Different payload"), NOW)
    other = RequestContext("other", "operator", "org_other", "evt_other", frozenset(), "test")
    assert store.get_config(other) is None


def test_retention_requires_review_instead_of_unattended_deletion() -> None:
    stored = InMemoryPilotStore().configure(CONTEXT, config(), NOW)
    preview = retention_preview(stored, "restricted_operational", NOW - timedelta(days=31), NOW)
    assert preview.action == "eligible_for_review"
    assert preview.automatic_deletion is False


def test_tabletop_exercise_is_deterministic_and_covers_required_faults() -> None:
    first, second = run_tabletop_exercise(), run_tabletop_exercise()
    assert first["result_hash"] == second["result_hash"]
    assert set(first["faults"]) == {
        "connectivity_outage",
        "duplicate_report",
        "blocked_corridor",
        "silent_village",
        "connectivity_restored",
    }
    assert first["metrics"]["wrong_dispatches"] == 0
    assert all(first["assertions"].values())
