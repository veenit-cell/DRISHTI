"""Phase 2 evidence primitives: immutable reports, claims, and bounded map features."""

# SQL statements are intentionally kept readable as single statements.
# ruff: noqa: E501

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.context import RequestContext
from app.operations import PostgreSQLOperationsStore
from app.plans import PlanStore


class SourceInput(BaseModel):
    channel: str = Field(min_length=1, max_length=64)
    source_class: str = Field(min_length=1, max_length=64)


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: str = Field(pattern=r"^(image/jpeg|image/png|application/pdf|text/plain)$")
    byte_size: int = Field(ge=1, le=5_000_000)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class LocationInput(BaseModel):
    geometry: dict[str, Any]
    uncertainty_m: int | None = Field(default=None, ge=0)
    place_text: str | None = Field(default=None, max_length=256)
    state_code: str | None = Field(default=None, max_length=16)
    district_id: str | None = Field(default=None, max_length=64)
    block_id: str | None = Field(default=None, max_length=64)
    village_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_point(self) -> LocationInput:
        if self.geometry.get("type") != "Point":
            raise ValueError("Only GeoJSON Point locations are supported in this checkpoint")
        coordinates = self.geometry.get("coordinates")
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 2
            or not all(isinstance(value, int | float) for value in coordinates)
            or not -180 <= coordinates[0] <= 180
            or not -90 <= coordinates[1] <= 90
        ):
            raise ValueError("Point coordinates must be [longitude, latitude] within WGS84 bounds")
        return self


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: int = Field(default=1, strict=True)
    client_record_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    observed_at: datetime | None = None
    received_at: datetime | None = None
    source: SourceInput
    location: LocationInput | None = None
    report_type: str = Field(min_length=1, max_length=64)
    facts: dict[str, Any] = Field(default_factory=dict)
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=5)
    privacy_class: str = Field(
        default="restricted_operational", pattern=r"^(restricted_operational|internal)$"
    )

    @field_validator("contract_version")
    @classmethod
    def supported_contract_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Only report contract version 1 is supported")
        return value


class ReportConflictError(Exception):
    """The client record ID was reused with a different immutable payload."""


class ReportNotFoundError(Exception):
    """The scoped report does not exist."""


class IncidentNotFoundError(Exception):
    """The scoped incident does not exist."""


class EvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_updates: dict[str, str] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_claim_states(self) -> EvidenceReview:
        allowed = {"proposed", "unknown", "corroborated", "contradicted", "stale", "superseded"}
        if any(state not in allowed for state in self.claim_updates.values()):
            raise ValueError("Unsupported claim verification state")
        return self


class IncidentLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=128)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("Timestamps must include a timezone offset")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _opaque_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _cursor_encode(recorded_at: str, report_id: str) -> str:
    raw = json.dumps([recorded_at, report_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) for item in value)
        ):
            raise ValueError
        return value[0], value[1]
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise ValueError("Invalid report cursor") from None


def normalize_report(
    report: ReportCreate, normalization_run_id: str | None = None
) -> dict[str, Any]:
    """Build deterministic derived claims without changing the submitted payload."""
    run_id = normalization_run_id or _opaque_id("norm")
    warnings: list[str] = []
    if report.observed_at is None:
        warnings.append("OBSERVED_TIME_UNKNOWN")
    if report.received_at is None:
        warnings.append("CLIENT_RECEIVED_TIME_UNKNOWN")
    if report.location is None:
        warnings.append("LOCATION_UNKNOWN")

    claims: list[dict[str, Any]] = []

    def add_claim(claim_type: str, value: Any) -> None:
        state = "unknown" if value is None else "proposed"
        if value is None:
            warnings.append(f"{claim_type.upper()}_UNKNOWN")
        claims.append(
            {
                "id": _opaque_id("clm"),
                "claim_type": claim_type,
                "value": copy.deepcopy(value),
                "verification_state": state,
                "normalization_run_id": run_id,
            }
        )

    add_claim("report_type", report.report_type)
    add_claim("location", report.location.model_dump(mode="json") if report.location else None)
    for fact_name in sorted(report.facts):
        add_claim(f"fact:{fact_name}", report.facts[fact_name])

    return {
        "id": run_id,
        "mapping_version": "phase-2-demo-mapping-v1",
        "taxonomy_version": "phase-2-demo-taxonomy-v1",
        "status": "completed",
        "warnings": sorted(set(warnings)),
        "claims": claims,
    }


class EvidenceStore(Protocol):
    def create_report(
        self, context: RequestContext, report: ReportCreate, recorded_at: datetime
    ) -> tuple[dict[str, Any], bool]: ...

    def list_reports(
        self, context: RequestContext, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    def get_report(self, context: RequestContext, report_id: str) -> dict[str, Any]: ...

    def seed_demo(self, context: RequestContext, recorded_at: datetime) -> int: ...

    def map_features(
        self,
        context: RequestContext,
        limit: int,
        bbox: tuple[float, float, float, float] | None,
    ) -> dict[str, Any]: ...

    def review_report(
        self, context: RequestContext, report_id: str, review: EvidenceReview, reviewed_at: datetime
    ) -> dict[str, Any]: ...

    def link_incident(
        self, context: RequestContext, report_id: str, link: IncidentLink, linked_at: datetime
    ) -> dict[str, Any]: ...

    def link_command_incident(
        self, context: RequestContext, report_id: str, incident_id: str, linked_at: datetime
    ) -> dict[str, Any]: ...

    def list_incidents(self, context: RequestContext) -> list[dict[str, Any]]: ...

    def list_sectors(self, context: RequestContext) -> list[dict[str, Any]]: ...


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "client_record_id": record["client_record_id"],
        "report_type": record["report_type"],
        "status": record["status"],
        "source": copy.deepcopy(record["source"]),
        "observed_at": record["observed_at"],
        "received_at": record["received_at"],
        "recorded_at": record["recorded_at"],
        "location": copy.deepcopy(record["location"]),
        "warnings": list(record["warnings"]),
        "revision": record["revision"],
    }


def _feature(
    kind: str, feature_id: str, geometry: dict[str, Any], properties: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": geometry,
        "properties": {"feature_kind": kind, **properties},
    }


def _in_bbox(
    geometry: dict[str, Any] | None, bbox: tuple[float, float, float, float] | None
) -> bool:
    if bbox is None:
        return True
    if geometry is None:
        return False
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return False
    while coordinates and isinstance(coordinates[0], list):
        coordinates = coordinates[0]
    if len(coordinates) != 2 or not all(isinstance(value, int | float) for value in coordinates):
        return False
    longitude, latitude = coordinates
    return bbox[0] <= longitude <= bbox[2] and bbox[1] <= latitude <= bbox[3]


def _feature_collection(
    incidents: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    limit: int,
    bbox: tuple[float, float, float, float] | None,
    sectors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for incident in incidents:
        geometry = incident["location"]
        if _in_bbox(geometry, bbox):
            features.append(
                _feature(
                    "synthetic_incident",
                    incident["id"],
                    geometry,
                    {
                        "title": incident["title"],
                        "need_type": incident["need_type"],
                        "verification_state": incident["verification_state"],
                        "source": incident["source"],
                        "observed_at": incident["observed_at"],
                        "synthetic": True,
                    },
                )
            )
    for report in reports:
        geometry = (
            (report.get("location") or {}).get("geometry") if report.get("location") else None
        )
        if geometry is not None and _in_bbox(geometry, bbox):
            features.append(
                _feature(
                    "report",
                    report["id"],
                    geometry,
                    {
                        "report_type": report["report_type"],
                        "status": report["status"],
                        "source": report["source"],
                        "observed_at": report["observed_at"],
                        "recorded_at": report["recorded_at"],
                        "location_uncertainty_m": (report.get("location") or {}).get(
                            "uncertainty_m"
                        ),
                    },
                )
            )
    for sector in sectors or []:
        geometry = sector["geometry"]
        if _in_bbox(geometry, bbox) or bbox is None:
            features.append(
                _feature(
                    "sector",
                    sector["id"],
                    geometry,
                    {
                        "name": sector["name"],
                        "assessment_state": sector["assessment_state"],
                        "assessment_source": sector.get("assessment_source"),
                        "assessed_at": sector.get("assessed_at"),
                    },
                )
            )
    return {"type": "FeatureCollection", "features": features[:limit]}


class InMemoryEvidenceStore:
    """Deterministic test adapter; production/dev application uses PostgreSQLEvidenceStore."""

    def __init__(self, plan_store: PlanStore | None = None) -> None:
        self._lock = Lock()
        self._reports: dict[str, dict[str, Any]] = {}
        self._keys: dict[tuple[str, str, str], str] = {}
        self._incidents: dict[str, dict[str, Any]] = {}
        self._sectors: dict[str, dict[str, Any]] = {}
        self._links: set[tuple[str, str]] = set()
        self._command_links: dict[str, list[dict[str, Any]]] = {}
        self.plan_store = plan_store

    def create_report(
        self, context: RequestContext, report: ReportCreate, recorded_at: datetime
    ) -> tuple[dict[str, Any], bool]:
        payload = report.model_dump(mode="json", exclude_unset=True)
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        key = (context.tenant_id, context.workspace_id, report.client_record_id)
        normalized = normalize_report(report)
        now = _utc_iso(recorded_at)
        record = {
            "id": _opaque_id("rpt"),
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "client_record_id": report.client_record_id,
            "original_payload": copy.deepcopy(payload),
            "original_sha256": digest,
            "source": report.source.model_dump(mode="json"),
            "report_type": report.report_type,
            "privacy_class": report.privacy_class,
            "observed_at": _utc_iso(report.observed_at),
            "received_at": _utc_iso(report.received_at),
            "recorded_at": now,
            "location": report.location.model_dump(mode="json") if report.location else None,
            "status": "accepted_for_review",
            "revision": 1,
            "warnings": normalized["warnings"],
            "normalization": normalized,
            "claims": normalized["claims"],
            "duplicate_candidates": [],
        }
        with self._lock:
            existing_id = self._keys.get(key)
            if existing_id:
                existing = self._reports[existing_id]
                if existing["original_sha256"] != digest:
                    raise ReportConflictError
                return copy.deepcopy(existing), True
            self._keys[key] = record["id"]
            for existing in self._reports.values():
                if (
                    existing["workspace_id"] == context.workspace_id
                    and existing["report_type"] == report.report_type
                    and existing.get("location") == record.get("location")
                ):
                    candidate = {
                        "report_id": record["id"],
                        "candidate_report_id": existing["id"],
                        "reason": "same report type and location",
                    }
                    record["duplicate_candidates"].append(candidate)
            self._reports[record["id"]] = record
        return copy.deepcopy(record), False

    def list_reports(
        self, context: RequestContext, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        marker = _cursor_decode(cursor)
        rows = [
            value
            for value in self._reports.values()
            if value["tenant_id"] == context.tenant_id
            and value["workspace_id"] == context.workspace_id
        ]
        rows.sort(key=lambda item: (item["recorded_at"], item["id"]), reverse=True)
        if marker:
            rows = [row for row in rows if (row["recorded_at"], row["id"]) < marker]
        page = rows[:limit]
        next_cursor = (
            _cursor_encode(page[-1]["recorded_at"], page[-1]["id"]) if len(rows) > limit else None
        )
        return [_summary(copy.deepcopy(row)) for row in page], next_cursor

    def get_report(self, context: RequestContext, report_id: str) -> dict[str, Any]:
        record = self._reports.get(report_id)
        if (
            record is None
            or record["tenant_id"] != context.tenant_id
            or record["workspace_id"] != context.workspace_id
        ):
            raise ReportNotFoundError
        detail = copy.deepcopy(record)
        detail["command_incident_links"] = copy.deepcopy(self._command_links.get(report_id, []))
        return detail

    def seed_demo(self, context: RequestContext, recorded_at: datetime) -> int:
        now = _utc_iso(recorded_at)
        seeds = [
            (
                "inc_demo_north",
                "North Sector water contamination",
                "water_contamination",
                "suspected",
                [91.742, 26.184],
            ),
            (
                "inc_demo_east",
                "East Sector medical access need",
                "medical_need",
                "unassessed",
                [91.756, 26.191],
            ),
            (
                "inc_demo_west",
                "West Sector blocked access",
                "access_blocked",
                "confirmed",
                [91.728, 26.176],
            ),
        ]
        created = 0
        with self._lock:
            for sector_id, name, state, coordinates in [
                ("sector_demo_north", "North Sector", "assessed", [91.73, 26.18]),
                ("sector_demo_east", "East Sector", "unassessed", [91.75, 26.19]),
                ("sector_demo_west", "West Sector", "inaccessible", [91.72, 26.17]),
            ]:
                self._sectors.setdefault(
                    sector_id,
                    {
                        "id": sector_id,
                        "name": name,
                        "assessment_state": state,
                        "assessment_source": "synthetic_demo_seed",
                        "assessed_at": now if state == "assessed" else None,
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [coordinates[0] - 0.01, coordinates[1] - 0.01],
                                    [coordinates[0] + 0.01, coordinates[1] - 0.01],
                                    [coordinates[0] + 0.01, coordinates[1] + 0.01],
                                    [coordinates[0] - 0.01, coordinates[1] + 0.01],
                                    [coordinates[0] - 0.01, coordinates[1] - 0.01],
                                ]
                            ],
                        },
                        "tenant_id": context.tenant_id,
                        "workspace_id": context.workspace_id,
                    },
                )
            for incident_id, title, need_type, state, coordinates in seeds:
                if incident_id in self._incidents:
                    continue
                self._incidents[incident_id] = {
                    "id": incident_id,
                    "tenant_id": context.tenant_id,
                    "workspace_id": context.workspace_id,
                    "title": title,
                    "need_type": need_type,
                    "verification_state": state,
                    "location": {"type": "Point", "coordinates": coordinates},
                    "source": "synthetic_demo_seed",
                    "observed_at": now,
                }
                created += 1
        return created

    def map_features(
        self, context: RequestContext, limit: int, bbox: tuple[float, float, float, float] | None
    ) -> dict[str, Any]:
        incidents = [
            value
            for value in self._incidents.values()
            if value["tenant_id"] == context.tenant_id
            and value["workspace_id"] == context.workspace_id
        ]
        reports = [
            value
            for value in self._reports.values()
            if value["tenant_id"] == context.tenant_id
            and value["workspace_id"] == context.workspace_id
        ]
        sectors = [
            value
            for value in self._sectors.values()
            if value["tenant_id"] == context.tenant_id
            and value["workspace_id"] == context.workspace_id
        ]
        return _feature_collection(incidents, reports, limit, bbox, sectors)

    def review_report(
        self, context: RequestContext, report_id: str, review: EvidenceReview, reviewed_at: datetime
    ) -> dict[str, Any]:
        record = self._reports.get(report_id)
        if (
            record is None
            or record["tenant_id"] != context.tenant_id
            or record["workspace_id"] != context.workspace_id
        ):
            raise ReportNotFoundError
        claims = {claim["id"]: claim for claim in record["claims"]}
        for claim_id, state in review.claim_updates.items():
            if claim_id not in claims:
                raise ReportNotFoundError
            claims[claim_id]["verification_state"] = state
        record["claims"] = list(claims.values())
        record["status"] = "reviewed"
        record["reviewed_by"] = context.actor_id
        record["reviewed_at"] = _utc_iso(reviewed_at)
        record["review_note"] = review.note
        if self.plan_store:
            for claim_id in review.claim_updates:
                self.plan_store.invalidate_subject(
                    context, "claim", claim_id, "claim_revision", reviewed_at
                )
        return copy.deepcopy(record)

    def link_incident(
        self, context: RequestContext, report_id: str, link: IncidentLink, linked_at: datetime
    ) -> dict[str, Any]:
        report = self._reports.get(report_id)
        incident = self._incidents.get(link.incident_id)
        if report is None or report["workspace_id"] != context.workspace_id:
            raise ReportNotFoundError
        if incident is None or incident["workspace_id"] != context.workspace_id:
            raise IncidentNotFoundError
        self._links.add((report_id, link.incident_id))
        return {
            "report_id": report_id,
            "incident_id": link.incident_id,
            "linked_by": context.actor_id,
            "linked_at": _utc_iso(linked_at),
        }

    def link_command_incident(self, context, report_id, incident_id, linked_at):
        report = self.get_report(context, report_id)
        link = {
            "report_id": report["id"],
            "incident_id": incident_id,
            "linked_by": context.actor_id,
            "linked_at": _utc_iso(linked_at),
        }
        with self._lock:
            links = self._command_links.setdefault(report_id, [])
            if not any(existing["incident_id"] == incident_id for existing in links):
                links.append(link)
        return copy.deepcopy(link)

    def list_incidents(self, context: RequestContext) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(value)
            for value in self._incidents.values()
            if value["workspace_id"] == context.workspace_id
        ]

    def list_sectors(self, context: RequestContext) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(value)
            for value in self._sectors.values()
            if value["workspace_id"] == context.workspace_id
        ]


class PostgreSQLEvidenceStore:
    def __init__(self, database_url: str, plan_store: PlanStore | None = None) -> None:
        self.database_url = database_url
        self.plan_store = plan_store

    def _connection(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor: Any, context: RequestContext, now: datetime) -> None:
        cursor.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (context.tenant_id, "Development demo organization", now),
        )
        cursor.execute(
            "INSERT INTO event_workspaces (id, organization_id, name, mode, status, event_time, created_at) VALUES (%s, %s, %s, 'live', 'active', %s, %s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Development demo event", now, now),
        )
        cursor.execute(
            "INSERT INTO memberships (organization_id, actor_id, role, created_at) VALUES (%s, %s, %s, %s) ON CONFLICT (organization_id, actor_id) DO NOTHING",
            (context.tenant_id, context.actor_id, context.role, now),
        )

    def review_report(
        self, context: RequestContext, report_id: str, review: EvidenceReview, reviewed_at: datetime
    ) -> dict[str, Any]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM raw_reports WHERE id = %s AND organization_id = %s AND workspace_id = %s FOR UPDATE",
                (report_id, context.tenant_id, context.workspace_id),
            )
            if cursor.fetchone() is None:
                raise ReportNotFoundError
            for claim_id, state in review.claim_updates.items():
                cursor.execute(
                    "UPDATE report_claims SET verification_state = %s WHERE id = %s AND report_id = %s AND organization_id = %s AND workspace_id = %s",
                    (state, claim_id, report_id, context.tenant_id, context.workspace_id),
                )
                if cursor.rowcount != 1:
                    raise ReportNotFoundError
            cursor.execute(
                "UPDATE raw_reports SET status = 'reviewed', reviewed_by = %s, reviewed_at = %s, review_note = %s, revision = revision + 1 WHERE id = %s",
                (context.actor_id, reviewed_at, review.note, report_id),
            )
            if self.plan_store:
                for claim_id in review.claim_updates:
                    self.plan_store.invalidate_subject(
                        context, "claim", claim_id, "claim_revision", reviewed_at
                    )
        return self.get_report(context, report_id)

    def link_incident(
        self, context: RequestContext, report_id: str, link: IncidentLink, linked_at: datetime
    ) -> dict[str, Any]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM raw_reports WHERE id = %s AND organization_id = %s AND workspace_id = %s",
                (report_id, context.tenant_id, context.workspace_id),
            )
            if cursor.fetchone() is None:
                raise ReportNotFoundError
            cursor.execute(
                "SELECT 1 FROM synthetic_incidents WHERE id = %s AND organization_id = %s AND workspace_id = %s",
                (link.incident_id, context.tenant_id, context.workspace_id),
            )
            if cursor.fetchone() is None:
                raise IncidentNotFoundError
            cursor.execute(
                "INSERT INTO report_incident_links (report_id, incident_id, organization_id, workspace_id, linked_by, linked_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    report_id,
                    link.incident_id,
                    context.tenant_id,
                    context.workspace_id,
                    context.actor_id,
                    linked_at,
                ),
            )
        return {
            "report_id": report_id,
            "incident_id": link.incident_id,
            "linked_by": context.actor_id,
            "linked_at": _utc_iso(linked_at),
        }

    def link_command_incident(self, context, report_id, incident_id, linked_at):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM raw_reports WHERE id=%s AND organization_id=%s AND workspace_id=%s",
                (report_id, context.tenant_id, context.workspace_id),
            )
            if cursor.fetchone() is None:
                raise ReportNotFoundError
            cursor.execute(
                "INSERT INTO report_command_incident_links (report_id,incident_id,organization_id,workspace_id,linked_by,linked_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    report_id,
                    incident_id,
                    context.tenant_id,
                    context.workspace_id,
                    context.actor_id,
                    linked_at,
                ),
            )
        return {
            "report_id": report_id,
            "incident_id": incident_id,
            "linked_by": context.actor_id,
            "linked_at": _utc_iso(linked_at),
        }

    def list_incidents(self, context: RequestContext) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, need_type, verification_state, location_geojson, source, observed_at FROM synthetic_incidents WHERE organization_id = %s AND workspace_id = %s ORDER BY created_at, id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "id": row[0],
                    "title": row[1],
                    "need_type": row[2],
                    "verification_state": row[3],
                    "location": row[4],
                    "source": row[5],
                    "observed_at": _utc_iso(row[6]),
                }
                for row in cursor.fetchall()
            ]

    def list_sectors(self, context: RequestContext) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, ST_AsGeoJSON(geometry)::jsonb, assessment_state, assessment_source, assessed_at FROM sectors WHERE organization_id = %s AND workspace_id = %s ORDER BY id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "geometry": row[2],
                    "assessment_state": row[3],
                    "assessment_source": row[4],
                    "assessed_at": _utc_iso(row[5]),
                }
                for row in cursor.fetchall()
            ]

    @staticmethod
    def _envelope(
        context: RequestContext,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        recorded_at: datetime,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = _utc_iso(recorded_at)
        return {
            "event_contract_version": 1,
            "event_id": _opaque_id("evt"),
            "event_type": event_type,
            "occurred_at": timestamp,
            "recorded_at": timestamp,
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "aggregate": {"type": aggregate_type, "id": aggregate_id, "revision": 1},
            "actor": {"type": "user", "id": context.actor_id},
            "correlation_id": context.correlation_id,
            "causation_id": None,
            "payload": payload,
        }

    def create_report(
        self, context: RequestContext, report: ReportCreate, recorded_at: datetime
    ) -> tuple[dict[str, Any], bool]:
        payload = report.model_dump(mode="json", exclude_unset=True)
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        normalized = normalize_report(report)
        report_id = _opaque_id("rpt")
        with self._connection() as connection:
            with connection.cursor() as cursor:
                self._ensure_context(cursor, context, recorded_at)
                cursor.execute(
                    "SELECT id, original_sha256 FROM raw_reports WHERE organization_id = %s AND workspace_id = %s AND client_record_id = %s",
                    (context.tenant_id, context.workspace_id, report.client_record_id),
                )
                existing = cursor.fetchone()
                if existing:
                    if existing[1] != digest:
                        raise ReportConflictError
                    return self.get_report(context, existing[0]), True
                cursor.execute(
                    """INSERT INTO raw_reports
                    (id, organization_id, workspace_id, client_record_id, original_payload, original_sha256,
                     source, report_type, privacy_class, observed_at, received_at, recorded_at,
                     location_geojson, location_uncertainty_m, place_text, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        report_id,
                        context.tenant_id,
                        context.workspace_id,
                        report.client_record_id,
                        Jsonb(payload),
                        digest,
                        Jsonb(report.source.model_dump(mode="json")),
                        report.report_type,
                        report.privacy_class,
                        report.observed_at,
                        report.received_at,
                        recorded_at,
                        Jsonb(report.location.geometry) if report.location else None,
                        report.location.uncertainty_m if report.location else None,
                        report.location.place_text if report.location else None,
                        "accepted_for_review",
                        recorded_at,
                    ),
                )
                cursor.execute(
                    "INSERT INTO normalization_runs (id, organization_id, workspace_id, report_id, mapping_version, taxonomy_version, status, warnings, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        normalized["id"],
                        context.tenant_id,
                        context.workspace_id,
                        report_id,
                        normalized["mapping_version"],
                        normalized["taxonomy_version"],
                        normalized["status"],
                        Jsonb(normalized["warnings"]),
                        recorded_at,
                    ),
                )
                for claim in normalized["claims"]:
                    cursor.execute(
                        "INSERT INTO report_claims (id, organization_id, workspace_id, report_id, normalization_run_id, claim_type, value, verification_state, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            claim["id"],
                            context.tenant_id,
                            context.workspace_id,
                            report_id,
                            normalized["id"],
                            claim["claim_type"],
                            Jsonb(claim["value"]) if claim["value"] is not None else None,
                            claim["verification_state"],
                            recorded_at,
                        ),
                    )
                if report.location:
                    longitude, latitude = report.location.geometry["coordinates"]
                    cursor.execute(
                        "INSERT INTO report_locations (report_id, organization_id, workspace_id, geometry, created_at) VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)",
                        (
                            report_id,
                            context.tenant_id,
                            context.workspace_id,
                            longitude,
                            latitude,
                            recorded_at,
                        ),
                    )
                    cursor.execute(
                        "SELECT id FROM raw_reports WHERE organization_id = %s AND workspace_id = %s AND report_type = %s AND id <> %s AND id IN (SELECT report_id FROM report_locations WHERE ST_DWithin(geometry, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 0.001))",
                        (
                            context.tenant_id,
                            context.workspace_id,
                            report.report_type,
                            report_id,
                            longitude,
                            latitude,
                        ),
                    )
                    for (candidate_id,) in cursor.fetchall():
                        cursor.execute(
                            "INSERT INTO duplicate_candidates (id, organization_id, workspace_id, report_id, candidate_report_id, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                            (
                                _opaque_id("dup"),
                                context.tenant_id,
                                context.workspace_id,
                                report_id,
                                candidate_id,
                                "same report type and nearby location",
                                recorded_at,
                            ),
                        )
                envelope = self._envelope(
                    context,
                    "report.accepted",
                    "report",
                    report_id,
                    recorded_at,
                    {"report_id": report_id, "revision": 1},
                )
                PostgreSQLOperationsStore._audit(
                    cursor,
                    context,
                    "report.accepted",
                    "report",
                    report_id,
                    {"warnings": normalized["warnings"]},
                    recorded_at,
                )
                cursor.execute(
                    "INSERT INTO outbox_events (id, organization_id, workspace_id, event_type, aggregate_type, aggregate_id, aggregate_revision, envelope, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        envelope["event_id"],
                        context.tenant_id,
                        context.workspace_id,
                        envelope["event_type"],
                        "report",
                        report_id,
                        1,
                        Jsonb(envelope),
                        recorded_at,
                    ),
                )
        return self.get_report(context, report_id), False

    def list_reports(
        self, context: RequestContext, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        marker = _cursor_decode(cursor)
        where = "organization_id = %s AND workspace_id = %s"
        params: list[Any] = [context.tenant_id, context.workspace_id]
        if marker:
            where += " AND (recorded_at, id) < (%s, %s)"
            params.extend(marker)
        params.append(limit + 1)
        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    f"SELECT id, client_record_id, report_type, status, source, observed_at, received_at, recorded_at, location_geojson, location_uncertainty_m, place_text, revision FROM raw_reports WHERE {where} ORDER BY recorded_at DESC, id DESC LIMIT %s",
                    params,
                )
                rows = cursor_obj.fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            {
                "id": row[0],
                "client_record_id": row[1],
                "report_type": row[2],
                "status": row[3],
                "source": row[4],
                "observed_at": _utc_iso(row[5]),
                "received_at": _utc_iso(row[6]),
                "recorded_at": _utc_iso(row[7]),
                "location": {"geometry": row[8], "uncertainty_m": row[9], "place_text": row[10]}
                if row[8]
                else None,
                "warnings": [],
                "revision": row[11],
            }
            for row in rows
        ]
        next_cursor = (
            _cursor_encode(items[-1]["recorded_at"], items[-1]["id"])
            if has_more and items
            else None
        )
        return items, next_cursor

    def get_report(self, context: RequestContext, report_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, client_record_id, original_payload, original_sha256, source, report_type, privacy_class, observed_at, received_at, recorded_at, location_geojson, location_uncertainty_m, place_text, status, revision FROM raw_reports WHERE id = %s AND organization_id = %s AND workspace_id = %s",
                    (report_id, context.tenant_id, context.workspace_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ReportNotFoundError
                cursor.execute(
                    "SELECT id, claim_type, value, verification_state, normalization_run_id FROM report_claims WHERE report_id = %s ORDER BY created_at, id",
                    (report_id,),
                )
                claims = [
                    {
                        "id": item[0],
                        "claim_type": item[1],
                        "value": item[2],
                        "verification_state": item[3],
                        "normalization_run_id": item[4],
                    }
                    for item in cursor.fetchall()
                ]
                cursor.execute(
                    "SELECT id, mapping_version, taxonomy_version, status, warnings FROM normalization_runs WHERE report_id = %s ORDER BY created_at DESC LIMIT 1",
                    (report_id,),
                )
                normalization = cursor.fetchone()
                cursor.execute(
                    "SELECT candidate_report_id, reason FROM duplicate_candidates WHERE report_id = %s ORDER BY created_at, id",
                    (report_id,),
                )
                duplicate_candidates = [
                    {"candidate_report_id": item[0], "reason": item[1]}
                    for item in cursor.fetchall()
                ]
                cursor.execute(
                    "SELECT incident_id, linked_by, linked_at FROM report_command_incident_links WHERE report_id=%s ORDER BY linked_at, incident_id",
                    (report_id,),
                )
                command_incident_links = [
                    {
                        "report_id": report_id,
                        "incident_id": item[0],
                        "linked_by": item[1],
                        "linked_at": _utc_iso(item[2]),
                    }
                    for item in cursor.fetchall()
                ]
        return {
            "id": row[0],
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "client_record_id": row[1],
            "original_payload": row[2],
            "original_sha256": row[3],
            "source": row[4],
            "report_type": row[5],
            "privacy_class": row[6],
            "observed_at": _utc_iso(row[7]),
            "received_at": _utc_iso(row[8]),
            "recorded_at": _utc_iso(row[9]),
            "location": {"geometry": row[10], "uncertainty_m": row[11], "place_text": row[12]}
            if row[10]
            else None,
            "status": row[13],
            "revision": row[14],
            "warnings": normalization[4] if normalization else [],
            "normalization": {
                "id": normalization[0],
                "mapping_version": normalization[1],
                "taxonomy_version": normalization[2],
                "status": normalization[3],
                "warnings": normalization[4],
            }
            if normalization
            else None,
            "claims": claims,
            "duplicate_candidates": duplicate_candidates,
            "command_incident_links": command_incident_links,
        }

    def seed_demo(self, context: RequestContext, recorded_at: datetime) -> int:
        seeds = [
            (
                "inc_demo_north",
                "North Sector water contamination",
                "water_contamination",
                "suspected",
                [91.742, 26.184],
            ),
            (
                "inc_demo_east",
                "East Sector medical access need",
                "medical_need",
                "unassessed",
                [91.756, 26.191],
            ),
            (
                "inc_demo_west",
                "West Sector blocked access",
                "access_blocked",
                "confirmed",
                [91.728, 26.176],
            ),
        ]
        created = 0
        with self._connection() as connection:
            with connection.cursor() as cursor:
                self._ensure_context(cursor, context, recorded_at)
                for sector_id, name, state, longitude, latitude in [
                    ("sector_demo_north", "North Sector", "assessed", 91.73, 26.18),
                    ("sector_demo_east", "East Sector", "unassessed", 91.75, 26.19),
                    ("sector_demo_west", "West Sector", "inaccessible", 91.72, 26.17),
                ]:
                    cursor.execute(
                        "INSERT INTO sectors (id, organization_id, workspace_id, name, geometry, assessment_state, assessment_source, assessed_at) VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePolygon(ST_GeomFromText(%s)), 4326), %s, 'synthetic_demo_seed', %s) ON CONFLICT (id) DO NOTHING",
                        (
                            sector_id,
                            context.tenant_id,
                            context.workspace_id,
                            name,
                            f"LINESTRING({longitude - 0.01} {latitude - 0.01}, {longitude + 0.01} {latitude - 0.01}, {longitude + 0.01} {latitude + 0.01}, {longitude - 0.01} {latitude + 0.01}, {longitude - 0.01} {latitude - 0.01})",
                            state,
                            recorded_at if state == "assessed" else None,
                        ),
                    )
                for incident_id, title, need_type, state, coordinates in seeds:
                    cursor.execute(
                        "INSERT INTO synthetic_incidents (id, organization_id, workspace_id, title, need_type, verification_state, location_geojson, source, observed_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                        (
                            incident_id,
                            context.tenant_id,
                            context.workspace_id,
                            title,
                            need_type,
                            state,
                            Jsonb({"type": "Point", "coordinates": coordinates}),
                            "synthetic_demo_seed",
                            recorded_at,
                            recorded_at,
                        ),
                    )
                    created += cursor.rowcount
                    cursor.execute(
                        "INSERT INTO incident_locations (incident_id, organization_id, workspace_id, geometry, created_at) VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s) ON CONFLICT (incident_id) DO NOTHING",
                        (
                            incident_id,
                            context.tenant_id,
                            context.workspace_id,
                            coordinates[0],
                            coordinates[1],
                            recorded_at,
                        ),
                    )
        return created

    def map_features(
        self, context: RequestContext, limit: int, bbox: tuple[float, float, float, float] | None
    ) -> dict[str, Any]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT i.id, i.title, i.need_type, i.verification_state, i.location_geojson, i.source, i.observed_at FROM synthetic_incidents i JOIN incident_locations l ON l.incident_id = i.id WHERE i.organization_id = %s AND i.workspace_id = %s AND (%s OR ST_Intersects(l.geometry, ST_MakeEnvelope(%s, %s, %s, %s, 4326))) ORDER BY i.created_at, i.id LIMIT 100",
                    (
                        context.tenant_id,
                        context.workspace_id,
                        bbox is None,
                        *(bbox or (0, 0, 0, 0)),
                    ),
                )
                incidents = [
                    {
                        "id": row[0],
                        "title": row[1],
                        "need_type": row[2],
                        "verification_state": row[3],
                        "location": row[4],
                        "source": row[5],
                        "observed_at": _utc_iso(row[6]),
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    "SELECT r.id, r.report_type, r.status, r.source, r.observed_at, r.recorded_at, r.location_geojson, r.location_uncertainty_m FROM raw_reports r LEFT JOIN report_locations l ON l.report_id = r.id WHERE r.organization_id = %s AND r.workspace_id = %s AND (%s OR ST_Intersects(l.geometry, ST_MakeEnvelope(%s, %s, %s, %s, 4326))) ORDER BY r.recorded_at DESC, r.id DESC LIMIT 100",
                    (
                        context.tenant_id,
                        context.workspace_id,
                        bbox is None,
                        *(bbox or (0, 0, 0, 0)),
                    ),
                )
                reports = [
                    {
                        "id": row[0],
                        "report_type": row[1],
                        "status": row[2],
                        "source": row[3],
                        "observed_at": _utc_iso(row[4]),
                        "recorded_at": _utc_iso(row[5]),
                        "location": {"geometry": row[6], "uncertainty_m": row[7]}
                        if row[6]
                        else None,
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    "SELECT id, name, ST_AsGeoJSON(geometry)::jsonb, assessment_state, assessment_source, assessed_at FROM sectors WHERE organization_id = %s AND workspace_id = %s AND (%s OR ST_Intersects(geometry, ST_MakeEnvelope(%s, %s, %s, %s, 4326))) ORDER BY id",
                    (
                        context.tenant_id,
                        context.workspace_id,
                        bbox is None,
                        *(bbox or (0, 0, 0, 0)),
                    ),
                )
                sectors = [
                    {
                        "id": row[0],
                        "name": row[1],
                        "geometry": row[2],
                        "assessment_state": row[3],
                        "assessment_source": row[4],
                        "assessed_at": _utc_iso(row[5]),
                    }
                    for row in cursor.fetchall()
                ]
        return _feature_collection(incidents, reports, limit, bbox, sectors)
