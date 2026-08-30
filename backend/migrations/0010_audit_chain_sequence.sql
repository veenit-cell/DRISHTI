CREATE SEQUENCE IF NOT EXISTS audit_events_chain_sequence;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS chain_sequence bigint;
ALTER TABLE audit_events ALTER COLUMN chain_sequence SET DEFAULT nextval('audit_events_chain_sequence');
UPDATE audit_events SET chain_sequence = nextval('audit_events_chain_sequence') WHERE chain_sequence IS NULL;
ALTER TABLE audit_events ALTER COLUMN chain_sequence SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS audit_events_scope_chain_sequence_idx
    ON audit_events (organization_id, workspace_id, chain_sequence);
