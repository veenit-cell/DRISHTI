from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext


class ResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    resource_type: str = Field(min_length=1, max_length=60)
    readiness: str = Field(pattern="^(ready|not_ready|unknown)$")
    location: str | None = Field(default=None, max_length=120)


class QueueItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")
    destination: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)


class TaskApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    approved: bool
    approval_note: str | None = Field(default=None, max_length=500)


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(assigned|acknowledged|en_route|completed)$")


class ResourceNotFoundError(Exception):
    pass


class QueueItemNotFoundError(Exception):
    pass


class TaskConflictError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


class InMemoryOperationsStore:
    def __init__(self) -> None:
        self.resources: dict[str, dict[str, Any]] = {}
        self.queue: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}

    def seed_demo(self, context: RequestContext, now: datetime) -> dict[str, int]:
        if any(r["workspace_id"] == context.workspace_id for r in self.resources.values()):
            return {"resources": 0, "queue_items": 0}
        for name, typ, readiness, location in [
            ("Synthetic Water Team Alpha", "water_team", "ready", "North Sector"),
            ("Synthetic Generator Unit", "power_unit", "ready", "Central Shelter"),
            ("Synthetic Medical Van", "medical_transport", "not_ready", "East Depot"),
        ]:
            rid = f"res_{uuid4().hex[:12]}"
            self.resources[rid] = {
                "id": rid,
                "name": name,
                "resource_type": typ,
                "readiness": readiness,
                "location": location,
                "workspace_id": context.workspace_id,
                "created_at": now.isoformat(),
            }
        return {"resources": 3, "queue_items": 0}

    def list_resources(self, context: RequestContext) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.resources.values() if r["workspace_id"] == context.workspace_id
        ]

    def create_queue(
        self, context: RequestContext, item: QueueItemCreate, now: datetime
    ) -> dict[str, Any]:
        iid = f"q_{uuid4().hex[:12]}"
        record = {
            "id": iid,
            **item.model_dump(),
            "status": "queued",
            "workspace_id": context.workspace_id,
            "created_at": now.isoformat(),
        }
        self.queue[iid] = record
        return dict(record)

    def list_queue(self, context: RequestContext) -> list[dict[str, Any]]:
        return [dict(i) for i in self.queue.values() if i["workspace_id"] == context.workspace_id]

    def approve_task(
        self, context: RequestContext, queue_id: str, approval: TaskApproval, now: datetime
    ) -> dict[str, Any]:
        item = self.queue.get(queue_id)
        resource = self.resources.get(approval.resource_id)
        if item is None or item["workspace_id"] != context.workspace_id:
            raise QueueItemNotFoundError
        if resource is None or resource["workspace_id"] != context.workspace_id:
            raise ResourceNotFoundError
        if not approval.approved:
            item["status"] = "rejected"
            return {"approved": False, "queue_item_id": queue_id, "status": item["status"]}
        if resource["readiness"] != "ready":
            raise TaskConflictError("resource is not ready")
        if any(
            t["resource_id"] == resource["id"] and t["status"] != "completed"
            for t in self.tasks.values()
        ):
            raise TaskConflictError("resource already has an active task")
        tid = f"task_{uuid4().hex[:12]}"
        task = {
            "id": tid,
            "queue_item_id": queue_id,
            "resource_id": resource["id"],
            "status": "assigned",
            "approved": True,
            "approved_by": context.actor_id,
            "approved_at": now.isoformat(),
            "workspace_id": context.workspace_id,
        }
        self.tasks[tid] = task
        item["status"] = "assigned"
        return dict(task)

    def update_task(
        self, context: RequestContext, task_id: str, status: str, now: datetime
    ) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if task is None or task["workspace_id"] != context.workspace_id:
            raise TaskNotFoundError
        task["status"] = status
        task["updated_at"] = now.isoformat()
        return dict(task)

    def list_tasks(self, context: RequestContext) -> list[dict[str, Any]]:
        return [dict(t) for t in self.tasks.values() if t["workspace_id"] == context.workspace_id]
