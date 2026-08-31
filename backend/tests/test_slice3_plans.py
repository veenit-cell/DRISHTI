from datetime import UTC, datetime, timedelta

from app.core.context import RequestContext
from app.decision_loop import InMemoryDecisionStore
from app.operations import InMemoryOperationsStore, ResourceReadinessUpdate, RouteObservationCreate
from app.plans import (
    CertificateCreate,
    InMemoryPlanStore,
    PlanActionCreate,
    PlanAssumptionCreate,
    PlanCreate,
    compute_plan_fragility,
    find_affected_plans,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
CONTEXT = RequestContext("operator", "operator", "org_demo", "evt_demo", frozenset(), "test")


def plan_input(valid_until=None):
    return PlanCreate(
        objective_summary="Reach the hospital",
        policy_version="policy_v1",
        horizon_hours=12,
        actions=[
            PlanActionCreate(
                action_class="response", action_type="medical_support", target_ref="hospital"
            )
        ],
        assumptions=[
            PlanAssumptionCreate(
                subject_type="route",
                subject_id="bridge-1",
                expected_state="passable",
                sensitivity="critical",
                valid_until=valid_until,
            )
        ],
        input_snapshot_hash="snapshot-hash",
    )


def test_bridge_contradiction_matches_only_bridge_dependent_plans():
    affected = find_affected_plans(
        "claim",
        "bridge-1",
        [
            {
                "plan_id": "p1",
                "status": "approved",
                "assumptions": [{"subject_type": "claim", "subject_id": "bridge-1"}],
            },
            {
                "plan_id": "p2",
                "status": "approved",
                "assumptions": [{"subject_type": "claim", "subject_id": "other"}],
            },
        ],
    )
    assert [plan["plan_id"] for plan in affected] == ["p1"]


def test_subject_invalidation_marks_only_matching_plans():
    store = InMemoryPlanStore()
    matching = store.create_plan(CONTEXT, plan_input(), NOW)
    unrelated_input = plan_input()
    unrelated_input.assumptions[0].subject_id = "other-route"
    unrelated = store.create_plan(CONTEXT, unrelated_input, NOW)
    invalidations = store.invalidate_subject(CONTEXT, "route", "bridge-1", "claim_revision", NOW)
    assert [item["plan_id"] for item in invalidations] == [matching["plan_id"]]
    assert store.get_plan(CONTEXT, unrelated["plan_id"])["status"] == "feasible"


def test_inmemory_invalidation_and_certificate_supersession():
    store = InMemoryPlanStore()
    plan = store.create_plan(CONTEXT, plan_input(), NOW)
    invalidation = store.invalidate_plan(
        CONTEXT, plan["plan_id"], "claim_revision", "bridge-1", NOW
    )
    assert invalidation["assumption_id"] == plan["assumptions"][0]["assumption_id"]
    assert store.get_plan(CONTEXT, plan["plan_id"])["status"] == "review_required"

    # Re-approval is allowed after a revised plan is created and preserves the old certificate.
    revised = store.create_plan(CONTEXT, plan_input(), NOW)
    first = store.create_certificate(
        CONTEXT,
        CertificateCreate(
            selected_plan_id=revised["plan_id"],
            input_snapshot_hash="a",
            policy_version="policy_v1",
            approver_id="operator",
        ),
        NOW,
    )
    second = store.create_certificate(
        CONTEXT,
        CertificateCreate(
            selected_plan_id=revised["plan_id"],
            input_snapshot_hash="b",
            policy_version="policy_v1",
            approver_id="operator",
        ),
        NOW + timedelta(minutes=1),
    )
    assert first["certificate_id"] != second["certificate_id"]
    assert second["supersedes_certificate_id"] == first["certificate_id"]
    assert store.get_certificate(CONTEXT, first["certificate_id"])["input_snapshot_hash"] == "a"


def test_expired_assumption_requires_review():
    store = InMemoryPlanStore()
    plan = store.create_plan(CONTEXT, plan_input(NOW - timedelta(minutes=1)), NOW)
    results = store.check_assumptions(CONTEXT, plan["plan_id"], NOW)
    assert results and store.get_plan(CONTEXT, plan["plan_id"])["status"] == "review_required"


def test_fragility_increases_with_critical_assumptions_and_low_margin():
    assert compute_plan_fragility(
        {"constraint_margin": 0.5, "assumptions": [{"sensitivity": "critical"}]}
    ) > compute_plan_fragility({"constraint_margin": 2, "assumptions": [{"sensitivity": "low"}]})


def test_readiness_change_invalidates_resource_assumption():
    plans = InMemoryPlanStore()
    operations = InMemoryOperationsStore(plans)
    resource_id = "res_test"
    operations.resources[resource_id] = {
        "id": resource_id,
        "workspace_id": CONTEXT.workspace_id,
        "readiness": "ready",
        "readiness_expires_at": "2026-08-30T14:30:00+00:00",
    }
    plan_input_value = plan_input()
    plan_input_value.assumptions[0] = PlanAssumptionCreate(
        subject_type="resource",
        subject_id=resource_id,
        expected_state="ready",
    )
    created = plans.create_plan(CONTEXT, plan_input_value, NOW)
    operations.update_readiness(
        CONTEXT,
        resource_id,
        ResourceReadinessUpdate(readiness="not_ready", observed_at=NOW, expires_at=NOW),
        NOW,
        "readiness-test",
    )
    assert plans.get_plan(CONTEXT, created["plan_id"])["status"] == "review_required"


def test_blocked_route_invalidates_route_assumption():
    plans = InMemoryPlanStore()
    operations = InMemoryOperationsStore(plans)
    created = plans.create_plan(CONTEXT, plan_input(), NOW)
    operations.create_route_observation(
        CONTEXT,
        RouteObservationCreate(
            destination="bridge-1", state="blocked", observed_at=NOW, expires_at=NOW
        ),
        NOW,
        "route-test",
    )
    assert plans.get_plan(CONTEXT, created["plan_id"])["status"] == "review_required"


def test_recommendation_persists_two_alternative_plans():
    plans = InMemoryPlanStore()
    decision = InMemoryDecisionStore(InMemoryOperationsStore(), plan_store=plans)
    decision.replay(CONTEXT, NOW, "replay-plans")
    recommendation = decision.recommend(CONTEXT, NOW, "recommend-plans")
    assert len(recommendation["plan_ids"]) == 2
    assert len(plans.list_plans(CONTEXT)) == 2
