# Phase 1 Bug Log

| Finding | Classification | Root cause | Fix | Verification |
|---|---|---|---|---|
| Frontend dependency audit reported one high-severity Vite advisory | Environment/dependency issue | The initially selected Vite 7.1.3 was inside an affected range | Pinned Vite 7.3.6 and regenerated `package-lock.json` | `npm.cmd --prefix .\frontend audit --audit-level=high` returned 0 vulnerabilities |
| FastAPI rejected the readiness endpoint return annotation during test collection | Implementation bug | `JSONResponse | dict` was interpreted as an invalid response model | Disabled generated response modeling for the endpoint while retaining its explicit typed return | Targeted `tests/test_api.py`: 6 passed; full backend suite: 10 passed |
| Ruff could not create its cache under the managed filesystem | Environment/configuration issue | The validation environment denied temporary cache creation | Made the check script use Ruff's supported `--no-cache` mode | Full `scripts/check.ps1` gate passed |

No frozen-contract or architecture issue was found.
