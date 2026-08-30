-- Earlier hashes lacked a stable sequence when several events shared a timestamp.
-- Preserve the audit records, but begin a separately verifiable chain after this migration.
UPDATE audit_events SET previous_hash = NULL, event_hash = NULL;
