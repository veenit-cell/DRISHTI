ALTER TABLE resources ADD COLUMN IF NOT EXISTS capacity_value NUMERIC;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS capacity_unit TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS reserve_floor NUMERIC DEFAULT 0;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS owner_agency TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS evidence_ref TEXT;
ALTER TABLE response_tasks ADD COLUMN IF NOT EXISTS completion_evidence JSONB;
ALTER TABLE response_tasks ADD COLUMN IF NOT EXISTS completion_quantities JSONB;
ALTER TABLE response_tasks ADD COLUMN IF NOT EXISTS residual_need TEXT;
ALTER TABLE response_tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE response_tasks ADD COLUMN IF NOT EXISTS verified_by TEXT;

CREATE TABLE IF NOT EXISTS resource_forecasts (
    forecast_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    request JSONB NOT NULL,
    forecast JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resource_requests (
    request_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    reserve_floor NUMERIC NOT NULL CHECK (reserve_floor >= 0),
    location TEXT NOT NULL,
    need_by TIMESTAMPTZ NOT NULL,
    forecast_hash TEXT NOT NULL,
    shortage_window_bucket TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','rejected','fulfilled','cancelled')),
    source_reality TEXT NOT NULL DEFAULT 'synthetic',
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    approval_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, workspace_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_resource_forecasts_scope ON resource_forecasts(organization_id,workspace_id,created_at);
CREATE INDEX IF NOT EXISTS idx_resource_requests_scope ON resource_requests(organization_id,workspace_id,status,created_at);
