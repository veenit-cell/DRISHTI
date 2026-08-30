"""Small, deterministic cascading-capability evaluator (no persistence)."""
# ruff: noqa: E501, UP038, B905

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

RULE_VERSION = "cascade_v1"
MAX_DEPTH = 4

_UNITS = {
    "power_available": "boolean",
    "purification_available": "boolean",
    "water_runway_hours": "hours",
    "cold_chain_hours": "hours",
    "unsafe_water_liters": "liters",
    "population": "people",
    "capacity": "people",
    "population_influx_per_hour": "people/hour",
    "medical_demand_trend": "category",
    "medical_demand_per_hour": "units/hour",
    "diagnostic_capacity_per_hour": "units/hour",
    "medicine_runway_hours": "hours",
}

DEPENDENCY_GRAPH = {
    "power": ["water_purification", "medicine_cold_chain"],
    "water_purification": ["safe_water_runway"],
    "unsafe_water": ["operational_disease_risk_pressure"],
    "population_pressure": ["operational_disease_risk_pressure"],
    "medical_demand": ["medicine_diagnostic_pressure"],
}


class CascadeSnapshot(BaseModel):
    """Packet-local typed adapter; callers provide explicit units and freshness."""

    model_config = ConfigDict(extra="forbid")

    observed_at: str | None = None
    freshness_state: str = Field(default="unknown", pattern="^(fresh|stale|unknown)$")
    values: dict[str, float | str | bool | None] = Field(default_factory=dict, max_length=20)
    units: dict[str, str] = Field(default_factory=dict, max_length=20)
    field_freshness: dict[str, str] = Field(default_factory=dict, max_length=20)
    supporting_refs: dict[str, list[str]] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def validate_contract(self) -> CascadeSnapshot:
        fields = set(self.values) | set(self.units) | set(self.field_freshness) | set(self.supporting_refs)
        if fields - set(_UNITS):
            raise ValueError("snapshot contains an unsupported cascade field")
        for field, value in self.values.items():
            if value is not None and self.units.get(field) != _UNITS[field]:
                raise ValueError(f"invalid or missing unit for {field}")
        if any(state not in {"fresh", "stale", "unknown"} for state in self.field_freshness.values()):
            raise ValueError("invalid field freshness")
        return self


class CascadeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: CascadeSnapshot
    max_depth: int = Field(default=MAX_DEPTH, ge=1, le=MAX_DEPTH)


class CascadeFinding(BaseModel):
    affected_capability: str
    severity: str
    estimated_time_window_hours: float | None
    causal_path: list[str]
    supporting_input_refs: list[str]
    unknown_contributors: list[str]
    confidence: str
    rule_version: str


class CascadeResult(BaseModel):
    rule_version: str
    observed_at: str | None
    max_depth: int
    findings: list[CascadeFinding]


def validate_dependency_graph(graph: dict[str, list[str]], max_depth: int = MAX_DEPTH) -> None:
    """Reject cycles and paths deeper than the evaluator's bounded contract."""
    if max_depth < 1 or max_depth > MAX_DEPTH:
        raise ValueError("max depth exceeds cascade bound")
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str, depth: int) -> None:
        if depth > max_depth:
            raise ValueError("dependency graph exceeds cascade depth")
        if node in visiting:
            raise ValueError("dependency graph contains a cycle")
        if node in done:
            return
        visiting.add(node)
        for child in sorted(graph.get(node, [])):
            visit(child, depth + 1)
        visiting.remove(node)
        done.add(node)

    for node in sorted(graph):
        visit(node, 1)


def _value(snapshot: CascadeSnapshot, key: str) -> float | str | bool | None:
    return snapshot.values.get(key)


def _refs(snapshot: CascadeSnapshot, fields: list[str]) -> list[str]:
    return sorted({ref for field in fields for ref in snapshot.supporting_refs.get(field, [f"input:{field}"])})


def _quality(snapshot: CascadeSnapshot, fields: list[str]) -> tuple[str, list[str]]:
    states = [snapshot.field_freshness.get(field, snapshot.freshness_state) for field in fields]
    unknown = [
        field for field, state in zip(fields, states)
        if state == "unknown" or snapshot.values.get(field) is None
    ]
    stale = [field for field, state in zip(fields, states) if state == "stale"]
    if snapshot.freshness_state == "unknown":
        unknown.append("snapshot freshness")
    if snapshot.freshness_state == "stale":
        stale.append("snapshot freshness")
    return ("low" if unknown or stale else "high"), sorted(set(unknown + stale))


def _finding(snapshot: CascadeSnapshot, capability: str, severity: str, window: float | None, path: list[str], fields: list[str]) -> CascadeFinding:
    confidence, quality_issues = _quality(snapshot, fields)
    return CascadeFinding(
        affected_capability=capability,
        severity=severity,
        estimated_time_window_hours=round(window, 1) if window is not None else None,
        causal_path=path,
        supporting_input_refs=_refs(snapshot, fields),
        unknown_contributors=quality_issues,
        confidence=confidence,
        rule_version=RULE_VERSION,
    )


def evaluate_cascade(request: CascadeRequest, dependency_graph: dict[str, list[str]] | None = None) -> CascadeResult:
    """Evaluate fixed rules once; no state is mutated and output ordering is stable."""
    graph = dependency_graph or DEPENDENCY_GRAPH
    validate_dependency_graph(graph, request.max_depth)
    s = request.snapshot
    v = s.values
    findings: list[CascadeFinding] = []
    power = _value(s, "power_available")
    purification = _value(s, "purification_available")
    water_window = _value(s, "water_runway_hours")
    if power is False:
        fields = ["power_available", "purification_available", "water_runway_hours"]
        severity = "critical" if isinstance(water_window, (int, float)) and water_window <= 2 else "high"
        findings.append(_finding(s, "safe_water_runway", severity, water_window if isinstance(water_window, (int, float)) else None, ["power", "water_purification", "safe_water_runway"], fields))
    elif power is None or purification is None or water_window is None:
        fields = ["power_available", "purification_available", "water_runway_hours"]
        findings.append(_finding(s, "safe_water_runway", "medium", None, ["power", "water_purification", "safe_water_runway"], fields))
    cold = _value(s, "cold_chain_hours")
    if power is False:
        findings.append(_finding(s, "medicine_cold_chain", "critical" if isinstance(cold, (int, float)) and cold <= 2 else "high", cold if isinstance(cold, (int, float)) else None, ["power", "medicine_cold_chain"], ["power_available", "cold_chain_hours"]))
    elif power is None or cold is None:
        findings.append(_finding(s, "medicine_cold_chain", "medium", None, ["power", "medicine_cold_chain"], ["power_available", "cold_chain_hours"]))
    unsafe, population, capacity, influx = (v.get(k) for k in ("unsafe_water_liters", "population", "capacity", "population_influx_per_hour"))
    pressure = isinstance(influx, (int, float)) and influx > 0 or isinstance(population, (int, float)) and isinstance(capacity, (int, float)) and population > capacity
    if isinstance(unsafe, (int, float)) and unsafe > 0 and pressure:
        findings.append(_finding(s, "operational_disease_risk_pressure", "high", None, ["unsafe_water", "population_pressure", "operational_disease_risk_pressure"], ["unsafe_water_liters", "population", "capacity", "population_influx_per_hour"]))
    elif unsafe is None or not (isinstance(influx, (int, float)) or isinstance(population, (int, float)) and isinstance(capacity, (int, float))):
        findings.append(_finding(s, "operational_disease_risk_pressure", "medium", None, ["unsafe_water", "population_pressure", "operational_disease_risk_pressure"], ["unsafe_water_liters", "population", "capacity", "population_influx_per_hour"]))
    trend, demand, diagnostic = v.get("medical_demand_trend"), v.get("medical_demand_per_hour"), v.get("diagnostic_capacity_per_hour")
    rising = trend == "rising" or isinstance(demand, (int, float)) and isinstance(diagnostic, (int, float)) and demand > diagnostic
    if rising:
        findings.append(_finding(s, "medicine_diagnostic_pressure", "high", v.get("medicine_runway_hours") if isinstance(v.get("medicine_runway_hours"), (int, float)) else None, ["medical_demand", "medicine", "diagnostics"], ["medical_demand_trend", "medical_demand_per_hour", "diagnostic_capacity_per_hour", "medicine_runway_hours"]))
    elif trend is None and demand is None:
        findings.append(_finding(s, "medicine_diagnostic_pressure", "medium", None, ["medical_demand", "medicine", "diagnostics"], ["medical_demand_trend", "medical_demand_per_hour", "diagnostic_capacity_per_hour"]))
    findings.sort(key=lambda item: (item.affected_capability, tuple(item.causal_path)))
    return CascadeResult(rule_version=RULE_VERSION, observed_at=s.observed_at, max_depth=request.max_depth, findings=findings)
