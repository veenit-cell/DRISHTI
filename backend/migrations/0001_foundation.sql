CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS organizations (
    id text PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    organization_id text NOT NULL REFERENCES organizations(id),
    actor_id text NOT NULL,
    role text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, actor_id)
);

CREATE TABLE IF NOT EXISTS event_workspaces (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    name text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('live', 'replay')),
    status text NOT NULL CHECK (status IN ('draft', 'active', 'closed', 'archived')),
    event_time timestamptz NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    version text NOT NULL,
    checksum text NOT NULL,
    activated_at timestamptz,
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, workspace_id, version)
);

CREATE TABLE IF NOT EXISTS baseline_versions (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    version text NOT NULL,
    checksum text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, workspace_id, version)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    actor_id text NOT NULL,
    action text NOT NULL,
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    correlation_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    event_type text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    aggregate_revision integer NOT NULL CHECK (aggregate_revision > 0),
    envelope jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    published_at timestamptz
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    response_status integer NOT NULL,
    response_body jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, workspace_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS jobs (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    job_type text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'leased', 'succeeded', 'failed', 'dead')),
    available_at timestamptz NOT NULL,
    lease_owner text,
    leased_until timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    last_error_code text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS audit_events_scope_time_idx
    ON audit_events (organization_id, workspace_id, recorded_at);
CREATE INDEX IF NOT EXISTS outbox_events_unpublished_idx
    ON outbox_events (created_at) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS jobs_claim_idx
    ON jobs (status, available_at, leased_until);
