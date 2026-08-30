# Phase 5 Handoff — Validation Hardening

Added only high-value validation around the existing demo path:

- complete replay → recommendation → commander approval flow;
- audit visibility for replay, recommendation creation, and approval;
- viewer authorization denial for write operations;
- invalid decision/status input checks;
- regression coverage that approval never creates or dispatches a task.

## Exact validation

Command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Result: Ruff format/check passed, **21 backend tests passed**, and the frontend TypeScript/Vite build passed.

Docker/PostGIS remains unavailable, so live database execution is not claimed. Development identities are fixed fixtures, audit visibility is an in-memory demo adapter, and no product scope was expanded. Production must replace the fixture identity and persist audit records in the database before deployment.
