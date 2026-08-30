from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(approve|reject)$")
    note: str | None = Field(default=None, max_length=500)


class DecisionNotFoundError(Exception):
    pass


class InMemoryDecisionStore:
    def __init__(self, operations_store: Any) -> None:
        self.operations_store = operations_store
        self.scenarios: dict[str, dict[str, Any]] = {}
        self.recommendations: dict[str, dict[str, Any]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.audit_events: list[dict[str, Any]] = []

    def replay(self, context: RequestContext, now: datetime) -> dict[str, Any]:
        self.scenarios = {
            context.workspace_id: {
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
        }
        self.recommendations = {}
        self.decisions = {}
        self.audit_events = []
        self.operations_store.resources.clear()
        self.operations_store.queue.clear()
        self.operations_store.tasks.clear()
        self.operations_store.seed_demo(context, now)
        self.audit_events.append(
            {"event": "scenario_replayed", "actor_id": context.actor_id, "at": now.isoformat()}
        )
        return self.scenarios[context.workspace_id]

    def get_scenario(self, context: RequestContext) -> dict[str, Any]:
        return dict(self.scenarios.get(context.workspace_id) or {})

    def recommend(self, context: RequestContext, now: datetime) -> dict[str, Any]:
        scenario = self.scenarios.get(context.workspace_id)
        if scenario is None:
            self.replay(context, now)
            scenario = self.scenarios[context.workspace_id]
        signals = scenario["signals"]
        reasons = []
        if signals["water_runway_hours"] < 6:
            reasons.append("potable-water runway is below 6 hours")
        if signals["contamination"] == "elevated":
            reasons.append("synthetic contamination signal is elevated")
        if signals["population_influx"] > 0:
            reasons.append(f"population influx of {signals['population_influx']} is expected")
        compatible = [
            r
            for r in self.operations_store.list_resources(context)
            if r["readiness"] == "ready" and r["resource_type"] == "water_team"
        ]
        recommendation = {
            "id": f"rec_{uuid4().hex[:12]}",
            "status": "pending_approval",
            "action": "Assign a ready water team to North Sector",
            "sector": scenario["sector"],
            "compatible_resources": compatible,
            "reasons": reasons,
            "rule": "water_attention_v1",
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
        return dict(recommendation)

    def decide(
        self,
        context: RequestContext,
        recommendation_id: str,
        response: DecisionResponse,
        now: datetime,
    ) -> dict[str, Any]:
        recommendation = self.recommendations.get(recommendation_id)
        if recommendation is None or recommendation["workspace_id"] != context.workspace_id:
            raise DecisionNotFoundError
        recommendation["status"] = "approved" if response.decision == "approve" else "rejected"
        recommendation["decided_by"] = context.actor_id
        recommendation["decided_at"] = now.isoformat()
        recommendation["decision_note"] = response.note
        recommendation["auto_dispatched"] = False
        self.decisions[recommendation_id] = dict(recommendation)
        self.audit_events.append(
            {
                "event": f"recommendation_{recommendation['status']}",
                "recommendation_id": recommendation_id,
                "actor_id": context.actor_id,
                "at": now.isoformat(),
                "auto_dispatched": False,
            }
        )
        return dict(recommendation)

    def audit(self, context: RequestContext) -> list[dict[str, Any]]:
        return [dict(event) for event in self.audit_events]
