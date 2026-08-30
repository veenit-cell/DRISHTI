"""Bounded scoped polling events and low-cardinality telemetry."""
# ruff: noqa: E501

from __future__ import annotations

import base64
import binascii
from collections import Counter
from threading import Lock
from time import monotonic
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UpdatePublish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=64)
    aggregate_id: str = Field(min_length=1, max_length=128)
    status: str | None = Field(default=None, max_length=32)


class UpdateFeed:
    def __init__(self, max_events: int = 500) -> None:
        self.events: list[dict[str, Any]] = []
        self.max_events = max_events
        self._next_cursor = 1
        self.lock = Lock()

    def publish(self, tenant_id: str, workspace_id: str, event_type: str, payload: dict[str, Any], at: str) -> str:
        with self.lock:
            event = {"cursor": str(self._next_cursor), "tenant_id": tenant_id, "workspace_id": workspace_id, "event_type": event_type, "payload": payload, "occurred_at": at}
            self._next_cursor += 1
            self.events.append(event)
            self.events = self.events[-self.max_events :]
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
        return {"items": [{key: value for key, value in event.items() if key not in {"tenant_id", "workspace_id"}} for event in page], "next_cursor": next_cursor}


class Telemetry:
    def __init__(self) -> None:
        self.counters: Counter[tuple[str, str]] = Counter()
        self.latencies_ms: list[float] = []
        self.lock = Lock()

    def request(self, route: str, status: int, started: float) -> None:
        with self.lock:
            self.counters[("requests", "ok" if status < 400 else "error")] += 1
            self.latencies_ms.append(round((monotonic() - started) * 1000, 2))

    def increment(self, name: str, label: str = "total") -> None:
        safe_name = name if name in {"recommendation_decisions", "sync_conflicts", "queue_depth", "job_backlog"} else "other"
        safe_label = label if label in {"approved", "rejected", "conflict", "accepted", "total"} else "other"
        with self.lock:
            self.counters[(safe_name, safe_label)] += 1

    def snapshot(self, queue_depth: int = 0, job_backlog: int = 0) -> dict[str, Any]:
        with self.lock:
            values = sorted(self.latencies_ms[-1000:])
            counters = {f"{name}:{label}": count for (name, label), count in sorted(self.counters.items())}
            for key in ("recommendation_decisions:approved", "recommendation_decisions:rejected", "sync_conflicts:conflict"):
                counters.setdefault(key, 0)
            return {"counters": counters, "latency_ms": {"count": len(values), "p50": values[len(values) // 2] if values else None, "p95": values[min(len(values) - 1, int(len(values) * .95))] if values else None}, "queue_depth": min(queue_depth, 1000), "job_backlog": min(job_backlog, 1000)}
