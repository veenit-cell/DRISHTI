from pathlib import Path

import psycopg
from pytest import MonkeyPatch

from app.persistence import apply_foundation_migration


class FakeCursor:
    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        assert "CREATE TABLE IF NOT EXISTS organizations" in sql


class FakeConnection:
    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def test_apply_migration_retries_transient_startup_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = 0

    def connect(database_url: str, connect_timeout: int) -> FakeConnection:
        nonlocal calls
        assert database_url == "postgresql://example"
        assert connect_timeout == 2
        calls += 1
        if calls == 1:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return FakeConnection()

    monkeypatch.setattr("app.persistence.psycopg.connect", connect)
    monkeypatch.setattr("app.persistence.sleep", lambda _seconds: None)

    apply_foundation_migration("postgresql://example", attempts=2)

    assert calls == 2


def test_durable_operations_migration_uses_partial_active_task_constraint() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "0004_durable_operations_and_decisions.sql"
    ).read_text(encoding="utf-8")
    assert (
        "DROP CONSTRAINT IF EXISTS response_tasks_workspace_id_resource_id_status_key" in migration
    )
    assert "ON response_tasks (workspace_id, resource_id)" in migration
    assert "WHERE status <> 'completed'" in migration
