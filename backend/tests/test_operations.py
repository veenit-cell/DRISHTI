from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.evidence import InMemoryEvidenceStore
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
    outcome = client.post(
        f"/api/v1/tasks/{first.json()['id']}/outcome",
        headers=headers("outcome-001"),
        json={"summary": "Synthetic water delivery completed"},
    )
    assert outcome.status_code == 200 and outcome.json()["outcome_summary"]
    assert client.get("/api/v1/response-queue", headers=headers("read-002")).json()["items"][0][
        "status"
    ] == "completed"
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


def test_queue_provenance_must_resolve_in_current_scope() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        evidence_store=InMemoryEvidenceStore(),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    headers = {"X-Dev-Identity": "operator", "Idempotency-Key": "source-001"}
    missing = client.post(
        "/api/v1/response-queue",
        headers=headers,
        json={"title": "Trace water concern", "source_report_id": "rpt_missing"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "QUEUE_SOURCE_REPORT_NOT_FOUND"

    report = client.post(
        "/api/v1/reports",
        headers={"X-Dev-Identity": "operator", "Idempotency-Key": "rpt-source-001"},
        json={
            "contract_version": 1,
            "client_record_id": "rpt-source-001",
            "source": {"channel": "test", "source_class": "synthetic"},
            "report_type": "water_contamination",
            "facts": {"access_state": "unknown"},
            "privacy_class": "restricted_operational",
        },
    ).json()
    created = client.post(
        "/api/v1/response-queue",
        headers={"X-Dev-Identity": "operator", "Idempotency-Key": "source-002"},
        json={"title": "Trace water concern", "source_report_id": report["report_id"]},
    )
    assert created.status_code == 201
    assert created.json()["source_report_id"] == report["report_id"]

    assert client.post("/api/v1/demo/seed", headers=headers).status_code == 200
    incident = client.get("/api/v1/incidents", headers=headers).json()["items"][0]
    incident_queue = client.post(
        "/api/v1/verification-queue",
        headers={"X-Dev-Identity": "operator", "Idempotency-Key": "source-003"},
        json={"title": "Verify incident", "source_incident_id": incident["id"]},
    )
    assert incident_queue.status_code == 201
    assert incident_queue.json()["source_incident_id"] == incident["id"]


def test_cors_allows_mutating_api_contract_headers() -> None:
    app = create_app(
        Settings(
            app_environment="test",
            dev_identity_enabled=True,
            allowed_origins=["http://localhost:5173"],
        ),
        operations_store=InMemoryOperationsStore(),
    )
    response = TestClient(app).options(
        "/api/v1/response-queue",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key,x-dev-identity",
        },
    )
    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()


def test_feasibility_surfaces_verification_readiness_and_routes() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    write = {"X-Dev-Identity": "operator", "Idempotency-Key": "k-001"}
    client.post("/api/v1/operations/demo/seed", headers=write)
    q = client.post(
        "/api/v1/verification-queue",
        headers={**write, "Idempotency-Key": "q-001"},
        json={"title": "Verify shelter count"},
    )
    assert (
        q.status_code == 201
        and client.get("/api/v1/verification-queue", headers=write).json()["items"][0]["queue_type"]
        == "verification"
    )
    resource = client.get("/api/v1/resources", headers=write).json()["items"][0]
    assert (
        client.patch(
            f"/api/v1/resources/{resource['id']}/readiness",
            headers={**write, "Idempotency-Key": "r-001"},
            json={"readiness": "not_ready", "observed_at": "2026-08-30T10:30:00Z"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/route-observations",
            headers={**write, "Idempotency-Key": "route-001"},
            json={
                "destination": "North Sector",
                "state": "blocked",
                "observed_at": "2026-08-30T10:30:00Z",
            },
        ).status_code
        == 201
    )


def test_blocked_route_prevents_task_approval() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    h = {"X-Dev-Identity": "operator"}
    client.post("/api/v1/operations/demo/seed", headers={**h, "Idempotency-Key": "s-route"})
    resource = client.get("/api/v1/resources", headers=h).json()["items"][0]
    client.post(
        "/api/v1/route-observations",
        headers={**h, "Idempotency-Key": "r-route"},
        json={
            "destination": "North Sector",
            "state": "blocked",
            "observed_at": "2026-08-30T10:30:00Z",
        },
    )
    queue = client.post(
        "/api/v1/response-queue",
        headers={**h, "Idempotency-Key": "q-route"},
        json={"title": "Water", "destination": "North Sector"},
    ).json()
    assert (
        client.post(
            f"/api/v1/response-queue/{queue['id']}/approve",
            headers={**h, "Idempotency-Key": "a-route"},
            json={"resource_id": resource["id"], "approved": True},
        ).status_code
        == 409
    )
