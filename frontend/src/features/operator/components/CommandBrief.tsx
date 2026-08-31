import { type FormEvent, useState } from "react";
import { createEvidenceReport, type GoldenFlow } from "../api";
import { MapCOP } from "./MapCOP";

type Action = "approve" | "reject" | "assign" | "acknowledged" | "en_route" | "on_scene" | "paused" | "completed";

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
      setStatus("Report accepted as unverified evidence; map refreshed.");
      onAccepted();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Field report submission failed");
    }
  }

  return <form className="approval-panel" onSubmit={(event) => void submit(event)} style={{ marginTop: "1rem" }}>
    <strong>FIELD REPORT INTAKE</strong>
    <select aria-label="Report type" value={reportType} onChange={(event) => setReportType(event.target.value)}>
      <option value="life_safety">Life safety</option>
      <option value="access">Access / route</option>
      <option value="infrastructure">Infrastructure</option>
    </select>
    <input aria-label="Report location" required placeholder="Location or sector" value={placeText} onChange={(event) => setPlaceText(event.target.value)} />
    <div style={{ display: "flex", gap: "0.5rem" }}>
      <input style={{ flex: 1, minWidth: 0 }} aria-label="Latitude" required min="-90" max="90" step="any" type="number" value={latitude} onChange={(event) => setLatitude(event.target.value)} />
      <input style={{ flex: 1, minWidth: 0 }} aria-label="Longitude" required min="-180" max="180" step="any" type="number" value={longitude} onChange={(event) => setLongitude(event.target.value)} />
    </div>
    <input aria-label="People affected" min="0" placeholder="People affected (optional)" type="number" value={peopleAffected} onChange={(event) => setPeopleAffected(event.target.value)} />
    <button type="submit" className="btn-secondary" disabled={busy}>Add report to map</button>
    {status ? <small>{status}</small> : <small>New reports remain unverified until reviewed.</small>}
  </form>;
}

export function CommandBrief({
  flow,
  busy,
  act,
  setError
}: {
  flow: GoldenFlow | null;
  busy: boolean;
  act: (action: Action, selectedAction?: string) => void;
  setError: (value: string) => void;
}) {
  const [expandedDecision, setExpandedDecision] = useState<string | null>(null);
  const [mapRefreshToken, setMapRefreshToken] = useState(0);

  if (!flow) {
    return (
      <div className="workspace-placeholder">
        <p className="eyebrow">COMMAND BRIEF</p>
        <h2>Awaiting Intelligence</h2>
        <p>No operational flow loaded. Activate an incident or reset the golden replay.</p>
      </div>
    );
  }

  const status = flow.recommendation.status;
  const task = flow.data.tasks.find((item) => item.status !== "completed");

  const criticalProjections = flow.data.projections.filter(p => p.state.includes("critical") || p.time.includes("+") || p.state.includes("immediate"));
  const watchProjections = flow.data.projections.filter(p => p.state.includes("expected") || p.state.includes("pressure") || p.state.includes("verification") || p.state.includes("elevated"));
  const systemProjections = flow.data.projections.filter(p => !criticalProjections.includes(p) && !watchProjections.includes(p));

  return (
    <div className="command-brief-grid">
      {/* LEFT: DECISION COLUMN */}
      <div className="brief-column">
        <div className="brief-column-header">Dominant Decisions</div>

        <div style={{display: "flex", flexDirection: "column", gap: "1rem"}}>
          {flow.data.candidates.slice(0, 3).map((item) => {
            const isExpanded = expandedDecision === item.action;
            return (
              <article className="candidate" key={item.action}>
                <div
                  className="candidate-header"
                  onClick={() => setExpandedDecision(isExpanded ? null : item.action)}
                >
                  <div className="candidate-meta">
                    <span className="candidate-priority">#{item.rank} PRIORITY</span>
                    <span className="candidate-confidence">{item.confidence}</span>
                  </div>
                  <h3>{item.action}</h3>
                  <div className="candidate-summary">
                    <strong>Why now</strong>
                    <span>{item.effect.split('.')[0]}.</span>
                    {item.cost && (
                      <>
                        <strong>Blocker</strong>
                        <span>{item.cost.split('.')[0]}.</span>
                      </>
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="candidate-drawer">
                    <div style={{marginBottom: "1rem"}}>
                      <strong style={{color: "var(--text-main)", display: "block", marginBottom: "0.25rem"}}>PROVENANCE & DETAILS</strong>
                      <div><strong>Full effect:</strong> {item.effect}</div>
                      <div><strong>Full cost:</strong> {item.cost}</div>
                      <div><strong>Excluded options:</strong> {item.excluded}</div>
                    </div>

                    {status === "pending_approval" && (
                      <div className="drawer-actions">
                        <button type="button" className="btn-primary" disabled={busy} onClick={() => act("approve", item.actionId ?? item.action)}>Approve Option</button>
                        <div style={{display: "flex", gap: "0.5rem"}}>
                          <button type="button" className="btn-secondary" disabled={busy} onClick={() => act("reject", item.action)} style={{flex: 1}}>Review Evidence</button>
                          <button type="button" className="btn-secondary" disabled={busy} onClick={() => act("reject", item.action)} style={{flex: 1}}>Pause / Override</button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>

        <div className="approval-panel" style={{marginTop: "auto"}}>
          {status === "approved" && !task && (
            <button type="button" className="btn-primary" disabled={busy} onClick={() => act("assign")} style={{width: "100%", padding: "1rem"}}>CONFIRM ROUTE & DEPLOY ASSET</button>
          )}
          {task?.status === "assigned" && (
            <button type="button" className="btn-primary" disabled={busy} onClick={() => act("acknowledged")} style={{width: "100%", padding: "1rem"}}>ASSET: ACKNOWLEDGE TASK</button>
          )}
          {task?.status === "acknowledged" && (
            <button type="button" className="btn-primary" disabled={busy} onClick={() => act("en_route")} style={{width: "100%", padding: "1rem"}}>ASSET: MARK EN ROUTE</button>
          )}
          {task?.status === "en_route" && (
            <div style={{display: "flex", flexDirection: "column", gap: "0.5rem", width: "100%"}}>
              <button type="button" className="btn-primary" disabled={busy} onClick={() => act("on_scene")} style={{padding: "1rem"}}>ASSET: MARK ON SCENE</button>
              <button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")}>PAUSE MISSION</button>
            </div>
          )}
          {task?.status === "on_scene" && (
            <div style={{display: "flex", flexDirection: "column", gap: "0.5rem", width: "100%"}}>
              <button type="button" className="btn-primary" disabled={busy} onClick={() => act("completed")} style={{padding: "1rem"}}>ASSET: MARK COMPLETED</button>
              <button type="button" className="btn-danger" disabled={busy} onClick={() => act("paused")}>PAUSE MISSION</button>
            </div>
          )}
          {task?.status === "paused" && (
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => act("en_route")} style={{width: "100%", padding: "1rem"}}>RESUME MISSION</button>
          )}
        </div>
        <FieldReportIntake busy={busy} setError={setError} onAccepted={() => setMapRefreshToken((current) => current + 1)} />
      </div>

      {/* CENTER: COMMON OPERATING PICTURE (MAP) */}
      <div className="brief-column" style={{padding: "0", background: "transparent", border: "none"}}>
        <MapCOP setError={setError} isSynthetic={true} refreshToken={mapRefreshToken} />
      </div>

      {/* RIGHT: COMMAND PULSE */}
      <div className="brief-column">
        <div className="brief-column-header">Command Pulse</div>

        <div style={{display: "flex", flexDirection: "column", gap: "1rem"}}>

          {criticalProjections.length > 0 && (
            <div className="pulse-group">
              <h4>Critical</h4>
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
              <h4>Watch</h4>
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
            <h4>System</h4>
            {systemProjections.map((item) => (
              <div className="pulse-row pulse-system" key={item.resource}>
                <span className="pulse-title">{item.resource}</span>
                <span className="pulse-state" style={{marginTop: 0}}>{item.state}</span>
                <span className="pulse-freshness">{item.freshness}</span>
              </div>
            ))}

            {/* System Connection State - Explicitly showing as requested by system */}
            <div className="pulse-row pulse-system">
              <span className="pulse-title">DATA</span>
              <span className="pulse-metric">Live replay</span>
              <span className="pulse-freshness">Last trusted update {new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })}</span>
            </div>
          </div>

        </div>

        <div className="unknown-box">
          <strong>TACTICAL UNKNOWNS DETECTED</strong>
          <p>Contradictory influx and stale constraints require verification. Do not treat as safe.</p>
        </div>

        {flow.audit.length ? (
          <div style={{background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: "4px", padding: "0.75rem", fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "1rem"}}>
            <strong>LATEST ACTION</strong>
            <div style={{marginTop: "0.5rem"}}>{String(flow.audit[flow.audit.length - 1]?.event || "No events")}</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
