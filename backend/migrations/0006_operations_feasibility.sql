ALTER TABLE resources ADD COLUMN IF NOT EXISTS capabilities jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS readiness_observed_at timestamptz;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS readiness_expires_at timestamptz;
ALTER TABLE response_queue_items ADD COLUMN IF NOT EXISTS queue_type text NOT NULL DEFAULT 'response';
ALTER TABLE response_queue_items ADD COLUMN IF NOT EXISTS required_capability text;

DO $$ BEGIN
  ALTER TABLE response_queue_items ADD CONSTRAINT response_queue_type_check CHECK (queue_type IN ('response','verification'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS route_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id text NOT NULL,
  workspace_id text NOT NULL,
  destination text NOT NULL,
  state text NOT NULL CHECK (state IN ('passable','blocked','unknown','stale')),
  source text,
  observed_at timestamptz NOT NULL,
  expires_at timestamptz,
  created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS route_observations_scope_idx ON route_observations (organization_id, workspace_id, destination, observed_at DESC);
