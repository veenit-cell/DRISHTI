import { type FormEvent, useEffect, useState } from "react";
import { activateIncident, advanceLiveTask, advanceTask, approveMission, approveMutualAid, assignApproved, assignVerification, completeLiveTask, closeIncident, configurePilot, createEvidenceReport, createIncidentSector, createMission, createSitrep, decide, getActiveIncident, getEvidenceReport, getPilotStatus, linkEvidenceToCommandIncident, listEvidenceReports, listIncidentSectors, listMapFeatures, listMissions, listResourceForecasts, pauseIncident, resumeIncident, listResourceRequests, listResources, resetGoldenFlow, reviewEvidenceReport, runExerciseReplay, runPilotTabletop, type CommandIncident, type EvidenceReport, type EvidenceReportDetail, type GoldenFlow, type IncidentSector, type MapFeature, type Mission, type PilotStatus, type TabletopExercise } from "./api";
import { printTaskPacket, queueCommand, queueTaskUpdate, readOutbox, syncOutbox } from "./offline";
import { demoWorkspace, type WorkspaceData } from "./fixtures";
import { IncidentBar } from "./components/IncidentBar";
import { CommandBrief } from "./components/CommandBrief";
import { MapCOP } from "./components/MapCOP";

type Action = "approve" | "reject" | "assign" | "acknowledged" | "en_route" | "on_scene" | "paused" | "completed";
type WorkspaceView = "Command" | "Map" | "Reports" | "Missions" | "Resources" | "Logistics" | "Handover";

const workspaceViews: WorkspaceView[] = [
  "Command",
  "Map",
  "Reports",
  "Missions",
  "Resources",
  "Logistics",
  "Handover",
];

function CommandNavigation({ activeView, onSelect }: { activeView: WorkspaceView; onSelect: (view: WorkspaceView) => void }) {
  return (
    <nav className="command-navigation" aria-label="RescueOps workspaces">
      <span className="command-navigation__label">WORKSPACES</span>
      <div className="command-navigation__tabs">
        {workspaceViews.map((view) => (
          <button
            key={view}
            className={`command-navigation__tab${activeView === view ? " is-active" : ""}`}
            type="button"
            aria-current={activeView === view ? "page" : undefined}
            onClick={() => onSelect(view)}
          >
            {view}
          </button>
        ))}
      </div>
    </nav>
  );
}

function WorkspacePlaceholder({ view }: { view: Exclude<WorkspaceView, "Command"> }) {
  return (
    <section className="workspace-section workspace-placeholder" aria-label={`${view} workspace`}>
      <p className="eyebrow">{view.toUpperCase()} WORKSPACE</p>
      <h2>{view} is not available in Phase 1</h2>
      <p>Command context remains active. This workspace will be enabled with its corresponding operational workflow in a later phase.</p>
    </section>
  );
}

function ConnectivityPanel({ setError }: { setError: (value: string) => void }) {
  const [online, setOnline] = useState(navigator.onLine);
  const [pending, setPending] = useState(0);
  const [lastSync, setLastSync] = useState<string | null>(null);
  useEffect(() => {
    const refresh = () => { setOnline(navigator.onLine); void readOutbox().then((commands) => setPending(commands.length)).catch(() => setPending(0)); };
    refresh(); window.addEventListener("online", refresh); window.addEventListener("offline", refresh);
    return () => { window.removeEventListener("online", refresh); window.removeEventListener("offline", refresh); };
  }, []);
  async function sync() { try { const result = await syncOutbox(); setPending((current) => Math.max(0, current - result.accepted)); setLastSync(new Date().toLocaleTimeString()); if (result.conflicts || result.rejected) setError(`${result.conflicts} sync conflicts and ${result.rejected} rejected commands require review.`); } catch (reason) { setError(reason instanceof Error ? reason.message : "Outbox sync failed"); } }
  return <div className={`state-banner${online ? "" : " state-error"}`} role="status"><span><strong>{online ? "NETWORK AVAILABLE" : "DEGRADED CONNECTIVITY"}</strong> // Pending field commands: {pending} // Last sync: {lastSync ?? "not yet"}</span>{online ? <button type="button" className="btn-secondary" onClick={() => void sync()}>Sync outbox</button> : <span>Commands remain local until reconnect.</span>}</div>;
}

function ReportsWorkspace({ incident, busy, setBusy, setError }: { incident: CommandIncident | null; busy: boolean; setBusy: (value: boolean) => void; setError: (value: string) => void }) {
  const [reports, setReports] = useState<EvidenceReport[]>([]);
  const [selected, setSelected] = useState<EvidenceReportDetail | null>(null);
  const [reportType, setReportType] = useState("life_safety");
  const [placeText, setPlaceText] = useState("");
  const [peopleAffected, setPeopleAffected] = useState("");
  const [verificationQueued, setVerificationQueued] = useState<string[]>([]);
  const refresh = async () => setReports(await listEvidenceReports());
  useEffect(() => { void refresh(); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (!navigator.onLine) {
        const commandId = `offline-report-${Date.now()}`;
        await queueCommand({ command_id: commandId, aggregate_id: commandId, sequence: 1, kind: "report", client_timestamp: new Date().toISOString(), payload: { report_type: reportType, place_text: placeText, people_affected: peopleAffected ? Number(peopleAffected) : null }, tenant_id: "org_demo", workspace_id: "evt_demo" });
        setError("Offline: report saved locally for server reconciliation.");
        return;
      }
      const created = await createEvidenceReport({ report_type: reportType, place_text: placeText, people_affected: peopleAffected ? Number(peopleAffected) : null });
      if (incident) await linkEvidenceToCommandIncident(created.report_id, incident.incident_id);
      setSelected(await getEvidenceReport(created.report_id)); setPlaceText(""); setPeopleAffected(""); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Report intake failed"); } finally { setBusy(false); }
  }
  async function verify(claimId: string, state: "corroborated" | "contradicted") {
    if (!selected) return; setBusy(true); setError("");
    try { setSelected(await reviewEvidenceReport(selected.id, { [claimId]: state })); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Review failed"); } finally { setBusy(false); }
  }
  async function queueVerification() {
    if (!selected) return; setBusy(true); setError("");
    try { await assignVerification(selected, incident?.incident_id); setVerificationQueued((current) => [...current, selected.id]); } catch (reason) { setError(reason instanceof Error ? reason.message : "Verification assignment failed"); } finally { setBusy(false); }
  }
  return <section className="workspace-section" aria-label="Report desk"><div className="section-heading"><div><p className="eyebrow">EVIDENCE INTAKE</p><h2>Reports & Verification</h2></div><span className="badge">{incident ? "LINKED TO ACTIVE INCIDENT" : "NO ACTIVE INCIDENT"}</span></div><form className="approval-panel" onSubmit={(event) => void submit(event)}><select aria-label="Report type" value={reportType} onChange={(event) => setReportType(event.target.value)}><option value="life_safety">Life safety</option><option value="access_blocked">Access blocked</option><option value="water_contamination">Water contamination</option></select><input aria-label="Approximate place" required placeholder="Approximate place or sector" value={placeText} onChange={(event) => setPlaceText(event.target.value)} /><input aria-label="People affected" inputMode="numeric" min="0" placeholder="People affected (unknown allowed)" value={peopleAffected} onChange={(event) => setPeopleAffected(event.target.value)} /><button type="submit" className="btn-primary" disabled={busy}>Receive report</button></form><div className="ops-dashboard"><div className="ops-column"><div className="ops-card"><h3>Received reports</h3><div className="ops-list">{reports.length ? reports.map((report) => <button type="button" className="ops-row" key={report.id} onClick={() => void getEvidenceReport(report.id).then(setSelected).catch((reason) => setError(reason.message))}><span className="ops-row-title">{report.report_type.replaceAll("_", " ")}</span><span className="ops-row-meta">{report.location?.place_text ?? "Location unknown"} · {report.status}</span></button>) : <div className="empty-state">No reports received.</div>}</div></div></div><div className="ops-column"><div className="ops-card"><h3>Review trail</h3>{selected ? <div className="ops-list"><div className="ops-row"><strong>{selected.report_type.replaceAll("_", " ")}</strong><div className="ops-row-meta">Source: {selected.source.channel} · {selected.observed_at ?? "Observed time unknown"}</div><div className="ops-row-meta">Links: {selected.command_incident_links.length ? selected.command_incident_links.map((link) => link.incident_id).join(", ") : "Not linked"}</div><button type="button" className="btn-primary" disabled={busy || verificationQueued.includes(selected.id)} onClick={() => void queueVerification()}>{verificationQueued.includes(selected.id) ? "Verification assigned" : "Assign verification"}</button></div>{selected.duplicate_candidates.map((candidate) => <div className="ops-row" key={candidate.candidate_report_id}>Possible duplicate: {candidate.reason}</div>)}{selected.claims.map((claim) => <div className="ops-row" key={claim.id}><strong>{claim.claim_type}</strong><div className="ops-row-meta">{claim.verification_state}</div><button type="button" className="btn-secondary" disabled={busy} onClick={() => void verify(claim.id, "corroborated")}>Corroborate</button><button type="button" className="btn-danger" disabled={busy} onClick={() => void verify(claim.id, "contradicted")}>Contradict</button></div>)}</div> : <div className="empty-state">Select a report to review its source, claims, duplicates, and incident link.</div>}</div></div></div></section>;
}

function MapWorkspace({ setError }: { setError: (value: string) => void }) {
  const [features, setFeatures] = useState<MapFeature[]>([]);
  useEffect(() => { void listMapFeatures().then(setFeatures).catch((reason) => setError(reason instanceof Error ? reason.message : "Map unavailable")); }, [setError]);
  return <section className="workspace-section" aria-label="Operational map"><div className="section-heading"><div><p className="eyebrow">SPATIAL STATE</p><h2>Map evidence and coverage state</h2></div><span className="badge">{features.length} FEATURES</span></div><div className="map-workspace-canvas"><MapCOP setError={setError} /></div><div className="ops-list">{features.length ? features.map((feature) => <div className="ops-row" key={feature.id}><strong>{String(feature.properties.title ?? feature.properties.name ?? feature.properties.report_type ?? "Unnamed feature")}</strong><div className="ops-row-meta">{String(feature.properties.feature_kind)} · {String(feature.properties.verification_state ?? feature.properties.status ?? feature.properties.assessment_state ?? "unassessed")}</div></div>) : <div className="empty-state">No map features are available. Unassessed areas remain unknown, not safe.</div>}</div></section>;
}

function HandoverWorkspace({ busy, setBusy, setError }: { busy: boolean; setBusy: (value: boolean) => void; setError: (value: string) => void }) {
  const [sitrep, setSitrep] = useState<{ reports: number; by_type: Record<string, number>; summary_hash: string } | null>(null);
  const [exercise, setExercise] = useState<{ record_count: number; future_records_excluded: number; scenario_signals: string[]; result_hash: string; synthetic: boolean } | null>(null);
  const [pilot, setPilot] = useState<PilotStatus | null>(null);
  const [tabletop, setTabletop] = useState<TabletopExercise | null>(null);
  const [agency, setAgency] = useState("District Emergency Operations Centre");
  const [district, setDistrict] = useState("Kamrup Metropolitan");
  async function exportSitrep() { setBusy(true); setError(""); try { setSitrep(await createSitrep(await listEvidenceReports())); } catch (reason) { setError(reason instanceof Error ? reason.message : "SITREP export failed"); } finally { setBusy(false); } }
  async function exerciseReplay() { setBusy(true); setError(""); try { setExercise(await runExerciseReplay()); } catch (reason) { setError(reason instanceof Error ? reason.message : "Exercise replay failed"); } finally { setBusy(false); } }
  async function setupPilot(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await configurePilot({ agency_name: agency, district_name: district, country_code: "IN", approved_feed_ids: ["district_control_room"] }); setPilot(await getPilotStatus()); } catch (reason) { setError(reason instanceof Error ? reason.message : "Pilot setup failed"); } finally { setBusy(false); } }
  async function tabletopExercise() { setBusy(true); setError(""); try { setTabletop(await runPilotTabletop()); } catch (reason) { setError(reason instanceof Error ? reason.message : "Tabletop exercise failed"); } finally { setBusy(false); } }
  return <section className="workspace-section" aria-label="Handover package"><div className="section-heading"><div><p className="eyebrow">HANDOVER & EXERCISE</p><h2>Bounded SITREP and pilot proof</h2></div><span className="badge">SYNTHETIC EXERCISES ONLY</span></div><p>Creates a bounded summary from the scoped report register for the next command period.</p><button type="button" className="btn-primary" disabled={busy} onClick={() => void exportSitrep()}>Generate SITREP</button><button type="button" className="btn-secondary" disabled={busy} onClick={() => void exerciseReplay()}>Run synthetic replay</button><form className="approval-panel" onSubmit={(event) => void setupPilot(event)}><input aria-label="Pilot agency" required value={agency} onChange={(event) => setAgency(event.target.value)} /><input aria-label="Pilot district" required value={district} onChange={(event) => setDistrict(event.target.value)} /><button type="submit" className="btn-secondary" disabled={busy}>Configure pilot boundary</button></form><button type="button" className="btn-primary" disabled={busy} onClick={() => void tabletopExercise()}>Run fault tabletop</button>{sitrep ? <div className="ops-row"><strong>{sitrep.reports} reports included</strong><div className="ops-row-meta">{Object.entries(sitrep.by_type).map(([kind, count]) => `${kind}: ${count}`).join(" · ") || "No reports"}</div><div className="ops-row-meta">Integrity hash: {sitrep.summary_hash}</div></div> : null}{exercise ? <div className="ops-row"><strong>{exercise.record_count} synthetic records · {exercise.future_records_excluded} future records excluded</strong><div className="ops-row-meta">Signals: {exercise.scenario_signals.join(", ")}</div><div className="ops-row-meta">Replay hash: {exercise.result_hash}</div></div> : null}{pilot?.configuration ? <div className="ops-row"><strong>{pilot.configuration.agency_name} · {pilot.configuration.district_name}</strong><div className="ops-row-meta">Approved feeds: {pilot.configuration.approved_feed_ids.join(", ")} · {pilot.retention_enforcement}</div><div className="ops-row-meta">Identity: {pilot.identity_mode}</div></div> : null}{tabletop ? <div className="ops-row"><strong>Fault exercise: {tabletop.faults.join(" · ")}</strong><div className="ops-row-meta">Verification {tabletop.metrics.verification_time_minutes}m · Wrong dispatches {tabletop.metrics.wrong_dispatches} · Duplicate missions prevented {tabletop.metrics.duplicate_missions_prevented} · Coverage gaps {tabletop.metrics.coverage_gaps_surfaced} · Sync delay {tabletop.metrics.sync_delay_minutes}m · Operator actions {tabletop.metrics.operator_actions}</div><div className="ops-row-meta">Exercise hash: {tabletop.result_hash}</div></div> : null}</section>;
}

function ResourcesWorkspace({ setError }: { setError: (value: string) => void }) {
  const [resources, setResources] = useState<Array<{ id: string; name: string; readiness: string }>>([]);
  useEffect(() => { void listResources().then(setResources).catch((reason) => setError(reason instanceof Error ? reason.message : "Resources unavailable")); }, [setError]);
  return <section className="workspace-section" aria-label="Resources"><div className="section-heading"><div><p className="eyebrow">RESOURCE READINESS</p><h2>Capability, availability, and freshness</h2></div><span className="badge">{resources.length} RESOURCES</span></div><div className="ops-list">{resources.length ? resources.map((resource) => <div className="ops-row" key={resource.id}><div className="ops-row-header"><strong>{resource.name}</strong><span className="ops-row-status">{resource.readiness}</span></div><div className="ops-row-meta">Current task, route constraints, and readiness detail remain governed by backend updates.</div></div>) : <div className="empty-state">No resources are currently returned for this operational scope.</div>}</div></section>;
}

function SustainmentWorkspace({ setError }: { setError: (value: string) => void }) {
  const [forecasts, setForecasts] = useState<WorkspaceData["forecasts"]>([]);
  const [requests, setRequests] = useState<WorkspaceData["resourceRequests"]>([]);
  useEffect(() => { void Promise.all([listResourceForecasts(), listResourceRequests()]).then(([nextForecasts, nextRequests]) => { setForecasts(nextForecasts); setRequests(nextRequests); }).catch((reason) => setError(reason instanceof Error ? reason.message : "Sustainment unavailable")); }, [setError]);
  return <section className="workspace-section" aria-label="Sustainment"><div className="section-heading"><div><p className="eyebrow">SUSTAINMENT</p><h2>Runway, reserves, and mutual aid</h2></div><span className="badge">{forecasts.length + requests.length} ITEMS</span></div><div className="ops-list">{forecasts.map((forecast) => <div className="ops-row" key={forecast.forecast_id}><strong>{forecast.resource_type}</strong><div className="ops-row-meta">Projected: {forecast.projected_quantity} · Reserve floor: {forecast.reserve_floor} · Runway: {forecast.hours_to_reserve ?? "unknown"} h</div></div>)}{requests.map((request) => <div className="ops-row" key={request.request_id}><strong>Mutual aid: {request.quantity} {request.resource_type}</strong><div className="ops-row-meta">{request.location} · Need by {request.need_by} · {request.status}</div></div>)}{!forecasts.length && !requests.length ? <div className="empty-state">No sustainment forecast is currently returned for this operational scope. Unknown runway is not safe.</div> : null}</div></section>;
}
function MissionLifecycleControls({ task, busy, onChanged, setBusy, setError }: { task: { id: string; status: string }; busy: boolean; onChanged: () => Promise<void>; setBusy: (value: boolean) => void; setError: (value: string) => void }) {
  const [outcome, setOutcome] = useState("");
  async function advance(status: "acknowledged" | "en_route" | "on_scene" | "paused") { setBusy(true); setError(""); try { if (!navigator.onLine) { await queueTaskUpdate(task.id, status); setError(`Offline: ${status.replaceAll("_", " ")} queued for reconciliation.`); return; } await advanceLiveTask(task.id, status); await onChanged(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Mission update failed"); } finally { setBusy(false); } }
  async function complete() { if (!outcome.trim()) return; setBusy(true); setError(""); try { if (!navigator.onLine) { await queueTaskUpdate(task.id, "completed", { action_type_evidence: outcome.trim() }); setError("Offline: completion and evidence queued for reconciliation."); return; } await completeLiveTask(task.id, outcome.trim()); await onChanged(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Mission completion failed"); } finally { setBusy(false); } }
  if (task.status === "assigned") return <><button type="button" className="btn-primary" disabled={busy} onClick={() => void advance("acknowledged")}>Acknowledge</button><button type="button" className="btn-secondary" onClick={() => printTaskPacket({ id: task.id, resource: "Assigned resource", status: task.status })}>Print task packet</button></>;
  if (task.status === "acknowledged") return <button type="button" className="btn-primary" disabled={busy} onClick={() => void advance("en_route")}>Mark en route</button>;
  if (task.status === "en_route") return <><button type="button" className="btn-primary" disabled={busy} onClick={() => void advance("on_scene")}>Arrived on scene</button><button type="button" className="btn-danger" disabled={busy} onClick={() => void advance("paused")}>Pause</button></>;
  if (task.status === "paused") return <button type="button" className="btn-secondary" disabled={busy} onClick={() => void advance("en_route")}>Resume en route</button>;
  if (task.status === "on_scene") return <div className="approval-panel"><input aria-label="Completion evidence" required placeholder="Observed completion evidence" value={outcome} onChange={(event) => setOutcome(event.target.value)} /><button type="button" className="btn-primary" disabled={busy || !outcome.trim()} onClick={() => void complete()}>Complete & record outcome</button><button type="button" className="btn-danger" disabled={busy} onClick={() => void advance("paused")}>Pause</button></div>;
  return null;
}

function MissionsWorkspace({ incident, busy, setBusy, setError }: { incident: CommandIncident | null; busy: boolean; setBusy: (value: boolean) => void; setError: (value: string) => void }) {
  const [reports, setReports] = useState<EvidenceReport[]>([]); const [missions, setMissions] = useState<Mission[]>([]); const [resources, setResources] = useState<Array<{ id: string; name: string; readiness: string }>>([]); const [reportId, setReportId] = useState(""); const [objective, setObjective] = useState("");
  const refresh = async () => { const [nextReports, nextMissions, nextResources] = await Promise.all([listEvidenceReports(), listMissions(), listResources()]); setReports(nextReports); setMissions(nextMissions); setResources(nextResources.filter((resource) => resource.readiness === "ready")); };
  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "Mission board unavailable")); }, []);
  async function create(event: FormEvent) { event.preventDefault(); if (!incident) return; setBusy(true); setError(""); try { await createMission({ source_report_id: reportId, source_incident_id: incident.incident_id, objective, destination: reports.find((report) => report.id === reportId)?.location?.place_text ?? "", required_capability: "" }); setObjective(""); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Mission creation failed"); } finally { setBusy(false); } }
  async function approve(mission: Mission, resourceId: string) { setBusy(true); setError(""); try { await approveMission(mission.mission_id, resourceId); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Mission approval failed"); } finally { setBusy(false); } }
  return <section className="workspace-section" aria-label="Mission board"><div className="section-heading"><div><p className="eyebrow">MISSION CONTROL</p><h2>Verified need to accountable action</h2></div><span className="badge">COMMANDER APPROVAL REQUIRED</span></div>{incident ? <form className="approval-panel" onSubmit={(event) => void create(event)}><select aria-label="Verified source report" required value={reportId} onChange={(event) => setReportId(event.target.value)}><option value="">Choose corroborated report</option>{reports.map((report) => <option key={report.id} value={report.id}>{report.report_type} · {report.location?.place_text ?? "Unknown location"}</option>)}</select><input aria-label="Mission objective" required placeholder="Mission objective" value={objective} onChange={(event) => setObjective(event.target.value)} /><button type="submit" className="btn-primary" disabled={busy || !reportId}>Create mission</button></form> : <div className="empty-state">Activate an incident before creating a mission.</div>}<div className="ops-list">{missions.length ? missions.map((mission) => <div className="ops-row" key={mission.mission_id}><div className="ops-row-header"><span className="ops-row-title">{mission.title}</span><span className="ops-row-status active">{mission.task?.status ?? mission.status}</span></div><div className="ops-row-meta">Source report: {mission.source_report_id} · {mission.destination ?? "Destination unknown"}</div>{mission.status === "queued" && !mission.task ? <select aria-label={`Resource for ${mission.title}`} disabled={busy} defaultValue="" onChange={(event) => { if (event.target.value) void approve(mission, event.target.value); }}><option value="">Commander: select ready resource</option>{resources.map((resource) => <option key={resource.id} value={resource.id}>{resource.name}</option>)}</select> : null}{mission.task ? <MissionLifecycleControls task={mission.task} busy={busy} onChanged={refresh} setBusy={setBusy} setError={setError} /> : null}</div>) : <div className="empty-state">No missions created from verified reports.</div>}</div></section>;
}

function IncidentGate({ incident, busy, onActivate }: { incident: CommandIncident | null; busy: boolean; onActivate: (input: { name: string; hazard_type: string; severity: string; summary: string; event_time: string }) => void }) {
  const [name, setName] = useState("");
  const [summary, setSummary] = useState("");
  if (incident) return (
    <div className="state-banner" role="status">
      <div><strong>{incident.name}</strong> // {incident.hazard_type.toUpperCase()} // {incident.operational_period} // {incident.phase.replaceAll("_", " ")} // {incident.severity.toUpperCase()}</div>
      <span>Commander: {incident.roles.incident_commander ?? "unassigned"}</span>
    </div>
  );
  return (
    <section className="workspace-section" style={{marginBottom: "2rem"}}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">COMMAND ACTIVATION</p>
          <h2>No active incident</h2>
        </div>
        <span className="badge" style={{color: "var(--status-warning)"}}>TRAINING REPLAY IS SEPARATE</span>
      </div>
      <form className="approval-panel" onSubmit={(event) => { event.preventDefault(); onActivate({ name, hazard_type: "multi_hazard", severity: "critical", summary, event_time: new Date().toISOString() }); }}>
        <input style={{background: "var(--bg-panel)", color: "white", border: "1px solid var(--border-light)", padding: "0.5rem", borderRadius: "4px"}} aria-label="Incident name" required placeholder="Incident name" value={name} onChange={(event) => setName(event.target.value)} />
        <input style={{background: "var(--bg-panel)", color: "white", border: "1px solid var(--border-light)", padding: "0.5rem", borderRadius: "4px", flexGrow: 1}} aria-label="Initial situation summary" required placeholder="Initial situation summary" value={summary} onChange={(event) => setSummary(event.target.value)} />
        <button type="submit" className="btn-primary" disabled={busy}>Activate incident</button>
      </form>
    </section>
  );
}

function SectorBoard({ incident, sectors, busy, onCreate }: { incident: CommandIncident | null; sectors: IncidentSector[]; busy: boolean; onCreate: (input: { name: string; owner_actor_id: string }) => void }) {
  const [name, setName] = useState("");
  if (!incident) return null;
  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">INCIDENT SECTORS</p>
          <h2>Operational Sectors</h2>
        </div>
      </div>
      <div className="ops-grid" style={{display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", marginBottom: "1rem"}}>
        {sectors.map(s => (
          <div key={s.sector_id} className="ops-card" style={{padding: "1rem"}}>
            <strong style={{color: "var(--accent-cyan)"}}>{s.name}</strong>
            <div style={{fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.5rem"}}>Owner: {s.owner_actor_id}</div>
          </div>
        ))}
      </div>
      <form className="approval-panel" onSubmit={(event) => { event.preventDefault(); onCreate({ name, owner_actor_id: "operator" }); setName(""); }}>
        <input style={{background: "var(--bg-panel)", color: "white", border: "1px solid var(--border-light)", padding: "0.5rem", borderRadius: "4px"}} aria-label="Sector name" required placeholder="New sector name" value={name} onChange={(event) => setName(event.target.value)} />
        <button type="submit" className="btn-secondary" disabled={busy}>Create Sector</button>
      </form>
    </section>
  );
}

function Signals({ data }: { data: WorkspaceData }) {
  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">I. THREAT INTELLIGENCE</p>
          <h2>Projections & Signals</h2>
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
      <div className="unknown-box">
        <strong>⚠️ TACTICAL UNKNOWNS DETECTED</strong>
        <p>Contradictory influx and stale constraints require verification. Do not treat as safe.</p>
      </div>
    </section>
  );
}

function Recommendation({ flow, busy, act }: { flow: GoldenFlow; busy: boolean; act: (action: Action, selectedAction?: string) => void }) {
  const status = flow.recommendation.status;
  const task = flow.data.tasks.find((item) => item.status !== "completed");
  const [selectedAction, setSelectedAction] = useState(flow.data.candidates[0]?.action);

  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">II. COURSES OF ACTION (COA)</p>
          <h2>Ranked Interventions</h2>
        </div>
        <span className="badge">Auto-dispatch: {String(flow.recommendation.auto_dispatched).toUpperCase()}</span>
      </div>

      <div className="candidate-list">
        {flow.data.candidates.map((item) => (
          <article className="candidate" key={item.action}>
            <div className="rank-box">
              <span className="rank">#{item.rank}</span>
            </div>
            <div className="content">
              <h3>{item.action}</h3>
              <div className="details-grid">
                <div className="detail-item"><strong>Effect</strong><span>{item.effect}</span></div>
                <div className="detail-item"><strong>Cost</strong><span>{item.cost}</span></div>
                <div className="detail-item"><strong>Confidence</strong><span>{item.confidence}</span></div>
                <div className="detail-item"><strong>Excluded Assets</strong><span>{item.excluded}</span></div>
              </div>
              {status === "pending_approval" && (
                <div className="candidate-selector">
                  <label>
                    <input
                      type="radio"
                      name="selected-action"
                      checked={selectedAction === item.action}
                      onChange={() => setSelectedAction(item.action)}
                    />
                    AUTHORIZE THIS INTERVENTION
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
            <button type="button" className="btn-primary" disabled={busy} onClick={() => act("approve", selectedAction)}>Execute Selected COA</button>
            <button type="button" className="btn-danger" disabled={busy} onClick={() => act("reject", selectedAction)}>Stand Down (Reject)</button>
          </>
        )}
        {status === "approved" && !task && (
          <button type="button" className="btn-primary" disabled={busy} onClick={() => act("assign")}>Confirm Route & Deploy Asset</button>
        )}
        {task?.status === "assigned" && (
          <button type="button" className="btn-primary" disabled={busy} onClick={() => act("acknowledged")}>Asset: Acknowledge Task</button>
        )}
        {task?.status === "acknowledged" && (
          <button type="button" className="btn-primary" disabled={busy} onClick={() => act("en_route")}>Asset: Mark En Route</button>
        )}
        {task?.status === "en_route" && (
          <><button type="button" className="btn-primary" disabled={busy} onClick={() => act("on_scene")}>Asset: Mark On Scene</button><button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")}>Pause mission</button></>
        )}
        {task?.status === "on_scene" && (
          <><button type="button" className="btn-primary" disabled={busy} onClick={() => act("completed")}>Asset: Mark Completed (Log Outcome)</button><button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")}>Pause mission</button></>
        )}
        {task?.status === "paused" && (
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => act("en_route")}>Resume mission</button>
        )}
      </div>
    </section>
  );
}

function Operations({ flow }: { flow: GoldenFlow }) {
  return (
    <section className="workspace-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">III. THEATRE OPERATIONS</p>
          <h2>Logistics & Fleet Status</h2>
        </div>
      </div>

      <div className="ops-dashboard">
        <div className="ops-column">

          <div className="ops-card">
            <h3>Active Resources</h3>
            <div className="ops-list">
              {flow.data.resources.length ? flow.data.resources.map((item) => (
                <div className="ops-row" key={item.id}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">{item.name}</span>
                    <span className={`ops-row-status ${String(item.readiness).toLowerCase() === 'ready' ? 'active' : 'warning'}`}>{item.readiness}</span>
                  </div>
                  <div className="ops-row-meta">Task: {item.task || "Unassigned"}</div>
                </div>
              )) : <div className="empty-state">No assets deployed.</div>}
            </div>
          </div>

          <div className="ops-card">
            <h3>Resource Forecasts</h3>
            <div className="ops-list">
              {flow.data.forecasts.length ? flow.data.forecasts.map((item) => (
                <div className="ops-row" key={item.forecast_id}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">{item.resource_type} | {item.location}</span>
                  </div>
                  <div className="ops-row-details">Available: {item.current_quantity} | Reserve Floor: {item.reserve_floor}</div>
                  <div className="ops-row-meta" style={{color: item.request_recommended ? "var(--status-warning)" : "var(--status-success)"}}>
                    {item.request_recommended ? `[WARNING] Request Recommended · ${item.hours_to_reserve ?? "?"}h to reserve` : "[OK] No request needed"}
                  </div>
                </div>
              )) : <div className="empty-state">No forecasts active.</div>}
            </div>
          </div>

          <div className="ops-card">
            <h3>Mutual-Aid Requests</h3>
            <div className="ops-list">
              {flow.data.resourceRequests.length ? flow.data.resourceRequests.map((item) => (
                <div className="ops-row" key={item.request_id}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">{item.quantity} {item.resource_type}</span>
                    <span className={`ops-row-status ${item.status === 'draft' ? 'warning' : 'active'}`}>{item.status}</span>
                  </div>
                  <div className="ops-row-details">Loc: {item.location} | Source: {item.source_reality}</div>
                  <div className="ops-row-meta" style={{color: "var(--accent-cyan)"}}>T-Minus (Need By): {item.need_by}</div>
                </div>
              )) : <div className="empty-state">No mutual-aid requests active.</div>}
            </div>
          </div>

        </div>

        <div className="ops-column">

          <div className="ops-card">
            <h3>Coverage Verification & Data Debt</h3>
            <div className="ops-list">
              {flow.data.verification.length ? flow.data.verification.map((item) => (
                <div className="ops-row" key={`${item.cell_id}:${item.fact_type}`}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">#{item.rank} | Cell: {item.cell_id}</span>
                    <span className="ops-row-status active">{item.debt_band} DEBT</span>
                  </div>
                  <div className="ops-row-details">Pop: {item.population.toLocaleString()} | {item.reporting_impaired ? "REPORTING IMPAIRED" : "REPORTING ACTIVE"}</div>
                  <div className="ops-row-meta">Impact: {item.decision_impact_score.toFixed(2)} | {item.what_answer_changes}</div>
                </div>
              )) : <div className="empty-state">No coverage cells mapped.</div>}
            </div>
          </div>

          <div className="ops-card">
            <h3>Strategic Mission Unlocks</h3>
            <div className="ops-list">
              {flow.data.unlocks.length ? flow.data.unlocks.map((item) => (
                <div className="ops-row" key={item.target_node_id}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">#{item.rank} | {item.action}</span>
                    <span className="ops-row-status active">VALUE {item.mission_unlock_value.toFixed(2)}</span>
                  </div>
                  <div className="ops-row-details">Downstream: {item.downstream_nodes_unlocked.join(", ") || "none"}</div>
                  <div className="ops-row-meta">Missions: {item.missions_unlocked.join(", ") || "none"}</div>
                </div>
              )) : <div className="empty-state">No unlocks available.</div>}
            </div>
          </div>

          <div className="ops-card">
            <h3>Strategic Plan Assumptions</h3>
            <div className="ops-list">
              {flow.data.plans.length ? flow.data.plans.map((item) => (
                <div className="ops-row" key={item.plan_id}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">{item.objective_summary}</span>
                    <span className={`ops-row-status ${item.status === 'review_required' ? 'warning' : 'active'}`}>{item.status}</span>
                  </div>
                  <div className="ops-row-details">Fragility: {item.fragility.toFixed(2)}</div>
                  <div className="ops-row-meta">{item.assumptions.map((a) => `${a.subject_type}:${a.subject_id}=${a.expected_state}(${a.sensitivity})`).join(" · ")}</div>
                </div>
              )) : <div className="empty-state">No plans loaded.</div>}
            </div>
          </div>

          <div className="ops-card">
            <h3>Response Queues & Tasks</h3>
            <div className="ops-list">
              {flow.data.queue.length ? flow.data.queue.map((item) => (
                <div className="ops-row" key={item.id}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">{item.title}</span>
                    <span className="ops-row-status active">{item.status}</span>
                  </div>
                </div>
              )) : <div className="empty-state">Queue empty.</div>}
              {flow.data.tasks.length ? flow.data.tasks.map((item) => (
                <div className="ops-row" key={item.id}>
                  <div className="ops-row-header">
                    <span className="ops-row-title">{item.resource}</span>
                    <span className="ops-row-status warning">{item.status}</span>
                  </div>
                  <div className="ops-row-details">{item.outcome || "Pending outcome..."}</div>
                </div>
              )) : null}
            </div>
          </div>

        </div>
      </div>

      <div className="audit-panel">
        <strong>[CRYPTOGRAPHIC AUDIT TRAIL]</strong>
        {flow.audit.length ? flow.audit.map((item, index) => (
          <span key={index}>
            {String(item.event)}
            {index < flow.audit.length - 1 && <span className="audit-arrow">→</span>}
          </span>
        )) : "No events recorded in session."}
      </div>
    </section>
  );
}

function PlanAlerts({ plans }: { plans: WorkspaceData["plans"] }) {
  const affected = plans.filter((plan) => plan.status === "review_required");
  if (!affected.length) return null;
  return (
    <div className="state-banner state-error" role="alert">
      <strong>⚠️ {affected.length} PLAN{affected.length === 1 ? "" : "S"} COMPROMISED:</strong>
      A named dependency assumption has changed. Review immediately: {affected.map((plan) => plan.objective_summary).join(" | ")}
    </div>
  );
}

function MutualAidApproval({ flow, busy, onApprove }: { flow: GoldenFlow; busy: boolean; onApprove: (requestId: string) => void }) {
  const drafts = flow.data.resourceRequests.filter((item) => item.status === "draft");
  if (!drafts.length) return null;
  return (
    <section className="workspace-section" aria-label="Mutual-aid approvals">
      <div className="section-heading">
        <div>
          <p className="eyebrow" style={{color: "var(--status-warning)"}}>EXTERNAL SUPPORT REQUIRED</p>
          <h2>Draft Mutual-Aid Requests</h2>
        </div>
      </div>
      {drafts.map((item) => (
        <div className="approval-panel" key={item.request_id} style={{borderColor: "var(--status-warning)", boxShadow: "0 0 20px rgba(245,158,11,0.1) inset"}}>
          <div style={{flexGrow: 1}}>
            <h3 style={{margin: "0 0 0.5rem 0", color: "var(--status-warning)"}}>{item.quantity} {item.resource_type} for {item.location}</h3>
            <div style={{fontSize: "0.85rem", color: "var(--text-muted)"}}>Required by: <strong style={{color: "var(--text-main)"}}>{item.need_by}</strong> | Reserve Floor: {item.reserve_floor}</div>
            <div style={{fontSize: "0.75rem", fontFamily: "JetBrains Mono", marginTop: "0.25rem", color: "#64748b"}}>Source: Forecast-backed synthetic request</div>
          </div>
          <button type="button" className="btn-primary" style={{background: "var(--status-warning)", color: "#000"}} disabled={busy} onClick={() => onApprove(item.request_id)}>
            Transmit Official Request
          </button>
        </div>
      ))}
    </section>
  );
}

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

  async function load() {
    setState("loading");
    setError("");
    try {
      const activeIncident = await getActiveIncident();
      setIncident(activeIncident);
      setShowPausedLanding(activeIncident?.status === "paused");
      setSectors(activeIncident ? await listIncidentSectors(activeIncident.incident_id) : []);
      setFlow(null);
      if (!activeIncident && new URLSearchParams(window.location.search).get("mode") === "tabletop") {
        setFlow(await resetGoldenFlow());
        setActiveView("Command");
        setGuidedStep(1);
      }
      setState("ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "API unavailable");
      setState("error");
    }
  }

  useEffect(() => { void load(); }, []);

  async function activate(input: { name: string; hazard_type: string; severity: string; summary: string; event_time: string }) {
    setBusy(true);
    setError("");
    try {
      const active = await activateIncident(input);
      setIncident(active);
      setFlow(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Activation failed");
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
      setError(reason instanceof Error ? reason.message : "Incident pause failed");
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
      setError(reason instanceof Error ? reason.message : "Incident resume failed");
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
      setError(reason instanceof Error ? reason.message : "Incident close failed");
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
      setError(reason instanceof Error ? reason.message : "Sector assignment failed");
    } finally {
      setBusy(false);
    }
  }

  async function startTraining() {
    setBusy(true);
    setError("");
    try {
      setFlow(await resetGoldenFlow());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Training replay failed");
    } finally {
      setBusy(false);
    }
  }

  async function act(action: Action, selectedAction?: string) {
    if (!flow) return;
    setBusy(true);
    setError("");
    try {
      setFlow(action === "approve" || action === "reject" ? await decide(flow, action, selectedAction) : action === "assign" ? await assignApproved(flow) : await advanceTask(flow, action));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action failed");
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
      setError(reason instanceof Error ? reason.message : "Mutual-aid approval failed");
    } finally {
      setBusy(false);
    }
  }

  if (state === "loading") return <main className="shell"><div className="state-banner" role="status">SYSTEM BOOTSTRAPPING // ESTABLISHING API UPLINK...</div></main>;
  if (state === "error") return (
    <main className="shell">
      <div className="state-banner state-error" role="alert">CONNECTION SEVERED: {error}</div>
      <div style={{display: "flex", gap: "1rem"}}>
        <button type="button" className="btn-secondary" onClick={() => void load()}>RETRY UPLINK</button>
        <button type="button" className="btn-primary" onClick={() => setState("offline")}>INITIATE OFFLINE FIXTURE</button>
      </div>
    </main>
  );
  if (state === "offline") return (
    <main className="shell">
      <IncidentBar incident={incident} busy={busy} isSynthetic={true} />
      <div className="state-banner state-error" role="status">OFFLINE PROTOCOL ENGAGED // SYNTHETIC DATA ONLY</div>
      <CommandBrief flow={{ data: demoWorkspace, recommendation: { status: "pending_approval", candidates: [], auto_dispatched: false }, audit: [] } as any} busy={busy} act={act} setError={setError} />
      <button type="button" className="btn-secondary" style={{marginTop: "2rem"}} onClick={() => void load()}>RECONNECT TO COMMAND NETWORK</button>
    </main>
  );

  const TABLETOP_STEPS = [
    {
      title: "Command activated",
      narration: "The incident is active. Command has an operational period, a named commander, and a shared picture.",
      target: "top incident bar",
      action: "Observe the incident banner."
    },
    {
      title: "Signal overload",
      narration: "Connected areas are reporting water pressure. Report volume alone does not determine priority.",
      target: "first Dominant Decision and Command Pulse",
      action: "Review pending decisions and metrics."
    },
    {
      title: "Silent village",
      narration: "One high-exposure settlement is not reporting. RescueOps keeps it visible as no information requiring verification, never as safe.",
      target: "map marker/coverage overlay and verification-related card",
      action: "Note the unassessed geographic zones."
    },
    {
      title: "Blocked corridor",
      narration: "A route update can rule out an apparently obvious assignment. A resource must be capable, ready, and able to reach the destination.",
      target: "route/map layer and decision blocker text",
      action: "Observe resource constraints."
    },
    {
      title: "Commander approval and outage",
      narration: "The commander chooses a feasible option. If connectivity drops, field updates are queued locally rather than silently lost.",
      target: "Approve action and connectivity/outbox status",
      action: "Review resilience design."
    },
    {
      title: "Outcome and handover",
      narration: "The outcome changes the next operational picture. Remaining risk, shortages, and uncertainty are preserved for the next shift.",
      target: "Handover tab and SITREP/tabletop metrics",
      action: "Prepare for handover."
    }
  ];

  if ((!incident || (incident.status === "paused" && showPausedLanding)) && !flow && !showBriefingModal) {
    return (
      <main className="shell" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", gap: "2rem", textAlign: "center", background: "var(--bg-surface)" }}>
        {error && <div className="state-banner state-error" role="alert" style={{position: "absolute", top: 0, left: 0, right: 0}}>{error}</div>}

        <div>
          <p className="eyebrow" style={{color: "var(--text-muted)", letterSpacing: "2px", fontWeight: 600}}>SYSTEM IN STANDBY</p>
          <h1 style={{fontSize: "2.5rem", marginBottom: "1rem", color: "var(--text-main)"}}>NO ACTIVE INCIDENT</h1>
          <p style={{color: "var(--text-muted)", maxWidth: "600px", margin: "0 auto"}}>
            RescueOps is ready for an operational period.
          </p>
        </div>

        {showPausedLanding && incident ? (
          <div className="approval-panel" role="status" style={{maxWidth: "640px", textAlign: "left"}}>
            <div style={{flex: 1}}><strong>PAUSED INCIDENT: {incident.name}</strong><div className="ops-row-meta">The incident remains preserved and can be resumed or closed by the commander.</div></div>
            <button type="button" className="btn-primary" disabled={busy} onClick={() => void resumePausedIncident()}>Resume incident</button>
            <button type="button" className="btn-danger" disabled={busy} onClick={() => void closePausedIncident()}>Close incident</button>
          </div>
        ) : (        <div style={{display: "flex", gap: "1rem"}}>
          <button type="button" className="btn-primary" disabled={busy} onClick={() => setShowBriefingModal(true)} style={{padding: "0.75rem 1.5rem"}}>
            {busy ? "INITIALIZING..." : "START SYNTHETIC TABLETOP"}
          </button>
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => void activate({ name: "New Incident", hazard_type: "multi_hazard", severity: "critical", summary: "Initial situation", event_time: new Date().toISOString() })} style={{padding: "0.75rem 1.5rem"}}>
            ACTIVATE INCIDENT
          </button>
        </div>        )}
      </main>
    );
  }

  if (showBriefingModal) {
    return (
      <main className="shell" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "var(--bg-dark)" }}>
        <div style={{background: "var(--bg-surface)", border: "1px solid var(--status-warning)", borderRadius: "4px", padding: "2.5rem", maxWidth: "600px", boxShadow: "0 10px 25px rgba(0,0,0,0.05)"}}>
          <p className="eyebrow" style={{color: "var(--status-warning)"}}>SYNTHETIC TABLETOP — TRAINING ONLY</p>
          <h2 style={{fontSize: "1.75rem", marginBottom: "1.5rem", color: "var(--text-main)"}}>Brahmaputra Flood: First 24 Hours</h2>

          <div style={{display: "flex", flexDirection: "column", gap: "1rem", marginBottom: "2rem", fontSize: "0.95rem", color: "var(--text-muted)", lineHeight: "1.5"}}>
            <div><strong style={{color: "var(--text-main)"}}>What happened:</strong> flooding, water pressure, reports from connected areas</div>
            <div><strong style={{color: "var(--text-main)"}}>What is unknown:</strong> one communications-dark high-exposure settlement</div>
            <div><strong style={{color: "var(--text-main)"}}>What can change the plan:</strong> route status, verification result, resource readiness</div>
            <div style={{background: "rgba(217,119,6,0.1)", padding: "1rem", borderLeft: "3px solid var(--status-warning)", borderRadius: "2px", color: "var(--status-warning)"}}>
              <strong>Safety boundary:</strong> RescueOps recommends; a commander approves every high-risk action
            </div>
          </div>

          <div style={{display: "flex", gap: "1rem", justifyContent: "flex-end"}}>
            <button type="button" className="btn-secondary" onClick={() => setShowBriefingModal(false)}>Exit tabletop</button>
            <button type="button" className="btn-primary" onClick={() => { setShowBriefingModal(false); setGuidedStep(1); void startTraining(); }}>Begin command briefing</button>
          </div>
        </div>
      </main>
    );
  }

  const effectiveIncident = incident || (flow ? {
    incident_id: "demo",
    name: "Brahmaputra Flood",
    hazard_type: "multi_hazard",
    operational_period: "OP-1",
    phase: "Size-up",
    severity: "critical",
    roles: { incident_commander: "J. Vance" }
  } as any : null);

  return (
    <main className="shell" style={{ maxWidth: "1600px", padding: "1rem", position: "relative" }}>
      <IncidentBar incident={effectiveIncident} busy={busy} isSynthetic={!!flow} onPause={!flow && incident?.status === "active" ? () => void pauseCurrentIncident() : undefined} />
      <CommandNavigation activeView={activeView} onSelect={setActiveView} />

      {error && <div className="state-banner state-error" role="alert" style={{marginBottom: "1rem"}}>{error}</div>}

      {activeView === "Command" ? <CommandBrief flow={flow} busy={busy} act={act} setError={setError} /> : null}
      {activeView === "Map" ? <MapWorkspace setError={setError} /> : null}
      {activeView === "Reports" ? <ReportsWorkspace incident={incident} busy={busy} setBusy={setBusy} setError={setError} /> : null}
      {activeView === "Missions" ? <MissionsWorkspace incident={incident} busy={busy} setBusy={setBusy} setError={setError} /> : null}
      {activeView === "Resources" ? <ResourcesWorkspace setError={setError} /> : null}
      {activeView === "Logistics" ? <SustainmentWorkspace setError={setError} /> : null}
      {activeView === "Handover" ? <HandoverWorkspace busy={busy} setBusy={setBusy} setError={setError} /> : null}
            {/* Controls for synthetic replay state */}
      {flow && (
        <div className="state-banner" role="status" style={{marginTop: "1.5rem", marginBottom: "0"}}>
          <div><strong>UPLINK SECURE</strong> // SERVER AUTHORITATIVE {busy ? " // EXECUTING COMMAND..." : ""}</div>
          <button type="button" className="btn-secondary" onClick={() => void load()}>RESET GOLDEN REPLAY</button>
        </div>
      )}

      {guidedStep > 0 && (
        <div style={{
          position: "fixed",
          bottom: "2rem",
          right: "2rem",
          width: "400px",
          background: "var(--bg-surface)",
          border: "1px solid var(--status-warning)",
          borderRadius: "4px",
          boxShadow: "0 10px 30px rgba(0,0,0,0.15)",
          zIndex: 1000,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden"
        }}>
          <div style={{background: "var(--status-warning)", color: "#000", padding: "0.5rem 1rem", fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase"}}>
            SYNTHETIC DATA — TRAINING ONLY
          </div>

          <div style={{padding: "1.5rem"}}>
            <div style={{display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem"}}>
              <span style={{fontSize: "0.75rem", fontWeight: 700, color: "var(--text-muted)"}}>STEP {guidedStep} OF 6</span>
              <button type="button"
                onClick={() => setGuidedStep(0)}
                style={{background: "none", border: "none", color: "var(--text-muted)", fontSize: "1.2rem", lineHeight: 1, padding: 0}}
                aria-label="Close panel"
              >
                &times;
              </button>
            </div>

            <h3 style={{margin: "0 0 0.5rem 0", fontSize: "1.1rem", color: "var(--text-main)"}}>{TABLETOP_STEPS[guidedStep - 1].title}</h3>
            <p style={{margin: "0 0 1.5rem 0", fontSize: "0.95rem", color: "var(--text-main)", lineHeight: 1.5}}>
              {TABLETOP_STEPS[guidedStep - 1].narration}
            </p>

            <div style={{display: "flex", flexDirection: "column", gap: "0.75rem", background: "var(--bg-panel)", padding: "1rem", borderRadius: "4px", marginBottom: "1.5rem"}}>
              <div>
                <strong style={{fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase", display: "block", marginBottom: "0.25rem"}}>Look here</strong>
                <span style={{fontSize: "0.9rem", color: "var(--status-info)", fontWeight: 500}}>{TABLETOP_STEPS[guidedStep - 1].target}</span>
              </div>
              <div>
                <strong style={{fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase", display: "block", marginBottom: "0.25rem"}}>Your action</strong>
                <span style={{fontSize: "0.9rem", color: "var(--text-main)", fontWeight: 500}}>{TABLETOP_STEPS[guidedStep - 1].action}</span>
              </div>
            </div>

            <div style={{display: "flex", justifyContent: "space-between", alignItems: "center"}}>
              <div style={{display: "flex", gap: "0.5rem"}}>
                <button type="button"
                  className="btn-secondary"
                  style={{padding: "0.5rem 1rem", fontSize: "0.85rem"}}
                  disabled={guidedStep === 1}
                  onClick={() => setGuidedStep(Math.max(1, guidedStep - 1))}
                >
                  Previous
                </button>
                <button type="button"
                  className="btn-primary"
                  style={{padding: "0.5rem 1rem", fontSize: "0.85rem"}}
                  disabled={guidedStep === 6}
                  onClick={() => setGuidedStep(Math.min(6, guidedStep + 1))}
                >
                  Next step
                </button>
              </div>

              <div style={{display: "flex", gap: "0.5rem"}}>
                <button type="button" className="btn-secondary" style={{padding: "0.5rem 1rem", fontSize: "0.85rem"}} onClick={() => {}}>Show target</button>
                <button type="button"
                  className="btn-secondary"
                  style={{padding: "0.5rem 1rem", fontSize: "0.85rem"}}
                  onClick={() => { setGuidedStep(0); void load(); }}
                >
                  Reset scenario
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
