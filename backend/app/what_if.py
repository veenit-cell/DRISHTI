"""Bounded, non-mutating intervention comparisons over an explicit runway snapshot."""
# ruff: noqa: E501, UP038

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.runway import (
    MAX_HORIZON_HOURS,
    RunwayProjection,
    RunwayRequest,
    RunwaySnapshot,
    project_runway,
)

SCENARIO_VERSION = "what_if_v1"
ScenarioValue = float | str | bool | None


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "add_potable_water",
        "purification",
        "shift_power_load",
        "population_influx",
        "water_contamination",
        "battery_reduction",
        "purification_unavailable",
        "route_blockage",
        "resource_transfer",
    ]
    amount: float | None = None
    unit: str | None = None
    enabled: bool | None = None
    power_cost_kw: float | None = None
    resource_type: Literal["potable_water", "medicine"] | None = None
    source_resource: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_intervention(self) -> Intervention:
        if self.kind in {"purification_unavailable", "route_blockage"}:
            if self.amount not in (None, 0) or self.unit is not None or self.power_cost_kw is not None:
                raise ValueError(f"{self.kind} does not accept an amount, unit, or power cost")
            if self.enabled is None:
                raise ValueError(f"{self.kind} requires enabled")
            if self.resource_type is not None or self.source_resource is not None:
                raise ValueError("resource transfer fields are only valid for resource_transfer")
            return self
        expected = {
            "add_potable_water": "liters",
            "purification": "liters/hour",
            "shift_power_load": "kilowatts",
            "population_influx": "people/hour",
            "water_contamination": "percent",
            "battery_reduction": "percent",
            "resource_transfer": None,
        }[self.kind]
        if self.kind == "resource_transfer":
            if self.resource_type is None:
                raise ValueError("resource_transfer requires resource_type")
            expected = "liters" if self.resource_type == "potable_water" else "units"
        if self.unit != expected or self.amount is None:
            raise ValueError(f"{self.kind} requires amount in {expected}")
        if self.kind == "purification":
            if self.enabled is None:
                raise ValueError("purification requires enabled")
            if self.enabled and (self.power_cost_kw is None or self.power_cost_kw <= 0):
                raise ValueError("enabled purification requires positive power_cost_kw")
            if not self.enabled and self.power_cost_kw not in (None, 0):
                raise ValueError("disabled purification cannot have a power cost")
            if self.amount < 0:
                raise ValueError("purification rate cannot be negative")
        elif self.kind in {"water_contamination", "battery_reduction"} and not 0 <= self.amount <= 100:
            raise ValueError(f"{self.kind} must be between 0 and 100 percent")
        elif self.amount <= 0 if self.kind in {"add_potable_water", "shift_power_load", "battery_reduction", "resource_transfer"} else self.amount < 0:
            raise ValueError("intervention amount is invalid")
        if self.kind not in {"purification", "purification_unavailable", "route_blockage"} and (self.enabled is not None or self.power_cost_kw is not None):
            raise ValueError("enabled and power_cost_kw are only valid for purification")
        if self.kind != "resource_transfer" and (self.resource_type is not None or self.source_resource is not None):
            raise ValueError("resource_type and source_resource are only valid for resource_transfer")
        return self


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: RunwaySnapshot
    intervention: Intervention
    horizon_hours: float = Field(default=48.0, gt=0, le=MAX_HORIZON_HOURS)


class ScenarioComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    changed_inputs: dict[str, ScenarioValue]
    projection: RunwayProjection
    resource_consumption: dict[str, float | None]
    risk_level: Literal["low", "medium", "high", "critical", "unknown"]
    tradeoffs: list[str]
    uncertainty: list[str]
    scenario_hash: str


class WhatIfResult(BaseModel):
    scenario_version: str
    input_hash: str
    baseline: ScenarioComparison
    do_nothing: ScenarioComparison
    intervention: ScenarioComparison


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _resource_consumption(snapshot: RunwaySnapshot) -> dict[str, float | None]:
    values = snapshot.values
    population = values.get("population")
    influx = values.get("population_influx_per_hour")
    population_factor = 1.0
    if population is not None and influx is not None and population > 0 and influx >= 0:
        population_factor += influx / population
    water_rate = values.get("water_consumption_liters_per_hour")
    medicine_rate = values.get("medicine_consumption_per_hour")
    return {
        "water_liters_per_hour": None if water_rate is None else water_rate * population_factor,
        "water_replenishment_liters_per_hour": values.get("replenishment_liters_per_hour"),
        "power_kilowatts": values.get("power_consumption_kw"),
        "medicine_units_per_hour": None if medicine_rate is None else medicine_rate * population_factor,
        "cold_chain_hours_per_hour": values.get("cold_chain_depletion_hours_per_hour"),
    }


def _risk_level(projection: RunwayProjection, changed: dict[str, ScenarioValue]) -> Literal["low", "medium", "high", "critical", "unknown"]:
    states = {item.state for item in projection.projections}
    if "critical" in states:
        return "critical"
    if changed.get("route_blocked") is True or changed.get("water_contamination_percent", 0) >= 50:
        return "high"
    if any(item.within_horizon is True for item in projection.projections):
        return "high"
    if "unknown" in states:
        return "unknown"
    if changed.get("water_contamination_percent", 0) > 0:
        return "medium"
    return "low"


def _compare(label: str, snapshot: RunwaySnapshot, horizon: float, changed: dict[str, ScenarioValue], tradeoffs: list[str], uncertainty: list[str] | None = None) -> ScenarioComparison:
    projection = project_runway(RunwayRequest(snapshot=snapshot, horizon_hours=horizon))
    reported_uncertainty = sorted({f"{p.resource}: {p.freshness_state}/{p.confidence}" for p in projection.projections if p.confidence != "medium"})
    reported_uncertainty.extend(uncertainty or [])
    reported_uncertainty = sorted(set(reported_uncertainty))
    payload = {"label": label, "changed_inputs": changed, "projection": projection.model_dump(mode="json"), "tradeoffs": tradeoffs}
    return ScenarioComparison(label=label, changed_inputs=changed, projection=projection, resource_consumption=_resource_consumption(snapshot), risk_level=_risk_level(projection, changed), tradeoffs=tradeoffs, uncertainty=reported_uncertainty, scenario_hash=_hash(payload))


def evaluate_what_if(request: WhatIfRequest) -> WhatIfResult:
    """Compare baseline, explicit do-nothing, and one synthetic intervention."""
    source = request.snapshot
    simulation_notice = "This is a simulation; it does not change operational state."
    baseline = _compare("baseline", source, request.horizon_hours, {}, ["No intervention applied"], [simulation_notice])
    do_nothing = _compare("do_nothing", source.model_copy(deep=True), request.horizon_hours, {}, ["Operational state remains unchanged"], [simulation_notice])
    simulated = source.model_copy(deep=True)
    values = dict(simulated.values)
    intervention = request.intervention
    changed: dict[str, ScenarioValue] = {}
    tradeoffs: list[str] = []
    uncertainty = [simulation_notice]
    if intervention.kind == "add_potable_water":
        key = "potable_water_liters"
        values[key] = None if values.get(key) is None else values[key] + intervention.amount
        changed[key] = values[key]
        tradeoffs.append(f"adds {intervention.amount:g} liters of potable reserve")
    elif intervention.kind == "purification":
        rate = intervention.amount if intervention.enabled else 0
        values["replenishment_liters_per_hour"] = None if values.get("replenishment_liters_per_hour") is None else values["replenishment_liters_per_hour"] + rate
        if intervention.enabled:
            values["power_consumption_kw"] = None if values.get("power_consumption_kw") is None else values["power_consumption_kw"] + intervention.power_cost_kw
            tradeoffs.append(f"adds {rate:g} liters/hour treatment transfer and costs {intervention.power_cost_kw:g} kilowatts")
        else:
            tradeoffs.append("purification disabled; no treatment transfer is assumed")
        changed.update({"replenishment_liters_per_hour": values["replenishment_liters_per_hour"], "power_consumption_kw": values.get("power_consumption_kw")})
    elif intervention.kind == "water_contamination":
        values["water_contamination_percent"] = intervention.amount
        simulated.units["water_contamination_percent"] = "percent"
        simulated.field_freshness["water_contamination_percent"] = "unknown"
        changed["water_contamination_percent"] = intervention.amount
        tradeoffs.append(f"marks {intervention.amount:g}% of potable reserve as potentially unusable")
        uncertainty.append("Contamination effect is represented as usable-reserve reduction; field confirmation is still required.")
    elif intervention.kind == "battery_reduction":
        key = "battery_percent"
        values[key] = None if values.get(key) is None else max(0, values[key] - intervention.amount)
        changed[key] = values[key]
        tradeoffs.append(f"reduces battery reserve by {intervention.amount:g} percentage points")
    elif intervention.kind == "purification_unavailable":
        unavailable = intervention.enabled is True
        if unavailable:
            values["replenishment_liters_per_hour"] = 0
            simulated.units["replenishment_liters_per_hour"] = "liters/hour"
            simulated.field_freshness["replenishment_liters_per_hour"] = "unknown"
            changed.update({"purification_available": False, "replenishment_liters_per_hour": 0})
            tradeoffs.append("removes treatment replenishment from the simulated water balance")
        else:
            changed["purification_available"] = True
            tradeoffs.append("keeps the current treatment replenishment assumption")
    elif intervention.kind == "route_blockage":
        blocked = intervention.enabled is True
        changed["route_blocked"] = blocked
        tradeoffs.append("blocks the route-dependent intervention path" if blocked else "keeps the route available")
        uncertainty.append("Route travel time and access capacity are not modeled by runway projections.")
    elif intervention.kind == "resource_transfer":
        key = "potable_water_liters" if intervention.resource_type == "potable_water" else "medicine_units"
        values[key] = None if values.get(key) is None else values[key] + intervention.amount
        simulated.field_freshness[key] = "unknown"
        changed.update({key: values[key], "transferred_from": intervention.source_resource or "external reserve"})
        tradeoffs.append(f"transfers {intervention.amount:g} {intervention.unit} into {intervention.resource_type.replace('_', ' ')} reserve")
        uncertainty.append("The source reserve is not included in this single-shelter snapshot; source-side depletion is not modeled.")
    elif intervention.kind == "shift_power_load":
        key = "power_consumption_kw"
        values[key] = None if values.get(key) is None else values[key] - intervention.amount
        changed[key] = values[key]
        tradeoffs.append(f"shifts {intervention.amount:g} kilowatts of non-critical load")
    else:
        key = "population_influx_per_hour"
        values[key] = intervention.amount
        changed[key] = intervention.amount
        tradeoffs.append(f"sets expected influx to {intervention.amount:g} people/hour; demand scales accordingly")
    simulated.values = values
    result = _compare("intervention", simulated, request.horizon_hours, changed, tradeoffs, uncertainty)
    input_hash = _hash({"snapshot": source.model_dump(mode="json"), "intervention": intervention.model_dump(mode="json"), "horizon_hours": request.horizon_hours})
    return WhatIfResult(scenario_version=SCENARIO_VERSION, input_hash=input_hash, baseline=baseline, do_nothing=do_nothing, intervention=result)
