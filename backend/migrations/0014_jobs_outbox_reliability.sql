ALTER TABLE jobs ADD COLUMN IF NOT EXISTS handler_key text;
CREATE UNIQUE INDEX IF NOT EXISTS jobs_handler_key_unique ON jobs (organization_id, workspace_id, handler_key) WHERE handler_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_backlog_age_idx ON jobs (organization_id, workspace_id, status, created_at);
