"""Bounded scoped polling events and low-cardinality telemetry."""
# ruff: noqa: E501

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import Counter
from threading import Lock
from time import monotonic
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


OperationalUpdateType = Literal[
    "shelter_state_changed",
    "route_condition_changed",
    "incident_phase_changed",
    "recommendation_changed",
    "resource_readiness_changed",
    "task_status_changed",
    "verification_priority_changed",
    "communication_gap_detected",
    "communication_gap_recovered",
]
UpdateEventType = OperationalUpdateType

_ENTITY_TYPES: dict[str, str] = {
    "shelter_state_changed": "shelter",
    "route_condition_changed": "route",
    "incident_phase_changed": "incident",
    "recommendation_changed": "recommendation",
    "resource_readiness_changed": "resource",
    "task_status_changed": "task",
    "verification_priority_changed": "verification_item",
    "communication_gap_detected": "communication_gap",
    "communication_gap_recovered": "communication_gap",
}
_SAFE_PAYLOAD_KEYS = {"id", "aggregate_id", "status", "state", "freshness_state", "priority"}


class UpdateEvent(BaseModel):
    """Public, bounded event envelope returned by the polling feed."""

    model_config = ConfigDict(extra="forbid")
    event_type: OperationalUpdateType
    cursor: str = Field(min_length=1, max_length=128)
    occurred_at: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    source_class: str = Field(default="derived_model", min_length=1, max_length=64)
    correlation_id: str = Field(default="system", min_length=1, max_length=128)
    affected_entity_type: str = Field(min_length=1, max_length=64)
    affected_entity_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


class UpdatePublish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: OperationalUpdateType
    aggregate_id: str = Field(min_length=1, max_length=128)
    status: str | None = Field(default=None, max_length=32)


def source_class_for(source: str | None) -> str:
    normalized = (source or "").lower()
    if "sensor" in normalized or "telemetry" in normalized or "lorawan" in normalized:
        return "sensor"
    if "satellite" in normalized or "usgs" in normalized:
        return "satellite_feed"
    if "synthetic" in normalized or "fixture" in normalized or "demo" in normalized:
        return "synthetic_fixture"
    if "operator" in normalized or "commander" in normalized:
        return "operator_report"
    return "derived_model"


def entity_type_for_event(event_type: str) -> str:
    return _ENTITY_TYPES.get(event_type, "aggregate")


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep polling payloads low-cardinality and free of raw operational detail."""
    safe: dict[str, Any] = {}
    for key in _SAFE_PAYLOAD_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and len(value) <= 256:
            safe[key] = value
        elif isinstance(value, (int, float, bool)) or value is None:
            if key in payload:
                safe[key] = value
    return safe


def publish_communication_gap_event(
    feed: "UpdateFeed",
    tenant_id: str,
    workspace_id: str,
    entity_id: str,
    detected: bool,
    occurred_at: str,
    correlation_id: str,
    idempotency_key: str | None = None,
) -> str:
    """Publish a telemetry gap transition for an authorized adapter callback.

    The telemetry adapter calls this only when its health state changes; reads do
    not infer or publish events. The payload contains no device credentials or
    raw measurements.
    """
    event_type = "communication_gap_detected" if detected else "communication_gap_recovered"
    return feed.publish(
        tenant_id,
        workspace_id,
        event_type,
        {"id": entity_id, "state": "detected" if detected else "recovered", "freshness_state": "silent" if detected else "fresh"},
        occurred_at,
        source="lorawan_adapter",
        source_class="sensor",
        correlation_id=correlation_id,
        affected_entity_type="communication_gap",
        affected_entity_id=entity_id,
        idempotency_key=idempotency_key,
    )


class UpdateFeed:
    def __init__(self, max_events: int = 500) -> None:
        self.events: list[dict[str, Any]] = []
        self.max_events = max_events
        self._next_cursor = 1
        self._idempotency_cursors: dict[tuple[str, str, str], str] = {}
        self._idempotency_digests: dict[tuple[str, str, str], str] = {}
        self._idempotency_seen_at: dict[tuple[str, str, str], float] = {}
        self.idempotency_ttl_seconds = 24 * 60 * 60
        self.lock = Lock()

    def publish(
        self,
        tenant_id: str,
        workspace_id: str,
        event_type: str,
        payload: dict[str, Any],
        at: str,
        *,
        source: str = "system",
        source_class: str | None = None,
        correlation_id: str = "system",
        affected_entity_type: str | None = None,
        affected_entity_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        with self.lock:
            resolved_source_class = source_class or source_class_for(source)
            now_monotonic = monotonic()
            expired = [
                identity
                for identity, seen_at in self._idempotency_seen_at.items()
                if now_monotonic - seen_at > self.idempotency_ttl_seconds
            ]
            for identity in expired:
                self._idempotency_seen_at.pop(identity, None)
                self._idempotency_cursors.pop(identity, None)
                self._idempotency_digests.pop(identity, None)
            identity = (tenant_id, workspace_id, idempotency_key) if idempotency_key else None
            idempotency_digest = hashlib.sha256(
                json.dumps(
                    {
                        "event_type": event_type,
                        "payload": _safe_payload(payload),
                        "source": source,
                        "source_class": resolved_source_class,
                        "affected_entity_type": affected_entity_type or entity_type_for_event(event_type),
                        "affected_entity_id": affected_entity_id or str(payload.get("id") or payload.get("aggregate_id") or "unknown"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if idempotency_key:
                existing_cursor = self._idempotency_cursors.get(identity)
                if existing_cursor:
                    if self._idempotency_digests.get(identity) != idempotency_digest:
                        raise ValueError("This key was already used for a different update.")
                    return existing_cursor
            cursor = str(self._next_cursor)
            event_fields = {
                "event_type": event_type,
                "cursor": cursor,
                "occurred_at": at,
                "source": source,
                "source_class": resolved_source_class,
                "correlation_id": correlation_id,
                "affected_entity_type": affected_entity_type or entity_type_for_event(event_type),
                "affected_entity_id": affected_entity_id or str(payload.get("id") or payload.get("aggregate_id") or "unknown"),
                "payload": _safe_payload(payload),
            }
            # Keep older internal feed producers readable while strictly typing the
            # six operational events exposed by the current API.
            public_event = (
                UpdateEvent(**event_fields).model_dump()
                if event_type in _ENTITY_TYPES
                else event_fields
            )
            event = {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "_idempotency_key": idempotency_key,
                **public_event,
            }
            self._next_cursor += 1
            self.events.append(event)
            self.events = self.events[-self.max_events :]
            if idempotency_key:
                self._idempotency_cursors[identity] = cursor
                self._idempotency_digests[identity] = idempotency_digest
                self._idempotency_seen_at[identity] = now_monotonic
            return event["cursor"]

    def poll(self, tenant_id: str, workspace_id: str, cursor: str | None, limit: int = 50) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        start = 0
        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode() + b"=" * (-len(cursor) % 4)).decode()
                start = int(decoded)
            except (ValueError, UnicodeDecodeError, binascii.Error):
                raise ValueError("invalid update cursor") from None
            if start < 0:
                raise ValueError("invalid update cursor")
        scoped = [event for event in self.events if event["tenant_id"] == tenant_id and event["workspace_id"] == workspace_id and int(event["cursor"]) > start]
        page = scoped[:limit]
        next_value = int(page[-1]["cursor"]) if page else start
        next_cursor = base64.urlsafe_b64encode(str(next_value).encode()).decode().rstrip("=")
        return {
            "items": [
                {
                    key: value
                    for key, value in event.items()
                    if key not in {"tenant_id", "workspace_id", "_idempotency_key"}
                }
                for event in page
            ],
            "next_cursor": next_cursor,
        }


class Telemetry:
    _COUNTER_NAMES = {
        "recommendation_decisions",
        "sync_conflicts",
        "queue_depth",
        "job_backlog",
        "failed_writes",
        "duplicate_retries",
        "stale_feed_reads",
        "offline_reconciliation_failures",
        "external_integration_failures",
    }

    def __init__(self) -> None:
        self.counters: Counter[tuple[str, str]] = Counter()
        self.latencies_ms: list[float] = []
        self.lock = Lock()

    def request(self, route: str, status: int, started: float) -> None:
        with self.lock:
            self.counters[("requests", "ok" if status < 400 else "error")] += 1
            self.latencies_ms.append(round((monotonic() - started) * 1000, 2))

    def increment(self, name: str, label: str = "total") -> None:
        safe_name = name if name in self._COUNTER_NAMES else "other"
        safe_label = label if label in {"approved", "rejected", "conflict", "accepted", "blocked", "total"} else "other"
        with self.lock:
            self.counters[(safe_name, safe_label)] += 1

    def snapshot(self, queue_depth: int = 0, job_backlog: int = 0) -> dict[str, Any]:
        with self.lock:
            values = sorted(self.latencies_ms[-1000:])
            counters = {f"{name}:{label}": count for (name, label), count in sorted(self.counters.items())}
            for key in (
                "recommendation_decisions:approved",
                "recommendation_decisions:rejected",
                "sync_conflicts:conflict",
                "failed_writes:total",
                "duplicate_retries:total",
                "stale_feed_reads:total",
                "offline_reconciliation_failures:total",
                "external_integration_failures:total",
            ):
                counters.setdefault(key, 0)
            return {"counters": counters, "latency_ms": {"count": len(values), "p50": values[len(values) // 2] if values else None, "p95": values[min(len(values) - 1, int(len(values) * .95))] if values else None}, "queue_depth": min(queue_depth, 1000), "job_backlog": min(job_backlog, 1000)}
