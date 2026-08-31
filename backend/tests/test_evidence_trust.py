from fastapi.testclient import TestClient

from app.core.config import Settings
from app.evidence import InMemoryEvidenceStore
from app.main import create_app


def _client() -> TestClient:
    store = InMemoryEvidenceStore()
    app = create_app(
        Settings(app_environment="test", database_url="postgresql://unused", dev_identity_enabled=True),
        evidence_store=store,
    )
    return TestClient(app, raise_server_exceptions=False)


def _report(client: TestClient, *, client_record_id: str, observed_at: str, place: str = "North Sector") -> dict:
    response = client.post(
        "/api/v1/reports",
        headers={"X-Dev-Identity": "operator", "Idempotency-Key": client_record_id},
        json={
            "contract_version": 1,
            "client_record_id": client_record_id,
            "observed_at": observed_at,
            "received_at": observed_at,
            "source": {"channel": "operator_report_desk", "source_class": "authenticated_operator"},
            "location": {"geometry": {"type": "Point", "coordinates": [91.742, 26.184]}, "place_text": place},
            "report_type": "water_contamination",
            "facts": {"people_affected": 20},
            "privacy_class": "restricted_operational",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_contradictory_evidence_keeps_duplicate_reference_and_raw_report_immutable() -> None:
    client = _client()
    observed = "2026-09-04T08:00:00+00:00"
    first = _report(client, client_record_id="rpt-first", observed_at=observed)
    second = _report(client, client_record_id="rpt-second", observed_at=observed)

    detail = client.get(f"/api/v1/reports/{second['report_id']}", headers={"X-Dev-Identity": "operator"})
    assert detail.status_code == 200
    assert detail.json()["duplicate_candidates"]
    assert detail.json()["original_payload"]["client_record_id"] == "rpt-second"
    assert detail.json()["original_sha256"]
    assert detail.json()["duplicate_candidates"][0]["candidate_report_id"] == first["report_id"]


def test_stale_evidence_preserves_observed_and_received_times_and_verification_state() -> None:
    client = _client()
    old = "2026-08-20T08:00:00+00:00"
    created = _report(client, client_record_id="rpt-stale", observed_at=old)
    before = client.get(f"/api/v1/reports/{created['report_id']}", headers={"X-Dev-Identity": "operator"}).json()
    claim_id = before["claims"][0]["id"]

    reviewed = client.post(
        f"/api/v1/reports/{created['report_id']}/review",
        headers={"X-Dev-Identity": "operator"},
        json={"claim_updates": {claim_id: "stale"}, "note": "Evidence age requires recheck"},
    )
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["observed_at"] == old
    assert body["received_at"] == old
    assert body["claims"][0]["verification_state"] == "stale"
    assert body["original_payload"]["client_record_id"] == "rpt-stale"
