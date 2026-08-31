import httpx
import uuid
from datetime import datetime

base = "http://localhost:8000/api/v1"
headers = {"x-tenant-id": "t1", "x-workspace-id": "w1", "X-Dev-Identity": "operator"}

def run():
    # 1. Activate incident
    inc_req = {
        "name": "Phase 2 Test Incident",
        "hazard_type": "flood",
        "severity": "critical",
        "summary": "Testing verification",
        "event_time": datetime.utcnow().isoformat() + "Z"
    }
    r = httpx.post(f"{base}/command/incidents", json=inc_req, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code in (200, 201), r.text
    inc_id = r.json()["incident_id"]

    r = httpx.patch(f"{base}/command/incidents/{inc_id}", json={"status": "active", "phase": "activation", "note": "activate"}, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code in (200, 201), r.text

    # 2. Receive report
    obs_at = datetime.utcnow().isoformat() + "Z"
    rpt_req = {
        "contract_version": 1,
        "client_record_id": str(uuid.uuid4()),
        "observed_at": obs_at,
        "received_at": obs_at,
        "source": {"channel": "test", "source_class": "test"},
        "location": {"geometry": {"type": "Point", "coordinates": [91.7, 26.2]}, "uncertainty_m": 100, "place_text": "Test Village"},
        "report_type": "life_safety",
        "facts": {"people_affected": 5, "access_state": "unknown"},
        "privacy_class": "restricted_operational"
    }
    r = httpx.post(f"{base}/reports", json=rpt_req, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code in (200, 201), r.text
    rep_id = r.json()["report_id"]

    # Link to incident
    r = httpx.post(f"{base}/reports/{rep_id}/command-incident-links", json={"incident_id": inc_id}, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code in (200, 201), r.text

    # 3. Assign verification
    r = httpx.post(f"{base}/verification-queue", json={
        "title": "Verify Test Village",
        "priority": "high",
        "destination": "Test Village",
        "notes": "Verify",
        "owner_actor_id": "operator",
        "source_report_id": rep_id,
        "source_incident_id": inc_id
    }, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code in (200, 201), r.text

    # 4. Corroborate claim (review)
    r = httpx.post(f"{base}/reports/{rep_id}/review", json={
        "claim_updates": {}, # API signature requires dict
        "note": "Corroborated by operator"
    }, headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code in (200, 201), r.text

    # 5. Check map state
    r = httpx.get(f"{base}/map/features", headers=headers)
    assert r.status_code in (200, 201), r.text
    features = r.json()["features"]
    assert len(features) > 0, "No map features found"

    print("ALL CLEAR: Phase 2 exit gate passed programmatically!")

if __name__ == "__main__":
    run()
