# Gap-fix tracker

Updated: 30 August 2026

## First three priority gaps

| Gap | Status | Evidence |
|---|---|---|
| Evidence → incident → queue → recommendation → task chain | Partial / demo slice | Approved recommendations now create a linked response queue item; existing explicit queue approval creates the task. |
| Recommendation snapshots and explainability | Improved / demo slice | Recommendations now carry priority, evidence references, input snapshot/hash, expected effect, reasons, and compatibility snapshot. |
| Commander approval linked to tasking | Partial / explicit | Approval accepts an optional compatible `resource_id`, records `queue_item_id`, and never auto-dispatches; task creation remains a separate authorized action. |

Remaining: direct evidence/incident IDs in recommendation inputs, full field outcomes, alternatives/exclusions, expiry enforcement, and operator UI.

## Operational-loop update

Queue items now accept owner, deadline, report/incident source IDs. Completed tasks accept an idempotent outcome; the PostgreSQL adapter records it on the linked recommendation and emits an audit event. Remaining: source-ID validation against the evidence store, field task UX, and richer outcomes.

## First-half pass (architecture commitments 1–9)

Recommendation expiry is now enforced in both adapters (four-hour synthetic horizon). The first half remains demo-complete but not production-complete: aggregate revisions, cross-module atomic replay reset, full evidence references, spatial coverage, capacity modeling, alternatives/exclusions, and field outcomes remain open.

## Second-half pass started

- Request bodies are bounded to 1 MB with a structured `413` response.
- Request completion emits structured logger fields for method, path, and duration.
- Existing health/readiness and job/polling surfaces remain the local observability baseline.

Still open: real authentication/RLS, worker execution/retries, WebSockets, backup/restore drills, vulnerability/SBOM evidence, and production deployment proof.

## Next three gaps

| Gap | Status | Evidence |
|---|---|---|
| Operator decision workspace | Demo slice | React now loads resources, queue, tasks, evaluates a recommendation, and exposes commander approve/reject. |
| Minimal field/offline shell | Shell only | Service worker caches the app shell; no IndexedDB/outbox or sync conflict protocol yet. |
| Verification workflow linkage | Partial | Verification queue endpoint exists; recommendation approvals create response queue items for explicit task issuance. |

## Following three gaps

| Gap | Status | Evidence |
|---|---|---|
| Geospatial feasibility | Improved / demo slice | Task approval rejects a latest non-passable route observation. |
| Concurrency/recovery proof | Regression covered | No-double-booking remains enforced and the focused route test passes; recovery drill remains open. |
| Authorization hardening | Regression covered | Scoped write/read dependencies and invalid-input tests remain green. |

## Latest three gaps

| Gap | Status | Evidence |
|---|---|---|
| Audit integrity | Improved / demo slice | PostgreSQL audit rows now carry chained `previous_hash` and `event_hash` values. |
| Async job visibility | Partial | Scoped `GET /jobs` exposes queued/leased/failed state; workers and leasing remain deferred. |
| Realtime fallback | Demo slice | Decision audit supports bounded `after` polling with `next_after`; WebSockets remain deferred. |
