import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore
from app.telemetry import (
    InMemoryTelemetryAdapter,
    TelemetryDeviceRecord,
    TelemetryGatewayRecord,
    TelemetryMeasurement,
    TelemetryOperationalLink,
    TelemetrySourceProvenance,
)


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
HEADERS = {"X-Dev-Identity": "operator"}


def _client(adapter: InMemoryTelemetryAdapter) -> TestClient:
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
        telemetry_adapter=adapter,
        clock=FixedClock(NOW),
    )
    return TestClient(app, raise_server_exceptions=False)


def _source(synthetic: bool = False) -> TelemetrySourceProvenance:
    return TelemetrySourceProvenance(
        source="lorawan_gateway",
        source_class="synthetic_telemetry" if synthetic else "approved_lorawan_feed",
        synthetic=synthetic,
    )


def test_summary_is_bounded_scoped_and_hides_device_keys() -> None:
    adapter = InMemoryTelemetryAdapter()
    link = TelemetryOperationalLink(
        link_type="runway", entity_id="potable_water", label="Potable-water runway"
    )
    adapter.set_workspace_data(
        "org_demo",
        "evt_demo",
        [
            TelemetryDeviceRecord(
                device_id="device-fresh",
                sensor_type="water_quality",
                shelter="North Shelter",
                last_seen=NOW,
                battery=88,
                signal_quality=92,
                latest_measurements=[
                    TelemetryMeasurement(
                        name="turbidity", value=11.2, unit="NTU", observed_at=NOW, status="critical", links=[link]
                    )
                ],
                source_provenance=_source(),
            ),
            TelemetryDeviceRecord(
                device_id="device-stale",
                sensor_type="battery_health",
                shelter="North Shelter",
                last_seen=NOW - timedelta(minutes=30),
                battery=41,
                signal_quality=45,
                source_provenance=_source(),
            ),
            TelemetryDeviceRecord(
                device_id="device-silent",
                sensor_type="shelter_environment",
                shelter="East Shelter",
                last_seen=None,
                source_provenance=_source(),
            ),
        ],
        [
            TelemetryGatewayRecord(
                gateway_id="gateway-north",
                shelter="North Shelter",
                last_seen=NOW,
                status="healthy",
                connected_devices=2,
                source_provenance=_source(),
            )
        ],
    )

    response = _client(adapter).get("/api/v1/telemetry/summary", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "live"
    assert body["counts"] == {
        "fresh_sensors": 1,
        "stale_sensors": 1,
        "silent_sensors": 1,
        "critical_readings": 1,
        "gateway_count": 1,
    }
    assert [item["freshness"] for item in body["devices"]] == ["fresh", "stale", "silent"]
    assert body["devices"][0]["latest_measurements"][0]["links"][0]["link_type"] == "runway"
    assert "device_key" not in json.dumps(body)
    assert "No telemetry does not mean safe conditions" in body["warning"]


def test_summary_does_not_leak_data_from_another_tenant_or_workspace() -> None:
    adapter = InMemoryTelemetryAdapter()
    adapter.set_workspace_data(
        "org_other",
        "evt_other",
        [
            TelemetryDeviceRecord(
                device_id="other-device",
                sensor_type="water_quality",
                shelter="Other Shelter",
                last_seen=NOW,
                source_provenance=_source(),
            )
        ],
        [],
    )

    response = _client(adapter).get("/api/v1/telemetry/summary", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["devices"] == []
    assert response.json()["gateways"] == []
    assert response.json()["freshness"] == "unknown"


def test_empty_live_workspace_is_not_mislabeled_as_synthetic() -> None:
    adapter = InMemoryTelemetryAdapter()
    client = _client(adapter)
    client.post("/api/v1/workspace/mode?mode=live", headers=HEADERS)

    response = client.get("/api/v1/telemetry/summary", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["mode"] == "live"
    assert response.json()["freshness"] == "unknown"


def test_synthetic_telemetry_keeps_provenance_visible() -> None:
    adapter = InMemoryTelemetryAdapter(seed_synthetic=True)

    response = _client(adapter).get("/api/v1/telemetry/summary", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "synthetic"
    assert body["devices"]
    assert all(item["source_provenance"]["synthetic"] is True for item in body["devices"])
    assert body["warning"] == "No telemetry does not mean safe conditions."
