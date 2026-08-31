# Load harness

`k6 run load/k6-command.js` exercises command summary reads, cursor update polling, and a synthetic response-queue mutation. Provide `BASE_URL`, `AUTHORIZATION`, or (only for a non-production test server) `DEV_IDENTITY=operator` explicitly. The script never invents production credentials and uses a unique idempotency key per synthetic load action.

Results are valid only when k6 and a running, scoped test deployment are available. A missing k6 binary, backend, database, or authorization is **blocked**, not passed.
