from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from app.core.context import RequestContext
from app.core.config import Settings
from app.operations import PostgreSQLOperationsStore
from app.persistence import apply_foundation_migration, database_ready


DATABASE_URL = Settings().database_url


@pytest.mark.integration
@pytest.mark.skipif(
    not database_ready(DATABASE_URL),
    reason="PostgreSQL/PostGIS integration service is unavailable",
)
def test_migrations_enable_postgis_and_expected_scope_tables() -> None:
    apply_foundation_migration(DATABASE_URL)
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT PostGIS_Version()")
        assert cursor.fetchone()[0]
        cursor.execute(
            "SELECT to_regclass('public.resources'), to_regclass('public.event_workspaces')"
        )
        assert cursor.fetchone() == ("resources", "event_workspaces")


@pytest.mark.integration
@pytest.mark.skipif(
    not database_ready(DATABASE_URL),
    reason="PostgreSQL/PostGIS integration service is unavailable",
)
def test_postgres_operations_are_isolated_by_tenant_and_workspace() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    workspace_a, workspace_b = str(uuid4()), str(uuid4())

    def context(tenant: str, workspace: str) -> RequestContext:
        return RequestContext(
            "harness-operator",
            "operator",
            tenant,
            workspace,
            frozenset({"operations:read"}),
            "harness-correlation",
        )

    store = PostgreSQLOperationsStore(DATABASE_URL)
    store.seed_demo(context(tenant_a, workspace_a), now, f"harness-{tenant_a}")
    store.seed_demo(context(tenant_b, workspace_b), now, f"harness-{tenant_b}")
    resources_a = store.list_resources(context(tenant_a, workspace_a))
    resources_b = store.list_resources(context(tenant_b, workspace_b))
    assert resources_a and resources_b
    assert not {item["id"] for item in resources_a} & {item["id"] for item in resources_b}
