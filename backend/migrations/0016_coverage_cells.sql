CREATE TABLE IF NOT EXISTS coverage_cells (
    cell_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    geometry geometry(Polygon, 4326),
    admin_id TEXT,
    population INTEGER NOT NULL DEFAULT 0 CHECK (population >= 0),
    critical_facilities INTEGER NOT NULL DEFAULT 0 CHECK (critical_facilities >= 0),
    hazard_exposure TEXT NOT NULL DEFAULT 'unknown' CHECK (hazard_exposure IN ('none','low','moderate','high','extreme','unknown')),
    required_fact_types TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverage_observations (
    observation_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    cell_id TEXT NOT NULL REFERENCES coverage_cells(cell_id),
    fact_type TEXT NOT NULL,
    claim_id TEXT,
    observed_at TIMESTAMPTZ,
    freshness_state TEXT NOT NULL DEFAULT 'unknown' CHECK (freshness_state IN ('fresh','stale','expired','unknown')),
    reporting_impaired BOOLEAN NOT NULL DEFAULT false,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, workspace_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_coverage_cells_scope ON coverage_cells(organization_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_coverage_obs_cell ON coverage_observations(organization_id, workspace_id, cell_id);
