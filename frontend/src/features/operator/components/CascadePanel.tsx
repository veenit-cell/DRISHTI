import { useEffect, useState } from "react";
import type { CascadeFinding } from "../api";

type CascadePanelProps = {
  findings: CascadeFinding[];
  state?: "loading" | "ready" | "error";
  mode?: "live" | "synthetic" | "mixed";
  onViewEvidence?: () => void;
  onRetry?: () => void;
};

const CANONICAL_DEPENDENCY_PATH = [
  { key: "power", label: "Power" },
  { key: "water_purification", label: "Water purification" },
  { key: "safe_water", label: "Safe water" },
  { key: "medical_demand", label: "Medical demand" },
];

const INTERVENTION_CONTEXT: Record<string, { consumed: string; protected: string }> = {
  safe_water_runway: { consumed: "Water treatment and purification capacity", protected: "Safe-water continuity" },
  medicine_cold_chain: { consumed: "Power reserve and medical support capacity", protected: "Medicine cold-chain continuity" },
  operational_disease_risk_pressure: { consumed: "Safe-water capacity and verification effort", protected: "Operational disease-risk pressure control" },
  medicine_diagnostic_pressure: { consumed: "Diagnostic and medical support capacity", protected: "Medicine and diagnostic capability" },
};
const PATH_ALIASES: Record<string, string> = {
  "safe water runway": "safe water",
  "medicine cold chain": "medicine cold chain",
  "operational disease risk pressure": "operational disease risk pressure",
  "medicine diagnostic pressure": "medicine diagnostic pressure",
};

function pathKey(value: string): string {
  return value.toLowerCase().replaceAll("_", " ").replaceAll("-", " ").trim();
}

function dependencyKey(value: string): string {
  const normalized = pathKey(value);
  return PATH_ALIASES[normalized] || normalized;
}

function displayPathLabel(value: string): string {
  const canonical = CANONICAL_DEPENDENCY_PATH.find((node) => dependencyKey(node.key) === dependencyKey(value) || dependencyKey(node.label) === dependencyKey(value));
  if (canonical) return canonical.label;
  return value.replaceAll("_", " ");
}

export function findingFreshness(finding: CascadeFinding): "stale" | "uncertain" | "fresh" {
  const contributors = finding.unknown_contributors.map((value) => value.toLowerCase());
  if (contributors.some((value) => value.includes("stale"))) return "stale";
  if (contributors.length) return "uncertain";
  return "fresh";
}

export function CascadePanel({ findings, state = "ready", mode = "live", onViewEvidence, onRetry }: CascadePanelProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  useEffect(() => {
    setSelectedIndex((current) => Math.min(current, Math.max(findings.length - 1, 0)));
  }, [findings.length]);
  const selected = findings.length ? findings[Math.min(selectedIndex, findings.length - 1)] : null;
  const selectedPath = new Set((selected?.causal_path || []).map(dependencyKey));
  const visiblePath = selected?.causal_path.length
    ? selected.causal_path
    : CANONICAL_DEPENDENCY_PATH.map((node) => node.label);
  const intervention = selected ? INTERVENTION_CONTEXT[selected.affected_capability] || {
    consumed: "Not specified by the evaluator",
    protected: selected.affected_capability.replaceAll("_", " "),
  } : null;
  const freshness = selected ? findingFreshness(selected) : "uncertain";

  return (
    <section className="cascade-panel" aria-labelledby="cascade-panel-heading">
      <div className="cascade-panel-heading">
        <div>
          <p className="eyebrow">Dependency &amp; Cascade View</p>
          <h2 id="cascade-panel-heading">What fails if a dependency is lost?</h2>
        </div>
        <span className={`semantic-status ${mode === "synthetic" ? "status-warning" : "status-info"}`}>
          {mode === "synthetic" ? "Synthetic evaluation" : mode === "mixed" ? "Mixed evaluation" : "Operational evaluation"}
        </span>
      </div>

      {state === "loading" && <div className="cascade-state" role="status" aria-live="polite" aria-label="Loading dependency findings">
        <span className="sr-only">Loading dependency findings</span>
        <div className="section-skeleton section-skeleton-cascade" aria-hidden="true">
          <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
          <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
        </div>
      </div>}
      {state === "error" && <div className="cascade-state cascade-state-error" role="alert"><span>Cascade findings unavailable. The operational view remains unchanged.</span>{onRetry && <button type="button" className="btn-secondary" onClick={onRetry}>Retry cascade data</button>}</div>}
      {state === "ready" && !findings.length && <div className="cascade-state" role="status">No cascade findings are available for this shelter state.</div>}

      {state === "ready" && (
        <div className="cascade-layout">
          <div className="cascade-findings" role="region" aria-label="Cascade findings">
            {findings.map((finding, index) => (
              <button
                type="button"
                className={`cascade-finding ${selectedIndex === index ? "is-selected" : ""}`}
                aria-pressed={selectedIndex === index}
                key={`${finding.affected_capability}-${index}`}
                onClick={() => setSelectedIndex(index)}
              >
                <span className="cascade-finding-severity">{finding.severity}</span>
                <strong>{finding.affected_capability.replaceAll("_", " ")}</strong>
                <span>{finding.estimated_time_window_hours == null ? "Time window unknown" : `${finding.estimated_time_window_hours}h window`}</span>
              </button>
            ))}
          </div>

          <div className="cascade-detail" aria-live="polite" aria-atomic="false">
            <div className="dependency-path" aria-label="Causal dependency path">
              {visiblePath.map((node, index) => (
                <div className="dependency-step" key={`${node}-${index}`}>
                    <span className={`dependency-node ${selectedPath.has(dependencyKey(node)) ? "is-highlighted" : ""}`}>
                    <span className="dependency-node-index">{index + 1}</span>
                    {displayPathLabel(node)}
                  </span>
                  {index < visiblePath.length - 1 && <span className="dependency-arrow" aria-hidden="true">→</span>}
                </div>
              ))}
            </div>

            {selected && (
              <div className="cascade-detail-grid">
                <div><span className="timeline-label">Affected capability</span><strong>{selected.affected_capability.replaceAll("_", " ")}</strong></div>
                <div><span className="timeline-label">Severity</span><strong>{selected.severity}</strong></div>
                <div><span className="timeline-label">Time window</span><strong>{selected.estimated_time_window_hours == null ? "Unknown" : `${selected.estimated_time_window_hours} hours`}</strong></div>
                <div><span className="timeline-label">Confidence</span><strong>{selected.confidence}</strong></div>
              </div>
            )}

            {selected && intervention && (
              <div className="intervention-context">
                <div><span className="timeline-label">Intervention resource consumed</span><strong>{intervention.consumed}</strong></div>
                <div><span className="timeline-label">Capability protected</span><strong>{intervention.protected}</strong></div>
              </div>
            )}

            {selected && (
              <div className="cascade-uncertainty">
                <div className="cascade-uncertainty-heading"><strong>Uncertainty and input quality</strong><span className={`semantic-status ${freshness === "stale" ? "status-critical" : freshness === "uncertain" ? "status-warning" : "status-success"}`}>{freshness} inputs</span></div>
                {selected.unknown_contributors.length ? <ul>{selected.unknown_contributors.map((item) => <li key={item}>{item}</li>)}</ul> : <p>No unknown contributors reported for this finding.</p>}
              </div>
            )}

            {selected && (
              <div className="cascade-references">
                <div className="cascade-uncertainty-heading"><strong>Supporting references</strong>{onViewEvidence && <button type="button" className="btn-ghost" onClick={onViewEvidence}>View evidence</button>}</div>
                {selected.supporting_input_refs.length ? <ul>{selected.supporting_input_refs.map((reference) => <li key={reference}>{reference}</li>)}</ul> : <p>No supporting references recorded.</p>}
              </div>
            )}
          </div>
        </div>
      )}
      <p className="cascade-disclaimer">Evaluation is read-only decision support. It does not diagnose patients, dispatch resources, or change operational state.</p>
    </section>
  );
}
