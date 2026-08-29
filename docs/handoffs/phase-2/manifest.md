# Phase 2 Handoff — Durable Evidence and Geospatial Demo Path

Status: hackathon-minimum checkpoint complete. Base revision: `bb0ca9c` (Phase 1). Final revision: this manifest's containing Git commit.

## What works

- `POST /api/v1/reports` accepts a scoped structured report with an `Idempotency-Key` matching `client_record_id`.
- The PostgreSQL implementation stores the original JSON payload, SHA-256 hash, source metadata, observed/received/recorded timestamps, location metadata, and revision. No public update path exists.
- Reusing the same client record and identical payload returns the original report; reusing it with a different payload returns `409 IDEMPOTENCY_CONFLICT`.
- Deterministic normalization creates a versioned run and derived claims. Missing location/time/fact values remain `null` and produce explicit warnings; they are never coerced to zero or `(0,0)`.
- `GET /api/v1/reports` provides tenant/workspace-scoped summaries with an opaque bounded cursor. `GET /api/v1/reports/{id}` returns the preserved original, hash, normalization lineage, and claims.
- `POST /api/v1/demo/seed` seeds three clearly labeled synthetic incidents. `GET /api/v1/map/features` returns bounded `FeatureCollection` GeoJSON with optional WGS84 `bbox` filtering and report/incident properties.
- Report creation in PostgreSQL writes the normalization record, claims, audit event, and outbox event in the same transaction.
- The React shell now includes a small evidence workbench for synthetic report creation, incident seeding, report listing, and read-only original/hash inspection.

## Repository changes

- `backend/app/evidence.py`: report contracts, deterministic normalization, in-memory test adapter, and PostgreSQL evidence store.
- `backend/app/api/routes.py`: report, demo seed, and bounded map endpoints.
- `backend/app/main.py`: injected clock/store wiring.
- `backend/app/core/context.py` and `contracts/v1/roles-and-scopes.md`: backward-compatible evidence/map scopes.
- `backend/migrations/0002_evidence.sql`: raw reports, normalization runs, claims, report locations, synthetic incidents, and indexes.
- `contracts/v1/report.schema.json`, `geojson.schema.json`, and synthetic examples.
- `backend/tests/test_evidence.py` and expanded contract validation.
- `frontend/src/api.ts`, `App.tsx`, and `styles.css`: evidence workbench.

## API index

| Method | Path | Scope | Purpose |
|---|---|---|---|
| POST | `/api/v1/reports` | `evidence:write` | Idempotent immutable report intake |
| GET | `/api/v1/reports` | `evidence:read` | Scoped report summaries and cursor |
| GET | `/api/v1/reports/{id}` | `evidence:read` | Original payload, hash, claims, lineage |
| POST | `/api/v1/demo/seed` | `evidence:write` | Seed synthetic incident/location fixtures |
| GET | `/api/v1/map/features` | `map:read` | Bounded report/incident GeoJSON |

## Migration and contracts

- Apply migrations in lexical order through `backend.app.persistence.apply_foundation_migration`; Phase 2 adds `0002_evidence.sql` after Phase 1's `0001_foundation.sql`.
- Contract additions are under `contracts/v1/`; Phase 1 event/problem/config contracts remain unchanged.
- Event time, server recorded time, opaque IDs, unknown/null semantics, tenant/workspace scope, and development identity rules are preserved.

## Validation evidence

Command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Observed result on the named local environment (Windows, Python 3.13.7, Node 24.14.0, npm 11.9.0):

- Ruff format/check: passed; 15 files formatted.
- Phase 1 + Phase 2 backend tests: **17 passed in 0.76 seconds**.
- Frontend TypeScript/Vite build: passed; 30 modules transformed in 0.748 seconds.
- Report path tests prove immutable hash preservation, same-payload retry, conflicting reuse `409`, unknown warnings, scoped reads, cursor paging, malformed location rejection, synthetic seed idempotency, bounded GeoJSON, and invalid bbox rejection.
- Contract tests validate report examples and all Phase 1/2 JSON Schemas with date-time format checking.
- Frontend workbench builds against the real API field shapes.

## Security and data posture

- All report/list/detail/map operations require server-side development-fixture scopes; SQL reads are tenant/workspace constrained.
- Original payloads are returned only from the scoped detail endpoint and are not exposed in map features.
- Geometry is restricted to bounded WGS84 Point input for this demo; map output is capped at 100 features.
- Fixtures are synthetic and contain no credentials or real victim data.

## Deliberate limitations

- Docker is unavailable in the validation environment, so the real PostGIS container, `0002` migration execution, and PostgreSQL-backed API path were not run here. The SQL repository and migration are implemented and covered structurally; the in-memory adapter provides deterministic behavior tests.
- Attachments, scanning/promotion, CSV/GeoJSON bulk import, external geocoding, claim review mutations, duplicate/contradiction relation review, and full incident lifecycle are deferred because they are outside the requested demo slice.
- No resources, tasking, recommendations, offline sync, realtime, replay, or performance-hardening behavior was added.
- The in-memory store is test-only; the application factory uses the PostgreSQL store by default.
- The development identity remains non-production and uses the fixed Phase 1 fixture.

## Next smallest checkpoint

Phase 3 should consume the incident/map read contracts to add readiness, routes, separate response/verification queues, and explicit human-approved tasking without changing raw report ownership or normalization semantics.

`docs/baby (1).md` was not changed; the workflow remains unchanged.
