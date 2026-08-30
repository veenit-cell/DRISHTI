# Phase 6 Handoff — Deployment Handoff and Demo Package

## Start

One-time setup:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
npm.cmd --prefix .\frontend install
```

Start the local stack:

```powershell
.\scripts\dev.ps1
```

This starts PostgreSQL/PostGIS, applies migrations, then starts the API at `http://127.0.0.1:8000` and React at `http://127.0.0.1:5173`.

## Reset/seed command

With the API running:

```powershell
$h = @{ 'X-Dev-Identity' = 'operator' }
Invoke-RestMethod -Method Post -Headers $h http://127.0.0.1:8000/api/v1/decision-loop/demo/replay
```

This resets and replays the fixed synthetic North Sector scenario and clears demo operations state.

## 3–5 minute demo script

1. Open the React shell and identify the synthetic/operator development context.
2. Run the reset command above; explain that this creates a reproducible starting state.
3. Open the decision-loop scenario and show the short water runway, elevated contamination, and expected influx.
4. Generate a recommendation. Point out the rule name, each reason, and the filtered ready water-team resource.
5. Approve it as commander. Show `approved` plus `auto_dispatched: false`; show that the task list is still empty.
6. Open the audit view/API and show replay, recommendation creation, and approval events.
7. Optionally create a response queue item and manually assign it through the existing operations flow to demonstrate the separate human-controlled dispatch boundary.

## Verification evidence

Command:

```powershell
.\scripts\check.ps1
```

Result in the current local environment: Ruff checks passed, **21 backend tests passed**, and the frontend TypeScript/Vite build passed. The documented `dev.ps1` command could not be freshly run because Docker/PostGIS is not installed here.

## Known limitations and security posture

All data is synthetic. Development identities are fixed fixtures and rejected in production configuration. The in-memory decision/audit adapter is for the demo; production requires authenticated identity, durable audit persistence, and live PostgreSQL migration verification. There is no hosting, cloud integration, real scanning, external geocoding, ML, WebSockets, or offline synchronization in this release.
