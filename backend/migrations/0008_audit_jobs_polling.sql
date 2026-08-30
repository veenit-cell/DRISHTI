ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS previous_hash text;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS event_hash text;
CREATE INDEX IF NOT EXISTS jobs_scope_status_idx ON jobs (organization_id, workspace_id, status, updated_at DESC);
