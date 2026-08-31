# Idempotency key lifecycle

DRISHTI uses one `Idempotency-Key` for each logical mutation. The operator client creates the key when the action starts, stores it in session storage while the request is pending, and sends the same key for timeout, reconnect, and browser retry attempts. A successful response clears the client entry. Compound actions retain their base key until every server-confirmed step has completed.

The key is scoped by tenant and workspace on the server. The request payload is hashed canonically. Reusing a key with different payload data returns a `409` problem response with code `IDEMPOTENCY_CONFLICT`; it never replays a different operation. A duplicate request with the same payload returns the original stored result and does not create another queue item, task, report, mission, or update event.

Server records use the existing `idempotency_records` table where the durable store owns the write, and the shared coordinator for routes without store-native replay. Records expire after 24 hours. Client pending entries use the same 24-hour retention window and are removed after confirmed success or expiry. Expiration permits a new logical action; it is not a substitute for authorization or server reconciliation.

Correlation IDs are request metadata and are not part of the idempotency payload hash. Therefore a retry may have a new correlation ID while still replaying the original result and original event cursor. Idempotency keys are not authentication credentials and must never contain secrets.

Evaluation-only endpoints such as runway, cascade, policy, snapshot, and what-if evaluation do not mutate operational state and do not use mutation idempotency records.
