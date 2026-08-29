from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.clock import FixedClock
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.api.routes.database_ready", lambda _url: True)
    app = create_app(Settings(app_environment="test", dev_identity_enabled=True))
    return TestClient(app, raise_server_exceptions=False)


def test_liveness_version_and_correlation(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Correlation-ID": "test-123"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Correlation-ID"] == "test-123"

    version = client.get("/api/v1/version")
    assert version.json()["api_version"] == "v1"


def test_readiness_reports_required_database_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.routes.database_ready", lambda _url: False)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["retryable"] is True


def test_development_context_is_deny_by_default_and_scope_checked(client: TestClient) -> None:
    missing = client.get("/api/v1/dev/context")
    assert missing.status_code == 401
    assert missing.json()["code"] == "AUTHENTICATION_REQUIRED"

    denied = client.get("/api/v1/dev/context", headers={"X-Dev-Identity": "viewer"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "SCOPE_DENIED"

    allowed = client.get("/api/v1/dev/context", headers={"X-Dev-Identity": "operator"})
    assert allowed.status_code == 200
    assert allowed.json()["tenant_id"] == "org_demo"
    assert allowed.json()["workspace_id"] == "evt_demo"
    assert allowed.json()["identity_source"] == "development-fixture"


def test_invalid_correlation_id_is_bounded(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Correlation-ID": "x" * 129},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CORRELATION_ID"


def test_fixed_clock_requires_timezone() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 8, 30, 10, 0, 0)).now()
    expected = datetime(2026, 8, 30, 10, 0, 0, tzinfo=UTC)
    assert FixedClock(expected).now() == expected


def test_production_configuration_rejects_development_identity() -> None:
    with pytest.raises(ValidationError):
        Settings(app_environment="production", dev_identity_enabled=True)
