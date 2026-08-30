-- Phase 1 correction: operational IDs share the text tenant/workspace scope
-- established by 0001, and active-task exclusion is a partial unique index.
ALTER TABLE resources
    ALTER COLUMN organization_id TYPE text USING organization_id::text,
    ALTER COLUMN workspace_id TYPE text USING workspace_id::text;

ALTER TABLE response_queue_items
    ALTER COLUMN organization_id TYPE text USING organization_id::text,
    ALTER COLUMN workspace_id TYPE text USING workspace_id::text;

ALTER TABLE response_tasks
    ALTER COLUMN organization_id TYPE text USING organization_id::text,
    ALTER COLUMN workspace_id TYPE text USING workspace_id::text,
    ALTER COLUMN approved_by TYPE text USING approved_by::text;

ALTER TABLE response_tasks
    DROP CONSTRAINT IF EXISTS response_tasks_workspace_id_resource_id_status_key;

CREATE UNIQUE INDEX IF NOT EXISTS response_tasks_one_active_resource_idx
    ON response_tasks (workspace_id, resource_id)
    WHERE status <> 'completed';

CREATE TABLE IF NOT EXISTS demo_scenarios (
    workspace_id text PRIMARY KEY REFERENCES event_workspaces(id),
    organization_id text NOT NULL REFERENCES organizations(id),
    scenario_id text NOT NULL,
    sector text NOT NULL,
    synthetic boolean NOT NULL DEFAULT true,
    signals jsonb NOT NULL,
    replayed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    status text NOT NULL CHECK (status IN ('pending_approval', 'approved', 'rejected')),
    action text NOT NULL,
    sector text NOT NULL,
    compatible_resources jsonb NOT NULL,
    reasons jsonb NOT NULL,
    rule text NOT NULL,
    auto_dispatched boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    decided_by text,
    decided_at timestamptz,
    decision_note text
);

CREATE TABLE IF NOT EXISTS recommendation_decisions (
    id text PRIMARY KEY,
    recommendation_id text NOT NULL UNIQUE REFERENCES recommendations(id),
    organization_id text NOT NULL REFERENCES organizations(id),
    workspace_id text NOT NULL REFERENCES event_workspaces(id),
    decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
    actor_id text NOT NULL,
    note text,
    decided_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS recommendations_scope_created_idx
    ON recommendations (organization_id, workspace_id, created_at DESC, id DESC);
