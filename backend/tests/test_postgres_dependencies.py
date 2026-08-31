from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.context import RequestContext
from app.dependencies import (
    InfraDependencyCreate,
    InfraNodeCreate,
    PostgreSQLDependencyStore,
)
from app.persistence import database_ready


@pytest.mark.skipif(
    not database_ready(Settings().database_url),
    reason="local PostgreSQL/PostGIS integration profile is not running",
)
def test_postgresql_dependency_nodes_and_edges_are_persisted() -> None:
    now = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)
    suffix = uuid4().hex
    context = RequestContext(
        actor_id="usr_demo_operator",
        role="operator",
        tenant_id="org_demo",
        workspace_id="evt_demo",
        scopes=frozenset({"operations:read", "operations:write"}),
        correlation_id=f"dependencies-{suffix}",
    )
    store = PostgreSQLDependencyStore(Settings().database_url)
    upstream = f"generator_{suffix}"
    downstream = f"hospital_{suffix}"

    store.create_node(
        context,
        InfraNodeCreate(
            node_id=upstream, node_type="power", name="Synthetic Generator", state="failed"
        ),
        now,
    )
    store.create_node(
        context,
        InfraNodeCreate(
            node_id=downstream, node_type="hospital", name="Synthetic Hospital", state="degraded"
        ),
        now,
    )
    created = store.create_dependency(
        context,
        InfraDependencyCreate(upstream_id=upstream, downstream_id=downstream),
        now,
    )

    assert created["upstream_id"] == upstream
    assert {node["node_id"] for node in store.list_nodes(context)} >= {upstream, downstream}
    assert any(
        edge["upstream_id"] == upstream and edge["downstream_id"] == downstream
        for edge in store.list_dependencies(context)
    )
