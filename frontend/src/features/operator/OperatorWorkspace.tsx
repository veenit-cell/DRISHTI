import { useEffect, useState } from "react";
import { advanceTask, assignApproved, decide, resetGoldenFlow, type GoldenFlow } from "./api";
import { demoWorkspace, type WorkspaceData } from "./fixtures";

type Action = "approve" | "reject" | "assign" | "acknowledged" | "en_route" | "completed";

function Signals({ data }: { data: WorkspaceData }) {
  return <section className="workspace-section"><h2>What fails next, and why</h2><div className="signal-grid">{data.projections.map((item) => <article className="signal-card" key={item.resource}><span>{item.resource}</span><strong>{item.time}</strong><span>{item.state}</span><small>{item.freshness}</small></article>)}</div><div className="unknown-box"><strong>Unknowns stay visible</strong><p>Contradictory influx and stale constraints require verification; they are never treated as safe.</p></div></section>;
}

function Recommendation({ flow, busy, act }: { flow: GoldenFlow; busy: boolean; act: (action: Action) => void }) {
  const status = flow.recommendation.status;
  const task = flow.data.tasks.find((item) => item.status !== "completed");
  return <section className="workspace-section"><div className="section-heading"><div><p className="eyebrow">Live deterministic policy</p><h2>Ranked interventions · {status}</h2></div><span className="badge">Auto-dispatch: {String(flow.recommendation.auto_dispatched)}</span></div><div className="candidate-list">{flow.data.candidates.map((item) => <article className="candidate" key={item.action}><div className="rank">#{item.rank}</div><div><h3>{item.action}</h3><p><strong>Effect:</strong> {item.effect}</p><p><strong>Cost:</strong> {item.cost} · <strong>Confidence:</strong> {item.confidence}</p><p><strong>Excluded:</strong> {item.excluded}</p></div></article>)}</div><div className="approval">{status === "pending_approval" && <><button disabled={busy} onClick={() => act("approve")}>Commander approve</button><button disabled={busy} onClick={() => act("reject")}>Reject</button></>}{status === "approved" && !task && <button disabled={busy} onClick={() => act("assign")}>Confirm route + manually assign</button>}{task?.status === "assigned" && <button disabled={busy} onClick={() => act("acknowledged")}>Acknowledge task</button>}{task?.status === "acknowledged" && <button disabled={busy} onClick={() => act("en_route")}>Mark en route</button>}{task?.status === "en_route" && <button disabled={busy} onClick={() => act("completed")}>Complete and record outcome</button>}</div></section>;
}

function Operations({ flow }: { flow: GoldenFlow }) {
  return <section className="workspace-section"><h2>Resources, both queues, tasks, and audit</h2><div className="ops-grid"><div><h3>Resources</h3>{flow.data.resources.map((item) => <p className="ops-row" key={item.id}><strong>{item.name}</strong><span>{item.readiness}</span><small>{item.task}</small></p>)}</div><div><h3>Response + verification queues</h3>{flow.data.queue.map((item) => <p className="ops-row" key={item.id}><strong>{item.title}</strong><span>{item.status}</span></p>)}<h3>Tasks</h3>{flow.data.tasks.map((item) => <p className="ops-row" key={item.id}><strong>{item.resource}</strong><span>{item.status}</span><small>{item.outcome}</small></p>)}</div></div><p className="verification-note"><strong>Audit:</strong> {flow.audit.map((item) => String(item.event)).join(" → ") || "No events"}</p></section>;
}

export function OperatorWorkspace() {
  const [flow, setFlow] = useState<GoldenFlow | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "offline" | "error">("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() { setState("loading"); setError(""); try { setFlow(await resetGoldenFlow()); setState("ready"); } catch (reason) { setError(reason instanceof Error ? reason.message : "API unavailable"); setState("error"); } }
  useEffect(() => { void load(); }, []);
  async function act(action: Action) { if (!flow) return; setBusy(true); setError(""); try { setFlow(action === "approve" || action === "reject" ? await decide(flow, action) : action === "assign" ? await assignApproved(flow) : await advanceTask(flow, action)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Action failed"); } finally { setBusy(false); } }
  if (state === "loading") return <main className="shell"><div className="state-banner" role="status">Loading live synthetic replay…</div></main>;
  if (state === "error") return <main className="shell"><div className="state-banner state-error" role="alert">Backend error: {error}</div><button onClick={() => void load()}>Retry real API</button><button onClick={() => setState("offline")}>Use explicit offline fixture</button></main>;
  if (state === "offline") return <main className="shell"><div className="state-banner" role="status">Offline fixture · not live backend data</div><Signals data={demoWorkspace} /><button onClick={() => void load()}>Reconnect</button></main>;
  if (!flow) return null;
  return <main className="shell"><div className="state-banner" role="status"><strong>Connected to real backend</strong>{busy ? " · applying command…" : " · server authoritative"}<button onClick={() => void load()}>Reset golden replay</button></div><header className="workspace-hero"><p className="eyebrow">Shelter Survival Intelligence · live API flow</p><h1>From coupled failure to accountable action.</h1><p>Replay → projection → ranked intervention → commander approval → manual task lifecycle → outcome → audit.</p></header>{error && <div className="unknown-box" role="alert">{error}</div>}<Signals data={flow.data} /><Recommendation flow={flow} busy={busy} act={act} /><Operations flow={flow} /></main>;
}
