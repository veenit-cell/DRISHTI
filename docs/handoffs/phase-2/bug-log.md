# Phase 2 Bug Log

| Finding | Classification | Fix | Verification |
|---|---|---|---|
| Initial evidence test expected unknown `people_affected` to produce no warning | Test bug | Corrected the expectation; `null` remains explicit and emits an unknown warning | Full backend suite passed: 17 tests |
| Initial cursor test expected the second item to disappear | Test bug | Corrected the expectation; the opaque cursor returns the remaining report | Full backend suite passed: 17 tests |
| Ruff flagged SQL statements and imports | Implementation/quality issue | Applied import fixes and documented intentional SQL line-length exemption | Ruff format/check passed |
| Managed filesystem denied Vite temporary writes in sandbox mode | Environment issue | Re-ran the build through the approved elevated path; no source workaround added | Vite production build passed |

No evidence-immutability, scope, or frozen-architecture conflict was found.
