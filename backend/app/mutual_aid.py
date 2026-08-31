# ruff: noqa: E501

"""Deterministic resource forecasts and commander-gated mutual-aid drafts."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: str = Field(min_length=1, max_length=80)
    current_quantity: float = Field(ge=0)
    consumption_per_hour: float = Field(ge=0)
    replenishment_per_hour: float = Field(default=0, ge=0)
    reserve_floor: float = Field(ge=0)
    forecast_window_hours: float = Field(gt=0, le=168)
    lead_time_hours: float = Field(default=0, ge=0, le=168)
    location: str = Field(min_length=1, max_length=120)


class ResourceForecast(BaseModel):
    formula_version: str = "resource_forecast_v1"
    resource_type: str
    current_quantity: float
    projected_quantity: float
    reserve_floor: float
    net_depletion_per_hour: float
    hours_to_reserve: float | None
    forecast_window_hours: float
    lead_time_hours: float
    shortage_window_bucket: str | None
    request_recommended: bool
    location: str


class MutualAidRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0)
    reserve_floor: float = Field(ge=0)
    location: str = Field(min_length=1, max_length=120)
    need_by: datetime
    forecast_hash: str = Field(min_length=1, max_length=128)
    shortage_window_bucket: str = Field(min_length=1, max_length=80)
    source_reality: str = Field(default="synthetic", pattern="^(synthetic)$")


class MutualAidApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    approval_note: str | None = Field(default=None, max_length=500)


class MutualAidNotFoundError(Exception):
    pass


class MutualAidConflictError(Exception):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def compute_forecast(request: ForecastRequest) -> ResourceForecast:
    net = request.consumption_per_hour - request.replenishment_per_hour
    projected = max(0.0, request.current_quantity - net * request.forecast_window_hours)
    available = request.current_quantity - request.reserve_floor
    hours_to_reserve = None if net <= 0 else round(max(0.0, available) / net, 6)
    request_recommended = (
        net > 0
        and available <= net * (request.forecast_window_hours + request.lead_time_hours)
        and hours_to_reserve is not None
        and hours_to_reserve <= request.forecast_window_hours + request.lead_time_hours
    )
    bucket = None
    if request_recommended and hours_to_reserve is not None:
        bucket = f"{int(hours_to_reserve * 4) / 4:.2f}h"
    return ResourceForecast(
        resource_type=request.resource_type,
        current_quantity=request.current_quantity,
        projected_quantity=round(projected, 6),
        reserve_floor=request.reserve_floor,
        net_depletion_per_hour=round(net, 6),
        hours_to_reserve=hours_to_reserve,
        forecast_window_hours=request.forecast_window_hours,
        lead_time_hours=request.lead_time_hours,
        shortage_window_bucket=bucket,
        request_recommended=request_recommended,
        location=request.location,
    )


def draft_mutual_aid_request(
    forecast: ResourceForecast, request: ForecastRequest, now: datetime
) -> dict[str, Any] | None:
    if not forecast.request_recommended or forecast.shortage_window_bucket is None:
        return None
    quantity = max(0.0, request.reserve_floor - forecast.projected_quantity)
    return {
        "resource_type": request.resource_type,
        "quantity": round(quantity, 6),
        "reserve_floor": request.reserve_floor,
        "location": request.location,
        "need_by": _iso(
            (now + timedelta(hours=forecast.hours_to_reserve or 0)).replace(microsecond=0)
        ),
        "shortage_window_bucket": forecast.shortage_window_bucket,
        "forecast_hash": _hash(forecast.model_dump(mode="json")),
        "source_reality": "synthetic",
    }


class MutualAidStore(Protocol):
    def create_forecast(
        self, context: RequestContext, request: ForecastRequest, now: datetime
    ) -> dict[str, Any]: ...

    def list_forecasts(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def create_request(
        self, context: RequestContext, request: MutualAidRequestCreate, now: datetime
    ) -> dict[str, Any]: ...

    def list_requests(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def approve_request(
        self,
        context: RequestContext,
        request_id: str,
        approval: MutualAidApproval,
        now: datetime,
    ) -> dict[str, Any]: ...


class InMemoryMutualAidStore:
    def __init__(self) -> None:
        self.forecasts: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.requests: dict[tuple[str, str, str], dict[str, Any]] = {}

    def create_forecast(self, context, request, now):
        forecast = compute_forecast(request).model_dump(mode="json")
        forecast.update(
            forecast_id=f"forecast_{uuid4().hex}",
            organization_id=context.tenant_id,
            workspace_id=context.workspace_id,
            created_at=_iso(now),
        )
        self.forecasts[(context.tenant_id, context.workspace_id, forecast["forecast_id"])] = (
            forecast
        )
        return copy.deepcopy(forecast)

    def list_forecasts(self, context):
        return copy.deepcopy(
            [
                item
                for item in self.forecasts.values()
                if item["organization_id"] == context.tenant_id
                and item["workspace_id"] == context.workspace_id
            ]
        )

    def create_request(self, context, request, now):
        key = (
            context.tenant_id,
            context.workspace_id,
            f"{request.resource_type}:{request.shortage_window_bucket}:{request.reserve_floor}",
        )
        existing = next(
            (
                item
                for item in self.requests.values()
                if item.get("dedupe_key") == key[2] and item["workspace_id"] == context.workspace_id
            ),
            None,
        )
        if existing:
            return copy.deepcopy(existing)
        record = {
            "request_id": f"request_{uuid4().hex}",
            "organization_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            **request.model_dump(mode="json"),
            "dedupe_key": key[2],
            "status": "draft",
            "source_reality": "synthetic",
            "approved_by": None,
            "approved_at": None,
            "approval_note": None,
            "created_at": _iso(now),
        }
        self.requests[(context.tenant_id, context.workspace_id, record["request_id"])] = record
        return copy.deepcopy(record)

    def list_requests(self, context):
        return copy.deepcopy(
            [
                item
                for item in self.requests.values()
                if item["organization_id"] == context.tenant_id
                and item["workspace_id"] == context.workspace_id
            ]
        )

    def approve_request(self, context, request_id, approval, now):
        record = self.requests.get((context.tenant_id, context.workspace_id, request_id))
        if record is None:
            raise MutualAidNotFoundError
        if record["status"] != "draft":
            raise MutualAidConflictError("mutual-aid request is no longer a draft")
        if not approval.approved:
            record["status"] = "rejected"
        else:
            record["status"] = "submitted"
        record["approved_by"] = context.actor_id
        record["approved_at"] = _iso(now)
        record["approval_note"] = approval.approval_note
        record["export"] = {
            "resource_type": record["resource_type"],
            "quantity": record["quantity"],
            "location": record["location"],
            "need_by": record["need_by"],
            "source_reality": "synthetic",
        }
        return copy.deepcopy(record)


class PostgreSQLMutualAidStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connection(self):
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor, context, now):
        cursor.execute(
            "INSERT INTO organizations (id,name,created_at) VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.tenant_id, "Development demo organization", now),
        )
        cursor.execute(
            "INSERT INTO event_workspaces (id,organization_id,name,mode,status,event_time,created_at) VALUES (%s,%s,%s,'replay','active',%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Development demo event", now, now),
        )

    def create_forecast(self, context, request, now):
        forecast = compute_forecast(request).model_dump(mode="json")
        forecast.update(forecast_id=f"forecast_{uuid4().hex}", created_at=_iso(now))
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "INSERT INTO resource_forecasts (forecast_id,organization_id,workspace_id,resource_type,request,forecast,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    forecast["forecast_id"],
                    context.tenant_id,
                    context.workspace_id,
                    request.resource_type,
                    Jsonb(request.model_dump(mode="json")),
                    Jsonb(forecast),
                    now,
                ),
            )
        return {
            "forecast_id": forecast["forecast_id"],
            **forecast,
            "organization_id": context.tenant_id,
            "workspace_id": context.workspace_id,
        }

    def list_forecasts(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT forecast_id,forecast,created_at FROM resource_forecasts WHERE organization_id=%s AND workspace_id=%s ORDER BY created_at,forecast_id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {"forecast_id": row[0], **row[1], "created_at": _iso(row[2])}
                for row in cursor.fetchall()
            ]

    def create_request(self, context, request, now):
        dedupe_key = (
            f"{request.resource_type}:{request.shortage_window_bucket}:{request.reserve_floor}"
        )
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "SELECT request_id,resource_type,quantity,reserve_floor,location,need_by,forecast_hash,shortage_window_bucket,status,source_reality,approved_by,approved_at,approval_note,created_at FROM resource_requests WHERE organization_id=%s AND workspace_id=%s AND dedupe_key=%s",
                (context.tenant_id, context.workspace_id, dedupe_key),
            )
            row = cursor.fetchone()
            if row:
                return self._row(row)
            request_id = f"request_{uuid4().hex}"
            cursor.execute(
                "INSERT INTO resource_requests (request_id,organization_id,workspace_id,resource_type,quantity,reserve_floor,location,need_by,forecast_hash,shortage_window_bucket,dedupe_key,status,source_reality,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft','synthetic',%s)",
                (
                    request_id,
                    context.tenant_id,
                    context.workspace_id,
                    request.resource_type,
                    request.quantity,
                    request.reserve_floor,
                    request.location,
                    request.need_by,
                    request.forecast_hash,
                    request.shortage_window_bucket,
                    dedupe_key,
                    now,
                ),
            )
            return {
                "request_id": request_id,
                **request.model_dump(mode="json"),
                "dedupe_key": dedupe_key,
                "status": "draft",
                "source_reality": "synthetic",
                "created_at": _iso(now),
                "approved_by": None,
                "approved_at": None,
                "approval_note": None,
            }

    @staticmethod
    def _row(row):
        return {
            "request_id": str(row[0]),
            "resource_type": row[1],
            "quantity": row[2],
            "reserve_floor": row[3],
            "location": row[4],
            "need_by": _iso(row[5]),
            "forecast_hash": row[6],
            "shortage_window_bucket": row[7],
            "status": row[8],
            "source_reality": row[9],
            "approved_by": row[10],
            "approved_at": _iso(row[11]),
            "approval_note": row[12],
            "created_at": _iso(row[13]),
        }

    def list_requests(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT request_id,resource_type,quantity,reserve_floor,location,need_by,forecast_hash,shortage_window_bucket,status,source_reality,approved_by,approved_at,approval_note,created_at FROM resource_requests WHERE organization_id=%s AND workspace_id=%s ORDER BY created_at,request_id",
                (context.tenant_id, context.workspace_id),
            )
            return [self._row(row) for row in cursor.fetchall()]

    def approve_request(self, context, request_id, approval, now):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT request_id,resource_type,quantity,reserve_floor,location,need_by,forecast_hash,shortage_window_bucket,status,source_reality,approved_by,approved_at,approval_note,created_at FROM resource_requests WHERE request_id=%s AND organization_id=%s AND workspace_id=%s FOR UPDATE",
                (request_id, context.tenant_id, context.workspace_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise MutualAidNotFoundError
            if row[8] != "draft":
                raise MutualAidConflictError("mutual-aid request is no longer a draft")
            status = "submitted" if approval.approved else "rejected"
            cursor.execute(
                "UPDATE resource_requests SET status=%s,approved_by=%s,approved_at=%s,approval_note=%s WHERE request_id=%s",
                (status, context.actor_id, now, approval.approval_note, request_id),
            )
            result = self._row(
                (*row[:8], status, row[9], context.actor_id, now, approval.approval_note, row[13])
            )
            result["export"] = {
                "resource_type": result["resource_type"],
                "quantity": result["quantity"],
                "location": result["location"],
                "need_by": result["need_by"],
                "source_reality": "synthetic",
            }
            return result
