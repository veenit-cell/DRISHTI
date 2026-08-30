# Reliability/recovery handoff

Implemented `scripts/reliability-recovery.ps1` and `docs/reliability-recovery.md`.

The script is guarded to repository-local `artifacts\recovery` backups and restore database names matching `ev2_recovery_*`. It applies migrations, starts the API, seeds/replays synthetic data, verifies health/audit integrity, backs up, restores, and compares report/audit counts.

Verification:

- PowerShell parse check: passed.
- Exact recovery command: **passed** with Docker available: 718 audit events and 46 raw reports restored; audit hash `8a80ebdfac5ad66472b1569ac89e7fd7` matched; elapsed 6.61 seconds. Restore target was `ev2_recovery_demo`.
- Existing backend suite remains the applicable regression check; no application code changed.

Known limitation: this is local evidence only; production backup monitoring, failover, and concurrency/load evidence remain deployment gates.
