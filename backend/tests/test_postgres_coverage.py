from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.context import RequestContext
from app.coverage import (
    CoverageCellCreate,
    CoverageObservationCreate,
    PostgreSQLCoverageStore,
)
from app.persistence import database_ready


@pytest.mark.skipif(
    not database_ready(Settings().database_url),
    reason="local PostgreSQL/PostGIS integration profile is not running",
)
def test_postgresql_coverage_cell_observation_and_ranking() -> None:
    now = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)
    suffix = uuid4().hex
    context = RequestContext(
        actor_id="usr_demo_operator",
        role="operator",
        tenant_id="org_demo",
        workspace_id="evt_demo",
        scopes=frozenset({"evidence:read", "evidence:write"}),
        correlation_id=f"coverage-{suffix}",
    )
    store = PostgreSQLCoverageStore(Settings().database_url)
    cell_id = f"coverage_pg_{suffix}"

    created = store.create_cell(
        context,
        CoverageCellCreate(
            cell_id=cell_id,
            name="Synthetic PostgreSQL Coverage Cell",
            population=4200,
            critical_facilities=1,
            hazard_exposure="high",
            required_fact_types=["bridge_passable"],
        ),
        now,
    )
    assert created["cell_id"] == cell_id
    assert created["observation_count"] == 0

    observation = store.create_observation(
        context,
        cell_id,
        CoverageObservationCreate(
            fact_type="bridge_passable",
            observed_at=now,
            freshness_state="fresh",
        ),
        now,
        f"coverage-observation-{suffix}",
    )
    assert observation["replayed"] is False
    assert observation["cell"]["observation_count"] == 1

    replay = store.create_observation(
        context,
        cell_id,
        CoverageObservationCreate(
            fact_type="bridge_passable",
            observed_at=now,
            freshness_state="fresh",
        ),
        now,
        f"coverage-observation-{suffix}",
    )
    assert replay["replayed"] is True
    assert replay["observation_id"] == observation["observation_id"]

    persisted = store.get_cell(context, cell_id, now)
    assert persisted["observation_count"] == 1
    ranking = store.verification_ranking(context, now)
    assert ranking
    assert ranking[0]["cell_id"] == cell_id
    assert ranking[0]["fact_type"] == "bridge_passable"
