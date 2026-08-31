"""LoRaWAN integration via ChirpStack.

Provides TelemetryAdapter implementation for real sensor feeds.
"""
import asyncio
import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any

import paho.mqtt.client as mqtt

from app.core.context import RequestContext
from app.telemetry import (
    TelemetryDeviceRecord,
    TelemetryGatewayRecord,
    TelemetryMeasurement,
    TelemetrySourceProvenance,
    TelemetryOperationalLink,
)
from app.updates import UpdateFeed, publish_communication_gap_event


logger = logging.getLogger(__name__)


def parse_chirpstack_uplink(payload: dict[str, Any], dev_profile: str, links: list[TelemetryOperationalLink]) -> list[TelemetryMeasurement]:
    """Parse a ChirpStack v4 uplink event JSON payload into TelemetryMeasurements.
    
    In a full production implementation, this would use a registry of codecs 
    (e.g., standard LoRa Alliance payload codecs). For this demo, we provide
    basic extraction for a few common formats or generic payloads.
    """
    now = datetime.now(UTC)
    measurements: list[TelemetryMeasurement] = []
    
    # Try to decode based on profile, or generic object if decoded in ChirpStack
    if "object" in payload and payload["object"]:
        obj = payload["object"]
        for key, value in obj.items():
            if isinstance(value, (int, float, bool, str)):
                # basic heuristics for units
                unit = ""
                status = "unknown"
                if "turbidity" in key.lower():
                    unit = "NTU"
                    status = "critical" if float(value) > 10 else "normal"
                elif "bat" in key.lower() or "power" in key.lower():
                    unit = "%" if float(value) <= 100 else "V"
                    status = "normal" if float(value) > 20 else "critical"
                    
                measurements.append(TelemetryMeasurement(
                    name=key,
                    value=value,
                    unit=unit,
                    observed_at=now,
                    status=status,
                    links=links
                ))
    else:
        # Fallback raw data size if not decoded
        data = payload.get("data", "")
        if data:
            measurements.append(TelemetryMeasurement(
                name="raw_payload_bytes",
                value=len(base64.b64decode(data)),
                unit="bytes",
                observed_at=now,
                status="unknown",
                links=links
            ))
            
    return measurements


class DeviceRegistry:
    """Registry mapping ChirpStack EUIs to DRISHTI operational entities."""
    
    def __init__(self, path: str | None = None):
        self._devices: dict[str, dict[str, Any]] = {}
        self._gateways: dict[str, dict[str, Any]] = {}
        
        if path:
            self.load(path)
            
    def load(self, path: str) -> None:
        try:
            with open(path, "r") as f:
                data = json.load(f)
                for dev in data.get("devices", []):
                    self._devices[dev["dev_eui"].lower()] = dev
                for gw in data.get("gateways", []):
                    self._gateways[gw.get("chirpstack_gateway_id", "").lower()] = gw
        except FileNotFoundError:
            logger.warning(f"Device registry file {path} not found.")
        except json.JSONDecodeError:
            logger.error(f"Device registry file {path} is invalid JSON.")

    def lookup_device(self, dev_eui: str) -> dict[str, Any] | None:
        return self._devices.get(dev_eui.lower())
        
    def lookup_gateway(self, gateway_id: str) -> dict[str, Any] | None:
        return self._gateways.get(gateway_id.lower())
        
    def get_all_devices(self) -> list[dict[str, Any]]:
        return list(self._devices.values())
        
    def get_all_gateways(self) -> list[dict[str, Any]]:
        return list(self._gateways.values())


class ChirpStackTelemetryAdapter:
    """Live LoRaWAN telemetry adapter implementing the TelemetryAdapter protocol."""

    def __init__(self, device_registry_path: str | None = None) -> None:
        self._registry = DeviceRegistry(device_registry_path)
        self._device_state: dict[str, TelemetryDeviceRecord] = {}
        self._gateway_state: dict[str, TelemetryGatewayRecord] = {}
        self._mqtt_connected = False
        
        self._source = TelemetrySourceProvenance(
            source="chirpstack_lorawan", 
            source_class="approved_lorawan_feed", 
            synthetic=False
        )
        
        self._initialize_state()

    def _initialize_state(self) -> None:
        """Initialize state from registry with unknown freshness."""
        for dev in self._registry.get_all_devices():
            self._device_state[dev["dev_eui"].lower()] = TelemetryDeviceRecord(
                device_id=dev.get("device_id", dev["dev_eui"]),
                sensor_type=dev.get("sensor_type", "unknown"),
                shelter=dev.get("shelter", "Unknown Shelter"),
                gateway_id=dev.get("gateway_id"),
                last_seen=None,
                source_provenance=self._source
            )
            
        for gw in self._registry.get_all_gateways():
            gw_eui = gw.get("chirpstack_gateway_id", "").lower()
            if gw_eui:
                self._gateway_state[gw_eui] = TelemetryGatewayRecord(
                    gateway_id=gw.get("gateway_id", gw_eui),
                    shelter=gw.get("shelter", "Unknown Shelter"),
                    last_seen=None,
                    status="offline",
                    source_provenance=self._source
                )

    def set_mqtt_status(self, connected: bool) -> None:
        self._mqtt_connected = connected

    def health_check(self) -> str:
        return "healthy" if self._mqtt_connected else "degraded (mqtt offline)"

    def list_devices(self, context: RequestContext) -> list[TelemetryDeviceRecord]:
        return list(self._device_state.values())

    def list_gateways(self, context: RequestContext) -> list[TelemetryGatewayRecord]:
        return list(self._gateway_state.values())

    def ingest_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Ingest event from MQTT or Webhook."""
        if event_type == "up":
            self._handle_uplink(payload)
        elif event_type == "status":
            self._handle_status(payload)
            
    def _handle_uplink(self, payload: dict[str, Any]) -> None:
        dev_info = payload.get("deviceInfo", {})
        dev_eui = dev_info.get("devEui", "").lower()
        if not dev_eui:
            return
            
        reg_info = self._registry.lookup_device(dev_eui)
        if not reg_info:
            logger.debug(f"Ignoring uplink from unregistered device {dev_eui}")
            return
            
        now = datetime.now(UTC)
        profile = reg_info.get("fport_profile", "generic")
        
        # We'd ideally look up operational links for the device here from a store.
        links = [
            TelemetryOperationalLink(
                link_type="runway", entity_id="lorawan_live", label="Live sensor feed"
            )
        ]
        
        measurements = parse_chirpstack_uplink(payload, profile, links)
        
        # Update device state
        if dev_eui in self._device_state:
            record = self._device_state[dev_eui]
            record.last_seen = now
            if measurements:
                record.latest_measurements = measurements
                
            # Extract basic rx info for signal quality
            rx_info = payload.get("rxInfo", [])
            if rx_info:
                # Basic SNR normalization for signal quality (0-100)
                snr = rx_info[0].get("snr", 0)
                qual = max(0, min(100, int((snr + 20) * 2.5))) # maps -20..20 to 0..100
                record.signal_quality = qual
                
    def _handle_status(self, payload: dict[str, Any]) -> None:
        dev_info = payload.get("deviceInfo", {})
        dev_eui = dev_info.get("devEui", "").lower()
        if not dev_eui or dev_eui not in self._device_state:
            return
            
        now = datetime.now(UTC)
        record = self._device_state[dev_eui]
        record.last_seen = now
        
        if "batteryLevel" in payload:
            record.battery = payload["batteryLevel"]


class MQTTIngestionTask:
    """Background task connecting to ChirpStack MQTT broker."""
    
    def __init__(
        self, 
        adapter: ChirpStackTelemetryAdapter, 
        broker_url: str,
        topic_prefix: str,
        update_feed: UpdateFeed
    ):
        self.adapter = adapter
        self.broker_url = broker_url
        self.topic_prefix = topic_prefix
        self.update_feed = update_feed
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        
    def start(self) -> None:
        try:
            # Parse simple tcp://host:port for this demo
            host = "127.0.0.1"
            port = 1883
            if self.broker_url.startswith("tcp://"):
                parts = self.broker_url[6:].split(":")
                host = parts[0]
                if len(parts) > 1:
                    port = int(parts[1])
                    
            self._client.connect_async(host, port, 60)
            self._client.loop_start()
        except Exception as e:
            logger.error(f"Failed to start MQTT client: {e}")
            
    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        
    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            self.adapter.set_mqtt_status(True)
            topic = f"{self.topic_prefix}/+/device/+/event/+"
            client.subscribe(topic)
        else:
            self.adapter.set_mqtt_status(False)
            
    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self.adapter.set_mqtt_status(False)
        
    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic_parts = msg.topic.split("/")
            if len(topic_parts) >= 6 and topic_parts[4] == "event":
                event_type = topic_parts[5]
                self.adapter.ingest_event(event_type, payload)
        except Exception as e:
            logger.error(f"Error parsing MQTT message: {e}")

