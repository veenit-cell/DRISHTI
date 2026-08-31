# ruff: noqa: E501

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext
from app.plans import PlanStore


class ResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    resource_type: str = Field(min_length=1, max_length=60)
    readiness: str = Field(pattern="^(ready|not_ready|unknown)$")
    location: str | None = Field(default=None, max_length=120)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    readiness_observed_at: datetime | None = None
    readiness_expires_at: datetime | None = None


class QueueItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")
    destination: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)
    queue_type: str = Field(default="response", pattern="^(response|verification)$")
    required_capability: str | None = Field(default=None, max_length=80)
    owner_actor_id: str | None = Field(default=None, max_length=128)
    due_at: datetime | None = None
    source_report_id: str | None = Field(default=None, max_length=128)
    source_incident_id: str | None = Field(default=None, max_length=128)


class MissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_report_id: str = Field(min_length=1, max_length=128)
    source_incident_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=160)
    destination: str | None = Field(default=None, max_length=120)
    priority: str = Field(default="high", pattern="^(low|normal|high|critical)$")
    required_capability: str | None = Field(default=None, max_length=80)
    owner_actor_id: str | None = Field(default=None, max_length=128)


class ResourceReadinessUpdate(BaseModel):
    readiness: str = Field(pattern="^(ready|not_ready|unknown)$")
    observed_at: datetime
    expires_at: datetime | None = None


class RouteObservationCreate(BaseModel):
    destination: str = Field(min_length=1, max_length=120)
    state: str = Field(pattern="^(passable|blocked|unknown|stale)$")
    observed_at: datetime
    expires_at: datetime | None = None
    source: str | None = Field(default=None, max_length=80)


class TaskApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    approved: bool
    approval_note: str | None = Field(default=None, max_length=500)


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(assigned|acknowledged|en_route|on_scene|paused|completed)$")


class TaskOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=1000)


class StructuredTaskOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type_evidence: str = Field(min_length=1, max_length=160)
    completion_quantities: dict[str, float] = Field(default_factory=dict, max_length=20)
    completed_at: datetime
    residual_need: str | None = Field(default=None, max_length=500)
    verified_by: str = Field(min_length=1, max_length=128)


class ResourceNotFoundError(Exception):
    pass


class QueueItemNotFoundError(Exception):
    pass


class TaskConflictError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


class OperationsStore(Protocol):
    def seed_demo(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, int]: ...

    def list_resources(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def update_readiness(
        self,
        context: RequestContext,
        resource_id: str,
        update: ResourceReadinessUpdate,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def create_queue(
        self, context: RequestContext, item: QueueItemCreate, now: datetime, idempotency_key: str
    ) -> dict[str, Any]: ...

    def list_queue(
        self, context: RequestContext, queue_type: str = "response"
    ) -> list[dict[str, Any]]: ...
    def create_route_observation(
        self,
        context: RequestContext,
        observation: RouteObservationCreate,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    def list_route_observations(self, context: RequestContext) -> list[dict[str, Any]]: ...

    def approve_task(
        self,
        context: RequestContext,
        queue_id: str,
        approval: TaskApproval,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def update_task(
        self,
        context: RequestContext,
        task_id: str,
        status: str,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def list_tasks(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def record_task_outcome(
        self,
        context: RequestContext,
        task_id: str,
        outcome: TaskOutcome,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    def record_structured_outcome(
        self,
        context: RequestContext,
        task_id: str,
        outcome: StructuredTaskOutcome,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    def list_jobs(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def verify_audit_chain(self, context: RequestContext) -> dict[str, Any]: ...

    def reset_for_replay(self, context: RequestContext, now: datetime) -> None: ...


def _opaque_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _request_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _task_record(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "queue_item_id": str(row[1]),
        "resource_id": str(row[2]),
        "status": row[3],
        "approved": True,
        "approved_by": row[4],
        "approved_at": _iso(row[5]),
        "updated_at": _iso(row[6]),
    }


class InMemoryOperationsStore:
    """Fast deterministic test adapter. Application runtime uses PostgreSQLOperationsStore."""

    def __init__(self, plan_store: PlanStore | None = None) -> None:
        self.resources: dict[str, dict[str, Any]] = {}
        self.queue: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.routes: dict[str, dict[str, Any]] = {}
        self._idempotent: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
        self.plan_store = plan_store

    def _replay_or_record(
        self, context: RequestContext, key: str, payload: Any, result: dict[str, Any]
    ) -> dict[str, Any]:
        identity = (context.tenant_id, context.workspace_id, key)
        digest = _request_hash(payload)
        existing = self._idempotent.get(identity)
        if existing:
            if existing[0] != digest:
                raise IdempotencyConflictError
            return copy.deepcopy(existing[1])
        self._idempotent[identity] = (digest, copy.deepcopy(result))
        return result

    def seed_demo(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, int]:
        payload = {"operation": "operations.seed.v1"}
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        if any(r["workspace_id"] == context.workspace_id for r in self.resources.values()):
            return self._replay_or_record(
                context, idempotency_key, payload, {"resources": 0, "queue_items": 0}
            )
        for name, typ, readiness, location in [
            ("Synthetic Water Team Alpha", "water_team", "ready", "North Sector"),
            ("Synthetic Generator Unit", "power_unit", "ready", "Central Shelter"),
            ("Synthetic Medical Van", "medical_transport", "not_ready", "East Depot"),
        ]:
            resource_id = _opaque_id("res")
            self.resources[resource_id] = {
                "id": resource_id,
                "name": name,
                "resource_type": typ,
                "readiness": readiness,
                "location": location,
                "workspace_id": context.workspace_id,
                "created_at": now.isoformat(),
                "capabilities": (
                    ["water_delivery"]
                    if typ == "water_team"
                    else ["generator"]
                    if typ == "power_unit"
                    else ["medical_transport"]
                ),
                "readiness_observed_at": now.isoformat(),
                "readiness_expires_at": (now + timedelta(hours=4)).isoformat(),
            }
        return self._replay_or_record(
            context, idempotency_key, payload, {"resources": 3, "queue_items": 0}
        )

    def list_resources(self, context: RequestContext) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.resources.values() if r["workspace_id"] == context.workspace_id
        ]

    def update_readiness(self, context, resource_id, update, now, idempotency_key):
        payload = {
            "operation": "resource.readiness.v1",
            "resource_id": resource_id,
            "update": update.model_dump(mode="json"),
        }
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        resource = self.resources.get(resource_id)
        if resource is None or resource["workspace_id"] != context.workspace_id:
            raise ResourceNotFoundError
        readiness_changed = resource["readiness"] != update.readiness or resource.get(
            "readiness_expires_at"
        ) != _iso(update.expires_at)
        resource.update(
            readiness=update.readiness,
            readiness_observed_at=update.observed_at.isoformat(),
            readiness_expires_at=_iso(update.expires_at),
        )
        if readiness_changed and self.plan_store:
            self.plan_store.invalidate_subject(
                context, "resource", resource_id, "readiness_expiry", now
            )
        return self._replay_or_record(context, idempotency_key, payload, dict(resource))

    def create_queue(
        self, context: RequestContext, item: QueueItemCreate, now: datetime, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"operation": "response_queue.create.v1", "item": item.model_dump(mode="json")}
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        item_id = _opaque_id("q")
        record = {
            "id": item_id,
            **item.model_dump(),
            "status": "queued",
            "workspace_id": context.workspace_id,
            "created_at": now.isoformat(),
        }
        self.queue[item_id] = record
        return self._replay_or_record(context, idempotency_key, payload, dict(record))

    def list_queue(
        self, context: RequestContext, queue_type: str = "response"
    ) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self.queue.values()
            if item["workspace_id"] == context.workspace_id
            and item.get("queue_type", "response") == queue_type
        ]

    def create_route_observation(self, context, observation, now, idempotency_key):
        payload = {
            "operation": "route.observe.v1",
            "observation": observation.model_dump(mode="json"),
        }
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        record = {
            "id": _opaque_id("route"),
            **observation.model_dump(mode="json"),
            "workspace_id": context.workspace_id,
            "created_at": now.isoformat(),
        }
        self.queue.setdefault("__routes__", {}) if False else None
        self.routes[record["id"]] = record
        if self.plan_store and (
            observation.state != "passable"
            or (observation.expires_at and observation.expires_at <= now)
        ):
            self.plan_store.invalidate_subject(
                context, "route", observation.destination, "route_expiry", now
            )
        return self._replay_or_record(context, idempotency_key, payload, dict(record))

    def list_route_observations(self, context):
        return [
            dict(v)
            for v in getattr(self, "routes", {}).values()
            if v["workspace_id"] == context.workspace_id
        ]

    def approve_task(
        self,
        context: RequestContext,
        queue_id: str,
        approval: TaskApproval,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "operation": "response_queue.approve.v1",
            "queue_id": queue_id,
            "approval": approval.model_dump(mode="json"),
        }
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        item = self.queue.get(queue_id)
        resource = self.resources.get(approval.resource_id)
        if item is None or item["workspace_id"] != context.workspace_id:
            raise QueueItemNotFoundError
        if resource is None or resource["workspace_id"] != context.workspace_id:
            raise ResourceNotFoundError
        if not approval.approved:
            item["status"] = "rejected"
            return self._replay_or_record(
                context,
                idempotency_key,
                payload,
                {"approved": False, "queue_item_id": queue_id, "status": "rejected"},
            )
        if resource["readiness"] != "ready":
            raise TaskConflictError("resource is not ready")
        if resource.get("readiness_expires_at") and datetime.fromisoformat(
            resource["readiness_expires_at"]
        ) <= now.replace(tzinfo=UTC):
            raise TaskConflictError("resource readiness is expired")
        required = item.get("required_capability")
        if required and required not in resource.get("capabilities", []):
            raise TaskConflictError("resource lacks required capability")
        if item.get("destination"):
            observations = [
                r
                for r in self.routes.values()
                if r["workspace_id"] == context.workspace_id
                and r["destination"] == item["destination"]
            ]
            latest = max(observations, key=lambda r: r["observed_at"], default=None)
            if (
                latest is None
                or latest["state"] != "passable"
                or latest.get("expires_at") is None
                or datetime.fromisoformat(latest["expires_at"]) <= now.replace(tzinfo=UTC)
            ):
                raise TaskConflictError("route is not confirmed passable")
        if any(
            task["resource_id"] == resource["id"] and task["status"] != "completed"
            for task in self.tasks.values()
        ):
            raise TaskConflictError("resource already has an active task")
        task_id = _opaque_id("task")
        task = {
            "id": task_id,
            "queue_item_id": queue_id,
            "resource_id": resource["id"],
            "status": "assigned",
            "approved": True,
            "approved_by": context.actor_id,
            "approved_at": now.isoformat(),
            "workspace_id": context.workspace_id,
        }
        self.tasks[task_id] = task
        item["status"] = "assigned"
        return self._replay_or_record(context, idempotency_key, payload, dict(task))

    def update_task(
        self,
        context: RequestContext,
        task_id: str,
        status: str,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"operation": "task.update.v1", "task_id": task_id, "status": status}
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        task = self.tasks.get(task_id)
        if task is None or task["workspace_id"] != context.workspace_id:
            raise TaskNotFoundError
        transitions = {
            "assigned": "acknowledged",
            "acknowledged": "en_route",
            "en_route": {"on_scene", "paused"},
            "on_scene": {"completed", "paused"},
            "paused": "en_route",
        }
        allowed = transitions.get(task["status"])
        if status not in (allowed if isinstance(allowed, set) else {allowed}):
            raise TaskConflictError(f"cannot change task from {task['status']} to {status}")
        task["status"] = status
        task["updated_at"] = now.isoformat()
        if status == "completed":
            self.queue[task["queue_item_id"]]["status"] = "completed"
        return self._replay_or_record(context, idempotency_key, payload, dict(task))

    def list_tasks(self, context: RequestContext) -> list[dict[str, Any]]:
        return [
            dict(task)
            for task in self.tasks.values()
            if task["workspace_id"] == context.workspace_id
        ]

    def record_task_outcome(self, context, task_id, outcome, now, idempotency_key):
        payload = {
            "operation": "task.outcome.v1",
            "task_id": task_id,
            "outcome": outcome.model_dump(),
        }
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        task = self.tasks.get(task_id)
        if task is None or task["workspace_id"] != context.workspace_id:
            raise TaskNotFoundError
        if task["status"] != "completed":
            raise TaskConflictError("task outcome requires completion")
        task["outcome_summary"] = outcome.summary
        task["outcome_recorded_at"] = now.isoformat()
        return self._replay_or_record(context, idempotency_key, payload, dict(task))

    def record_structured_outcome(self, context, task_id, outcome, now, idempotency_key):
        payload = {
            "operation": "task.structured_outcome.v1",
            "task_id": task_id,
            "outcome": outcome.model_dump(mode="json"),
        }
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        task = self.tasks.get(task_id)
        if task is None or task["workspace_id"] != context.workspace_id:
            raise TaskNotFoundError
        if task["status"] != "completed":
            raise TaskConflictError("structured outcome requires completion")
        quantities = {
            key: value for key, value in outcome.completion_quantities.items() if value >= 0
        }
        if len(quantities) != len(outcome.completion_quantities):
            raise TaskConflictError("completion quantities cannot be negative")
        task.update(
            completion_evidence=outcome.action_type_evidence,
            completion_quantities=quantities,
            residual_need=outcome.residual_need,
            completed_at=outcome.completed_at.isoformat(),
            verified_by=outcome.verified_by,
            outcome_summary=outcome.action_type_evidence,
            outcome_recorded_at=now.isoformat(),
        )
        resource = self.resources.get(task["resource_id"])
        if resource is not None:
            resource["capacity_value"] = round(
                float(resource.get("capacity_value") or 0) + sum(quantities.values()), 6
            )
        return self._replay_or_record(context, idempotency_key, payload, dict(task))

    def list_jobs(self, context):
        return []

    def verify_audit_chain(self, context):
        return {"available": False, "valid": None, "checked": 0}

    def reset_for_replay(self, context: RequestContext, now: datetime) -> None:
        self.resources = {
            key: value
            for key, value in self.resources.items()
            if value["workspace_id"] != context.workspace_id
        }
        self.queue = {
            key: value
            for key, value in self.queue.items()
            if value["workspace_id"] != context.workspace_id
        }
        self.tasks = {
            key: value
            for key, value in self.tasks.items()
            if value["workspace_id"] != context.workspace_id
        }
        self._idempotent = {
            key: value for key, value in self._idempotent.items() if key[1] != context.workspace_id
        }


class PostgreSQLOperationsStore:
    """Durable operations state. PostgreSQL owns all shared runtime state."""

    def __init__(self, database_url: str, plan_store: PlanStore | None = None) -> None:
        self.database_url = database_url
        self.plan_store = plan_store

    def _connection(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor: Any, context: RequestContext, now: datetime) -> None:
        cursor.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (context.tenant_id, "Development demo organization", now),
        )
        cursor.execute(
            "INSERT INTO event_workspaces (id, organization_id, name, mode, status, event_time, created_at) VALUES (%s, %s, %s, 'replay', 'active', %s, %s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Development demo event", now, now),
        )
        cursor.execute(
            "INSERT INTO memberships (organization_id, actor_id, role, created_at) VALUES (%s, %s, %s, %s) ON CONFLICT (organization_id, actor_id) DO NOTHING",
            (context.tenant_id, context.actor_id, context.role, now),
        )

    @staticmethod
    def _idempotent(
        cursor: Any, context: RequestContext, key: str, payload: Any
    ) -> dict[str, Any] | None:
        digest = _request_hash(payload)
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"{context.tenant_id}:{context.workspace_id}:{key}",),
        )
        cursor.execute(
            "SELECT request_hash, response_body FROM idempotency_records WHERE organization_id = %s AND workspace_id = %s AND idempotency_key = %s",
            (context.tenant_id, context.workspace_id, key),
        )
        existing = cursor.fetchone()
        if existing is None:
            return None
        if existing[0] != digest:
            raise IdempotencyConflictError
        return existing[1]

    @staticmethod
    def _record_idempotency(
        cursor: Any,
        context: RequestContext,
        key: str,
        payload: Any,
        response: dict[str, Any],
        now: datetime,
    ) -> None:
        cursor.execute(
            "INSERT INTO idempotency_records (organization_id, workspace_id, idempotency_key, request_hash, response_status, response_body, created_at, expires_at) VALUES (%s, %s, %s, %s, 200, %s, %s, %s)",
            (
                context.tenant_id,
                context.workspace_id,
                key,
                _request_hash(payload),
                Jsonb(response),
                now,
                now.replace(year=now.year + 1),
            ),
        )

    @staticmethod
    def _audit(
        cursor: Any,
        context: RequestContext,
        action: str,
        subject_type: str,
        subject_id: str,
        details: dict[str, Any],
        now: datetime,
    ) -> None:
        cursor.execute(
            "SELECT event_hash FROM audit_events WHERE organization_id=%s AND workspace_id=%s AND event_hash IS NOT NULL ORDER BY chain_sequence DESC LIMIT 1",
            (context.tenant_id, context.workspace_id),
        )
        previous = cursor.fetchone()
        previous_hash = previous[0] if previous else None
        event_hash = _request_hash(
            {
                "previous_hash": previous_hash,
                "action": action,
                "subject_id": subject_id,
                "occurred_at": now.isoformat(),
                "details": details,
            }
        )
        cursor.execute(
            "INSERT INTO audit_events (id, organization_id, workspace_id, actor_id, action, subject_type, subject_id, correlation_id, occurred_at, recorded_at, details, previous_hash, event_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                _opaque_id("evt"),
                context.tenant_id,
                context.workspace_id,
                context.actor_id,
                action,
                subject_type,
                subject_id,
                context.correlation_id,
                now,
                now,
                Jsonb(details),
                previous_hash,
                event_hash,
            ),
        )

    def seed_demo(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, int]:
        payload = {"operation": "operations.seed.v1"}
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "SELECT count(*) FROM resources WHERE organization_id = %s AND workspace_id = %s",
                (context.tenant_id, context.workspace_id),
            )
            if cursor.fetchone()[0]:
                response = {"resources": 0, "queue_items": 0}
            else:
                cursor.executemany(
                    "INSERT INTO resources (organization_id, workspace_id, name, resource_type, readiness, location, capabilities, readiness_observed_at, readiness_expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            context.tenant_id,
                            context.workspace_id,
                            name,
                            resource_type,
                            readiness,
                            location,
                            Jsonb(
                                ["water_delivery"]
                                if resource_type == "water_team"
                                else ["generator"]
                                if resource_type == "power_unit"
                                else ["medical_transport"]
                            ),
                            now,
                            now + timedelta(hours=4),
                            now,
                        )
                        for name, resource_type, readiness, location in [
                            ("Synthetic Water Team Alpha", "water_team", "ready", "North Sector"),
                            ("Synthetic Generator Unit", "power_unit", "ready", "Central Shelter"),
                            (
                                "Synthetic Medical Van",
                                "medical_transport",
                                "not_ready",
                                "East Depot",
                            ),
                        ]
                    ],
                )
                response = {"resources": 3, "queue_items": 0}
            self._audit(
                cursor,
                context,
                "operations.seeded",
                "workspace",
                context.workspace_id,
                response,
                now,
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def list_resources(self, context: RequestContext) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, resource_type, readiness, location, capabilities, readiness_observed_at, readiness_expires_at, created_at FROM resources WHERE organization_id = %s AND workspace_id = %s ORDER BY created_at, id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "id": str(row[0]),
                    "name": row[1],
                    "resource_type": row[2],
                    "readiness": row[3],
                    "location": row[4],
                    "capabilities": row[5],
                    "readiness_observed_at": _iso(row[6]),
                    "readiness_expires_at": _iso(row[7]),
                    "created_at": _iso(row[8]),
                }
                for row in cursor.fetchall()
            ]

    def update_readiness(self, context, resource_id, update, now, idempotency_key):
        payload = {
            "operation": "resource.readiness.v1",
            "resource_id": resource_id,
            "update": update.model_dump(mode="json"),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "SELECT readiness, readiness_expires_at FROM resources WHERE id=%s AND organization_id=%s AND workspace_id=%s FOR UPDATE",
                (resource_id, context.tenant_id, context.workspace_id),
            )
            previous = cursor.fetchone()
            if previous is None:
                raise ResourceNotFoundError
            cursor.execute(
                "UPDATE resources SET readiness=%s, readiness_observed_at=%s, readiness_expires_at=%s WHERE id=%s AND organization_id=%s AND workspace_id=%s RETURNING id, name, resource_type, readiness, location, capabilities, readiness_observed_at, readiness_expires_at, created_at",
                (
                    update.readiness,
                    update.observed_at,
                    update.expires_at,
                    resource_id,
                    context.tenant_id,
                    context.workspace_id,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise ResourceNotFoundError
            response = {
                "id": str(row[0]),
                "name": row[1],
                "resource_type": row[2],
                "readiness": row[3],
                "location": row[4],
                "capabilities": row[5],
                "readiness_observed_at": _iso(row[6]),
                "readiness_expires_at": _iso(row[7]),
                "created_at": _iso(row[8]),
            }
            self._audit(
                cursor,
                context,
                "resource.readiness_updated",
                "resource",
                resource_id,
                {"readiness": update.readiness},
                now,
            )
            if self.plan_store and (
                previous[0] != update.readiness or previous[1] != update.expires_at
            ):
                self.plan_store.invalidate_subject(
                    context, "resource", resource_id, "readiness_expiry", now
                )
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def create_queue(
        self, context: RequestContext, item: QueueItemCreate, now: datetime, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"operation": "response_queue.create.v1", "item": item.model_dump(mode="json")}
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "INSERT INTO response_queue_items (organization_id, workspace_id, title, priority, destination, notes, queue_type, required_capability, owner_actor_id, due_at, source_report_id, source_incident_id, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', %s) RETURNING id, title, priority, destination, notes, queue_type, required_capability, owner_actor_id, due_at, source_report_id, source_incident_id, status, created_at",
                (
                    context.tenant_id,
                    context.workspace_id,
                    item.title,
                    item.priority,
                    item.destination,
                    item.notes,
                    item.queue_type,
                    item.required_capability,
                    item.owner_actor_id,
                    item.due_at,
                    item.source_report_id,
                    item.source_incident_id,
                    now,
                ),
            )
            row = cursor.fetchone()
            response = {
                "id": str(row[0]),
                "title": row[1],
                "priority": row[2],
                "destination": row[3],
                "notes": row[4],
                "queue_type": row[5],
                "required_capability": row[6],
                "owner_actor_id": row[7],
                "due_at": _iso(row[8]),
                "source_report_id": row[9],
                "source_incident_id": row[10],
                "status": row[11],
                "created_at": _iso(row[12]),
            }
            self._audit(
                cursor,
                context,
                "response_queue.created",
                "queue_item",
                response["id"],
                {"priority": item.priority},
                now,
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def list_queue(
        self, context: RequestContext, queue_type: str = "response"
    ) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, priority, destination, notes, queue_type, required_capability, owner_actor_id, due_at, source_report_id, source_incident_id, status, created_at FROM response_queue_items WHERE organization_id = %s AND workspace_id = %s AND queue_type = %s ORDER BY created_at, id",
                (context.tenant_id, context.workspace_id, queue_type),
            )
            return [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "priority": row[2],
                    "destination": row[3],
                    "notes": row[4],
                    "queue_type": row[5],
                    "required_capability": row[6],
                    "owner_actor_id": row[7],
                    "due_at": _iso(row[8]),
                    "source_report_id": row[9],
                    "source_incident_id": row[10],
                    "status": row[11],
                    "created_at": _iso(row[12]),
                }
                for row in cursor.fetchall()
            ]

    def create_route_observation(self, context, observation, now, idempotency_key):
        payload = {
            "operation": "route.observe.v1",
            "observation": observation.model_dump(mode="json"),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "INSERT INTO route_observations (organization_id, workspace_id, destination, state, source, observed_at, expires_at, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, destination, state, source, observed_at, expires_at, created_at",
                (
                    context.tenant_id,
                    context.workspace_id,
                    observation.destination,
                    observation.state,
                    observation.source,
                    observation.observed_at,
                    observation.expires_at,
                    now,
                ),
            )
            row = cursor.fetchone()
            response = {
                "id": str(row[0]),
                "destination": row[1],
                "state": row[2],
                "source": row[3],
                "observed_at": _iso(row[4]),
                "expires_at": _iso(row[5]),
                "created_at": _iso(row[6]),
            }
            self._audit(
                cursor,
                context,
                "route.observed",
                "route",
                response["id"],
                {"destination": observation.destination, "state": observation.state},
                now,
            )
            if self.plan_store and (
                observation.state != "passable"
                or (observation.expires_at and observation.expires_at <= now)
            ):
                self.plan_store.invalidate_subject(
                    context, "route", observation.destination, "route_expiry", now
                )
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def list_route_observations(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, destination, state, source, observed_at, expires_at, created_at FROM route_observations WHERE organization_id=%s AND workspace_id=%s ORDER BY observed_at DESC, id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "id": str(r[0]),
                    "destination": r[1],
                    "state": r[2],
                    "source": r[3],
                    "observed_at": _iso(r[4]),
                    "expires_at": _iso(r[5]),
                    "created_at": _iso(r[6]),
                }
                for r in cursor.fetchall()
            ]

    def approve_task(
        self,
        context: RequestContext,
        queue_id: str,
        approval: TaskApproval,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "operation": "response_queue.approve.v1",
            "queue_id": queue_id,
            "approval": approval.model_dump(mode="json"),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "SELECT id, required_capability, destination FROM response_queue_items WHERE id = %s AND organization_id = %s AND workspace_id = %s FOR UPDATE",
                (queue_id, context.tenant_id, context.workspace_id),
            )
            queue_row = cursor.fetchone()
            if queue_row is None:
                raise QueueItemNotFoundError
            cursor.execute(
                "SELECT id, readiness, capabilities, readiness_expires_at FROM resources WHERE id = %s AND organization_id = %s AND workspace_id = %s FOR UPDATE",
                (approval.resource_id, context.tenant_id, context.workspace_id),
            )
            resource = cursor.fetchone()
            if resource is None:
                raise ResourceNotFoundError
            if not approval.approved:
                cursor.execute(
                    "UPDATE response_queue_items SET status = 'rejected' WHERE id = %s", (queue_id,)
                )
                response = {"approved": False, "queue_item_id": queue_id, "status": "rejected"}
                self._audit(
                    cursor,
                    context,
                    "task.rejected",
                    "queue_item",
                    queue_id,
                    {"note": approval.approval_note},
                    now,
                )
                self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
                return response
            if resource[1] != "ready":
                raise TaskConflictError("resource is not ready")
            if resource[3] is not None and resource[3] <= now:
                raise TaskConflictError("resource readiness is expired")
            if queue_row[1] and queue_row[1] not in (resource[2] or []):
                raise TaskConflictError("resource lacks required capability")
            cursor.execute(
                "SELECT state, expires_at, destination FROM route_observations WHERE organization_id=%s AND workspace_id=%s AND destination=(SELECT destination FROM response_queue_items WHERE id=%s) ORDER BY observed_at DESC LIMIT 1",
                (context.tenant_id, context.workspace_id, queue_id),
            )
            route = cursor.fetchone()
            if queue_row[2] is not None and (
                route is None or route[0] != "passable" or route[1] is None or route[1] <= now
            ):
                raise TaskConflictError("route is not confirmed passable")
            try:
                cursor.execute(
                    "INSERT INTO response_tasks (organization_id, workspace_id, queue_item_id, resource_id, status, approved_by, approved_at) VALUES (%s, %s, %s, %s, 'assigned', %s, %s) RETURNING id, queue_item_id, resource_id, status, approved_by, approved_at, updated_at",
                    (
                        context.tenant_id,
                        context.workspace_id,
                        queue_id,
                        approval.resource_id,
                        context.actor_id,
                        now,
                    ),
                )
            except psycopg.errors.UniqueViolation:
                raise TaskConflictError("resource already has an active task") from None
            response = _task_record(cursor.fetchone())
            cursor.execute(
                "UPDATE response_queue_items SET status = 'assigned' WHERE id = %s", (queue_id,)
            )
            self._audit(
                cursor,
                context,
                "task.approved",
                "task",
                response["id"],
                {
                    "queue_item_id": queue_id,
                    "resource_id": approval.resource_id,
                    "note": approval.approval_note,
                },
                now,
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def update_task(
        self,
        context: RequestContext,
        task_id: str,
        status: str,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"operation": "task.update.v1", "task_id": task_id, "status": status}
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "SELECT id, queue_item_id, resource_id, status, approved_by, approved_at, updated_at FROM response_tasks WHERE id = %s AND organization_id = %s AND workspace_id = %s FOR UPDATE",
                (task_id, context.tenant_id, context.workspace_id),
            )
            task = cursor.fetchone()
            if task is None:
                raise TaskNotFoundError
            transitions = {
                "assigned": "acknowledged",
                "acknowledged": "en_route",
                "en_route": {"on_scene", "paused"},
                "on_scene": {"completed", "paused"},
                "paused": "en_route",
            }
            allowed = transitions.get(task[3])
            if status not in (allowed if isinstance(allowed, set) else {allowed}):
                raise TaskConflictError(f"cannot change task from {task[3]} to {status}")
            cursor.execute(
                "UPDATE response_tasks SET status = %s, updated_at = %s WHERE id = %s RETURNING id, queue_item_id, resource_id, status, approved_by, approved_at, updated_at",
                (status, now, task_id),
            )
            response = _task_record(cursor.fetchone())
            if status == "completed":
                cursor.execute(
                    "UPDATE response_queue_items SET status = 'completed' WHERE id = %s",
                    (task[1],),
                )
            self._audit(
                cursor, context, "task.status_updated", "task", task_id, {"status": status}, now
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def list_tasks(self, context: RequestContext) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, queue_item_id, resource_id, status, approved_by, approved_at, updated_at FROM response_tasks WHERE organization_id = %s AND workspace_id = %s ORDER BY approved_at, id",
                (context.tenant_id, context.workspace_id),
            )
            return [_task_record(row) for row in cursor.fetchall()]

    def record_task_outcome(self, context, task_id, outcome, now, idempotency_key):
        payload = {
            "operation": "task.outcome.v1",
            "task_id": task_id,
            "outcome": outcome.model_dump(),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "SELECT queue_item_id, status FROM response_tasks WHERE id=%s AND organization_id=%s AND workspace_id=%s FOR UPDATE",
                (task_id, context.tenant_id, context.workspace_id),
            )
            task = cursor.fetchone()
            if task is None:
                raise TaskNotFoundError
            if task[1] != "completed":
                raise TaskConflictError("task outcome requires completion")
            cursor.execute(
                "UPDATE response_tasks SET outcome_summary=%s, outcome_recorded_at=%s WHERE id=%s",
                (outcome.summary, now, task_id),
            )
            cursor.execute(
                "UPDATE recommendations SET outcome_summary=%s, outcome_at=%s WHERE organization_id=%s AND workspace_id=%s AND queue_item_id=%s",
                (outcome.summary, now, context.tenant_id, context.workspace_id, task[0]),
            )
            response = {
                "task_id": task_id,
                "queue_item_id": str(task[0]),
                "outcome_summary": outcome.summary,
                "outcome_recorded_at": now.isoformat(),
            }
            self._audit(cursor, context, "task.outcome_recorded", "task", task_id, response, now)
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def record_structured_outcome(self, context, task_id, outcome, now, idempotency_key):
        payload = {
            "operation": "task.structured_outcome.v1",
            "task_id": task_id,
            "outcome": outcome.model_dump(mode="json"),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "SELECT queue_item_id,resource_id,status FROM response_tasks WHERE id=%s AND organization_id=%s AND workspace_id=%s FOR UPDATE",
                (task_id, context.tenant_id, context.workspace_id),
            )
            task = cursor.fetchone()
            if task is None:
                raise TaskNotFoundError
            if task[2] != "completed":
                raise TaskConflictError("structured outcome requires completion")
            quantities = {
                key: value for key, value in outcome.completion_quantities.items() if value >= 0
            }
            if len(quantities) != len(outcome.completion_quantities):
                raise TaskConflictError("completion quantities cannot be negative")
            cursor.execute(
                "UPDATE response_tasks SET completion_evidence=%s,completion_quantities=%s,residual_need=%s,completed_at=%s,verified_by=%s,outcome_summary=%s,outcome_recorded_at=%s WHERE id=%s",
                (
                    outcome.action_type_evidence,
                    Jsonb(quantities),
                    outcome.residual_need,
                    outcome.completed_at,
                    outcome.verified_by,
                    outcome.action_type_evidence,
                    now,
                    task_id,
                ),
            )
            cursor.execute(
                "UPDATE resources SET capacity_value=COALESCE(capacity_value,0)+%s WHERE id=%s AND organization_id=%s AND workspace_id=%s",
                (sum(quantities.values()), task[1], context.tenant_id, context.workspace_id),
            )
            response = {
                "task_id": task_id,
                "queue_item_id": str(task[0]),
                "completion_evidence": outcome.action_type_evidence,
                "completion_quantities": quantities,
                "residual_need": outcome.residual_need,
                "completed_at": _iso(outcome.completed_at),
                "verified_by": outcome.verified_by,
                "outcome_recorded_at": _iso(now),
            }
            self._audit(
                cursor, context, "task.structured_outcome_recorded", "task", task_id, response, now
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, response, now)
            return response

    def list_jobs(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, job_type, status, attempt_count, last_error_code, updated_at FROM jobs WHERE organization_id=%s AND workspace_id=%s ORDER BY updated_at DESC, id LIMIT 100",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "id": str(r[0]),
                    "job_type": r[1],
                    "status": r[2],
                    "attempt_count": r[3],
                    "last_error_code": r[4],
                    "updated_at": _iso(r[5]),
                }
                for r in cursor.fetchall()
            ]

    def verify_audit_chain(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, action, subject_id, occurred_at, details, previous_hash, event_hash FROM audit_events WHERE organization_id=%s AND workspace_id=%s AND event_hash IS NOT NULL ORDER BY chain_sequence",
                (context.tenant_id, context.workspace_id),
            )
            previous_hash = None
            checked = 0
            for (
                event_id,
                action,
                subject_id,
                occurred_at,
                details,
                stored_previous,
                event_hash,
            ) in cursor:
                expected_hash = _request_hash(
                    {
                        "previous_hash": previous_hash,
                        "action": action,
                        "subject_id": subject_id,
                        "occurred_at": occurred_at.isoformat(),
                        "details": details,
                    }
                )
                checked += 1
                if stored_previous != previous_hash or event_hash != expected_hash:
                    return {
                        "available": True,
                        "valid": False,
                        "checked": checked,
                        "failure_id": event_id,
                    }
                previous_hash = event_hash
            return {"available": True, "valid": True, "checked": checked}

    def reset_for_replay(self, context: RequestContext, now: datetime) -> None:
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "DELETE FROM response_tasks WHERE organization_id = %s AND workspace_id = %s",
                (context.tenant_id, context.workspace_id),
            )
            cursor.execute(
                "DELETE FROM response_queue_items WHERE organization_id = %s AND workspace_id = %s",
                (context.tenant_id, context.workspace_id),
            )
            cursor.execute(
                "DELETE FROM resources WHERE organization_id = %s AND workspace_id = %s",
                (context.tenant_id, context.workspace_id),
            )
