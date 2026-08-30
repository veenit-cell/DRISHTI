# Final architecture acceptance gate

Date: 2026-08-30. This report evaluates the prototype against `docs/SYSTEM_ARCHITECTURE.md` Definition of Done. Synthetic evidence is not real-world validation.

## Evidence commands

| Command | Result |
|---|---|
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1` | Pass: Ruff checks, 73 backend tests, TypeScript check and Vite production build. Ruff format reports existing files that would be reformatted but exits successfully; this is recorded as Partial formatting hygiene. |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-evaluation-replay.ps1` (twice) | Pass: 120 visible / 121 total, 1 future record excluded; identical result hash `1bccaf48fc3b74d40419a6c8aff3fcbd64f015e5c9be42d296fd1ae2f735af25`. |
| `pytest -q tests/test_evaluation_replay.py` | Pass: 2 tests; deterministic replay, future filtering, required signals, lifecycle. |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\reliability-recovery.ps1` | Pass: 718 audit events and 46 raw reports backed up/restored; audit hash `8a80ebdfac5ad66472b1569ac89e7fd7` matched; elapsed 6.61s. |

Raw replay evidence is in `artifacts/evaluation-replay/results.json`; comparison is in `artifacts/evaluation-replay/comparison.md`.

## Prototype Definition of Done

| Criterion | Gate | Direct evidence |
|---|---|---|
| Labeled replay completes evidence-to-outcome loop | Pass | `backend/tests/test_validation_hardening.py`; `evaluation_replay.py` lifecycle; 73 tests pass |
| Originals/provenance, contradiction review, unknown sector, both queues | Partial | `evidence.py`, `decision_snapshot.py`, `operations.py`; synthetic replay labels these, but no single automated test asserts every view together |
| Stale route/resource, explanations, commander decision, outcome, audit | Pass | `tests/test_validation_hardening.py`, operations/decision tests, replay lifecycle |
| Allocation invariants and fallback | Pass | `tests/test_operations.py`, `tests/test_decision_policy.py` |
| Future information inaccessible | Pass | `tests/test_decision_snapshot.py`, `tests/test_evaluation_replay.py` |
| Role/tenant scope and idempotency | Pass | `tests/test_security_boundary.py`, evidence/operations tests |
| Offline restart/sync and critical tests | Pass | `tests/test_offline_sync.py`; frontend offline adapter; full suite |
| Team-readable non-goals/provenance/limitations | Pass | README, handoffs, status ledger |

Prototype assessment: **90%**. The remaining 10% is integration-test breadth, not an unimplemented core mechanism.

## MVP Definition of Done

| Criterion | Gate | Direct evidence |
|---|---|---|
| Prototype criteria | Partial | See gate above |
| 50–200 records, bounded media, PostGIS baseline, exports | Partial | 121-record replay; bounded CSV/GeoJSON adapters; PostGIS migrations. No media scanning. |
| Health metrics, backup/restore, reproducible deployment | Partial | `/health/ready`, `/metrics`, guarded recovery script; local backup/restore passes, deployment remains local-only |
| Baseline and ablation with raw results | Pass | `artifacts/evaluation-replay/results.json` and `comparison.md` |
| No autonomous action, hidden original, cross-tenant access, invariant violation known open | Pass | authorization, decision, offline, and operations tests; explicit `auto_dispatched: false` contract |
| Required algorithm/API/integration sign-offs | Missing | No external Person 1/2/3 sign-off artifacts exist |

MVP assessment: **72%**. This is a strong synthetic hackathon MVP, not a signed district pilot.

## Final district system Definition of Done

| Criterion | Gate | Evidence / reason |
|---|---|---|
| Partner-approved roles, policy, taxonomy, retention, fallback, automation | Externally blocked | Requires partner and legal decisions |
| Controlled tabletop/shadow drill | Externally blocked | No partner-approved drill has occurred |
| Production MFA, monitored backups, SBOM/patching, incident response | Missing | Deliberately outside prototype scope |
| Partner-approved capacity thresholds and model promotion | Externally blocked | No approved workload/validation baseline |
| Accepted residual risk, legal status, support ownership, rollback | Missing | Requires organizational governance |

Final district system assessment: **22%**. This low percentage is intentional: those gates cannot honestly be simulated in a local hackathon repository.

## Complete demo command sequence

```powershell
.\scripts\dev.ps1
# second shell
Invoke-RestMethod -Method Post -Headers @{'X-Dev-Identity'='operator';'Idempotency-Key'='demo-replay-001'} http://127.0.0.1:8000/api/v1/decision-loop/demo/replay
.\scripts\run-evaluation-replay.ps1
.\scripts\check.ps1
```

For recovery evidence, run `.scriptseliability-recovery.ps1` only with the local Compose/PostGIS engine available. Never point it at a shared database.

## Honest limitations

Polling is process-local rather than a durable outbox reader; RLS and external OIDC are deployment seams; some frontend intelligence uses labeled fixtures; PostgreSQL concurrency under production load remains unverified. No cloud, production, clinical, partner, or operational-accuracy claim is made.

Self-debug audit: performed (reviewed Definition of Done, commands, status ledger, replay hashes, and format output; no small reproduced product defect found). Additional user inputs: 0. Token consumption: unavailable from runtime.
