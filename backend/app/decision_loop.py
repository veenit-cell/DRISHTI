# ruff: noqa: E501

import copy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext
from app.operations import (
    IdempotencyConflictError,
    OperationsStore,
    PostgreSQLOperationsStore,
    QueueItemCreate,
    _opaque_id,
    _request_hash,
)


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(approve|reject)$")
    note: str | None = Field(default=None, max_length=500)
    resource_id: str | None = None


class DecisionNotFoundError(Exception):
    pass


class InMemoryDecisionStore:
    """Fast deterministic test adapter. Application runtime uses PostgreSQLDecisionStore."""

    def __init__(self, operations_store: OperationsStore) -> None:
        self.operations_store = operations_store
        self.scenarios: dict[str, dict[str, Any]] = {}
        self.recommendations: dict[str, dict[str, Any]] = {}
        self.audit_events: list[dict[str, Any]] = []
        self._idempotent: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}

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

    def replay(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"operation": "decision.replay.v1"}
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        self.operations_store.reset_for_replay(context, now)
        self.operations_store.seed_demo(context, now, f"replay-seed-{_opaque_id('key')}")
        scenario = {
            "scenario_id": "scenario_fixed_north_sector_v1",
            "sector": "North Sector",
            "synthetic": True,
            "signals": {
                "water_runway_hours": 3.5,
                "contamination": "elevated",
                "population_influx": 180,
            },
            "replayed_at": now.isoformat(),
        }
        self.scenarios[context.workspace_id] = scenario
        self.recommendations = {
            key: value
            for key, value in self.recommendations.items()
            if value["workspace_id"] != context.workspace_id
        }
        self.audit_events.append(
            {"event": "scenario_replayed", "actor_id": context.actor_id, "at": now.isoformat()}
        )
        return self._replay_or_record(context, idempotency_key, payload, scenario)

    def get_scenario(self, context: RequestContext) -> dict[str, Any]:
        return dict(self.scenarios.get(context.workspace_id) or {})

    def recommend(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"operation": "decision.recommend.v1"}
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        scenario = self.scenarios.get(context.workspace_id)
        if scenario is None:
            scenario = self.replay(context, now, f"implicit-replay-{_opaque_id('key')}")
        signals = scenario["signals"]
        reasons = [
            reason
            for condition, reason in [
                (signals["water_runway_hours"] < 6, "potable-water runway is below 6 hours"),
                (
                    signals["contamination"] == "elevated",
                    "synthetic contamination signal is elevated",
                ),
                (
                    signals["population_influx"] > 0,
                    f"population influx of {signals['population_influx']} is expected",
                ),
            ]
            if condition
        ]
        compatible = [
            resource
            for resource in self.operations_store.list_resources(context)
            if resource["readiness"] == "ready"
            and resource["resource_type"] == "water_team"
            and (
                not resource.get("readiness_expires_at")
                or datetime.fromisoformat(resource["readiness_expires_at"]) > now.astimezone(UTC)
            )
        ]
        recommendation = {
            "id": _opaque_id("rec"),
            "status": "pending_approval",
            "action": "Assign a ready water team to North Sector",
            "sector": scenario["sector"],
            "compatible_resources": compatible,
            "reasons": reasons,
            "rule": "water_attention_v1",
            "priority": 100,
            "evidence_refs": ["scenario_fixed_north_sector_v1:signals"],
            "input_snapshot": signals,
            "input_hash": _request_hash(signals),
            "expected_effect": "protect potable-water continuity before the 3.5 hour runway threshold",
            "auto_dispatched": False,
            "created_at": now.isoformat(),
            "workspace_id": context.workspace_id,
        }
        self.recommendations[recommendation["id"]] = recommendation
        self.audit_events.append(
            {
                "event": "recommendation_created",
                "recommendation_id": recommendation["id"],
                "actor_id": context.actor_id,
                "at": now.isoformat(),
            }
        )
        return self._replay_or_record(context, idempotency_key, payload, recommendation)

    def decide(
        self,
        context: RequestContext,
        recommendation_id: str,
        response: DecisionResponse,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "operation": "decision.decide.v1",
            "recommendation_id": recommendation_id,
            "response": response.model_dump(mode="json"),
        }
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        recommendation = self.recommendations.get(recommendation_id)
        if recommendation is None or recommendation["workspace_id"] != context.workspace_id:
            raise DecisionNotFoundError
        if recommendation["status"] != "pending_approval":
            raise DecisionNotFoundError
        recommendation["status"] = "approved" if response.decision == "approve" else "rejected"
        recommendation["decided_by"] = context.actor_id
        recommendation["decided_at"] = now.isoformat()
        recommendation["decision_note"] = response.note
        recommendation["auto_dispatched"] = False
        if response.decision == "approve":
            chosen = response.resource_id or (
                recommendation["compatible_resources"][0]["id"]
                if recommendation["compatible_resources"]
                else None
            )
            if chosen is None or chosen not in {
                r["id"] for r in recommendation["compatible_resources"]
            }:
                raise DecisionNotFoundError
            queue = self.operations_store.create_queue(
                context,
                QueueItemCreate(
                    title=recommendation["action"],
                    priority="critical",
                    destination=recommendation["sector"],
                    required_capability="water_delivery",
                ),
                now,
                f"recommendation-queue-{recommendation_id}",
            )
            recommendation["queue_item_id"] = queue["id"]
        self.audit_events.append(
            {
                "event": f"recommendation_{recommendation['status']}",
                "recommendation_id": recommendation_id,
                "actor_id": context.actor_id,
                "at": now.isoformat(),
                "auto_dispatched": False,
            }
        )
        return self._replay_or_record(
            context, idempotency_key, payload, copy.deepcopy(recommendation)
        )

    def audit(self, context: RequestContext) -> list[dict[str, Any]]:
        return [dict(event) for event in self.audit_events]


class PostgreSQLDecisionStore:
    def __init__(self, database_url: str, operations_store: PostgreSQLOperationsStore) -> None:
        self.database_url = database_url
        self.operations_store = operations_store

    def _connection(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url)

    def _idempotent(
        self, cursor: Any, context: RequestContext, key: str, payload: Any
    ) -> dict[str, Any] | None:
        return PostgreSQLOperationsStore._idempotent(cursor, context, key, payload)

    def _record_idempotency(
        self,
        cursor: Any,
        context: RequestContext,
        key: str,
        payload: Any,
        response: dict[str, Any],
        now: datetime,
    ) -> None:
        PostgreSQLOperationsStore._record_idempotency(cursor, context, key, payload, response, now)

    def _audit(
        self,
        cursor: Any,
        context: RequestContext,
        action: str,
        subject_type: str,
        subject_id: str,
        details: dict[str, Any],
        now: datetime,
    ) -> None:
        PostgreSQLOperationsStore._audit(
            cursor, context, action, subject_type, subject_id, details, now
        )

    def replay(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"operation": "decision.replay.v1"}
        self.operations_store.reset_for_replay(context, now)
        self.operations_store.seed_demo(context, now, f"replay-seed-{_opaque_id('key')}")
        scenario = {
            "scenario_id": "scenario_fixed_north_sector_v1",
            "sector": "North Sector",
            "synthetic": True,
            "signals": {
                "water_runway_hours": 3.5,
                "contamination": "elevated",
                "population_influx": 180,
            },
            "replayed_at": now.isoformat(),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            PostgreSQLOperationsStore._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "DELETE FROM recommendation_decisions WHERE organization_id = %s AND workspace_id = %s",
                (context.tenant_id, context.workspace_id),
            )
            cursor.execute(
                "DELETE FROM recommendations WHERE organization_id = %s AND workspace_id = %s",
                (context.tenant_id, context.workspace_id),
            )
            cursor.execute(
                "INSERT INTO demo_scenarios (workspace_id, organization_id, scenario_id, sector, synthetic, signals, replayed_at) VALUES (%s, %s, %s, %s, true, %s, %s) ON CONFLICT (workspace_id) DO UPDATE SET scenario_id = EXCLUDED.scenario_id, sector = EXCLUDED.sector, synthetic = EXCLUDED.synthetic, signals = EXCLUDED.signals, replayed_at = EXCLUDED.replayed_at",
                (
                    context.workspace_id,
                    context.tenant_id,
                    scenario["scenario_id"],
                    scenario["sector"],
                    Jsonb(scenario["signals"]),
                    now,
                ),
            )
            self._audit(
                cursor,
                context,
                "scenario.replayed",
                "scenario",
                scenario["scenario_id"],
                {"synthetic": True},
                now,
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, scenario, now)
            return scenario

    def get_scenario(self, context: RequestContext) -> dict[str, Any]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT scenario_id, sector, synthetic, signals, replayed_at FROM demo_scenarios WHERE organization_id = %s AND workspace_id = %s",
                (context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            return (
                {}
                if row is None
                else {
                    "scenario_id": row[0],
                    "sector": row[1],
                    "synthetic": row[2],
                    "signals": row[3],
                    "replayed_at": row[4].isoformat(),
                }
            )

    def recommend(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"operation": "decision.recommend.v1"}
        scenario = self.get_scenario(context)
        if not scenario:
            scenario = self.replay(context, now, f"implicit-replay-{_opaque_id('key')}")
        signals = scenario["signals"]
        reasons = [
            reason
            for condition, reason in [
                (signals["water_runway_hours"] < 6, "potable-water runway is below 6 hours"),
                (
                    signals["contamination"] == "elevated",
                    "synthetic contamination signal is elevated",
                ),
                (
                    signals["population_influx"] > 0,
                    f"population influx of {signals['population_influx']} is expected",
                ),
            ]
            if condition
        ]
        compatible = [
            resource
            for resource in self.operations_store.list_resources(context)
            if resource["readiness"] == "ready"
            and resource["resource_type"] == "water_team"
            and (
                not resource.get("readiness_expires_at")
                or datetime.fromisoformat(resource["readiness_expires_at"]) > now.astimezone(UTC)
            )
        ]
        recommendation = {
            "id": _opaque_id("rec"),
            "status": "pending_approval",
            "action": "Assign a ready water team to North Sector",
            "sector": scenario["sector"],
            "compatible_resources": compatible,
            "reasons": reasons,
            "rule": "water_attention_v1",
            "priority": 100,
            "evidence_refs": ["scenario_fixed_north_sector_v1:signals"],
            "input_snapshot": signals,
            "input_hash": _request_hash(signals),
            "expected_effect": "protect potable-water continuity before the 3.5 hour runway threshold",
            "auto_dispatched": False,
            "created_at": now.isoformat(),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            PostgreSQLOperationsStore._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "INSERT INTO recommendations (id, organization_id, workspace_id, status, action, sector, compatible_resources, reasons, rule, priority, evidence_refs, input_snapshot, input_hash, expected_effect, auto_dispatched, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)",
                (
                    recommendation["id"],
                    context.tenant_id,
                    context.workspace_id,
                    recommendation["status"],
                    recommendation["action"],
                    recommendation["sector"],
                    Jsonb(compatible),
                    Jsonb(reasons),
                    recommendation["rule"],
                    recommendation["priority"],
                    Jsonb(recommendation["evidence_refs"]),
                    Jsonb(recommendation["input_snapshot"]),
                    recommendation["input_hash"],
                    recommendation["expected_effect"],
                    now,
                ),
            )
            self._audit(
                cursor,
                context,
                "recommendation.created",
                "recommendation",
                recommendation["id"],
                {"rule": recommendation["rule"], "reason_count": len(reasons)},
                now,
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, recommendation, now)
            return recommendation

    def decide(
        self,
        context: RequestContext,
        recommendation_id: str,
        response: DecisionResponse,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "operation": "decision.decide.v1",
            "recommendation_id": recommendation_id,
            "response": response.model_dump(mode="json"),
        }
        with self._connection() as connection, connection.cursor() as cursor:
            PostgreSQLOperationsStore._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "SELECT id, action, sector, compatible_resources, reasons, rule, priority, evidence_refs, input_snapshot, input_hash, expected_effect, created_at FROM recommendations WHERE id = %s AND organization_id = %s AND workspace_id = %s AND status = 'pending_approval' FOR UPDATE",
                (recommendation_id, context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise DecisionNotFoundError
            status = "approved" if response.decision == "approve" else "rejected"
            cursor.execute(
                "UPDATE recommendations SET status = %s, decided_by = %s, decided_at = %s, decision_note = %s WHERE id = %s",
                (status, context.actor_id, now, response.note, recommendation_id),
            )
            queue_id = None
            if response.decision == "approve":
                resources = row[3] or []
                chosen = response.resource_id or (resources[0]["id"] if resources else None)
                if chosen is None or chosen not in {r["id"] for r in resources}:
                    raise DecisionNotFoundError
                queue_id = str(uuid4())
                cursor.execute(
                    "INSERT INTO response_queue_items (id, organization_id, workspace_id, title, priority, destination, notes, queue_type, required_capability, status, created_at) VALUES (%s,%s,%s,%s,'critical',%s,%s,'response','water_delivery','queued',%s)",
                    (
                        queue_id,
                        context.tenant_id,
                        context.workspace_id,
                        row[1],
                        row[2],
                        f"from recommendation {recommendation_id}",
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE recommendations SET queue_item_id=%s WHERE id=%s",
                    (queue_id, recommendation_id),
                )
            cursor.execute(
                "INSERT INTO recommendation_decisions (id, recommendation_id, organization_id, workspace_id, decision, actor_id, note, decided_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    _opaque_id("dec"),
                    recommendation_id,
                    context.tenant_id,
                    context.workspace_id,
                    response.decision,
                    context.actor_id,
                    response.note,
                    now,
                ),
            )
            result = {
                "id": row[0],
                "status": status,
                "action": row[1],
                "sector": row[2],
                "compatible_resources": row[3],
                "reasons": row[4],
                "rule": row[5],
                "priority": row[6],
                "evidence_refs": row[7],
                "input_snapshot": row[8],
                "input_hash": row[9],
                "expected_effect": row[10],
                "queue_item_id": queue_id,
                "auto_dispatched": False,
                "created_at": row[11].isoformat(),
                "decided_by": context.actor_id,
                "decided_at": now.isoformat(),
                "decision_note": response.note,
            }
            self._audit(
                cursor,
                context,
                f"recommendation.{status}",
                "recommendation",
                recommendation_id,
                {"auto_dispatched": False},
                now,
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, result, now)
            return result

    def audit(self, context: RequestContext) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT action, subject_id, actor_id, occurred_at, details FROM audit_events WHERE organization_id = %s AND workspace_id = %s AND (action LIKE 'scenario.%%' OR action LIKE 'recommendation.%%') ORDER BY recorded_at, id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "event": row[0].replace(".", "_"),
                    "subject_id": row[1],
                    "actor_id": row[2],
                    "at": row[3].isoformat(),
                    **row[4],
                }
                for row in cursor.fetchall()
            ]
