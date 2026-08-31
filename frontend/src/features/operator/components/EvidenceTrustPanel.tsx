import { useMemo, useState } from "react";
import type { EvidenceReport, EvidenceReportDetail } from "../api";

export type EvidenceTrustFilter = "all" | "confirmed" | "unverified" | "contradictory" | "stale" | "unknown" | "high_decision_impact";

type EvidenceTrustPanelProps = {
  reports: EvidenceReport[];
  selected: EvidenceReportDetail | null;
  busy?: boolean;
  verificationQueued?: boolean;
  verificationAssignedAt?: string | null;
  onSelect: (reportId: string) => void;
  onVerify: (claimId: string, state: "corroborated" | "contradicted" | "unknown") => void;
  onQueueVerification: () => void;
};

const FILTER_LABELS: Record<EvidenceTrustFilter, string> = {
  all: "All",
  confirmed: "Confirmed",
  unverified: "Unverified",
  contradictory: "Contradictory",
  stale: "Stale",
  unknown: "Unknown",
  high_decision_impact: "High decision impact",
};

const HIGH_DECISION_IMPACT_TYPES = new Set(["life_safety", "water_contamination", "access_blocked", "infrastructure"]);

function normalized(value: string): string {
  return value.toLowerCase().replaceAll("_", " ");
}

export function evidenceFreshness(report: EvidenceReport, now = Date.now()): "fresh" | "stale" | "unknown" {
  const text = `${report.status} ${report.warnings.join(" ")}`.toLowerCase();
  const claims: EvidenceReportDetail["claims"] = "claims" in report && Array.isArray(report.claims) ? report.claims as EvidenceReportDetail["claims"] : [];
  if (claims.some((claim) => claim.verification_state.toLowerCase() === "stale")) return "stale";
  if (text.includes("stale")) return "stale";
  if (!report.observed_at) return "unknown";
  const observed = Date.parse(report.observed_at);
  if (Number.isNaN(observed)) return "unknown";
  return now - observed > 6 * 60 * 60 * 1000 ? "stale" : "fresh";
}

export function evidenceClassification(report: EvidenceReport): "confirmed" | "unverified" | "contradictory" | "unknown" {
  const text = `${report.status} ${report.warnings.join(" ")}`.toLowerCase();
  const claims: EvidenceReportDetail["claims"] = "claims" in report && Array.isArray(report.claims) ? report.claims as EvidenceReportDetail["claims"] : [];
  if (claims.some((claim) => claim.verification_state.toLowerCase() === "contradicted")) return "contradictory";
  if (text.includes("contradict") || text.includes("conflict")) return "contradictory";
  if (claims.length && claims.every((claim) => ["corroborated", "confirmed"].includes(claim.verification_state.toLowerCase()))) return "confirmed";
  if (claims.some((claim) => ["unknown", "proposed"].includes(claim.verification_state.toLowerCase()))) return "unknown";
  if (claims.some((claim) => claim.verification_state.toLowerCase() === "unverified")) return "unverified";
  if (text.includes("corroborat") || text.includes("confirm")) return "confirmed";
  if (text.includes("unknown") || text.includes("silent")) return "unknown";
  return "unverified";
}

export function highDecisionImpact(report: EvidenceReport): boolean {
  return HIGH_DECISION_IMPACT_TYPES.has(report.report_type) || Boolean(report.duplicate_candidates?.length) || evidenceClassification(report) === "contradictory";
}

function confidence(detail: EvidenceReportDetail): "high" | "medium" | "low" | "unknown" {
  const states = detail.claims.map((claim) => claim.verification_state.toLowerCase());
  if (!states.length) return "unknown";
  if (states.some((state) => state === "contradicted" || state === "stale")) return "low";
  if (states.some((state) => state === "unknown" || state === "proposed" || state === "unverified")) return "medium";
  if (states.every((state) => state === "corroborated" || state === "confirmed")) return "high";
  return "unknown";
}

function importantUnknowns(detail: EvidenceReportDetail): string[] {
  const unknowns = [...detail.warnings];
  if (!detail.observed_at) unknowns.push("Observed time is unknown.");
  if (!detail.received_at) unknowns.push("Received time is unknown.");
  if (!detail.location?.place_text) unknowns.push("Location is unknown.");
  detail.claims.filter((claim) => ["unknown", "proposed", "unverified", "stale"].includes(claim.verification_state.toLowerCase())).forEach((claim) => {
    unknowns.push(`Claim requires verification: ${claim.claim_type.replaceAll("_", " ")}.`);
  });
  return [...new Set(unknowns)];
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unknown" : parsed.toLocaleString();
}

function timeline(detail: EvidenceReportDetail, verificationAssignedAt?: string | null) {
  const contradiction = detail.duplicate_candidates.length || detail.claims.some((claim) => claim.verification_state.toLowerCase() === "contradicted");
  return [
    { label: "Report received", time: detail.received_at ?? detail.recorded_at, detail: detail.received_at ? "Received timestamp" : "Receipt timestamp unavailable; recorded time shown" },
    { label: "Report reviewed", time: detail.reviewed_at ?? (detail.status.toLowerCase().includes("reviewed") ? detail.recorded_at : null), detail: detail.reviewed_at ? `Reviewed by ${detail.reviewed_by ?? "operator"}` : "Not yet recorded" },
    { label: "Contradiction discovered", time: contradiction ? detail.recorded_at : null, detail: contradiction ? "Contradictory claim or duplicate candidate recorded" : "No contradiction recorded" },
    { label: "Verification assigned", time: verificationAssignedAt, detail: verificationAssignedAt ? "Verification queue assignment recorded in this session" : "Not assigned" },
    { label: "Decision affected", time: detail.affected_recommendations?.length ? detail.recorded_at : null, detail: detail.affected_recommendations?.length ? "Linked recommendation reference" : "No affected recommendation recorded" },
  ];
}

export function EvidenceTrustPanel({ reports, selected, busy = false, verificationQueued = false, verificationAssignedAt, onSelect, onVerify, onQueueVerification }: EvidenceTrustPanelProps) {
  const [filter, setFilter] = useState<EvidenceTrustFilter>("all");
  const visibleReports = useMemo(() => reports.filter((report) => {
    if (filter === "all") return true;
    if (filter === "stale") return evidenceFreshness(report) === "stale";
    if (filter === "high_decision_impact") return highDecisionImpact(report);
    return evidenceClassification(report) === filter;
  }), [filter, reports]);
  const selectedFreshness = selected ? evidenceFreshness(selected) : "unknown";
  const selectedClassification = selected ? evidenceClassification(selected) : "unknown";
  const selectedUnknowns = selected ? importantUnknowns(selected) : [];
  const selectedTimeline = selected ? timeline(selected, verificationAssignedAt) : [];
  const isSynthetic = selected ? `${selected.source.channel} ${selected.source.source_class} ${selected.warnings.join(" ")}`.toLowerCase().includes("synthetic") : false;

  return (
    <section className="evidence-trust-panel" aria-labelledby="evidence-trust-heading">
      <div className="evidence-trust-heading">
        <div>
          <p className="eyebrow">Evidence Trust</p>
          <h2 id="evidence-trust-heading">What can this report support?</h2>
          <p className="evidence-trust-note">Raw reports remain immutable. This view exposes scoped provenance and review state without displaying raw sensitive payloads.</p>
        </div>
        <span className="semantic-status status-info">Tenant/workspace scoped</span>
      </div>

      <div className="evidence-trust-filters" role="toolbar" aria-label="Evidence trust filters">
        {(Object.keys(FILTER_LABELS) as EvidenceTrustFilter[]).map((key) => {
          const count = key === "all" ? reports.length : visibleReports.length && filter === key ? visibleReports.length : reports.filter((report) => key === "stale" ? evidenceFreshness(report) === "stale" : key === "high_decision_impact" ? highDecisionImpact(report) : evidenceClassification(report) === key).length;
          return <button type="button" key={key} className={filter === key ? "btn-primary" : "btn-secondary"} aria-pressed={filter === key} onClick={() => setFilter(key)}>{FILTER_LABELS[key]} ({count})</button>;
        })}
      </div>

      <div className="evidence-trust-layout">
        <div className="evidence-trust-list" role="region" aria-label="Evidence reports">
          {visibleReports.length ? visibleReports.map((report) => {
            const classification = evidenceClassification(report);
            const freshness = evidenceFreshness(report);
            return <button type="button" className={`evidence-trust-row ${selected?.id === report.id ? "is-selected" : ""}`} aria-pressed={selected?.id === report.id} key={report.id} onClick={() => onSelect(report.id)}>
              <span className="evidence-row-heading"><strong>{normalized(report.report_type)}</strong><span className="evidence-row-state">{classification}</span></span>
              <span>{report.source.channel} · {freshness} · {formatTime(report.received_at ?? report.recorded_at)}</span>
              <span>{highDecisionImpact(report) ? "High decision impact" : "Standard decision impact"}{report.duplicate_candidates?.length ? ` · ${report.duplicate_candidates.length} duplicate candidate(s)` : ""}</span>
            </button>;
          }) : <div className="empty-state">No reports match this trust filter.</div>}
        </div>

        <div className="evidence-trust-detail" role="region" aria-live="polite" aria-label="Selected evidence report details">
          {selected ? <>
            <div className="evidence-detail-heading">
              <div><span className="eyebrow">Selected report</span><h3>{normalized(selected.report_type)}</h3></div>
              <div className="evidence-detail-badges"><span className="semantic-status status-info">{selectedClassification}</span><span className={`semantic-status ${selectedFreshness === "stale" ? "status-critical" : selectedFreshness === "unknown" ? "status-warning" : "status-success"}`}>{selectedFreshness} data</span></div>
            </div>
            {isSynthetic && <div className="evidence-synthetic-notice" role="status">Synthetic provenance is visible. Treat this report as a training or replay signal.</div>}
            <dl className="evidence-facts">
              <div><dt>Report source</dt><dd>{selected.source.channel}</dd></div>
              <div><dt>Source class</dt><dd>{selected.source.source_class}</dd></div>
              <div><dt>Observed time</dt><dd>{formatTime(selected.observed_at)}</dd></div>
              <div><dt>Received time</dt><dd>{formatTime(selected.received_at)}</dd></div>
              <div><dt>Verification status</dt><dd>{selected.status}</dd></div>
              <div><dt>Confidence</dt><dd>{confidence(selected)}</dd></div>
              <div><dt>Linked incident</dt><dd>{selected.command_incident_links.length ? selected.command_incident_links.map((link) => link.incident_id).join(", ") : "No linked incident"}</dd></div>
              <div><dt>Affected recommendation</dt><dd>{selected.affected_recommendations?.length ? selected.affected_recommendations.map((item) => `${item.action} (${item.status})`).join(", ") : "No affected recommendation recorded"}</dd></div>
            </dl>

            <div className="evidence-trust-subsection"><h4>Contradictions and duplicate candidates</h4>{selected.duplicate_candidates.length ? <ul>{selected.duplicate_candidates.map((candidate) => <li key={candidate.candidate_report_id}>{candidate.candidate_report_id}: {candidate.reason}</li>)}</ul> : <p>No duplicate candidates recorded.</p>}{selected.claims.filter((claim) => claim.verification_state.toLowerCase() === "contradicted").map((claim) => <p key={claim.id}>Contradicted claim: {claim.claim_type.replaceAll("_", " ")}</p>)}</div>
            <div className="evidence-trust-subsection"><h4>Important unknowns</h4>{selectedUnknowns.length ? <ul>{selectedUnknowns.map((unknown) => <li key={unknown}>{unknown}</li>)}</ul> : <p>No material unknowns recorded.</p>}</div>

            <div className="evidence-timeline"><h4>Evidence timeline</h4><ol>{selectedTimeline.map((item) => <li key={item.label} className={item.time ? "is-recorded" : "is-unknown"}><span className="evidence-timeline-marker" aria-hidden="true" /> <div><strong>{item.label}</strong><span>{formatTime(item.time)}</span><small>{item.detail}</small></div></li>)}</ol></div>

            <div className="evidence-review-actions"><button type="button" className="btn-primary" disabled={busy || verificationQueued} onClick={onQueueVerification}>{verificationQueued ? "Verification assigned" : "Assign verification"}</button>{selected.claims.map((claim) => <div className="evidence-claim-review" key={claim.id}><span>{claim.claim_type.replaceAll("_", " ")} · {claim.verification_state}</span><button type="button" className="btn-secondary" disabled={busy} onClick={() => onVerify(claim.id, "corroborated")}>Confirm</button><button type="button" className="btn-secondary" disabled={busy} onClick={() => onVerify(claim.id, "contradicted")}>Contradict</button><button type="button" className="btn-secondary" disabled={busy} onClick={() => onVerify(claim.id, "unknown")}>Unknown</button></div>)}</div>
          </> : <div className="empty-state">Select a report to inspect source trust, contradictions, review lineage, and decision impact.</div>}
        </div>
      </div>
    </section>
  );
}
