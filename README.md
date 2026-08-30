# D.R.I.S.H.T.I - Disaster Response Intelligence System for Human Triage Intelligence

Phase 1 provides a deliberately thin foundation for the district disaster evidence and resource decision-support demo. It includes a FastAPI boundary, a React shell, executable API contracts, a development-only identity fixture, and a PostgreSQL/PostGIS foundation migration. It does not implement reports, resources, recommendations, or tasking.

## Prerequisites

- Python 3.12 or 3.13
- Node.js 22 or newer
- Docker with Compose (for PostgreSQL/PostGIS)

No secret-bearing file is required for the development profile.

## One-time setup

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
npm.cmd --prefix .\frontend install
```

## Start the local stack

```powershell
.\scripts\dev.ps1
```

The script starts the local PostGIS container, applies the foundation migration, then runs the API at `http://127.0.0.1:8000` and the frontend at `http://127.0.0.1:5173`. Press Ctrl+C to stop the application processes. The database container remains available for faster restarts.

Health and version endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/version`

The protected development context probe accepts `X-Dev-Identity: operator` only when the typed configuration enables the non-production fixture:

```powershell
Invoke-RestMethod -Headers @{ 'X-Dev-Identity' = 'operator' } http://127.0.0.1:8000/api/v1/dev/context
```

## Validate

```powershell
.\scripts\check.ps1
```

This runs backend formatting/lint checks, backend tests (including contract validation), and the frontend TypeScript production build.

## Hackathon demo runbook

Start the local stack with `.\scripts\dev.ps1`. In a second PowerShell window, reset the fixed synthetic scenario:

```powershell
$h = @{ 'X-Dev-Identity' = 'operator' }
Invoke-RestMethod -Method Post -Headers $h http://127.0.0.1:8000/api/v1/decision-loop/demo/replay
```

Then open `http://127.0.0.1:5173` and use the evidence workbench. The 3–5 minute judge flow is documented in [docs/handoffs/phase-6/manifest.md](docs/handoffs/phase-6/manifest.md).

## Architecture boundary

- PostgreSQL/PostGIS is the intended operational source of truth.
- Development identity is deterministic, deny-by-default, and rejected in production configuration.
- Correlation IDs and errors use one shared boundary implementation.
- Event time remains distinct from server-recorded time.
- The initial migration creates only organization/workspace metadata and the audit, outbox, idempotency, and job primitives required by later phases.
- Object storage, real OIDC, and all disaster-domain workflows remain later checkpoints.
