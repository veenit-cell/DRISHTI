# Architecture Alignment Execution Prompts

## Purpose

These prompts close the verified gap between the current product and `docs/SYSTEM_ARCHITECTURE.md`. They prioritize the promised evidence-to-outcome decision loop over generic CRUD or production theater.

The target demonstrable mechanism is:

```text
Evidence
→ coupled shelter state
→ time-to-critical projections
→ cascading-risk explanation
→ intervention comparison
→ feasible ranked recommendation
→ explicit commander approval
→ task and observed outcome
```

## How to use this file

- Run one prompt per fresh agent turn.
- Prompts are independently startable. They must inspect current HEAD and must not assume another prompt ran first.
- Every packet owns a narrow module and tests it with local fixtures or a typed adapter. Missing adjacent modules are not permission to implement them.
- Recommended order is product value order, not a dependency chain.
- Do not read `.env`, credentials, tokens, keys, or secret-bearing configuration.
- Preserve unrelated worktree changes. Never restore or overwrite deleted user files without permission.
- Use synthetic data and label it. Preserve unknown values as unknown.
- No recommendation may automatically create an active dispatch.
- Update or create `docs/architecture-alignment-status.md` with evidence after each packet. Never mark a packet complete from code inspection alone.

## Common completion contract

Every prompt below must enforce this contract:

1. Read `PROJECT_OVERVIEW.md`, `docs/SYSTEM_ARCHITECTURE.md`, `baby.md`, the current status ledger if present, and only the relevant implementation files.
2. Before editing, report in at most five bullets: current evidence, exact files expected to change, and blockers.
3. Implement the smallest real vertical slice. Do not redesign the modular monolith or add speculative infrastructure.
4. Add unit tests and at least one API/integration test for the packet's observable behavior.
5. Test unknown, stale, unauthorized, invalid, and idempotent behavior where applicable.
6. Run:

   ```powershell
   .\.venv\Scripts\python.exe -m ruff check backend/app backend/tests
   .\.venv\Scripts\python.exe -m pytest backend/tests -q
   npm --prefix frontend run build
   git diff --check
   ```

7. If a database migration is added, run `.\.venv\Scripts\python.exe -m app.persistence` and a PostgreSQL-backed regression test.
8. Inspect the final diff. Fix only reproduced failures. Record exact commands/results and remaining limitations in the status ledger.
9. Commit only packet files with a focused message. Do not stage unrelated modifications or deletions.
10. Stop at the packet checkpoint. Do not begin another prompt.

---

## Prompt 01 — Coupled shelter-state contract

```text
$EV2 Implement the coupled shelter-state contract described in docs/SYSTEM_ARCHITECTURE.md.

This packet is independently startable. Inspect current migrations and APIs first. Create a narrow shelter-state module with its own fixtures; do not implement forecasting, recommendations, simulation, offline sync, or UI redesign.

Represent one shelter and time-stamped observations for: population/capacity/influx, potable and unsafe water, consumption and treatment capacity, battery/power consumption, medicine/cold-chain/diagnostic constraints, replenishment, and operational thresholds. Use nullable values plus explicit freshness/source/provenance fields. Never coerce missing data to zero, safe, or passable.

Persist observations and a reproducible current snapshot in PostgreSQL. Expose scoped create/read APIs and seed one clearly labeled synthetic shelter. Keep raw observations immutable. Add tenant/workspace scoping and idempotency.

Self-verification: prove snapshot reproducibility, immutable observations, unknown preservation, stale-state labeling, cross-scope rejection, invalid-unit rejection, and PostgreSQL durability. Update docs/architecture-alignment-status.md under `shelter-state`. Follow the common completion contract and commit.
```

## Prompt 02 — Deterministic runway projections

```text
$EV2 Implement deterministic resource-runway projections as a pure intelligence module.

This packet is independently startable. Define a typed input adapter and test fixtures so it does not require Prompt 01. If a compatible shelter snapshot already exists, adapt to it without changing that module's ownership.

Calculate time to critical state for potable water, battery/power, medicine, and cold-chain reserve using quantities, consumption, replenishment, thresholds, and population change. Return unknown when required inputs are unknown or invalid. Include input timestamp, freshness, formula version, units, confidence category, and major contributors. Avoid false precision and clinical claims.

Expose one bounded API that evaluates an explicit snapshot without mutating operational state. Keep formulas deterministic and documented beside the code.

Self-verification: cover depletion, net replenishment, threshold already crossed, zero/negative invalid rates, population influx, stale inputs, unknown propagation, deterministic replay, and formula-version output. Update the status ledger under `runway-projection`. Follow the common completion contract and commit.
```

## Prompt 03 — Cascading-failure explanation engine

```text
$EV2 Implement a small deterministic cascading-failure engine for the PS4 thesis.

This packet is independently startable. Consume a typed state/projection interface with local fixtures; do not require database state or Prompt 02. Do not add ML.

Model only the demonstrable dependency paths: power → water purification → safe-water runway; power → medicine cold chain; unsafe water + population pressure → operational disease-risk pressure; rising medical demand → medicine/diagnostic pressure. Rules must be versioned, acyclic per evaluation, bounded in depth, and explainable.

Return affected capability, severity, estimated time window when known, ordered causal path, supporting input references, unknown contributors, confidence category, and rule version. Unknown inputs must reduce confidence or produce an explicit verification need, never silently become safe.

Self-verification: test each dependency path, multiple simultaneous paths, cycles in malformed configuration, bounded execution, unknown inputs, stale inputs, deterministic output ordering, and no clinical diagnosis language. Update the status ledger under `cascade-engine`. Follow the common completion contract and commit.
```

## Prompt 04 — Non-mutating what-if comparison

```text
$EV2 Implement a non-mutating what-if intervention comparison module.

This packet is independently startable. Use explicit snapshot and projection interfaces with packet-local fixtures. Do not depend on live shelter tables, and do not alter operational state.

Support four bounded synthetic interventions: add potable water, enable/disable purification with its power cost, shift non-critical power load, and change expected population influx. Compare baseline, do-nothing, and intervention results. Return changed inputs, projected critical times, trade-offs, uncertainty, and a stable scenario/input hash.

Expose an evaluation-only API. It must reject unsupported fields, excessive horizons, invalid units, and attempts to mutate IDs, provenance, or live timestamps.

Self-verification: prove the source snapshot is byte-for-byte unchanged, identical inputs give identical hashes/results, interventions show both benefits and costs, unknowns stay unknown, horizons are bounded, and invalid intervention combinations fail clearly. Update the status ledger under `what-if`. Follow the common completion contract and commit.
```

## Prompt 05 — Ranked explainable intervention policy

```text
$EV2 Replace the single hardcoded recommendation path with a small versioned, deterministic intervention policy.

This packet is independently startable. Use typed snapshot, projection, cascade, and resource adapters with local fixtures. Integrate existing compatible modules only through their public contracts. Do not implement those modules here and do not add ML or a complex solver.

Generate and rank at least three candidate actions for the fixed demo: deliver/treat water, shift non-critical power, and request medicine/cold-chain support. Each option must include action, evidence references, reasons, resource cost, expected benefit, time sensitivity, confidence, expiry, policy version, input hash, excluded resources with reasons, and expected operational effect. Apply hard readiness, capability, route, expiry, and no-double-booking constraints. Provide a deterministic greedy fallback with a strict candidate/time bound.

Recommendations remain pending until an authorized commander approves or rejects them. Approval may create a queue item but must never create an assigned task or auto-dispatch.

Self-verification: test ranking determinism, hard-constraint exclusions, expired inputs, all-resources-infeasible behavior, greedy fallback, explicit approval/rejection, no auto-dispatch, and complete explanation fields. Update the status ledger under `decision-policy`. Follow the common completion contract and commit.
```

## Prompt 06 — Reviewed evidence to decision snapshot

```text
$EV2 Connect reviewed evidence and incident state to immutable decision snapshots.

This packet is independently startable. Work inside an integration adapter; do not rewrite evidence or decision modules. If the target intelligence interface is absent, persist and test the snapshot contract without inventing its implementation.

Build a snapshot only from scoped reports, reviewed claims, linked incidents, sector assessment state, route/readiness observations, and policy version. Include exact source IDs, revision/version, event time, recorded time, freshness, uncertainty, unknown fields, and a canonical hash. Unreviewed or contradictory evidence must remain visible but must not silently become accepted truth. Missing decision-critical evidence should generate a verification-queue candidate with the reason it could change a decision.

Replace synthetic placeholder evidence references only when real seeded records exist. Preserve a clearly labeled synthetic provenance chain for demo data.

Self-verification: test exact source resolution, out-of-scope rejection, immutable hashes, revision changes producing new hashes, contradiction visibility, unknown preservation, decision-sensitive verification creation, and replay-time exclusion of future evidence. Update the status ledger under `decision-snapshot`. Follow the common completion contract and commit.
```

## Prompt 07 — Operator decision workspace

```text
$EV2 Build the smallest coherent React operator workspace that exposes the complete decision mechanism.

This packet is independently startable. Use current APIs and typed frontend adapters; fixtures may stand in for unavailable read-only intelligence APIs. Do not implement backend domain logic in React and do not add decorative dashboards.

The workspace must visibly answer: what is failing, what will fail next, how soon, why, what is unknown/stale, which interventions were compared, what the system recommends, what happens if nothing is done, which resources were excluded, and what the commander approved/rejected. Include evidence provenance, both queues, readiness/route state, task lifecycle, and outcome visibility. Render bounded GeoJSON meaningfully or provide an honest accessible spatial list if a map library is unavailable.

Use feature-oriented components rather than expanding one monolithic App.tsx. Show loading, empty, stale, offline, unauthorized, and error states without relying on color alone.

Self-verification: add component tests for the decision states, one mocked end-to-end operator flow, accessibility assertions for labels/status, TypeScript build, and a production build. Update the status ledger under `operator-workspace`. Follow the common completion contract and commit.
```

## Prompt 08 — Offline field task and report workflow

```text
$EV2 Implement the minimum honest offline field PWA workflow.

This packet is independently startable. Keep server authority explicit. Do not build background GPS, mesh networking, media uploads, or pretend shell caching is offline synchronization.

Add a bounded IndexedDB cache/outbox for assigned task packets and idempotent report, acknowledgement, en_route, completion, route-observation, and outcome commands. Show last sync, unsent count, failed/conflicted items, and retry state. Add a bounded sync API that authenticates and scopes every command, preserves client IDs/timestamps, returns per-command accepted/replayed/conflict/rejected results, and never applies later commands after an unresolved ordering conflict for the same aggregate.

Provide a printable task packet and explicit paper/radio fallback. Do not cache unnecessary sensitive coordinates or personal data.

Self-verification: test offline restart, ordered replay, duplicate replay, partial batch failure, conflict retention, expired session, quota/storage failure, bounded batch size, cross-scope rejection, and server-authoritative reconciliation. Update the status ledger under `offline-sync`. Follow the common completion contract and commit.
```

## Prompt 09 — Identity, tenant isolation, and abuse boundaries

```text
$EV2 Harden the identity and tenant boundary without requiring a real external provider.

This packet is independently startable. Preserve development identity only in development/test. Add an OIDC-compatible verifier interface with a deterministic local test provider; do not request, inspect, or embed secrets and do not claim production authentication.

Centralize role, organization, workspace/event, and scope resolution. Add PostgreSQL row-level-security policies for operational tables where practical, with application query scoping retained as defense in depth. Add bounded per-identity request throttling suitable for one-process demo use, safe mass-assignment rejection, and consistent problem responses. Production startup must refuse development identity.

Self-verification: test missing/invalid/expired identity, role denial, object-level cross-tenant access, direct database RLS isolation, development identity disabled in production, request-limit behavior, and no sensitive values in structured logs. Record provider/RLS deployment limitations honestly. Update the status ledger under `security-boundary`. Follow the common completion contract and commit.
```

## Prompt 10 — Transactional outbox and bounded job worker

```text
$EV2 Implement the database-backed outbox/job reliability slice promised by the architecture.

This packet is independently startable. Do not add Redis, Celery, Kafka, or another service. Use PostgreSQL and one bounded worker command.

Ensure important domain writes and their outbox event commit atomically. Implement job claim/lease, attempt count, bounded exponential backoff, idempotent handler key, success, retryable failure, terminal failure, and visible backlog age. Provide one useful handler such as replay export or SITREP generation. A crashed lease must be reclaimable without duplicate externally visible effects.

Self-verification: test transaction rollback leaves neither domain write nor event, concurrent claim exclusivity, lease expiry/reclaim, retry limit, idempotent replay, terminal failure visibility, and worker restart. Run a PostgreSQL concurrency test. Update the status ledger under `jobs-outbox`. Follow the common completion contract and commit.
```

## Prompt 11 — Safe CSV/GeoJSON import and redacted export

```text
$EV2 Implement a bounded import/export adapter slice.

This packet is independently startable. Do not build live external integrations, attachment scanning, ZIP ingestion, or a large mapping platform.

Accept only small CSV and GeoJSON fixtures with explicit mapping/schema version, maximum bytes/rows/features/geometry complexity, event timestamps, provenance, and per-row validation. Quarantine invalid rows and expose partial results without hiding originals. Prevent spreadsheet-formula injection on exported cells. Produce one authorized redacted CSV/GeoJSON export and one deterministic synthetic SITREP summary from scoped data.

Imports must create canonical commands through public application interfaces rather than writing private module tables directly.

Self-verification: test oversized input, malformed geometry, invalid timestamp, formula injection, partial failure, idempotent re-import, cross-scope export denial, redaction, deterministic SITREP, and absence of future replay data. Update the status ledger under `import-export`. Follow the common completion contract and commit.
```

## Prompt 12 — Polling/realtime and operational telemetry

```text
$EV2 Complete the observable update path using polling first and optional WebSockets second.

This packet is independently startable. Do not introduce a broker. Use committed outbox/audit records or a packet-local event adapter. Polling is the required path; WebSockets are optional only after polling tests pass.

Provide stable cursor polling for scoped operational changes with bounded pages, no silent gaps, and reconnect behavior. Add structured request/domain/job logs, health/readiness details, and lightweight counters/histograms for request latency, errors, queue depth, job backlog, recommendation decisions, and sync conflicts. Do not place personal data, raw report bodies, tokens, or exact sensitive locations in telemetry.

Self-verification: test cursor continuation, empty poll, invalid cursor, tenant isolation, reconnect catch-up, event ordering, telemetry labels with bounded cardinality, dependency degradation, and log redaction. Update the status ledger under `updates-telemetry`. Follow the common completion contract and commit.
```

## Prompt 13 — Reproducible reliability and recovery proof

```text
$EV2 Add reproducible local reliability evidence without making cloud or production claims.

This packet is independently startable. Use disposable local test data and exact documented commands. Do not access secrets and do not perform destructive operations against an unresolved or shared database target.

Document and automate: clean setup, migrations, seed/replay, application start, health verification, database backup to an explicit disposable path, restore into a separately named disposable database, audit-integrity verification, degraded database behavior, and manual paper/radio fallback. Add a safe target guard before any restore cleanup.

Self-verification: execute the clean-start path, back up seeded data, restore to the isolated target, compare key record counts/hashes, verify health and audit integrity, and record exact timings/results. Any unavailable platform command must be listed as unverified rather than simulated. Update the status ledger under `reliability-recovery`. Follow the common completion contract and commit.
```

## Prompt 14 — Representative replay, baseline, and ablation

```text
$EV2 Build the final synthetic evaluation package that proves the differentiated mechanism.

This packet is independently startable. Use 50–200 clearly labeled synthetic records with event-time ordering and provenance. Do not claim real-world accuracy or operational validation.

Create one deterministic flood/shelter replay containing contradictory reports, unknown sectors, stale routes/readiness, population influx, water contamination, power decline, purification dependency, cold-chain pressure, and constrained resources. Provide a baseline that ranks by report volume/manual asset availability and an ablation that removes dependency reasoning or verification value. Compare outputs using transparent operational metrics: critical failures identified before threshold, infeasible assignments proposed, unknown sectors surfaced, explanation completeness, and deterministic runtime.

The replay must hide future information, reset safely, and finish through commander decision, task acknowledgement, completion, outcome, and audit verification.

Self-verification: run the replay twice and compare hashes, validate record counts and timestamps, prove no future leakage, test invariants, store raw machine-readable results, and generate a concise human-readable comparison without unsupported superiority claims. Update the status ledger under `evaluation-replay`. Follow the common completion contract and commit.
```

## Prompt 15 — Final architecture acceptance gate

```text
$EV2 Run the final architecture acceptance gate. This is a verification and integration packet, not permission to add missing product scope.

This packet is independently startable. Read docs/SYSTEM_ARCHITECTURE.md Definition of Done and inspect current code, migrations, tests, status ledger, and prior evidence. Reproduce every claimed command. Mark each criterion Pass, Partial, Missing, Externally blocked, or Intentionally deferred with a direct file/test/result reference.

Run one clean evidence-to-outcome replay and verify: immutable provenance, contradiction/unknown handling, both queues, coupled state, projections, cascade explanations, non-mutating comparison, ranked feasible recommendation, explicit commander decision, no auto-dispatch, no double-booking, offline restart/sync, task outcome, polling catch-up, audit integrity, authorization boundaries, and recovery evidence.

Fix only failures that are small, reproduced, and inside an already implemented module. Do not create substitutes for partner approval, production OIDC, cloud hosting, legal review, tabletop drills, or production backup monitoring. Record those as external gates.

Create docs/architecture-alignment-final-report.md with exact evidence, remaining limitations, demo commands, and an honest completion percentage for Prototype, MVP, and Final District System. Follow the common completion contract and commit.
```

---

## Completion rule

The product matches the promised **prototype architecture** only when Prompt 15 can reproduce the prototype Definition of Done from a clean setup. Passing isolated unit tests or having endpoints is insufficient.

The product must not claim the **final district architecture** until partner approvals, real identity, operational drills, monitored recovery, legal/security review, and accepted capacity evidence exist. Those are external acceptance gates, not coding prompts.
