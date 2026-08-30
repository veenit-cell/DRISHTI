# Real API golden flow

The React operator workspace now executes the server-authoritative synthetic path:

`reset replay → generate ranked recommendation → commander approve/reject → confirm route → manually assign ready resource → acknowledge → en route → complete → record outcome → refresh audit and queues`.

Approval still creates only a queue item and displays `auto-dispatch: false`. Route freshness and resource compatibility remain backend-enforced. The fixture is used only after the operator explicitly selects offline fallback.

Verification:

- `pytest -q tests/test_frontend_golden_flow.py` — 1 passed.
- `ruff check --no-cache tests/test_frontend_golden_flow.py` — passed.
- `npm run build` from `frontend` — TypeScript and Vite production build passed.
