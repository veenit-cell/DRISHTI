"""Bounded, server-authoritative command reconciliation for field PWA clients."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_BATCH = 20
CommandKind = Literal["report", "acknowledgement", "en_route", "completion", "route_observation", "outcome"]


class OfflineCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=3, max_length=128)
    aggregate_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    kind: CommandKind
    client_timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict, max_length=20)
    tenant_id: str
    workspace_id: str


class SyncBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[OfflineCommand] = Field(min_length=1, max_length=MAX_BATCH)


class OfflineSyncStore:
    def __init__(self) -> None:
        self.accepted: dict[tuple[str, str], dict[str, Any]] = {}
        self.last_sequence: dict[tuple[str, str], int] = {}
        self.blocked: set[tuple[str, str]] = set()

    def reconcile(self, batch: SyncBatch, tenant_id: str, workspace_id: str, now: datetime) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        blocked_batch: set[tuple[str, str]] = set()
        for command in batch.commands:
            key = (command.aggregate_id, workspace_id)
            if command.tenant_id != tenant_id or command.workspace_id != workspace_id:
                results.append({"command_id": command.command_id, "status": "rejected", "reason": "cross-scope command"})
                continue
            if command.command_id in self.accepted:
                results.append({"command_id": command.command_id, "status": "replayed", "server_timestamp": self.accepted[command.command_id]["server_timestamp"]})
                continue
            expected = self.last_sequence.get(key, 0) + 1
            if (key in self.blocked or key in blocked_batch) and command.sequence != expected:
                results.append({"command_id": command.command_id, "status": "conflict", "reason": "aggregate blocked by unresolved ordering conflict"})
                continue
            if command.sequence != expected:
                blocked_batch.add(key)
                self.blocked.add(key)
                results.append({"command_id": command.command_id, "status": "conflict", "reason": f"expected sequence {expected}"})
                continue
            record = {"command_id": command.command_id, "status": "accepted", "aggregate_id": command.aggregate_id, "sequence": command.sequence, "kind": command.kind, "client_timestamp": command.client_timestamp.isoformat(), "server_timestamp": now.isoformat(), "payload": command.payload}
            self.accepted[command.command_id] = record
            self.last_sequence[key] = command.sequence
            results.append(record)
        return {"accepted_at": now.isoformat(), "results": results}
