# ruff: noqa: E501

"""Scoped incident activation and command-role state for the operational shell."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext

INCIDENT_STATUSES = {"draft", "active", "paused", "closed"}
INCIDENT_PHASES = {"activation", "size_up", "search_rescue", "stabilization", "handover"}
ROLE_NAMES = {
    "incident_commander",
    "operations_lead",
    "planning_lead",
    "logistics_lead",
    "medical_lead",
}


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    hazard_type: str = Field(
        pattern="^(flood|earthquake|landslide|cyclone|structural_collapse|multi_hazard|other)$"
    )
    severity: str = Field(default="high", pattern="^(low|moderate|high|critical)$")
    operational_period: str = Field(default="OP-1", min_length=1, max_length=32)
    summary: str = Field(min_length=1, max_length=500)
    event_time: datetime


class IncidentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(active|paused|closed)$")
    phase: str | None = Field(
        default=None, pattern="^(activation|size_up|search_rescue|stabilization|handover)$"
    )
    note: str | None = Field(default=None, max_length=500)


class CommandRoleAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(
        pattern="^(incident_commander|operations_lead|planning_lead|logistics_lead|medical_lead)$"
    )
    actor_id: str = Field(min_length=1, max_length=128)


class SectorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    owner_actor_id: str = Field(min_length=1, max_length=128)
    assessment_state: str = Field(
        default="unassessed", pattern="^(unassessed|assessed|inaccessible|closed)$"
    )


class IncidentNotFoundError(Exception):
    pass


class IncidentConflictError(Exception):
    pass


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class IncidentStore(Protocol):
    def create_incident(
        self, context: RequestContext, incident: IncidentCreate, now: datetime
    ) -> dict[str, Any]: ...
    def list_incidents(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def get_incident(self, context: RequestContext, incident_id: str) -> dict[str, Any]: ...
    def get_active_incident(self, context: RequestContext) -> dict[str, Any] | None: ...
    def transition(
        self, context: RequestContext, incident_id: str, update: IncidentTransition, now: datetime
    ) -> dict[str, Any]: ...
    def assign_role(
        self,
        context: RequestContext,
        incident_id: str,
        assignment: CommandRoleAssignment,
        now: datetime,
    ) -> dict[str, Any]: ...
    def create_sector(
        self, context: RequestContext, incident_id: str, sector: SectorCreate, now: datetime
    ) -> dict[str, Any]: ...
    def list_sectors(self, context: RequestContext, incident_id: str) -> list[dict[str, Any]]: ...


def _validate_transition(current: str, target: str) -> None:
    allowed = {
        "draft": {"active"},
        "active": {"paused", "closed"},
        "paused": {"active", "closed"},
        "closed": set(),
    }
    if target not in allowed[current]:
        raise IncidentConflictError(f"cannot transition incident from {current} to {target}")


class InMemoryIncidentStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.incidents: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.sectors: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _get(self, context, incident_id):
        incident = self.incidents.get((context.tenant_id, context.workspace_id, incident_id))
        if incident is None:
            raise IncidentNotFoundError
        return incident

    def create_incident(self, context, incident, now):
        with self._lock:
            if self.get_active_incident(context) is not None:
                raise IncidentConflictError("an active incident already exists in this workspace")
            incident_id = f"inc_{uuid4().hex}"
            record = {
                "incident_id": incident_id,
                "organization_id": context.tenant_id,
                "workspace_id": context.workspace_id,
                **incident.model_dump(mode="json"),
                "status": "draft",
                "phase": "activation",
                "roles": {},
                "created_by": context.actor_id,
                "created_at": _iso(now),
                "updated_at": _iso(now),
            }
            self.incidents[(context.tenant_id, context.workspace_id, incident_id)] = record
            return copy.deepcopy(record)

    def list_incidents(self, context):
        return copy.deepcopy(
            [
                item
                for item in self.incidents.values()
                if item["organization_id"] == context.tenant_id
                and item["workspace_id"] == context.workspace_id
            ]
        )

    def get_incident(self, context, incident_id):
        return copy.deepcopy(self._get(context, incident_id))

    def get_active_incident(self, context):
        matches = [
            item for item in self.list_incidents(context) if item["status"] in {"active", "paused"}
        ]
        return matches[0] if matches else None

    def transition(self, context, incident_id, update, now):
        with self._lock:
            incident = self._get(context, incident_id)
            _validate_transition(incident["status"], update.status)
            if (
                update.status == "active"
                and incident["status"] == "draft"
                and "incident_commander" not in incident["roles"]
            ):
                raise IncidentConflictError("incident commander must be assigned before activation")
            if (
                update.status == "active"
                and self.get_active_incident(context)
                and self.get_active_incident(context)["incident_id"] != incident_id
            ):
                raise IncidentConflictError("an active incident already exists in this workspace")
            incident["status"] = update.status
            if update.phase:
                incident["phase"] = update.phase
            incident["updated_at"] = _iso(now)
            if update.note:
                incident["transition_note"] = update.note
            return copy.deepcopy(incident)

    def assign_role(self, context, incident_id, assignment, now):
        with self._lock:
            incident = self._get(context, incident_id)
            if incident["status"] == "closed":
                raise IncidentConflictError("closed incidents cannot receive command assignments")
            incident["roles"][assignment.role] = assignment.actor_id
            incident["updated_at"] = _iso(now)
            return copy.deepcopy(incident)

    def create_sector(self, context, incident_id, sector, now):
        with self._lock:
            incident = self._get(context, incident_id)
            if incident["status"] == "closed":
                raise IncidentConflictError("closed incidents cannot receive sectors")
            if any(
                item["incident_id"] == incident_id and item["name"] == sector.name
                for item in self.sectors.values()
            ):
                raise IncidentConflictError("sector names must be unique within an incident")
            sector_id = f"sector_{uuid4().hex}"
            record = {
                "sector_id": sector_id,
                "incident_id": incident_id,
                "organization_id": context.tenant_id,
                "workspace_id": context.workspace_id,
                **sector.model_dump(),
                "created_at": _iso(now),
                "updated_at": _iso(now),
            }
            self.sectors[(context.tenant_id, context.workspace_id, sector_id)] = record
            return copy.deepcopy(record)

    def list_sectors(self, context, incident_id):
        self._get(context, incident_id)
        return copy.deepcopy(
            [
                item
                for item in self.sectors.values()
                if item["organization_id"] == context.tenant_id
                and item["workspace_id"] == context.workspace_id
                and item["incident_id"] == incident_id
            ]
        )


class PostgreSQLIncidentStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connection(self):
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor, context, now):
        cursor.execute(
            "INSERT INTO organizations (id,name,created_at) VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.tenant_id, "Development demo organization", now),
        )
        cursor.execute(
            "INSERT INTO event_workspaces (id,organization_id,name,mode,status,event_time,created_at) VALUES (%s,%s,%s,'live','active',%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Operational incident workspace", now, now),
        )

    @staticmethod
    def _row(row):
        return {
            "incident_id": str(row[0]),
            "organization_id": row[1],
            "workspace_id": row[2],
            "name": row[3],
            "hazard_type": row[4],
            "severity": row[5],
            "summary": row[6],
            "operational_period": row[7],
            "event_time": _iso(row[8]),
            "status": row[9],
            "phase": row[10],
            "roles": row[11] or {},
            "created_by": row[12],
            "created_at": _iso(row[13]),
            "updated_at": _iso(row[14]),
        }

    def create_incident(self, context, incident, now):
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "SELECT 1 FROM incidents WHERE organization_id=%s AND workspace_id=%s AND status IN ('active','paused')",
                (context.tenant_id, context.workspace_id),
            )
            if cursor.fetchone():
                raise IncidentConflictError("an active incident already exists in this workspace")
            incident_id = f"inc_{uuid4().hex}"
            cursor.execute(
                "INSERT INTO incidents (incident_id,organization_id,workspace_id,name,hazard_type,severity,operational_period,summary,event_time,status,phase,roles,created_by,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft','activation','{}',%s,%s,%s)",
                (
                    incident_id,
                    context.tenant_id,
                    context.workspace_id,
                    incident.name,
                    incident.hazard_type,
                    incident.severity,
                    incident.operational_period,
                    incident.summary,
                    incident.event_time,
                    context.actor_id,
                    now,
                    now,
                ),
            )
            connection.commit()
            return self.get_incident(context, incident_id)

    def get_incident(self, context, incident_id):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT incident_id,organization_id,workspace_id,name,hazard_type,severity,operational_period,summary,event_time,status,phase,roles,created_by,created_at,updated_at FROM incidents WHERE incident_id=%s AND organization_id=%s AND workspace_id=%s",
                (incident_id, context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise IncidentNotFoundError
            return self._row(row)

    def list_incidents(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT incident_id,organization_id,workspace_id,name,hazard_type,severity,operational_period,summary,event_time,status,phase,roles,created_by,created_at,updated_at FROM incidents WHERE organization_id=%s AND workspace_id=%s ORDER BY created_at,incident_id",
                (context.tenant_id, context.workspace_id),
            )
            return [self._row(row) for row in cursor.fetchall()]

    def get_active_incident(self, context):
        matches = [
            item for item in self.list_incidents(context) if item["status"] in {"active", "paused"}
        ]
        return matches[0] if matches else None

    def transition(self, context, incident_id, update, now):
        incident = self.get_incident(context, incident_id)
        _validate_transition(incident["status"], update.status)
        if (
            update.status == "active"
            and incident["status"] == "draft"
            and "incident_commander" not in incident["roles"]
        ):
            raise IncidentConflictError("incident commander must be assigned before activation")
        active = self.get_active_incident(context)
        if update.status == "active" and active and active["incident_id"] != incident_id:
            raise IncidentConflictError("an active incident already exists in this workspace")
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE incidents SET status=%s,phase=COALESCE(%s,phase),updated_at=%s WHERE incident_id=%s AND organization_id=%s AND workspace_id=%s",
                (
                    update.status,
                    update.phase,
                    now,
                    incident_id,
                    context.tenant_id,
                    context.workspace_id,
                ),
            )
        return self.get_incident(context, incident_id)

    def assign_role(self, context, incident_id, assignment, now):
        incident = self.get_incident(context, incident_id)
        if incident["status"] == "closed":
            raise IncidentConflictError("closed incidents cannot receive command assignments")
        roles = {**incident["roles"], assignment.role: assignment.actor_id}
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE incidents SET roles=%s,updated_at=%s WHERE incident_id=%s AND organization_id=%s AND workspace_id=%s",
                (Jsonb(roles), now, incident_id, context.tenant_id, context.workspace_id),
            )
        return self.get_incident(context, incident_id)

    def create_sector(self, context, incident_id, sector, now):
        incident = self.get_incident(context, incident_id)
        if incident["status"] == "closed":
            raise IncidentConflictError("closed incidents cannot receive sectors")
        sector_id = f"sector_{uuid4().hex}"
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO incident_sectors (sector_id,incident_id,organization_id,workspace_id,name,owner_actor_id,assessment_state,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING sector_id,incident_id,organization_id,workspace_id,name,owner_actor_id,assessment_state,created_at,updated_at",
                (
                    sector_id,
                    incident_id,
                    context.tenant_id,
                    context.workspace_id,
                    sector.name,
                    sector.owner_actor_id,
                    sector.assessment_state,
                    now,
                    now,
                ),
            )
            row = cursor.fetchone()
        return self._sector_row(row)

    @staticmethod
    def _sector_row(row):
        return {
            "sector_id": str(row[0]),
            "incident_id": str(row[1]),
            "organization_id": row[2],
            "workspace_id": row[3],
            "name": row[4],
            "owner_actor_id": row[5],
            "assessment_state": row[6],
            "created_at": _iso(row[7]),
            "updated_at": _iso(row[8]),
        }

    def list_sectors(self, context, incident_id):
        self.get_incident(context, incident_id)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT sector_id,incident_id,organization_id,workspace_id,name,owner_actor_id,assessment_state,created_at,updated_at FROM incident_sectors WHERE incident_id=%s AND organization_id=%s AND workspace_id=%s ORDER BY created_at,sector_id",
                (incident_id, context.tenant_id, context.workspace_id),
            )
            return [self._sector_row(row) for row in cursor.fetchall()]
