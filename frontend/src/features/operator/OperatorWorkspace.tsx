import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { activateIncident, advanceLiveTask, advanceTask, approveMission, approveMutualAid, assignApproved, assignVerification, completeLiveTask, closeIncident, configurePilot, createEvidenceReport, createIncidentSector, createMission, createSitrep, decide, getActiveIncident, getLiveDecisionFlow, getEvidenceReport, getPilotStatus, linkEvidenceToCommandIncident, listEvidenceReports, listIncidentSectors, listMapFeatures, listMissions, listResourceForecasts, pauseIncident, pollOperationalUpdates, recordAuditInteraction, resumeIncident, listResourceRequests, listResources, resetGoldenFlow, reviewEvidenceReport, runExerciseReplay, runPilotTabletop, type CommandIncident, type EvidenceReport, type EvidenceReportDetail, type GoldenFlow, type IncidentSector, type MapFeature, type Mission, type OperationalUpdateType, type PilotStatus, type TabletopExercise } from "./api";
import { getOfflineSummary, isOfflineCommandPending, printTaskPacket, queueCommand, queueTaskUpdate, readOutbox, retryOutbox, syncOutbox, type OfflineSummary, type StoredOfflineCommand } from "./offline";
import { demoWorkspace, type WorkspaceData } from "./fixtures";
import { syntheticGeography } from "./fixtures/syntheticGeography";
import { IncidentBar } from "./components/IncidentBar";
import { CommandBrief } from "./components/CommandBrief";
import { MapCOP } from "./components/MapCOP";
import { EvidenceTrustPanel } from "./components/EvidenceTrustPanel";

type Action = "approve" | "reject" | "modify" | "assign" | "acknowledged" | "en_route" | "on_scene" | "paused" | "completed";
type WorkspaceView = "Command" | "Map" | "Reports" | "Missions" | "Resources" | "Logistics" | "Handover";
type RefreshSection = "command" | "map" | "reports" | "missions" | "resources";
export type UpdateHealthState = "connecting" | "connected" | "reconnecting" | "stale";

export function affectedSectionsForUpdate(eventType: OperationalUpdateType): RefreshSection[] {
  switch (eventType) {
    case "shelter_state_changed": return ["command", "map"];
    case "route_condition_changed": return ["command", "map", "missions"];
    case "incident_phase_changed": return ["command", "map", "reports"];
    case "recommendation_changed": return ["command", "missions"];
    case "resource_readiness_changed": return ["command", "resources"];
    case "task_status_changed": return ["command", "missions"];
    case "verification_priority_changed": return ["command", "reports"];
    case "communication_gap_detected": return ["command", "map", "reports"];
    case "communication_gap_recovered": return ["command", "map", "reports"];
    default: return [];
  }
}

/* ===================================================================
   SVG Icons (inline, no extra dependencies)
   =================================================================== */
const icons: Record<string, ReactNode> = {
  Command: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>,
  Map: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>,
  Reports: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>,
  Missions: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>,
  Resources: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  Logistics: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>,
  Handover: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>,
  training: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>,
  incident: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  menu: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>,
};

const viewMeta: Record<WorkspaceView, { label: string; desc: string }> = {
  Command: { label: "Dashboard", desc: "Overview & decisions" },
  Map: { label: "Live Map", desc: "Spatial awareness" },
  Reports: { label: "Reports", desc: "Evidence & verification" },
  Missions: { label: "Missions", desc: "Track field operations" },
  Resources: { label: "Resources", desc: "Teams & equipment" },
  Logistics: { label: "Logistics", desc: "Supply & forecasts" },
  Handover: { label: "Handover", desc: "Shift reports & drills" },
};

const workspaceViews: WorkspaceView[] = ["Command", "Map", "Reports", "Missions", "Resources", "Logistics", "Handover"];

/* ===================================================================
   Sidebar Navigation
   =================================================================== */
function AppSidebar({ activeView, onSelect, isOpen, onClose }: { activeView: WorkspaceView; onSelect: (view: WorkspaceView) => void; isOpen: boolean; onClose: () => void }) {
  return (
    <aside id="main-navigation" className={`app-sidebar${isOpen ? " is-open" : ""}`} aria-label="Main navigation">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">D</div>
        <div className="sidebar-brand-text">
          <h1>DRISHTI</h1>
          <small>Disaster Response</small>
        </div>
      </div>

      <nav className="sidebar-nav">
        <div className="sidebar-section-label">Workspaces</div>
        {workspaceViews.map((view) => (
          <button
            key={view}
            className={`sidebar-nav-item${activeView === view ? " is-active" : ""}`}
            type="button"
            aria-current={activeView === view ? "page" : undefined}
            onClick={() => { onSelect(view); onClose(); }}
          >
            <span className="sidebar-nav-icon" aria-hidden="true">{icons[view]}</span>
            <div>
              <div>{viewMeta[view].label}</div>
              <div className="sidebar-nav-desc">{viewMeta[view].desc}</div>
            </div>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-status" role="status" aria-live="polite">
          <span className={`sidebar-status-dot${navigator.onLine ? "" : " offline"}`} aria-hidden="true" />
          <span>{navigator.onLine ? "Connected" : "Offline"}</span>
        </div>
      </div>
    </aside>
  );
}

/* ===================================================================
   Offline Command Center — local queue state is never presented as applied
   =================================================================== */
function OfflineCommandCenter({ setError, mission }: { setError: (value: string) => void; mission?: { id: string; resource: string; status: string } }) {
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  const [commands, setCommands] = useState<StoredOfflineCommand[]>([]);
  const [summary, setSummary] = useState<OfflineSummary>({ last_successful_sync: null, last_known_state_timestamp: null });
  const [syncing, setSyncing] = useState(false);

  async function refresh() {
    try {
      const [nextCommands, nextSummary] = await Promise.all([readOutbox(), getOfflineSummary()]);
      setCommands(nextCommands);
      setSummary(nextSummary);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Offline state unavailable");
    }
  }

  async function sync() {
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      setError("Still offline — commands remain queued locally and are not server-applied.");
      return;
    }
    setSyncing(true);
    try {
      await retryOutbox();
      const result = await syncOutbox();
      await refresh();
      if (result.conflicts || result.rejected) setError(`${result.conflicts} command conflicts and ${result.rejected} rejected commands require review. No unresolved command was reported as applied.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Outbox reconciliation failed");
    } finally {
      setSyncing(false);
    }
  }

  useEffect(() => {
    const onConnectivityChange = () => {
      const connected = navigator.onLine;
      setOnline(connected);
      void refresh();
      if (connected) void sync();
    };
    void refresh();
    window.addEventListener("online", onConnectivityChange);
    window.addEventListener("offline", onConnectivityChange);
    return () => {
      window.removeEventListener("online", onConnectivityChange);
      window.removeEventListener("offline", onConnectivityChange);
    };
  }, []);

  const pending = commands.filter(isOfflineCommandPending).length;
  const conflicts = commands.filter((command) => command.local_status === "conflict" || command.local_status === "blocked").length;
  const rejected = commands.filter((command) => command.local_status === "rejected").length;
  const statusLabel = (command: StoredOfflineCommand) => {
    if (command.local_status === "queued") return "Queued locally — not server-applied";
    if (command.local_status === "syncing") return "Reconciling with server";
    if (command.local_status === "accepted") return "Server reconciled: accepted";
    if (command.local_status === "replayed") return "Server reconciled: replayed safely";
    if (command.local_status === "rejected") return `Rejected: ${command.last_error ?? "server declined command"}`;
    return `Conflict / blocked: ${command.last_error ?? "ordering requires review"}`;
  };
  const shownCommands = commands.slice(0, 8);
  const formatTime = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : "Not available";

  return (
    <section className={`offline-command-center${online ? "" : " is-offline"}`} aria-labelledby="offline-command-center-title">
      <div className="offline-command-heading">
        <div>
          <p className="eyebrow">Offline command center</p>
          <h2 id="offline-command-center-title"><span aria-hidden="true">{online ? "●" : "○"}</span> {online ? "Connected" : "Offline"}</h2>
          <p className="offline-command-note">{online ? "Server reconciliation is available." : "Commands are saved locally. Local queue state is not proof of operational application."}</p>
        </div>
        <div className="offline-command-actions">
          <button type="button" className="btn-secondary" disabled={syncing || !online} onClick={() => void sync()}>{syncing ? "Reconciling..." : "Retry reconciliation"}</button>
          {mission ? <button type="button" className="btn-secondary" onClick={() => printTaskPacket(mission)}>Print mission packet</button> : null}
        </div>
      </div>
      <dl className="offline-command-facts">
        <div><dt>Pending commands</dt><dd>{pending}</dd></div>
        <div><dt>Conflicts</dt><dd>{conflicts}</dd></div>
        <div><dt>Rejected</dt><dd>{rejected}</dd></div>
        <div><dt>Last successful sync</dt><dd>{formatTime(summary.last_successful_sync)}</dd></div>
        <div><dt>Last-known state</dt><dd>{formatTime(summary.last_known_state_timestamp)}</dd></div>
      </dl>
      <div className="offline-command-status" role="status" aria-live="polite">
        <strong>Per-command reconciliation</strong>
        {shownCommands.length ? <ul>{shownCommands.map((command) => <li key={command.command_id}><span className={`offline-status offline-status-${command.local_status}`}>{command.local_status}</span><span><strong>{command.kind}</strong> · {command.aggregate_id} · sequence {command.sequence}<small>{statusLabel(command)} · client time {formatTime(command.client_timestamp)}</small></span></li>)}</ul> : <p>No local commands recorded.</p>}
        {commands.length > shownCommands.length ? <small>Showing {shownCommands.length} of {commands.length} local command records.</small> : null}
      </div>
    </section>
  );
}

/* ===================================================================
   Reports Workspace — same logic, better labels
   =================================================================== */
function ReportsWorkspace({ incident, busy, setBusy, setError }: { incident: CommandIncident | null; busy: boolean; setBusy: (value: boolean) => void; setError: (value: string) => void }) {
  const [reports, setReports] = useState<EvidenceReport[]>([]);
  const [selected, setSelected] = useState<EvidenceReportDetail | null>(null);
  const [reportType, setReportType] = useState("life_safety");
  const [placeText, setPlaceText] = useState("");
  const [peopleAffected, setPeopleAffected] = useState("");
  const [filterClass, setFilterClass] = useState<string>("all");
  const [verificationQueued, setVerificationQueued] = useState<string[]>([]);
  const [verificationAssignedAt, setVerificationAssignedAt] = useState<Record<string, string>>({});
  const refresh = async () => setReports(await listEvidenceReports());
  useEffect(() => { void refresh(); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (!navigator.onLine) {
        const commandId = `offline-report-${Date.now()}`;
        await queueCommand({ command_id: commandId, aggregate_id: commandId, sequence: 1, kind: "report", client_timestamp: new Date().toISOString(), payload: { report_type: reportType, place_text: placeText, people_affected: peopleAffected ? Number(peopleAffected) : null }, tenant_id: "org_demo", workspace_id: "evt_demo" });
        setError("You're offline — this report has been saved locally as Unverified and will sync when you reconnect.");
        return;
      }
      const created = await createEvidenceReport({ report_type: reportType, place_text: placeText, people_affected: peopleAffected ? Number(peopleAffected) : null });
      if (incident) await linkEvidenceToCommandIncident(created.report_id, incident.incident_id);
      await openEvidence(created.report_id); setPlaceText(""); setPeopleAffected(""); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Failed to submit report"); } finally { setBusy(false); }
  }

  async function verify(claimId: string, state: "corroborated" | "contradicted" | "unknown") {
    if (!selected) return; setBusy(true); setError("");
    try { setSelected(await reviewEvidenceReport(selected.id, { [claimId]: state })); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Review failed"); } finally { setBusy(false); }
  }

  async function openEvidence(reportId: string) {
    try {
      setSelected(await getEvidenceReport(reportId));
      void recordAuditInteraction("evidence_opened", "evidence", reportId).catch(() => undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load report");
    }
  }

  async function queueVerification() {
    if (!selected) return; setBusy(true); setError("");
    try {
      await assignVerification(selected, incident?.incident_id);
      setVerificationQueued((current) => [...current, selected.id]);
      setVerificationAssignedAt((current) => ({ ...current, [selected.id]: new Date().toISOString() }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not assign verification"); } finally { setBusy(false); }
  }

  const getReportClassification = (r: EvidenceReport): "Confirmed" | "Unverified" | "Contradictory" | "Unknown / Needs Verification" => {
    const s = r.status.toLowerCase();
    const claims = "claims" in r && Array.isArray(r.claims) ? r.claims : [];
    if (claims.some((claim) => claim.verification_state.toLowerCase() === "contradicted")) return "Contradictory";
    if (s.includes("corroborated") || s.includes("confirmed")) return "Confirmed";
    if (s.includes("contradicted") || s.includes("conflict")) return "Contradictory";
    if (s.includes("unknown") || s.includes("silent") || s.includes("stale")) return "Unknown / Needs Verification";
    return "Unverified";
  };

  const filteredReports = reports.filter((r) => {
    if (filterClass === "all") return true;
    return getReportClassification(r).toLowerCase().includes(filterClass.toLowerCase());
  });

  return (
    <section className="workspace-section" aria-label="Reports & Evidence">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Evidence Intake &amp; Classification</p>
          <h2>Reports &amp; Verification</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>
            Classify fragmented reports as <strong>Confirmed</strong>, <strong>Unverified</strong>, <strong>Contradictory</strong>, or <strong>Unknown / Needs Verification</strong>.
          </p>
        </div>
        <span className="badge"><span className={`badge-dot${incident ? " info" : " warning"}`} />{incident ? "Linked to active incident" : "No active incident"}</span>
      </div>

      <form className="approval-panel" onSubmit={(event) => void submit(event)}>
        <select aria-label="Report type" value={reportType} onChange={(event) => setReportType(event.target.value)}>
          <option value="life_safety">Life safety / Rescue</option>
          <option value="access_blocked">Access blocked</option>
          <option value="water_contamination">Water contamination</option>
        </select>
        <input aria-label="Location" required placeholder="Location or area name" value={placeText} onChange={(event) => setPlaceText(event.target.value)} />
        <input aria-label="People affected" inputMode="numeric" min="0" placeholder="People affected (optional)" value={peopleAffected} onChange={(event) => setPeopleAffected(event.target.value)} />
        <button type="submit" className="btn-primary" disabled={busy}>Submit Unverified Report</button>
      </form>

      {/* CLASSIFICATION FILTER TABS (Requirement 2) */}
      <div style={{display: "flex", gap: "0.5rem", marginTop: "1rem", flexWrap: "wrap"}}>
        {[
          { key: "all", label: `All (${reports.length})` },
          { key: "confirmed", label: "Confirmed", color: "var(--status-success)" },
          { key: "unverified", label: "Unverified", color: "var(--status-info)" },
          { key: "contradictory", label: "Contradictory", color: "var(--status-warning)" },
          { key: "unknown", label: "Unknown / Needs Verification", color: "#8b5cf6" },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={filterClass === tab.key ? "btn-primary" : "btn-secondary"}
            onClick={() => setFilterClass(tab.key)}
            style={{fontSize: "0.75rem", padding: "0.35rem 0.75rem"}}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="ops-dashboard" style={{marginTop: "1rem"}}>
        <div className="ops-column">
          <div className="ops-card">
            <h3>Field Reports ({filteredReports.length})</h3>
            <div className="ops-list">
              {filteredReports.length ? filteredReports.map((report) => {
                const cls = getReportClassification(report);
                const badgeColor = cls === "Confirmed" ? "var(--status-success)" : cls === "Contradictory" ? "var(--status-warning)" : cls === "Unverified" ? "var(--status-info)" : "#8b5cf6";

                return (
                  <button type="button" className="ops-row" key={report.id} onClick={() => void openEvidence(report.id)}>
                    <div style={{display: "flex", justifyContent: "space-between", alignItems: "center"}}>
                      <span className="ops-row-title">{report.report_type.replaceAll("_", " ")}</span>
                      <span style={{fontSize: "0.65rem", fontWeight: 700, padding: "0.15rem 0.4rem", borderRadius: "3px", border: `1px solid ${badgeColor}`, color: badgeColor}}>
                        {cls.toUpperCase()}
                      </span>
                    </div>
                    <span className="ops-row-meta">{report.location?.place_text ?? "Location unknown"} · {report.status}</span>
                  </button>
                );
              }) : <div className="empty-state">No reports match this classification.</div>}
            </div>
          </div>
        </div>

        <div className="ops-column">
          <div className="ops-card">
            <h3>Evidence Review &amp; Claims</h3>
            {selected ? (
              <div className="ops-list">
                <div className="ops-row">
                  <div style={{display: "flex", justifyContent: "space-between", alignItems: "center"}}>
                    <strong>{selected.report_type.replaceAll("_", " ")}</strong>
                    <span style={{fontSize: "0.7rem", fontWeight: 700, color: "var(--accent-cyan)"}}>{getReportClassification(selected)}</span>
                  </div>
                  <div className="ops-row-meta">Source: {selected.source.channel} · {selected.observed_at ?? "Time unknown"}</div>
                  <div className="ops-row-meta">Linked incidents: {selected.command_incident_links.length ? selected.command_incident_links.map((link) => link.incident_id).join(", ") : "None"}</div>
                  <button type="button" className="btn-primary" disabled={busy || verificationQueued.includes(selected.id)} onClick={() => void queueVerification()} style={{marginTop: "0.5rem", fontSize: "0.8rem"}}>
                    {verificationQueued.includes(selected.id) ? "✓ Verification Assigned" : "Assign for Verification"}
                  </button>
                </div>

                {selected.duplicate_candidates.map((candidate) => (
                  <div className="ops-row" key={candidate.candidate_report_id} style={{borderLeft: "3px solid var(--status-warning)", background: "var(--status-warning-bg)"}}>
                    <strong style={{color: "var(--status-warning)"}}>⚠ Contradiction / Duplicate Alert</strong>
                    <div className="ops-row-meta">{candidate.reason}</div>
                  </div>
                ))}

                {selected.claims.map((claim) => (
                  <div className="ops-row" key={claim.id}>
                    <strong>{claim.claim_type}</strong>
                    <div className="ops-row-meta">Status: <span style={{fontWeight: 700}}>{claim.verification_state}</span></div>
                    <div style={{display: "flex", gap: "0.5rem", marginTop: "0.35rem"}}>
                      <button type="button" className="btn-secondary" disabled={busy} onClick={() => void verify(claim.id, "corroborated")} style={{fontSize: "0.75rem", padding: "0.35rem 0.6rem"}}>✓ Confirm</button>
                      <button type="button" className="btn-secondary" disabled={busy} onClick={() => void verify(claim.id, "contradicted")} style={{fontSize: "0.75rem", padding: "0.35rem 0.6rem", color: "var(--status-warning)", borderColor: "rgba(245,158,11,0.3)"}}>⚠ Contradict</button>
                      <button type="button" className="btn-danger" disabled={busy} onClick={() => void verify(claim.id, "unknown")} style={{fontSize: "0.75rem", padding: "0.35rem 0.6rem"}}>? Needs Verification</button>
                    </div>
                  </div>
                ))}
              </div>
            ) : <div className="empty-state">Click a report on the left to review its details, claims, and verification classification.</div>}
          </div>
        </div>
      </div>

      <EvidenceTrustPanel
        reports={reports}
        selected={selected}
        busy={busy}
        verificationQueued={selected ? verificationQueued.includes(selected.id) : false}
        verificationAssignedAt={selected ? verificationAssignedAt[selected.id] : null}
        onSelect={(reportId) => void openEvidence(reportId)}
        onVerify={(claimId, state) => void verify(claimId, state)}
        onQueueVerification={() => void queueVerification()}
      />
    </section>
  );
}

/* ===================================================================
   Map Workspace
   =================================================================== */
function MapWorkspace({ setError, workspaceMode }: { setError: (value: string) => void; workspaceMode?: "live" | "synthetic" | "mixed" }) {
  const [features, setFeatures] = useState<MapFeature[]>(workspaceMode === "synthetic" ? syntheticGeography : []);
  useEffect(() => {
    const baseline = workspaceMode === "synthetic" ? syntheticGeography : [];
    void listMapFeatures().then((liveFeatures) => {
      setFeatures([...baseline, ...liveFeatures.filter((feature) => !baseline.some((seed) => seed.id === feature.id))]);
    }).catch((reason) => {
      setFeatures(baseline);
      if (workspaceMode !== "synthetic") setError(reason instanceof Error ? reason.message : "Map unavailable");
    });
  }, [setError, workspaceMode]);
  return (
    <section className="workspace-section" aria-label="Map view">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Spatial Awareness</p>
          <h2>Live Map & Coverage</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>View reported incidents, resource positions, and coverage gaps on the map.</p>
        </div>
        <span className="badge">{features.length} map features</span>
      </div>
      <div className="map-workspace-canvas"><MapCOP setError={setError} isSynthetic={workspaceMode === "synthetic"} /></div>
      <div className="ops-list" style={{marginTop: "1rem"}}>
        {features.length ? features.map((feature) => (
          <div className="ops-row" key={feature.id}>
            <strong>{String(feature.properties.title ?? feature.properties.name ?? feature.properties.report_type ?? "Unnamed feature")}</strong>
            <div className="ops-row-meta">{String(feature.properties.feature_kind)} · {String(feature.properties.verification_state ?? feature.properties.status ?? feature.properties.assessment_state ?? "unassessed")}</div>
          </div>
        )) : <div className="empty-state">No map features available. Areas without data are unknown, not safe.</div>}
      </div>
    </section>
  );
}

/* ===================================================================
   Handover Workspace
   =================================================================== */
function HandoverWorkspace({ busy, setBusy, setError, workspaceMode }: { busy: boolean; setBusy: (value: boolean) => void; setError: (value: string) => void; workspaceMode: "live" | "synthetic" | "mixed" }) {
  const [sitrep, setSitrep] = useState<{ reports: number; by_type: Record<string, number>; summary_hash: string } | null>(null);
  const [exercise, setExercise] = useState<{ record_count: number; future_records_excluded: number; scenario_signals: string[]; result_hash: string; synthetic: boolean } | null>(null);
  const [pilot, setPilot] = useState<PilotStatus | null>(null);
  const [tabletop, setTabletop] = useState<TabletopExercise | null>(null);
  const [agency, setAgency] = useState("District Emergency Operations Centre");
  const [district, setDistrict] = useState("Kamrup Metropolitan");
  async function exportSitrep() { setBusy(true); setError(""); try { setSitrep(await createSitrep(await listEvidenceReports())); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not generate shift report"); } finally { setBusy(false); } }
  async function exerciseReplay() { setBusy(true); setError(""); try { setExercise(await runExerciseReplay(workspaceMode === "synthetic")); } catch (reason) { setError(reason instanceof Error ? reason.message : "Exercise replay failed"); } finally { setBusy(false); } }
  async function setupPilot(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await configurePilot({ agency_name: agency, district_name: district, country_code: "IN", approved_feed_ids: ["district_control_room"] }); setPilot(await getPilotStatus()); } catch (reason) { setError(reason instanceof Error ? reason.message : "Pilot setup failed"); } finally { setBusy(false); } }
  async function tabletopExercise() { setBusy(true); setError(""); try { setTabletop(await runPilotTabletop(workspaceMode === "synthetic")); } catch (reason) { setError(reason instanceof Error ? reason.message : "Training exercise failed"); } finally { setBusy(false); } }
  return (
    <section className="workspace-section" aria-label="Handover & training">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Shift Handover & Training</p>
          <h2>Shift Reports & Exercises</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>Generate end-of-shift summaries and run training exercises with synthetic data.</p>
        </div>
        <span className="badge"><span className="badge-dot warning" />Training mode only</span>
      </div>
      <div style={{display: "flex", gap: "0.75rem", flexWrap: "wrap"}}>
        <button type="button" className="btn-primary" disabled={busy} onClick={() => void exportSitrep()}>Generate Shift Report</button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => void exerciseReplay()}>Run Synthetic Replay</button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => void tabletopExercise()}>Run Training Exercise</button>
      </div>
      <form className="approval-panel" onSubmit={(event) => void setupPilot(event)}>
        <input aria-label="Agency name" required value={agency} onChange={(event) => setAgency(event.target.value)} />
        <input aria-label="District name" required value={district} onChange={(event) => setDistrict(event.target.value)} />
        <button type="submit" className="btn-secondary" disabled={busy}>Set Pilot Boundaries</button>
      </form>
      {sitrep ? <div className="ops-card" style={{marginTop: "1rem"}}><h3>Shift Report Generated</h3><div className="ops-row"><strong>{sitrep.reports} reports included</strong><div className="ops-row-meta">{Object.entries(sitrep.by_type).map(([kind, count]) => `${kind}: ${count}`).join(" · ") || "No reports"}</div><div className="ops-row-meta">Integrity hash: {sitrep.summary_hash}</div></div></div> : null}
      {exercise ? <div className="ops-card" style={{marginTop: "0.75rem"}}><h3>Replay Results</h3><div className="ops-row"><strong>{exercise.record_count} synthetic records · {exercise.future_records_excluded} future excluded</strong><div className="ops-row-meta">Signals: {exercise.scenario_signals.join(", ")}</div><div className="ops-row-meta">Hash: {exercise.result_hash}</div></div></div> : null}
      {pilot?.configuration ? <div className="ops-card" style={{marginTop: "0.75rem"}}><h3>Pilot Configuration</h3><div className="ops-row"><strong>{pilot.configuration.agency_name} · {pilot.configuration.district_name}</strong><div className="ops-row-meta">Feeds: {pilot.configuration.approved_feed_ids.join(", ")} · {pilot.retention_enforcement}</div><div className="ops-row-meta">Identity: {pilot.identity_mode}</div></div></div> : null}
      {tabletop ? <div className="ops-card" style={{marginTop: "0.75rem"}}><h3>Training Exercise Results</h3><div className="ops-row"><strong>Faults tested: {tabletop.faults.join(" · ")}</strong><div className="ops-row-meta">Verification {tabletop.metrics.verification_time_minutes}m · Wrong dispatches {tabletop.metrics.wrong_dispatches} · Duplicates prevented {tabletop.metrics.duplicate_missions_prevented} · Coverage gaps {tabletop.metrics.coverage_gaps_surfaced} · Sync delay {tabletop.metrics.sync_delay_minutes}m · Actions {tabletop.metrics.operator_actions}</div><div className="ops-row-meta">Hash: {tabletop.result_hash}</div></div></div> : null}
    </section>
  );
}

/* ===================================================================
   Resources Workspace (Requirement 5)
   =================================================================== */
function ResourcesWorkspace({ setError }: { setError: (value: string) => void }) {
  const [resources, setResources] = useState<Array<{ id: string; name: string; readiness: string; feasibility?: string; category?: string }>>([]);
  const [activeCategory, setActiveCategory] = useState<string>("all");

  useEffect(() => {
    void listResources()
      .then((items) => {
        // Enriched mapping with asset categories and feasibility
        const enriched = items.map((r) => {
          const nameLower = r.name.toLowerCase();
          let category = "other";
          if (nameLower.includes("boat")) category = "boat";
          else if (nameLower.includes("med")) category = "medical_team";
          else if (nameLower.includes("excavat")) category = "excavator";
          else if (nameLower.includes("sar") || nameLower.includes("search")) category = "sar_team";
          else if (nameLower.includes("water")) category = "water_team";
          else if (nameLower.includes("power") || nameLower.includes("gen")) category = "power_unit";

          let feasibility = "feasible";
          if (r.readiness.toLowerCase() !== "ready") {
            feasibility = nameLower.includes("excavat") ? "infeasible" : "constrained";
          } else if (nameLower.includes("med")) {
            feasibility = "constrained";
          }

          return { ...r, category, feasibility };
        });
        setResources(enriched);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load resources"));
  }, [setError]);

  const categories = [
    { key: "all", label: `All Assets (${resources.length})` },
    { key: "boat", label: "Boats" },
    { key: "medical_team", label: "Medical Teams" },
    { key: "excavator", label: "Excavators" },
    { key: "sar_team", label: "SAR Teams" },
    { key: "water_team", label: "Water Teams" },
  ];

  const filteredResources = resources.filter((r) => activeCategory === "all" || r.category === activeCategory);

  const getFeasibilityBadge = (f?: string) => {
    const status = (f || "feasible").toLowerCase();
    if (status === "feasible") return { label: "FEASIBLE", color: "var(--status-success)", border: "rgba(16,185,129,0.3)", bg: "var(--status-success-bg)" };
    if (status === "constrained") return { label: "CONSTRAINED", color: "var(--status-warning)", border: "rgba(245,158,11,0.3)", bg: "var(--status-warning-bg)" };
    if (status === "infeasible") return { label: "INFEASIBLE", color: "var(--status-critical)", border: "rgba(239,68,68,0.3)", bg: "var(--status-critical-bg)" };
    return { label: "UNKNOWN", color: "#8b5cf6", border: "rgba(139,92,246,0.3)", bg: "rgba(139,92,246,0.1)" };
  };

  return (
    <section className="workspace-section" aria-label="Resources">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Resource Feasibility</p>
          <h2>Assets, Teams &amp; Readiness</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>
            Audit asset availability across Boats, Medical Teams, Excavators, and SAR Teams with feasibility tracking.
          </p>
        </div>
        <span className="badge">{resources.length} resources tracked</span>
      </div>

      <div style={{display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap"}}>
        {categories.map((c) => (
          <button
            key={c.key}
            type="button"
            className={activeCategory === c.key ? "btn-primary" : "btn-secondary"}
            onClick={() => setActiveCategory(c.key)}
            style={{fontSize: "0.75rem", padding: "0.35rem 0.75rem"}}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div className="ops-card" style={{marginTop: "1rem"}}>
        <h3>Tracked Assets &amp; Feasibility</h3>
        <div className="ops-list">
          {filteredResources.length ? filteredResources.map((resource) => {
            const badge = getFeasibilityBadge(resource.feasibility);
            return (
              <div className="ops-row" key={resource.id}>
                <div className="ops-row-header" style={{display: "flex", justifyContent: "space-between", alignItems: "center"}}>
                  <div>
                    <strong>{resource.name}</strong>
                    <div style={{fontSize: "0.7rem", color: "var(--text-dim)", textTransform: "capitalize"}}>
                      Category: {resource.category?.replaceAll("_", " ") || "Resource"}
                    </div>
                  </div>
                  <div style={{display: "flex", gap: "0.4rem", alignItems: "center"}}>
                    <span className={`ops-row-status ${resource.readiness.toLowerCase() === "ready" ? "active" : "warning"}`}>{resource.readiness}</span>
                    <span style={{fontSize: "0.65rem", fontWeight: 800, padding: "0.2rem 0.5rem", borderRadius: "4px", background: badge.bg, border: `1px solid ${badge.border}`, color: badge.color}}>
                      {badge.label}
                    </span>
                  </div>
                </div>
              </div>
            );
          }) : <div className="empty-state">No resources found matching this category.</div>}
        </div>
      </div>
    </section>
  );
}

/* ===================================================================
   Logistics (Sustainment) Workspace (Requirement 6)
   =================================================================== */
function SustainmentWorkspace({ setError }: { setError: (value: string) => void }) {
  const [forecasts, setForecasts] = useState<WorkspaceData["forecasts"]>([]);
  const [requests, setRequests] = useState<WorkspaceData["resourceRequests"]>([]);

  // 5-tier route observations (Requirement 6)
  const routes = [
    { corridor: "NH-27 Highway West Corridor", state: "Open", reason: "Cleared for heavy vehicles & relief transport.", speed: "Normal (50 km/h)" },
    { corridor: "NH-27 Km 18 Bridge Crossing", state: "Blocked", reason: "Bridge washed out. Lowbed excavators and trucks cannot pass.", speed: "Impasse" },
    { corridor: "East Sector Feeder Road", state: "Degraded", reason: "Waterlogged secondary road. Accessible by 4x4 / tractors only.", speed: "15 km/h" },
    { corridor: "Dharapur Approach Road", state: "Unknown", reason: "INFORMATION GAP: 0 reports from sector. Reconnaissance needed.", speed: "Unverified" },
    { corridor: "South River Embankment Bund", state: "High Risk", reason: "Structural weakening. Danger of secondary breach under load.", speed: "Emergency only" },
  ];

  useEffect(() => {
    void Promise.all([listResourceForecasts(), listResourceRequests()])
      .then(([nextForecasts, nextRequests]) => { setForecasts(nextForecasts); setRequests(nextRequests); })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load logistics data"));
  }, [setError]);

  const getRouteBadge = (state: string) => {
    switch (state.toLowerCase()) {
      case "open": return { color: "var(--status-success)", border: "rgba(16,185,129,0.3)", bg: "var(--status-success-bg)" };
      case "blocked": return { color: "var(--status-critical)", border: "rgba(239,68,68,0.3)", bg: "var(--status-critical-bg)" };
      case "degraded": return { color: "var(--status-warning)", border: "rgba(245,158,11,0.3)", bg: "var(--status-warning-bg)" };
      case "high risk": return { color: "#ef4444", border: "rgba(239,68,68,0.5)", bg: "rgba(239,68,68,0.15)" };
      default: return { color: "#8b5cf6", border: "rgba(139,92,246,0.3)", bg: "rgba(139,92,246,0.1)" };
    }
  };

  return (
    <section className="workspace-section" aria-label="Logistics">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Supply &amp; Route Feasibility</p>
          <h2>Logistics &amp; Route Feasibility</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>
            Assess route accessibility (<strong>Open</strong>, <strong>Blocked</strong>, <strong>Degraded</strong>, <strong>Unknown</strong>, <strong>High Risk</strong>) alongside supply forecasts.
          </p>
        </div>
        <span className="badge">{routes.length} corridors · {forecasts.length + requests.length} items</span>
      </div>

      {/* 5-TIER ROUTE FEASIBILITY BOARD (Requirement 6) */}
      <div className="ops-card" style={{marginBottom: "1rem"}}>
        <h3>Transportation Route Feasibility Board</h3>
        <div className="ops-list">
          {routes.map((r) => {
            const badge = getRouteBadge(r.state);
            return (
              <div className="ops-row" key={r.corridor}>
                <div className="ops-row-header" style={{display: "flex", justifyContent: "space-between", alignItems: "center"}}>
                  <div>
                    <strong>{r.corridor}</strong>
                    <div className="ops-row-meta">{r.reason}</div>
                  </div>
                  <div style={{textAlign: "right"}}>
                    <span style={{fontSize: "0.65rem", fontWeight: 800, padding: "0.2rem 0.55rem", borderRadius: "4px", background: badge.bg, border: `1px solid ${badge.border}`, color: badge.color, textTransform: "uppercase"}}>
                      {r.state}
                    </span>
                    <div style={{fontSize: "0.65rem", color: "var(--text-dim)", marginTop: "0.2rem"}}>{r.speed}</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="ops-card">
        <h3>Supply Forecasts &amp; Aid Requests</h3>
        <div className="ops-list">
          {forecasts.map((forecast) => (
            <div className="ops-row" key={forecast.forecast_id}>
              <strong>{forecast.resource_type}</strong>
              <div className="ops-row-meta">Projected: {forecast.projected_quantity} · Reserve floor: {forecast.reserve_floor} · Runway: {forecast.hours_to_reserve ?? "unknown"} h</div>
            </div>
          ))}
          {requests.map((request) => (
            <div className="ops-row" key={request.request_id}>
              <strong>Aid request: {request.quantity} {request.resource_type}</strong>
              <div className="ops-row-meta">{request.location} · Need by {request.need_by} · {request.status}</div>
            </div>
          ))}
          {!forecasts.length && !requests.length ? <div className="empty-state">No active aid requests. All local stocks currently tracking normal.</div> : null}
        </div>
      </div>
    </section>
  );
}

/* ===================================================================
   Mission Lifecycle Controls
   =================================================================== */
function MissionLifecycleControls({ task, busy, onChanged, setBusy, setError }: { task: { id: string; status: string }; busy: boolean; onChanged: () => Promise<void>; setBusy: (value: boolean) => void; setError: (value: string) => void }) {
  const [outcome, setOutcome] = useState("");
  async function advance(status: "acknowledged" | "en_route" | "on_scene" | "paused") { setBusy(true); setError(""); try { if (!navigator.onLine) { await queueTaskUpdate(task.id, status); setError(`Offline: "${status.replaceAll("_", " ")}" saved locally.`); return; } await advanceLiveTask(task.id, status); await onChanged(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Update failed"); } finally { setBusy(false); } }
  async function complete() { if (!outcome.trim()) return; setBusy(true); setError(""); try { if (!navigator.onLine) { await queueTaskUpdate(task.id, "completed", { action_type_evidence: outcome.trim() }); setError("Offline: completion saved locally."); return; } await completeLiveTask(task.id, outcome.trim()); await onChanged(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not complete mission"); } finally { setBusy(false); } }
  if (task.status === "assigned") return <><button type="button" className="btn-primary" disabled={busy} onClick={() => void advance("acknowledged")}>Acknowledge Task</button><button type="button" className="btn-secondary" onClick={() => printTaskPacket({ id: task.id, resource: "Assigned resource", status: task.status })}>Print Task Sheet</button></>;
  if (task.status === "acknowledged") return <button type="button" className="btn-primary" disabled={busy} onClick={() => void advance("en_route")}>Mark En Route</button>;
  if (task.status === "en_route") return <><button type="button" className="btn-primary" disabled={busy} onClick={() => void advance("on_scene")}>Arrived On Scene</button><button type="button" className="btn-danger" disabled={busy} onClick={() => void advance("paused")}>Pause</button></>;
  if (task.status === "paused") return <button type="button" className="btn-secondary" disabled={busy} onClick={() => void advance("en_route")}>Resume Mission</button>;
  if (task.status === "on_scene") return <div className="approval-panel"><input aria-label="Completion notes" required placeholder="What was done? (completion evidence)" value={outcome} onChange={(event) => setOutcome(event.target.value)} /><button type="button" className="btn-primary" disabled={busy || !outcome.trim()} onClick={() => void complete()}>Complete & Record</button><button type="button" className="btn-danger" disabled={busy} onClick={() => void advance("paused")}>Pause</button></div>;
  return null;
}

/* ===================================================================
   Missions Workspace
   =================================================================== */
function MissionsWorkspace({ incident, busy, setBusy, setError }: { incident: CommandIncident | null; busy: boolean; setBusy: (value: boolean) => void; setError: (value: string) => void }) {
  const [reports, setReports] = useState<EvidenceReport[]>([]); const [missions, setMissions] = useState<Mission[]>([]); const [resources, setResources] = useState<Array<{ id: string; name: string; readiness: string }>>([]);  const [reportId, setReportId] = useState(""); const [objective, setObjective] = useState("");
  const refresh = async () => { const [nextReports, nextMissions, nextResources] = await Promise.all([listEvidenceReports(), listMissions(), listResources()]); setReports(nextReports); setMissions(nextMissions); setResources(nextResources.filter((resource) => resource.readiness === "ready")); };
  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load missions")); }, []);
  async function create(event: FormEvent) { event.preventDefault(); if (!incident) return; setBusy(true); setError(""); try { await createMission({ source_report_id: reportId, source_incident_id: incident.incident_id, objective, destination: reports.find((report) => report.id === reportId)?.location?.place_text ?? "", required_capability: "" }); setObjective(""); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create mission"); } finally { setBusy(false); } }
  async function approve(mission: Mission, resourceId: string) { setBusy(true); setError(""); try { await approveMission(mission.mission_id, resourceId); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not approve mission"); } finally { setBusy(false); } }
  return (
    <section className="workspace-section" aria-label="Missions">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Mission Control</p>
          <h2>Field Operations</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>Create missions from verified reports, assign resources, and track progress.</p>
        </div>
        <span className="badge"><span className="badge-dot warning" />Commander approval required</span>
      </div>
      {incident ? (
        <form className="approval-panel" onSubmit={(event) => void create(event)}>
          <select aria-label="Source report" required value={reportId} onChange={(event) => setReportId(event.target.value)}>
            <option value="">Select a verified report...</option>
            {reports.map((report) => <option key={report.id} value={report.id}>{report.report_type.replaceAll("_", " ")} · {report.location?.place_text ?? "Unknown location"}</option>)}
          </select>
          <input aria-label="Mission objective" required placeholder="What needs to be done?" value={objective} onChange={(event) => setObjective(event.target.value)} />
          <button type="submit" className="btn-primary" disabled={busy || !reportId}>Create Mission</button>
        </form>
      ) : <div className="empty-state" style={{background: "var(--bg-panel)", borderRadius: "var(--radius-md)", margin: "0 0 1rem"}}>Activate an incident first to create missions.</div>}
      <div className="ops-card" style={{marginTop: "1rem"}}>
        <h3>Active Missions ({missions.length})</h3>
        <div className="ops-list">
          {missions.length ? missions.map((mission) => (
            <div className="ops-row" key={mission.mission_id}>
              <div className="ops-row-header">
                <span className="ops-row-title">{mission.title}</span>
                <span className={`ops-row-status ${mission.task ? "active" : "warning"}`}>{mission.task?.status ?? mission.status}</span>
              </div>
              <div className="ops-row-meta">Source: {mission.source_report_id} · {mission.destination ?? "No destination"}</div>
              {mission.status === "queued" && !mission.task ? (
                <select aria-label={`Assign resource for ${mission.title}`} disabled={busy} defaultValue="" onChange={(event) => { if (event.target.value) void approve(mission, event.target.value); }} style={{marginTop: "0.5rem"}}>
                  <option value="">Select a ready resource to assign...</option>
                  {resources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name}</option>)}
                </select>
              ) : null}
              {mission.task ? <MissionLifecycleControls task={mission.task} busy={busy} onChanged={refresh} setBusy={setBusy} setError={setError} /> : null}
            </div>
          )) : <div className="empty-state">No missions yet. Create one from a verified report above.</div>}
        </div>
      </div>
    </section>
  );
}

/* ===================================================================
   Incident Gate — now with clear labels
   =================================================================== */
function IncidentGate({ incident, busy, onActivate }: { incident: CommandIncident | null; busy: boolean; onActivate: (input: { name: string; hazard_type: string; severity: string; summary: string; event_time: string }) => void }) {
  const [name, setName] = useState("");
  const [summary, setSummary] = useState("");
  if (incident) return (
    <div className="state-banner" role="status">
      <div><strong>{incident.name}</strong> · {incident.hazard_type.toUpperCase()} · {incident.operational_period} · {incident.phase.replaceAll("_", " ")} · {incident.severity.toUpperCase()}</div>
      <span>Commander: {incident.roles.incident_commander ?? "unassigned"}</span>
    </div>
  );
  return (
    <section className="workspace-section" style={{marginBottom: "2rem"}}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Get Started</p>
          <h2>No Active Incident</h2>
        </div>
      </div>
      <form className="approval-panel" onSubmit={(event) => { event.preventDefault(); onActivate({ name, hazard_type: "multi_hazard", severity: "critical", summary, event_time: new Date().toISOString() }); }}>
        <input aria-label="Incident name" required placeholder="Give this incident a name" value={name} onChange={(event) => setName(event.target.value)} style={{background: "var(--bg-panel)", color: "var(--text-main)", border: "1px solid var(--border-light)", padding: "0.65rem", borderRadius: "var(--radius-sm)"}} />
        <input aria-label="Situation summary" required placeholder="Brief description of the situation" value={summary} onChange={(event) => setSummary(event.target.value)} style={{background: "var(--bg-panel)", color: "var(--text-main)", border: "1px solid var(--border-light)", padding: "0.65rem", borderRadius: "var(--radius-sm)", flexGrow: 1}} />
        <button type="submit" className="btn-primary" disabled={busy}>Activate Incident</button>
      </form>
    </section>
  );
}

/* ===================================================================
   Sector Board
   =================================================================== */
function SectorBoard({ incident, sectors, busy, onCreate }: { incident: CommandIncident | null; sectors: IncidentSector[]; busy: boolean; onCreate: (input: { name: string; owner_actor_id: string }) => void }) {
  const [name, setName] = useState("");
  if (!incident) return null;
  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Area Management</p>
          <h2>Operational Sectors</h2>
        </div>
      </div>
      <div style={{display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", marginBottom: "1rem"}}>
        {sectors.map(s => (
          <div key={s.sector_id} className="ops-card" style={{padding: "1rem", marginBottom: 0}}>
            <strong style={{color: "var(--accent-cyan)"}}>{s.name}</strong>
            <div style={{fontSize: "0.75rem", color: "var(--text-dim)", marginTop: "0.35rem"}}>Owner: {s.owner_actor_id}</div>
          </div>
        ))}
      </div>
      <form className="approval-panel" onSubmit={(event) => { event.preventDefault(); onCreate({ name, owner_actor_id: "operator" }); setName(""); }}>
        <input aria-label="Sector name" required placeholder="New sector name" value={name} onChange={(event) => setName(event.target.value)} style={{background: "var(--bg-panel)", color: "var(--text-main)", border: "1px solid var(--border-light)", padding: "0.65rem", borderRadius: "var(--radius-sm)"}} />
        <button type="submit" className="btn-secondary" disabled={busy}>Add Sector</button>
      </form>
    </section>
  );
}

/* ===================================================================
   Signal Cards (Projections)
   =================================================================== */
function Signals({ data }: { data: WorkspaceData }) {
  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Situational Awareness</p>
          <h2>Current Threat Signals</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>Key indicators from field data. Red = critical, amber = watch, blue = tracking.</p>
        </div>
      </div>
      <div className="signal-grid">
        {data.projections.map((item) => {
          let statusClass = "status-info";
          if (item.state.includes("critical") || item.time.includes("+")) statusClass = "status-critical";
          else if (item.state.includes("expected") || item.state.includes("pressure")) statusClass = "status-warning";
          return (
            <article className={`signal-card ${statusClass}`} key={item.resource}>
              <span className="resource-name">{item.resource}</span>
              <strong className="metric">{item.time}</strong>
              <span className="state">{item.state}</span>
              <small className="freshness">{item.freshness}</small>
            </article>
          );
        })}
      </div>
      <div className="unknown-box" style={{marginTop: "1rem"}}>
        <strong>⚠ Unknowns Detected</strong>
        <p>Some data is contradictory or stale and needs verification. Unverified areas should not be treated as safe.</p>
      </div>
    </section>
  );
}

/* ===================================================================
   Recommendation (COA cards)
   =================================================================== */
function Recommendation({ flow, busy, act }: { flow: GoldenFlow; busy: boolean; act: (action: Action, selectedAction?: string, note?: string) => void }) {
  const status = flow.recommendation.status;
  const task = flow.data.tasks.find((item) => item.status !== "completed");
  const [selectedAction, setSelectedAction] = useState(flow.data.candidates[0]?.action);
  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Recommended Actions</p>
          <h2>What Should We Do?</h2>
          <p style={{color: "var(--text-dim)", fontSize: "0.8rem", marginTop: "0.25rem"}}>Ranked options based on current evidence. Select one and authorize it.</p>
        </div>
        <span className="badge">Auto-dispatch: {String(flow.recommendation.auto_dispatched).toUpperCase()}</span>
      </div>
      <div className="candidate-list">
        {flow.data.candidates.map((item) => (
          <article className="candidate" key={item.action}>
            <div className="rank-box"><span className="rank">#{item.rank}</span></div>
            <div className="content">
              <h3>{item.action}</h3>
              <div className="details-grid">
                <div className="detail-item"><strong>Expected Effect</strong><span>{item.effect}</span></div>
                <div className="detail-item"><strong>Resource Cost</strong><span>{item.cost}</span></div>
                <div className="detail-item"><strong>Confidence</strong><span>{item.confidence}</span></div>
                <div className="detail-item"><strong>Excluded</strong><span>{item.excluded}</span></div>
              </div>
              {status === "pending_approval" && (
                <div className="candidate-selector">
                  <label>
                    <input type="radio" name="selected-action" checked={selectedAction === item.action} onChange={() => setSelectedAction(item.action)} />
                    Select this option
                  </label>
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
      <div className="approval-panel">
        {status === "pending_approval" && (
          <>
            <button type="button" className="btn-primary" disabled={busy} onClick={() => act("approve", selectedAction)}>✓ Authorize Selected Option</button>
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => act("modify", selectedAction, "Commander modified parameters")}>✎ Modify Directive</button>
            <button type="button" className="btn-danger" disabled={busy} onClick={() => act("reject", selectedAction)}>✗ Stand Down</button>
          </>
        )}
        {status === "approved" && !task && (
          <button type="button" className="btn-primary" disabled={busy} onClick={() => act("assign")}>Confirm Route & Deploy</button>
        )}
        {task?.status === "assigned" && <button type="button" className="btn-primary" disabled={busy} onClick={() => act("acknowledged")}>Acknowledge Task</button>}
        {task?.status === "acknowledged" && <button type="button" className="btn-primary" disabled={busy} onClick={() => act("en_route")}>Mark En Route</button>}
        {task?.status === "en_route" && <><button type="button" className="btn-primary" disabled={busy} onClick={() => act("on_scene")}>Arrived On Scene</button><button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")}>Pause</button></>}
        {task?.status === "on_scene" && <><button type="button" className="btn-primary" disabled={busy} onClick={() => act("completed")}>Mark Completed</button><button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")}>Pause</button></>}
        {task?.status === "paused" && <button type="button" className="btn-secondary" disabled={busy} onClick={() => act("en_route")}>Resume Mission</button>}
      </div>
    </section>
  );
}

/* ===================================================================
   Operations Panel
   =================================================================== */
function Operations({ flow }: { flow: GoldenFlow }) {
  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Operations Overview</p>
          <h2>Resources, Forecasts & Queue</h2>
        </div>
      </div>
      <div className="ops-dashboard">
        <div className="ops-column">
          <div className="ops-card"><h3>Active Resources</h3><div className="ops-list">{flow.data.resources.length ? flow.data.resources.map((item) => (<div className="ops-row" key={item.id}><div className="ops-row-header"><span className="ops-row-title">{item.name}</span><span className={`ops-row-status ${String(item.readiness).toLowerCase() === 'ready' ? 'active' : 'warning'}`}>{item.readiness}</span></div><div className="ops-row-meta">Task: {item.task || "Unassigned"}</div></div>)) : <div className="empty-state">No resources deployed.</div>}</div></div>
          <div className="ops-card"><h3>Supply Forecasts</h3><div className="ops-list">{flow.data.forecasts.length ? flow.data.forecasts.map((item) => (<div className="ops-row" key={item.forecast_id}><div className="ops-row-header"><span className="ops-row-title">{item.resource_type} | {item.location}</span></div><div className="ops-row-details">Available: {item.current_quantity} | Reserve: {item.reserve_floor}</div><div className="ops-row-meta" style={{color: item.request_recommended ? "var(--status-warning)" : "var(--status-success)"}}>{item.request_recommended ? `⚠ Request needed · ${item.hours_to_reserve ?? "?"}h to reserve` : "✓ Sufficient"}</div></div>)) : <div className="empty-state">No forecasts available.</div>}</div></div>
          <div className="ops-card"><h3>Aid Requests</h3><div className="ops-list">{flow.data.resourceRequests.length ? flow.data.resourceRequests.map((item) => (<div className="ops-row" key={item.request_id}><div className="ops-row-header"><span className="ops-row-title">{item.quantity} {item.resource_type}</span><span className={`ops-row-status ${item.status === 'draft' ? 'warning' : 'active'}`}>{item.status}</span></div><div className="ops-row-details">{item.location} | Source: {item.source_reality}</div><div className="ops-row-meta" style={{color: "var(--accent-cyan)"}}>Needed by: {item.need_by}</div></div>)) : <div className="empty-state">No aid requests.</div>}</div></div>
        </div>
        <div className="ops-column">
          <div className="ops-card"><h3>Coverage & Data Gaps</h3><div className="ops-list">{flow.data.verification.length ? flow.data.verification.map((item) => (<div className="ops-row" key={`${item.cell_id}:${item.fact_type}`}><div className="ops-row-header"><span className="ops-row-title">#{item.rank} | Cell: {item.cell_id}</span><span className="ops-row-status active">{item.debt_band} DEBT</span></div><div className="ops-row-details">Population: {item.population.toLocaleString()} | {item.reporting_impaired ? "⚠ Reporting impaired" : "Reporting active"}</div><div className="ops-row-meta">Impact: {item.decision_impact_score.toFixed(2)} | {item.what_answer_changes}</div></div>)) : <div className="empty-state">No coverage data mapped.</div>}</div></div>
          <div className="ops-card"><h3>Strategic Unlocks</h3><div className="ops-list">{flow.data.unlocks.length ? flow.data.unlocks.map((item) => (<div className="ops-row" key={item.target_node_id}><div className="ops-row-header"><span className="ops-row-title">#{item.rank} | {item.action}</span><span className="ops-row-status active">VALUE {item.mission_unlock_value.toFixed(2)}</span></div><div className="ops-row-details">Downstream: {item.downstream_nodes_unlocked.join(", ") || "none"}</div><div className="ops-row-meta">Missions: {item.missions_unlocked.join(", ") || "none"}</div></div>)) : <div className="empty-state">No unlocks available.</div>}</div></div>
          <div className="ops-card"><h3>Plan Assumptions</h3><div className="ops-list">{flow.data.plans.length ? flow.data.plans.map((item) => (<div className="ops-row" key={item.plan_id}><div className="ops-row-header"><span className="ops-row-title">{item.objective_summary}</span><span className={`ops-row-status ${item.status === 'review_required' ? 'warning' : 'active'}`}>{item.status}</span></div><div className="ops-row-details">Fragility: {item.fragility.toFixed(2)}</div><div className="ops-row-meta">{item.assumptions.map((a) => `${a.subject_type}:${a.subject_id}=${a.expected_state}(${a.sensitivity})`).join(" · ")}</div></div>)) : <div className="empty-state">No plans loaded.</div>}</div></div>
          <div className="ops-card"><h3>Task Queue</h3><div className="ops-list">{flow.data.queue.length ? flow.data.queue.map((item) => (<div className="ops-row" key={item.id}><div className="ops-row-header"><span className="ops-row-title">{item.title}</span><span className="ops-row-status active">{item.status}</span></div></div>)) : <div className="empty-state">Queue empty.</div>}{flow.data.tasks.length ? flow.data.tasks.map((item) => (<div className="ops-row" key={item.id}><div className="ops-row-header"><span className="ops-row-title">{item.resource}</span><span className="ops-row-status warning">{item.status}</span></div><div className="ops-row-details">{item.outcome || "Outcome pending..."}</div></div>)) : null}</div></div>
        </div>
      </div>
      <div className="audit-panel">
        <strong>Audit Trail</strong>
        {flow.audit.length ? flow.audit.map((item, index) => (
          <span key={index}> {String(item.event)}{index < flow.audit.length - 1 && <span className="audit-arrow">→</span>}</span>
        )) : " No events recorded."}
      </div>
    </section>
  );
}

/* ===================================================================
   Plan Alerts
   =================================================================== */
function PlanAlerts({ plans }: { plans: WorkspaceData["plans"] }) {
  const affected = plans.filter((plan) => plan.status === "review_required");
  if (!affected.length) return null;
  return (
    <div className="state-banner state-error" role="alert">
      <strong>⚠ {affected.length} plan{affected.length === 1 ? "" : "s"} need attention:</strong>
      <span>{affected.map((plan) => plan.objective_summary).join(" | ")}</span>
    </div>
  );
}

/* ===================================================================
   Mutual Aid Approval
   =================================================================== */
function MutualAidApproval({ flow, busy, onApprove }: { flow: GoldenFlow; busy: boolean; onApprove: (requestId: string) => void }) {
  const drafts = flow.data.resourceRequests.filter((item) => item.status === "draft");
  if (!drafts.length) return null;
  return (
    <section className="workspace-section" aria-label="Aid requests needing approval">
      <div className="section-heading">
        <div>
          <p className="eyebrow" style={{color: "var(--status-warning)"}}>Action Needed</p>
          <h2>Aid Requests Awaiting Approval</h2>
        </div>
      </div>
      {drafts.map((item) => (
        <div className="approval-panel" key={item.request_id} style={{borderColor: "rgba(245,158,11,0.3)", background: "var(--status-warning-bg)"}}>
          <div style={{flexGrow: 1}}>
            <h3 style={{margin: "0 0 0.35rem 0", color: "var(--status-warning)", fontSize: "1rem"}}>{item.quantity} {item.resource_type} for {item.location}</h3>
            <div style={{fontSize: "0.8rem", color: "var(--text-muted)"}}>Needed by: <strong style={{color: "var(--text-main)"}}>{item.need_by}</strong> | Reserve: {item.reserve_floor}</div>
          </div>
          <button type="button" className="btn-primary" style={{background: "var(--status-warning)", borderColor: "var(--status-warning)", color: "#000"}} disabled={busy} onClick={() => onApprove(item.request_id)}>
            Send Request
          </button>
        </div>
      ))}
    </section>
  );
}

/* ===================================================================
   MAIN COMPONENT: OperatorWorkspace
   =================================================================== */
export function OperatorWorkspace() {
  const [incident, setIncident] = useState<CommandIncident | null>(null);
  const [sectors, setSectors] = useState<IncidentSector[]>([]);
  const [flow, setFlow] = useState<GoldenFlow | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "offline" | "error">("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeView, setActiveView] = useState<WorkspaceView>("Command");
  const [showBriefingModal, setShowBriefingModal] = useState(false);
  const [guidedStep, setGuidedStep] = useState(0);
  const [showPausedLanding, setShowPausedLanding] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [workspaceMode, setWorkspaceModeState] = useState<"live"|"synthetic"|"mixed">("live");
  const [feedHealth, setFeedHealth] = useState<Record<string, string>>({});
  const [lastFeedSync, setLastFeedSync] = useState<string | null>(null);
  const updateCursorRef = useRef<string | null>(null);
  const lastSuccessfulPollRef = useRef<number | null>(null);
  const [updateHealth, setUpdateHealth] = useState<UpdateHealthState>("connecting");
  const [updateError, setUpdateError] = useState("");
  const [lastOperationalUpdate, setLastOperationalUpdate] = useState<string | null>(null);
  const [lastUpdateProvenance, setLastUpdateProvenance] = useState<{ source: string; source_class: string; entity_type: string; entity_id: string } | null>(null);
  const [lastOperationalPoll, setLastOperationalPoll] = useState<string | null>(null);
  const [sectionRefresh, setSectionRefresh] = useState<Record<RefreshSection, number>>({ command: 0, map: 0, reports: 0, missions: 0, resources: 0 });

  useEffect(() => {
    if (!sidebarOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSidebarOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [sidebarOpen]);

  async function load() {
    setState("loading");
    setError("");
    try {
      const { getWorkspaceMode } = await import("./api");
      const modeData = await getWorkspaceMode();
      setWorkspaceModeState(modeData.mode as any);
      setFeedHealth(modeData.health_status || {});
      setLastFeedSync(modeData.last_sync_time || null);

      const activeIncident = await getActiveIncident();
      setIncident(activeIncident);
      setShowPausedLanding(activeIncident?.status === "paused");
      setSectors(activeIncident ? await listIncidentSectors(activeIncident.incident_id) : []);
      setFlow(null);
      const resolvedMode = modeData?.mode as "live" | "synthetic" | "mixed" | undefined;
      if (!activeIncident && new URLSearchParams(window.location.search).get("mode") === "tabletop") {
        const f = await resetGoldenFlow(resolvedMode === "synthetic").catch(() => null);
        if (f) setFlow(f);
        setActiveView("Command");
        setGuidedStep(1);
      } else if (resolvedMode === "live" || resolvedMode === "mixed") {
        const liveFlow = await getLiveDecisionFlow();
        if (liveFlow) setFlow(liveFlow);
      }
      setState("ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Backend unavailable; operational state was not loaded.");
      setState("ready");
    }
  }

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (state !== "ready") return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      if (cancelled) return;
      try {
        const page = await pollOperationalUpdates(updateCursorRef.current, 50);
        if (cancelled) return;
        updateCursorRef.current = page.next_cursor;
        if (page.freshness?.state === "degraded" || page.availability?.state === "degraded") {
          setUpdateHealth(lastSuccessfulPollRef.current && Date.now() - lastSuccessfulPollRef.current > 45000 ? "stale" : "reconnecting");
          setUpdateError("Update feed is degraded; command sections may be stale.");
          return;
        }
        lastSuccessfulPollRef.current = Date.now();
        setLastOperationalPoll(new Date().toISOString());
        setUpdateHealth("connected");
        setUpdateError("");
        for (const event of page.items) {
          setLastOperationalUpdate((current) => !current || event.occurred_at > current ? event.occurred_at : current);
          setLastUpdateProvenance({ source: event.source || "unknown", source_class: event.source_class || "derived_model", entity_type: event.affected_entity_type || "aggregate", entity_id: event.affected_entity_id || String(event.payload?.id || "unknown") });
          setSectionRefresh((current) => {
            const next = { ...current };
            for (const section of affectedSectionsForUpdate(event.event_type)) next[section] += 1;
            return next;
          });
          if ((workspaceMode === "live" || workspaceMode === "mixed") && ["recommendation_changed", "resource_readiness_changed", "task_status_changed"].includes(event.event_type)) {
            void getLiveDecisionFlow().then((liveFlow) => {
              if (!cancelled && liveFlow) setFlow(liveFlow);
            }).catch(() => undefined);
          }
        }
      } catch (reason) {
        if (!cancelled) {
          setUpdateHealth(lastSuccessfulPollRef.current && Date.now() - lastSuccessfulPollRef.current > 45000 ? "stale" : "reconnecting");
          setUpdateError(reason instanceof Error ? reason.message : "Update feed unavailable");
        }
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), 10000);
      }
    };

    void poll();
    const staleTimer = window.setInterval(() => {
      if (lastSuccessfulPollRef.current && Date.now() - lastSuccessfulPollRef.current > 45000) {
        setUpdateHealth("stale");
      }
    }, 10000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
      window.clearInterval(staleTimer);
    };
  }, [state]);

  async function doSyncFeeds() {
    setBusy(true);
    try {
      const { syncLiveFeeds } = await import("./api");
      const result = await syncLiveFeeds();
      setFeedHealth(result.health_status);
      setLastFeedSync(result.last_sync_time);
      if (result.created_count > 0) {
        // reload workspace to fetch new reports
        await load();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to sync feeds");
    } finally {
      setBusy(false);
    }
  }

  async function changeMode(newMode: "live" | "synthetic" | "mixed") {
    setBusy(true);
    try {
      const { setWorkspaceMode } = await import("./api");
      await setWorkspaceMode(newMode);
      setWorkspaceModeState(newMode);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change mode");
    } finally {
      setBusy(false);
    }
  }


  async function activate(input: { name: string; hazard_type: string; severity: string; summary: string; event_time: string }) {
    setBusy(true);
    setError("");
    try {
      const active = await activateIncident(input);
      setIncident(active);
      setFlow(null);
      setShowPausedLanding(false);
      setSectors(await listIncidentSectors(active.incident_id));
      setActiveView("Command");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Incident was not created by the server.");
    } finally {
      setBusy(false);
    }
  }

  async function pauseCurrentIncident() {
    if (!incident || incident.status !== "active") return;
    setBusy(true);
    setError("");
    try {
      setIncident(await pauseIncident(incident.incident_id));
      setFlow(null);
      setActiveView("Command");
      setGuidedStep(0);
      setShowPausedLanding(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not pause incident");
    } finally {
      setBusy(false);
    }
  }

  async function resumePausedIncident() {
    if (!incident || incident.status !== "paused") return;
    setBusy(true);
    setError("");
    try {
      setIncident(await resumeIncident(incident.incident_id));
      setShowPausedLanding(false);
      setActiveView("Command");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not resume incident");
    } finally {
      setBusy(false);
    }
  }

  async function closePausedIncident() {
    if (!incident || incident.status !== "paused") return;
    setBusy(true);
    setError("");
    try {
      await closeIncident(incident.incident_id);
      setIncident(null);
      setSectors([]);
      setFlow(null);
      setShowPausedLanding(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not close incident");
    } finally {
      setBusy(false);
    }
  }

  async function createSector(input: { name: string; owner_actor_id: string }) {
    if (!incident) return;
    setBusy(true);
    setError("");
    try {
      const sector = await createIncidentSector(incident.incident_id, input);
      setSectors((current) => [...current, sector]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create sector");
    } finally {
      setBusy(false);
    }
  }

  async function startTraining() {
    setBusy(true);
    setError("");
    try {
      setFlow(await resetGoldenFlow(workspaceMode === "synthetic"));
      setActiveView("Command");
    } catch (reason) {
      if (workspaceMode !== "synthetic") {
        setError(reason instanceof Error ? reason.message : "Training fallback is available only in explicit synthetic mode.");
        return;
      }
      setFlow({
        source: "fallback",
        source_detail: "Synthetic fixture used only for explicit training mode",
        data: demoWorkspace,
        recommendation: {
          id: "rec_demo_offline",
          status: "pending_approval",
          auto_dispatched: false,
          candidates: [
            {
              action: "deliver_or_treat_water",
              rank: 1,
              confidence: "medium",
              expected_operational_effect: "Adds or treats potable water before 3.5h runway expires.",
              resource_cost: { "water_team": 1.0, "power_kw": 4.0 },
              excluded_resources: {},
              priority_reason: "Safe-water runway in North Sector is 3.5h, below emergency 6.0h threshold with incoming population influx.",
              evidence_available: "Field sensor telemetry + drone reconnaissance (rpt_demo_01, rpt_demo_02).",
              important_unknowns: "INFORMATION GAP: Dharapur Village silent (0 reports, pop: 4,200).",
              resource_availability: "FEASIBLE: Synthetic Water Team Alpha & Rescue Boat 1 ready on scene.",
              route_accessibility: "NH-27 Highway Open; West Bank River Corridor Degraded / Blocked.",
              decision_model: { need: "Critical", confidence: "Medium", feasibility: "Feasible" }
            } as any,
            {
              action: "request_medicine_cold_chain_support",
              rank: 2,
              confidence: "low",
              expected_operational_effect: "Protects medicine and cold-chain reserve.",
              resource_cost: { "medical_support": 1.0 },
              excluded_resources: {},
              priority_reason: "Restores mission capability and access for downstream critical sectors.",
              evidence_available: "Infrastructure node dependency telemetry.",
              important_unknowns: "Structural damage extent pending ground reconnaissance.",
              resource_availability: "CONSTRAINED: Heavy excavator awaiting transport.",
              route_accessibility: "Route degraded by mud and debris.",
              decision_model: { need: "Medium", confidence: "Medium", feasibility: "Constrained" }
            } as any
          ],
          compatible_resources: [{ id: "res_348a10f74f374c47af445be276f0f3b8", name: "Synthetic Water Team Alpha" }]
        },
        audit: [{ event: "Tabletop Scenario Initialized: Brahmaputra Flood OP-1" }]
      });
      setActiveView("Command");
    } finally {
      setBusy(false);
    }
  }

  async function act(action: Action, selectedAction?: string, note?: string) {
    if (!flow) return;
    setBusy(true);
    setError("");
    try {
      setFlow(
        action === "approve" || action === "reject" || action === "modify"
          ? await decide(flow, action, selectedAction, note)
          : action === "assign"
          ? await assignApproved(flow)
          : await advanceTask(flow, action)
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action was not reconciled by the server; no operational state was changed in this view.");
    } finally {
      setBusy(false);
    }
  }

  async function approveRequest(requestId: string) {
    if (!flow) return;
    setBusy(true);
    setError("");
    try {
      setFlow(await approveMutualAid(flow, requestId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not approve aid request");
    } finally {
      setBusy(false);
    }
  }

  /* --- Loading state --- */
  if (state === "loading") return (
    <main className="shell" style={{display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh"}} aria-busy="true">
      <div style={{textAlign: "center"}}>
        <div className="sidebar-brand-icon" style={{width: 56, height: 56, fontSize: "1.5rem", margin: "0 auto 1rem"}} aria-hidden="true">D</div>
        <p style={{color: "var(--text-muted)"}} role="status" aria-live="polite">Connecting to DRISHTI…</p>
      </div>
    </main>
  );

  /* --- Error state --- */
  if (state === "error") return (
    <main className="shell" style={{display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", gap: "1.5rem"}}>
      <div style={{textAlign: "center"}}>
        <div style={{width: 56, height: 56, background: "var(--status-critical-bg)", borderRadius: "var(--radius-md)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 1rem", color: "var(--status-critical)", fontSize: "1.5rem"}}>!</div>
        <h2>Connection Failed</h2>
        <p style={{color: "var(--text-muted)", maxWidth: 400}}>{error}</p>
      </div>
      <div style={{display: "flex", gap: "0.75rem"}}>
        <button type="button" className="btn-primary" onClick={() => void load()}>Try Again</button>
        <button type="button" className="btn-secondary" onClick={() => setState("offline")}>Work Offline</button>
      </div>
    </main>
  );

  /* --- Offline fixture state --- */
  if (state === "offline") return (
    <main className="shell">
      <IncidentBar incident={incident} busy={busy} isSynthetic={false} />
      <div className="state-banner state-error" role="status" style={{marginBottom: "1.5rem"}}>
        <span>⚠ Working offline — no server-confirmed operational state is displayed</span>
      </div>
      <OfflineCommandCenter setError={setError} />
      <CommandBrief flow={null} busy={busy} act={act} setError={setError} workspaceMode="live" readOnly />
      <button type="button" className="btn-secondary" style={{marginTop: "2rem"}} onClick={() => void load()}>Reconnect to Server</button>
    </main>
  );

  /* --- Tabletop guided narration steps --- */
  const TABLETOP_STEPS = [
    { title: "Incident is active", narration: "The incident has been activated. You can see the name, severity, and commander in the header bar above.", target: "Top header bar", action: "Look at the incident status header." },
    { title: "Reading the signals", narration: "Field reports are coming in. Look at the threat signal cards — red means critical, amber means watch.", target: "Signal cards on the Dashboard", action: "Review the threat indicators." },
    { title: "The silent area", narration: "One area isn't reporting. That doesn't mean it's safe — DRISHTI keeps it visible so you don't forget about it.", target: "Map and coverage data", action: "Notice the unassessed areas." },
    { title: "Blocked route", narration: "A road is blocked. Just because a resource is nearby doesn't mean it can get there. DRISHTI checks route constraints.", target: "Resource and route info", action: "See why some resources are excluded." },
    { title: "Commander decides", narration: "You choose an action from the ranked options. If connectivity drops, your commands are saved locally.", target: "Action cards and offline indicator", action: "Authorize an action." },
    { title: "Outcome & handover", narration: "After the action completes, the situation updates. Remaining risks and unknowns are preserved for the next shift.", target: "Handover tab", action: "Review what happened." },
  ];

  /* --- Landing page (no incident, no flow) --- */
  if ((!incident || (incident.status === "paused" && showPausedLanding)) && !flow && !showBriefingModal) {
    return (
      <main className="shell">
        {error && <div className="state-banner state-error" role="alert">{error}</div>}

        <div className="landing-page">
          <div className="landing-hero">
            <div className="sidebar-brand-icon" style={{width: 64, height: 64, fontSize: "1.75rem", margin: "0 auto 1.5rem"}}>D</div>
            <h1>Welcome to DRISHTI</h1>
            <p>Disaster Response Intelligence System. Manage incidents, track field operations, and coordinate resources — all in one place.</p>
          </div>

          {showPausedLanding && incident ? (
            <div className="paused-incident-card">
              <div style={{flex: 1}}>
                <strong style={{color: "var(--status-warning)"}}>⏸ Paused: {incident.name}</strong>
                <p style={{color: "var(--text-muted)", fontSize: "0.85rem", margin: "0.25rem 0 0"}}>This incident is paused. Resume it or close it permanently.</p>
              </div>
              <div style={{display: "flex", gap: "0.5rem"}}>
                <button type="button" className="btn-primary" disabled={busy} onClick={() => void resumePausedIncident()}>Resume</button>
                <button type="button" className="btn-danger" disabled={busy} onClick={() => void closePausedIncident()}>Close</button>
              </div>
            </div>
          ) : (
            <div className="landing-actions">
              <button type="button" className="landing-action-card" disabled={busy} onClick={() => setShowBriefingModal(true)}>
                <div className="landing-card-icon">{icons.training}</div>
                <p className="landing-card-title">Start Training</p>
                <p className="landing-card-desc">Run a guided exercise with synthetic data to learn how the system works.</p>
              </button>
              <button type="button" className="landing-action-card" disabled={busy} onClick={() => void activate({ name: "New Incident", hazard_type: "multi_hazard", severity: "critical", summary: "Initial situation", event_time: new Date().toISOString() })}>
                <div className="landing-card-icon" style={{background: "var(--status-critical-bg)", color: "var(--status-critical)"}}>{icons.incident}</div>
                <p className="landing-card-title">Activate Incident</p>
                <p className="landing-card-desc">Start managing a real disaster event with live data and field coordination.</p>
              </button>
            </div>
          )}
        </div>
      </main>
    );
  }

  /* --- Briefing modal (before training starts) --- */
  if (showBriefingModal) {
    return (
      <div className="briefing-modal-backdrop">
        <div className="briefing-modal">
          <p className="eyebrow" style={{color: "var(--status-warning)"}}>Training Exercise — Synthetic Data Only</p>
          <h2 style={{fontSize: "1.5rem", marginBottom: "1.25rem"}}>Brahmaputra Flood: First 24 Hours</h2>
          <div style={{display: "flex", flexDirection: "column", gap: "0.85rem", marginBottom: "1.75rem", fontSize: "0.9rem", color: "var(--text-muted)", lineHeight: "1.5"}}>
            <div><strong style={{color: "var(--text-main)"}}>Scenario:</strong> Flooding, water contamination, reports from connected areas</div>
            <div><strong style={{color: "var(--text-main)"}}>Unknown:</strong> One high-risk settlement has gone silent — no communications</div>
            <div><strong style={{color: "var(--text-main)"}}>Variables:</strong> Road status, verification results, and resource availability can change</div>
            <div style={{background: "var(--status-warning-bg)", padding: "0.85rem", borderLeft: "3px solid var(--status-warning)", borderRadius: "var(--radius-sm)", color: "var(--status-warning)", fontSize: "0.85rem"}}>
              <strong>Safety rule:</strong> The system recommends actions, but a human commander must approve every critical decision.
            </div>
          </div>
          <div style={{display: "flex", gap: "0.75rem", justifyContent: "flex-end"}}>
            <button type="button" className="btn-secondary" onClick={() => setShowBriefingModal(false)}>Cancel</button>
            <button type="button" className="btn-primary" onClick={() => { setShowBriefingModal(false); setGuidedStep(1); void startTraining(); }}>Start Training</button>
          </div>
        </div>
      </div>
    );
  }

  /* --- Build the effective incident for display --- */
  const effectiveIncident = incident || (flow ? {
    incident_id: "demo",
    name: "Brahmaputra Flood",
    hazard_type: "multi_hazard",
    operational_period: "OP-1",
    phase: "Size-up",
    severity: "critical",
    roles: { incident_commander: "J. Vance" }
  } as any : null);

  /* --- Main app layout with sidebar --- */
  return (
    <div className="app-layout">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <AppSidebar activeView={activeView} onSelect={setActiveView} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      {sidebarOpen && <button type="button" className="sidebar-backdrop" aria-label="Close main navigation" onClick={() => setSidebarOpen(false)} />}

      <main id="main-content" className="app-main" tabIndex={-1}>
        <IncidentBar incident={effectiveIncident} busy={busy} isSynthetic={!!flow || workspaceMode === "synthetic"} workspaceMode={workspaceMode} onPause={!flow && incident?.status === "active" ? () => void pauseCurrentIncident() : undefined} onMenuClick={() => setSidebarOpen(!sidebarOpen)} menuOpen={sidebarOpen} />

        <div className="state-banner" style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-panel)", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
          <div style={{display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap"}}>
            <span style={{ fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", color: "var(--text-dim)", letterSpacing: "0.05em" }}>Data Feed:</span>
            <div className="feed-mode-selector" style={{ display: "inline-flex", background: "var(--bg-surface)", border: "1px solid var(--border-light)", borderRadius: "var(--radius-sm)", overflow: "hidden" }}>
              <button
                type="button"
                onClick={() => void changeMode("synthetic")}
                aria-label="Use synthetic tabletop data"
                aria-pressed={workspaceMode === "synthetic"}
                className="feed-mode-button"
                style={{
                  padding: "0.3rem 0.65rem",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                  background: workspaceMode === "synthetic" ? "var(--status-warning-bg)" : "transparent",
                  color: workspaceMode === "synthetic" ? "var(--status-warning)" : "var(--text-muted)"
                }}
              >
                ✦ Synthetic (Tabletop)
              </button>
              <button
                type="button"
                onClick={() => void changeMode("mixed")}
                aria-label="Use mixed operational and synthetic data"
                aria-pressed={workspaceMode === "mixed"}
                className="feed-mode-button"
                style={{
                  padding: "0.3rem 0.65rem",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  border: "none",
                  borderLeft: "1px solid var(--border-light)",
                  cursor: "pointer",
                  background: workspaceMode === "mixed" ? "var(--accent-primary-glow)" : "transparent",
                  color: workspaceMode === "mixed" ? "var(--accent-cyan)" : "var(--text-muted)"
                }}
              >
                Mixed Mode
              </button>
              <button
                type="button"
                onClick={() => void changeMode("live")}
                aria-label="Use live operational feeds"
                aria-pressed={workspaceMode === "live"}
                className="feed-mode-button"
                style={{
                  padding: "0.3rem 0.65rem",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  border: "none",
                  borderLeft: "1px solid var(--border-light)",
                  cursor: "pointer",
                  background: workspaceMode === "live" ? "var(--status-success-bg)" : "transparent",
                  color: workspaceMode === "live" ? "var(--status-success)" : "var(--text-muted)"
                }}
              >
                Live Feeds
              </button>
            </div>
            {lastFeedSync && (workspaceMode === "live" || workspaceMode === "mixed") && (
              <span style={{ fontSize: "0.75rem", color: "var(--text-dim)" }}>
                &middot; Sync: {new Date(lastFeedSync).toLocaleTimeString()}
              </span>
            )}
            <span className={`update-health update-health-${updateHealth}`} role="status" aria-live="polite">
              <span className="update-health-dot" aria-hidden="true" />
              Updates: {updateHealth}
              {lastOperationalUpdate ? ` · Last updated ${new Date(lastOperationalUpdate).toLocaleTimeString()}` : ""}
              {!lastOperationalUpdate && lastOperationalPoll ? ` · Last checked ${new Date(lastOperationalPoll).toLocaleTimeString()}` : ""}
              {lastUpdateProvenance ? ` · Provenance ${lastUpdateProvenance.source_class.replaceAll("_", " ")} (${lastUpdateProvenance.entity_type}:${lastUpdateProvenance.entity_id})` : ""}
              {updateError ? ` · ${updateError}` : ""}
            </span>
          </div>
          {(workspaceMode === "live" || workspaceMode === "mixed") && (
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => void doSyncFeeds()} style={{fontSize: "0.75rem", padding: "0.35rem 0.75rem"}}>
              {busy ? "Syncing..." : "Sync Live Data"}
            </button>
          )}
        </div>

        <OfflineCommandCenter setError={setError} mission={flow?.data.tasks.find((task) => task.status !== "completed")} />

        <div className="app-content">
          {error && <div className="state-banner state-error" role="alert" style={{marginBottom: "1rem"}}><span>{error}</span><button type="button" className="btn-secondary" onClick={() => { setError(""); void load(); }}>Retry data</button></div>}

          {activeView === "Command" ? <CommandBrief key={`command-${sectionRefresh.command}`} flow={flow} busy={busy} act={act} setError={setError} workspaceMode={workspaceMode} onViewEvidence={() => setActiveView("Reports")} /> : null}
          {activeView === "Map" ? <MapWorkspace key={`map-${sectionRefresh.map}`} setError={setError} workspaceMode={workspaceMode} /> : null}
          {activeView === "Reports" ? <ReportsWorkspace key={`reports-${sectionRefresh.reports}`} incident={effectiveIncident} busy={busy} setBusy={setBusy} setError={setError} /> : null}
          {activeView === "Missions" ? <MissionsWorkspace key={`missions-${sectionRefresh.missions}`} incident={effectiveIncident} busy={busy} setBusy={setBusy} setError={setError} /> : null}
          {activeView === "Resources" ? <ResourcesWorkspace key={`resources-${sectionRefresh.resources}`} setError={setError} /> : null}
          {activeView === "Logistics" ? <SustainmentWorkspace setError={setError} /> : null}
          {activeView === "Handover" ? <HandoverWorkspace busy={busy} setBusy={setBusy} setError={setError} workspaceMode={workspaceMode} /> : null}

          {/* Synthetic replay controls */}
          {flow && (
            <div className="state-banner" role="status" style={{marginTop: "1rem"}}>
              <div style={{display: "flex", alignItems: "center", gap: "0.5rem"}}>
                <span className="badge-dot warning" style={{width: 8, height: 8, borderRadius: "50%", background: "var(--status-warning)", flexShrink: 0}} />
                <span><strong>Training Mode</strong> · Using synthetic data{busy ? " · Processing..." : ""}</span>
              </div>
              <button type="button" className="btn-secondary" onClick={() => void load()} style={{fontSize: "0.75rem", padding: "0.35rem 0.75rem"}}>Reset Scenario</button>
            </div>
          )}
        </div>

        {/* Guided step panel */}
        {guidedStep > 0 && (
          <div className="guided-panel">
            <div className="guided-panel-header">Training Exercise — Step {guidedStep} of 6</div>
            <div className="guided-panel-body">
              <div style={{display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem"}}>
                <h3 style={{margin: 0, fontSize: "1.05rem"}}>{TABLETOP_STEPS[guidedStep - 1].title}</h3>
                <button type="button" className="btn-ghost" onClick={() => setGuidedStep(0)} aria-label="Close" style={{fontSize: "1.2rem", padding: "0.25rem 0.5rem"}}>×</button>
              </div>
              <p style={{margin: "0 0 1rem 0", fontSize: "0.85rem", color: "var(--text-muted)", lineHeight: 1.5}}>
                {TABLETOP_STEPS[guidedStep - 1].narration}
              </p>
              <div style={{display: "flex", flexDirection: "column", gap: "0.5rem", background: "var(--bg-elevated)", padding: "0.75rem", borderRadius: "var(--radius-sm)", marginBottom: "1rem"}}>
                <div>
                  <strong style={{fontSize: "0.65rem", color: "var(--text-dim)", textTransform: "uppercase", display: "block", marginBottom: "0.15rem"}}>Where to look</strong>
                  <span style={{fontSize: "0.8rem", color: "var(--accent-cyan)", fontWeight: 500}}>{TABLETOP_STEPS[guidedStep - 1].target}</span>
                </div>
                <div>
                  <strong style={{fontSize: "0.65rem", color: "var(--text-dim)", textTransform: "uppercase", display: "block", marginBottom: "0.15rem"}}>What to do</strong>
                  <span style={{fontSize: "0.8rem", color: "var(--text-main)", fontWeight: 500}}>{TABLETOP_STEPS[guidedStep - 1].action}</span>
                </div>
              </div>
              <div style={{display: "flex", justifyContent: "space-between"}}>
                <div style={{display: "flex", gap: "0.5rem"}}>
                  <button type="button" className="btn-secondary" style={{padding: "0.4rem 0.85rem", fontSize: "0.8rem"}} disabled={guidedStep === 1} onClick={() => setGuidedStep(Math.max(1, guidedStep - 1))}>← Back</button>
                  <button type="button" className="btn-primary" style={{padding: "0.4rem 0.85rem", fontSize: "0.8rem"}} disabled={guidedStep === 6} onClick={() => setGuidedStep(Math.min(6, guidedStep + 1))}>Next →</button>
                </div>
                <button type="button" className="btn-ghost" style={{fontSize: "0.75rem"}} onClick={() => { setGuidedStep(0); void load(); }}>Restart</button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
