# Phase 1 Semantic Glossary

- **Actor:** authenticated human or system identity responsible for an operation.
- **Tenant / organization:** the jurisdictional data boundary. IDs never grant access.
- **Event workspace:** one disaster-event scope inside a tenant. It is explicitly `live` or `replay`.
- **Event time (`occurred_at`):** when the represented operational fact happened in live or replay time.
- **Recorded time (`recorded_at`):** when this system durably recorded the event.
- **Unknown (`null`):** information was not supplied or cannot presently be established.
- **Zero (`0`):** an observed or calculated quantity of zero. It must never stand in for unknown.
- **Correlation ID:** bounded request/workflow identifier used for safe diagnostics; it is not authorization.
- **Idempotency key:** bounded client-selected write identifier scoped to tenant and workspace. Reuse with a different request payload is a conflict.
- **Revision:** positive aggregate version used for optimistic concurrency and per-aggregate event ordering.
- **Command incident:** the scoped event record that holds hazard, severity, operational period, phase, and named command roles.
- **Sector:** an owned operational area with an explicit assessment state. `unassessed` and `inaccessible` are not safe states.
- **Evidence report:** immutable source record with observed/received/recorded times, claims, location uncertainty, and review state.
- **Coverage debt:** a deterministic measure of what remains unknown in a sector/cell. It is an ignorance signal, not a casualty estimate.
- **Verification ranking:** a decision-sensitive order for information-gathering tasks; it is not a dispatch order.
- **Mission:** a human-approved operational objective linked to source evidence and constrained by route, capability, readiness, and lifecycle state.
- **Structured outcome:** completion evidence that records what occurred, quantities, residual need, completion time, and verifier.
- **Synthetic:** fixture or exercise data. It must never be represented as live agency or field information.
- **Offline reconciliation:** server acknowledgement and ordering of queued commands. In the current MVP it does not itself apply accepted task updates to task state.

All identifiers are opaque, immutable strings. The event envelope is delivered at least once; consumers deduplicate by event occurrence ID.
