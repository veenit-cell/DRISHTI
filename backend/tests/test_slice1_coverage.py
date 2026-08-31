from datetime import UTC, datetime, timedelta

from app.core.context import RequestContext
from app.coverage import (
    CoverageCell,
    CoverageCellCreate,
    CoverageObservationCreate,
    InMemoryCoverageStore,
    compute_coverage_debt,
    rank_verification_tasks,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
CONTEXT = RequestContext("operator", "operator", "org_demo", "evt_demo", frozenset(), "test")


def cell(**overrides):
    values = {
        "cell_id": "hilltop",
        "name": "Hilltop Village",
        "population": 4200,
        "critical_facilities": 1,
        "hazard_exposure": "high",
        "required_fact_types": ["bridge_passable"],
        "reporting_impaired": True,
        "last_verified_at": None,
        "observation_count": 0,
    }
    values.update(overrides)
    return CoverageCell(**values)


def test_silent_high_population_cell_extreme_debt():
    result = compute_coverage_debt(cell(population=25_000, hazard_exposure="extreme"), NOW)
    assert result.debt_band == "EXTREME"
    assert result.debt_score == 1.0


def test_verified_cell_low_debt():
    result = compute_coverage_debt(
        cell(
            population=100,
            hazard_exposure="low",
            reporting_impaired=False,
            last_verified_at=NOW - timedelta(minutes=5),
        ),
        NOW,
    )
    assert result.debt_band == "LOW"


def test_plan_changing_fact_ranks_higher_than_unrelated_missing_fact():
    high = cell(required_fact_types=["bridge_passable"])
    low = cell(
        cell_id="valley",
        name="Valley Settlement",
        population=100,
        hazard_exposure="low",
        reporting_impaired=False,
        required_fact_types=["shelter_count"],
    )
    plans = [
        {
            "plan_id": "plan-bridge",
            "status": "feasible",
            "assumptions": [
                {
                    "subject_type": "coverage_cell",
                    "subject_id": "hilltop",
                    "expected_state": "bridge_passable",
                }
            ],
        }
    ]
    ranked = rank_verification_tasks([high, low], plans, NOW)
    assert ranked[0].cell_id == "hilltop"
    assert ranked[0].plan_ids_affected == ["plan-bridge"]


def test_no_plan_impact_is_visible_and_lower_ranked():
    ranked = rank_verification_tasks([cell()], [], NOW)
    assert ranked[0].plan_ids_affected == []
    assert "no active plan" in ranked[0].what_answer_changes


def test_in_memory_store_persists_cell_and_replays_observation():
    store = InMemoryCoverageStore()
    store.create_cell(
        CONTEXT,
        CoverageCellCreate(
            cell_id="hilltop",
            name="Hilltop Village",
            population=4200,
            hazard_exposure="high",
            required_fact_types=["bridge_passable"],
        ),
        NOW,
    )
    observation = CoverageObservationCreate(
        fact_type="bridge_passable", observed_at=NOW, freshness_state="fresh"
    )
    first = store.create_observation(CONTEXT, "hilltop", observation, NOW, "obs-hilltop-1")
    second = store.create_observation(CONTEXT, "hilltop", observation, NOW, "obs-hilltop-1")
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert store.get_cell(CONTEXT, "hilltop", NOW)["observation_count"] == 1
