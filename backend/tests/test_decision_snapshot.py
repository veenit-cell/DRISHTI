# ruff: noqa: E501

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.decision_snapshot import (
    IncidentRecord,
    ReportRecord,
    SnapshotRequest,
    SourceRecord,
    build_decision_snapshot,
)
from app.main import create_app
from app.operations import InMemoryOperationsStore

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def request(**kwargs):
    report = ReportRecord(id="r1", tenant_id="t1", workspace_id="w1", revision=2, recorded_at=NOW - timedelta(hours=1), event_time=NOW - timedelta(hours=2), status="reviewed", claims=[{"id": "c1", "claim_type": "water", "verification_state": "corroborated"}], linked_incident_ids=["i1"], data={"source": "synthetic_demo_seed"})
    incident = IncidentRecord(id="i1", tenant_id="t1", workspace_id="w1", revision=1, recorded_at=NOW - timedelta(hours=1), event_time=NOW - timedelta(hours=2), verification_state="suspected", data={"source": "synthetic_demo_seed"})
    return SnapshotRequest(tenant_id="t1", workspace_id="w1", replay_at=NOW, policy_version="intervention_policy_v1", reports=[report], incidents=[incident], sector_assessments=[SourceRecord(id="s1", tenant_id="t1", workspace_id="w1", revision=3, recorded_at=NOW - timedelta(hours=1), event_time=NOW - timedelta(hours=1), freshness="fresh", data={"assessment_state": "assessed"})], operational_observations=[], **kwargs)


def test_exact_sources_hash_and_revision_replay():
    first = build_decision_snapshot(request())
    second = build_decision_snapshot(request())
    assert first.model_dump() == second.model_dump()
    assert [s.source_id for s in first.sources] == ["i1", "r1", "s1"]
    changed = request()
    changed.reports[0].revision = 3
    assert build_decision_snapshot(changed).canonical_hash != first.canonical_hash


def test_contradictions_unknowns_and_verification_candidates_visible():
    source = request()
    source.reports[0].claims = [{"id": "c1", "verification_state": "contradicted"}, {"id": "c2", "verification_state": "unknown"}]
    source.reports[0].linked_incident_ids = ["missing"]
    result = build_decision_snapshot(source)
    report = next(item for item in result.sources if item.kind == "report")
    assert report.visible_claims and not report.accepted_claims
    assert result.unknown_fields and result.verification_candidates


def test_scope_and_future_evidence_rejected_or_excluded():
    out = request()
    out.reports[0].tenant_id = "other"
    with pytest.raises(ValueError, match="out-of-scope"):
        build_decision_snapshot(out)
    future = request()
    future.reports[0].recorded_at = NOW + timedelta(minutes=1)
    assert not any(item.source_id == "r1" for item in build_decision_snapshot(future).sources)


def test_api_scope_rejection():
    app = create_app(Settings(app_environment="test", dev_identity_enabled=True), operations_store=InMemoryOperationsStore())
    body = request().model_dump(mode="json")
    body["tenant_id"] = "other"
    assert TestClient(app).post("/api/v1/decision-snapshot/build", headers={"X-Dev-Identity": "viewer"}, json=body).status_code == 403
