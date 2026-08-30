-- Phase 2: reviewable evidence lineage and bounded spatial state.
ALTER TABLE raw_reports
    ADD COLUMN IF NOT EXISTS reviewed_by text,
    ADD COLUMN IF NOT EXISTS reviewed_at timestamptz,
    ADD COLUMN IF NOT EXISTS review_note text;

ALTER TABLE report_claims
    DROP CONSTRAINT IF EXISTS report_claims_verification_state_check;

ALTER TABLE report_claims
    ADD CONSTRAINT report_claims_verification_state_check
    CHECK (verification_state IN ('proposed', 'unknown', 'corroborated', 'contradicted', 'stale', 'superseded'));

CREATE TABLE IF NOT EXISTS sectors (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    name text NOT NULL,
    geometry geometry(Polygon, 4326) NOT NULL,
    assessment_state text NOT NULL CHECK (assessment_state IN ('assessed', 'unassessed', 'inaccessible', 'unknown')),
    assessment_source text,
    assessed_at timestamptz,
    UNIQUE (organization_id, workspace_id, name)
);

CREATE TABLE IF NOT EXISTS incident_locations (
    incident_id text PRIMARY KEY REFERENCES synthetic_incidents(id),
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    geometry geometry(Point, 4326),
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS sectors_geometry_idx ON sectors USING gist (geometry);
CREATE INDEX IF NOT EXISTS incident_locations_geometry_idx ON incident_locations USING gist (geometry);

CREATE TABLE IF NOT EXISTS report_incident_links (
    report_id text NOT NULL REFERENCES raw_reports(id),
    incident_id text NOT NULL REFERENCES synthetic_incidents(id),
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    linked_by text NOT NULL,
    linked_at timestamptz NOT NULL,
    PRIMARY KEY (report_id, incident_id)
);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    report_id text NOT NULL REFERENCES raw_reports(id),
    candidate_report_id text NOT NULL REFERENCES raw_reports(id),
    reason text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (report_id, candidate_report_id)
);
