from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.persistence import database_ready


@pytest.mark.skipif(
    not database_ready(Settings().database_url),
    reason="local PostgreSQL/PostGIS integration profile is not running",
)
def test_postgresql_evidence_review_link_and_bounded_map() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    client = TestClient(app)
    operator = {"X-Dev-Identity": "operator"}
    suffix = uuid4().hex
    assert client.post("/api/v1/demo/seed", headers=operator).status_code == 200
    report = {
        "contract_version": 1,
        "client_record_id": f"pg-review-{suffix}",
        "observed_at": "2026-08-30T10:10:00+00:00",
        "received_at": "2026-08-30T10:11:00+00:00",
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
    created = client.post(
        "/api/v1/reports",
        headers={**operator, "Idempotency-Key": report["client_record_id"]},
        json=report,
    )
    assert created.status_code == 201
    report_id = created.json()["report_id"]
    detail = client.get(f"/api/v1/reports/{report_id}", headers=operator).json()
    claim_id = detail["claims"][0]["id"]
    reviewed = client.post(
        f"/api/v1/reports/{report_id}/review",
        headers=operator,
        json={"claim_updates": {claim_id: "corroborated"}, "note": "Synthetic review"},
    )
    assert reviewed.status_code == 200
    linked = client.post(
        f"/api/v1/reports/{report_id}/incident-links",
        headers=operator,
        json={"incident_id": "inc_demo_north"},
    )
    assert linked.status_code == 200
    bounded = client.get(
        "/api/v1/map/features?bbox=91.73,26.18,91.75,26.19&limit=100", headers=operator
    )
    assert bounded.status_code == 200
    assert "inc_demo_north" in {feature["id"] for feature in bounded.json()["features"]}
