from datetime import UTC, datetime

import pytest

from app.core.context import RequestContext
from app.operations import InMemoryOperationsStore, TaskConflictError

NOW = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
CONTEXT = RequestContext("operator", "operator", "org_demo", "evt_demo", frozenset(), "test")


def test_mission_requires_on_scene_before_completion_and_can_pause():
    store = InMemoryOperationsStore()
    store.queue["queue-1"] = {
        "id": "queue-1",
        "workspace_id": CONTEXT.workspace_id,
        "status": "assigned",
    }
    store.tasks["task-1"] = {
        "id": "task-1",
        "workspace_id": CONTEXT.workspace_id,
        "queue_item_id": "queue-1",
        "resource_id": "resource-1",
        "status": "en_route",
    }
    with pytest.raises(TaskConflictError):
        store.update_task(CONTEXT, "task-1", "completed", NOW, "complete-too-soon")
    assert store.update_task(CONTEXT, "task-1", "paused", NOW, "pause-1")["status"] == "paused"
    assert store.update_task(CONTEXT, "task-1", "en_route", NOW, "resume-1")["status"] == "en_route"
    assert store.update_task(CONTEXT, "task-1", "on_scene", NOW, "scene-1")["status"] == "on_scene"
    assert (
        store.update_task(CONTEXT, "task-1", "completed", NOW, "complete-1")["status"]
        == "completed"
    )
