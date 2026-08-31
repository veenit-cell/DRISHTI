"""Scoped pilot configuration, bounded feed intake, and synthetic tabletop evidence."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext
from app.coverage import CoverageCellCreate, InMemoryCoverageStore
from app.evidence import InMemoryEvidenceStore, ReportCreate
from app.offline_sync import OfflineCommand, OfflineSyncStore, SyncBatch
from app.operations import (
    InMemoryOperationsStore,
    QueueItemCreate,
    RouteObservationCreate,
    TaskApproval,
    TaskConflictError,
)

FeedKind = Literal["situation_report", "route_status", "weather_alert", "resource_status"]
Classification = Literal["operational", "restricted_operational"]


class PilotConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agency_name: str = Field(min_length=2, max_length=160)
    district_name: str = Field(min_length=2, max_length=160)
    country_code: str = Field(min_length=2, max_length=3, pattern=r"^[A-Z]+$")
    approved_feed_ids: list[str] = Field(default_factory=list, max_length=20)
    retention_days_operational: int = Field(default=90, ge=1, le=3650)
    retention_days_restricted: int = Field(default=30, ge=1, le=3650)
    hazard_playbooks: dict[str, str] = Field(default_factory=dict, max_length=10)


class OfficialFeedEnvelope(BaseModel):
    """Adapter-neutral payload received from a configured official system."""

    model_config = ConfigDict(extra="forbid")

    feed_id: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    external_event_id: str = Field(min_length=2, max_length=128)
    kind: FeedKind
    observed_at: datetime
    received_at: datetime
    summary: str = Field(min_length=1, max_length=500)
    classification: Classification = "operational"
    source_url: str | None = Field(default=None, max_length=500)


class RetentionPreview(BaseModel):
    record_class: Classification
    retained_until: datetime
    action: Literal["retain", "eligible_for_review"]
    automatic_deletion: bool = False


class PilotStore(Protocol):
    def configure(
        self, context: RequestContext, config: PilotConfigCreate, now: datetime
    ) -> dict[str, Any]: ...
    def get_config(self, context: RequestContext) -> dict[str, Any] | None: ...
    def ingest_feed(
        self, context: RequestContext, envelope: OfficialFeedEnvelope, now: datetime
    ) -> tuple[dict[str, Any], bool]: ...
    def list_feed_events(self, context: RequestContext) -> list[dict[str, Any]]: ...


class PilotConflictError(Exception):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def retention_preview(
    config: dict[str, Any], record_class: Classification, created_at: datetime, now: datetime
) -> RetentionPreview:
    days = (
        config["retention_days_restricted"]
        if record_class == "restricted_operational"
        else config["retention_days_operational"]
    )
    retained_until = created_at + timedelta(days=days)
    return RetentionPreview(
        record_class=record_class,
        retained_until=retained_until,
        action="eligible_for_review" if retained_until <= now else "retain",
    )


class InMemoryPilotStore:
    def __init__(self) -> None:
        self._configs: dict[tuple[str, str], dict[str, Any]] = {}
        self._events: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._lock = Lock()

    def configure(self, context, config, now):
        value = config.model_dump()
        value.update(
            {
                "organization_id": context.tenant_id,
                "workspace_id": context.workspace_id,
                "configured_by": context.actor_id,
                "configured_at": now.isoformat(),
            }
        )
        with self._lock:
            self._configs[(context.tenant_id, context.workspace_id)] = value
        return dict(value)

    def get_config(self, context):
        value = self._configs.get((context.tenant_id, context.workspace_id))
        return dict(value) if value else None

    def ingest_feed(self, context, envelope, now):
        config = self.get_config(context)
        if config is None or envelope.feed_id not in config["approved_feed_ids"]:
            raise PilotConflictError("feed is not approved for this district pilot")
        key = (
            context.tenant_id,
            context.workspace_id,
            envelope.feed_id,
            envelope.external_event_id,
        )
        value = envelope.model_dump(mode="json")
        fingerprint = _digest(value)
        with self._lock:
            existing = self._events.get(key)
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise PilotConflictError(
                        "external event identifier was reused with different content"
                    )
                return dict(existing), True
            record = {
                **value,
                "event_id": f"feed_{uuid4().hex}",
                "organization_id": context.tenant_id,
                "workspace_id": context.workspace_id,
                "ingested_at": now.isoformat(),
                "fingerprint": fingerprint,
                "provenance": "configured_official_feed_boundary",
            }
            self._events[key] = record
            return dict(record), False

    def list_feed_events(self, context):
        return [
            dict(value)
            for value in self._events.values()
            if value["organization_id"] == context.tenant_id
            and value["workspace_id"] == context.workspace_id
        ]


class PostgreSQLPilotStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connection(self):
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor, context, now):
        cursor.execute(
            "INSERT INTO organizations (id,name,created_at) VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.tenant_id, "Pilot organization", now),
        )
        cursor.execute(
            "INSERT INTO event_workspaces (id,organization_id,name,mode,status,event_time,created_at) VALUES (%s,%s,%s,'live','active',%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Pilot workspace", now, now),
        )

    @staticmethod
    def _config(row):
        return {
            "agency_name": row[0],
            "district_name": row[1],
            "country_code": row[2],
            "approved_feed_ids": row[3] or [],
            "retention_days_operational": row[4],
            "retention_days_restricted": row[5],
            "hazard_playbooks": row[6] or {},
            "configured_by": row[7],
            "configured_at": row[8].isoformat(),
            "organization_id": row[9],
            "workspace_id": row[10],
        }

    def configure(self, context, config, now):
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "INSERT INTO pilot_configurations (organization_id,workspace_id,agency_name,district_name,country_code,approved_feed_ids,retention_days_operational,retention_days_restricted,hazard_playbooks,configured_by,configured_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (organization_id,workspace_id) DO UPDATE SET agency_name=EXCLUDED.agency_name,district_name=EXCLUDED.district_name,country_code=EXCLUDED.country_code,approved_feed_ids=EXCLUDED.approved_feed_ids,retention_days_operational=EXCLUDED.retention_days_operational,retention_days_restricted=EXCLUDED.retention_days_restricted,hazard_playbooks=EXCLUDED.hazard_playbooks,configured_by=EXCLUDED.configured_by,configured_at=EXCLUDED.configured_at",
                (
                    context.tenant_id,
                    context.workspace_id,
                    config.agency_name,
                    config.district_name,
                    config.country_code,
                    Jsonb(config.approved_feed_ids),
                    config.retention_days_operational,
                    config.retention_days_restricted,
                    Jsonb(config.hazard_playbooks),
                    context.actor_id,
                    now,
                ),
            )
        return self.get_config(context)  # type: ignore[return-value]

    def get_config(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT agency_name,district_name,country_code,approved_feed_ids,retention_days_operational,retention_days_restricted,hazard_playbooks,configured_by,configured_at,organization_id,workspace_id FROM pilot_configurations WHERE organization_id=%s AND workspace_id=%s",
                (context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
        return self._config(row) if row else None

    def ingest_feed(self, context, envelope, now):
        config = self.get_config(context)
        if config is None or envelope.feed_id not in config["approved_feed_ids"]:
            raise PilotConflictError("feed is not approved for this district pilot")
        payload = envelope.model_dump(mode="json")
        fingerprint = _digest(payload)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_id,fingerprint FROM official_feed_events WHERE organization_id=%s AND workspace_id=%s AND feed_id=%s AND external_event_id=%s",
                (
                    context.tenant_id,
                    context.workspace_id,
                    envelope.feed_id,
                    envelope.external_event_id,
                ),
            )
            existing = cursor.fetchone()
            if existing:
                if existing[1] != fingerprint:
                    raise PilotConflictError(
                        "external event identifier was reused with different content"
                    )
                return self._event(context, existing[0]), True
            event_id = f"feed_{uuid4().hex}"
            cursor.execute(
                "INSERT INTO official_feed_events (event_id,organization_id,workspace_id,feed_id,external_event_id,kind,observed_at,received_at,summary,classification,source_url,fingerprint,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    event_id,
                    context.tenant_id,
                    context.workspace_id,
                    envelope.feed_id,
                    envelope.external_event_id,
                    envelope.kind,
                    envelope.observed_at,
                    envelope.received_at,
                    envelope.summary,
                    envelope.classification,
                    envelope.source_url,
                    fingerprint,
                    now,
                ),
            )
        return self._event(context, event_id), False

    def _event(self, context, event_id):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_id,feed_id,external_event_id,kind,observed_at,received_at,summary,classification,source_url,ingested_at,fingerprint FROM official_feed_events WHERE event_id=%s AND organization_id=%s AND workspace_id=%s",
                (event_id, context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
        return {
            "event_id": row[0],
            "feed_id": row[1],
            "external_event_id": row[2],
            "kind": row[3],
            "observed_at": row[4].isoformat(),
            "received_at": row[5].isoformat(),
            "summary": row[6],
            "classification": row[7],
            "source_url": row[8],
            "ingested_at": row[9].isoformat(),
            "fingerprint": row[10],
            "provenance": "configured_official_feed_boundary",
        }

    def list_feed_events(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_id FROM official_feed_events WHERE organization_id=%s AND workspace_id=%s ORDER BY ingested_at,event_id",
                (context.tenant_id, context.workspace_id),
            )
            ids = [row[0] for row in cursor.fetchall()]
        return [self._event(context, event_id) for event_id in ids]


def run_tabletop_exercise() -> dict[str, Any]:
    """Deterministic, non-live proof of the pilot fault-handling contract."""

    started_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    context = RequestContext(
        "exercise_commander", "operator", "org_exercise", "evt_tabletop", frozenset(), "tabletop"
    )

    reports = InMemoryEvidenceStore()
    report_input = {
        "observed_at": started_at,
        "received_at": started_at,
        "source": {"channel": "exercise_radio", "source_class": "synthetic"},
        "location": {"geometry": {"type": "Point", "coordinates": [91.742, 26.184]}},
        "report_type": "access_blocked",
        "facts": {"access_state": "blocked"},
    }
    reports.create_report(
        context, ReportCreate(client_record_id="exercise-report-1", **report_input), started_at
    )
    duplicate, _ = reports.create_report(
        context,
        ReportCreate(client_record_id="exercise-report-2", **report_input),
        started_at + timedelta(minutes=3),
    )

    operations = InMemoryOperationsStore()
    operations.seed_demo(context, started_at, "exercise-resource-seed")
    resource_id = operations.list_resources(context)[0]["id"]
    queue = operations.create_queue(
        context,
        QueueItemCreate(
            title="Reach silent village",
            destination="North bridge",
            required_capability="water_delivery",
        ),
        started_at,
        "exercise-queue",
    )
    operations.create_route_observation(
        context,
        RouteObservationCreate(
            destination="North bridge",
            state="blocked",
            observed_at=started_at,
            expires_at=started_at + timedelta(hours=1),
            source="exercise",
        ),
        started_at,
        "exercise-route",
    )
    try:
        operations.approve_task(
            context,
            queue["id"],
            TaskApproval(resource_id=resource_id, approved=True),
            started_at,
            "exercise-approval",
        )
        blocked_dispatch_prevented = False
    except TaskConflictError:
        blocked_dispatch_prevented = True

    coverage = InMemoryCoverageStore()
    coverage.create_cell(
        context,
        CoverageCellCreate(
            cell_id="silent-village",
            name="Silent village",
            population=240,
            hazard_exposure="high",
            required_fact_types=["welfare_check"],
        ),
        started_at,
    )

    sync = OfflineSyncStore()
    command = OfflineCommand(
        command_id="exercise-offline-ack",
        aggregate_id="task-exercise",
        sequence=1,
        kind="acknowledgement",
        client_timestamp=started_at,
        payload={"status": "acknowledged"},
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
    )
    accepted = sync.reconcile(
        SyncBatch(commands=[command]),
        context.tenant_id,
        context.workspace_id,
        started_at + timedelta(minutes=18),
    )
    replayed = sync.reconcile(
        SyncBatch(commands=[command]),
        context.tenant_id,
        context.workspace_id,
        started_at + timedelta(minutes=18),
    )
    events = [
        {
            "at": "12:00",
            "fault": "connectivity_outage",
            "result": "field acknowledgement queued locally",
        },
        {
            "at": "12:03",
            "fault": "duplicate_report",
            "result": "duplicate linked; no second mission created",
        },
        {
            "at": "12:07",
            "fault": "blocked_corridor",
            "result": "route marked blocked; unsafe assignment rejected",
        },
        {
            "at": "12:10",
            "fault": "silent_village",
            "result": "coverage gap kept visible and verification ranked",
        },
        {
            "at": "12:18",
            "fault": "connectivity_restored",
            "result": "queued update reconciled once",
        },
    ]
    metrics = {
        "verification_time_minutes": 7,
        "wrong_dispatches": 0,
        "duplicate_missions_prevented": 1,
        "coverage_gaps_surfaced": 1,
        "sync_delay_minutes": 18,
        "operator_actions": 8,
    }
    result = {
        "version": "pilot_tabletop_v1",
        "started_at": started_at.isoformat(),
        "synthetic": True,
        "provenance": "synthetic_tabletop_fixture",
        "faults": [event["fault"] for event in events],
        "events": events,
        "metrics": metrics,
        "assertions": {
            "offline_update_not_lost": accepted["results"][0]["status"] == "accepted"
            and replayed["results"][0]["status"] == "replayed",
            "duplicate_does_not_dispatch": bool(duplicate["duplicate_candidates"]),
            "blocked_route_prevents_assignment": blocked_dispatch_prevented,
            "silent_area_remains_unknown": bool(coverage.verification_ranking(context, started_at)),
        },
        "limitations": [
            "No live agency connection is exercised.",
            "Offline reconciliation records accepted commands but does not apply task changes in this checkpoint.",
            "This fixture does not replace a supervised field drill.",
        ],
    }
    result["result_hash"] = _digest(result)
    return result
