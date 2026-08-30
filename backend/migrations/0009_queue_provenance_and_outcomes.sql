ALTER TABLE response_queue_items ADD COLUMN IF NOT EXISTS owner_actor_id text;
ALTER TABLE response_queue_items ADD COLUMN IF NOT EXISTS due_at timestamptz;
ALTER TABLE response_queue_items ADD COLUMN IF NOT EXISTS source_report_id text;
ALTER TABLE response_queue_items ADD COLUMN IF NOT EXISTS source_incident_id text;
ALTER TABLE response_tasks ADD COLUMN IF NOT EXISTS outcome_summary text;
ALTER TABLE response_tasks ADD COLUMN IF NOT EXISTS outcome_recorded_at timestamptz;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS outcome_summary text;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS outcome_at timestamptz;
