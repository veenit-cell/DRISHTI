# ruff: noqa: E501

from datetime import UTC, datetime

import pytest

from app.import_export import ImportRequest, export_redacted_csv, export_sitrep, import_fixture

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def csv_request(content):
    return ImportRequest(kind="csv", content=content, schema_version="1", mapping_version="map1", provenance="synthetic_fixture", tenant_id="t1", workspace_id="w1", replay_at=NOW)


def test_partial_csv_failure_and_idempotent_reimport():
    content = "id,event_time,report_type\n1,2026-08-30T11:00:00Z,water\n2,bad-time,power\n3,2026-08-31T11:00:00Z,future"
    first = import_fixture(csv_request(content))
    second = import_fixture(csv_request(content))
    assert len(first.accepted_commands) == 1 and len(first.quarantined) == 2
    assert first.import_hash == second.import_hash and first.quarantined[0]["original"]["id"] == "2"


def test_oversized_and_geojson_validation():
    with pytest.raises(ValueError, match="bytes"):
        csv_request("x" * 1_000_001)
    invalid = ImportRequest(kind="geojson", content='{"type":"FeatureCollection","features":[{"geometry":{"type":"Polygon"}}]}', schema_version="1", mapping_version="m", provenance="fixture", tenant_id="t1", workspace_id="w1", replay_at=NOW)
    result = import_fixture(invalid)
    assert result.quarantined and "Point or LineString" in result.quarantined[0]["reason"]


def test_redaction_formula_safety_and_deterministic_sitrep():
    exported = export_redacted_csv([{"id": "1", "person_name": "secret", "value": "=SUM(A1)", "tenant_id": "t1"}], "t1", "w1")
    assert "secret" not in exported and "'=SUM" in exported
    rows = [{"event_time": "2026-08-30T11:00:00Z", "report_type": "water"}, {"event_time": "2026-08-31T11:00:00Z", "report_type": "future"}]
    first, second = export_sitrep(rows, NOW), export_sitrep(rows, NOW)
    assert first == second and first["reports"] == 1 and "future" not in first["by_type"]
