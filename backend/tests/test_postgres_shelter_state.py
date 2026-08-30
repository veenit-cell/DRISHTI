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
def test_postgresql_shelter_state_survives_new_app_instance() -> None:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        clock=FixedClock(datetime(2026, 8, 30, 10, 30, tzinfo=UTC)),
    )
    first = TestClient(app)
    shelter_id = f"shelter_pg_{uuid4().hex}"
    headers = {"X-Dev-Identity": "operator"}
    assert first.post(
        "/api/v1/shelters",
        headers=headers,
        json={"shelter_id": shelter_id, "name": "PostgreSQL Shelter"},
    ).status_code == 201
    created = first.post(
        f"/api/v1/shelters/{shelter_id}/observations",
        headers={**headers, "Idempotency-Key": f"obs-{shelter_id}"},
        json={
            "observed_at": "2026-08-30T10:30:00Z",
            "source": "synthetic_test",
            "values": {"population": 42},
            "units": {"population": "people"},
        },
    )
    assert created.status_code == 201
    expected_hash = created.json()["state"]["snapshot_hash"]
    second = TestClient(create_app(Settings(app_environment="test", dev_identity_enabled=True)))
    persisted = second.get(f"/api/v1/shelters/{shelter_id}/state", headers=headers)
    assert persisted.status_code == 200
    assert persisted.json()["snapshot_hash"] == expected_hash
