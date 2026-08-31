from datetime import UTC, datetime

import pytest

from app.core.context import RequestContext
from app.evidence import InMemoryEvidenceStore, ReportCreate
from app.incident_command import (
    CommandRoleAssignment,
    IncidentConflictError,
    IncidentCreate,
    IncidentNotFoundError,
    IncidentTransition,
    InMemoryIncidentStore,
    SectorCreate,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
CONTEXT = RequestContext("operator", "operator", "org_demo", "evt_demo", frozenset(), "test")


def make_incident(store):
    return store.create_incident(
        CONTEXT,
        IncidentCreate(
            name="North district flood",
            hazard_type="flood",
            severity="critical",
            summary="River overflow has cut multiple settlements",
            event_time=NOW,
        ),
        NOW,
    )


def test_incident_requires_commander_before_activation():
    store = InMemoryIncidentStore()
    incident = make_incident(store)
    with pytest.raises(IncidentConflictError, match="commander"):
        store.transition(CONTEXT, incident["incident_id"], IncidentTransition(status="active"), NOW)
    store.assign_role(
        CONTEXT,
        incident["incident_id"],
        CommandRoleAssignment(role="incident_commander", actor_id="operator"),
        NOW,
    )
    active = store.transition(
        CONTEXT, incident["incident_id"], IncidentTransition(status="active", phase="size_up"), NOW
    )
    assert active["status"] == "active" and active["phase"] == "size_up"


def test_workspace_has_one_active_incident_and_scope_isolated():
    store = InMemoryIncidentStore()
    first = make_incident(store)
    store.assign_role(
        CONTEXT,
        first["incident_id"],
        CommandRoleAssignment(role="incident_commander", actor_id="operator"),
        NOW,
    )
    store.transition(CONTEXT, first["incident_id"], IncidentTransition(status="active"), NOW)
    with pytest.raises(IncidentConflictError):
        make_incident(store)
    other = RequestContext("other", "operator", "org_other", "evt_other", frozenset(), "test")
    assert store.get_active_incident(other) is None


def test_invalid_lifecycle_transition_is_rejected():
    store = InMemoryIncidentStore()
    incident = make_incident(store)
    with pytest.raises(IncidentConflictError):
        store.transition(CONTEXT, incident["incident_id"], IncidentTransition(status="closed"), NOW)


def test_sector_is_scoped_owned_and_unique_within_incident():
    store = InMemoryIncidentStore()
    incident = make_incident(store)
    sector = store.create_sector(
        CONTEXT,
        incident["incident_id"],
        SectorCreate(name="North bank", owner_actor_id="team-alpha", assessment_state="assessed"),
        NOW,
    )
    assert sector["owner_actor_id"] == "team-alpha"
    assert sector["assessment_state"] == "assessed"
    assert [item["sector_id"] for item in store.list_sectors(CONTEXT, incident["incident_id"])] == [
        sector["sector_id"]
    ]
    with pytest.raises(IncidentConflictError, match="unique"):
        store.create_sector(
            CONTEXT,
            incident["incident_id"],
            SectorCreate(name="North bank", owner_actor_id="team-bravo"),
            NOW,
        )


def test_closed_incident_cannot_receive_sector():
    store = InMemoryIncidentStore()
    incident = make_incident(store)
    store.assign_role(
        CONTEXT,
        incident["incident_id"],
        CommandRoleAssignment(role="incident_commander", actor_id="operator"),
        NOW,
    )
    store.transition(CONTEXT, incident["incident_id"], IncidentTransition(status="active"), NOW)
    store.transition(CONTEXT, incident["incident_id"], IncidentTransition(status="closed"), NOW)
    with pytest.raises(IncidentConflictError, match="closed"):
        store.create_sector(
            CONTEXT,
            incident["incident_id"],
            SectorCreate(name="North bank", owner_actor_id="team-alpha"),
            NOW,
        )


def test_get_incident_respects_workspace_scope():
    store = InMemoryIncidentStore()
    incident = make_incident(store)
    assert store.get_incident(CONTEXT, incident["incident_id"])["name"] == "North district flood"
    other = RequestContext("other", "operator", "org_other", "evt_other", frozenset(), "test")
    with pytest.raises(IncidentNotFoundError):
        store.get_incident(other, incident["incident_id"])


def test_report_trace_persists_against_command_incident():
    incidents = InMemoryIncidentStore()
    incident = make_incident(incidents)
    reports = InMemoryEvidenceStore()
    report, replayed = reports.create_report(
        CONTEXT,
        ReportCreate(
            client_record_id="rpt_command_trace_001",
            observed_at=NOW,
            received_at=NOW,
            source={"channel": "field_form", "source_class": "authenticated_responder"},
            location={"geometry": {"type": "Point", "coordinates": [91.742, 26.184]}},
            report_type="life_safety",
            facts={"people_affected": 12},
        ),
        NOW,
    )
    assert replayed is False
    incidents.get_incident(CONTEXT, incident["incident_id"])
    reports.link_command_incident(CONTEXT, report["id"], incident["incident_id"], NOW)
    assert reports.get_report(CONTEXT, report["id"])["command_incident_links"] == [
        {
            "report_id": report["id"],
            "incident_id": incident["incident_id"],
            "linked_by": CONTEXT.actor_id,
                "linked_at": "2026-08-30T12:00:00Z",
        }
    ]
