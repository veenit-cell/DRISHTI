from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.operations import InMemoryOperationsStore
from app.persistence import database_ready
from app.telemetry import InMemoryTelemetryAdapter


class FakeProductionVerifier:
    def verify(self, token: str) -> dict[str, Any]:
        if token != "oidc-production-token":
            raise ValueError("invalid token")
        return {
            "actor_id": "operator-1",
            "role": "operator",
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
            "scopes": frozenset({"context:read", "system:read", "operations:read"}),
        }


def production_client() -> TestClient:
    settings = Settings(
        app_environment="production",
        dev_identity_enabled=False,
        allowed_origins=("https://command.example.test",),
    )
    return TestClient(
        create_app(
            settings,
            identity_verifier=FakeProductionVerifier(),
            telemetry_adapter=InMemoryTelemetryAdapter(),
        )
    )


def test_production_requires_external_identity_and_rejects_local_fixture_tokens() -> None:
    client = production_client()
    assert client.get("/api/v1/dev/context", headers={"X-Dev-Identity": "operator"}).status_code == 401
    assert client.get(
        "/api/v1/dev/context", headers={"Authorization": "Bearer local:operator"}
    ).status_code == 401
    accepted = client.get(
        "/api/v1/dev/context", headers={"Authorization": "Bearer oidc-production-token"}
    )
    assert accepted.status_code == 200
    assert accepted.json()["tenant_id"] == "tenant-1"
    assert accepted.json()["workspace_id"] == "workspace-1"


def test_production_app_fails_closed_without_identity_verifier() -> None:
    settings = Settings(
        app_environment="production",
        dev_identity_enabled=False,
        allowed_origins=("https://command.example.test",),
    )
    with pytest.raises(ValueError, match="identity verifier"):
        create_app(settings)


def test_production_app_fails_closed_without_telemetry_adapter() -> None:
    settings = Settings(
        app_environment="production",
        dev_identity_enabled=False,
        allowed_origins=("https://command.example.test",),
    )
    with pytest.raises(ValueError, match="telemetry adapter"):
        create_app(settings, identity_verifier=FakeProductionVerifier())


def test_production_cors_does_not_advertise_development_header() -> None:
    client = production_client()
    response = client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "https://command.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Dev-Identity",
        },
    )
    assert "x-dev-identity" not in response.headers.get("access-control-allow-headers", "").lower()


def test_production_security_headers_are_present() -> None:
    response = production_client().get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "max-age=31536000" in response.headers["strict-transport-security"]


def test_readiness_and_metrics_expose_dependency_state_without_payload_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.routes.database_ready", lambda _url: True)
    app = create_app(
        Settings(app_environment="test", dev_identity_enabled=True),
        operations_store=InMemoryOperationsStore(),
    )
    client = TestClient(app)
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {
        "database": "available",
        "update_feed": "available",
        "telemetry_adapter": "healthy",
        "external_integrations": "not_checked",
    }
    metrics = client.get("/api/v1/metrics", headers={"X-Dev-Identity": "operator"})
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["correlation_id"]
    assert "failed_writes:total" in body["counters"]
    assert "duplicate_retries:total" in body["counters"]
    assert "offline_reconciliation_failures:total" in body["counters"]


def test_database_ready_requires_postgis(monkeypatch: pytest.MonkeyPatch) -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, _sql: str) -> None:
            self.calls += 1

        def fetchone(self) -> tuple[object, ...]:
            return (1,) if self.calls == 1 else ("3.5",)

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr("app.persistence.psycopg.connect", lambda *_args, **_kwargs: Connection())
    assert database_ready("postgresql://example") is True
