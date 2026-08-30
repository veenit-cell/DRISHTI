# Decision snapshot handoff

Implemented `decision_snapshot_v1` as a pure scoped integration adapter.

Verification:

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_decision_snapshot.py -q` — 4 passed
- `.\.venv\Scripts\python.exe -m pytest backend/tests -q` — 58 passed
- `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` — passed
- `git diff --check` — passed

The contract preserves visible contradictions/unknowns, excludes future replay records, rejects out-of-scope sources, and emits verification-queue candidates where missing evidence could change a decision. No evidence or decision module was rewritten.
