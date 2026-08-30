"""Bounded CSV/GeoJSON fixture import and redacted export adapters."""
# ruff: noqa: E501, UP038

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BYTES, MAX_ROWS, MAX_FEATURES, MAX_GEOMETRY_DEPTH = 1_000_000, 100, 100, 4


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["csv", "geojson"]
    content: str
    schema_version: str = Field(min_length=1, max_length=40)
    mapping_version: str = Field(min_length=1, max_length=40)
    provenance: str = Field(min_length=1, max_length=200)
    tenant_id: str
    workspace_id: str
    replay_at: datetime

    @model_validator(mode="after")
    def bounded_content(self) -> ImportRequest:
        if len(self.content.encode()) > MAX_BYTES:
            raise ValueError("fixture exceeds maximum bytes")
        return self


class ImportResult(BaseModel):
    schema_version: str
    mapping_version: str
    provenance: str
    accepted_commands: list[dict[str, Any]]
    quarantined: list[dict[str, Any]]
    import_hash: str


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _command(request: ImportRequest, index: int, row: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(row.get("id") or f"row-{index}")
    return {"command_id": _hash({"import": request.mapping_version, "row": row})[:32], "aggregate_id": raw_id, "kind": "report", "client_timestamp": row.get("event_time"), "payload": row, "tenant_id": request.tenant_id, "workspace_id": request.workspace_id}


def import_fixture(request: ImportRequest) -> ImportResult:
    accepted, quarantined = [], []
    if request.kind == "csv":
        reader = csv.DictReader(io.StringIO(request.content))
        for index, row in enumerate(reader, 1):
            if index > MAX_ROWS:
                quarantined.append({"row": index, "reason": "row limit exceeded", "original": dict(row)})
                continue
            try:
                timestamp = datetime.fromisoformat(str(row.get("event_time", "")).replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp > request.replay_at.astimezone(UTC):
                    raise ValueError("event timestamp is invalid or in the future")
                accepted.append(_command(request, index, dict(row)))
            except (TypeError, ValueError) as exc:
                quarantined.append({"row": index, "reason": str(exc), "original": dict(row)})
    else:
        try:
            document = json.loads(request.content)
            if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
                raise ValueError("expected GeoJSON FeatureCollection")
            for index, feature in enumerate(document["features"], 1):
                if index > MAX_FEATURES:
                    quarantined.append({"row": index, "reason": "feature limit exceeded", "original": feature})
                    continue
                geometry = feature.get("geometry") if isinstance(feature, dict) else None
                if not isinstance(geometry, dict) or geometry.get("type") not in {"Point", "LineString"}:
                    raise ValueError("only Point or LineString geometry is supported")
                if len(json.dumps(geometry)) > 10_000:
                    raise ValueError("geometry complexity exceeds bound")
                properties = feature.get("properties") or {}
                timestamp = datetime.fromisoformat(str(properties.get("event_time", "")).replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp > request.replay_at.astimezone(UTC):
                    raise ValueError("event timestamp is invalid or in the future")
                accepted.append(_command(request, index, {"id": feature.get("id"), "geometry": geometry, **properties}))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            quarantined.append({"row": 1, "reason": str(exc), "original": request.content})
    return ImportResult(schema_version=request.schema_version, mapping_version=request.mapping_version, provenance=request.provenance, accepted_commands=accepted, quarantined=quarantined, import_hash=_hash({"kind": request.kind, "content": request.content, "mapping": request.mapping_version, "provenance": request.provenance}))


def _safe_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in {"=", "+", "-", "@"} else text


def export_redacted_csv(rows: list[dict[str, Any]], tenant_id: str, workspace_id: str) -> str:
    output = io.StringIO()
    fields = sorted({key for row in rows for key in row if key not in {"tenant_id", "workspace_id", "coordinates", "person_name", "phone"}})
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _safe_cell(row.get(key)) for key in fields})
    return output.getvalue()


def export_sitrep(rows: list[dict[str, Any]], replay_at: datetime) -> dict[str, Any]:
    included = [row for row in rows if datetime.fromisoformat(str(row["event_time"]).replace("Z", "+00:00")) <= replay_at.astimezone(UTC)]
    summary = {"reports": len(included), "by_type": {}}
    for row in included:
        kind = str(row.get("report_type", "unknown"))
        summary["by_type"][kind] = summary["by_type"].get(kind, 0) + 1
    summary["summary_hash"] = _hash(summary)
    return summary
