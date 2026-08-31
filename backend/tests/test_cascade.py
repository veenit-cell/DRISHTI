# ruff: noqa: E501

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.cascade import (
    DEPENDENCY_GRAPH,
    CascadeRequest,
    CascadeSnapshot,
    evaluate_cascade,
    validate_dependency_graph,
)
from app.core.config import Settings
from app.dependencies import legacy_dependency_graph
from app.main import create_app
from app.operations import InMemoryOperationsStore


def test_cascade_uses_shared_dependency_graph_adapter():
    assert DEPENDENCY_GRAPH == legacy_dependency_graph()


def snap(**changes):
    freshness_state = changes.pop("freshness_state", "fresh")
    values = {
        "power_available": False,
        "purification_available": True,
        "water_runway_hours": 4,
        "cold_chain_hours": 5,
        "unsafe_water_liters": 100,
        "population": 110,
        "capacity": 100,
        "population_influx_per_hour": 2,
        "medical_demand_trend": "rising",
        "medical_demand_per_hour": 12,
        "diagnostic_capacity_per_hour": 8,
        "medicine_runway_hours": 6,
    }
    values.update(changes)
    units = {
        "power_available": "boolean",
        "purification_available": "boolean",
        "water_runway_hours": "hours",
        "cold_chain_hours": "hours",
        "unsafe_water_liters": "liters",
        "population": "people",
        "capacity": "people",
        "population_influx_per_hour": "people/hour",
        "medical_demand_trend": "category",
        "medical_demand_per_hour": "units/hour",
        "diagnostic_capacity_per_hour": "units/hour",
        "medicine_runway_hours": "hours",
    }
    return CascadeSnapshot(
        observed_at="2026-08-30T10:00:00Z",
        freshness_state=freshness_state,
        values=values,
        units=units,
    )


def test_all_dependency_paths_and_deterministic_order():
    result = evaluate_cascade(CascadeRequest(snapshot=snap()))
    names = [item.affected_capability for item in result.findings]
    assert names == sorted(names)
    assert {
        "safe_water_runway",
        "medicine_cold_chain",
        "operational_disease_risk_pressure",
        "medicine_diagnostic_pressure",
    } == set(names)
    assert all(item.rule_version == "cascade_v1" for item in result.findings)
    assert evaluate_cascade(CascadeRequest(snapshot=snap())).model_dump() == result.model_dump()


def test_unknown_and_stale_inputs_are_visible_not_safe():
    result = evaluate_cascade(
        CascadeRequest(snapshot=snap(power_available=None, freshness_state="stale"))
    )
    assert any(item.confidence == "low" and item.unknown_contributors for item in result.findings)
    assert "diagnosis" not in str(result.model_dump()).lower()


def test_graph_cycle_and_depth_are_rejected():
    with pytest.raises(ValueError, match="cycle"):
        validate_dependency_graph({"a": ["b"], "b": ["a"]})
    with pytest.raises(ValueError, match="depth"):
        validate_dependency_graph({"a": ["b"], "b": ["c"], "c": ["d"], "d": ["e"]}, max_depth=4)


def test_api_is_bounded_and_does_not_mutate_input():
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
    )
    body = CascadeRequest(snapshot=snap()).model_dump(mode="json")
    original = deepcopy(body)
    response = TestClient(app).post(
        "/api/v1/cascade/evaluate", headers={"X-Dev-Identity": "viewer"}, json=body
    )
    assert response.status_code == 200 and body == original
    body["max_depth"] = 5
    assert (
        TestClient(app)
        .post("/api/v1/cascade/evaluate", headers={"X-Dev-Identity": "viewer"}, json=body)
        .status_code
        == 422
    )
