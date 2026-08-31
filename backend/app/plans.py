# ruff: noqa: E501

"""Plan alternatives, named assumptions, selective invalidation, and certificates."""

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

PLAN_VERSION = "plan_v1"
CERTIFICATE_VERSION = "certificate_v1"
ACTIVE_STATUSES = {"draft", "feasible", "selected", "approved", "review_required"}


class PlanActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_class: str = Field(pattern=r"^(response|verification|unlock)$")
    action_type: str = Field(min_length=1, max_length=120)
    target_ref: str | None = None
    resource_id: str | None = None
    route_ref: str | None = None
    timing_hours: float | None = Field(default=None, ge=0)
    expected_effect: str | None = None


class PlanAssumptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_type: str = Field(pattern=r"^(claim|route|resource|coverage_cell|infrastructure_node)$")
    subject_id: str = Field(min_length=1, max_length=160)
    expected_state: str = Field(min_length=1, max_length=160)
    sensitivity: str = Field(default="medium", pattern=r"^(critical|high|medium|low)$")
    valid_until: datetime | None = None


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_summary: str = Field(min_length=1, max_length=500)
    policy_version: str = Field(min_length=1, max_length=120)
    horizon_hours: float = Field(gt=0, le=168)
    actions: list[PlanActionCreate] = Field(min_length=1, max_length=20)
    assumptions: list[PlanAssumptionCreate] = Field(default_factory=list, max_length=50)
    input_snapshot_hash: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None


class CertificateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_plan_id: str
    alternative_plan_ids: list[str] = Field(default_factory=list, max_length=20)
    input_snapshot_hash: str
    exclusions: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    policy_version: str
    assumptions_snapshot: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    approver_id: str
    dissent_note: str | None = Field(default=None, max_length=500)


class InvalidationResult(BaseModel):
    invalidation_id: str
    plan_id: str
    trigger_type: str
    trigger_ref: str
    assumption_id: str
    detected_at: str


def find_affected_plans(
    changed_subject_type: str, changed_subject_id: str, active_plans: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(plan)
        for plan in active_plans
        if plan.get("status") in ACTIVE_STATUSES
        and any(
            assumption.get("subject_type") == changed_subject_type
            and assumption.get("subject_id") == changed_subject_id
            for assumption in plan.get("assumptions", [])
        )
    ]


def compute_plan_fragility(plan: dict[str, Any]) -> float:
    assumptions = plan.get("assumptions", [])
    sensitivity = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    weighted = sum(sensitivity.get(item.get("sensitivity", "medium"), 2) for item in assumptions)
    margin = float(plan.get("constraint_margin", plan.get("feasibility_margin", 1.0)) or 1.0)
    return round(weighted / max(margin, 0.01), 6)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


class PlanStore(Protocol):
    def create_plan(
        self, context: RequestContext, plan: PlanCreate, now: datetime
    ) -> dict[str, Any]: ...
    def list_plans(
        self, context: RequestContext, status: str | None = None
    ) -> list[dict[str, Any]]: ...
    def get_plan(self, context: RequestContext, plan_id: str) -> dict[str, Any]: ...
    def check_assumptions(
        self, context: RequestContext, plan_id: str, now: datetime
    ) -> list[dict[str, Any]]: ...
    def invalidate_plan(
        self,
        context: RequestContext,
        plan_id: str,
        trigger_type: str,
        trigger_ref: str,
        now: datetime,
    ) -> dict[str, Any]: ...
    def invalidate_subject(
        self,
        context: RequestContext,
        subject_type: str,
        subject_id: str,
        trigger_type: str,
        now: datetime,
    ) -> list[dict[str, Any]]: ...
    def create_certificate(
        self, context: RequestContext, certificate: CertificateCreate, now: datetime
    ) -> dict[str, Any]: ...
    def get_certificate(self, context: RequestContext, certificate_id: str) -> dict[str, Any]: ...


class PlanNotFoundError(Exception):
    pass


class PlanConflictError(Exception):
    pass


class InMemoryPlanStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.plans: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.certificates: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _plan(self, context, plan_id):
        plan = self.plans.get((context.tenant_id, context.workspace_id, plan_id))
        if plan is None:
            raise PlanNotFoundError
        return plan

    def create_plan(self, context, plan, now):
        plan_id = f"plan_{uuid4().hex}"
        record = {
            "plan_id": plan_id,
            "organization_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "status": "feasible",
            **plan.model_dump(mode="json"),
            "actions": [item.model_dump(mode="json") for item in plan.actions],
            "assumptions": [
                {"assumption_id": f"asm_{uuid4().hex}", **item.model_dump(mode="json")}
                for item in plan.assumptions
            ],
            "fragility": compute_plan_fragility(
                {"assumptions": [item.model_dump() for item in plan.assumptions]}
            ),
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        self.plans[(context.tenant_id, context.workspace_id, plan_id)] = record
        return copy.deepcopy(record)

    def list_plans(self, context, status=None):
        rows = [
            plan
            for plan in self.plans.values()
            if plan["organization_id"] == context.tenant_id
            and plan["workspace_id"] == context.workspace_id
            and (status is None or plan["status"] == status)
        ]
        return copy.deepcopy(rows)

    def get_plan(self, context, plan_id):
        return copy.deepcopy(self._plan(context, plan_id))

    def check_assumptions(self, context, plan_id, now):
        plan = self._plan(context, plan_id)
        results = []
        for assumption in plan["assumptions"]:
            expires = assumption.get("valid_until")
            if expires and datetime.fromisoformat(expires) <= now.astimezone(UTC):
                results.append(
                    self.invalidate_plan(
                        context,
                        plan_id,
                        "manual",
                        f"expired:{assumption['assumption_id']}",
                        now,
                        assumption["assumption_id"],
                    )
                )
        return results

    def invalidate_plan(self, context, plan_id, trigger_type, trigger_ref, now, assumption_id=None):
        plan = self._plan(context, plan_id)
        match = assumption_id or next(
            (
                item["assumption_id"]
                for item in plan["assumptions"]
                if item["subject_id"] == trigger_ref
            ),
            None,
        )
        if match is None:
            raise PlanConflictError("trigger does not match a named assumption")
        plan["status"] = "review_required"
        result = {
            "invalidation_id": f"inv_{uuid4().hex}",
            "plan_id": plan_id,
            "trigger_type": trigger_type,
            "trigger_ref": trigger_ref,
            "assumption_id": match,
            "detected_at": _iso(now),
        }
        plan.setdefault("invalidations", []).append(result)
        plan["updated_at"] = _iso(now)
        return copy.deepcopy(result)

    def invalidate_subject(self, context, subject_type, subject_id, trigger_type, now):
        affected = find_affected_plans(subject_type, subject_id, self.list_plans(context))
        return [
            self.invalidate_plan(
                context,
                plan["plan_id"],
                trigger_type,
                subject_id,
                now,
                next(
                    a["assumption_id"]
                    for a in plan["assumptions"]
                    if a["subject_type"] == subject_type and a["subject_id"] == subject_id
                ),
            )
            for plan in affected
        ]

    def create_certificate(self, context, certificate, now):
        selected = self._plan(context, certificate.selected_plan_id)
        if selected["status"] not in ACTIVE_STATUSES:
            raise PlanConflictError("selected plan is not approvable")
        previous = [
            item
            for item in self.certificates.values()
            if item["organization_id"] == context.tenant_id
            and item["workspace_id"] == context.workspace_id
            and item["selected_plan_id"] == certificate.selected_plan_id
        ]
        record = {
            "certificate_id": f"cert_{uuid4().hex}",
            "organization_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            **certificate.model_dump(mode="json"),
            "supersedes_certificate_id": previous[-1]["certificate_id"] if previous else None,
            "created_at": _iso(now),
            "approved_at": _iso(now),
            "immutable": True,
            "version": CERTIFICATE_VERSION,
        }
        self.certificates[(context.tenant_id, context.workspace_id, record["certificate_id"])] = (
            record
        )
        selected["status"] = "approved"
        return copy.deepcopy(record)

    def get_certificate(self, context, certificate_id):
        record = self.certificates.get((context.tenant_id, context.workspace_id, certificate_id))
        if record is None:
            raise PlanNotFoundError
        return copy.deepcopy(record)


class PostgreSQLPlanStore:
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
            "INSERT INTO event_workspaces (id,organization_id,name,mode,status,event_time,created_at) VALUES (%s,%s,%s,'replay','active',%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Development demo event", now, now),
        )

    def create_plan(self, context, plan, now):
        plan_id = f"plan_{uuid4().hex}"
        assumptions = [
            {"assumption_id": f"asm_{uuid4().hex}", **item.model_dump(mode="json")}
            for item in plan.assumptions
        ]
        actions = [item.model_dump(mode="json") for item in plan.actions]
        record = {
            "plan_id": plan_id,
            "organization_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "status": "feasible",
            "horizon_hours": plan.horizon_hours,
            "objective_summary": plan.objective_summary,
            "policy_version": plan.policy_version,
            "input_snapshot_hash": plan.input_snapshot_hash,
            "expires_at": _iso(plan.expires_at),
            "actions": actions,
            "assumptions": assumptions,
            "fragility": compute_plan_fragility({"assumptions": assumptions}),
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "INSERT INTO plans (plan_id,organization_id,workspace_id,status,horizon_hours,objective_summary,policy_version,input_snapshot_hash,expires_at,actions,assumptions,fragility,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    plan_id,
                    context.tenant_id,
                    context.workspace_id,
                    record["status"],
                    plan.horizon_hours,
                    plan.objective_summary,
                    plan.policy_version,
                    plan.input_snapshot_hash,
                    plan.expires_at,
                    Jsonb(actions),
                    Jsonb(assumptions),
                    record["fragility"],
                    now,
                    now,
                ),
            )
            for assumption in assumptions:
                cursor.execute(
                    "INSERT INTO plan_assumptions (assumption_id,plan_id,subject_type,subject_id,expected_state,sensitivity,valid_until) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        assumption["assumption_id"],
                        plan_id,
                        assumption["subject_type"],
                        assumption["subject_id"],
                        assumption["expected_state"],
                        assumption["sensitivity"],
                        assumption.get("valid_until"),
                    ),
                )
        return record

    def list_plans(self, context, status=None):
        with self._connection() as connection, connection.cursor() as cursor:
            params = [context.tenant_id, context.workspace_id]
            where = "organization_id=%s AND workspace_id=%s"
            if status:
                where += " AND status=%s"
                params.append(status)
            cursor.execute(
                f"SELECT plan_id,status,horizon_hours,objective_summary,policy_version,input_snapshot_hash,expires_at,actions,assumptions,fragility,created_at,updated_at FROM plans WHERE {where} ORDER BY created_at,plan_id",
                params,
            )
            return [
                {
                    "plan_id": r[0],
                    "status": r[1],
                    "horizon_hours": r[2],
                    "objective_summary": r[3],
                    "policy_version": r[4],
                    "input_snapshot_hash": r[5],
                    "expires_at": _iso(r[6]),
                    "actions": r[7],
                    "assumptions": r[8],
                    "fragility": r[9],
                    "created_at": _iso(r[10]),
                    "updated_at": _iso(r[11]),
                }
                for r in cursor.fetchall()
            ]

    def get_plan(self, context, plan_id):
        plans = [item for item in self.list_plans(context) if item["plan_id"] == plan_id]
        if not plans:
            raise PlanNotFoundError
        return plans[0]

    def check_assumptions(self, context, plan_id, now):
        plan = self.get_plan(context, plan_id)
        results = []
        for assumption in plan["assumptions"]:
            if assumption.get("valid_until") and datetime.fromisoformat(
                assumption["valid_until"]
            ) <= now.astimezone(UTC):
                results.append(
                    self.invalidate_plan(
                        context,
                        plan_id,
                        "manual",
                        f"expired:{assumption['assumption_id']}",
                        now,
                        assumption["assumption_id"],
                    )
                )
        return results

    def invalidate_plan(self, context, plan_id, trigger_type, trigger_ref, now, assumption_id=None):
        plan = self.get_plan(context, plan_id)
        match = assumption_id or next(
            (
                item["assumption_id"]
                for item in plan["assumptions"]
                if item["subject_id"] == trigger_ref
            ),
            None,
        )
        if match is None:
            raise PlanConflictError("trigger does not match a named assumption")
        invalidation = {
            "invalidation_id": f"inv_{uuid4().hex}",
            "plan_id": plan_id,
            "trigger_type": trigger_type,
            "trigger_ref": trigger_ref,
            "assumption_id": match,
            "detected_at": _iso(now),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE plans SET status='review_required',updated_at=%s WHERE plan_id=%s AND organization_id=%s AND workspace_id=%s",
                (now, plan_id, context.tenant_id, context.workspace_id),
            )
            cursor.execute(
                "INSERT INTO decision_invalidations (invalidation_id,plan_id,trigger_type,trigger_ref,assumption_id,detected_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (invalidation["invalidation_id"], plan_id, trigger_type, trigger_ref, match, now),
            )
        return invalidation

    def invalidate_subject(self, context, subject_type, subject_id, trigger_type, now):
        affected = find_affected_plans(subject_type, subject_id, self.list_plans(context))
        return [
            self.invalidate_plan(
                context,
                plan["plan_id"],
                trigger_type,
                subject_id,
                now,
                next(
                    a["assumption_id"]
                    for a in plan["assumptions"]
                    if a["subject_type"] == subject_type and a["subject_id"] == subject_id
                ),
            )
            for plan in affected
        ]

    def create_certificate(self, context, certificate, now):
        self.get_plan(context, certificate.selected_plan_id)
        certificate_id = f"cert_{uuid4().hex}"
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT certificate_id FROM decision_certificates WHERE selected_plan_id=%s AND organization_id=%s AND workspace_id=%s ORDER BY created_at DESC LIMIT 1",
                (certificate.selected_plan_id, context.tenant_id, context.workspace_id),
            )
            previous = cursor.fetchone()
            cursor.execute(
                "INSERT INTO decision_certificates (certificate_id,organization_id,workspace_id,selected_plan_id,alternative_plan_ids,input_snapshot_hash,exclusions,policy_version,assumptions_snapshot,approver_id,approved_at,created_at,supersedes_certificate_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    certificate_id,
                    context.tenant_id,
                    context.workspace_id,
                    certificate.selected_plan_id,
                    certificate.alternative_plan_ids,
                    certificate.input_snapshot_hash,
                    Jsonb(certificate.exclusions),
                    certificate.policy_version,
                    Jsonb(certificate.assumptions_snapshot),
                    certificate.approver_id,
                    now,
                    now,
                    previous[0] if previous else None,
                ),
            )
            cursor.execute(
                "UPDATE plans SET status='approved',updated_at=%s WHERE plan_id=%s",
                (now, certificate.selected_plan_id),
            )
        return {
            "certificate_id": certificate_id,
            **certificate.model_dump(mode="json"),
            "supersedes_certificate_id": previous[0] if previous else None,
            "approved_at": _iso(now),
            "created_at": _iso(now),
            "immutable": True,
            "version": CERTIFICATE_VERSION,
        }

    def get_certificate(self, context, certificate_id):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT certificate_id,selected_plan_id,alternative_plan_ids,input_snapshot_hash,exclusions,policy_version,assumptions_snapshot,approver_id,approved_at,created_at,supersedes_certificate_id FROM decision_certificates WHERE certificate_id=%s AND organization_id=%s AND workspace_id=%s",
                (certificate_id, context.tenant_id, context.workspace_id),
            )
            r = cursor.fetchone()
            if not r:
                raise PlanNotFoundError
            return {
                "certificate_id": r[0],
                "selected_plan_id": r[1],
                "alternative_plan_ids": r[2],
                "input_snapshot_hash": r[3],
                "exclusions": r[4],
                "policy_version": r[5],
                "assumptions_snapshot": r[6],
                "approver_id": r[7],
                "approved_at": _iso(r[8]),
                "created_at": _iso(r[9]),
                "supersedes_certificate_id": r[10],
                "immutable": True,
                "version": CERTIFICATE_VERSION,
            }
