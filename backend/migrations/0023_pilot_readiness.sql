CREATE TABLE IF NOT EXISTS pilot_configurations (
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    workspace_id TEXT NOT NULL REFERENCES event_workspaces(id),
    agency_name TEXT NOT NULL,
    district_name TEXT NOT NULL,
    country_code TEXT NOT NULL,
    approved_feed_ids JSONB NOT NULL DEFAULT '[]',
    retention_days_operational INTEGER NOT NULL CHECK (retention_days_operational BETWEEN 1 AND 3650),
    retention_days_restricted INTEGER NOT NULL CHECK (retention_days_restricted BETWEEN 1 AND 3650),
    hazard_playbooks JSONB NOT NULL DEFAULT '{}',
    configured_by TEXT NOT NULL,
    configured_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (organization_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS official_feed_events (
    event_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    workspace_id TEXT NOT NULL REFERENCES event_workspaces(id),
    feed_id TEXT NOT NULL,
    external_event_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    summary TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('operational','restricted_operational')),
    source_url TEXT,
    fingerprint TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    UNIQUE (organization_id, workspace_id, feed_id, external_event_id)
);
