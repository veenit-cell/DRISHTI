# Architecture Alignment Status

## `shelter-state`

**Status:** Implemented as a local synthetic/PostgreSQL slice; not a production shelter registry.

### Delivered

- Fixed metric vocabulary covering population/capacity/influx, water, treatment, power/battery, medicine, cold chain, diagnostics, replenishment, and thresholds.
- Nullable measurements preserve unknown values; units are validated and never inferred.
- Immutable, time-stamped observations carry source, freshness, and provenance.
- Scoped shelter and observation APIs with development identity authorization and idempotency.
- Deterministic current snapshots merge the newest observation per field and expose field freshness, source, provenance, and a stable snapshot hash.
- Synthetic `shelter_demo_north` seed is explicitly labeled.
- In-memory adapter supports isolated tests; PostgreSQL adapter persists shelters, observations, and snapshots.

### Evidence

- Code: `backend/app/shelter_state.py`, `backend/app/api/routes.py`, `backend/app/main.py`.
- Migration: `backend/migrations/0012_shelter_state.sql`.
- Tests: `backend/tests/test_shelter_state.py`, `backend/tests/test_postgres_shelter_state.py`.
- API: `POST /api/v1/shelters`, `POST /api/v1/shelters/{id}/observations`, `GET /api/v1/shelters/{id}/state`, `POST /api/v1/shelter-state/demo/seed`.

### Verification

| Command | Result |
|---|---|
| `.\.venv\Scripts\python.exe -m app.persistence` | migrations applied |
| `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` | passed |
| `.\.venv\Scripts\python.exe -m pytest backend/tests -q` | 39 passed |
| `npm --prefix frontend run build` | TypeScript and Vite build passed |
| `git diff --check` | passed |

## `runway-projection`

**Status:** Implemented as a pure, bounded deterministic module.

- `backend/app/runway.py` defines a typed snapshot adapter and `runway_v1` formulas for water, battery/power, medicine, and cold-chain reserve.
- Population influx adjusts demand; explicit thresholds, capacities, replenishment, freshness, units, contributors, confidence, and horizon flags are returned.
- Missing/invalid required inputs return `unknown`; stale inputs remain labeled with low confidence; net replenishment returns `not_depleting`.
- `POST /api/v1/runway/projections` evaluates an explicit snapshot without persistence or mutation.
- Tests cover depletion, threshold crossing, replenishment, invalid/unknown/stale inputs, deterministic replay, formula version, and API immutability.

Verification update: `pytest backend/tests -q` = **43 passed**; Ruff, frontend build, migrations, and `git diff --check` passed.

Limitations: battery projections require explicit battery capacity and replenishment inputs; cold-chain depletion requires an explicit rate; treatment capacity is reported as context but not assumed to produce potable water without a confirmed transfer.

## `cascade-engine`

**Status:** Implemented as an independently startable, pure `cascade_v1` evaluator.

- `backend/app/cascade.py` accepts a typed snapshot adapter with explicit units, timestamps, freshness, and supporting references.
- Fixed bounded rules cover power → purification → safe-water runway, power → medicine cold chain, unsafe water + population pressure → operational disease-risk pressure, and rising medical demand → medicine/diagnostic pressure.
- Findings include severity, optional time window, ordered causal path, references, unknown contributors, confidence, and rule version. Unknown/stale inputs never become safe; they lower confidence and remain visible.
- `POST /api/v1/cascade/evaluate` evaluates an explicit snapshot under `decision:read` without persistence or operational mutation.
- Graph validation rejects malformed cycles and paths beyond the four-level bound; output ordering is stable.

Verification update: `pytest backend/tests/test_cascade.py -q` = **4 passed**; `pytest backend/tests -q` = **47 passed**; Ruff and `git diff --check` passed.

Limitations: this is an operational pressure/capability signal, not a clinical diagnosis, forecast, dispatch, or ML model. It uses caller-supplied snapshot fixtures and does not infer missing measurements.

## `what-if`

**Status:** Implemented as a bounded, evaluation-only intervention comparison module.

- `backend/app/what_if.py` adapts explicit runway snapshots and supports four synthetic interventions: potable-water addition, purification rate/power cost, non-critical load shifting, and expected influx changes.
- Every request returns baseline, do-nothing, and intervention projections with changed inputs, trade-offs, uncertainty, per-scenario hashes, and a stable input hash. Source snapshots are deep-copied and never mutated.
- Units, intervention combinations, and horizons are validated; extra live IDs/provenance/timestamp mutation fields are rejected by the typed contract.
- `POST /api/v1/what-if/evaluate` is scoped to `decision:read` and never writes operational state.

Verification update: `pytest backend/tests/test_what_if.py -q` = **3 passed**; full suite and diff checks recorded in the handoff.

Limitations: interventions are synthetic, single-action comparisons over caller-provided runway inputs; no live state, transfer workflow, or persistence is involved.

## `decision-policy`

**Status:** Implemented as a versioned deterministic intervention policy (`intervention_policy_v1`).

- `backend/app/decision_policy.py` accepts typed snapshot, runway projection, cascade, and resource adapters and generates/ranks three bounded candidates: water delivery/treatment, non-critical power shifting, and medicine/cold-chain support.
- Candidates include evidence, reasons, resource cost, expected benefit/effect, time sensitivity, confidence, expiry, input hash, excluded resources/reasons, and remain `pending_approval`.
- Readiness, capability, route, expiry, and active-task constraints are hard exclusions. Stable sorting and an explicit all-infeasible greedy fallback keep execution bounded and reproducible.
- `POST /api/v1/decision-policy/evaluate` is evaluation-only. Existing recommendation responses now expose policy candidates; commander approval remains queue-only and `auto_dispatched=false`.

Verification update: `pytest backend/tests/test_decision_policy.py backend/tests/test_decision_loop.py -q` = **5 passed**; full suite and Ruff recorded in handoff.

Limitations: resource effects are synthetic policy signals; PostgreSQL recommendation persistence retains the existing schema and does not persist the full candidate set as separate rows.

## `decision-snapshot`

**Status:** Implemented as a scoped, immutable evidence/incident integration adapter.

- `backend/app/decision_snapshot.py` resolves reports, reviewed/contradictory claims, linked incidents, sector assessments, operational observations, and policy version into a canonical snapshot.
- Each source retains exact ID, revision, event/recorded timestamps, freshness, uncertainty, visible and accepted claims, and source data. Future records are excluded at replay time; out-of-scope records are rejected.
- Contradictions and unknowns remain visible. Missing decision-critical claims or linked incidents create verification candidates with explicit decision-impact reasons. Synthetic provenance is labeled.
- `POST /api/v1/decision-snapshot/build` enforces caller tenant/workspace scope and is read-only.

Verification update: `pytest backend/tests/test_decision_snapshot.py -q` = **4 passed**; full suite = **58 passed**; Ruff and diff check passed.

Limitations: this packet does not rewrite evidence/decision persistence or invent a live snapshot store; callers provide already-resolved scoped records.

## `operator-workspace`

**Status:** Implemented as a small feature-oriented React operator workspace.

- `frontend/src/features/operator/OperatorWorkspace.tsx` separates decision overview, recommendations, evidence provenance, operations, and spatial list components; `fixtures.ts` is explicitly labeled synthetic fallback data.
- The screen answers failure/next failure/time/why, unknown and stale state, intervention comparison, recommendation, do-nothing framing, excluded resources, commander approval/rejection, evidence provenance, both queues, readiness/routes, task lifecycle, outcomes, and bounded coordinates.
- Loading, offline, unauthorized, error, and empty states are explicit and text-labelled; status is not conveyed by color alone. GeoJSON is represented as an accessible coordinate list because no map library is installed.
- `OperatorWorkspace.contract.test.ts` provides dependency-free component contract assertions; no backend domain logic is implemented in React.

Verification update: `npm --prefix frontend run build` (TypeScript + Vite production build) passed. Fixture contract assertions are available to a browser/test harness; no test runner dependency was added.

Limitations: read-only intelligence endpoints are not yet aggregated into one frontend client, so this checkpoint uses clearly labeled local fixtures for the complete operator flow.

## `offline-sync`

**Status:** Implemented as a minimum honest field PWA workflow with explicit server authority.

- `backend/app/offline_sync.py` provides a bounded (20-command) authenticated/scoped reconciliation API for report, acknowledgement, en_route, completion, route-observation, and outcome commands. Client IDs and timestamps are preserved; each result is accepted, replayed, conflict, or rejected.
- Per-aggregate sequence checks stop later commands after an unresolved ordering conflict; the expected sequence can resolve the block. Duplicate command IDs replay without reapplying.
- `frontend/src/features/operator/offline.ts` provides a bounded IndexedDB outbox, retry behavior, last-sync/unsent/conflict visibility, printable task packets, and paper/radio fallback. Only task/command metadata is cached.
- `POST /api/v1/offline-sync` authenticates `operations:write` and enforces tenant/workspace scope.

Verification update: `pytest backend/tests -q` = **60 passed**; `npm --prefix frontend run build` passed TypeScript and production Vite build; Ruff and diff check passed.

Limitations: this is not offline synchronization, GPS tracking, mesh networking, background upload, or shell-cache authority. Conflicted items remain client-side until an in-order command resolves them; server reconciliation is authoritative.

## `security-boundary`

**Status:** Hardened development/test identity boundary with an OIDC-compatible seam and bounded request protection.

- `backend/app/core/context.py` centralizes role, organization, workspace/event, and scope resolution. `OIDCVerifier` is the provider seam; `LocalOIDCVerifier` accepts only deterministic `local:<identity>[:expiry]` test tokens. Development identity is rejected in production by `Settings` validation.
- `IdentityRateLimitMiddleware` applies a one-process per-identity fixed-window limit and returns a consistent problem response. Request logs contain method/path/timing only; no credentials or identity tokens are logged. Pydantic `extra=forbid` contracts reject mass assignment.
- `backend/migrations/0013_security_rls.sql` adds tenant/workspace RLS policies for operational tables using transaction-local settings while retaining application predicates.

Verification update: security tests cover missing/invalid/expired identity, role denial, production refusal, and rate limiting; full suite = **62 passed**; Ruff and diff check passed.

Limitations: no external OIDC provider or secrets are configured. RLS policies are not enabled by this migration until API transactions set `app.tenant_id` and `app.workspace_id`; direct database isolation therefore remains a deployment task, not a production claim.

## `jobs-outbox`

**Status:** Implemented as a PostgreSQL-compatible transactional outbox/job reliability slice with a bounded worker.

- `backend/app/jobs_outbox.py` provides atomic domain-write + event + job enqueue semantics, leases, exclusive claims, attempt counts, capped exponential backoff, idempotent handler keys, success/retry/dead states, reclaimable leases, and backlog age visibility.
- PostgreSQL tables receive handler-key uniqueness and backlog indexes in migration `0014_jobs_outbox_reliability.sql`; `backend/app/worker.py --once` processes at most one deterministic SITREP job.
- In-memory parity tests cover rollback, claim exclusivity, lease reclaim, retry/terminal visibility, idempotent handling, and restart-style processing.

Verification update: `pytest backend/tests -q` = **64 passed**; Ruff and diff check passed.

Limitations: the demo worker is intentionally one-shot and the SITREP handler is local deterministic output; production multi-worker orchestration, external delivery, and database-specific concurrency execution require deployment wiring.

## `import-export`

**Status:** Implemented as a bounded CSV/GeoJSON fixture adapter.

- `backend/app/import_export.py` accepts only inline CSV or GeoJSON with explicit schema/mapping versions, provenance, replay time, byte/row/feature/geometry limits, and per-record validation. Invalid originals are quarantined while valid commands remain available as canonical report commands.
- Exports provide scoped redacted CSV with formula-injection protection and deterministic SITREP summaries that exclude future replay data.
- `POST /api/v1/imports/fixture`, `/api/v1/exports/csv`, and `/api/v1/exports/sitrep` enforce evidence scopes; imports do not write private tables directly.

Verification update: `pytest backend/tests -q` = **67 passed**; Ruff and diff check passed.

Limitations: no external integrations, attachment scanning, ZIP ingestion, or large mapping system is included; command application remains the responsibility of the public evidence/operations interfaces.

## `updates-telemetry`

**Status:** Implemented as a bounded, scoped polling update adapter with low-cardinality telemetry.

- `backend/app/updates.py` provides monotonic cursors, bounded pages, reconnect catch-up, tenant/workspace filtering, and a packet-local publish contract. Cursors remain stable when older events are trimmed.
- `GET /api/v1/updates` requires `operations:read`; `POST /api/v1/updates` is a safe demo publisher requiring `operations:write`. `GET /api/v1/metrics` requires `system:read` and exposes bounded request latency, errors, queue/job gauges, recommendation, and sync-conflict counters.
- Request logs contain method, status, and duration only. Event payloads, report bodies, tokens, personal data, and exact locations are not emitted to telemetry.

Verification update: `pytest -q` from `backend` = **71 passed**; focused polling/telemetry tests = **4 passed**.

Limitations: polling is the required path; no broker or WebSocket transport is included. The packet-local feed is process memory and must be replaced with committed outbox/audit reads for multi-process deployment. Queue/job gauges are bounded demo values until stores expose aggregate counts.

## `reliability-recovery`

**Status:** Implemented as a guarded local evidence workflow; no production or cloud claim.

- `scripts/reliability-recovery.ps1` applies migrations, seeds/replays synthetic data, checks readiness and audit integrity, backs up to an explicit repository-local disposable path, restores only to a name matching `ev2_recovery_*`, and compares key counts.
- `docs/reliability-recovery.md` documents clean start, degraded readiness behavior, manual paper/radio fallback, and the rule that unavailable Docker/PostgreSQL tooling is recorded as unverified.

Verification update: script structure and target guards reviewed; live Docker/PostGIS backup/restore execution is **unverified** when the platform is unavailable. No shared or unresolved database target was touched.

## `evaluation-replay`

**Status:** Implemented as a reproducible synthetic evaluation package.

- `backend/app/evaluation_replay.py` creates 121 provenance-labelled records with event-time replay filtering, contradictions, unknown/stale signals, dependency inputs, bounded lifecycle, baseline/ablation metrics, and canonical hashes.
- `scripts/run-evaluation-replay.ps1` emits raw JSON and a concise comparison; future information is excluded before scoring. Results finish through commander approval, task lifecycle, outcome, and audit verification as an explicit synthetic contract.

Verification update: `pytest -q tests/test_evaluation_replay.py` = **2 passed**; replay command executed and produced stable result hash `900ba1d3ce623b8471453bed10953793f391df6e768e843abfcbcb6d09544b89`.

Limitations: metrics are transparent fixture outputs, not measured superiority, accuracy, or operational validation.

### Honest limitations

- Synthetic state is not a measured operational baseline and is not medical or safety validation.
- This packet does not implement runway projections, cascading analysis, what-if simulation, recommendations, offline sync, OIDC, or RLS.
- The repository currently lacks `PROJECT_OVERVIEW.md` and `baby.md`; architecture comparison used the available `docs/SYSTEM_ARCHITECTURE.md` and current code.
