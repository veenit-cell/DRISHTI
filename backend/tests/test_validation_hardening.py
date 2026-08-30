from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore


def make_client() -> TestClient:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    return TestClient(app)


def test_complete_demo_path_and_audit_visibility() -> None:
    client = make_client()
    operator = {"X-Dev-Identity": "operator"}
    assert client.post("/api/v1/decision-loop/demo/replay", headers=operator).status_code == 200
    recommendation = client.post("/api/v1/decision-loop/recommendations", headers=operator).json()
    assert recommendation["reasons"] and recommendation["compatible_resources"]
    decision = client.post(
        f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision",
        headers=operator,
        json={"decision": "approve"},
    )
    assert decision.status_code == 200
    assert client.get("/api/v1/tasks", headers=operator).json()["items"] == []
    audit = client.get("/api/v1/decision-loop/audit", headers=operator)
    assert audit.status_code == 200
    assert {event["event"] for event in audit.json()["items"]} >= {
        "scenario_replayed",
        "recommendation_created",
        "recommendation_approved",
    }


def test_authorization_and_invalid_input_checks() -> None:
    client = make_client()
    viewer = {"X-Dev-Identity": "viewer"}
    assert client.post("/api/v1/decision-loop/demo/replay", headers=viewer).status_code == 403
    assert (
        client.post(
            "/api/v1/decision-loop/recommendations/nope/decision",
            headers={"X-Dev-Identity": "operator"},
            json={"decision": "maybe"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/tasks/nope",
            headers={"X-Dev-Identity": "operator"},
            json={"status": "dispatched"},
        ).status_code
        == 422
    )
