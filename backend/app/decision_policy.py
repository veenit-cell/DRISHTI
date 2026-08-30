"""Deterministic intervention policy; evaluation never mutates operational state."""
# ruff: noqa: E501, UP038

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "intervention_policy_v1"
MAX_CANDIDATES = 3
MAX_HORIZON_HOURS = 168.0


class PolicySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    expires_at: datetime | None = None
    values: dict[str, float | str | None] = Field(default_factory=dict, max_length=30)
    freshness_state: Literal["fresh", "stale", "unknown"] = "unknown"


class ProjectionAdapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str
    state: str
    time_to_critical_hours: float | None = None
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"


class CascadeAdapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affected_capability: str
    severity: Literal["critical", "high", "medium", "low"]
    supporting_input_refs: list[str] = Field(default_factory=list)


class ResourceAdapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    capabilities: list[str] = Field(default_factory=list)
    readiness: Literal["ready", "not_ready", "unknown"]
    route_passable: bool | None = None
    readiness_expires_at: datetime | None = None
    active_task: bool = False


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: PolicySnapshot
    projections: list[ProjectionAdapter] = Field(default_factory=list, max_length=20)
    cascades: list[CascadeAdapter] = Field(default_factory=list, max_length=20)
    resources: list[ResourceAdapter] = Field(default_factory=list, max_length=20)
    now: datetime
    horizon_hours: float = Field(default=48.0, gt=0, le=MAX_HORIZON_HOURS)


class CandidateAction(BaseModel):
    action: str
    evidence_references: list[str]
    reasons: list[str]
    resource_cost: dict[str, float | str]
    expected_benefit: list[str]
    time_sensitivity_hours: float | None
    confidence: str
    expires_at: datetime
    policy_version: str
    input_hash: str
    excluded_resources: dict[str, str]
    expected_operational_effect: str
    feasible: bool
    rank: int
    status: Literal["pending_approval"] = "pending_approval"


class PolicyResult(BaseModel):
    policy_version: str
    input_hash: str
    candidates: list[CandidateAction]
    fallback_used: bool


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _candidate(request: PolicyRequest, action: str, capability: str, evidence: list[str], reasons: list[str], cost: dict[str, float | str], benefit: list[str], effect: str, sensitivity: float | None) -> CandidateAction:
    excluded: dict[str, str] = {}
    for resource in sorted(request.resources, key=lambda item: item.id):
        if resource.readiness != "ready":
            excluded[resource.id] = "resource is not ready"
        elif resource.active_task:
            excluded[resource.id] = "resource already has an active task"
        elif resource.readiness_expires_at and resource.readiness_expires_at <= request.now.astimezone(UTC):
            excluded[resource.id] = "readiness expired"
        elif capability not in resource.capabilities:
            excluded[resource.id] = f"missing capability {capability}"
        elif resource.route_passable is not True:
            excluded[resource.id] = "route is not confirmed passable"
    stale = request.snapshot.freshness_state != "fresh" or (request.snapshot.expires_at and request.snapshot.expires_at <= request.now.astimezone(UTC))
    feasible = bool(request.resources) and len(excluded) < len(request.resources) and not stale
    confidence = "low" if stale else ("medium" if feasible else "low")
    unknown = [p.resource for p in request.projections if p.confidence in {"unknown", "low"}]
    if unknown:
        reasons.append("projection uncertainty: " + ", ".join(sorted(unknown)))
        confidence = "low"
    expires = min([x for x in [request.snapshot.expires_at, request.now.astimezone(UTC) + timedelta(hours=request.horizon_hours)] if x is not None])
    payload = {"action": action, "evidence": sorted(evidence), "cost": cost, "snapshot": request.snapshot.model_dump(mode="json"), "horizon": request.horizon_hours}
    return CandidateAction(action=action, evidence_references=sorted(set(evidence)), reasons=sorted(set(reasons)), resource_cost=cost, expected_benefit=benefit, time_sensitivity_hours=sensitivity, confidence=confidence, expires_at=expires, policy_version=POLICY_VERSION, input_hash=_hash(payload), excluded_resources=excluded, expected_operational_effect=effect, feasible=feasible, rank=0)


def evaluate_policy(request: PolicyRequest) -> PolicyResult:
    """Generate three bounded candidates and rank feasible actions deterministically."""
    refs = [f"projection:{p.resource}" for p in request.projections]
    refs += [ref for c in request.cascades for ref in c.supporting_input_refs]
    water = next((p for p in request.projections if p.resource == "potable_water"), None)
    battery = next((p for p in request.projections if p.resource == "battery"), None)
    medicine = next((p for p in request.projections if p.resource == "medicine"), None)
    candidates = [
        _candidate(request, "deliver_or_treat_water", "water_delivery", refs + ["cascade:water"], ["safe-water continuity is time-sensitive"], {"water_team": 1, "power_kw": 4}, ["extend potable-water runway", "reduce operational water pressure"], "adds or treats potable water; consumes transport/purification capacity", water.time_to_critical_hours if water else None),
        _candidate(request, "shift_non_critical_power", "power_management", refs + ["cascade:power"], ["protect coupled purification and cold-chain capability"], {"operator": 1, "shift_kw": 2}, ["extend battery runway", "preserve critical loads"], "reduces non-critical load without dispatching a resource", battery.time_to_critical_hours if battery else None),
        _candidate(request, "request_medicine_cold_chain_support", "medical_support", refs + ["cascade:medicine"], ["protect medicine and cold-chain continuity"], {"medical_support": 1}, ["extend medicine/cold-chain reserve"], "requests external support; no clinical outcome is inferred", medicine.time_to_critical_hours if medicine else None),
    ]
    candidates.sort(key=lambda item: (not item.feasible, item.time_sensitivity_hours is None, item.time_sensitivity_hours or 999999, item.action))
    for index, candidate in enumerate(candidates, 1):
        candidate.rank = index
    input_hash = _hash({"snapshot": request.snapshot.model_dump(mode="json"), "projections": [p.model_dump(mode="json") for p in request.projections], "cascades": [c.model_dump(mode="json") for c in request.cascades], "resources": [r.model_dump(mode="json") for r in sorted(request.resources, key=lambda item: item.id)], "horizon": request.horizon_hours})
    for candidate in candidates:
        candidate.input_hash = input_hash
    return PolicyResult(policy_version=POLICY_VERSION, input_hash=input_hash, candidates=candidates[:MAX_CANDIDATES], fallback_used=not any(c.feasible for c in candidates))
