from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.context import RequestContext
from app.incident_command import IncidentCreate, PostgreSQLIncidentStore, SectorCreate
from app.persistence import database_ready

pytestmark = pytest.mark.skipif(
    not database_ready(Settings().database_url), reason="PostgreSQL is not available"
)


def test_postgres_incident_command_round_trip():
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    context = RequestContext(
        "operator", "operator", "org_pg_command", "evt_pg_command", frozenset(), "test"
    )
    store = PostgreSQLIncidentStore(Settings().database_url)
    incident = store.create_incident(
        context,
        IncidentCreate(
            name="District flood exercise",
            hazard_type="flood",
            severity="high",
            summary="Initial reports require coordinated assessment",
            event_time=now,
        ),
        now,
    )
    assert store.get_active_incident(context) is None
    assert store.get_incident(context, incident["incident_id"])["status"] == "draft"
    sector = store.create_sector(
        context,
        incident["incident_id"],
        SectorCreate(name="North bank", owner_actor_id="team-alpha", assessment_state="assessed"),
        now,
    )
    assert sector["incident_id"] == incident["incident_id"]
    assert store.list_sectors(context, incident["incident_id"])[0]["owner_actor_id"] == "team-alpha"
