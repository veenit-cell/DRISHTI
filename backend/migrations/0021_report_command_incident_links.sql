CREATE TABLE IF NOT EXISTS report_command_incident_links (
    report_id TEXT NOT NULL REFERENCES raw_reports(id),
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    workspace_id TEXT NOT NULL REFERENCES event_workspaces(id),
    linked_by TEXT NOT NULL,
    linked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (report_id, incident_id)
);
