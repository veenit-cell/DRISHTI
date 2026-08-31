import { type FormEvent, useEffect, useState } from "react";
import { createEvidenceReport, getCommandSummary, getOperationalSnapshot, getTelemetrySummary, recordAuditInteraction, type CascadeFinding, type CommandSummary, type GoldenFlow, type ScenarioComparison, type TelemetrySummary } from "../api";
import { demoWorkspace, type WorkspaceData } from "../fixtures";
import { MapCOP } from "./MapCOP";
import { CascadePanel } from "./CascadePanel";
import { ScenarioLab } from "./ScenarioLab";
import { SensorHealthPanel } from "./SensorHealthPanel";

type Action = "approve" | "reject" | "modify" | "assign" | "acknowledged" | "en_route" | "on_scene" | "paused" | "completed";
type DrawerDetail = "evidence" | "excluded" | "assumptions" | null;

const fallbackGoldenFlow: GoldenFlow = {
  source: "fallback",
  source_detail: "Synthetic fixture used only for explicit training mode",
  data: demoWorkspace,
  recommendation: {
    id: "rec_live_view",
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
        priority_reason: "North Sector safe-water runway is below 3.5h critical threshold with incoming evacuees.",
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
      } as any,
      {
        action: "shift_non_critical_power",
        rank: 3,
        confidence: "high",
        expected_operational_effect: "Preserves critical loads without dispatching resources.",
        resource_cost: { "operator": 1.0, "shift_kw": 2.0 },
        excluded_resources: {},
        priority_reason: "Protects cold chain and water purification pumps from cascading outage.",
        evidence_available: "Central Shelter load reports and infrastructure dependency model.",
        important_unknowns: "Fuel reserve delivery status unknown for East corridor.",
        resource_availability: "FEASIBLE: Generator Unit ready at Central Shelter.",
        route_accessibility: "Central road network Open.",
        decision_model: { need: "High", confidence: "High", feasibility: "Feasible" }
      } as any
    ],
    compatible_resources: [{ id: "res_348a10f74f374c47af445be276f0f3b8", name: "Synthetic Water Team Alpha" }]
  },
  audit: [{ event: "Active Operational Session Initialized" }]
};

const emptyWorkspace: WorkspaceData = {
  projections: [], candidates: [], evidence: [], resources: [], queue: [], tasks: [], places: [],
  verification: [], unlocks: [], plans: [], forecasts: [], resourceRequests: [],
};

const unavailableFlow: GoldenFlow = {
  source: "unavailable",
  source_detail: "No operational flow was returned by the API",
  data: emptyWorkspace,
  recommendation: { id: "", status: "unavailable", auto_dispatched: false, candidates: [], compatible_resources: [] },
  audit: [],
};

export function formatProvenanceLabel(summary: CommandSummary | null, label = "Provenance"): string {
  const provenance = summary?.provenance;
  const freshness = summary?.freshness?.state ?? "unknown";
  const sourceClass = provenance?.source_class ?? (summary?.source === "fallback" ? "synthetic_fixture" : "derived_model");
  const source = provenance?.source ?? (summary?.source ?? "unavailable");
  const synthetic = provenance?.synthetic || summary?.mode === "synthetic";
  return `${label}: ${sourceClass.replaceAll("_", " ")} · ${freshness}${synthetic ? " · synthetic" : ""} · source ${source}`;
}

function ProvenanceStamp({ summary, label = "Provenance" }: { summary: CommandSummary | null; label?: string }) {
  const text = formatProvenanceLabel(summary, label);
  return <small className="metric-provenance">{text}</small>;
}

function FieldReportIntake({ busy, onAccepted, setError }: { busy: boolean; onAccepted: () => void; setError: (value: string) => void }) {
  const [reportType, setReportType] = useState("life_safety");
  const [placeText, setPlaceText] = useState("");
  const [peopleAffected, setPeopleAffected] = useState("");
  const [latitude, setLatitude] = useState("26.184");
  const [longitude, setLongitude] = useState("91.742");
  const [status, setStatus] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setStatus("");
    try {
      await createEvidenceReport({ report_type: reportType, place_text: placeText, people_affected: peopleAffected ? Number(peopleAffected) : null, latitude: Number(latitude), longitude: Number(longitude) });
      setPlaceText("");
      setPeopleAffected("");
      setStatus("✓ Report submitted as Unverified. Queued for verification.");
      onAccepted();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not submit report");
    }
  }

  return (
    <div style={{borderTop: "1px solid var(--border-subtle)", paddingTop: "0.75rem", marginTop: "auto"}}>
      <div style={{fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-dim)", marginBottom: "0.5rem"}}>Quick Field Report Intake</div>
      <form onSubmit={(event) => void submit(event)} style={{display: "flex", flexDirection: "column", gap: "0.5rem"}}>
        <select aria-label="Report type" value={reportType} onChange={(event) => setReportType(event.target.value)} style={{fontSize: "0.8rem", padding: "0.5rem"}}>
          <option value="life_safety">Life safety / Rescue</option>
          <option value="access">Access / Blocked route</option>
          <option value="infrastructure">Infrastructure failure</option>
          <option value="contamination">Water contamination</option>
        </select>
        <input aria-label="Location" required placeholder="Location / Village name" value={placeText} onChange={(event) => setPlaceText(event.target.value)} style={{fontSize: "0.8rem", padding: "0.5rem"}} />
        <div style={{ display: "flex", gap: "0.35rem" }}>
          <input style={{ flex: 1, minWidth: 0, fontSize: "0.8rem", padding: "0.5rem" }} aria-label="Latitude" required min="-90" max="90" step="any" type="number" value={latitude} onChange={(event) => setLatitude(event.target.value)} />
          <input style={{ flex: 1, minWidth: 0, fontSize: "0.8rem", padding: "0.5rem" }} aria-label="Longitude" required min="-180" max="180" step="any" type="number" value={longitude} onChange={(event) => setLongitude(event.target.value)} />
        </div>
        <input aria-label="People affected" min="0" placeholder="People affected (optional)" type="number" value={peopleAffected} onChange={(event) => setPeopleAffected(event.target.value)} style={{fontSize: "0.8rem", padding: "0.5rem"}} />
        <button type="submit" className="btn-secondary" disabled={busy} style={{fontSize: "0.8rem", padding: "0.5rem"}}>Add to Map (Unverified)</button>
        <small style={{color: status.startsWith("✓") ? "var(--status-success)" : "var(--text-dim)", fontSize: "0.7rem"}}>{status || "New reports classified as Unverified until reviewed."}</small>
      </form>
    </div>
  );
}

export function CommandBrief({
  flow,
  busy,
  act,
  setError,
  workspaceMode,
  onViewEvidence,
  readOnly = false,
}: {
  flow: GoldenFlow | null;
  busy: boolean;
  act: (action: Action, selectedAction?: string, note?: string) => void;
  setError: (value: string) => void;
  workspaceMode?: "live" | "synthetic" | "mixed";
  onViewEvidence?: () => void;
  readOnly?: boolean;
}) {
  const [expandedDecision, setExpandedDecision] = useState<string | null>(null);
  const [modifyingAction, setModifyingAction] = useState<string | null>(null);
  const [drawerDetail, setDrawerDetail] = useState<DrawerDetail>(null);
  const [modifyNote, setModifyNote] = useState("");
  const [mapRefreshToken, setMapRefreshToken] = useState(0);
  const [summary, setSummary] = useState<CommandSummary | null>(null);
  const [summaryState, setSummaryState] = useState<"loading" | "ready" | "error">("loading");
  const [summaryError, setSummaryError] = useState("");
  const [cascadeFindings, setCascadeFindings] = useState<CascadeFinding[]>([]);
  const [cascadeState, setCascadeState] = useState<"loading" | "ready" | "error">("loading");
  const [cascadeMode, setCascadeMode] = useState<"live" | "synthetic" | "mixed">("live");
  const [telemetrySummary, setTelemetrySummary] = useState<TelemetrySummary | null>(null);
  const [telemetryState, setTelemetryState] = useState<"loading" | "ready" | "error">("loading");
  const [telemetryError, setTelemetryError] = useState("");
  const [summaryRetry, setSummaryRetry] = useState(0);
  const [telemetryRetry, setTelemetryRetry] = useState(0);
  const [cascadeRetry, setCascadeRetry] = useState(0);

  const usingSyntheticFallback = !flow && workspaceMode === "synthetic";
  const currentFlow = flow || (usingSyntheticFallback ? fallbackGoldenFlow : unavailableFlow);
  const usingFallbackFlow = !flow || readOnly || flow?.source === "fallback";

  useEffect(() => {
    let disposed = false;
    setSummaryState("loading");
    const refresh = () => {
      void getCommandSummary({ allowSyntheticFallback: workspaceMode === "synthetic" })
        .then((next) => { if (!disposed) { setSummary(next); setSummaryError(""); setSummaryState("ready"); } })
        .catch((reason: unknown) => { if (!disposed) { setSummary(null); setSummaryError(reason instanceof Error ? reason.message : "Command summary unavailable"); setSummaryState("error"); } });
    };
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [flow, workspaceMode, summaryRetry]);

  useEffect(() => {
    let disposed = false;
    setTelemetryState("loading");
    const refresh = () => {
      void getTelemetrySummary({ allowSyntheticFallback: workspaceMode === "synthetic" })
        .then((next) => {
          if (!disposed) {
            setTelemetrySummary(next);
            setTelemetryError("");
            setTelemetryState("ready");
          }
        })
        .catch((reason: unknown) => {
          if (!disposed) {
            setTelemetrySummary(null);
            setTelemetryError(reason instanceof Error ? reason.message : "Telemetry health unavailable");
            setTelemetryState("error");
          }
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [flow, workspaceMode, telemetryRetry]);

  useEffect(() => {
    let disposed = false;
    setCascadeState("loading");
    const refresh = () => {
      void getOperationalSnapshot({ allowSyntheticFallback: workspaceMode === "synthetic" })
        .then((next) => {
          if (!disposed) {
            setCascadeFindings(next.cascade_findings);
            setCascadeMode(next.mode);
            setCascadeState("ready");
          }
        })
        .catch(() => {
          if (!disposed) {
            setCascadeFindings([]);
            setCascadeState("error");
          }
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [flow, workspaceMode, cascadeRetry]);

  const status = currentFlow.recommendation.status;
  const task = currentFlow.data.tasks.find((item) => item.status !== "completed");
  const queueItem = currentFlow.data.queue.find((item) => item.id === currentFlow.recommendation.queue_item_id);
  const assignedResource = task ? currentFlow.data.resources.find((item) => item.id === task.resource) : undefined;

  const criticalProjections = currentFlow.data.projections.filter((p) => {
    const stateValue = p.state.toLowerCase();
    return stateValue.includes("critical") || p.time.includes("+") || stateValue.includes("immediate");
  });
  const watchProjections = currentFlow.data.projections.filter((p) => {
    const stateValue = p.state.toLowerCase();
    return stateValue.includes("expected") || stateValue.includes("pressure") || stateValue.includes("verification") || stateValue.includes("elevated");
  });
  const systemProjections = currentFlow.data.projections.filter(p => !criticalProjections.includes(p) && !watchProjections.includes(p));

  const silentPlace = currentFlow.data.places.find(p => p.isSilent || p.informationGap || p.state.toLowerCase() === "silent");
  const syntheticSignals = usingSyntheticFallback || workspaceMode === "synthetic" || currentFlow.source === "fallback" || summary?.source === "fallback" || summary?.data_quality.synthetic || summary?.mode === "synthetic" || telemetrySummary?.source === "fallback" || telemetrySummary?.mode === "synthetic" || telemetrySummary?.devices.some((device) => device.source_provenance.synthetic) || telemetrySummary?.gateways.some((gateway) => gateway.source_provenance.synthetic);
  const modeLabel = summaryState === "loading"
    ? workspaceMode === "live" ? "Loading live data" : "Loading summary"
    : summaryState === "error" ? "Live data unavailable"
    : summary?.source === "fallback" || currentFlow.source === "fallback" ? "Synthetic fallback"
    : workspaceMode === "mixed"
    ? (syntheticSignals ? "Mixed · synthetic signals" : "Mixed data")
    : syntheticSignals ? "Synthetic tabletop" : "Operational state";
  const sourceLabel = summary?.source === "api"
    ? "API"
    : summary?.source === "fallback" || currentFlow.source === "fallback"
    ? "Synthetic fixture fallback"
    : summary?.source === "cache"
    ? "Cache"
    : summary?.source === "unavailable" || summaryState === "error"
    ? "Unavailable"
    : "Not reported";
  const failureProjection = criticalProjections[0] || currentFlow.data.projections[0];
  const leadingCandidate = currentFlow.data.candidates[0];
  const freshnessValues = currentFlow.data.projections.map((item) => item.freshness.toLowerCase());
  const freshDataCount = freshnessValues.filter((value) => value.includes("live") || value.includes("fresh") || value.includes("verified") || value.includes("backend")).length;
  const staleDataCount = freshnessValues.filter((value) => value.includes("stale")).length;
  const contradictionCount = currentFlow.data.evidence.filter((item) => (item.classification || "").toLowerCase().includes("contradict")).length + freshnessValues.filter((value) => value.includes("contradict")).length;
  const unknownAreaCount = currentFlow.data.places.filter((place) => place.isSilent || place.informationGap || place.state.toLowerCase() === "silent").length;
  const failureFactors = [
    leadingCandidate?.priorityReason,
    leadingCandidate?.routeAccessibility,
    leadingCandidate?.resourceAvailability,
  ].filter(Boolean) as string[];

  useEffect(() => {
    if (usingFallbackFlow || !currentFlow.recommendation.id) return;
    void recordAuditInteraction("recommendation_viewed", "recommendation", currentFlow.recommendation.id).catch(() => undefined);
  }, [currentFlow.recommendation.id, usingFallbackFlow]);

  const handleEvidenceOpened = () => {
    const evidenceId = currentFlow.data.evidence[0]?.id;
    if (evidenceId && !usingFallbackFlow) {
      void recordAuditInteraction("evidence_opened", "evidence", evidenceId).catch(() => undefined);
    }
    onViewEvidence?.();
  };

  const handleScenarioEvaluated = (comparison: ScenarioComparison) => {
    void recordAuditInteraction("scenario_evaluated", "scenario", comparison.scenario_hash).catch(() => undefined);
  };


  return (
    <div style={{display: "flex", flexDirection: "column", gap: "1rem"}}>
      <section className="decision-pulse" aria-label="Decision pulse">
        <div className="decision-pulse-heading">
          <div><p className="eyebrow">Decision Pulse</p><h2>What needs attention now?</h2></div>
          <div className="decision-pulse-status"><span className="badge"><span className={`badge-dot ${syntheticSignals ? "warning" : ""}`} />{modeLabel}</span><span className="data-source-label" role="status">Source: {sourceLabel}</span></div>
        </div>
        {summaryState === "loading" && <div className="decision-pulse-state" role="status" aria-live="polite" aria-label="Loading operational summary">
          <span className="sr-only">Loading operational summary</span>
          <div className="section-skeleton" aria-hidden="true">
            <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
            <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
            <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
            <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
          </div>
        </div>}
        {summaryState === "error" && <div className="decision-pulse-state decision-pulse-state-error" role="alert" aria-live="assertive"><span>{summaryError}. Live operational data was not replaced.</span><button type="button" className="btn-secondary" onClick={() => setSummaryRetry((value) => value + 1)}>Retry summary</button></div>}
        {summaryState === "ready" && summary && <>
          <div className="decision-pulse-grid" role="group" aria-label="Decision pulse metrics">
            <div className="pulse-metric-card critical"><span>Water runway</span><strong>{summary.metrics.water_runway_hours ?? "—"}<small>{summary.metrics.water_runway_hours == null ? " unknown" : " hours"}</small></strong><em>Criticality window</em><span className="metric-status-text">{summary.metrics.water_runway_hours != null && summary.metrics.water_runway_hours < 6 ? "Critical attention" : "Monitor"}</span><ProvenanceStamp summary={summary} /></div>
            <div className="pulse-metric-card"><span>Ready resources</span><strong>{summary.metrics.ready_resources}<small>{` / ${summary.metrics.total_resources}`}</small></strong><em>Available to deploy</em><ProvenanceStamp summary={summary} /></div>
            <div className="pulse-metric-card unknown"><span>Verification debt</span><strong>{summary.metrics.verification_queue}</strong><em>Open information gaps</em><ProvenanceStamp summary={summary} /></div>
            <div className="pulse-metric-card"><span>Active missions</span><strong>{summary.metrics.active_tasks}</strong><em>Currently in motion</em><ProvenanceStamp summary={summary} /></div>
          </div>
          {summary.priorities.length ? <div className="decision-pulse-priorities">{summary.priorities.map((priority) => <div className={`pulse-priority ${priority.severity}`} key={priority.key}><span className="pulse-priority-dot" /><div><strong>{priority.label}</strong><small>{priority.reason}</small><ProvenanceStamp summary={summary} label="Priority provenance" /></div></div>)}</div> : <div className="decision-pulse-empty">No priority signals are currently available.</div>}
        </>}
      </section>

      <section className="failure-timeline" aria-labelledby="failure-timeline-heading">
        <div className="section-heading">
          <div><p className="eyebrow">Next Failure Timeline</p><h2 id="failure-timeline-heading">What is projected to fail next?</h2></div>
          <span className="semantic-status status-critical">Forecast, not certainty</span>
        </div>
        <div className="failure-timeline-grid">
          <div className="failure-primary">
            <span className="timeline-label">Current threat</span>
            <strong>{failureProjection?.resource || "No active threat projection"}</strong>
            <span className="timeline-note">{failureProjection?.state || "No failure projection is currently available."}</span>
          </div>
          <div className="failure-detail"><span className="timeline-label">Projected failure time</span><strong>{failureProjection?.time || "Unknown"}</strong><span className="timeline-note">Threshold crossing window</span></div>
          <div className="failure-detail"><span className="timeline-label">Confidence</span><strong>{leadingCandidate?.confidence || "Unknown"}</strong><span className="timeline-note">Based on available evidence</span></div>
          <div className="failure-factors"><span className="timeline-label">Main contributing factors</span><ul>{(failureFactors.length ? failureFactors : ["No contributing factors reported"]).slice(0, 3).map((factor) => <li key={factor}>{factor}</li>)}</ul></div>
        </div>
        <ProvenanceStamp summary={summary} label="Forecast provenance" />
      </section>

      <section className="data-trust-bar" aria-labelledby="data-trust-heading">
        <div><p className="eyebrow">Data Trust Bar</p><h2 id="data-trust-heading">How much should we trust this picture?</h2></div>
        <ul className="trust-items">
          <li><strong>{freshDataCount}</strong><span>Fresh data</span></li>
          <li><strong>{staleDataCount}</strong><span>Stale data</span></li>
          <li><strong>{contradictionCount}</strong><span>Contradictions</span></li>
          <li><strong>{unknownAreaCount}</strong><span>Unknown areas</span></li>
        </ul>
        <div className={`synthetic-indicator ${syntheticSignals ? "is-synthetic" : "is-operational"}`}><span aria-hidden="true">{syntheticSignals ? "◆" : "●"}</span><strong>{syntheticSignals ? "Synthetic data" : "Operational data"}</strong><span>{syntheticSignals ? "Training signal; not a live dispatch order" : "Live operational context"}</span></div>
      </section>

      <SensorHealthPanel summary={telemetrySummary} state={telemetryState} error={telemetryError} onRetry={() => setTelemetryRetry((value) => value + 1)} />
      <CascadePanel findings={cascadeFindings} state={cascadeState} mode={cascadeMode === "live" && syntheticSignals ? "synthetic" : cascadeMode} onViewEvidence={onViewEvidence} onRetry={() => setCascadeRetry((value) => value + 1)} />
      <ScenarioLab mode={workspaceMode} onScenarioEvaluated={handleScenarioEvaluated} />

      {!usingFallbackFlow && <div className="legacy-command-context">
      {/* 4 CORE DASHBOARD FOCUS QUESTIONS (Requirement 8) */}
      <div style={{display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "0.75rem"}}>
        <div style={{background: "var(--bg-surface)", border: "1px solid var(--border-light)", borderLeft: "4px solid var(--status-critical)", borderRadius: "var(--radius-sm)", padding: "0.75rem 1rem"}}>
          <div style={{fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase", color: "var(--status-critical)", letterSpacing: "0.05em"}}>1. Attention First</div>
          <div style={{fontSize: "0.85rem", fontWeight: 700, color: "var(--text-main)", marginTop: "0.25rem"}}>North Sector Water Runway</div>
          <div style={{fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.15rem"}}>Runway &lt; 3.5h. Contamination breach coupled with 180 incoming evacuees.</div>
        </div>

        <div style={{background: "var(--bg-surface)", border: "1px solid var(--border-light)", borderLeft: "4px solid #8b5cf6", borderRadius: "var(--radius-sm)", padding: "0.75rem 1rem"}}>
          <div style={{fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase", color: "#8b5cf6", letterSpacing: "0.05em"}}>2. Still to Verify</div>
          <div style={{fontSize: "0.85rem", fontWeight: 700, color: "var(--text-main)", marginTop: "0.25rem"}}>Dharapur Silent Village</div>
          <div style={{fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.15rem"}}>0 field reports in 6h (Pop: 4,200). Silence is operational uncertainty, not safety.</div>
        </div>

        <div style={{background: "var(--bg-surface)", border: "1px solid var(--border-light)", borderLeft: "4px solid var(--accent-cyan)", borderRadius: "var(--radius-sm)", padding: "0.75rem 1rem"}}>
          <div style={{fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase", color: "var(--accent-cyan)", letterSpacing: "0.05em"}}>3. Limited Resources Next</div>
          <div style={{fontSize: "0.85rem", fontWeight: 700, color: "var(--text-main)", marginTop: "0.25rem"}}>Water Team Alpha &amp; Rescue Boat 1</div>
          <div style={{fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.15rem"}}>Deploy to North Sector via open waterway and NH-27 bypass.</div>
        </div>

        <div style={{background: "var(--bg-surface)", border: "1px solid var(--border-light)", borderLeft: "4px solid var(--status-success)", borderRadius: "var(--radius-sm)", padding: "0.75rem 1rem"}}>
          <div style={{fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase", color: "var(--status-success)", letterSpacing: "0.05em"}}>4. Operational Rationale (Why)</div>
          <div style={{fontSize: "0.85rem", fontWeight: 700, color: "var(--text-main)", marginTop: "0.25rem"}}>Feasible Route &amp; High Impact</div>
          <div style={{fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.15rem"}}>Avoids washed-out NH-27 bridge while protecting potable water continuity.</div>
        </div>
      </div>

      {/* INFORMATION GAP / SILENT VILLAGE BANNER (Requirement 3) */}
      {silentPlace && (
        <div style={{
          background: "linear-gradient(90deg, rgba(139, 92, 246, 0.15) 0%, rgba(245, 158, 11, 0.1) 100%)",
          border: "1px solid rgba(139, 92, 246, 0.4)",
          borderLeft: "5px solid #8b5cf6",
          borderRadius: "var(--radius-md)",
          padding: "0.85rem 1.25rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "0.75rem"
        }}>
          <div>
            <div style={{display: "flex", alignItems: "center", gap: "0.5rem"}}>
              <span style={{background: "#8b5cf6", color: "white", padding: "2px 6px", borderRadius: "4px", fontSize: "0.7rem", fontWeight: 800}}>INFORMATION GAP</span>
              <strong style={{color: "var(--text-main)", fontSize: "0.95rem"}}>Dharapur Village — Verification Required</strong>
            </div>
            <p style={{margin: "0.25rem 0 0 0", fontSize: "0.8rem", color: "var(--text-muted)"}}>
              Village has received <strong>0 field reports</strong> in the last 6 hours (Estimated pop: 4,200). <em>Do not assume it is safe — missing information is operational uncertainty.</em>
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary"
            style={{background: "rgba(139, 92, 246, 0.25)", borderColor: "#8b5cf6", color: "var(--text-main)", fontSize: "0.8rem"}}
            onClick={() => setMapRefreshToken((current) => current + 1)}
          >
            Assign Reconnaissance Mission
          </button>
        </div>
      )}
      </div>}

      {/* 3-COLUMN DASHBOARD */}
      <div className="command-brief-grid">
        {/* LEFT: DECISIONS & HUMAN-IN-THE-LOOP (Requirement 1, 4, 7) */}
        <div className="brief-column">
          <section className="decision-queue" aria-labelledby="decision-queue-heading">
            <div className="brief-column-header decision-queue-header">
              <h2 id="decision-queue-heading">Decision Queue</h2>
              <span className="semantic-status status-warning">Commander approval required</span>
            </div>
            <p className="approval-notice">Recommendations are advisory. The Incident Commander remains the final authority; autonomous dispatch is disabled.</p>
            {!usingFallbackFlow && currentFlow.recommendation.id ? (
              <section className="live-recommendation-state" aria-label="Live recommendation execution state" role="status">
                <div><span>Recommendation</span><strong>{currentFlow.recommendation.id}</strong></div>
                <div><span>Queue status</span><strong>{queueItem?.status ?? (status === "approved" ? "Queued status unavailable" : "Not created")}</strong></div>
                <div><span>Assigned resource</span><strong>{assignedResource?.name ?? (task?.resource ?? "Not assigned")}</strong></div>
                <div><span>Task status</span><strong>{task?.status ?? "No task assigned"}</strong></div>
              </section>
            ) : null}

          <div style={{display: "flex", flexDirection: "column", gap: "0.75rem"}}>
            {!currentFlow.data.candidates.length && <div className="empty-state" role="status">No recommendation was loaded from the API. Approval, assignment, and dispatch controls are unavailable until operational data is returned.</div>}
            {currentFlow.data.candidates.slice(0, 3).map((item) => {
              const isExpanded = expandedDecision === item.action;
              const isModifying = modifyingAction === item.action;
              const dm = item.decisionModel || { need: "High", confidence: "Medium", feasibility: "Feasible" };

              return (
                <article className="candidate decision-card" key={item.action}>
                  <div className="candidate-header decision-card-toggle">
                    <div className="candidate-meta">
                      <span className="candidate-priority">#{item.rank} Priority</span>
                      <span className="candidate-confidence">{item.confidence}</span>
                    </div>

                    <h3>{item.action}</h3>

                    <span className={`approval-state ${status === "pending_approval" ? "approval-pending" : "approval-resolved"}`}>
                      {status === "pending_approval" ? "Awaiting Incident Commander approval" : `Approval state: ${status}`}
                    </span>

                    {/* DECISION MODEL BADGES (Requirement 7) */}
                    <div style={{display: "flex", gap: "0.35rem", flexWrap: "wrap", margin: "0.35rem 0"}}>
                      <span style={{fontSize: "0.65rem", fontWeight: 700, padding: "0.15rem 0.4rem", borderRadius: "3px", background: dm.need === "Critical" ? "var(--status-critical-bg)" : "var(--bg-panel)", color: dm.need === "Critical" ? "var(--status-critical)" : "var(--text-muted)", border: "1px solid var(--border-light)"}}>
                        NEED: {dm.need.toUpperCase()}
                      </span>
                      <span style={{fontSize: "0.65rem", fontWeight: 700, padding: "0.15rem 0.4rem", borderRadius: "3px", background: "var(--bg-panel)", color: "var(--accent-primary-hover)", border: "1px solid var(--border-light)"}}>
                        CONFIDENCE: {dm.confidence.toUpperCase()}
                      </span>
                      <span style={{fontSize: "0.65rem", fontWeight: 700, padding: "0.15rem 0.4rem", borderRadius: "3px", background: dm.feasibility === "Feasible" ? "var(--status-success-bg)" : "var(--status-warning-bg)", color: dm.feasibility === "Feasible" ? "var(--status-success)" : "var(--status-warning)", border: "1px solid var(--border-light)"}}>
                        FEASIBILITY: {dm.feasibility.toUpperCase()}
                      </span>
                    </div>

                    {/* EXPLAINABILITY SUMMARY (Requirement 4) */}
                    <div className="candidate-summary">
                      <strong>Why this is prioritized</strong>
                      <span>{item.priorityReason || `${item.effect.split('.')[0]}.`}</span>
                      <ProvenanceStamp summary={summary} label="Decision provenance" />
                    </div>
                    <button
                      type="button"
                      className="decision-expand-toggle"
                      aria-expanded={isExpanded}
                      aria-controls={`decision-drawer-${item.rank}`}
                      onClick={() => { setExpandedDecision(isExpanded ? null : item.action); setDrawerDetail(null); }}
                    >
                      {isExpanded ? "Hide decision details" : "Review decision details"}
                    </button>
                  </div>

                  {/* EXPLAINABLE DRAWER (Requirement 4) */}
                  {isExpanded && (
                    <aside className="candidate-drawer action-drawer" id={`decision-drawer-${item.rank}`} aria-label={`Actions and rationale for ${item.action}`}>
                      <dl className="decision-facts">
                        <div><dt>Why now</dt><dd>{item.priorityReason || item.effect}</dd></div>
                        <div><dt>Evidence</dt><dd>{item.evidenceAvailable || "Sensor reports + reconnaissance"}</dd></div>
                        <div><dt>Unknowns</dt><dd>{item.importantUnknowns || "No material unknowns reported"}</dd></div>
                        <div><dt>Cost</dt><dd>{item.cost || "Cost not estimated"}</dd></div>
                        <div><dt>Expected benefit</dt><dd>{item.effect}</dd></div>
                      </dl>

                      <div className="drawer-reference-actions" aria-label="Decision references">
                        <button type="button" className="btn-secondary" onClick={() => { setDrawerDetail(drawerDetail === "evidence" ? null : "evidence"); handleEvidenceOpened(); }}>View evidence</button>
                        <button type="button" className="btn-secondary" onClick={() => setDrawerDetail(drawerDetail === "excluded" ? null : "excluded")}>View excluded resources</button>
                        <button type="button" className="btn-secondary" onClick={() => setDrawerDetail(drawerDetail === "assumptions" ? null : "assumptions")}>View assumptions</button>
                      </div>

                      {drawerDetail === "evidence" && <div className="drawer-detail" role="status"><strong>Evidence trace</strong><p>{item.evidenceAvailable || "No evidence summary is available."}</p></div>}
                      {drawerDetail === "excluded" && <div className="drawer-detail" role="status"><strong>Excluded resources</strong><p>{item.excluded || "None recorded for this option."}</p></div>}
                      {drawerDetail === "assumptions" && <div className="drawer-detail" role="status"><strong>Assumptions</strong><p>{item.routeAccessibility || "Route assumptions unavailable."} {item.resourceAvailability || "Resource assumptions unavailable."}</p></div>}

                      {/* MODIFY DRAWER (Requirement 1) */}
                      {isModifying ? (
                        <div style={{background: "var(--bg-panel)", padding: "0.75rem", borderRadius: "var(--radius-sm)", marginBottom: "0.75rem", border: "1px solid var(--accent-primary)"}}>
                          <strong style={{fontSize: "0.75rem", color: "var(--accent-primary-hover)", display: "block", marginBottom: "0.4rem"}}>Commander Directive / Modification</strong>
                          <textarea
                            aria-label="Commander modification note"
                            placeholder="Add commander modifications, resource overrides, or constraints..."
                            value={modifyNote}
                            onChange={(e) => setModifyNote(e.target.value)}
                            style={{width: "100%", height: 60, fontSize: "0.75rem", marginBottom: "0.5rem"}}
                          />
                          <div style={{display: "flex", gap: "0.5rem"}}>
                            <button
                              type="button"
                              className="btn-primary"
                              disabled={busy}
                              onClick={() => {
                                act("modify", item.actionId ?? item.action, modifyNote);
                                setModifyingAction(null);
                              }}
                              style={{fontSize: "0.75rem", flex: 1}}
                            >
                              ✓ Authorize Modified Action
                            </button>
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={() => setModifyingAction(null)}
                              style={{fontSize: "0.75rem"}}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : null}

                      {/* ACTION BUTTONS: APPROVE / MODIFY / REJECT (Requirement 1) */}
                      {status === "pending_approval" && usingFallbackFlow && !isModifying && (
                        <p className="preview-only-notice" role="status">Preview only: load an operational or tabletop recommendation before requesting commander approval.</p>
                      )}
                      {status === "pending_approval" && !usingFallbackFlow && !isModifying && (
                        <div className="drawer-actions">
                          <button
                            type="button"
                            className="btn-primary"
                            disabled={busy}
                            onClick={() => act("approve", item.actionId ?? item.action)}
                            style={{fontSize: "0.8rem"}}
                          >
                            ✓ Approve Option
                          </button>
                          <div style={{display: "flex", gap: "0.5rem"}}>
                            <button
                              type="button"
                              className="btn-secondary"
                              disabled={busy}
                              onClick={() => setModifyingAction(item.action)}
                              style={{flex: 1, fontSize: "0.75rem"}}
                            >
                              ✎ Modify Option
                            </button>
                            <button
                              type="button"
                              className="btn-danger"
                              disabled={busy}
                              onClick={() => act("reject", item.action)}
                              style={{flex: 1, fontSize: "0.75rem"}}
                            >
                              ✗ Reject Option
                            </button>
                          </div>
                        </div>
                      )}
                    </aside>
                  )}
                </article>
              );
            })}
          </div>
          </section>

          {/* Task progression buttons */}
          <div style={{marginTop: "auto", paddingTop: "0.5rem"}}>
            {!usingFallbackFlow && status === "approved" && !task && (
              <button type="button" className="btn-primary" disabled={busy} onClick={() => act("assign")} style={{width: "100%", padding: "0.85rem"}}>Confirm Route &amp; Deploy</button>
            )}
            {!usingFallbackFlow && task?.status === "assigned" && (
              <button type="button" className="btn-primary" disabled={busy} onClick={() => act("acknowledged")} style={{width: "100%", padding: "0.85rem"}}>Acknowledge Task</button>
            )}
            {!usingFallbackFlow && task?.status === "acknowledged" && (
              <button type="button" className="btn-primary" disabled={busy} onClick={() => act("en_route")} style={{width: "100%", padding: "0.85rem"}}>Mark En Route</button>
            )}
            {!usingFallbackFlow && task?.status === "en_route" && (
              <div style={{display: "flex", flexDirection: "column", gap: "0.5rem"}}>
                <button type="button" className="btn-primary" disabled={busy} onClick={() => act("on_scene")} style={{padding: "0.85rem"}}>Arrived On Scene</button>
                <button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")} style={{fontSize: "0.8rem"}}>Pause Mission</button>
              </div>
            )}
            {!usingFallbackFlow && task?.status === "on_scene" && (
              <div style={{display: "flex", flexDirection: "column", gap: "0.5rem"}}>
                <button type="button" className="btn-primary" disabled={busy} onClick={() => act("completed")} style={{padding: "0.85rem"}}>Mark Completed</button>
                <button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")} style={{fontSize: "0.8rem"}}>Pause Mission</button>
              </div>
            )}
            {!usingFallbackFlow && task?.status === "paused" && (
              <button type="button" className="btn-secondary" disabled={busy} onClick={() => act("en_route")} style={{width: "100%", padding: "0.85rem"}}>Resume Mission</button>
            )}
          </div>

          <FieldReportIntake busy={busy} setError={setError} onAccepted={() => setMapRefreshToken((current) => current + 1)} />
        </div>

        {/* CENTER: MAP WITH 4-TIER REPORT & ROUTE HIGHLIGHTS */}
        <div className="brief-column" style={{padding: "0", background: "transparent", border: "none"}}>
          <MapCOP setError={setError} isSynthetic={workspaceMode === "synthetic"} refreshToken={mapRefreshToken} />
        </div>

        {/* RIGHT: LIVE STATUS, RESOURCE FEASIBILITY & DECISION MATRIX (Requirement 5, 6, 7) */}
        <div className="brief-column">
          <div className="brief-column-header">
            <span>Operational Matrix &amp; Status</span>
          </div>

          {/* LOCATION DECISION MODEL MATRIX (Requirement 7) */}
          <div style={{background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.75rem"}}>
            <div style={{fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase", color: "var(--text-dim)", marginBottom: "0.5rem"}}>
              Location Decision Model
            </div>
            <div style={{display: "flex", flexDirection: "column", gap: "0.5rem"}}>
              {currentFlow.data.places.map((place) => {
                const dm = place.decisionModel || { need: "Medium", confidence: "Medium", feasibility: "Feasible" };
                const route = place.routeFeasibility || "unknown";
                return (
                  <div key={place.id} style={{fontSize: "0.75rem", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "0.35rem"}}>
                    <div style={{display: "flex", justifyContent: "space-between", alignItems: "center"}}>
                      <strong style={{color: place.isSilent ? "#8b5cf6" : "var(--text-main)"}}>{place.label.split('·')[0]}</strong>
                      <span style={{fontSize: "0.65rem", color: route === "blocked" ? "var(--status-critical)" : route === "open" ? "var(--status-success)" : "var(--status-warning)", textTransform: "uppercase", fontWeight: 700}}>
                        {route}
                      </span>
                    </div>
                    <div style={{display: "flex", gap: "0.25rem", marginTop: "0.25rem", fontSize: "0.65rem"}}>
                      <span style={{color: dm.need === "Critical" ? "var(--status-critical)" : "var(--text-muted)"}}>NEED: {dm.need}</span>
                      <span>·</span>
                      <span style={{color: "var(--text-muted)"}}>CONF: {dm.confidence}</span>
                      <span>·</span>
                      <span style={{color: dm.feasibility === "Feasible" ? "var(--status-success)" : "var(--status-warning)"}}>FEAS: {dm.feasibility}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* PULSE GROUPS */}
          <div style={{display: "flex", flexDirection: "column", gap: "0.75rem"}}>
            {criticalProjections.length > 0 && (
              <div className="pulse-group">
                <h4>🔴 Critical Threats</h4>
                {criticalProjections.map((item) => (
                  <div className="pulse-row pulse-critical" key={item.resource}>
                    <span className="pulse-title">{item.resource}</span>
                    <span className="pulse-metric">{item.time}</span>
                    <span className="pulse-state">{item.state}</span>
                  </div>
                ))}
              </div>
            )}

            {watchProjections.length > 0 && (
              <div className="pulse-group">
                <h4>🟡 Watch &amp; Unverified</h4>
                {watchProjections.map((item) => (
                  <div className="pulse-row pulse-watch" key={item.resource}>
                    <span className="pulse-title">{item.resource}</span>
                    <span className="pulse-metric">{item.time}</span>
                    <span className="pulse-state">{item.state}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="pulse-group">
              <h4>🔵 Tracking</h4>
              {systemProjections.map((item) => (
                <div className="pulse-row pulse-system" key={item.resource}>
                  <span className="pulse-title">{item.resource}</span>
                  <span className="pulse-state" style={{marginTop: 0}}>{item.state}</span>
                  <span className="pulse-freshness">{item.freshness}</span>
                </div>
              ))}

              <div className="pulse-row pulse-system">
                <span className="pulse-title">Scenario Integrity</span>
                <span className="pulse-metric" style={{fontSize: "0.85rem", color: workspaceMode === "live" ? "var(--status-success)" : "var(--status-warning)"}}>✦ {workspaceMode === "live" ? "Live Feed Mode" : workspaceMode === "mixed" ? "Mixed Mode Data" : "Synthetic Tabletop Data"}</span>
                <span className="pulse-freshness">{workspaceMode === "live" || workspaceMode === "mixed" ? "Verified live feeds enabled" : "Verified provenance · no live dispatch"}</span>
              </div>
            </div>
          </div>

          <div className="unknown-box">
            <strong>⚠ Unknowns Detected</strong>
            <p>Some data is contradictory or stale. Silence is operational uncertainty — unverified areas are not safe.</p>
          </div>

          {currentFlow.audit.length ? (
            <div style={{background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.65rem", fontSize: "0.7rem", color: "var(--text-dim)", marginTop: "0.5rem"}}>
              <strong style={{display: "block", marginBottom: "0.25rem"}}>Audit Trail</strong>
              <div>{String(currentFlow.audit[currentFlow.audit.length - 1]?.event || "No events")}</div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
