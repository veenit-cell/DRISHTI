CREATE TABLE IF NOT EXISTS infrastructure_nodes (
    node_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    node_type TEXT NOT NULL CHECK (node_type IN ('power','water','communications','hospital','shelter','transport','other')),
    name TEXT NOT NULL,
    location geometry(Point, 4326),
    state TEXT NOT NULL DEFAULT 'unknown' CHECK (state IN ('operational','degraded','failed','unknown')),
    capacity NUMERIC,
    evidence_ref TEXT,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS candidates JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE TABLE IF NOT EXISTS infrastructure_dependencies (
    dependency_id TEXT PRIMARY KEY,
    upstream_id TEXT NOT NULL REFERENCES infrastructure_nodes(node_id),
    downstream_id TEXT NOT NULL REFERENCES infrastructure_nodes(node_id),
    dependency_type TEXT NOT NULL DEFAULT 'requires' CHECK (dependency_type IN ('requires','enhances','degrades_without')),
    threshold NUMERIC,
    policy_version TEXT NOT NULL DEFAULT 'dependency_dag_v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT no_self_dependency CHECK (upstream_id <> downstream_id)
);
CREATE INDEX IF NOT EXISTS idx_infrastructure_nodes_scope ON infrastructure_nodes(organization_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_infrastructure_deps_upstream ON infrastructure_dependencies(upstream_id);
CREATE INDEX IF NOT EXISTS idx_infrastructure_deps_downstream ON infrastructure_dependencies(downstream_id);
