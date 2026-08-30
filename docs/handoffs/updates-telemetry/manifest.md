# Updates and telemetry handoff

Implemented the minimum observable update path for the hackathon demo.

## Delivered

- Scoped polling at `GET /api/v1/updates` with monotonic opaque cursors, bounded pages (1–100), empty polls, invalid-cursor errors, tenant/workspace isolation, and reconnect catch-up.
- Safe packet-local publish adapter at `POST /api/v1/updates`; payload is limited to event type, aggregate ID, and optional status.
- `GET /api/v1/metrics` exposes bounded low-cardinality request counters/latencies and queue/job gauges. Recommendation and sync-conflict counters are available through the telemetry contract for existing integrations.
- Request structured logs contain only method, status, and duration; no report payloads, tokens, personal data, or exact locations.

## Verification

From `backend`:

```powershell
pytest -q tests/test_updates_telemetry.py
# 4 passed
pytest -q
# 71 passed
```

## Honest limitations

The feed is process-local for this checkpoint and is intentionally not a broker. A production deployment should read committed outbox/audit records and expose durable retention. WebSockets are optional and were not added because polling is the required, tested path.
