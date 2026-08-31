"""Bounded, server-authoritative command reconciliation for field PWA clients."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_BATCH = 20
CommandKind = Literal[
    "report",
    "acknowledgement",
    "en_route",
    "on_scene",
    "paused",
    "completion",
    "route_observation",
    "outcome",
]
SyncStatus = Literal["accepted", "replayed", "rejected", "conflict", "blocked"]


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


class SyncResult(BaseModel):
    """The reconciliation result for one command, without claiming local application."""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    aggregate_id: str
    sequence: int
    status: SyncStatus
    client_timestamp: str | None = None
    server_timestamp: str | None = None
    reason: str | None = None
    conflict_explanation: str | None = None
    expected_sequence: int | None = None
    retryable: bool = False


class ReconciliationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: int = 0
    replayed: int = 0
    rejected: int = 0
    blocked: int = 0
    conflicts: int = 0
    server_timestamp: str
    expected_sequence_number: dict[str, int] = Field(default_factory=dict)
    safe_to_retry: bool = False
    retryable_command_ids: list[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_at: str
    results: list[SyncResult]
    reconciliation: ReconciliationSummary


class OfflineSyncStore:
    """Small authoritative reconciliation store used by the PWA adapter.

    The store never applies a payload to operational state. It only records an
    idempotent, ordered reconciliation decision. Scope is part of every key so
    the same command ID cannot replay data from another tenant or workspace.
    """

    def __init__(self) -> None:
        self.accepted: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.last_sequence: dict[tuple[str, str, str], int] = {}
        self.last_client_timestamp: dict[tuple[str, str, str], datetime] = {}
        self.blocked: set[tuple[str, str, str]] = set()

    @staticmethod
    def _fingerprint(command: OfflineCommand) -> str:
        canonical = {
            "aggregate_id": command.aggregate_id,
            "sequence": command.sequence,
            "kind": command.kind,
            "client_timestamp": command.client_timestamp.isoformat(),
            "payload": command.payload,
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _result(
        command: OfflineCommand,
        status: SyncStatus,
        *,
        server_timestamp: str | None = None,
        reason: str | None = None,
        conflict_explanation: str | None = None,
        expected_sequence: int | None = None,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return {
            "command_id": command.command_id,
            "aggregate_id": command.aggregate_id,
            "sequence": command.sequence,
            "status": status,
            "client_timestamp": command.client_timestamp.isoformat(),
            "server_timestamp": server_timestamp,
            "reason": reason,
            "conflict_explanation": conflict_explanation,
            "expected_sequence": expected_sequence,
            "retryable": retryable,
        }

    def reconcile(
        self, batch: SyncBatch, tenant_id: str, workspace_id: str, now: datetime
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        touched: set[tuple[str, str, str]] = set()

        for command in batch.commands:
            if command.tenant_id != tenant_id or command.workspace_id != workspace_id:
                results.append(
                    self._result(
                        command,
                        "rejected",
                        reason="cross-scope command",
                        conflict_explanation="The command scope does not match the authenticated tenant and workspace.",
                    )
                )
                continue

            key = (tenant_id, workspace_id, command.aggregate_id)
            touched.add(key)
            command_key = (tenant_id, workspace_id, command.command_id)
            existing = self.accepted.get(command_key)
            if existing is not None:
                if existing["fingerprint"] != self._fingerprint(command):
                    results.append(
                        self._result(
                            command,
                            "rejected",
                            reason="duplicate command ID with different content",
                            conflict_explanation="The command ID was already reconciled with different content; it was not replayed.",
                        )
                    )
                else:
                    results.append(
                        self._result(
                            command,
                            "replayed",
                            server_timestamp=existing["server_timestamp"],
                        )
                    )
                continue

            expected = self.last_sequence.get(key, 0) + 1
            if command.sequence != expected:
                self.blocked.add(key)
                results.append(
                    self._result(
                        command,
                        "conflict",
                        reason=f"expected sequence {expected}",
                        conflict_explanation=(
                            f"This command was not applied because the server expected sequence {expected}. "
                            "Reconcile the missing command first, then retry this command."
                        ),
                        expected_sequence=expected,
                        retryable=True,
                    )
                )
                continue

            previous_client_timestamp = self.last_client_timestamp.get(key)
            if previous_client_timestamp and command.client_timestamp < previous_client_timestamp:
                self.blocked.add(key)
                results.append(
                    self._result(
                        command,
                        "blocked",
                        reason="older client timestamp than reconciled state",
                        conflict_explanation=(
                            "The command is older than the latest reconciled command for this aggregate. "
                            "It was blocked so newer operational state cannot be overwritten by stale offline data."
                        ),
                        expected_sequence=expected,
                    )
                )
                continue

            server_timestamp = now.isoformat()
            record = {
                "command_id": command.command_id,
                "status": "accepted",
                "aggregate_id": command.aggregate_id,
                "sequence": command.sequence,
                "kind": command.kind,
                "client_timestamp": command.client_timestamp.isoformat(),
                "server_timestamp": server_timestamp,
                "payload": command.payload,
                "fingerprint": self._fingerprint(command),
            }
            self.accepted[command_key] = record
            self.last_sequence[key] = command.sequence
            self.last_client_timestamp[key] = command.client_timestamp
            self.blocked.discard(key)
            results.append(
                self._result(
                    command,
                    "accepted",
                    server_timestamp=server_timestamp,
                    expected_sequence=command.sequence + 1,
                )
            )

        expected_sequences = {
            key[2]: self.last_sequence.get(key, 0) + 1 for key in touched
        }
        counts = {
            "accepted": sum(item["status"] == "accepted" for item in results),
            "replayed": sum(item["status"] == "replayed" for item in results),
            "rejected": sum(item["status"] == "rejected" for item in results),
            "blocked": sum(item["status"] in {"conflict", "blocked"} for item in results),
            "conflicts": sum(item["status"] in {"conflict", "blocked"} for item in results),
        }
        retryable_ids = [item["command_id"] for item in results if item["retryable"]]
        response = SyncResponse(
            accepted_at=now.isoformat(),
            results=[SyncResult(**item) for item in results],
            reconciliation=ReconciliationSummary(
                **counts,
                server_timestamp=now.isoformat(),
                expected_sequence_number=expected_sequences,
                safe_to_retry=bool(retryable_ids),
                retryable_command_ids=retryable_ids,
            ),
        )
        return response.model_dump(mode="json")
