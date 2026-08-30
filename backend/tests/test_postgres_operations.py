from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.persistence import database_ready


def _headers(key: str) -> dict[str, str]:
    return {"X-Dev-Identity": "operator", "Idempotency-Key": key}


@pytest.mark.skipif(
    not database_ready(Settings().database_url),
    reason="local PostgreSQL/PostGIS integration profile is not running",
)
def test_postgresql_operations_and_decision_state_are_durable() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    suffix = uuid4().hex

    replay = client.post("/api/v1/decision-loop/demo/replay", headers=_headers(f"replay-{suffix}"))
    assert replay.status_code == 200
    resources = client.get("/api/v1/resources", headers=_headers(f"resources-{suffix}")).json()[
        "items"
    ]
    ready_resource = next(resource for resource in resources if resource["readiness"] == "ready")

    first_queue = client.post(
        "/api/v1/response-queue",
        headers=_headers(f"queue-one-{suffix}"),
        json={"title": "Deliver water treatment supplies", "priority": "high"},
    ).json()
    second_queue = client.post(
        "/api/v1/response-queue",
        headers=_headers(f"queue-two-{suffix}"),
        json={"title": "Verify secondary water point", "priority": "normal"},
    ).json()
    task = client.post(
        f"/api/v1/response-queue/{first_queue['id']}/approve",
        headers=_headers(f"approve-one-{suffix}"),
        json={"resource_id": ready_resource["id"], "approved": True},
    ).json()
    assert (
        client.post(
            f"/api/v1/response-queue/{second_queue['id']}/approve",
            headers=_headers(f"approve-two-{suffix}"),
            json={"resource_id": ready_resource["id"], "approved": True},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            headers=_headers(f"skip-transition-{suffix}"),
            json={"status": "completed"},
        ).status_code
        == 409
    )
    for status in ("acknowledged", "en_route", "completed"):
        assert (
            client.patch(
                f"/api/v1/tasks/{task['id']}",
                headers=_headers(f"{status}-{suffix}"),
                json={"status": status},
            ).status_code
            == 200
        )

    recommendation = client.post(
        "/api/v1/decision-loop/recommendations", headers=_headers(f"recommend-{suffix}")
    ).json()
    decision = client.post(
        f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision",
        headers=_headers(f"decision-{suffix}"),
        json={"decision": "approve", "note": "Synthetic commander approval"},
    )
    assert decision.status_code == 200
    audit = client.get("/api/v1/decision-loop/audit", headers=_headers(f"audit-{suffix}"))
    assert {event["event"] for event in audit.json()["items"]} >= {
        "scenario_replayed",
        "recommendation_created",
        "recommendation_approved",
    }
    integrity = client.get("/api/v1/audit/integrity", headers=_headers(f"integrity-{suffix}"))
    assert integrity.status_code == 200
    assert integrity.json()["valid"] is True


@pytest.mark.skipif(
    not database_ready(Settings().database_url),
    reason="local PostgreSQL/PostGIS integration profile is not running",
)
def test_postgresql_concurrent_approvals_do_not_double_book_a_resource() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    suffix = uuid4().hex
    replay = client.post(
        "/api/v1/decision-loop/demo/replay", headers=_headers(f"replay-{suffix}")
    )
    assert replay.status_code == 200
    resource = next(
        item
        for item in client.get(
            "/api/v1/resources", headers=_headers(f"resources-{suffix}")
        ).json()["items"]
        if item["readiness"] == "ready"
    )
    queues = [
        client.post(
            "/api/v1/response-queue",
            headers=_headers(f"queue-{index}-{suffix}"),
            json={"title": f"Concurrent water action {index}"},
        ).json()
        for index in range(2)
    ]

    def approve(index: int) -> int:
        with TestClient(app) as worker:
            return worker.post(
                f"/api/v1/response-queue/{queues[index]['id']}/approve",
                headers=_headers(f"approve-{index}-{suffix}"),
                json={"resource_id": resource["id"], "approved": True},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(approve, range(2)))
    assert statuses == [200, 409]
