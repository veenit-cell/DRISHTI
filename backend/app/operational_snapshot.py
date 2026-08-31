"""Bounded, read-only composition for the command operational snapshot."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.cascade import CascadeRequest, CascadeSnapshot, evaluate_cascade
from app.runway import RunwayRequest, RunwaySnapshot, THRESHOLD_UNITS, UNITS, project_runway

MAX_ITEMS = 50
_TERMINAL_STATUSES = {"completed", "cancelled", "rejected"}
_CASCADE_STATE_FIELDS = {
    "population",
    "capacity",
    "population_influx_per_hour",
    "unsafe_water_liters",
    "cold_chain_hours",
    "power_available",
    "purification_available",
    "water_runway_hours",
    "medicine_runway_hours",
    "medical_demand_trend",
    "medical_demand_per_hour",
    "diagnostic_capacity_per_hour",
}
_FRESHNESS_STATES = {"fresh", "stale", "unknown"}


def _freshness(value: Any) -> str:
    return value if value in _FRESHNESS_STATES else "unknown"


def _aggregate_freshness(values: list[str]) -> str:
    states = [_freshness(value) for value in values]
    if "stale" in states:
        return "stale"
    if "unknown" in states or not states:
        return "unknown"
    return "fresh"


def _bounded(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return items[:MAX_ITEMS]


def _incident_view(incident: dict[str, Any] | None) -> dict[str, Any] | None:
    if incident is None:
        return None
    return {
        "incident_id": incident.get("incident_id"),
        "name": incident.get("name"),
        "hazard_type": incident.get("hazard_type"),
        "severity": incident.get("severity"),
        "operational_period": incident.get("operational_period"),
        "summary": incident.get("summary"),
        "event_time": incident.get("event_time"),
        "status": incident.get("status"),
        "phase": incident.get("phase"),
        "roles": dict(incident.get("roles") or {}),
    }


def _task_view(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "queue_item_id": task.get("queue_item_id"),
        "resource_id": task.get("resource_id"),
        "status": task.get("status"),
        "approved_by": task.get("approved_by"),
        "approved_at": task.get("approved_at"),
        "updated_at": task.get("updated_at"),
    }


def _queue_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "priority": item.get("priority"),
        "destination": item.get("destination"),
        "queue_type": item.get("queue_type"),
        "required_capability": item.get("required_capability"),
        "source_recommendation_id": item.get("source_recommendation_id"),
        "status": item.get("status"),
        "created_at": item.get("created_at"),
    }


def _route_freshness(route: dict[str, Any], generated_at: datetime) -> str:
    state = route.get("freshness_state")
    if state in _FRESHNESS_STATES:
        return state
    if route.get("state") in {"stale"}:
        return "stale"
    if route.get("state") in {"unknown"}:
        return "unknown"
    expires_at = route.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(str(expires_at)) <= generated_at:
                return "stale"
        except (TypeError, ValueError):
            return "unknown"
    return "fresh" if route.get("state") else "unknown"


def _route_view(route: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    return {
        "id": route.get("id"),
        "destination": route.get("destination"),
        "state": route.get("state"),
        "source": route.get("source"),
        "observed_at": route.get("observed_at"),
        "expires_at": route.get("expires_at"),
        "freshness_state": _route_freshness(route, generated_at),
    }


def _recommendation_view(recommendation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": recommendation.get("id"),
        "status": recommendation.get("status"),
        "action": recommendation.get("action"),
        "sector": recommendation.get("sector"),
        "reasons": list(recommendation.get("reasons") or [])[:10],
        "rule": recommendation.get("rule"),
        "priority": recommendation.get("priority"),
        "expires_at": recommendation.get("expires_at"),
        "created_at": recommendation.get("created_at"),
        "auto_dispatched": bool(recommendation.get("auto_dispatched", False)),
    }


def _shelter_view(shelter_state: dict[str, Any] | None) -> dict[str, Any] | None:
    if shelter_state is None:
        return None
    view = {
        key: shelter_state.get(key)
        for key in ("shelter", "observed_at", "freshness_state", "snapshot_hash")
    }
    for key in ("values", "units", "field_freshness", "sources"):
        value = shelter_state.get(key)
        view[key] = dict(list(value.items())[:30]) if isinstance(value, dict) else {}
    provenance = shelter_state.get("provenance")
    view["provenance"] = (
        {
            key: dict(list(value.items())[:10]) if isinstance(value, dict) else {}
            for key, value in list(provenance.items())[:30]
        }
        if isinstance(provenance, dict)
        else {}
    )
    return view


def _runway_projections(shelter_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not shelter_state:
        return []
    values = shelter_state.get("values") or {}
    units = shelter_state.get("units") or {}
    field_freshness = shelter_state.get("field_freshness") or {}
    thresholds = shelter_state.get("thresholds") or {}
    snapshot = RunwaySnapshot(
        observed_at=shelter_state.get("observed_at"),
        freshness_state=_freshness(shelter_state.get("freshness_state")),
        values={key: value for key, value in values.items() if key in UNITS},
        units={key: value for key, value in units.items() if key in UNITS},
        field_freshness={key: value for key, value in field_freshness.items() if key in UNITS},
        thresholds={key: value for key, value in thresholds.items() if key in THRESHOLD_UNITS},
    )
    return project_runway(RunwayRequest(snapshot=snapshot)).model_dump(mode="json")[
        "projections"
    ][:10]


def _cascade_findings(shelter_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not shelter_state:
        return []
    values = shelter_state.get("values") or {}
    units = shelter_state.get("units") or {}
    field_freshness = shelter_state.get("field_freshness") or {}
    sources = shelter_state.get("sources") or {}
    cascade_units = {
        key: ("units/hour" if key == "diagnostic_capacity_per_hour" and value == "cases/hour" else value)
        for key, value in units.items()
        if key in _CASCADE_STATE_FIELDS
    }
    snapshot = CascadeSnapshot(
        observed_at=shelter_state.get("observed_at"),
        freshness_state=_freshness(shelter_state.get("freshness_state")),
        values={key: value for key, value in values.items() if key in _CASCADE_STATE_FIELDS},
        units=cascade_units,
        field_freshness={
            key: value for key, value in field_freshness.items() if key in _CASCADE_STATE_FIELDS
        },
        supporting_refs={
            key: [source]
            for key, source in sources.items()
            if key in _CASCADE_STATE_FIELDS and source
        },
    )
    return evaluate_cascade(CascadeRequest(snapshot=snapshot)).model_dump(mode="json")[
        "findings"
    ][:MAX_ITEMS]


def build_operational_snapshot(
    *,
    active_incident: dict[str, Any] | None,
    resources: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    response_queue: list[dict[str, Any]],
    verification_queue: list[dict[str, Any]],
    route_conditions: list[dict[str, Any]],
    shelter_state: dict[str, Any] | None,
    pending_recommendations: list[dict[str, Any]],
    generated_at: datetime,
    mode: str,
    correlation_id: str | None = None,
    unavailable_stores: list[str] | None = None,
) -> dict[str, Any]:
    active_tasks = [
        item for item in tasks if item.get("status") not in _TERMINAL_STATUSES
    ]
    response_items = [
        item for item in response_queue if item.get("status") not in _TERMINAL_STATUSES
    ]
    verification_items = [
        item for item in verification_queue if item.get("status") not in _TERMINAL_STATUSES
    ]
    incident_view = _incident_view(active_incident)
    route_views = [_route_view(item, generated_at) for item in route_conditions]
    shelter_freshness = _freshness((shelter_state or {}).get("freshness_state"))
    route_freshness = _aggregate_freshness([item["freshness_state"] for item in route_views])
    freshness = {
        "overall": _aggregate_freshness(
            [
                shelter_freshness,
                route_freshness,
                "fresh" if incident_view else "unknown",
                "fresh" if pending_recommendations else "unknown",
            ]
        ),
        "shelter_state": shelter_freshness,
        "routes": route_freshness,
        "incident": "fresh" if incident_view else "unknown",
        "recommendations": "fresh" if pending_recommendations else "unknown",
        "as_of": generated_at.isoformat(),
    }
    normalized_mode = mode if mode in {"live", "synthetic", "mixed"} else "synthetic"
    unavailable = sorted(set(unavailable_stores or []))
    if unavailable:
        freshness["overall"] = "unknown"
        freshness["state"] = "degraded"
    return {
        "snapshot_version": "operational_snapshot_v1",
        "generated_at": generated_at.isoformat(),
        "audit_timestamp": generated_at.isoformat(),
        "correlation_id": correlation_id,
        "mode": normalized_mode,
        "availability": {
            "state": "degraded" if unavailable else "available",
            "unavailable_stores": unavailable,
        },
        "active_incident": incident_view,
        "incident_phase": incident_view.get("phase") if incident_view else None,
        "resource_counts": {
            "total": len(resources),
            "ready": sum(1 for item in resources if item.get("readiness") == "ready"),
            "not_ready": sum(1 for item in resources if item.get("readiness") == "not_ready"),
            "unknown": sum(1 for item in resources if item.get("readiness") == "unknown"),
        },
        "active_tasks": {
            "count": len(active_tasks),
            "items": _bounded([_task_view(item) for item in active_tasks]),
        },
        "response_queue": {
            "count": len(response_items),
            "items": _bounded([_queue_view(item) for item in response_items]),
        },
        "verification_queue": {
            "count": len(verification_items),
            "items": _bounded([_queue_view(item) for item in verification_items]),
        },
        "route_conditions": {"count": len(route_views), "items": _bounded(route_views)},
        "current_shelter_state": _shelter_view(shelter_state),
        "runway_projections": _runway_projections(shelter_state),
        "cascade_findings": _cascade_findings(shelter_state),
        "pending_recommendations": {
            "count": len(pending_recommendations),
            "items": _bounded([_recommendation_view(item) for item in pending_recommendations]),
        },
        "data_freshness": freshness,
    }
