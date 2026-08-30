# Offline sync handoff

Implemented the minimum honest field PWA workflow.

Verification:

- `.\.venv\Scripts\python.exe -m pytest backend/tests -q` — 60 passed
- `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` — passed
- `npm --prefix frontend run build` — TypeScript and production Vite build passed
- `git diff --check` — passed

The IndexedDB outbox stores only bounded task/command metadata. Sync preserves client IDs/timestamps, returns per-command outcomes, rejects cross-scope/expired-auth requests through normal API auth, and blocks later aggregate commands after ordering conflicts. Paper/radio fallback and printable task packets are explicit; no GPS, mesh, uploads, or fake offline authority are included.
