# Reliability/recovery handoff

Implemented `scripts/reliability-recovery.ps1` and `docs/reliability-recovery.md`.

The script is guarded to repository-local `artifacts\recovery` backups and restore database names matching `ev2_recovery_*`. It applies migrations, starts the API, seeds/replays synthetic data, verifies health/audit integrity, backs up, restores, and compares report/audit counts.

Verification:

- PowerShell parse check: passed.
- Exact recovery command: executed, **unverified/blocked** because Docker could not connect to its local engine in this environment (`permission denied ... docker_engine`). No restore cleanup or shared database operation occurred.
- Existing backend suite remains the applicable regression check; no application code changed.

Known limitation: live backup bytes, restore counts/hashes, and timings require a local Docker/PostGIS engine and must be recorded from that machine, never simulated.
