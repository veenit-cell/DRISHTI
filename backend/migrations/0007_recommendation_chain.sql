ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS priority integer NOT NULL DEFAULT 0;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS input_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS input_hash text NOT NULL DEFAULT '';
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS expected_effect text;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS expires_at timestamptz;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS queue_item_id uuid;
