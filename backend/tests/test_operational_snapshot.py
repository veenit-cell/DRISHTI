# ruff: noqa: E501

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.context import RequestContext
from app.incident_command import (
    CommandRoleAssignment,
    IncidentCreate,
    IncidentTransition,
    InMemoryIncidentStore,
)
from app.main import create_app
from app.operations import InMemoryOperationsStore
from app.operational_snapshot import build_operational_snapshot
from app.shelter_state import InMemoryShelterStateStore


NOW = datetime(2026, 9, 3, 10, 5, tzinfo=UTC)
CONTEXT = RequestContext(
    "usr_demo_operator", "operator", "org_demo", "evt_demo", frozenset(), "test"
)


def shelter_state(freshness: str = "fresh") -> dict:
    values = {
        "population": 1800,
        "capacity": 2200,
        "population_influx_per_hour": 180,
        "potable_water_liters": 4200,
        "unsafe_water_liters": 800,
        "water_consumption_liters_per_hour": 420,
        "replenishment_liters_per_hour": 0,
        "battery_percent": 31,
        "battery_capacity_kwh": 100,
        "power_consumption_kw": 18,
        "battery_replenishment_kw": 0,
        "medicine_units": 240,
        "medicine_consumption_per_hour": 20,
        "cold_chain_hours": 8,
        "cold_chain_depletion_hours_per_hour": 1,
        "power_available": False,
        "purification_available": True,
        "water_runway_hours": 3.5,
        "medicine_runway_hours": 6,
        "medical_demand_trend": "rising",
        "medical_demand_per_hour": 12,
        "diagnostic_capacity_per_hour": 8,
    }
    units = {
        "population": "people",
        "capacity": "people",
        "population_influx_per_hour": "people/hour",
        "potable_water_liters": "liters",
        "unsafe_water_liters": "liters",
        "water_consumption_liters_per_hour": "liters/hour",
        "replenishment_liters_per_hour": "liters/hour",
        "battery_percent": "percent",
        "battery_capacity_kwh": "kilowatt-hours",
        "power_consumption_kw": "kilowatts",
        "battery_replenishment_kw": "kilowatts",
        "medicine_units": "units",
        "medicine_consumption_per_hour": "units/hour",
        "cold_chain_hours": "hours",
        "cold_chain_depletion_hours_per_hour": "hours/hour",
        "power_available": "boolean",
        "purification_available": "boolean",
        "water_runway_hours": "hours",
        "medicine_runway_hours": "hours",
        "medical_demand_trend": "category",
        "medical_demand_per_hour": "units/hour",
        "diagnostic_capacity_per_hour": "units/hour",
    }
    return {
        "observed_at": NOW.isoformat(),
        "freshness_state": freshness,
        "values": values,
        "units": units,
        "field_freshness": {key: freshness for key in values},
        "thresholds": {
            "potable_water_liters": 1000,
            "battery_percent": 20,
            "medicine_units": 40,
            "cold_chain_hours": 2,
        },
        "sources": {key: "synthetic_shelter_seed" for key in values},
    }


def incident(phase: str = "size_up") -> dict:
    return {
        "incident_id": "inc_demo",
        "name": "North district flood",
        "hazard_type": "flood",
        "severity": "critical",
        "operational_period": "OP-1",
        "summary": "River overflow has cut multiple settlements",
        "event_time": NOW.isoformat(),
        "status": "active",
        "phase": phase,
        "roles": {"incident_commander": "usr_demo_operator"},
    }


def snapshot_inputs(**overrides):
    inputs = {
        "active_incident": None,
        "resources": [],
        "tasks": [],
        "response_queue": [],
        "verification_queue": [],
        "route_conditions": [],
        "shelter_state": None,
        "pending_recommendations": [],
        "generated_at": NOW,
        "mode": "synthetic",
    }
    inputs.update(overrides)
    return inputs


def test_empty_workspace_has_stable_shape_and_unknown_freshness():
    result = build_operational_snapshot(**snapshot_inputs())

    assert set(result) == {
        "snapshot_version",
        "generated_at",
        "audit_timestamp",
        "correlation_id",
        "mode",
        "active_incident",
        "incident_phase",
        "resource_counts",
        "active_tasks",
        "response_queue",
        "verification_queue",
        "route_conditions",
        "current_shelter_state",
        "runway_projections",
        "cascade_findings",
        "pending_recommendations",
        "data_freshness",
    }
    assert result["active_incident"] is None
    assert result["incident_phase"] is None
    assert result["resource_counts"] == {"total": 0, "ready": 0, "not_ready": 0, "unknown": 0}
    assert result["data_freshness"]["overall"] == "unknown"
    assert result["runway_projections"] == []
    assert result["cascade_findings"] == []


def test_synthetic_workspace_includes_derived_runway_and_cascade_data():
    result = build_operational_snapshot(
        **snapshot_inputs(
            active_incident=incident(),
            resources=[{"readiness": "ready"}, {"readiness": "not_ready"}],
            route_conditions=[{"id": "route-1", "destination": "North Sector", "state": "blocked"}],
            shelter_state=shelter_state(),
            pending_recommendations=[
                {
                    "id": "rec-1",
                    "status": "pending_approval",
                    "action": "Protect water",
                    "auto_dispatched": False,
                }
            ],
        )
    )

    assert result["mode"] == "synthetic"
    assert result["resource_counts"]["ready"] == 1
    assert result["runway_projections"]
    assert result["cascade_findings"]
    assert result["data_freshness"] == {
        "overall": "fresh",
        "shelter_state": "fresh",
        "routes": "fresh",
        "incident": "fresh",
        "recommendations": "fresh",
        "as_of": NOW.isoformat(),
    }
    assert "diagnosis" not in str(result).lower()


def test_active_incident_phase_is_exposed_without_adding_mutation():
    result = build_operational_snapshot(
        **snapshot_inputs(active_incident=incident("stabilization"))
    )

    assert result["active_incident"]["status"] == "active"
    assert result["incident_phase"] == "stabilization"


def test_snapshot_endpoint_is_scoped_to_the_request_workspace():
    operations = InMemoryOperationsStore()
    incidents = InMemoryIncidentStore()
    shelters = InMemoryShelterStateStore()
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=operations,
        incident_store=incidents,
        shelter_state_store=shelters,
        clock=FixedClock(NOW),
    )
    app.state.decision_store.replay(CONTEXT, NOW, "snapshot-replay")
    app.state.decision_store.recommend(CONTEXT, NOW, "snapshot-recommendation")
    shelters.seed_demo(CONTEXT, NOW)
    other = RequestContext(
        "other", "operator", "org-other", "workspace-other", frozenset(), "other"
    )
    operations.seed_demo(other, NOW, "other-seed")
    shelters.seed_demo(other, NOW)
    app.state.decision_store.replay(other, NOW, "other-replay")
    app.state.decision_store.recommend(other, NOW, "other-recommendation")

    response = TestClient(app).get(
        "/api/v1/command/operational-snapshot", headers={"X-Dev-Identity": "operator"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resource_counts"]["total"] == 7
    assert body["current_shelter_state"]["shelter"]["id"] == "shelter_demo_north"
    assert body["pending_recommendations"]["count"] == 1
    assert body["pending_recommendations"]["items"][0]["auto_dispatched"] is False


def test_stale_data_remains_visible_in_freshness_and_projections():
    stale_route = {
        "id": "route-stale",
        "destination": "North Sector",
        "state": "passable",
        "observed_at": (NOW - timedelta(hours=2)).isoformat(),
        "expires_at": (NOW - timedelta(minutes=1)).isoformat(),
    }
    result = build_operational_snapshot(
        **snapshot_inputs(shelter_state=shelter_state("stale"), route_conditions=[stale_route])
    )

    assert result["data_freshness"]["shelter_state"] == "stale"
    assert result["data_freshness"]["routes"] == "stale"
    assert result["data_freshness"]["overall"] == "stale"
    assert result["route_conditions"]["items"][0]["freshness_state"] == "stale"
    assert all(item["freshness_state"] == "stale" for item in result["runway_projections"])


def test_snapshot_item_lists_are_bounded():
    result = build_operational_snapshot(
        **snapshot_inputs(
            tasks=[{"id": str(index), "status": "assigned"} for index in range(75)],
            response_queue=[{"id": str(index), "status": "queued"} for index in range(75)],
            verification_queue=[{"id": str(index), "status": "queued"} for index in range(75)],
            route_conditions=[{"id": str(index), "state": "unknown"} for index in range(75)],
            pending_recommendations=[
                {"id": str(index), "status": "pending_approval"} for index in range(75)
            ],
        )
    )

    assert all(
        len(result[key]["items"]) == 50
        for key in (
            "active_tasks",
            "response_queue",
            "verification_queue",
            "route_conditions",
            "pending_recommendations",
        )
    )
