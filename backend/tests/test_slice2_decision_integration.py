from datetime import UTC, datetime

from app.core.context import RequestContext
from app.decision_loop import DecisionResponse, InMemoryDecisionStore
from app.dependencies import (
    InfraDependencyCreate,
    InfraNodeCreate,
    InMemoryDependencyStore,
)
from app.operations import InMemoryOperationsStore


def test_unlock_candidate_is_approved_through_unified_decision_loop():
    now = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)
    context = RequestContext("operator", "operator", "org_demo", "evt_demo", frozenset(), "test")
    dependencies = InMemoryDependencyStore()
    dependencies.create_node(
        context,
        InfraNodeCreate(node_id="generator", node_type="power", name="Generator", state="failed"),
        now,
    )
    dependencies.create_node(
        context,
        InfraNodeCreate(
            node_id="hospital", node_type="hospital", name="Hospital", state="degraded"
        ),
        now,
    )
    dependencies.create_dependency(
        context, InfraDependencyCreate(upstream_id="generator", downstream_id="hospital"), now
    )
    dependencies.pending_missions[(context.tenant_id, context.workspace_id)] = [
        {"mission_id": "medical-team", "required_infrastructure": ["hospital"], "urgency_weight": 2}
    ]

    operations = InMemoryOperationsStore()
    decision = InMemoryDecisionStore(operations, dependencies)
    decision.replay(context, now, "replay")
    recommendation = decision.recommend(context, now, "recommend")
    unlock = next(
        item for item in recommendation["candidates"] if item["action"] == "restore_generator"
    )

    approved = decision.decide(
        context,
        recommendation["id"],
        DecisionResponse(decision="approve", selected_action=unlock["action"]),
        now,
        "approve",
    )
    assert approved["status"] == "approved"
    assert approved["selected_action"] == "restore_generator"
    assert operations.list_queue(context, "response")[0]["title"] == "restore_generator"
