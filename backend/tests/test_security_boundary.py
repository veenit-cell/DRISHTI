 # ruff: noqa: E501

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.context import LocalOIDCVerifier
from app.main import create_app
from app.operations import InMemoryOperationsStore


def app():
    return create_app(Settings(app_environment="test", dev_identity_enabled=True), operations_store=InMemoryOperationsStore())


def test_missing_invalid_expired_identity_and_role_denial():
    client = TestClient(app())
    assert client.get("/api/v1/dev/context").status_code == 401
    assert client.get("/api/v1/dev/context", headers={"Authorization": "Bearer nope"}).status_code == 401
    expired = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    assert client.get("/api/v1/dev/context", headers={"Authorization": f"Bearer local:viewer:{expired}"}).status_code == 401
    assert client.get("/api/v1/dev/context", headers={"X-Dev-Identity": "viewer"}).status_code == 403
    assert LocalOIDCVerifier().verify("local:operator")["role"] == "operator"


def test_production_refuses_development_identity_and_rate_limit_is_bounded():
    with pytest.raises(ValueError, match="disabled"):
        Settings(app_environment="production", dev_identity_enabled=True)
    client = TestClient(app())
    statuses = [client.get("/api/v1/health/live", headers={"X-Dev-Identity": "operator"}).status_code for _ in range(61)]
    assert statuses[-1] == 429
