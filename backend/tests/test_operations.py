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

    def headers(key: str) -> dict[str, str]:
        return {"X-Dev-Identity": "operator", "Idempotency-Key": key}

    assert (
        client.post("/api/v1/operations/demo/seed", headers=headers("seed-001")).status_code == 200
    )
    ready = next(
        r
        for r in client.get("/api/v1/resources", headers=headers("read-001")).json()["items"]
        if r["readiness"] == "ready"
    )
    q1 = client.post(
        "/api/v1/response-queue",
        headers=headers("queue-001"),
        json={"title": "Deliver water", "priority": "high"},
    ).json()
    q2 = client.post(
        "/api/v1/response-queue",
        headers=headers("queue-002"),
        json={"title": "Deliver filters", "priority": "normal"},
    ).json()
    first = client.post(
        f"/api/v1/response-queue/{q1['id']}/approve",
        headers=headers("approve-001"),
        json={"resource_id": ready["id"], "approved": True},
    )
    assert first.status_code == 200 and first.json()["status"] == "assigned"
    assert (
        client.post(
            f"/api/v1/response-queue/{q2['id']}/approve",
            headers=headers("approve-002"),
            json={"resource_id": ready["id"], "approved": True},
        ).status_code
        == 409
    )
    for status in ("acknowledged", "en_route", "completed"):
        assert (
            client.patch(
                f"/api/v1/tasks/{first.json()['id']}",
                headers=headers(f"status-{status}"),
                json={"status": status},
            ).status_code
            == 200
        )
    assert (
        client.post(
            f"/api/v1/response-queue/{q2['id']}/approve",
            headers=headers("approve-003"),
            json={"resource_id": ready["id"], "approved": True},
        ).status_code
        == 200
    )


def test_operations_write_idempotency_and_task_transition_guards() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    operator = {"X-Dev-Identity": "operator"}
    assert (
        client.post(
            "/api/v1/operations/demo/seed",
            headers={**operator, "Idempotency-Key": "seed-001"},
        ).status_code
        == 200
    )
    resource = client.get("/api/v1/resources", headers=operator).json()["items"][0]
    payload = {"title": "Water delivery"}
    first = client.post(
        "/api/v1/response-queue",
        headers={**operator, "Idempotency-Key": "queue-001"},
        json=payload,
    )
    replay = client.post(
        "/api/v1/response-queue",
        headers={**operator, "Idempotency-Key": "queue-001"},
        json=payload,
    )
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert (
        client.post(
            "/api/v1/response-queue",
            headers={**operator, "Idempotency-Key": "queue-001"},
            json={"title": "Different command"},
        ).status_code
        == 409
    )
    task = client.post(
        f"/api/v1/response-queue/{first.json()['id']}/approve",
        headers={**operator, "Idempotency-Key": "approve-001"},
        json={"resource_id": resource["id"], "approved": True},
    ).json()
    assert (
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            headers={**operator, "Idempotency-Key": "status-001"},
            json={"status": "completed"},
        ).status_code
        == 409
    )
