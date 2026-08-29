CREATE TABLE IF NOT EXISTS normalization_runs (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    report_id text NOT NULL,
    mapping_version text NOT NULL,
    taxonomy_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('completed', 'failed')),
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_reports (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    client_record_id text NOT NULL,
    original_payload jsonb NOT NULL,
    original_sha256 text NOT NULL,
    source jsonb NOT NULL,
    report_type text NOT NULL,
    privacy_class text NOT NULL,
    observed_at timestamptz,
    received_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    location_geojson jsonb,
    location_uncertainty_m integer,
    place_text text,
    status text NOT NULL CHECK (status IN ('accepted_for_review', 'reviewed')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, workspace_id, client_record_id)
);

CREATE TABLE IF NOT EXISTS report_locations (
    report_id text PRIMARY KEY REFERENCES raw_reports(id),
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    geometry geometry(Point, 4326),
    source_crs text NOT NULL DEFAULT 'EPSG:4326',
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS report_claims (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    report_id text NOT NULL REFERENCES raw_reports(id),
    normalization_run_id text NOT NULL REFERENCES normalization_runs(id),
    claim_type text NOT NULL,
    value jsonb,
    verification_state text NOT NULL CHECK (verification_state IN ('proposed', 'unknown')),
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS synthetic_incidents (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    title text NOT NULL,
    need_type text NOT NULL,
    verification_state text NOT NULL,
    location_geojson jsonb,
    location_uncertainty_m integer,
    source text NOT NULL,
    observed_at timestamptz,
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, workspace_id, id)
);

CREATE INDEX IF NOT EXISTS raw_reports_scope_time_idx
    ON raw_reports (organization_id, workspace_id, recorded_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS report_locations_geometry_idx
    ON report_locations USING gist (geometry);
CREATE INDEX IF NOT EXISTS report_claims_report_idx
    ON report_claims (organization_id, workspace_id, report_id, created_at);
CREATE INDEX IF NOT EXISTS synthetic_incidents_scope_idx
    ON synthetic_incidents (organization_id, workspace_id, created_at);
