import hashlib
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.evidence import InMemoryEvidenceStore
from app.main import create_app

FIXED_NOW = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)
HEADERS = {"X-Dev-Identity": "operator"}


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        evidence_store=InMemoryEvidenceStore(),
        clock=FixedClock(FIXED_NOW),
    )
    return TestClient(app, raise_server_exceptions=False)


def valid_report(client_record_id: str = "rpt_test_001") -> dict:
    return {
        "contract_version": 1,
        "client_record_id": client_record_id,
        "observed_at": "2026-08-30T10:10:00+05:30",
        "received_at": "2026-08-30T10:11:00+05:30",
        "source": {"channel": "field_form", "source_class": "authenticated_responder"},
        "location": {
            "geometry": {"type": "Point", "coordinates": [91.742, 26.184]},
            "uncertainty_m": 120,
            "place_text": "Synthetic North Sector",
        },
        "report_type": "water_contamination",
        "facts": {"people_affected": None, "access_state": "unknown"},
        "privacy_class": "restricted_operational",
    }


def create(client: TestClient, payload: dict | None = None):
    body = payload or valid_report()
    return client.post(
        "/api/v1/reports",
        headers={**HEADERS, "Idempotency-Key": body["client_record_id"]},
        json=body,
    )


def test_report_create_retry_conflict_and_immutable_detail(client: TestClient) -> None:
    payload = valid_report()
    created = create(client, payload)
    assert created.status_code == 201
    assert created.json()["deduplicated_replay"] is False
    assert "FACT:PEOPLE_AFFECTED_UNKNOWN" in created.json()["warnings"]
    report_id = created.json()["report_id"]

    retried = create(client, payload)
    assert retried.status_code == 201
    assert retried.json()["report_id"] == report_id
    assert retried.json()["deduplicated_replay"] is True

    changed = valid_report()
    changed["facts"] = {"people_affected": 17, "access_state": "blocked"}
    conflict = create(client, changed)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

    detail = client.get(f"/api/v1/reports/{report_id}", headers=HEADERS)
    assert detail.status_code == 200
    body = detail.json()
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert body["original_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert body["original_payload"] == payload
    assert body["normalization"]["mapping_version"] == "phase-2-demo-mapping-v1"
    assert any(
        claim["claim_type"] == "fact:people_affected" and claim["value"] is None
        for claim in body["claims"]
    )


def test_incomplete_report_preserves_unknown_and_lists_with_cursor(client: TestClient) -> None:
    assert create(client, valid_report("rpt_test_001")).status_code == 201
    payload = valid_report("rpt_test_002")
    payload.update({"observed_at": None, "received_at": None, "location": None})
    created = create(client, payload)
    assert created.status_code == 201
    assert "LOCATION_UNKNOWN" in created.json()["warnings"]
    assert "OBSERVED_TIME_UNKNOWN" in created.json()["warnings"]
    detail = client.get(f"/api/v1/reports/{created.json()['report_id']}", headers=HEADERS)
    assert detail.status_code == 200
    assert detail.json()["original_payload"]["location"] is None

    listed = client.get("/api/v1/reports?limit=1", headers=HEADERS)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert listed.json()["next_cursor"] is not None
    next_page = client.get(
        f"/api/v1/reports?cursor={listed.json()['next_cursor']}",
        headers=HEADERS,
    )
    assert next_page.status_code == 200
    assert len(next_page.json()["items"]) == 1

    invalid_cursor = client.get("/api/v1/reports?cursor=not-valid", headers=HEADERS)
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["code"] == "INVALID_CURSOR"


def test_validation_permissions_and_not_found(client: TestClient) -> None:
    malformed = valid_report("rpt_test_bad")
    malformed["location"]["geometry"] = {"type": "Point", "coordinates": [200, 0]}
    response = create(client, malformed)
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_FAILED"

    viewer = client.get("/api/v1/reports", headers={"X-Dev-Identity": "viewer"})
    assert viewer.status_code == 200
    denied = client.post(
        "/api/v1/reports",
        headers={"X-Dev-Identity": "viewer", "Idempotency-Key": "rpt_viewer_001"},
        json=valid_report("rpt_viewer_001"),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "SCOPE_DENIED"

    missing = client.get("/api/v1/reports/rpt_missing", headers=HEADERS)
    assert missing.status_code == 404
    assert missing.json()["code"] == "REPORT_NOT_FOUND"


def test_seed_and_bounded_map_features(client: TestClient) -> None:
    seeded = client.post("/api/v1/demo/seed", headers=HEADERS)
    assert seeded.status_code == 200
    assert seeded.json() == {"synthetic": True, "created": 3, "workspace_id": "evt_demo"}
    assert client.post("/api/v1/demo/seed", headers=HEADERS).json()["created"] == 0

    full = client.get("/api/v1/map/features?limit=2", headers=HEADERS)
    assert full.status_code == 200
    assert full.json()["type"] == "FeatureCollection"
    assert len(full.json()["features"]) == 2
    assert all(feature["geometry"]["type"] == "Point" for feature in full.json()["features"])

    bounded = client.get("/api/v1/map/features?bbox=91.73,26.18,91.75,26.19", headers=HEADERS)
    assert bounded.status_code == 200
    assert len(bounded.json()["features"]) == 1
    assert bounded.json()["features"][0]["id"] == "inc_demo_north"

    invalid_bbox = client.get("/api/v1/map/features?bbox=91,26,90,27", headers=HEADERS)
    assert invalid_bbox.status_code == 422
    assert invalid_bbox.json()["code"] == "INVALID_BBOX"
