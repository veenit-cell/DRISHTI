"""Coupled shelter-state contract and persistence adapters."""

# ruff: noqa: E501

from __future__ import annotations

import copy
from datetime import datetime
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.context import RequestContext

EXPECTED_UNITS = {
    "population": "people",
    "capacity": "people",
    "population_influx_per_hour": "people/hour",
    "potable_water_liters": "liters",
    "unsafe_water_liters": "liters",
    "water_consumption_liters_per_hour": "liters/hour",
    "treatment_capacity_liters_per_hour": "liters/hour",
    "battery_percent": "percent",
    "power_consumption_kw": "kilowatts",
    "medicine_units": "units",
    "medicine_consumption_per_hour": "units/hour",
    "cold_chain_hours": "hours",
    "diagnostic_capacity_per_hour": "cases/hour",
    "replenishment_liters_per_hour": "liters/hour",
}


class ShelterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shelter_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    synthetic: bool = False


class ShelterObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    source: str = Field(min_length=1, max_length=120)
    provenance: dict[str, str] = Field(default_factory=dict, max_length=20)
    freshness_state: str = Field(default="fresh", pattern="^(fresh|stale|unknown)$")
    values: dict[str, float | None] = Field(default_factory=dict, max_length=30)
    units: dict[str, str] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def validate_measurements(self) -> ShelterObservationCreate:
        unknown_fields = set(self.values) - set(EXPECTED_UNITS)
        unknown_units = set(self.units) - set(EXPECTED_UNITS)
        if unknown_fields or unknown_units:
            raise ValueError("values and units must use the shelter-state metric vocabulary")
        missing_units = {
            field for field, value in self.values.items() if value is not None and field not in self.units
        }
        if missing_units:
            raise ValueError(f"non-null measurements require units: {sorted(missing_units)}")
        invalid_units = {
            field
            for field, unit in self.units.items()
            if unit != EXPECTED_UNITS[field]
        }
        if invalid_units:
            raise ValueError(f"invalid units for metrics: {sorted(invalid_units)}")
        return self


class ShelterStateStore(Protocol):
    def create_shelter(self, context: RequestContext, shelter: ShelterCreate, now: datetime) -> dict[str, Any]: ...
    def list_shelters(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def create_observation(self, context: RequestContext, shelter_id: str, observation: ShelterObservationCreate, now: datetime, idempotency_key: str) -> dict[str, Any]: ...
    def list_observations(self, context: RequestContext, shelter_id: str) -> list[dict[str, Any]]: ...
    def get_state(self, context: RequestContext, shelter_id: str) -> dict[str, Any]: ...
    def seed_demo(self, context: RequestContext, now: datetime) -> dict[str, Any]: ...


class ShelterNotFoundError(Exception):
    pass


class ShelterConflictError(Exception):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _hash(value: Any) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _snapshot(shelter: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    values = {field: None for field in EXPECTED_UNITS}
    units = dict(EXPECTED_UNITS)
    freshness = {field: "unknown" for field in EXPECTED_UNITS}
    sources: dict[str, str | None] = {field: None for field in EXPECTED_UNITS}
    provenance: dict[str, dict[str, str]] = {field: {} for field in EXPECTED_UNITS}
    ordered = sorted(observations, key=lambda item: (item["observed_at"], item["id"]), reverse=True)
    for observation in ordered:
        for field, value in observation["values"].items():
            if freshness[field] == "unknown":
                values[field] = value
                freshness[field] = observation["freshness_state"] if value is not None else "unknown"
                sources[field] = observation["source"]
                provenance[field] = dict(observation["provenance"])
    top_freshness = "stale" if "stale" in freshness.values() else "fresh" if "fresh" in freshness.values() else "unknown"
    snapshot = {
        "shelter": {"id": shelter["id"], "name": shelter["name"], "synthetic": shelter["synthetic"]},
        "observed_at": max((item["observed_at"] for item in observations), default=None),
        "freshness_state": top_freshness,
        "values": values,
        "units": units,
        "field_freshness": freshness,
        "sources": sources,
        "provenance": provenance,
    }
    snapshot["snapshot_hash"] = _hash(snapshot)
    return snapshot


def _record(shelter_id: str, observation: ShelterObservationCreate, now: datetime, observation_id: str | None = None) -> dict[str, Any]:
    return {
        "id": observation_id or f"obs_{uuid4().hex}",
        "shelter_id": shelter_id,
        "observed_at": _iso(observation.observed_at),
        "recorded_at": _iso(now),
        "source": observation.source,
        "provenance": observation.provenance,
        "freshness_state": observation.freshness_state,
        "values": observation.values,
        "units": observation.units,
    }


class InMemoryShelterStateStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.shelters: dict[str, dict[str, Any]] = {}
        self.observations: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}

    def create_shelter(self, context, shelter, now):
        key = f"{context.tenant_id}:{context.workspace_id}:{shelter.shelter_id}"
        with self._lock:
            existing = self.shelters.get(key)
            if existing:
                if existing["name"] != shelter.name or existing["synthetic"] != shelter.synthetic:
                    raise ShelterConflictError
                return copy.deepcopy(existing)
            record = {"id": shelter.shelter_id, "name": shelter.name, "synthetic": shelter.synthetic, "tenant_id": context.tenant_id, "workspace_id": context.workspace_id, "created_at": _iso(now)}
            self.shelters[key] = record
            return copy.deepcopy(record)

    def list_shelters(self, context):
        return [copy.deepcopy(item) for item in self.shelters.values() if item["tenant_id"] == context.tenant_id and item["workspace_id"] == context.workspace_id]

    def _shelter(self, context, shelter_id):
        key = f"{context.tenant_id}:{context.workspace_id}:{shelter_id}"
        shelter = self.shelters.get(key)
        if shelter is None:
            raise ShelterNotFoundError
        return shelter

    def create_observation(self, context, shelter_id, observation, now, idempotency_key):
        shelter = self._shelter(context, shelter_id)
        payload = observation.model_dump(mode="json")
        digest = _hash(payload)
        key = (context.tenant_id, context.workspace_id, idempotency_key)
        existing = self.idempotency.get(key)
        if existing:
            if existing[0] != digest:
                raise ShelterConflictError
            replay = copy.deepcopy(existing[1])
            replay["replayed"] = True
            return replay
        record = _record(shelter_id, observation, now)
        with self._lock:
            self.observations[record["id"]] = {**record, "tenant_id": context.tenant_id, "workspace_id": context.workspace_id}
            state = _snapshot(shelter, self._observations(context, shelter_id))
        response = {"observation": copy.deepcopy(record), "state": state, "replayed": False}
        self.idempotency[key] = (digest, copy.deepcopy(response))
        return response

    def _observations(self, context, shelter_id):
        return [item for item in self.observations.values() if item["tenant_id"] == context.tenant_id and item["workspace_id"] == context.workspace_id and item["shelter_id"] == shelter_id]

    def list_observations(self, context, shelter_id):
        self._shelter(context, shelter_id)
        return [copy.deepcopy(item) for item in self._observations(context, shelter_id)]

    def get_state(self, context, shelter_id):
        shelter = self._shelter(context, shelter_id)
        return _snapshot(shelter, self._observations(context, shelter_id))

    def seed_demo(self, context, now):
        shelter = self.create_shelter(context, ShelterCreate(shelter_id="shelter_demo_north", name="Synthetic North Shelter", synthetic=True), now)
        observation = ShelterObservationCreate(observed_at=now, source="synthetic_demo_seed", provenance={"scenario": "fixed_north_sector_v1"}, values={"population": 1800, "capacity": 2200, "population_influx_per_hour": 180, "potable_water_liters": 4200, "unsafe_water_liters": 800, "water_consumption_liters_per_hour": 420, "treatment_capacity_liters_per_hour": 300, "battery_percent": 31, "power_consumption_kw": 18, "medicine_units": 240, "medicine_consumption_per_hour": 20, "cold_chain_hours": 8, "diagnostic_capacity_per_hour": 12, "replenishment_liters_per_hour": 0}, units=EXPECTED_UNITS)
        result = self.create_observation(context, shelter["id"], observation, now, "shelter-demo-seed")
        result["shelter"] = shelter
        return result


class PostgreSQLShelterStateStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connection(self):
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor, context, now):
        cursor.execute("INSERT INTO organizations (id, name, created_at) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING", (context.tenant_id, "Development demo organization", now))
        cursor.execute("INSERT INTO event_workspaces (id, organization_id, name, mode, status, event_time, created_at) VALUES (%s, %s, %s, 'replay', 'active', %s, %s) ON CONFLICT (id) DO NOTHING", (context.workspace_id, context.tenant_id, "Development demo event", now, now))
        cursor.execute("INSERT INTO memberships (organization_id, actor_id, role, created_at) VALUES (%s, %s, %s, %s) ON CONFLICT (organization_id, actor_id) DO NOTHING", (context.tenant_id, context.actor_id, context.role, now))

    def create_shelter(self, context, shelter, now):
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute("SELECT id, name, synthetic, created_at FROM shelters WHERE id=%s AND organization_id=%s AND workspace_id=%s", (shelter.shelter_id, context.tenant_id, context.workspace_id))
            existing = cursor.fetchone()
            if existing:
                if existing[1] != shelter.name or existing[2] != shelter.synthetic:
                    raise ShelterConflictError
                return {"id": existing[0], "name": existing[1], "synthetic": existing[2], "created_at": _iso(existing[3])}
            cursor.execute("INSERT INTO shelters (id, organization_id, workspace_id, name, synthetic, created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, name, synthetic, created_at", (shelter.shelter_id, context.tenant_id, context.workspace_id, shelter.name, shelter.synthetic, now))
            row = cursor.fetchone()
            return {"id": row[0], "name": row[1], "synthetic": row[2], "created_at": _iso(row[3])}

    def list_shelters(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, name, synthetic, created_at FROM shelters WHERE organization_id=%s AND workspace_id=%s ORDER BY id", (context.tenant_id, context.workspace_id))
            return [{"id": row[0], "name": row[1], "synthetic": row[2], "created_at": _iso(row[3])} for row in cursor.fetchall()]

    def _shelter(self, cursor, context, shelter_id):
        cursor.execute("SELECT id, name, synthetic, created_at FROM shelters WHERE id=%s AND organization_id=%s AND workspace_id=%s", (shelter_id, context.tenant_id, context.workspace_id))
        row = cursor.fetchone()
        if row is None:
            raise ShelterNotFoundError
        return {"id": row[0], "name": row[1], "synthetic": row[2], "created_at": _iso(row[3])}

    @staticmethod
    def _rows(cursor, context, shelter_id):
        cursor.execute("SELECT id, observed_at, recorded_at, source, provenance, freshness_state, values_json, units_json FROM shelter_observations WHERE shelter_id=%s AND organization_id=%s AND workspace_id=%s ORDER BY observed_at, id", (shelter_id, context.tenant_id, context.workspace_id))
        return [{"id": row[0], "shelter_id": shelter_id, "observed_at": row[1].isoformat(), "recorded_at": _iso(row[2]), "source": row[3], "provenance": row[4], "freshness_state": row[5], "values": row[6], "units": row[7]} for row in cursor.fetchall()]

    def create_observation(self, context, shelter_id, observation, now, idempotency_key):
        payload = observation.model_dump(mode="json")
        digest = _hash(payload)
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            shelter = self._shelter(cursor, context, shelter_id)
            cursor.execute("SELECT request_hash, id, observed_at, recorded_at, source, provenance, freshness_state, values_json, units_json FROM shelter_observations WHERE organization_id=%s AND workspace_id=%s AND idempotency_key=%s", (context.tenant_id, context.workspace_id, idempotency_key))
            existing = cursor.fetchone()
            if existing:
                if existing[0] != digest:
                    raise ShelterConflictError
                record = {"id": existing[1], "shelter_id": shelter_id, "observed_at": existing[2].isoformat(), "recorded_at": _iso(existing[3]), "source": existing[4], "provenance": existing[5], "freshness_state": existing[6], "values": existing[7], "units": existing[8]}
                return {"observation": record, "state": _snapshot(shelter, self._rows(cursor, context, shelter_id)), "replayed": True}
            record = _record(shelter_id, observation, now)
            cursor.execute("INSERT INTO shelter_observations (id, organization_id, workspace_id, shelter_id, observed_at, recorded_at, source, provenance, freshness_state, values_json, units_json, idempotency_key, request_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (record["id"], context.tenant_id, context.workspace_id, shelter_id, observation.observed_at, now, observation.source, Jsonb(observation.provenance), observation.freshness_state, Jsonb(observation.values), Jsonb(observation.units), idempotency_key, digest))
            state = _snapshot(shelter, self._rows(cursor, context, shelter_id))
            cursor.execute("INSERT INTO shelter_state_snapshots (id, organization_id, workspace_id, shelter_id, snapshot_hash, snapshot_json, generated_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (shelter_id, snapshot_hash) DO NOTHING", (f"snap_{uuid4().hex}", context.tenant_id, context.workspace_id, shelter_id, state["snapshot_hash"], Jsonb(state), now))
            return {"observation": record, "state": state, "replayed": False}

    def list_observations(self, context, shelter_id):
        with self._connection() as connection, connection.cursor() as cursor:
            self._shelter(cursor, context, shelter_id)
            return self._rows(cursor, context, shelter_id)

    def get_state(self, context, shelter_id):
        with self._connection() as connection, connection.cursor() as cursor:
            shelter = self._shelter(cursor, context, shelter_id)
            return _snapshot(shelter, self._rows(cursor, context, shelter_id))

    def seed_demo(self, context, now):
        shelter = self.create_shelter(context, ShelterCreate(shelter_id="shelter_demo_north", name="Synthetic North Shelter", synthetic=True), now)
        observation = ShelterObservationCreate(observed_at=now, source="synthetic_demo_seed", provenance={"scenario": "fixed_north_sector_v1"}, values={"population": 1800, "capacity": 2200, "population_influx_per_hour": 180, "potable_water_liters": 4200, "unsafe_water_liters": 800, "water_consumption_liters_per_hour": 420, "treatment_capacity_liters_per_hour": 300, "battery_percent": 31, "power_consumption_kw": 18, "medicine_units": 240, "medicine_consumption_per_hour": 20, "cold_chain_hours": 8, "diagnostic_capacity_per_hour": 12, "replenishment_liters_per_hour": 0}, units=EXPECTED_UNITS)
        result = self.create_observation(context, shelter["id"], observation, now, "shelter-demo-seed")
        result["shelter"] = shelter
        return result
