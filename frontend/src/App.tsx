import { useEffect, useState } from "react";

import {
  ApiStatus,
  ReportDetail,
  ReportSummary,
  createReport,
  readApiStatus,
  readMapFeatures,
  readReport,
  readReports,
  seedDemo,
} from "./api";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; value: ApiStatus }
  | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<ReportDetail | null>(null);
  const [workbenchError, setWorkbenchError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reportType, setReportType] = useState("water_contamination");
  const [placeText, setPlaceText] = useState("Synthetic North Sector");

  async function refreshEvidence() {
    setWorkbenchError(null);
    try {
      const [nextReports, map] = await Promise.all([readReports(), readMapFeatures()]);
      setReports(nextReports);
      setSelectedReport((current) => (current ? current : null));
      return map.features.length;
    } catch (error: unknown) {
      setWorkbenchError(error instanceof Error ? error.message : "Evidence path unavailable.");
      return null;
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    readApiStatus(controller.signal)
      .then((value) => setState({ kind: "ready", value }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : "API check failed.";
          setState({ kind: "error", message });
        }
    });
    void refreshEvidence();
    return () => controller.abort();
  }, []);

  async function handleSeed() {
    setBusy(true);
    try {
      await seedDemo();
      await refreshEvidence();
    } finally {
      setBusy(false);
    }
  }

  async function handleCreate() {
    setBusy(true);
    try {
      const created = await createReport(reportType, placeText);
      await refreshEvidence();
      const detail = await readReport(created.report_id);
      setSelectedReport(detail);
    } catch (error: unknown) {
      setWorkbenchError(error instanceof Error ? error.message : "Report could not be created.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSelect(reportId: string) {
    try {
      setSelectedReport(await readReport(reportId));
    } catch (error: unknown) {
      setWorkbenchError(error instanceof Error ? error.message : "Report detail unavailable.");
    }
  }

  return (
    <main className="shell">
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">District operations · Phase 1 foundation</p>
        <h1 id="page-title">Evidence-to-action starts with a trustworthy boundary.</h1>
        <p className="summary">
          This checkpoint proves the application shell, scoped development identity, stable
          contracts, and local persistence path. Operational disaster features intentionally begin
          in later phases.
        </p>
      </section>

      <section className="status-card" aria-live="polite">
        <div>
          <span className={`status-dot status-dot--${state.kind}`} aria-hidden="true" />
          <span className="status-label">System boundary</span>
        </div>
        {state.kind === "loading" && <p>Checking API health…</p>}
        {state.kind === "error" && (
          <p>
            <strong>Unavailable.</strong> {state.message}
          </p>
        )}
        {state.kind === "ready" && (
          <p>
            <strong>{state.value.service}</strong> v{state.value.version} · {state.value.detail}
          </p>
        )}
      </section>

      <section className="principles" aria-label="Foundation guarantees">
        <article>
          <span>01</span>
          <h2>Explicit scope</h2>
          <p>Actor, tenant, workspace, permission, and correlation context are resolved together.</p>
        </article>
        <article>
          <span>02</span>
          <h2>Honest state</h2>
          <p>Unknown is not zero, replay time is not wall time, and IDs never authorize access.</p>
        </article>
        <article>
          <span>03</span>
          <h2>Safe evolution</h2>
          <p>Versioned events and one migration path anchor the later evidence-to-action loop.</p>
        </article>
      </section>

      <section className="workbench" aria-labelledby="workbench-title">
        <div className="workbench-heading">
          <div>
            <p className="eyebrow">Phase 2 · evidence workbench</p>
            <h2 id="workbench-title">Reports stay traceable from intake to map.</h2>
          </div>
          <button type="button" onClick={() => void handleSeed()} disabled={busy}>
            {busy ? "Working…" : "Seed synthetic incidents"}
          </button>
        </div>

        <div className="workbench-grid">
          <div className="panel">
            <div className="panel-heading">
              <h3>New report</h3>
              <span className="muted">synthetic demo input</span>
            </div>
            <label>
              Report type
              <input value={reportType} onChange={(event) => setReportType(event.target.value)} />
            </label>
            <label>
              Place text
              <input value={placeText} onChange={(event) => setPlaceText(event.target.value)} />
            </label>
            <button type="button" onClick={() => void handleCreate()} disabled={busy || !reportType}>
              Create immutable report
            </button>
            {workbenchError && <p className="error-text">{workbenchError}</p>}
          </div>

          <div className="panel">
            <div className="panel-heading">
              <h3>Recent reports</h3>
              <span className="muted">{reports.length} loaded</span>
            </div>
            {reports.length === 0 ? (
              <p className="muted">No reports in this workspace yet.</p>
            ) : (
              <ul className="report-list">
                {reports.map((report) => (
                  <li key={report.id}>
                    <button type="button" className="report-row" onClick={() => void handleSelect(report.id)}>
                      <span>
                        <strong>{report.report_type}</strong>
                        <small>{report.location?.place_text ?? "Location unknown"}</small>
                      </span>
                      <span className="state-chip">{report.status}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel detail-panel">
            <div className="panel-heading">
              <h3>Original + lineage</h3>
              <span className="muted">read-only</span>
            </div>
            {selectedReport ? (
              <>
                <p className="hash">SHA-256 {selectedReport.original_sha256}</p>
                <p>
                  {selectedReport.claims.length} derived claims · {selectedReport.normalization?.mapping_version}
                </p>
                <pre>{JSON.stringify(selectedReport.original_payload, null, 2)}</pre>
              </>
            ) : (
              <p className="muted">Select a report to inspect its preserved payload.</p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
