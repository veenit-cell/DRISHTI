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

### Honest limitations

- Synthetic state is not a measured operational baseline and is not medical or safety validation.
- This packet does not implement runway projections, cascading analysis, what-if simulation, recommendations, offline sync, OIDC, or RLS.
- The repository currently lacks `PROJECT_OVERVIEW.md` and `baby.md`; architecture comparison used the available `docs/SYSTEM_ARCHITECTURE.md` and current code.
