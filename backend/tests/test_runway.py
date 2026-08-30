# ruff: noqa: E501

from copy import deepcopy

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore
from app.runway import FORMULA_VERSION, RunwayRequest, RunwaySnapshot, project_runway


def snapshot(**overrides):
    freshness_state = overrides.pop("freshness_state", "fresh")
    values = {
        "population": 1800,
        "population_influx_per_hour": 180,
        "potable_water_liters": 4200,
        "water_consumption_liters_per_hour": 420,
        "replenishment_liters_per_hour": 0,
        "battery_percent": 31,
        "battery_capacity_kwh": 100,
        "power_consumption_kw": 18,
        "battery_replenishment_kw": 0,
        "medicine_units": 240,
        "medicine_consumption_per_hour": 20,
        "cold_chain_hours": 8,
        "cold_chain_depletion_hours_per_hour": 1,
    }
    values.update(overrides)
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
        observed_at="2026-08-30T10:30:00+00:00",
        freshness_state=freshness_state,
        values=values,
        units=units,
        thresholds={
            "potable_water_liters": 1000,
            "battery_percent": 20,
            "medicine_units": 40,
            "cold_chain_hours": 2,
        },
    )


def test_projection_is_deterministic_and_uses_population_influx() -> None:
    request = RunwayRequest(snapshot=snapshot(), horizon_hours=48)
    first = project_runway(request).model_dump()
    second = project_runway(request).model_dump()
    assert first == second
    assert first["formula_version"] == FORMULA_VERSION
    water = next(item for item in first["projections"] if item["resource"] == "potable_water")
    assert water["time_to_critical_hours"] == 6.9
    assert "population influx increases" in water["contributors"][0]


def test_projection_handles_critical_unknown_stale_and_replenishing_states() -> None:
    critical = project_runway(RunwayRequest(snapshot=snapshot(potable_water_liters=900))).model_dump()
    assert next(item for item in critical["projections"] if item["resource"] == "potable_water")["state"] == "critical"
    unknown_values = snapshot(battery_capacity_kwh=None)
    unknown = project_runway(RunwayRequest(snapshot=unknown_values)).model_dump()
    battery = next(item for item in unknown["projections"] if item["resource"] == "battery")
    assert battery["state"] == "unknown" and battery["time_to_critical_hours"] is None
    stale_values = snapshot(freshness_state="stale")
    stale = project_runway(RunwayRequest(snapshot=stale_values)).model_dump()
    assert all(item["freshness_state"] == "stale" for item in stale["projections"])
    replenishing = project_runway(
        RunwayRequest(snapshot=snapshot(replenishment_liters_per_hour=600))
    ).model_dump()
    assert next(item for item in replenishing["projections"] if item["resource"] == "potable_water")["state"] == "not_depleting"


def test_invalid_rate_and_missing_required_inputs_return_unknown() -> None:
    negative = project_runway(
        RunwayRequest(snapshot=snapshot(water_consumption_liters_per_hour=-1))
    ).model_dump()
    assert next(item for item in negative["projections"] if item["resource"] == "potable_water")["state"] == "unknown"
    missing = project_runway(
        RunwayRequest(snapshot=snapshot(medicine_units=None))
    ).model_dump()
    assert next(item for item in missing["projections"] if item["resource"] == "medicine")["state"] == "unknown"


def test_api_evaluates_explicit_snapshot_without_mutating_input() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
    )
    body = RunwayRequest(snapshot=snapshot()).model_dump(mode="json")
    original = deepcopy(body)
    response = TestClient(app).post(
        "/api/v1/runway/projections",
        headers={"X-Dev-Identity": "operator"},
        json=body,
    )
    assert response.status_code == 200
    assert body == original
    assert response.json()["formula_version"] == FORMULA_VERSION
