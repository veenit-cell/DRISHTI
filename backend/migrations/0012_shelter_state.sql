CREATE TABLE IF NOT EXISTS shelters (
  id text NOT NULL,
  organization_id text NOT NULL REFERENCES organizations(id),
  workspace_id text NOT NULL REFERENCES event_workspaces(id),
  name text NOT NULL,
  synthetic boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (id, organization_id, workspace_id)
);
CREATE TABLE IF NOT EXISTS shelter_observations (
  id text PRIMARY KEY,
  organization_id text NOT NULL REFERENCES organizations(id),
  workspace_id text NOT NULL REFERENCES event_workspaces(id),
  shelter_id text NOT NULL,
  observed_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL,
  source text NOT NULL,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  freshness_state text NOT NULL CHECK (freshness_state IN ('fresh','stale','unknown')),
  values_json jsonb NOT NULL,
  units_json jsonb NOT NULL,
  idempotency_key text NOT NULL,
  request_hash text NOT NULL,
  UNIQUE (organization_id, workspace_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS shelter_observations_scope_idx ON shelter_observations (organization_id, workspace_id, shelter_id, observed_at DESC);
CREATE TABLE IF NOT EXISTS shelter_state_snapshots (
  id text PRIMARY KEY,
  organization_id text NOT NULL REFERENCES organizations(id),
  workspace_id text NOT NULL REFERENCES event_workspaces(id),
  shelter_id text NOT NULL,
  snapshot_hash text NOT NULL,
  snapshot_json jsonb NOT NULL,
  generated_at timestamptz NOT NULL,
  UNIQUE (shelter_id, snapshot_hash)
);
