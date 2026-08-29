# Phase 1 Handoff

Status: hackathon-minimum checkpoint complete. Revision: this manifest's containing Git commit.

## What works

- FastAPI application factory and `/api/v1` boundary.
- Liveness, database-aware readiness, and version endpoints.
- One stable `application/problem+json` model and bounded correlation-ID middleware.
- Deterministic development-only `operator` and `viewer` identities with server-side scope denial; production configuration rejects the fixture.
- Injected system/fixed clock primitives and explicit event-time versus recorded-time contract.
- PostgreSQL/PostGIS Compose profile and forward-only foundation migration for organization/workspace metadata, policy/baseline versions, audit, outbox, idempotency, and jobs.
- React/TypeScript shell that reads live API version/health instead of displaying fabricated domain state.
- Executable event, problem, and non-secret configuration schemas with valid/invalid event examples.

No report intake, evidence review, resource state, recommendation, dispatch, or other domain behavior was added.

## Repository map

- `backend/app/`: FastAPI edge, typed configuration, request context, clock, problems, and database readiness/migration entry point.
- `backend/migrations/`: forward-only PostGIS foundation schema.
- `backend/tests/`: API boundary, fixed-clock, production-fixture, and JSON Schema behavior tests.
- `contracts/v1/`: glossary, roles/scopes, schemas, and examples.
- `frontend/`: minimal React/Vite system-boundary shell.
- `infra/compose.yaml`: loopback-only, credential-free local development PostGIS profile.
- `scripts/`: one start command and one validation command.

## Setup and run

Prerequisites: Python 3.12/3.13, Node.js 22+, and Docker Compose.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
npm.cmd --prefix .\frontend install
.\scripts\dev.ps1
```

The start script launches PostGIS, applies `0001_foundation.sql`, and runs the API and frontend. It contains no secret-bearing defaults.

## Test commands and results

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Result on Windows with Python 3.13.7, Node 24.14.0, and npm 11.9.0:

- Ruff format: 13 files already formatted.
- Ruff lint: all checks passed.
- Pytest: 10 passed in 0.67 seconds.
- TypeScript/Vite production build: passed; 30 modules transformed in 0.768 seconds.
- API process smoke: liveness, version, and protected development context returned expected data; process stopped cleanly.
- Frontend process smoke: HTTP 200 and expected page title; process stopped cleanly.
- Python package integrity: `pip check` found no broken requirements.
- Frontend dependency audit: 0 known vulnerabilities reported by npm.

## Contracts and schema

- API base: `/api/v1`.
- Event envelope: version 1, at-least-once, positive aggregate revision, distinct `occurred_at` and `recorded_at`.
- Problem response: stable code/status/detail/correlation/retryability/violations shape.
- Configuration: typed and startup-validated; development identity cannot be enabled in production.
- Database migration: `0001_foundation.sql`; forward-only policy for this prototype.

## Known limitations

- Docker is not installed in the validation environment. The Compose definition, PostGIS health contract, migration SQL, readiness failure behavior, and migration entry point were inspected/tested where possible, but the real PostGIS container and migration were not executed here.
- The complete `scripts/dev.ps1` orchestration was therefore not run end to end; backend and frontend processes were started and smoke-tested separately.
- S3-compatible object storage, real OIDC, database-enforced tenant isolation/RLS, transactional service methods, runtime idempotency behavior, job leasing behavior, and clean-clone verification are deferred. Phase 1 includes only the schema/contract foundations needed for those paths.
- The development database uses loopback-only trust authentication. It is explicitly a local profile and must not be exposed or described as production configuration.
- No backend vulnerability advisory scanner was added; `pip check` verifies dependency consistency, not advisory status.

## Next smallest checkpoint

Phase 2 should consume these contracts to add one immutable synthetic report intake/read path with explicit provenance and bounded map-ready coordinates. It must preserve the development identity boundary and avoid adding real external integrations.

## Architecture/product review

- Modular-monolith and PostgreSQL/PostGIS ownership are preserved.
- The UI exposes system status only and does not imply disaster intelligence that does not yet exist.
- Human approval and shelter/disaster decision behavior remain untouched because they are outside this checkpoint.
- `docs/baby (1).md` was not changed because the workflow did not change.
