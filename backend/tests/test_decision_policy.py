# ruff: noqa: E501

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.decision_policy import (
    CascadeAdapter,
    PolicyRequest,
    PolicySnapshot,
    ProjectionAdapter,
    ResourceAdapter,
    evaluate_policy,
)
from app.main import create_app
from app.operations import InMemoryOperationsStore

NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)


def req(resources=None, **kwargs):
    return PolicyRequest(
        snapshot=PolicySnapshot(observed_at=NOW, values={"synthetic": 1}, freshness_state="fresh"),
        projections=[ProjectionAdapter(resource="potable_water", state="projected", time_to_critical_hours=3, confidence="medium"), ProjectionAdapter(resource="battery", state="projected", time_to_critical_hours=5, confidence="medium"), ProjectionAdapter(resource="medicine", state="projected", time_to_critical_hours=8, confidence="medium")],
        cascades=[CascadeAdapter(affected_capability="safe_water_runway", severity="high", supporting_input_refs=["fixture:water"])],
        resources=resources or [ResourceAdapter(id="water-1", capabilities=["water_delivery"], readiness="ready", route_passable=True, readiness_expires_at=NOW + timedelta(hours=2))],
        now=NOW,
        **kwargs,
    )


def test_three_ranked_candidates_are_deterministic_and_explained():
    first = evaluate_policy(req()).model_dump()
    second = evaluate_policy(req()).model_dump()
    assert first == second and len(first["candidates"]) == 3
    assert [c["rank"] for c in first["candidates"]] == [1, 2, 3]
    required = {"action", "evidence_references", "reasons", "resource_cost", "expected_benefit", "time_sensitivity_hours", "confidence", "expires_at", "policy_version", "input_hash", "excluded_resources", "expected_operational_effect"}
    assert required <= set(first["candidates"][0])


def test_constraints_expiry_and_all_infeasible_fallback():
    resources = [ResourceAdapter(id="busy", capabilities=["water_delivery"], readiness="ready", route_passable=True, active_task=True), ResourceAdapter(id="expired", capabilities=["power_management"], readiness="ready", route_passable=True, readiness_expires_at=NOW - timedelta(minutes=1))]
    result = evaluate_policy(req(resources=resources))
    assert result.fallback_used
    assert all(c.feasible is False for c in result.candidates)
    assert "resource already has an active task" in result.candidates[0].excluded_resources.values()
    expired = req()
    expired.snapshot.expires_at = NOW - timedelta(minutes=1)
    assert all(c.confidence == "low" and not c.feasible for c in evaluate_policy(expired).candidates)


def test_api_rejects_excessive_horizon_and_accepts_evaluation_only():
    app = create_app(Settings(app_environment="test", dev_identity_enabled=True), operations_store=InMemoryOperationsStore())
    body = req().model_dump(mode="json")
    response = TestClient(app).post("/api/v1/decision-policy/evaluate", headers={"X-Dev-Identity": "viewer"}, json=body)
    assert response.status_code == 200 and response.json()["policy_version"] == "intervention_policy_v1"
    body["horizon_hours"] = 169
    assert TestClient(app).post("/api/v1/decision-policy/evaluate", headers={"X-Dev-Identity": "viewer"}, json=body).status_code == 422


def test_invalid_horizon_is_rejected():
    with pytest.raises(ValueError):
        req(horizon_hours=169)
