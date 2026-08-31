"""Read-only operational summary for the command workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Any


_TERMINAL_STATUSES = {"completed", "cancelled", "rejected"}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_command_summary(
    *,
    resources: list[dict[str, Any]],
    response_queue: list[dict[str, Any]],
    verification_queue: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    scenario: dict[str, Any],
    generated_at: datetime,
    workspace_mode: str | None = None,
    correlation_id: str | None = None,
    freshness_state: str = "fresh",
    unavailable_stores: list[str] | None = None,
    source: str = "api",
) -> dict[str, Any]:
    """Build a bounded, UI-friendly summary without mutating operational state."""
    ready_resources = sum(
        1 for item in resources if str(item.get("readiness", "")).lower() == "ready"
    )
    active_tasks = sum(
        1 for item in tasks if str(item.get("status", "")).lower() not in _TERMINAL_STATUSES
    )
    open_response = sum(
        1
        for item in response_queue
        if str(item.get("status", "")).lower() not in _TERMINAL_STATUSES
    )
    open_verification = sum(
        1
        for item in verification_queue
        if str(item.get("status", "")).lower() not in _TERMINAL_STATUSES
    )
    safe_scenario = scenario or {}
    signals = safe_scenario.get("signals", {}) or {}
    water_runway = signals.get("water_runway_hours")
    contamination = signals.get("contamination")
    influx = signals.get("population_influx")
    priorities: list[dict[str, Any]] = []
    if _is_number(water_runway) and water_runway < 6:
        priorities.append(
            {
                "key": "water-runway",
                "label": "Protect potable-water continuity",
                "reason": f"Water runway is {water_runway:g} hours, below the 6-hour threshold.",
                "severity": "critical",
            }
        )
    if contamination in {"elevated", "high", "critical"}:
        priorities.append(
            {
                "key": "contamination",
                "label": "Verify contamination signal",
                "reason": f"Contamination signal is {contamination}.",
                "severity": "high",
            }
        )
    if open_verification:
        priorities.append(
            {
                "key": "verification",
                "label": "Resolve information gaps",
                "reason": f"{open_verification} verification item(s) may change the response plan.",
                "severity": "unknown",
            }
        )
    return {
        "generated_at": generated_at.isoformat(),
        "correlation_id": correlation_id,
        "freshness": {
            "state": freshness_state if freshness_state in {"fresh", "stale", "unknown", "degraded"} else "unknown",
            "as_of": generated_at.isoformat(),
        },
        "availability": {
            "state": "degraded" if unavailable_stores else "available",
            "unavailable_stores": sorted(set(unavailable_stores or [])),
        },
        "source": source,
        "provenance": {
            "source": "command_summary_api",
            "source_class": "synthetic_fixture" if workspace_mode == "synthetic" or safe_scenario.get("synthetic") else "derived_model",
            "synthetic": bool(workspace_mode == "synthetic" or safe_scenario.get("synthetic")),
            "affected_entity_type": "workspace",
            "affected_entity_id": "current_workspace",
        },
        "mode": (
            "synthetic"
            if workspace_mode == "synthetic" or safe_scenario.get("synthetic")
            else workspace_mode if workspace_mode in {"live", "mixed"} else "operational"
        ),
        "metrics": {
            "ready_resources": ready_resources,
            "total_resources": len(resources),
            "active_tasks": active_tasks,
            "response_queue": open_response,
            "verification_queue": open_verification,
            "population_influx": influx,
            "water_runway_hours": water_runway,
            "contamination": contamination,
        },
        "priorities": priorities[:3],
        "data_quality": {
            "contamination": contamination,
            "scenario_replayed_at": safe_scenario.get("replayed_at"),
            "synthetic": bool(safe_scenario.get("synthetic")),
        },
    }
