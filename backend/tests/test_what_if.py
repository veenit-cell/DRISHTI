# ruff: noqa: E501

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore
from app.runway import RunwaySnapshot
from app.what_if import Intervention, WhatIfRequest, evaluate_what_if


def snapshot(**changes):
    values = {"population": 1000, "population_influx_per_hour": 10, "potable_water_liters": 2000, "water_consumption_liters_per_hour": 100, "replenishment_liters_per_hour": 0, "battery_percent": 50, "battery_capacity_kwh": 100, "power_consumption_kw": 10, "battery_replenishment_kw": 0, "medicine_units": 100, "medicine_consumption_per_hour": 5, "cold_chain_hours": 10, "cold_chain_depletion_hours_per_hour": 1}
    values.update(changes)
    units = {"population": "people", "population_influx_per_hour": "people/hour", "potable_water_liters": "liters", "water_consumption_liters_per_hour": "liters/hour", "replenishment_liters_per_hour": "liters/hour", "battery_percent": "percent", "battery_capacity_kwh": "kilowatt-hours", "power_consumption_kw": "kilowatts", "battery_replenishment_kw": "kilowatts", "medicine_units": "units", "medicine_consumption_per_hour": "units/hour", "cold_chain_hours": "hours", "cold_chain_depletion_hours_per_hour": "hours/hour"}
    return RunwaySnapshot(observed_at="2026-08-30T10:00:00Z", freshness_state="fresh", values=values, units=units, thresholds={"potable_water_liters": 500, "battery_percent": 20, "medicine_units": 20, "cold_chain_hours": 2})


def request(kind, **kwargs):
    defaults = {"kind": kind, "amount": 100, "unit": "liters"}
    defaults.update(kwargs)
    return WhatIfRequest(snapshot=snapshot(), intervention=Intervention(**defaults))


def test_comparison_is_deterministic_and_source_unchanged():
    source = snapshot()
    before = json.dumps(source.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    req = WhatIfRequest(snapshot=source, intervention=Intervention(kind="add_potable_water", amount=100, unit="liters"))
    first, second = evaluate_what_if(req), evaluate_what_if(req)
    after = json.dumps(source.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    assert after == before
    assert first.model_dump() == second.model_dump()
    assert first.input_hash == second.input_hash
    assert first.baseline.projection.projections != first.intervention.projection.projections


def test_interventions_show_benefit_and_cost_and_unknowns():
    purification = evaluate_what_if(request("purification", amount=50, unit="liters/hour", enabled=True, power_cost_kw=4))
    assert "costs" in purification.intervention.tradeoffs[0]
    assert purification.intervention.projection.projections != purification.baseline.projection.projections
    shifted = evaluate_what_if(request("shift_power_load", amount=2, unit="kilowatts"))
    assert any(p.resource == "battery" and p.time_to_critical_hours > 0 for p in shifted.intervention.projection.projections if p.time_to_critical_hours is not None)
    unknown = evaluate_what_if(WhatIfRequest(snapshot=snapshot(potable_water_liters=None), intervention=Intervention(kind="add_potable_water", amount=100, unit="liters")))
    assert next(p for p in unknown.intervention.projection.projections if p.resource == "potable_water").state == "unknown"


def test_invalid_combinations_and_api_bounds_fail():
    with pytest.raises(ValueError, match="unit"):
        request("add_potable_water", unit="people")
    with pytest.raises(ValueError, match="power_cost"):
        request("purification", amount=10, unit="liters/hour", enabled=True)
    app = create_app(Settings(app_environment="test", dev_identity_enabled=True), operations_store=InMemoryOperationsStore())
    body = {"snapshot": snapshot().model_dump(mode="json"), "intervention": {"kind": "add_potable_water", "amount": 100, "unit": "liters"}, "horizon_hours": 169}
    assert TestClient(app).post("/api/v1/what-if/evaluate", headers={"X-Dev-Identity": "viewer"}, json=body).status_code == 422
    body["horizon_hours"] = 24
    body["source_snapshot_id"] = "live-1"
    assert TestClient(app).post("/api/v1/what-if/evaluate", headers={"X-Dev-Identity": "viewer"}, json=body).status_code == 422
