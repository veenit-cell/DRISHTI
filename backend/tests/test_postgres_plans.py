from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.context import RequestContext
from app.persistence import database_ready
from app.plans import PostgreSQLPlanStore


@pytest.mark.skipif(
    not database_ready(Settings().database_url),
    reason="local PostgreSQL/PostGIS integration profile is not running",
)
def test_postgresql_plan_store_round_trip():
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    context = RequestContext(
        "operator", "operator", "org_demo", "evt_demo", frozenset(), f"plans-{uuid4().hex}"
    )
    # The shared plan model is exercised through the SQL adapter when DB is available.
    from app.plans import PlanActionCreate, PlanCreate

    plan = PostgreSQLPlanStore(Settings().database_url).create_plan(
        context,
        PlanCreate(
            objective_summary="Test",
            policy_version="test",
            horizon_hours=1,
            actions=[PlanActionCreate(action_class="response", action_type="verify")],
            input_snapshot_hash="hash",
        ),
        now,
    )
    assert (
        PostgreSQLPlanStore(Settings().database_url).get_plan(context, plan["plan_id"])["plan_id"]
        == plan["plan_id"]
    )
