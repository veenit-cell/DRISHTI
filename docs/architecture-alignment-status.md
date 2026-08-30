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

### Honest limitations

- Synthetic state is not a measured operational baseline and is not medical or safety validation.
- This packet does not implement runway projections, cascading analysis, what-if simulation, recommendations, offline sync, OIDC, or RLS.
- The repository currently lacks `PROJECT_OVERVIEW.md` and `baby.md`; architecture comparison used the available `docs/SYSTEM_ARCHITECTURE.md` and current code.
