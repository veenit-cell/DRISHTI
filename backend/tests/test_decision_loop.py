from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore


def test_replay_recommendation_and_explicit_decision() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)

    def headers(key: str) -> dict[str, str]:
        return {"X-Dev-Identity": "operator", "Idempotency-Key": key}

    replay = client.post("/api/v1/decision-loop/demo/replay", headers=headers("replay-001"))
    assert (
        replay.status_code == 200
        and replay.json()["scenario_id"] == "scenario_fixed_north_sector_v1"
    )
    recommendation = client.post(
        "/api/v1/decision-loop/recommendations", headers=headers("recommend-001")
    )
    body = recommendation.json()
    assert recommendation.status_code == 200 and body["status"] == "pending_approval"
    assert body["reasons"] and body["compatible_resources"] and body["auto_dispatched"] is False
    decision = client.post(
        f"/api/v1/decision-loop/recommendations/{body['id']}/decision",
        headers=headers("decision-001"),
        json={"decision": "approve", "note": "Commander confirms water priority"},
    )
    assert decision.status_code == 200 and decision.json()["status"] == "approved"
    assert (
        client.post(
            f"/api/v1/decision-loop/recommendations/{body['id']}/decision",
            headers=headers("decision-002"),
            json={"decision": "reject"},
        ).status_code
        == 404
    )
    assert client.get("/api/v1/tasks", headers=headers("read-001")).json()["items"] == []
    assert (
        client.post("/api/v1/decision-loop/demo/replay", headers=headers("replay-002")).json()[
            "scenario_id"
        ]
        == "scenario_fixed_north_sector_v1"
    )
