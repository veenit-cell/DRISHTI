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

### Honest limitations

- Synthetic state is not a measured operational baseline and is not medical or safety validation.
- This packet does not implement runway projections, cascading analysis, what-if simulation, recommendations, offline sync, OIDC, or RLS.
- The repository currently lacks `PROJECT_OVERVIEW.md` and `baby.md`; architecture comparison used the available `docs/SYSTEM_ARCHITECTURE.md` and current code.
