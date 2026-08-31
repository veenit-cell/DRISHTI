from copy import deepcopy

from app.runway import RunwaySnapshot
from app.what_if import Intervention, WhatIfRequest, evaluate_what_if


def snapshot() -> RunwaySnapshot:
    values = {
        "population": 1000,
        "population_influx_per_hour": 10,
        "potable_water_liters": 2000,
        "water_consumption_liters_per_hour": 100,
        "replenishment_liters_per_hour": 20,
        "battery_percent": 50,
        "battery_capacity_kwh": 100,
        "power_consumption_kw": 10,
        "battery_replenishment_kw": 0,
        "medicine_units": 100,
        "medicine_consumption_per_hour": 5,
        "cold_chain_hours": 10,
        "cold_chain_depletion_hours_per_hour": 1,
    }
    units = {
        "population": "people",
        "population_influx_per_hour": "people/hour",
        "potable_water_liters": "liters",
        "water_consumption_liters_per_hour": "liters/hour",
        "replenishment_liters_per_hour": "liters/hour",
        "battery_percent": "percent",
        "battery_capacity_kwh": "kilowatt-hours",
        "power_consumption_kw": "kilowatts",
        "battery_replenishment_kw": "kilowatts",
        "medicine_units": "units",
        "medicine_consumption_per_hour": "units/hour",
        "cold_chain_hours": "hours",
        "cold_chain_depletion_hours_per_hour": "hours/hour",
    }
    return RunwaySnapshot(
        observed_at="2026-09-03T10:00:00+00:00",
        freshness_state="fresh",
        values=values,
        units=units,
        thresholds={
            "potable_water_liters": 500,
            "battery_percent": 20,
            "medicine_units": 20,
            "cold_chain_hours": 2,
        },
    )


def evaluate(intervention: Intervention):
    return evaluate_what_if(WhatIfRequest(snapshot=snapshot(), intervention=intervention))


def test_phase6_inputs_are_supported_and_typed():
    cases = [
        Intervention(kind="population_influx", amount=200, unit="people/hour"),
        Intervention(kind="water_contamination", amount=60, unit="percent"),
        Intervention(kind="battery_reduction", amount=20, unit="percent"),
        Intervention(kind="purification_unavailable", enabled=True),
        Intervention(kind="route_blockage", enabled=True),
        Intervention(kind="resource_transfer", amount=250, unit="liters", resource_type="potable_water", source_resource="Shelter B"),
    ]
    for intervention in cases:
        result = evaluate(intervention)
        assert result.baseline.risk_level in {"low", "medium", "high", "critical", "unknown"}
        assert result.intervention.scenario_hash
        assert isinstance(result.intervention.resource_consumption, dict)
        assert result.intervention.uncertainty


def test_phase6_evaluation_does_not_mutate_source_snapshot():
    source = snapshot()
    before = deepcopy(source.model_dump(mode="json"))
    for intervention in (
        Intervention(kind="water_contamination", amount=75, unit="percent"),
        Intervention(kind="purification_unavailable", enabled=True),
        Intervention(kind="resource_transfer", amount=100, unit="units", resource_type="medicine"),
    ):
        evaluate_what_if(WhatIfRequest(snapshot=source, intervention=intervention))
    assert source.model_dump(mode="json") == before


def test_phase6_changes_are_visible_in_comparison():
    influx = evaluate(Intervention(kind="population_influx", amount=500, unit="people/hour"))
    assert influx.intervention.resource_consumption["water_liters_per_hour"] > influx.baseline.resource_consumption["water_liters_per_hour"]

    contamination = evaluate(Intervention(kind="water_contamination", amount=80, unit="percent"))
    baseline_water = next(item for item in contamination.baseline.projection.projections if item.resource == "potable_water")
    intervention_water = next(item for item in contamination.intervention.projection.projections if item.resource == "potable_water")
    assert intervention_water.time_to_critical_hours < baseline_water.time_to_critical_hours
    assert contamination.intervention.changed_inputs["water_contamination_percent"] == 80

    blocked = evaluate(Intervention(kind="route_blockage", enabled=True))
    assert blocked.intervention.changed_inputs["route_blocked"] is True
    assert blocked.intervention.risk_level == "high"


def test_resource_transfer_records_source_limit_as_uncertainty():
    result = evaluate(Intervention(kind="resource_transfer", amount=30, unit="units", resource_type="medicine", source_resource="Shelter B"))
    assert result.intervention.changed_inputs["transferred_from"] == "Shelter B"
    assert any("source reserve" in item for item in result.intervention.uncertainty)
