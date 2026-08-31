"""Scoped LoRaWAN telemetry summaries for operator decision support.

The adapter boundary accepts already-authorized backend observations. Device keys,
join credentials, and raw gateway payloads are intentionally not part of the
public models or response projection.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext


TelemetryFreshness = Literal["fresh", "stale", "silent", "unknown"]
TelemetryMode = Literal["live", "synthetic", "mixed"]
TelemetryLinkType = Literal["runway", "cascade_finding", "recommendation"]


class TelemetrySourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=80)
    source_class: str = Field(min_length=1, max_length=80)
    synthetic: bool = False


class TelemetryOperationalLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_type: TelemetryLinkType
    entity_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=160)


TelemetryValue = float | int | str | bool | None


class TelemetryMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    value: TelemetryValue
    unit: str = Field(default="", max_length=32)
    observed_at: datetime | None = None
    status: Literal["normal", "critical", "unknown"] = "unknown"
    links: list[TelemetryOperationalLink] = Field(default_factory=list, max_length=6)


class TelemetryDeviceRecord(BaseModel):
    """Safe adapter input; no device key or raw LoRaWAN payload is accepted."""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=128)
    sensor_type: str = Field(min_length=1, max_length=80)
    shelter: str = Field(min_length=1, max_length=160)
    gateway_id: str | None = Field(default=None, max_length=128)
    last_seen: datetime | None = None
    battery: float | None = Field(default=None, ge=0, le=100)
    signal_quality: float | None = Field(default=None, ge=0, le=100)
    latest_measurements: list[TelemetryMeasurement] = Field(default_factory=list, max_length=20)
    source_provenance: TelemetrySourceProvenance


class TelemetryGatewayRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_id: str = Field(min_length=1, max_length=128)
    shelter: str = Field(min_length=1, max_length=160)
    last_seen: datetime | None = None
    status: Literal["healthy", "degraded", "offline", "unknown"] = "unknown"
    connected_devices: int = Field(default=0, ge=0, le=10000)
    source_provenance: TelemetrySourceProvenance


class TelemetryDeviceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    sensor_type: str
    shelter: str
    last_seen: datetime | None
    battery: float | None
    signal_quality: float | None
    freshness: TelemetryFreshness
    communication_gap: bool
    communication_gap_minutes: float | None
    latest_measurements: list[TelemetryMeasurement]
    source_provenance: TelemetrySourceProvenance


class TelemetryGatewaySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_id: str
    shelter: str
    last_seen: datetime | None
    status: Literal["healthy", "degraded", "offline", "unknown"]
    freshness: TelemetryFreshness
    communication_gap: bool
    connected_devices: int
    source_provenance: TelemetrySourceProvenance


class TelemetryCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fresh_sensors: int = Field(ge=0)
    stale_sensors: int = Field(ge=0)
    silent_sensors: int = Field(ge=0)
    critical_readings: int = Field(ge=0)
    gateway_count: int = Field(ge=0)


class TelemetrySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    mode: TelemetryMode
    freshness: TelemetryFreshness
    counts: TelemetryCounts
    devices: list[TelemetryDeviceSummary] = Field(max_length=100)
    gateways: list[TelemetryGatewaySummary] = Field(max_length=25)
    warning: str = "No telemetry does not mean safe conditions."


class TelemetryAdapter(Protocol):
    def list_devices(self, context: RequestContext) -> list[TelemetryDeviceRecord]: ...

    def list_gateways(self, context: RequestContext) -> list[TelemetryGatewayRecord]: ...

    def health_check(self) -> str: ...


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _freshness(last_seen: datetime | None, now: datetime) -> tuple[TelemetryFreshness, float | None]:
    seen = _utc(last_seen)
    if seen is None:
        return "silent", None
    age_minutes = max(0.0, (now.astimezone(UTC) - seen).total_seconds() / 60)
    if age_minutes <= 15:
        return "fresh", round(age_minutes, 1)
    if age_minutes <= 60:
        return "stale", round(age_minutes, 1)
    return "silent", round(age_minutes, 1)


def _mode(
    devices: list[TelemetryDeviceRecord],
    gateways: list[TelemetryGatewayRecord],
    fallback: TelemetryMode,
) -> TelemetryMode:
    provenance = [item.source_provenance.synthetic for item in [*devices, *gateways]]
    if not provenance:
        return fallback
    if all(provenance):
        return "synthetic"
    if not any(provenance):
        return "live"
    return "mixed"


def _overall_freshness(values: list[TelemetryFreshness]) -> TelemetryFreshness:
    if not values:
        return "unknown"
    if "silent" in values:
        return "silent"
    if "stale" in values:
        return "stale"
    if "unknown" in values:
        return "unknown"
    return "fresh"


def build_telemetry_summary(
    devices: list[TelemetryDeviceRecord],
    gateways: list[TelemetryGatewayRecord],
    generated_at: datetime,
    workspace_mode: TelemetryMode = "live",
) -> dict[str, Any]:
    """Build a bounded, read-only public projection from adapter observations."""

    now = generated_at.astimezone(UTC) if generated_at.tzinfo else generated_at.replace(tzinfo=UTC)
    device_summaries: list[TelemetryDeviceSummary] = []
    gateway_summaries: list[TelemetryGatewaySummary] = []
    device_freshness_values: list[TelemetryFreshness] = []
    freshness_values: list[TelemetryFreshness] = []
    critical_readings = 0

    for record in devices[:100]:
        freshness, gap_minutes = _freshness(record.last_seen, now)
        measurements = copy.deepcopy(record.latest_measurements[:8])
        critical_readings += sum(item.status == "critical" for item in measurements)
        device_freshness_values.append(freshness)
        freshness_values.append(freshness)
        device_summaries.append(
            TelemetryDeviceSummary(
                device_id=record.device_id,
                sensor_type=record.sensor_type,
                shelter=record.shelter,
                last_seen=_utc(record.last_seen),
                battery=record.battery,
                signal_quality=record.signal_quality,
                freshness=freshness,
                communication_gap=freshness in {"stale", "silent"},
                communication_gap_minutes=gap_minutes,
                latest_measurements=measurements,
                source_provenance=record.source_provenance,
            )
        )

    for record in gateways[:25]:
        freshness, _ = _freshness(record.last_seen, now)
        freshness_values.append(freshness)
        gateway_summaries.append(
            TelemetryGatewaySummary(
                gateway_id=record.gateway_id,
                shelter=record.shelter,
                last_seen=_utc(record.last_seen),
                status=record.status,
                freshness=freshness,
                communication_gap=freshness in {"stale", "silent"},
                connected_devices=record.connected_devices,
                source_provenance=record.source_provenance,
            )
        )

    result = TelemetrySummary(
        generated_at=now,
        mode=_mode(devices[:100], gateways[:25], workspace_mode),
        freshness=_overall_freshness(freshness_values),
        counts=TelemetryCounts(
            fresh_sensors=sum(item == "fresh" for item in device_freshness_values),
            stale_sensors=sum(item == "stale" for item in device_freshness_values),
            silent_sensors=sum(item == "silent" for item in device_freshness_values),
            critical_readings=critical_readings,
            gateway_count=len(gateway_summaries),
        ),
        devices=device_summaries,
        gateways=gateway_summaries,
    )
    return result.model_dump(mode="json")


def _synthetic_records() -> tuple[list[TelemetryDeviceRecord], list[TelemetryGatewayRecord]]:
    source = TelemetrySourceProvenance(
        source="lorawan_demo_fixture", source_class="synthetic_telemetry", synthetic=True
    )
    links = [
        TelemetryOperationalLink(
            link_type="runway", entity_id="potable_water", label="Potable-water runway"
        ),
        TelemetryOperationalLink(
            link_type="cascade_finding", entity_id="safe_water_runway", label="Safe-water cascade"
        ),
        TelemetryOperationalLink(
            link_type="recommendation", entity_id="pending_water_action", label="Pending water action"
        ),
    ]
    now = datetime.now(UTC)
    devices = [
        TelemetryDeviceRecord(
            device_id="sensor-synthetic-water-01",
            sensor_type="water_quality",
            shelter="Synthetic North Shelter",
            gateway_id="gateway-synthetic-north",
            last_seen=now,
            battery=84,
            signal_quality=91,
            latest_measurements=[
                TelemetryMeasurement(
                    name="turbidity",
                    value=12.4,
                    unit="NTU",
                    observed_at=now,
                    status="critical",
                    links=links,
                )
            ],
            source_provenance=source,
        ),
        TelemetryDeviceRecord(
            device_id="sensor-synthetic-power-02",
            sensor_type="battery_health",
            shelter="Synthetic North Shelter",
            gateway_id="gateway-synthetic-north",
            last_seen=now - timedelta(minutes=30),
            battery=62,
            signal_quality=64,
            latest_measurements=[
                TelemetryMeasurement(name="reserve", value=31, unit="%", observed_at=now, status="normal", links=links[:1])
            ],
            source_provenance=source,
        ),
        TelemetryDeviceRecord(
            device_id="sensor-synthetic-silent-03",
            sensor_type="shelter_environment",
            shelter="Synthetic East Shelter",
            gateway_id="gateway-synthetic-east",
            last_seen=None,
            battery=None,
            signal_quality=None,
            latest_measurements=[],
            source_provenance=source,
        ),
    ]
    gateways = [
        TelemetryGatewayRecord(
            gateway_id="gateway-synthetic-north",
            shelter="Synthetic North Shelter",
            last_seen=now,
            status="healthy",
            connected_devices=2,
            source_provenance=source,
        ),
        TelemetryGatewayRecord(
            gateway_id="gateway-synthetic-east",
            shelter="Synthetic East Shelter",
            last_seen=None,
            status="offline",
            connected_devices=1,
            source_provenance=source,
        ),
    ]
    return devices, gateways


class InMemoryTelemetryAdapter:
    """Scoped adapter for tests and the synthetic development workspace."""

    def __init__(self, seed_synthetic: bool = False) -> None:
        self._devices: dict[tuple[str, str], list[TelemetryDeviceRecord]] = {}
        self._gateways: dict[tuple[str, str], list[TelemetryGatewayRecord]] = {}
        self._seed_synthetic = seed_synthetic

    def set_workspace_data(
        self,
        tenant_id: str,
        workspace_id: str,
        devices: list[TelemetryDeviceRecord],
        gateways: list[TelemetryGatewayRecord],
    ) -> None:
        self._devices[(tenant_id, workspace_id)] = copy.deepcopy(devices)
        self._gateways[(tenant_id, workspace_id)] = copy.deepcopy(gateways)

    def health_check(self) -> str:
        return "healthy"

    def list_devices(self, context: RequestContext) -> list[TelemetryDeviceRecord]:
        key = (context.tenant_id, context.workspace_id)
        if key in self._devices:
            return copy.deepcopy(self._devices[key])
        return copy.deepcopy(_synthetic_records()[0]) if self._seed_synthetic else []

    def list_gateways(self, context: RequestContext) -> list[TelemetryGatewayRecord]:
        key = (context.tenant_id, context.workspace_id)
        if key in self._gateways:
            return copy.deepcopy(self._gateways[key])
        return copy.deepcopy(_synthetic_records()[1]) if self._seed_synthetic else []
