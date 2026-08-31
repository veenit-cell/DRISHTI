from datetime import UTC, datetime

from app.operational_snapshot import build_operational_snapshot


NOW = datetime(2026, 9, 3, 10, 5, tzinfo=UTC)


def cascade_state(freshness: str = "fresh", *, contradictory: bool = False) -> dict:
    values = {
        "population": 1800,
        "capacity": 2200,
        "population_influx_per_hour": 180,
        "unsafe_water_liters": 800,
        "power_available": False,
        "purification_available": True,
        "water_runway_hours": 3.5,
        "cold_chain_hours": 8,
        "medical_demand_trend": "rising",
        "medical_demand_per_hour": 12,
        "diagnostic_capacity_per_hour": 8,
        "medicine_runway_hours": 6,
    }
    if contradictory:
        values.update(power_available=True, purification_available=None, water_runway_hours=1.5)
    units = {
        "population": "people",
        "capacity": "people",
        "population_influx_per_hour": "people/hour",
        "unsafe_water_liters": "liters",
        "power_available": "boolean",
        "purification_available": "boolean",
        "water_runway_hours": "hours",
        "cold_chain_hours": "hours",
        "medical_demand_trend": "category",
        "medical_demand_per_hour": "units/hour",
        "diagnostic_capacity_per_hour": "cases/hour",
        "medicine_runway_hours": "hours",
    }
    return {
        "observed_at": NOW.isoformat(),
        "freshness_state": freshness,
        "values": values,
        "units": units,
        "field_freshness": {key: freshness for key in values},
        "sources": {key: f"fixture:{key}" for key in values},
    }


def snapshot_inputs(**overrides):
    inputs = {
        "active_incident": None,
        "resources": [],
        "tasks": [],
        "response_queue": [],
        "verification_queue": [],
        "route_conditions": [],
        "shelter_state": None,
        "pending_recommendations": [],
        "generated_at": NOW,
        "mode": "synthetic",
    }
    inputs.update(overrides)
    return inputs


def test_empty_snapshot_returns_empty_cascade_path() -> None:
    result = build_operational_snapshot(**snapshot_inputs())
    assert result["cascade_findings"] == []


def test_complete_path_contains_explainable_finding_fields() -> None:
    result = build_operational_snapshot(**snapshot_inputs(shelter_state=cascade_state()))
    required = {
        "severity",
        "causal_path",
        "estimated_time_window_hours",
        "confidence",
        "supporting_input_refs",
        "unknown_contributors",
    }
    assert result["cascade_findings"]
    assert all(required <= set(finding) for finding in result["cascade_findings"])
    assert all(finding["confidence"] == "high" for finding in result["cascade_findings"])
    assert all(finding["unknown_contributors"] == [] for finding in result["cascade_findings"])


def test_stale_path_keeps_stale_inputs_visible() -> None:
    result = build_operational_snapshot(**snapshot_inputs(shelter_state=cascade_state("stale")))
    assert result["cascade_findings"]
    assert all(finding["confidence"] == "low" for finding in result["cascade_findings"])
    assert all(finding["unknown_contributors"] for finding in result["cascade_findings"])


def test_contradictory_signals_keep_multiple_causal_paths_and_references() -> None:
    result = build_operational_snapshot(
        **snapshot_inputs(shelter_state=cascade_state(contradictory=True))
    )
    paths = {tuple(finding["causal_path"]) for finding in result["cascade_findings"]}
    references = {ref for finding in result["cascade_findings"] for ref in finding["supporting_input_refs"]}
    assert len(paths) >= 2
    assert "fixture:power_available" in references
    assert "fixture:purification_available" in references
