# Decision policy handoff

Implemented `intervention_policy_v1` with deterministic candidate ranking and hard operational exclusions.

Verification:

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_decision_policy.py backend/tests/test_decision_loop.py -q` — 5 passed
- `.\.venv\Scripts\python.exe -m pytest backend/tests -q` — 54 passed
- `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` — passed
- `git diff --check` — passed

Candidates stay pending until commander approval. Approval uses the existing queue-only path and never auto-dispatches or assigns a task. Synthetic adapters are independent of live shelter tables.
