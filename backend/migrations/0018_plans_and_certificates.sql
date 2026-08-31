CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','feasible','selected','approved','invalidated','expired','review_required','superseded')),
    horizon_hours NUMERIC, objective_summary TEXT, policy_version TEXT NOT NULL,
    input_snapshot_hash TEXT, expires_at TIMESTAMPTZ, actions JSONB NOT NULL DEFAULT '[]',
    assumptions JSONB NOT NULL DEFAULT '[]', fragility NUMERIC NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS plan_assumptions (
    assumption_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
    subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, expected_state TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'medium', valid_until TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS decision_invalidations (
    invalidation_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
    trigger_type TEXT NOT NULL, trigger_ref TEXT NOT NULL, assumption_id TEXT NOT NULL REFERENCES plan_assumptions(assumption_id),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(), reviewed_at TIMESTAMPTZ, recomputed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS decision_certificates (
    certificate_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    selected_plan_id TEXT NOT NULL REFERENCES plans(plan_id), alternative_plan_ids TEXT[] NOT NULL DEFAULT '{}',
    input_snapshot_hash TEXT NOT NULL, exclusions JSONB NOT NULL DEFAULT '[]', policy_version TEXT NOT NULL,
    assumptions_snapshot JSONB NOT NULL DEFAULT '[]', approver_id TEXT, approved_at TIMESTAMPTZ,
    dissent_note TEXT, outcome_ref TEXT, supersedes_certificate_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_plan_assumptions_subject ON plan_assumptions(subject_type, subject_id);
