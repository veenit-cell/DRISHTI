from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.context import RequestContext
from app.decision_loop import InteractionAuditRequest
from app.main import create_app
from app.operations import InMemoryOperationsStore


NOW = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
SCOPES = frozenset({"operations:read", "operations:write", "decision:read", "decision:write", "evidence:read"})


def make_client(operations: InMemoryOperationsStore | None = None) -> TestClient:
    operations = operations or InMemoryOperationsStore()
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=operations,
        clock=FixedClock(NOW),
    )
    return TestClient(app, raise_server_exceptions=False)


def operator_headers(**extra: str) -> dict[str, str]:
    return {"X-Dev-Identity": "operator", **extra}


def test_phase10_unauthorized_access_uses_problem_json() -> None:
    response = make_client().get("/api/v1/command/summary")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["correlation_id"]


def test_phase10_summary_is_scoped_and_has_freshness_metadata() -> None:
    client = make_client()
    response = client.get(
        "/api/v1/command/summary",
        headers=operator_headers(**{"X-Correlation-ID": "phase10-summary"}),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correlation_id"] == "phase10-summary"
    assert body["freshness"]["as_of"] == NOW.isoformat()
    assert body["availability"]["state"] == "available"


def test_phase10_empty_workspace_is_unknown_not_fresh() -> None:
    body = make_client().get("/api/v1/command/summary", headers=operator_headers()).json()
    assert body["freshness"]["state"] == "unknown"


def test_phase10_stale_scenario_is_visible() -> None:
    client = make_client()
    context = RequestContext("usr_demo_operator", "operator", "org_demo", "evt_demo", SCOPES, "seed")
    client.app.state.decision_store.replay(context, NOW - timedelta(hours=7), "phase10-stale-replay")
    body = client.get("/api/v1/command/summary", headers=operator_headers()).json()
    assert body["freshness"]["state"] == "stale"


def test_phase10_dependency_failure_returns_degraded_partial_summary() -> None:
    operations = InMemoryOperationsStore()
    client = make_client(operations)

    def unavailable(_context: RequestContext) -> list[dict[str, object]]:
        raise RuntimeError("temporary store outage")

    operations.list_resources = unavailable  # type: ignore[method-assign]
    response = client.get("/api/v1/command/summary", headers=operator_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["freshness"]["state"] == "degraded"
    assert "operations.resources" in body["availability"]["unavailable_stores"]
    assert body["metrics"]["total_resources"] == 0


def test_phase10_update_duplicate_is_replayed_and_conflict_is_problem_json() -> None:
    client = make_client()
    headers = operator_headers(**{"Idempotency-Key": "phase10-update-1"})
    payload = {"event_type": "task_status_changed", "aggregate_id": "task-1", "status": "assigned"}
    first = client.post("/api/v1/updates", headers=headers, json=payload)
    duplicate = client.post("/api/v1/updates", headers=headers, json=payload)
    conflict = client.post(
        "/api/v1/updates",
        headers=headers,
        json={**payload, "status": "completed"},
    )
    assert first.status_code == duplicate.status_code == 201
    assert first.json()["cursor"] == duplicate.json()["cursor"]
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")


def test_phase10_interaction_audit_is_idempotent_and_tenant_isolated() -> None:
    client = make_client()
    payload = {"event": "recommendation_viewed", "subject_type": "recommendation", "subject_id": "rec-1"}
    headers = operator_headers(**{"Idempotency-Key": "phase10-audit-1"})
    first = client.post("/api/v1/decision-loop/audit/interactions", headers=headers, json=payload)
    duplicate = client.post("/api/v1/decision-loop/audit/interactions", headers=headers, json=payload)
    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["replayed"] is True
    assert client.get("/api/v1/decision-loop/audit", headers=operator_headers()).json()["items"]

    store = client.app.state.decision_store
    other = RequestContext("other", "operator", "org_other", "evt_demo", SCOPES, "other")
    store.record_interaction(other, InteractionAuditRequest(**payload), NOW, "phase10-audit-1")
    scoped = store.audit(RequestContext("usr_demo_operator", "operator", "org_demo", "evt_demo", SCOPES, "scope"))
    assert all(item.get("tenant_id") == "org_demo" for item in scoped)


def test_phase10_evaluation_endpoint_does_not_write_audit_records() -> None:
    client = make_client()
    before = list(client.app.state.decision_store.audit_events)
    response = client.post(
        "/api/v1/cascade/evaluate",
        headers=operator_headers(),
        json={
            "snapshot": {
                "observed_at": NOW.isoformat(),
                "freshness_state": "fresh",
                "values": {"power_available": True, "purification_available": True},
                "units": {"power_available": "boolean", "purification_available": "boolean"},
                "field_freshness": {"power_available": "fresh", "purification_available": "fresh"},
                "supporting_refs": {},
            }
        },
    )
    assert response.status_code == 200
    assert client.app.state.decision_store.audit_events == before
