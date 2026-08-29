from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore


def test_tasking_requires_approval_and_prevents_double_booking() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    h = {"X-Dev-Identity": "operator"}
    assert client.post("/api/v1/operations/demo/seed", headers=h).status_code == 200
    ready = next(
        r
        for r in client.get("/api/v1/resources", headers=h).json()["items"]
        if r["readiness"] == "ready"
    )
    q1 = client.post(
        "/api/v1/response-queue", headers=h, json={"title": "Deliver water", "priority": "high"}
    ).json()
    q2 = client.post(
        "/api/v1/response-queue", headers=h, json={"title": "Deliver filters", "priority": "normal"}
    ).json()
    first = client.post(
        f"/api/v1/response-queue/{q1['id']}/approve",
        headers=h,
        json={"resource_id": ready["id"], "approved": True},
    )
    assert first.status_code == 200 and first.json()["status"] == "assigned"
    assert (
        client.post(
            f"/api/v1/response-queue/{q2['id']}/approve",
            headers=h,
            json={"resource_id": ready["id"], "approved": True},
        ).status_code
        == 409
    )
    for status in ("acknowledged", "en_route", "completed"):
        assert (
            client.patch(
                f"/api/v1/tasks/{first.json()['id']}", headers=h, json={"status": status}
            ).status_code
            == 200
        )
    assert (
        client.post(
            f"/api/v1/response-queue/{q2['id']}/approve",
            headers=h,
            json={"resource_id": ready["id"], "approved": True},
        ).status_code
        == 200
    )
