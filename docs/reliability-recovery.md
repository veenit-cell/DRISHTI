# Local reliability and recovery evidence

This is a disposable local demonstration, not a cloud or production recovery claim.

## Exact command

From the repository root (PowerShell):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\reliability-recovery.ps1
```

The script applies all forward migrations, seeds and replays the fixed synthetic scenario, verifies readiness and audit integrity, writes a custom-format backup to `artifacts/recovery/ev2-seeded.dump`, restores only to the guarded `ev2_recovery_demo` database, and compares audit/report counts. It never drops `ev2`.

The normal app command remains:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Degraded database behavior is observable at `GET /api/v1/health/ready`: it returns `503` with `DEPENDENCY_UNAVAILABLE` when PostgreSQL cannot be reached. Stop only the local Compose database to demonstrate this, then restart it; do not point the script at a shared database.

Paper/radio fallback: print the assigned task packet from the operator workspace, record task ID, time, resource, route, and acknowledgement on paper/radio, then enter the command through `/api/v1/offline-sync` when an authenticated connection returns. Server reconciliation remains authoritative.

## Evidence status

The recovery script is automated and safe-target guarded. Docker/PostGIS execution, backup bytes, restore counts/hashes, and timings must be recorded from the operator's machine; if Docker or `pg_dump`/`pg_restore` is unavailable, report that run as **unverified**, never simulated. The in-memory demo adapter's audit endpoint may report its documented adapter limitation.
