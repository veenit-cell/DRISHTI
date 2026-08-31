ALTER TABLE response_queue_items
    ADD COLUMN IF NOT EXISTS source_recommendation_id text;

CREATE INDEX IF NOT EXISTS response_queue_items_recommendation_scope_idx
    ON response_queue_items (organization_id, workspace_id, source_recommendation_id);

ALTER TABLE recommendation_decisions
    DROP CONSTRAINT IF EXISTS recommendation_decisions_decision_check;

ALTER TABLE recommendation_decisions
    ADD CONSTRAINT recommendation_decisions_decision_check
    CHECK (decision IN ('approve', 'modify', 'reject'));
