# ruff: noqa: E501

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore


def test_frontend_golden_flow_reaches_audited_outcome_without_auto_dispatch() -> None:
    client = TestClient(create_app(Settings(app_environment="test", dev_identity_enabled=True), operations_store=InMemoryOperationsStore(), clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC))))
    def headers(key):
        return {"X-Dev-Identity": "operator", "Idempotency-Key": key}
    assert client.post("/api/v1/decision-loop/demo/replay", headers=headers("ui-replay")).status_code == 200
    recommendation = client.post("/api/v1/decision-loop/recommendations", headers=headers("ui-recommend")).json()
    assert recommendation["candidates"] and recommendation["auto_dispatched"] is False
    approved = client.post(f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision", headers=headers("ui-decision"), json={"decision": "approve"}).json()
    assert client.get("/api/v1/tasks", headers=headers("read-empty")).json()["items"] == []
    client.post("/api/v1/route-observations", headers=headers("ui-route"), json={"destination": "North Sector", "state": "passable", "observed_at": "2026-08-30T10:30:00Z", "expires_at": (datetime(2026, 8, 30, 10, 30, tzinfo=UTC) + timedelta(hours=1)).isoformat(), "source": "commander_demo_confirmation"})
    task = client.post(f"/api/v1/response-queue/{approved['queue_item_id']}/approve", headers=headers("ui-assign"), json={"resource_id": approved["compatible_resources"][0]["id"], "approved": True}).json()
    for status in ("acknowledged", "en_route", "on_scene", "completed"):
        task = client.patch(f"/api/v1/tasks/{task['id']}", headers=headers(f"ui-{status}"), json={"status": status}).json()
    task = client.post(f"/api/v1/tasks/{task['id']}/outcome", headers=headers("ui-outcome"), json={"summary": "Synthetic intervention completed"}).json()
    assert task["outcome_summary"] and client.get("/api/v1/decision-loop/audit", headers=headers("read-audit")).json()["items"]
