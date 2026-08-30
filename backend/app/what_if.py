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


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["add_potable_water", "purification", "shift_power_load", "population_influx"]
    amount: float | None = None
    unit: str | None = None
    enabled: bool | None = None
    power_cost_kw: float | None = None

    @model_validator(mode="after")
    def validate_intervention(self) -> Intervention:
        expected = {
            "add_potable_water": "liters",
            "purification": "liters/hour",
            "shift_power_load": "kilowatts",
            "population_influx": "people/hour",
        }[self.kind]
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
        elif self.amount <= 0 if self.kind in {"add_potable_water", "shift_power_load"} else self.amount < 0:
            raise ValueError("intervention amount is invalid")
        if self.kind != "purification" and (self.enabled is not None or self.power_cost_kw is not None):
            raise ValueError("enabled and power_cost_kw are only valid for purification")
        return self


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: RunwaySnapshot
    intervention: Intervention
    horizon_hours: float = Field(default=48.0, gt=0, le=MAX_HORIZON_HOURS)


class ScenarioComparison(BaseModel):
    label: str
    changed_inputs: dict[str, float | None]
    projection: RunwayProjection
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


def _compare(label: str, snapshot: RunwaySnapshot, horizon: float, changed: dict[str, float | None], tradeoffs: list[str]) -> ScenarioComparison:
    projection = project_runway(RunwayRequest(snapshot=snapshot, horizon_hours=horizon))
    uncertainty = sorted({f"{p.resource}: {p.freshness_state}/{p.confidence}" for p in projection.projections if p.confidence != "medium"})
    payload = {"label": label, "changed_inputs": changed, "projection": projection.model_dump(mode="json"), "tradeoffs": tradeoffs}
    return ScenarioComparison(label=label, changed_inputs=changed, projection=projection, tradeoffs=tradeoffs, uncertainty=uncertainty, scenario_hash=_hash(payload))


def evaluate_what_if(request: WhatIfRequest) -> WhatIfResult:
    """Compare baseline, explicit do-nothing, and one synthetic intervention."""
    source = request.snapshot
    baseline = _compare("baseline", source, request.horizon_hours, {}, ["No intervention applied"])
    do_nothing = _compare("do_nothing", source.model_copy(deep=True), request.horizon_hours, {}, ["Operational state remains unchanged"])
    simulated = source.model_copy(deep=True)
    values = dict(simulated.values)
    intervention = request.intervention
    changed: dict[str, float | None] = {}
    tradeoffs: list[str] = []
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
    result = _compare("intervention", simulated, request.horizon_hours, changed, tradeoffs)
    input_hash = _hash({"snapshot": source.model_dump(mode="json"), "intervention": intervention.model_dump(mode="json"), "horizon_hours": request.horizon_hours})
    return WhatIfResult(scenario_version=SCENARIO_VERSION, input_hash=input_hash, baseline=baseline, do_nothing=do_nothing, intervention=result)
