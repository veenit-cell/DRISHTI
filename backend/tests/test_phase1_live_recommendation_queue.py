from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.context import RequestContext
from app.main import create_app
from app.operations import InMemoryOperationsStore, QueueItemCreate


NOW = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)


def make_client() -> TestClient:
    return TestClient(
        create_app(
            Settings(app_environment="test", dev_identity_enabled=True),
            operations_store=InMemoryOperationsStore(),
            clock=FixedClock(NOW),
        )
    )


def headers(key: str, identity: str = "operator") -> dict[str, str]:
    return {"X-Dev-Identity": identity, "Idempotency-Key": key}


def create_recommendation(client: TestClient) -> dict:
    assert client.post("/api/v1/decision-loop/demo/replay", headers=headers("replay-1")).status_code == 200
    response = client.post("/api/v1/decision-loop/recommendations", headers=headers("recommend-1"))
    assert response.status_code == 200
    return response.json()


def test_approved_recommendation_creates_linked_queue_and_explicit_assignment_creates_task() -> None:
    client = make_client()
    recommendation = create_recommendation(client)
    resource_id = recommendation["compatible_resources"][0]["id"]

    approved = client.post(
        f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision",
        headers=headers("decision-1"),
        json={"decision": "approve", "resource_id": resource_id},
    )
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["status"] == "approved"
    assert approved_body["auto_dispatched"] is False
    assert approved_body["queue_item_id"]

    queue = client.get("/api/v1/response-queue", headers=headers("read-queue")).json()["items"]
    item = next(item for item in queue if item["id"] == approved_body["queue_item_id"])
    assert item["source_recommendation_id"] == recommendation["id"]
    assert item["status"] == "queued"
    assert client.get("/api/v1/tasks", headers=headers("read-tasks")).json()["items"] == []

    route = client.post(
        "/api/v1/route-observations",
        headers=headers("route-1"),
        json={
            "destination": "North Sector",
            "state": "passable",
            "observed_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "source": "commander_confirmation",
        },
    )
    assert route.status_code == 200
    task = client.post(
        f"/api/v1/response-queue/{approved_body['queue_item_id']}/approve",
        headers=headers("assign-1"),
        json={"resource_id": resource_id, "approved": True, "approval_note": "Commander approved assignment"},
    )
    assert task.status_code == 200
    task_body = task.json()
    assert task_body["queue_item_id"] == approved_body["queue_item_id"]
    assert task_body["resource_id"] == resource_id
    assert task_body["status"] == "assigned"


def test_duplicate_approval_replays_without_duplicate_queue_item() -> None:
    client = make_client()
    recommendation = create_recommendation(client)
    path = f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision"
    payload = {"decision": "approve", "resource_id": recommendation["compatible_resources"][0]["id"]}

    first = client.post(path, headers=headers("decision-same"), json=payload)
    second = client.post(path, headers=headers("decision-same"), json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["queue_item_id"] == second.json()["queue_item_id"]
    queue = client.get("/api/v1/response-queue", headers=headers("read-queue")).json()["items"]
    assert len([item for item in queue if item["source_recommendation_id"] == recommendation["id"]]) == 1


def test_invalid_resource_does_not_approve_or_create_queue() -> None:
    client = make_client()
    recommendation = create_recommendation(client)
    response = client.post(
        f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision",
        headers=headers("decision-invalid"),
        json={"decision": "approve", "resource_id": "resource-outside-scope"},
    )
    assert response.status_code == 404
    current = client.get("/api/v1/decision-loop/recommendations/current", headers=headers("read-current"))
    assert current.status_code == 200
    assert current.json()["recommendation"]["status"] == "pending_approval"
    assert client.get("/api/v1/response-queue", headers=headers("read-queue")).json()["items"] == []


def test_unauthorized_viewer_cannot_approve_recommendation() -> None:
    client = make_client()
    recommendation = create_recommendation(client)
    response = client.post(
        f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision",
        headers=headers("viewer-decision", "viewer"),
        json={"decision": "approve"},
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_rejected_approval_does_not_create_queue_or_task() -> None:
    client = make_client()
    recommendation = create_recommendation(client)
    response = client.post(
        f"/api/v1/decision-loop/recommendations/{recommendation['id']}/decision",
        headers=headers("decision-reject"),
        json={"decision": "reject", "note": "Commander rejected this option"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["queue_item_id"] is None
    assert client.get("/api/v1/response-queue", headers=headers("read-queue")).json()["items"] == []
    assert client.get("/api/v1/tasks", headers=headers("read-tasks")).json()["items"] == []


def test_in_memory_operations_enforce_tenant_and_workspace_scope() -> None:
    store = InMemoryOperationsStore()
    first = RequestContext("actor-a", "operator", "tenant-a", "workspace-a", frozenset(), "corr-a")
    other = RequestContext("actor-b", "operator", "tenant-b", "workspace-a", frozenset(), "corr-b")
    item = store.create_queue(first, QueueItemCreate(title="Scoped task"), NOW, "queue-a")
    assert item in store.list_queue(first)
    assert store.list_queue(other) == []
