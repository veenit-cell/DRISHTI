"""Scoped, immutable decision-snapshot integration adapter."""
# ruff: noqa: E501, UP038

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SNAPSHOT_VERSION = "decision_snapshot_v1"


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    tenant_id: str
    workspace_id: str
    revision: int = Field(ge=1)
    event_time: datetime | None = None
    recorded_at: datetime
    freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    uncertainty: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ReportRecord(SourceRecord):
    status: Literal["accepted_for_review", "reviewed"] = "accepted_for_review"
    claims: list[dict[str, Any]] = Field(default_factory=list)
    linked_incident_ids: list[str] = Field(default_factory=list)


class IncidentRecord(SourceRecord):
    verification_state: str = "unknown"


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    workspace_id: str
    replay_at: datetime
    policy_version: str = Field(min_length=1, max_length=80)
    reports: list[ReportRecord] = Field(default_factory=list, max_length=100)
    incidents: list[IncidentRecord] = Field(default_factory=list, max_length=100)
    sector_assessments: list[SourceRecord] = Field(default_factory=list, max_length=50)
    operational_observations: list[SourceRecord] = Field(default_factory=list, max_length=100)


class SnapshotSource(BaseModel):
    kind: str
    source_id: str
    revision: int
    event_time: datetime | None
    recorded_at: datetime
    freshness: str
    uncertainty: str | None
    accepted_claims: list[dict[str, Any]] = Field(default_factory=list)
    visible_claims: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class VerificationCandidate(BaseModel):
    kind: str
    reason: str
    source_ids: list[str]


class DecisionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_version: str
    tenant_id: str
    workspace_id: str
    replay_at: datetime
    policy_version: str
    sources: list[SnapshotSource]
    unknown_fields: list[str]
    verification_candidates: list[VerificationCandidate]
    synthetic_provenance: bool
    canonical_hash: str


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _in_scope(record: SourceRecord, request: SnapshotRequest) -> bool:
    return record.tenant_id == request.tenant_id and record.workspace_id == request.workspace_id


def build_decision_snapshot(request: SnapshotRequest) -> DecisionSnapshot:
    """Resolve only in-scope records at replay time; never mutates inputs."""
    records: list[SnapshotSource] = []
    unknown: set[str] = set()
    verification: list[VerificationCandidate] = []
    incidents = {item.id: item for item in request.incidents if _in_scope(item, request) and (item.event_time or item.recorded_at) <= request.replay_at}
    for report in request.reports:
        if not _in_scope(report, request):
            raise ValueError(f"out-of-scope report: {report.id}")
        if report.recorded_at > request.replay_at or report.event_time and report.event_time > request.replay_at:
            continue
        visible = [dict(claim) for claim in report.claims]
        accepted = [dict(claim) for claim in visible if claim.get("verification_state") == "corroborated"]
        if not accepted:
            verification.append(VerificationCandidate(kind="evidence", reason="reviewed claim could change a decision", source_ids=[report.id]))
        if any(claim.get("verification_state") in {"unknown", "stale"} for claim in visible):
            unknown.add(f"report:{report.id}:claim_state")
        if any(claim.get("verification_state") == "contradicted" for claim in visible):
            unknown.add(f"report:{report.id}:contradiction")
        missing = set(report.linked_incident_ids) - set(incidents)
        if missing:
            verification.append(VerificationCandidate(kind="incident", reason="linked incident is unavailable in the replay scope/time", source_ids=sorted(missing)))
        records.append(SnapshotSource(kind="report", source_id=report.id, revision=report.revision, event_time=report.event_time, recorded_at=report.recorded_at, freshness=report.freshness, uncertainty=report.uncertainty, accepted_claims=accepted, visible_claims=visible, data={"linked_incident_ids": sorted(set(report.linked_incident_ids) & set(incidents))}))
    for incident in incidents.values():
        records.append(SnapshotSource(kind="incident", source_id=incident.id, revision=incident.revision, event_time=incident.event_time, recorded_at=incident.recorded_at, freshness=incident.freshness, uncertainty=incident.uncertainty, data=incident.data | {"verification_state": incident.verification_state}))
        if incident.verification_state in {"unknown", "unassessed"}:
            unknown.add(f"incident:{incident.id}:verification_state")
    for kind, items in (("sector", request.sector_assessments), ("observation", request.operational_observations)):
        for item in items:
            if not _in_scope(item, request):
                raise ValueError(f"out-of-scope {kind}: {item.id}")
            if item.recorded_at > request.replay_at or item.event_time and item.event_time > request.replay_at:
                continue
            records.append(SnapshotSource(kind=kind, source_id=item.id, revision=item.revision, event_time=item.event_time, recorded_at=item.recorded_at, freshness=item.freshness, uncertainty=item.uncertainty, data=dict(item.data)))
            if item.freshness != "fresh":
                unknown.add(f"{kind}:{item.id}:freshness")
    if not records:
        verification.append(VerificationCandidate(kind="snapshot", reason="no decision-relevant evidence resolved at replay time", source_ids=[]))
    records.sort(key=lambda item: (item.kind, item.source_id, item.revision))
    provenance = any(item.data.get("source") == "synthetic_demo_seed" for item in records)
    payload = {"snapshot_version": SNAPSHOT_VERSION, "tenant_id": request.tenant_id, "workspace_id": request.workspace_id, "replay_at": request.replay_at, "policy_version": request.policy_version, "sources": [item.model_dump(mode="json") for item in records], "unknown_fields": sorted(unknown), "verification_candidates": [item.model_dump(mode="json") for item in verification], "synthetic_provenance": provenance}
    return DecisionSnapshot(**payload, canonical_hash=_hash(payload))
