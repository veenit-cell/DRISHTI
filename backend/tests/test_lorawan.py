import pytest
import json
from datetime import UTC, datetime

from app.lorawan import parse_chirpstack_uplink, DeviceRegistry, ChirpStackTelemetryAdapter
from app.telemetry import TelemetryOperationalLink
from app.core.context import RequestContext


def test_parse_chirpstack_uplink_with_object():
    """Test decoding a payload where ChirpStack already parsed the object."""
    payload = {
        "deviceInfo": {"devEui": "0000000000000001"},
        "object": {
            "turbidity": 12.5,
            "bat": 85.0
        },
        "rxInfo": [{"snr": 5.0}]
    }
    links = [TelemetryOperationalLink(link_type="runway", entity_id="test", label="Test")]
    measurements = parse_chirpstack_uplink(payload, "generic", links)
    
    assert len(measurements) == 2
    
    turbidity = next(m for m in measurements if m.name == "turbidity")
    assert turbidity.value == 12.5
    assert turbidity.unit == "NTU"
    assert turbidity.status == "critical" # > 10
    
    bat = next(m for m in measurements if m.name == "bat")
    assert bat.value == 85.0
    assert bat.unit == "%"
    assert bat.status == "normal"


def test_parse_chirpstack_uplink_raw_fallback():
    """Test fallback when no object is present but base64 data is."""
    payload = {
        "deviceInfo": {"devEui": "0000000000000002"},
        "data": "SGVsbG8=" # Base64 for 'Hello'
    }
    measurements = parse_chirpstack_uplink(payload, "generic", [])
    
    assert len(measurements) == 1
    assert measurements[0].name == "raw_payload_bytes"
    assert measurements[0].value == 5
    assert measurements[0].unit == "bytes"


def test_chirpstack_adapter_initialization(tmp_path):
    """Test adapter loads registry correctly."""
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps({
        "devices": [
            {
                "dev_eui": "1111222233334444",
                "device_id": "sensor-1",
                "sensor_type": "water",
                "shelter": "Camp 1"
            }
        ],
        "gateways": [
            {
                "gateway_id": "gw-1",
                "chirpstack_gateway_id": "9999888877776666",
                "shelter": "Camp 1"
            }
        ]
    }))
    
    adapter = ChirpStackTelemetryAdapter(device_registry_path=str(registry_file))
    
    context = RequestContext(
        actor_id="test",
        role="operator",
        tenant_id="test-tenant",
        workspace_id="test-workspace",
        scopes=frozenset(),
        correlation_id="test-corr-id"
    )
    
    devices = adapter.list_devices(context)
    assert len(devices) == 1
    assert devices[0].device_id == "sensor-1"
    assert devices[0].sensor_type == "water"
    assert devices[0].last_seen is None
    
    gateways = adapter.list_gateways(context)
    assert len(gateways) == 1
    assert gateways[0].gateway_id == "gw-1"
    assert gateways[0].status == "offline"


def test_chirpstack_adapter_ingests_uplink(tmp_path):
    """Test adapter processes uplink and updates state."""
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps({
        "devices": [
            {
                "dev_eui": "aabbccddeeff0011",
                "device_id": "sensor-1"
            }
        ]
    }))
    
    adapter = ChirpStackTelemetryAdapter(device_registry_path=str(registry_file))
    
    payload = {
        "deviceInfo": {"devEui": "aabbccddeeff0011"},
        "object": {"temperature": 25.4},
        "rxInfo": [{"snr": 10.0}] # +20 * 2.5 = 75 signal quality
    }
    
    adapter.ingest_event("up", payload)
    
    context = RequestContext("test", "operator", "t", "w", frozenset(), "corr")
    devices = adapter.list_devices(context)
    
    assert len(devices) == 1
    assert devices[0].last_seen is not None
    assert devices[0].signal_quality == 75
    assert len(devices[0].latest_measurements) == 1
    assert devices[0].latest_measurements[0].name == "temperature"
    assert devices[0].latest_measurements[0].value == 25.4


def test_chirpstack_adapter_ignores_unregistered_devices():
    """Test adapter drops uplinks from unknown EUIs."""
    adapter = ChirpStackTelemetryAdapter(device_registry_path=None)
    
    payload = {
        "deviceInfo": {"devEui": "unknown"},
        "object": {"data": 1}
    }
    
    adapter.ingest_event("up", payload)
    
    context = RequestContext("test", "operator", "t", "w", frozenset(), "corr")
    devices = adapter.list_devices(context)
    
    assert len(devices) == 0


def test_chirpstack_adapter_status_update(tmp_path):
    """Test adapter processes status update for battery."""
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps({
        "devices": [
            {
                "dev_eui": "aabbccddeeff0011",
                "device_id": "sensor-1"
            }
        ]
    }))
    
    adapter = ChirpStackTelemetryAdapter(device_registry_path=str(registry_file))
    
    payload = {
        "deviceInfo": {"devEui": "aabbccddeeff0011"},
        "batteryLevel": 99.5
    }
    
    adapter.ingest_event("status", payload)
    
    context = RequestContext("test", "operator", "t", "w", frozenset(), "corr")
    devices = adapter.list_devices(context)
    
    assert len(devices) == 1
    assert devices[0].battery == 99.5
    assert devices[0].last_seen is not None
