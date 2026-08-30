"""Deterministic, non-mutating resource runway projections."""

# Compact formula tables below intentionally keep related inputs together.
# ruff: noqa: E501

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMULA_VERSION = "runway_v1"
MAX_HORIZON_HOURS = 168.0

UNITS = {
    "population": "people",
    "population_influx_per_hour": "people/hour",
    "potable_water_liters": "liters",
    "water_consumption_liters_per_hour": "liters/hour",
    "replenishment_liters_per_hour": "liters/hour",
    "battery_percent": "percent",
    "battery_capacity_kwh": "kilowatt-hours",
    "power_consumption_kw": "kilowatts",
    "battery_replenishment_kw": "kilowatts",
    "medicine_units": "units",
    "medicine_consumption_per_hour": "units/hour",
    "cold_chain_hours": "hours",
    "cold_chain_depletion_hours_per_hour": "hours/hour",
}

THRESHOLD_UNITS = {
    "potable_water_liters": "liters",
    "battery_percent": "percent",
    "medicine_units": "units",
    "cold_chain_hours": "hours",
}


class RunwaySnapshot(BaseModel):
    """A compatible shelter snapshot plus explicit runway-only inputs."""

    model_config = ConfigDict(extra="forbid")

    observed_at: str | None = None
    freshness_state: str = Field(default="unknown", pattern="^(fresh|stale|unknown)$")
    field_freshness: dict[str, str] = Field(default_factory=dict, max_length=30)
    values: dict[str, float | None] = Field(default_factory=dict, max_length=30)
    units: dict[str, str] = Field(default_factory=dict, max_length=30)
    thresholds: dict[str, float | None] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def validate_contract(self) -> RunwaySnapshot:
        unknown_values = set(self.values) - set(UNITS)
        unknown_units = set(self.units) - set(UNITS)
        unknown_thresholds = set(self.thresholds) - set(THRESHOLD_UNITS)
        if unknown_values or unknown_units or unknown_thresholds:
            raise ValueError("snapshot contains an unsupported runway field")
        for field, value in self.values.items():
            if value is not None and self.units.get(field) != UNITS[field]:
                raise ValueError(f"invalid or missing unit for {field}")
        for field, value in self.thresholds.items():
            if value is not None and self.units.get(field) != THRESHOLD_UNITS[field]:
                raise ValueError(f"invalid or missing unit for threshold {field}")
        for field, state in self.field_freshness.items():
            if field not in UNITS or state not in {"fresh", "stale", "unknown"}:
                raise ValueError("invalid field freshness")
        return self


class RunwayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: RunwaySnapshot
    horizon_hours: float = Field(default=48.0, gt=0, le=MAX_HORIZON_HOURS)


class ResourceProjection(BaseModel):
    resource: str
    state: str
    time_to_critical_hours: float | None
    threshold: float | None
    unit: str
    freshness_state: str
    confidence: str
    within_horizon: bool | None
    contributors: list[str]


class RunwayProjection(BaseModel):
    formula_version: str
    observed_at: str | None
    horizon_hours: float
    projections: list[ResourceProjection]


def _round_hours(value: float) -> float:
    return round(value, 1)


def _quality(snapshot: RunwaySnapshot, fields: list[str]) -> tuple[str, str]:
    states = [snapshot.field_freshness.get(field, snapshot.freshness_state) for field in fields]
    if any(state == "unknown" for state in states) or snapshot.freshness_state == "unknown":
        return "unknown", "low"
    if any(state == "stale" for state in states) or snapshot.freshness_state == "stale":
        return "stale", "low"
    return "fresh", "medium"


def _projection(
    snapshot: RunwaySnapshot,
    resource: str,
    quantity_field: str,
    threshold_key: str,
    rate: float | None,
    unit: str,
    required_fields: list[str],
    horizon: float,
    contributors: list[str],
) -> ResourceProjection:
    quantity = snapshot.values.get(quantity_field)
    threshold = snapshot.thresholds.get(threshold_key)
    freshness, confidence = _quality(snapshot, required_fields)
    if quantity is None or threshold is None or rate is None or quantity < 0 or threshold < 0:
        return ResourceProjection(
            resource=resource,
            state="unknown",
            time_to_critical_hours=None,
            threshold=threshold,
            unit=unit,
            freshness_state=freshness,
            confidence="low",
            within_horizon=None,
            contributors=contributors + ["required input is unknown or invalid"],
        )
    available = quantity - threshold
    if available <= 0:
        return ResourceProjection(
            resource=resource,
            state="critical",
            time_to_critical_hours=0.0,
            threshold=threshold,
            unit=unit,
            freshness_state=freshness,
            confidence=confidence,
            within_horizon=True,
            contributors=contributors + ["current quantity is at or below threshold"],
        )
    if rate <= 0:
        return ResourceProjection(
            resource=resource,
            state="not_depleting",
            time_to_critical_hours=None,
            threshold=threshold,
            unit=unit,
            freshness_state=freshness,
            confidence=confidence,
            within_horizon=None,
            contributors=contributors + ["net depletion rate is zero or replenishing"],
        )
    hours = _round_hours(available / rate)
    return ResourceProjection(
        resource=resource,
        state="projected",
        time_to_critical_hours=hours,
        threshold=threshold,
        unit=unit,
        freshness_state=freshness,
        confidence=confidence,
        within_horizon=hours <= horizon,
        contributors=contributors + [f"net depletion rate = {rate:g} {unit}/hour"],
    )


def project_runway(request: RunwayRequest) -> RunwayProjection:
    """Evaluate a bounded snapshot without changing it."""
    snapshot = request.snapshot
    values = snapshot.values
    population = values.get("population")
    influx = values.get("population_influx_per_hour")
    population_factor = 1.0
    population_note = "population change not applied"
    if population is not None and influx is not None and population > 0 and influx >= 0:
        population_factor += influx / population
        population_note = (
            f"population influx increases hourly demand by factor {population_factor:.3f}"
        )

    water_rate = values.get("water_consumption_liters_per_hour")
    water_replenishment = values.get("replenishment_liters_per_hour")
    effective_water_rate = None if water_rate is None or water_replenishment is None or water_rate < 0 or water_replenishment < 0 else water_rate * population_factor - water_replenishment
    battery_percent = values.get("battery_percent")
    battery_capacity = values.get("battery_capacity_kwh")
    power_rate = values.get("power_consumption_kw")
    battery_replenishment = values.get("battery_replenishment_kw")
    effective_battery_rate = None if power_rate is None or battery_replenishment is None or power_rate < 0 or battery_replenishment < 0 else power_rate - battery_replenishment
    battery_quantity = None if battery_percent is None or battery_capacity is None else battery_percent
    battery_threshold = snapshot.thresholds.get("battery_percent")
    projections = [
        _projection(snapshot, "potable_water", "potable_water_liters", "potable_water_liters", effective_water_rate, "liters", ["potable_water_liters", "water_consumption_liters_per_hour", "replenishment_liters_per_hour"], request.horizon_hours, [population_note, "water treatment capacity is not counted as replenishment without a confirmed transfer"]),
        _projection(snapshot, "battery", "battery_percent", "battery_percent", None if battery_quantity is None or battery_threshold is None or battery_capacity is None else (effective_battery_rate * 100 / battery_capacity if effective_battery_rate is not None else None), "percent", ["battery_percent", "battery_capacity_kwh", "power_consumption_kw", "battery_replenishment_kw"], request.horizon_hours, ["battery percent converted using explicit battery capacity", population_note]),
        _projection(snapshot, "medicine", "medicine_units", "medicine_units", None if values.get("medicine_consumption_per_hour") is None or values["medicine_consumption_per_hour"] < 0 else values["medicine_consumption_per_hour"] * population_factor, "units", ["medicine_units", "medicine_consumption_per_hour"], request.horizon_hours, [population_note]),
        _projection(snapshot, "cold_chain", "cold_chain_hours", "cold_chain_hours", None if values.get("cold_chain_depletion_hours_per_hour") is not None and values["cold_chain_depletion_hours_per_hour"] < 0 else values.get("cold_chain_depletion_hours_per_hour"), "hours", ["cold_chain_hours", "cold_chain_depletion_hours_per_hour"], request.horizon_hours, ["reserve is operational time, not a clinical guarantee"]),
    ]
    return RunwayProjection(formula_version=FORMULA_VERSION, observed_at=snapshot.observed_at, horizon_hours=request.horizon_hours, projections=projections)
