from datetime import UTC, datetime, timedelta

from app.core.context import RequestContext
from app.mutual_aid import (
    ForecastRequest,
    InMemoryMutualAidStore,
    MutualAidApproval,
    MutualAidRequestCreate,
    compute_forecast,
    draft_mutual_aid_request,
)
from app.operations import InMemoryOperationsStore, StructuredTaskOutcome

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
CONTEXT = RequestContext("operator", "operator", "org_demo", "evt_demo", frozenset(), "test")


def request():
    return ForecastRequest(
        resource_type="potable_water",
        current_quantity=100,
        consumption_per_hour=12,
        reserve_floor=40,
        forecast_window_hours=8,
        lead_time_hours=4,
        location="North Sector",
    )


def test_below_reserve_inside_lead_time_recommends_request():
    forecast = compute_forecast(request())
    assert forecast.request_recommended is True
    assert forecast.projected_quantity == 4
    assert draft_mutual_aid_request(forecast, request(), NOW)["quantity"] == 36


def test_same_forecast_replay_creates_one_draft():
    store = InMemoryMutualAidStore()
    forecast = compute_forecast(request())
    draft = draft_mutual_aid_request(forecast, request(), NOW)
    payload = MutualAidRequestCreate(**draft)
    first = store.create_request(CONTEXT, payload, NOW)
    second = store.create_request(CONTEXT, payload, NOW + timedelta(minutes=1))
    assert first["request_id"] == second["request_id"]
    assert len(store.list_requests(CONTEXT)) == 1


def test_draft_requires_commander_approval_before_submission():
    store = InMemoryMutualAidStore()
    forecast = compute_forecast(request())
    draft_payload = MutualAidRequestCreate(**draft_mutual_aid_request(forecast, request(), NOW))
    draft = store.create_request(CONTEXT, draft_payload, NOW)
    assert draft["status"] == "draft"
    approved = store.approve_request(
        CONTEXT, draft["request_id"], MutualAidApproval(approved=True), NOW
    )
    assert approved["status"] == "submitted"
    assert approved["export"]["source_reality"] == "synthetic"


def test_structured_completion_updates_resource_capacity():
    store = InMemoryOperationsStore()
    store.resources["resource-1"] = {
        "id": "resource-1",
        "workspace_id": CONTEXT.workspace_id,
        "capacity_value": 10,
    }
    store.tasks["task-1"] = {
        "id": "task-1",
        "workspace_id": CONTEXT.workspace_id,
        "resource_id": "resource-1",
        "queue_item_id": "queue-1",
        "status": "completed",
    }
    result = store.record_structured_outcome(
        CONTEXT,
        "task-1",
        StructuredTaskOutcome(
            action_type_evidence="water delivered",
            completion_quantities={"liters": 25},
            completed_at=NOW,
            residual_need="monitor next shift",
            verified_by="operator",
        ),
        NOW,
        "structured-outcome-1",
    )
    assert result["completion_quantities"] == {"liters": 25}
    assert store.resources["resource-1"]["capacity_value"] == 35
