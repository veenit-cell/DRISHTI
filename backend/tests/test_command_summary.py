from copy import deepcopy
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.command_summary import build_command_summary
from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.context import RequestContext
from app.main import create_app
from app.operations import InMemoryOperationsStore, QueueItemCreate, TaskApproval


NOW = datetime(2026, 9, 3, 10, 5, tzinfo=UTC)
CONTEXT = RequestContext(
    "usr_demo_operator",
    "operator",
    "org_demo",
    "evt_demo",
    frozenset({"operations:read", "operations:write", "decision:read", "decision:write"}),
    "test-correlation",
)


def test_command_summary_prioritizes_water_and_unknowns():
    summary = build_command_summary(
        resources=[{"readiness": "ready"}, {"readiness": "not_ready"}],
        response_queue=[{"status": "queued"}],
        verification_queue=[{"status": "queued"}],
        tasks=[{"status": "en_route"}],
        scenario={
            "synthetic": True,
            "replayed_at": "2026-09-03T10:00:00+00:00",
            "signals": {
                "water_runway_hours": 3.5,
                "contamination": "elevated",
                "population_influx": 180,
            },
        },
        generated_at=datetime(2026, 9, 3, 10, 5, tzinfo=UTC),
    )
    assert summary["metrics"]["ready_resources"] == 1
    assert summary["metrics"]["water_runway_hours"] == 3.5
    assert summary["metrics"]["contamination"] == "elevated"
    assert [item["key"] for item in summary["priorities"]] == [
        "water-runway",
        "contamination",
        "verification",
    ]


def test_command_summary_preserves_mixed_mode_and_normalizes_statuses():
    summary = build_command_summary(
        resources=[{"readiness": "READY"}],
        response_queue=[{"status": "COMPLETED"}, {"status": "queued"}],
        verification_queue=[{"status": "cancelled"}],
        tasks=[{"status": "REJECTED"}, {"status": "assigned"}],
        scenario={"signals": {}},
        generated_at=NOW,
        workspace_mode="mixed",
    )
    assert summary["mode"] == "mixed"
    assert summary["metrics"]["ready_resources"] == 1
    assert summary["metrics"]["response_queue"] == 1
    assert summary["metrics"]["verification_queue"] == 0
    assert summary["metrics"]["active_tasks"] == 1


def test_command_summary_endpoint_is_read_only_and_workspace_scoped():
    operations = InMemoryOperationsStore()
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=operations,
        clock=FixedClock(NOW),
    )
    decision_store = app.state.decision_store
    decision_store.replay(CONTEXT, NOW, "replay-command-summary")
    operations.seed_demo(CONTEXT, NOW, "seed-command-summary")
    other_context = RequestContext(
        "other-operator",
        "operator",
        "org-other",
        "workspace-other",
        CONTEXT.scopes,
        "other-correlation",
    )
    operations.seed_demo(other_context, NOW, "seed-other-workspace")
    response_queue = operations.create_queue(
        CONTEXT,
        QueueItemCreate(title="Dispatch water team", required_capability="water_delivery"),
        NOW,
        "summary-response-queue",
    )
    operations.create_queue(
        CONTEXT,
        QueueItemCreate(title="Verify silent village", queue_type="verification"),
        NOW,
        "summary-verification-queue",
    )
    resource = next(
        item for item in operations.list_resources(CONTEXT) if item["readiness"] == "ready"
    )
    operations.approve_task(
        CONTEXT,
        response_queue["id"],
        TaskApproval(resource_id=resource["id"], approved=True),
        NOW,
        "summary-task-approval",
    )
    before = deepcopy(
        (operations.resources, operations.queue, operations.tasks, decision_store.scenarios)
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/command/summary", headers={"X-Dev-Identity": "operator"}
    )
    write_attempt = client.post(
        "/api/v1/command/summary", headers={"X-Dev-Identity": "operator"}
    )

    assert response.status_code == 200
    assert write_attempt.status_code == 405
    body = response.json()
    assert body["mode"] == "synthetic"
    assert body["source"] == "api"
    assert body["metrics"] == {
        "ready_resources": 5,
        "total_resources": 7,
        "active_tasks": 1,
        "response_queue": 1,
        "verification_queue": 1,
        "population_influx": 180,
        "water_runway_hours": 3.5,
        "contamination": "elevated",
    }
    assert body["generated_at"] == NOW.isoformat()
    assert body["priorities"]
    assert (
        operations.resources,
        operations.queue,
        operations.tasks,
        decision_store.scenarios,
    ) == before

import pytest


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        app_environment="development",
        dev_identity_enabled=True,
        database_url="postgresql://localhost/unused",
    )
    return TestClient(create_app(settings=settings, clock=FixedClock(NOW)))


def test_command_summary_requires_read_scope(client: TestClient) -> None:
    missing = client.get("/api/v1/command/summary")
    assert missing.status_code == 401
    denied = client.get("/api/v1/command/summary", headers={"X-Dev-Identity": "viewer"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "SCOPE_DENIED"
