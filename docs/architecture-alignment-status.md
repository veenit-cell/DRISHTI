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

### Honest limitations

- Synthetic state is not a measured operational baseline and is not medical or safety validation.
- This packet does not implement runway projections, cascading analysis, what-if simulation, recommendations, offline sync, OIDC, or RLS.
- The repository currently lacks `PROJECT_OVERVIEW.md` and `baby.md`; architecture comparison used the available `docs/SYSTEM_ARCHITECTURE.md` and current code.
