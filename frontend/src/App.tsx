import { useEffect, useState } from "react";

import { ApiStatus, readApiStatus } from "./api";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; value: ApiStatus }
  | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

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
    return () => controller.abort();
  }, []);

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
    </main>
  );
}
