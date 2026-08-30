# Architecture and Implementation Gap Analysis

**Updated:** 30 August 2026  
**Method:** static review of current code/migrations/routes/tests, recent commits through `0560695`, phase handoffs, and the current gap-fix tracker. The full backend suite last passed locally: **29 tests**.

## Bottom line

The project is now a credible, durable **synthetic demo** of a human-supervised evidence-to-action loop:

```text
immutable report → review/link → response or verification queue
→ feasible recommendation → commander approval → explicit task approval → audit
```

It is not yet the full district operational platform described by the architecture. The remaining work is concentrated in completeness, recovery, real identity/security, field/offline workflows, workers, and deployability—not basic endpoint absence.

## Current architecture gaps

| Commitment | Current evidence | Status | Remaining gap |
|---|---|---|---|
| PostgreSQL/PostGIS authoritative state | PostgreSQL adapters are runtime defaults; evidence and operations integration tests run locally. | Partial | Replay resets operations and scenario state across module transactions; no restart/recovery drill. |
| Scoped/idempotent writes | Operations/decision writes use scoped idempotency and audit correlation. | Partial | Report idempotency differs; aggregate revision/optimistic concurrency is absent. |
| Reviewable evidence | Immutable raw payload/hash, claim review states, incident links, duplicate candidates, sectors, and attachment metadata exist. | Partial | No object storage, scanning/quarantine, bulk import safety, or rich conflict-resolution UI. |
| Unknown/stale/conflict state | Claims support `unknown`, `contradicted`, `stale`, and `superseded`; readiness/route expiry exists. | Partial | Staleness is not systematically propagated into queue/recommendation priority. |
| Geospatial state | PostGIS-backed sectors, incident/report map filtering, and route observations exist. | Partial | No spatial coverage/assessment calculation, spatial joins, or route network model. |
| Two queues | Scoped response and verification queue APIs exist; queue items accept owner, deadline, report/incident source metadata. | Partial | Source IDs are not yet validated against evidence and verification completion lifecycle is absent. |
| Feasible resource allocation | Capability, readiness expiry, route passability, and database active-task reservation are enforced. | Partial | No capacity/quantity model, multi-client concurrency drill, or allocation alternatives. |
| Explainable recommendations | Priority, reasons, compatible resources, synthetic evidence reference, input snapshot/hash, expected effect, expiry, and queue linkage exist. | Partial | One hard-coded rule; no real evidence IDs, policy/versioned scoring, alternatives, or recomputation policy. |
| Commander-to-task authority | Approval/reject is durable; approval creates a linked queue item; a separate explicit queue approval creates the task; completed tasks record an outcome on linked recommendations. | Partial | No modify/override path or field task UX/richer outcome model. |
| Field/offline workflow | React decision workspace and service-worker shell cache exist. | Partial | No task packet, IndexedDB outbox, sync/conflict UX, or degraded paper/radio workflow. |
| Realtime | Scoped audit polling supports `after`/`next_after`. | Partial | No WebSocket transport, reconnect behavior, or client polling loop. |
| Jobs/outbox | Job schema and scoped job-status endpoint exist. | Partial | No worker leasing, dispatcher, retries, publishing, or failure recovery. |
| Audit integrity | Audit writes include correlation data and PostgreSQL hash-chain fields. | Partial | No append-only database enforcement, chain verifier, before/after payload references, or export/policy audit. |
| Identity and tenancy | Development fixtures, scopes, tenant/workspace query scoping, and write-denial tests exist. | Partial | No OIDC, production RBAC, RLS, jurisdiction/task/privacy policy, MFA, or session lifecycle. |
| Input safety | Pydantic bounds, geometry validation, and 1 MB body guard exist. | Partial | No rate limiting, streaming/body enforcement beyond declared length, attachment quarantine, or safe import pipeline. |
| Observability | Health/readiness, correlation IDs, request completion logs, audit, and job visibility exist. | Partial | No metrics, traces, dashboards, alerts, dependency matrix, SLOs, or runbooks. |
| Resilience | Database readiness is checked and idempotent command paths exist. | Missing | No backup/restore test, degraded-mode contract, replay recovery proof, or offline manual implementation. |
| Deployment/release | Local Compose/dev commands, migration path, demo/reset instructions, and limitations exist. | Partial | No app/worker images, object storage, TLS boundary, clean-clone proof, rollback/restore, checksums/SBOM, or independent takeover verification. |

## Phase-gate status

| Phase | Current outcome | Remaining gate gap |
|---|---|---|
| 1 — Foundations | FastAPI/React, contracts, PostgreSQL migrations, development identity, health, idempotency, audit/outbox/job tables. | RLS, aggregate revision, clean-clone/runtime recovery proof. |
| 2 — Evidence/geospatial | Immutable reports, reviewable claims, incident links, duplicate candidates, sectors, bounded PostGIS map reads, live evidence integration test. | Attachment bytes/scanning, import quarantine, geocoding, coverage and richer review UX. |
| 3 — Operations | Resources with capability/readiness expiry, response + verification queues, routes, no-double-booking, task lifecycle, queue provenance, and recorded task outcome. | Capacity, source-ID validation, multi-client race drill, and field task UX. |
| 4 — Decision loop | Deterministic replay, explainable/expiring recommendation snapshot, compatible resource filtering, approval→queue linkage, no auto-dispatch. | More rules, real evidence references, alternatives, policy versioning, outcomes, realtime/offline integration. |
| 5 — Validation | Demo-path, authorization/input, route/no-double-booking, PostgreSQL integration, audit visibility tests. | Threat model, performance, recovery/failure, UX research, raw benchmark evidence. |
| 6 — Handoff | Local start/reset/demo documentation and limitations exist. | Handoffs are stale (report 21 tests and old in-memory limitations); no clean-environment, backup/restore, rollback, or independent verification. |

## Documentation corrections still needed

- Phase 5 and Phase 6 manifests must be revised to the current **29-test**, PostgreSQL-backed state and current decision/task linkage.
- The README is stronger than the old implementation, but its “full loop” wording must stay qualified as synthetic/demo-only until field outcomes, production identity, and recovery proof exist.
- The tracker at `docs/architecture-implementation-gap-fix-tracker.md` is the incremental work log; this document is the current architecture baseline.

## Recommended next order

1. Finish the operational loop: queue provenance/ownership/deadline, field task packet/outcome, and outcome-to-recommendation audit linkage.
2. Make the demo reliable: transactional replay boundary, actual job worker/retry or explicitly remove job claims, and backup/restore/degraded-mode tests.
3. Make it safe to extend: OIDC/RBAC/RLS design and implementation, rate limits/import controls, audit-chain verifier, and metrics/traces.
4. Make handoff claims reproducible: clean-run verification, updated Phase 5/6 manifests, release checksums/SBOM, and independently repeatable demo instructions.

## Scope boundary

Do not add ML, live external geocoding, Kafka, Kubernetes, or cloud hosting to close these gaps. The immediate goal remains a small, durable, human-supervised district decision loop with honest operational limits.
