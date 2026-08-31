from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.context import RequestContext
from app.persistence import database_ready
from app.pilot_readiness import OfficialFeedEnvelope, PilotConfigCreate, PostgreSQLPilotStore

pytestmark = pytest.mark.skipif(
    not database_ready(Settings().database_url), reason="PostgreSQL is not available"
)


def test_postgres_pilot_configuration_and_feed_boundary_round_trip() -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    suffix = uuid4().hex
    context = RequestContext(
        "operator", "operator", f"org_pg_pilot_{suffix}", f"evt_pg_pilot_{suffix}", frozenset(), "test"
    )
    store = PostgreSQLPilotStore(Settings().database_url)
    configured = store.configure(
        context,
        PilotConfigCreate(
            agency_name="District EOC",
            district_name="Pilot District",
            country_code="IN",
            approved_feed_ids=["control_room"],
        ),
        now,
    )
    assert configured["district_name"] == "Pilot District"
    event, replayed = store.ingest_feed(
        context,
        OfficialFeedEnvelope(
            feed_id="control_room",
            external_event_id="road-1",
            kind="route_status",
            observed_at=now,
            received_at=now,
            summary="Primary corridor blocked",
        ),
        now,
    )
    assert replayed is False
    assert store.list_feed_events(context)[0]["event_id"] == event["event_id"]
