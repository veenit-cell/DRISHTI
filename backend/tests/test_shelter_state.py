from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.context import RequestContext
from app.main import create_app
from app.operations import InMemoryOperationsStore
from app.shelter_state import (
    InMemoryShelterStateStore,
    ShelterCreate,
    ShelterNotFoundError,
)

NOW = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)
HEADERS = {"X-Dev-Identity": "operator"}


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        shelter_state_store=InMemoryShelterStateStore(),
        clock=FixedClock(NOW),
    )
    return TestClient(app)


def test_synthetic_seed_and_reproducible_snapshot(client: TestClient) -> None:
    seeded = client.post("/api/v1/shelter-state/demo/seed", headers=HEADERS)
    assert seeded.status_code == 200
    first = client.get("/api/v1/shelters/shelter_demo_north/state", headers=HEADERS).json()
    second = client.get("/api/v1/shelters/shelter_demo_north/state", headers=HEADERS).json()
    assert first == second
    assert first["shelter"]["synthetic"] is True
    assert first["values"]["population"] == 1800
    assert first["values"]["potable_water_liters"] == 4200


def test_unknown_and_stale_values_are_explicit(client: TestClient) -> None:
    created = client.post(
        "/api/v1/shelters",
        headers=HEADERS,
        json={"shelter_id": "shelter_state_test", "name": "State Test Shelter"},
    )
    assert created.status_code == 201
    unknown = client.post(
        "/api/v1/shelters/shelter_state_test/observations",
        headers={**HEADERS, "Idempotency-Key": "unknown-001"},
        json={
            "observed_at": NOW.isoformat(),
            "source": "field_form",
            "provenance": {"operator": "synthetic"},
            "values": {"battery_percent": None},
        },
    )
    assert unknown.status_code == 201
    state = unknown.json()["state"]
    assert state["values"]["battery_percent"] is None
    assert state["field_freshness"]["battery_percent"] == "unknown"

    stale = client.post(
        "/api/v1/shelters/shelter_state_test/observations",
        headers={**HEADERS, "Idempotency-Key": "stale-001"},
        json={
            "observed_at": NOW.isoformat(),
            "source": "synthetic_sensor",
            "freshness_state": "stale",
            "values": {"population": 120},
            "units": {"population": "people"},
        },
    )
    assert stale.status_code == 201
    assert stale.json()["state"]["freshness_state"] == "stale"


def test_invalid_units_and_idempotency_conflict_are_rejected(client: TestClient) -> None:
    client.post(
        "/api/v1/shelters",
        headers=HEADERS,
        json={"shelter_id": "shelter_validation", "name": "Validation Shelter"},
    )
    payload = {
        "observed_at": NOW.isoformat(),
        "source": "field_form",
        "values": {"battery_percent": 50},
        "units": {"battery_percent": "liters"},
    }
    invalid = client.post(
        "/api/v1/shelters/shelter_validation/observations",
        headers={**HEADERS, "Idempotency-Key": "invalid-unit"},
        json=payload,
    )
    assert invalid.status_code == 422
    valid = {**payload, "units": {"battery_percent": "percent"}}
    first = client.post(
        "/api/v1/shelters/shelter_validation/observations",
        headers={**HEADERS, "Idempotency-Key": "same-key"},
        json=valid,
    )
    assert first.status_code == 201
    replay = client.post(
        "/api/v1/shelters/shelter_validation/observations",
        headers={**HEADERS, "Idempotency-Key": "same-key"},
        json=valid,
    )
    assert replay.status_code == 201 and replay.json()["replayed"] is True
    conflict = client.post(
        "/api/v1/shelters/shelter_validation/observations",
        headers={**HEADERS, "Idempotency-Key": "same-key"},
        json={**valid, "values": {"battery_percent": 49}},
    )
    assert conflict.status_code == 409


def test_in_memory_scope_isolation() -> None:
    store = InMemoryShelterStateStore()
    context_a = RequestContext("actor-a", "operator", "org-a", "event-a", frozenset(), "corr-a")
    context_b = RequestContext("actor-b", "operator", "org-b", "event-b", frozenset(), "corr-b")
    store.create_shelter(context_a, ShelterCreate(shelter_id="shelter-a", name="A"), NOW)
    with pytest.raises(ShelterNotFoundError):
        store.get_state(context_b, "shelter-a")
