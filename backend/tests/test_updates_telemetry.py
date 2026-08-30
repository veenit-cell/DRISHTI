import base64
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.updates import Telemetry, UpdateFeed


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.api.routes.database_ready", lambda _url: True)
    app = create_app(Settings(app_environment="test", dev_identity_enabled=True))
    return TestClient(app, raise_server_exceptions=False)


def test_feed_cursor_order_scope_and_reconnect() -> None:
    feed = UpdateFeed(max_events=3)
    feed.publish("a", "w", "report.created", {"id": "r1"}, "2026-08-30T00:00:00Z")
    feed.publish("b", "w", "report.created", {"id": "other"}, "2026-08-30T00:00:01Z")
    feed.publish("a", "w", "task.updated", {"id": "t1"}, "2026-08-30T00:00:02Z")
    first = feed.poll("a", "w", None, 1)
    assert [item["event_type"] for item in first["items"]] == ["report.created"]
    resumed = feed.poll("a", "w", first["next_cursor"], 10)
    assert [item["event_type"] for item in resumed["items"]] == ["task.updated"]
    assert feed.poll("b", "w", None)["items"][0]["payload"]["id"] == "other"
    assert feed.poll("a", "w", resumed["next_cursor"])["items"] == []
    with pytest.raises(ValueError):
        feed.poll("a", "w", "not-a-cursor")
    assert feed.poll("a", "w", base64.urlsafe_b64encode(b"0").decode().rstrip("="))["items"]


def test_feed_cursor_survives_bounded_trim_without_duplicates() -> None:
    feed = UpdateFeed(max_events=2)
    for index in range(4):
        feed.publish("a", "w", "changed", {"n": index}, str(index))
    assert [item["cursor"] for item in feed.events] == ["3", "4"]
    assert feed.poll("a", "w", "Mg")["items"][0]["cursor"] == "3"


def test_telemetry_is_low_cardinality_and_redacts_event_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    telemetry = Telemetry()
    telemetry.increment("recommendation_decisions", "approved")
    telemetry.increment("arbitrary-sensitive-name", "token-value")
    snapshot = telemetry.snapshot(queue_depth=5000, job_backlog=4)
    assert "recommendation_decisions:approved" in snapshot["counters"]
    assert "other:other" in snapshot["counters"]
    assert snapshot["queue_depth"] == 1000
    assert snapshot["job_backlog"] == 4
    with caplog.at_level(logging.INFO, logger="drishti.request"):
        caplog.records.clear()
        record = logging.getLogger("drishti.request")
        record.info("request_complete", extra={"method": "GET", "status": 200})
    assert "token-value" not in caplog.text
    assert "raw report" not in caplog.text.lower()


def test_updates_api_requires_scope_and_supports_empty_poll(client: TestClient) -> None:
    denied = client.get("/api/v1/updates", headers={"X-Dev-Identity": "viewer"})
    assert denied.status_code == 200
    response = client.get("/api/v1/updates", headers={"X-Dev-Identity": "operator"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    metrics = client.get("/api/v1/metrics", headers={"X-Dev-Identity": "operator"})
    assert metrics.status_code == 200
    assert "latency_ms" in metrics.json()
