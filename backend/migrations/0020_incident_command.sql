CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    workspace_id TEXT NOT NULL REFERENCES event_workspaces(id),
    name TEXT NOT NULL,
    hazard_type TEXT NOT NULL CHECK (hazard_type IN ('flood','earthquake','landslide','cyclone','structural_collapse','multi_hazard','other')),
    severity TEXT NOT NULL CHECK (severity IN ('low','moderate','high','critical')),
    operational_period TEXT NOT NULL DEFAULT 'OP-1',
    summary TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','paused','closed')),
    phase TEXT NOT NULL DEFAULT 'activation' CHECK (phase IN ('activation','size_up','search_rescue','stabilization','handover')),
    roles JSONB NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_incident_per_workspace
    ON incidents(organization_id, workspace_id) WHERE status IN ('active','paused');
CREATE TABLE IF NOT EXISTS incident_sectors (
    sector_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    workspace_id TEXT NOT NULL REFERENCES event_workspaces(id),
    name TEXT NOT NULL,
    owner_actor_id TEXT NOT NULL,
    assessment_state TEXT NOT NULL DEFAULT 'unassessed' CHECK (assessment_state IN ('unassessed','assessed','inaccessible','closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (incident_id, name)
);
