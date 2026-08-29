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

All identifiers are opaque, immutable strings. The event envelope is delivered at least once; consumers deduplicate by event occurrence ID.
