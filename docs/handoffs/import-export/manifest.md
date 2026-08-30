# Import/export handoff

Implemented the bounded CSV/GeoJSON fixture import and redacted export slice.

Verification:

- `.\.venv\Scripts\python.exe -m pytest backend/tests/test_import_export.py -q` — 3 passed
- `.\.venv\Scripts\python.exe -m pytest backend/tests -q` — 67 passed
- `.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests` — passed
- `git diff --check` — passed

Invalid rows/features remain quarantined with originals; valid rows become canonical command-shaped records. Formula-leading cells are prefixed, sensitive columns are redacted, and SITREP replay excludes future timestamps. No external or large-file ingestion is claimed.
