# Cascade engine handoff

## Delivered

- Pure `cascade_v1` evaluator in `backend/app/cascade.py`; no database, ML, or operational mutation.
- Typed snapshot adapter with explicit units, freshness, timestamps, and supporting references.
- Four bounded dependency paths plus cycle/depth validation and deterministic ordering.
- Bounded API: `POST /api/v1/cascade/evaluate` (`decision:read`).

## Verification

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_cascade.py -q` — 4 passed.
- `.\.venv\Scripts\python.exe -m pytest backend/tests -q` — 47 passed.
- `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` — passed.

## Limitations

Signals are operational capability/pressure indicators only. Missing or stale inputs are surfaced; no clinical diagnosis, forecast, dispatch, persistence, or ML is included.
