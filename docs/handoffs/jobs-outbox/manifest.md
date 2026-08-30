# Jobs/outbox handoff

Implemented the PostgreSQL-backed outbox/job reliability contract with an in-memory parity adapter and bounded worker command.

Verification:

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_jobs_outbox.py -q` — 2 passed
- `.\.venv\Scripts\python.exe -m pytest backend/tests -q` — 64 passed
- `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` — passed
- `git diff --check` — passed

Use `python -m app.worker --once --tenant org_demo --workspace evt_demo` for one bounded SITREP job attempt. Lease expiry is reclaimable; handler keys prevent duplicate externally visible handling. PostgreSQL concurrency execution remains deployment-dependent and is documented rather than overstated.
