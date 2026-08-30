# What-if handoff

Implemented `what_if_v1` as a pure, non-mutating comparison module and API.

Verification:

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_what_if.py -q` — 3 passed
- `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` — passed
- `.\.venv\Scripts\python.exe -m pytest backend/tests -q` — 50 passed
- `git diff --check` — passed

The module rejects unsupported fields, invalid units/combinations, and horizons above 168 hours. It does not read or mutate live shelter state. Synthetic intervention effects are operational projections, not clinical or production claims.
