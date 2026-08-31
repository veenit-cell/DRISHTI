# ruff: noqa: E501

import copy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext
from app.decision_policy import (
    CascadeAdapter,
    PolicyRequest,
    PolicySnapshot,
    ProjectionAdapter,
    ResourceAdapter,
    evaluate_policy,
)
from app.dependencies import DependencyStore
from app.operations import (
    IdempotencyConflictError,
    OperationsStore,
    PostgreSQLOperationsStore,
    QueueItemCreate,
    _opaque_id,
    _request_hash,
)
from app.plans import PlanActionCreate, PlanAssumptionCreate, PlanCreate, PlanStore


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(approve|reject|modify)$")
    note: str | None = Field(default=None, max_length=500)
    resource_id: str | None = None
    selected_action: str | None = Field(default=None, max_length=160)


class InteractionAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: str = Field(pattern="^(recommendation_viewed|evidence_opened|scenario_evaluated)$")
    subject_type: str = Field(pattern="^(recommendation|evidence|scenario)$")
    subject_id: str = Field(min_length=1, max_length=128)


class DecisionNotFoundError(Exception):
    pass


def _unlock_candidate(unlock: dict[str, Any], expires_at: str, input_hash: str) -> dict[str, Any]:
    return {
        "action": unlock["action"],
        "evidence_references": unlock["evidence_refs"],
        "reasons": [f"restoration unlocks {', '.join(unlock['missions_unlocked'])}"],
        "resource_cost": {"restoration": unlock["restoration_cost"]},
        "expected_benefit": unlock["missions_unlocked"],
        "time_sensitivity_hours": None,
        "confidence": "medium",
        "expires_at": expires_at,
        "policy_version": unlock["version"],
        "input_hash": input_hash,
        "excluded_resources": {},
        "expected_operational_effect": f"restoring {unlock['target_node_id']} unlocks downstream missions",
        "feasible": True,
        "rank": 0,
        "status": "pending_approval",
    }


def _persist_alternative_plans(
    plan_store: PlanStore | None,
    context: RequestContext,
    recommendation: dict[str, Any],
    now: datetime,
) -> list[str]:
    if plan_store is None:
        return []
    plan_ids = []
    for candidate in recommendation.get("candidates", [])[:2]:
        action_class = "unlock" if candidate["action"].startswith("restore_") else "response"
        plan = plan_store.create_plan(
            context,
            PlanCreate(
                objective_summary=recommendation["expected_effect"],
                policy_version=recommendation["rule"],
                horizon_hours=4,
                actions=[
                    PlanActionCreate(
                        action_class=action_class,
                        action_type=candidate["action"],
                        expected_effect=candidate["expected_operational_effect"],
                    )
                ],
                assumptions=[
                    PlanAssumptionCreate(
                        subject_type="route",
                        subject_id=recommendation["sector"],
                        expected_state="passable",
                        sensitivity="high",
                        valid_until=datetime.fromisoformat(recommendation["expires_at"]),
                    )
                ],
                input_snapshot_hash=recommendation["input_hash"],
                expires_at=datetime.fromisoformat(recommendation["expires_at"]),
            ),
            now,
        )
        plan_ids.append(plan["plan_id"])
    return plan_ids


class InMemoryDecisionStore:
    """Fast deterministic test adapter. Application runtime uses PostgreSQLDecisionStore."""

    def __init__(self, operations_store: OperationsStore, dependency_store: DependencyStore | None = None, plan_store: PlanStore | None = None) -> None:
        self.operations_store = operations_store
        self.dependency_store = dependency_store
        self.plan_store = plan_store
        self.scenarios: dict[tuple[str, str], dict[str, Any]] = {}
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
        self.scenarios[(context.tenant_id, context.workspace_id)] = scenario
        self.recommendations = {
            key: value
            for key, value in self.recommendations.items()
            if value["tenant_id"] != context.tenant_id or value["workspace_id"] != context.workspace_id
        }
        self.audit_events.append(
            {
                "event": "scenario_replayed",
                "actor_id": context.actor_id,
                "at": now.isoformat(),
                "tenant_id": context.tenant_id,
                "workspace_id": context.workspace_id,
                "correlation_id": context.correlation_id,
            }
        )
        return self._replay_or_record(context, idempotency_key, payload, scenario)

    def get_scenario(self, context: RequestContext) -> dict[str, Any]:
        return dict(self.scenarios.get((context.tenant_id, context.workspace_id)) or {})

    def recommend(
        self, context: RequestContext, now: datetime, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"operation": "decision.recommend.v1"}
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            return self._replay_or_record(context, idempotency_key, payload, {})
        scenario = self.scenarios.get((context.tenant_id, context.workspace_id))
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
            "expires_at": (now + timedelta(hours=4)).isoformat(),
            "auto_dispatched": False,
            "queue_item_id": None,
            "selected_action": None,
            "selected_resource_id": None,
            "created_at": now.isoformat(),
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
        }
        policy = evaluate_policy(
            PolicyRequest(
                snapshot=PolicySnapshot(
                    observed_at=now,
                    values={"population_influx": signals["population_influx"]},
                    freshness_state="fresh",
                ),
                projections=[
                    ProjectionAdapter(
                        resource="potable_water",
                        state="projected",
                        time_to_critical_hours=signals["water_runway_hours"],
                        confidence="medium",
                    )
                ],
                cascades=[CascadeAdapter(affected_capability="safe_water_runway", severity="high", supporting_input_refs=["scenario_fixed_north_sector_v1:signals"])],
                resources=[
                    ResourceAdapter(
                        id=item["id"],
                        capabilities=item.get("capabilities", []),
                        readiness=item["readiness"],
                        readiness_expires_at=datetime.fromisoformat(item["readiness_expires_at"]) if item.get("readiness_expires_at") else None,
                        route_passable=True,
                    )
                    for item in self.operations_store.list_resources(context)
                ],
                now=now,
            )
        )
        recommendation["candidates"] = [item.model_dump(mode="json") for item in policy.candidates]
        if self.dependency_store is not None:
            for unlock in self.dependency_store.unlock_ranking(context):
                if unlock["mission_unlock_value"] <= 0:
                    continue
                candidate = _unlock_candidate(unlock, recommendation["expires_at"], recommendation["input_hash"])
                candidate["rank"] = len(recommendation["candidates"]) + 1
                recommendation["candidates"].append(candidate)
        recommendation["plan_ids"] = _persist_alternative_plans(
            self.plan_store, context, recommendation, now
        )
        for cand in recommendation.get("candidates", []):
            action_name = cand.get("action", "").lower()
            if "water" in action_name:
                cand["priority_reason"] = "Potable water runway in North Sector is 3.5h, below emergency 6.0h threshold with incoming population influx."
                cand["evidence_available"] = "Corroborated sensor telemetry + drone reconnaissance (rpt_demo_01, rpt_demo_02)."
                cand["important_unknowns"] = "INFORMATION GAP: Dharapur Village silent (0 reports, pop: 4,200); West corridor bridge unassessed."
                cand["resource_availability"] = "FEASIBLE: Synthetic Water Team Alpha & Rescue Boat 1 ready on scene."
                cand["route_accessibility"] = "NH-27 Highway Open; West Bank River Corridor Degraded / Blocked."
                cand["decision_model"] = {"need": "Critical", "confidence": "Medium", "feasibility": "Feasible"}
            elif "power" in action_name:
                cand["priority_reason"] = "Protects cold chain and water purification pumps from cascading outage."
                cand["evidence_available"] = "Central Shelter load reports and infrastructure dependency model."
                cand["important_unknowns"] = "Fuel reserve delivery status unknown for East corridor."
                cand["resource_availability"] = "FEASIBLE: Generator Unit ready at Central Shelter."
                cand["route_accessibility"] = "Central road network Open."
                cand["decision_model"] = {"need": "High", "confidence": "High", "feasibility": "Feasible"}
            else:
                cand["priority_reason"] = "Restores mission capability and access for downstream critical sectors."
                cand["evidence_available"] = "Infrastructure node dependency telemetry."
                cand["important_unknowns"] = "Structural damage extent pending ground reconnaissance."
                cand["resource_availability"] = "CONSTRAINED: Heavy excavator awaiting transport."
                cand["route_accessibility"] = "Route degraded by mud and debris."
                cand["decision_model"] = {"need": "Medium", "confidence": "Medium", "feasibility": "Constrained"}

        self.recommendations[recommendation["id"]] = recommendation
        self.audit_events.append(
            {
                "event": "recommendation_created",
                "recommendation_id": recommendation["id"],
                "actor_id": context.actor_id,
                "at": now.isoformat(),
                "tenant_id": context.tenant_id,
                "workspace_id": context.workspace_id,
                "correlation_id": context.correlation_id,
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
        if recommendation is None or recommendation["tenant_id"] != context.tenant_id or recommendation["workspace_id"] != context.workspace_id:
            raise DecisionNotFoundError
        if recommendation["status"] != "pending_approval":
            raise DecisionNotFoundError
        if recommendation.get("expires_at") and datetime.fromisoformat(
            recommendation["expires_at"]
        ) <= now.astimezone(UTC):
            raise DecisionNotFoundError
        if response.decision in ("approve", "modify"):
            selected_action = response.selected_action or recommendation["candidates"][0]["action"]
            selected = next((item for item in recommendation["candidates"] if item["action"] == selected_action), None)
            if selected is None:
                raise DecisionNotFoundError
            chosen = None
            if selected_action.startswith("restore_"):
                required_capability = "infrastructure_restoration"
                queue_priority = "high"
                queue_title = selected_action
            else:
                chosen = response.resource_id or (
                    recommendation["compatible_resources"][0]["id"]
                    if recommendation["compatible_resources"]
                    else None
                )
                if chosen is None or chosen not in {
                    r["id"] for r in recommendation["compatible_resources"]
                }:
                    raise DecisionNotFoundError
                required_capability = "water_delivery"
                queue_priority = "critical"
                queue_title = selected_action
            recommendation["selected_action"] = selected_action
            recommendation["selected_resource_id"] = chosen
            queue = self.operations_store.create_queue(
                context,
                QueueItemCreate(
                    title=queue_title,
                    priority=queue_priority,
                    destination=recommendation["sector"],
                    required_capability=required_capability,
                    source_recommendation_id=recommendation_id,
                ),
                now,
                f"recommendation-queue-{recommendation_id}",
            )
            recommendation["queue_item_id"] = queue["id"]
        recommendation["status"] = "approved" if response.decision in ("approve", "modify") else "rejected"
        recommendation["decided_by"] = context.actor_id
        recommendation["decided_at"] = now.isoformat()
        recommendation["decision_note"] = response.note
        recommendation["auto_dispatched"] = False
        legacy_event = f"recommendation_{'modified_approved' if response.decision == 'modify' else recommendation['status']}"
        event = f"action_{'modified' if response.decision == 'modify' else response.decision}"
        audit_fields = {
            "recommendation_id": recommendation_id,
            "actor_id": context.actor_id,
            "at": now.isoformat(),
            "auto_dispatched": False,
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "correlation_id": context.correlation_id,
        }
        self.audit_events.append({"event": legacy_event, **audit_fields})
        self.audit_events.append({"event": event, **audit_fields})
        return self._replay_or_record(
            context, idempotency_key, payload, copy.deepcopy(recommendation)
        )

    def record_interaction(
        self,
        context: RequestContext,
        interaction: InteractionAuditRequest,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"operation": "command.interaction_audit.v1", **interaction.model_dump()}
        existing = self._idempotent.get((context.tenant_id, context.workspace_id, idempotency_key))
        if existing:
            if existing[0] != _request_hash(payload):
                raise IdempotencyConflictError
            result = copy.deepcopy(existing[1])
            result["replayed"] = True
            return result
        record = {
            "event": interaction.event.replace("_", "."),
            "subject_type": interaction.subject_type,
            "subject_id": interaction.subject_id,
            "actor_id": context.actor_id,
            "at": now.isoformat(),
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "correlation_id": context.correlation_id,
        }
        self.audit_events.append(record)
        return self._replay_or_record(
            context,
            idempotency_key,
            payload,
            {"recorded_at": now.isoformat(), "correlation_id": context.correlation_id, "replayed": False},
        )

    def audit(
        self, context: RequestContext, after: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        scoped = [
            dict(event)
            for event in self.audit_events
            if event.get("tenant_id") == context.tenant_id
            and event.get("workspace_id") == context.workspace_id
            and (not after or event.get("at", "") > after)
        ]
        normalized = []
        for event in scoped[: max(1, min(limit, 100))]:
            if isinstance(event.get("event"), str):
                event["event"] = event["event"].replace(".", "_")
            normalized.append(event)
        return normalized

    def list_pending_recommendations(self, context: RequestContext) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(item)
            for item in self.recommendations.values()
            if item.get("tenant_id") == context.tenant_id
            and item.get("workspace_id") == context.workspace_id
            and item.get("status") == "pending_approval"
        ]

    def get_current_recommendation(self, context: RequestContext) -> dict[str, Any] | None:
        scoped = [
            item
            for item in self.recommendations.values()
            if item.get("tenant_id") == context.tenant_id
            and item.get("workspace_id") == context.workspace_id
        ]
        return copy.deepcopy(max(scoped, key=lambda item: (item.get("created_at", ""), item.get("id", "")), default=None))


class PostgreSQLDecisionStore:
    def __init__(
        self,
        database_url: str,
        operations_store: PostgreSQLOperationsStore,
        dependency_store: DependencyStore | None = None,
        plan_store: PlanStore | None = None,
    ) -> None:
        self.database_url = database_url
        self.operations_store = operations_store
        self.dependency_store = dependency_store
        self.plan_store = plan_store

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
        # Check the scoped idempotency record before touching operational state.
        # This keeps a sequential retry a true replay rather than a second reset/seed.
        with self._connection() as connection, connection.cursor() as cursor:
            PostgreSQLOperationsStore._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
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
            "expires_at": (now + timedelta(hours=4)).isoformat(),
            "auto_dispatched": False,
            "created_at": now.isoformat(),
        }
        recommendation["candidates"] = []
        if self.dependency_store is not None:
            for unlock in self.dependency_store.unlock_ranking(context):
                if unlock["mission_unlock_value"] > 0:
                    candidate = _unlock_candidate(
                        unlock, recommendation["expires_at"], recommendation["input_hash"]
                    )
                    candidate["rank"] = len(recommendation["candidates"]) + 1
                    recommendation["candidates"].append(candidate)
        recommendation["plan_ids"] = _persist_alternative_plans(
            self.plan_store, context, recommendation, now
        )
        with self._connection() as connection, connection.cursor() as cursor:
            PostgreSQLOperationsStore._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return existing
            cursor.execute(
                "INSERT INTO recommendations (id, organization_id, workspace_id, status, action, sector, compatible_resources, reasons, rule, priority, evidence_refs, input_snapshot, input_hash, expected_effect, expires_at, candidates, auto_dispatched, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)",
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
                    now + timedelta(hours=4),
                    Jsonb(recommendation["candidates"]),
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
                "SELECT id, action, sector, compatible_resources, reasons, rule, priority, evidence_refs, input_snapshot, input_hash, expected_effect, expires_at, created_at, candidates FROM recommendations WHERE id = %s AND organization_id = %s AND workspace_id = %s AND status = 'pending_approval' FOR UPDATE",
                (recommendation_id, context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise DecisionNotFoundError
            if row[11] and row[11] <= now:
                raise DecisionNotFoundError
            status = "approved" if response.decision in ("approve", "modify") else "rejected"
            cursor.execute(
                "UPDATE recommendations SET status = %s, decided_by = %s, decided_at = %s, decision_note = %s WHERE id = %s",
                (status, context.actor_id, now, response.note, recommendation_id),
            )
            queue_id = None
            chosen = None
            if response.decision in ("approve", "modify"):
                resources = row[3] or []
                candidates = row[13] or []
                selected_action = response.selected_action or (candidates[0]["action"] if candidates else row[1])
                if selected_action.startswith("restore_"):
                    selected = next(
                        (item for item in candidates if item["action"] == selected_action),
                        None,
                    )
                    if selected is None:
                        raise DecisionNotFoundError
                    required_capability = "infrastructure_restoration"
                    title = selected_action
                else:
                    chosen = response.resource_id or (resources[0]["id"] if resources else None)
                    if chosen is None or chosen not in {r["id"] for r in resources}:
                        raise DecisionNotFoundError
                    required_capability = "water_delivery"
                    title = row[1]
                queue_id = str(uuid4())
                cursor.execute(
                    "INSERT INTO response_queue_items (id, organization_id, workspace_id, title, priority, destination, notes, queue_type, required_capability, source_recommendation_id, status, created_at) VALUES (%s,%s,%s,%s,'critical',%s,%s,'response',%s,%s,'queued',%s)",
                    (
                        queue_id,
                        context.tenant_id,
                        context.workspace_id,
                        title,
                        row[2],
                        f"from recommendation {recommendation_id}",
                        required_capability,
                        recommendation_id,
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
                "candidates": row[13] or [],
                "reasons": row[4],
                "rule": row[5],
                "priority": row[6],
                "evidence_refs": row[7],
                "input_snapshot": row[8],
                "input_hash": row[9],
                "expected_effect": row[10],
                "expires_at": row[11].isoformat() if row[11] else None,
                "queue_item_id": queue_id,
                "selected_action": selected_action if response.decision in ("approve", "modify") else None,
                "selected_resource_id": chosen,
                "auto_dispatched": False,
                "created_at": row[12].isoformat(),
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
            self._audit(
                cursor,
                context,
                f"action.{'modified' if response.decision == 'modify' else response.decision}",
                "recommendation",
                recommendation_id,
                {"auto_dispatched": False},
                now,
            )
            self._record_idempotency(cursor, context, idempotency_key, payload, result, now)
            return result

    def record_interaction(
        self,
        context: RequestContext,
        interaction: InteractionAuditRequest,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"operation": "command.interaction_audit.v1", **interaction.model_dump()}
        with self._connection() as connection, connection.cursor() as cursor:
            PostgreSQLOperationsStore._ensure_context(cursor, context, now)
            existing = self._idempotent(cursor, context, idempotency_key, payload)
            if existing is not None:
                return {**existing, "replayed": True}
            self._audit(
                cursor,
                context,
                interaction.event.replace("_", "."),
                interaction.subject_type,
                interaction.subject_id,
                {},
                now,
            )
            result = {
                "recorded_at": now.isoformat(),
                "correlation_id": context.correlation_id,
                "replayed": False,
            }
            self._record_idempotency(cursor, context, idempotency_key, payload, result, now)
            return result

    def audit(
        self, context: RequestContext, after: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT action, subject_id, actor_id, occurred_at, details FROM audit_events WHERE organization_id = %s AND workspace_id = %s AND (action LIKE 'scenario.%%' OR action LIKE 'recommendation.%%' OR action LIKE 'action.%%' OR action LIKE 'evidence.%%') AND (%s IS NULL OR occurred_at > %s) ORDER BY recorded_at, id LIMIT %s",
                (context.tenant_id, context.workspace_id, after, after, max(1, min(limit, 100))),
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

    def list_pending_recommendations(self, context: RequestContext) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, status, action, sector, reasons, rule, priority, expires_at, created_at, auto_dispatched FROM recommendations WHERE organization_id = %s AND workspace_id = %s AND status = 'pending_approval' ORDER BY priority DESC, created_at, id LIMIT 50",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "id": row[0],
                    "status": row[1],
                    "action": row[2],
                    "sector": row[3],
                    "reasons": row[4] or [],
                    "rule": row[5],
                    "priority": row[6],
                    "expires_at": row[7].isoformat() if row[7] else None,
                    "created_at": row[8].isoformat(),
                    "auto_dispatched": row[9],
                }
                for row in cursor.fetchall()
            ]

    def get_current_recommendation(self, context: RequestContext) -> dict[str, Any] | None:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, status, action, sector, compatible_resources, reasons, rule, priority, evidence_refs, input_snapshot, input_hash, expected_effect, expires_at, candidates, auto_dispatched, created_at, queue_item_id, decided_by, decided_at, decision_note FROM recommendations WHERE organization_id = %s AND workspace_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "status": row[1],
                "action": row[2],
                "sector": row[3],
                "compatible_resources": row[4] or [],
                "reasons": row[5] or [],
                "rule": row[6],
                "priority": row[7],
                "evidence_refs": row[8] or [],
                "input_snapshot": row[9] or {},
                "input_hash": row[10],
                "expected_effect": row[11],
                "expires_at": row[12].isoformat() if row[12] else None,
                "candidates": row[13] or [],
                "auto_dispatched": row[14],
                "created_at": row[15].isoformat(),
                "queue_item_id": str(row[16]) if row[16] else None,
                "decided_by": row[17],
                "decided_at": row[18].isoformat() if row[18] else None,
                "decision_note": row[19],
            }
