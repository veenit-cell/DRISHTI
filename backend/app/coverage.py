# ruff: noqa: E501

"""Coverage Debt and decision-aware verification ranking.

Slice 1 of RescueOps.  Debt is an ignorance signal; it is not a casualty or
probability estimate.  Store adapters keep coverage state tenant/workspace
scoped, while the scoring functions remain deterministic and side-effect free.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext

COVERAGE_VERSION = "coverage_debt_v1"
VERIFICATION_VERSION = "decision_impact_v1"
_HAZARD_WEIGHT = {
    "none": 0.25,
    "low": 0.45,
    "moderate": 0.65,
    "high": 0.85,
    "extreme": 1.0,
    "unknown": 0.75,
}


class CoverageCellCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_id: str | None = Field(
        default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$"
    )
    name: str = Field(min_length=1, max_length=160)
    geometry: dict[str, Any] | None = None
    admin_id: str | None = Field(default=None, max_length=120)
    population: int = Field(default=0, ge=0)
    critical_facilities: int = Field(default=0, ge=0)
    hazard_exposure: str = Field(
        default="unknown", pattern=r"^(none|low|moderate|high|extreme|unknown)$"
    )
    required_fact_types: list[str] = Field(default_factory=list, max_length=30)


class CoverageObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_type: str = Field(min_length=1, max_length=120)
    claim_id: str | None = Field(default=None, max_length=120)
    observed_at: datetime | None = None
    freshness_state: str = Field(default="unknown", pattern=r"^(fresh|stale|expired|unknown)$")
    reporting_impaired: bool = False


class CoverageCell(BaseModel):
    cell_id: str
    name: str
    population: int
    critical_facilities: int
    hazard_exposure: str
    required_fact_types: list[str]
    reporting_impaired: bool
    last_verified_at: datetime | None
    observation_count: int


class CoverageDebtResult(BaseModel):
    cell_id: str
    name: str
    debt_score: float = Field(ge=0, le=1)
    debt_band: str
    population_weight: float
    hazard_weight: float
    impairment_weight: float
    time_weight: float
    version: str


class VerificationCandidate(BaseModel):
    cell_id: str
    fact_type: str
    population: int
    debt_score: float
    debt_band: str
    reporting_impaired: bool
    decision_impact_score: float
    plan_ids_affected: list[str]
    what_answer_changes: str
    urgency: float
    debt_reduction: float
    time_cost_hours: float
    team_cost: float
    rank: int
    version: str


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _cell_value(cell: CoverageCell | dict[str, Any], key: str, default: Any = None) -> Any:
    return getattr(cell, key, default) if isinstance(cell, CoverageCell) else cell.get(key, default)


def compute_coverage_debt(cell: CoverageCell, now: datetime) -> CoverageDebtResult:
    """Compute normalized danger of remaining uninformed about one cell."""
    population_weight = min(1.0, (cell.population / 25_000) ** 0.5) if cell.population else 0.0
    hazard_weight = _HAZARD_WEIGHT[cell.hazard_exposure]
    impairment_weight = 1.0 if cell.reporting_impaired else 0.55
    if cell.last_verified_at is None:
        time_weight = 1.0
    else:
        age_hours = max(0.0, (_aware(now) - _aware(cell.last_verified_at)).total_seconds() / 3600)
        time_weight = min(1.0, 0.25 + age_hours / 24.0)
    score = round(
        max(0.0, min(1.0, population_weight * hazard_weight * impairment_weight * time_weight)), 6
    )
    band = (
        "LOW"
        if score < 0.25
        else "MODERATE"
        if score < 0.50
        else "HIGH"
        if score < 0.75
        else "EXTREME"
    )
    return CoverageDebtResult(
        cell_id=cell.cell_id,
        name=cell.name,
        debt_score=score,
        debt_band=band,
        population_weight=round(population_weight, 6),
        hazard_weight=hazard_weight,
        impairment_weight=impairment_weight,
        time_weight=round(time_weight, 6),
        version=COVERAGE_VERSION,
    )


def _assumption_matches(assumption: dict[str, Any], cell_id: str, fact_type: str) -> bool:
    subject_type = assumption.get("subject_type")
    subject_id = assumption.get("subject_id")
    return subject_id in {cell_id, f"{cell_id}:{fact_type}"} or (
        subject_type == "coverage_cell" and subject_id == cell_id
    )


def rank_verification_tasks(
    cells: list[CoverageCell], plans: list[dict[str, Any]], now: datetime
) -> list[VerificationCandidate]:
    """Rank missing/stale facts by whether their answer can change active plans."""
    candidates: list[VerificationCandidate] = []
    active_plans = [
        p
        for p in plans
        if p.get("status", "active") not in {"invalidated", "expired", "superseded"}
    ]
    for cell in cells:
        debt = compute_coverage_debt(cell, now)
        if debt.debt_score == 0:
            continue
        for fact_type in cell.required_fact_types:
            affected = [
                str(plan.get("plan_id", plan.get("id", "unknown")))
                for plan in active_plans
                if any(
                    _assumption_matches(a, cell.cell_id, fact_type)
                    for a in plan.get("assumptions", [])
                )
            ]
            impact = 1.0 if affected else 0.15
            urgency = max(0.1, debt.time_weight)
            reduction = min(1.0, debt.debt_score)
            time_cost = 1.0
            team_cost = 0.1
            score = round(impact * urgency * reduction - time_cost * 0.05 - team_cost * 0.05, 6)
            answer = (
                f"Confirming or rejecting {fact_type} changes plan feasibility for {', '.join(affected)}."
                if affected
                else f"Confirming or rejecting {fact_type} reduces uncertainty but no active plan currently names it as an assumption."
            )
            candidates.append(
                VerificationCandidate(
                    cell_id=cell.cell_id,
                    fact_type=fact_type,
                    population=cell.population,
                    debt_score=debt.debt_score,
                    debt_band=debt.debt_band,
                    reporting_impaired=cell.reporting_impaired,
                    decision_impact_score=score,
                    plan_ids_affected=affected,
                    what_answer_changes=answer,
                    urgency=round(urgency, 6),
                    debt_reduction=round(reduction, 6),
                    time_cost_hours=time_cost,
                    team_cost=team_cost,
                    rank=0,
                    version=VERIFICATION_VERSION,
                )
            )
    candidates.sort(
        key=lambda item: (-item.decision_impact_score, -item.urgency, item.cell_id, item.fact_type)
    )
    return [
        item.model_copy(update={"rank": index}) for index, item in enumerate(candidates, start=1)
    ]


class CoverageStore(Protocol):
    def create_cell(
        self, context: RequestContext, cell: CoverageCellCreate, now: datetime
    ) -> dict[str, Any]: ...
    def list_cells(self, context: RequestContext, now: datetime) -> list[dict[str, Any]]: ...
    def get_cell(self, context: RequestContext, cell_id: str, now: datetime) -> dict[str, Any]: ...
    def create_observation(
        self,
        context: RequestContext,
        cell_id: str,
        observation: CoverageObservationCreate,
        now: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]: ...
    def list_observations(self, context: RequestContext, cell_id: str) -> list[dict[str, Any]]: ...
    def verification_ranking(
        self, context: RequestContext, now: datetime
    ) -> list[dict[str, Any]]: ...


class CoverageNotFoundError(Exception):
    pass


class CoverageConflictError(Exception):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class InMemoryCoverageStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.cells: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.observations: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
        self.plans: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _cell(self, context, cell_id):
        cell = self.cells.get((context.tenant_id, context.workspace_id, cell_id))
        if cell is None:
            raise CoverageNotFoundError
        return cell

    def _observations(self, context, cell_id):
        return [
            o
            for o in self.observations.values()
            if o["tenant_id"] == context.tenant_id
            and o["workspace_id"] == context.workspace_id
            and o["cell_id"] == cell_id
        ]

    def _view(self, context, cell, now):
        observations = self._observations(context, cell["cell_id"])
        verified = [o for o in observations if o["freshness_state"] == "fresh" and o["observed_at"]]
        last = max((datetime.fromisoformat(o["observed_at"]) for o in verified), default=None)
        model = CoverageCell(
            **{
                **cell,
                "last_verified_at": last,
                "observation_count": len(observations),
                "reporting_impaired": any(o["reporting_impaired"] for o in observations)
                or cell.get("reporting_impaired", False),
            }
        )
        return {
            **copy.deepcopy(cell),
            "observation_count": model.observation_count,
            "last_verified_at": last.isoformat() if last else None,
            "reporting_impaired": model.reporting_impaired,
            "debt": compute_coverage_debt(model, now).model_dump(mode="json"),
            "observations": copy.deepcopy(observations),
        }

    def create_cell(self, context, cell, now):
        cell_id = cell.cell_id or f"cell_{uuid4().hex}"
        key = (context.tenant_id, context.workspace_id, cell_id)
        record = {
            "cell_id": cell_id,
            **cell.model_dump(exclude={"cell_id"}),
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "created_at": _aware(now).isoformat(),
            "reporting_impaired": False,
        }
        with self._lock:
            existing = self.cells.get(key)
            if existing:
                if {
                    k: existing[k]
                    for k in record
                    if k not in {"tenant_id", "workspace_id", "created_at"}
                } != {
                    k: record[k]
                    for k in record
                    if k not in {"tenant_id", "workspace_id", "created_at"}
                }:
                    raise CoverageConflictError
                return self._view(context, existing, now)
            self.cells[key] = record
        return self._view(context, record, now)

    def list_cells(self, context, now):
        return [
            self._view(context, cell, now)
            for cell in self.cells.values()
            if cell["tenant_id"] == context.tenant_id
            and cell["workspace_id"] == context.workspace_id
        ]

    def get_cell(self, context, cell_id, now):
        return self._view(context, self._cell(context, cell_id), now)

    def create_observation(self, context, cell_id, observation, now, idempotency_key):
        self._cell(context, cell_id)
        payload = observation.model_dump(mode="json")
        key = (context.tenant_id, context.workspace_id, idempotency_key)
        digest = _hash(payload)
        with self._lock:
            existing = self.idempotency.get(key)
            if existing:
                if existing[0] != digest:
                    raise CoverageConflictError
                replay = copy.deepcopy(existing[1])
                replay["replayed"] = True
                return replay
            record = {
                "observation_id": f"obs_{uuid4().hex}",
                "cell_id": cell_id,
                **payload,
                "observed_at": _aware(observation.observed_at).isoformat()
                if observation.observed_at
                else None,
                "created_at": _aware(now).isoformat(),
                "tenant_id": context.tenant_id,
                "workspace_id": context.workspace_id,
            }
            self.observations[record["observation_id"]] = record
            response = {
                "observation": copy.deepcopy(record),
                "cell": self._view(context, self._cell(context, cell_id), now),
                "replayed": False,
            }
            self.idempotency[key] = (digest, copy.deepcopy(response))
            return response

    def list_observations(self, context, cell_id):
        self._cell(context, cell_id)
        return [copy.deepcopy(o) for o in self._observations(context, cell_id)]

    def verification_ranking(self, context, now):
        cells = [
            CoverageCell(
                **{
                    **self._view(context, c, now),
                    "last_verified_at": self._view(context, c, now)["last_verified_at"],
                }
            )
            for c in self.cells.values()
            if c["tenant_id"] == context.tenant_id and c["workspace_id"] == context.workspace_id
        ]
        return [
            item.model_dump(mode="json")
            for item in rank_verification_tasks(
                cells, self.plans.get((context.tenant_id, context.workspace_id), []), now
            )
        ]


class PostgreSQLCoverageStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connection(self):
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor, context, now):
        cursor.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (context.tenant_id, "Development demo organization", now),
        )
        cursor.execute(
            "INSERT INTO event_workspaces (id, organization_id, name, mode, status, event_time, created_at) VALUES (%s, %s, %s, 'replay', 'active', %s, %s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Development demo event", now, now),
        )
        cursor.execute(
            "INSERT INTO memberships (organization_id, actor_id, role, created_at) VALUES (%s, %s, %s, %s) ON CONFLICT (organization_id, actor_id) DO NOTHING",
            (context.tenant_id, context.actor_id, context.role, now),
        )

    def _row(self, row):
        return {
            "cell_id": row[0],
            "name": row[1],
            "geometry": json.loads(row[2]) if row[2] else None,
            "admin_id": row[3],
            "population": row[4],
            "critical_facilities": row[5],
            "hazard_exposure": row[6],
            "required_fact_types": row[7],
            "created_at": row[8].isoformat(),
        }

    def _observations(self, cursor, context, cell_id):
        cursor.execute(
            "SELECT observation_id, fact_type, claim_id, observed_at, freshness_state, reporting_impaired, created_at FROM coverage_observations WHERE organization_id=%s AND workspace_id=%s AND cell_id=%s ORDER BY observed_at NULLS LAST, observation_id",
            (context.tenant_id, context.workspace_id, cell_id),
        )
        return [
            {
                "observation_id": r[0],
                "cell_id": cell_id,
                "fact_type": r[1],
                "claim_id": r[2],
                "observed_at": r[3].isoformat() if r[3] else None,
                "freshness_state": r[4],
                "reporting_impaired": r[5],
                "created_at": r[6].isoformat(),
            }
            for r in cursor.fetchall()
        ]

    def _view(self, cursor, context, row, now):
        record = self._row(row)
        observations = self._observations(cursor, context, record["cell_id"])
        fresh = [o for o in observations if o["freshness_state"] == "fresh" and o["observed_at"]]
        last = max((datetime.fromisoformat(o["observed_at"]) for o in fresh), default=None)
        model = CoverageCell(
            **{
                **record,
                "last_verified_at": last,
                "observation_count": len(observations),
                "reporting_impaired": any(o["reporting_impaired"] for o in observations),
            }
        )
        return {
            **record,
            "observation_count": len(observations),
            "last_verified_at": last.isoformat() if last else None,
            "reporting_impaired": model.reporting_impaired,
            "debt": compute_coverage_debt(model, now).model_dump(mode="json"),
            "observations": observations,
        }

    def create_cell(self, context, cell, now):
        cell_id = cell.cell_id or f"cell_{uuid4().hex}"
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            geometry = json.dumps(cell.geometry) if cell.geometry else None
            cursor.execute(
                "INSERT INTO coverage_cells (cell_id, organization_id, workspace_id, name, geometry, admin_id, population, critical_facilities, hazard_exposure, required_fact_types, created_at) VALUES (%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,%s,%s,%s,%s,%s) ON CONFLICT (cell_id) DO NOTHING",
                (
                    cell_id,
                    context.tenant_id,
                    context.workspace_id,
                    cell.name,
                    geometry,
                    cell.admin_id,
                    cell.population,
                    cell.critical_facilities,
                    cell.hazard_exposure,
                    cell.required_fact_types,
                    now,
                ),
            )
            cursor.execute(
                "SELECT cell_id, name, ST_AsGeoJSON(geometry), admin_id, population, critical_facilities, hazard_exposure, required_fact_types, created_at FROM coverage_cells WHERE cell_id=%s AND organization_id=%s AND workspace_id=%s",
                (cell_id, context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise CoverageNotFoundError
            return self._view(cursor, context, row, now)

    def list_cells(self, context, now):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT cell_id, name, ST_AsGeoJSON(geometry), admin_id, population, critical_facilities, hazard_exposure, required_fact_types, created_at FROM coverage_cells WHERE organization_id=%s AND workspace_id=%s ORDER BY cell_id",
                (context.tenant_id, context.workspace_id),
            )
            return [self._view(cursor, context, row, now) for row in cursor.fetchall()]

    def get_cell(self, context, cell_id, now):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT cell_id, name, ST_AsGeoJSON(geometry), admin_id, population, critical_facilities, hazard_exposure, required_fact_types, created_at FROM coverage_cells WHERE cell_id=%s AND organization_id=%s AND workspace_id=%s",
                (cell_id, context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise CoverageNotFoundError
            return self._view(cursor, context, row, now)

    def create_observation(self, context, cell_id, observation, now, idempotency_key):
        payload = observation.model_dump(mode="json")
        digest = _hash(payload)
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "SELECT cell_id, name, ST_AsGeoJSON(geometry), admin_id, population, critical_facilities, hazard_exposure, required_fact_types, created_at FROM coverage_cells WHERE cell_id=%s AND organization_id=%s AND workspace_id=%s",
                (cell_id, context.tenant_id, context.workspace_id),
            )
            cell_row = cursor.fetchone()
            if cell_row is None:
                raise CoverageNotFoundError
            cursor.execute(
                "SELECT request_hash, observation_id FROM coverage_observations WHERE organization_id=%s AND workspace_id=%s AND idempotency_key=%s",
                (context.tenant_id, context.workspace_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing:
                if existing[0] != digest:
                    raise CoverageConflictError
                return {
                    "observation_id": existing[1],
                    "replayed": True,
                    "cell": self._view(cursor, context, cell_row, now),
                }
            observation_id = f"obs_{uuid4().hex}"
            cursor.execute(
                "INSERT INTO coverage_observations (observation_id, organization_id, workspace_id, cell_id, fact_type, claim_id, observed_at, freshness_state, reporting_impaired, idempotency_key, request_hash, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    observation_id,
                    context.tenant_id,
                    context.workspace_id,
                    cell_id,
                    observation.fact_type,
                    observation.claim_id,
                    observation.observed_at,
                    observation.freshness_state,
                    observation.reporting_impaired,
                    idempotency_key,
                    digest,
                    now,
                ),
            )
            return {
                "observation_id": observation_id,
                "replayed": False,
                "cell": self._view(cursor, context, cell_row, now),
            }

    def list_observations(self, context, cell_id):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT cell_id, name, ST_AsGeoJSON(geometry), admin_id, population, critical_facilities, hazard_exposure, required_fact_types, created_at FROM coverage_cells WHERE cell_id=%s AND organization_id=%s AND workspace_id=%s",
                (cell_id, context.tenant_id, context.workspace_id),
            )
            if cursor.fetchone() is None:
                raise CoverageNotFoundError
            return self._observations(cursor, context, cell_id)

    def verification_ranking(self, context, now):
        cells = self.list_cells(context, now)
        models = [
            CoverageCell(
                **{
                    **cell,
                    "last_verified_at": datetime.fromisoformat(cell["last_verified_at"])
                    if cell["last_verified_at"]
                    else None,
                }
            )
            for cell in cells
        ]
        return [item.model_dump(mode="json") for item in rank_verification_tasks(models, [], now)]
