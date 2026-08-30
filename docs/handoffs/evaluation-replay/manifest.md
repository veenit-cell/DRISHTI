# Evaluation replay handoff

Added a deterministic, synthetic evaluation package with 121 fixture records (120 visible at replay time plus one future record deliberately excluded). The scenario explicitly labels contradictory reports, unknown sectors, stale route/readiness observations, influx, contamination, power decline, purification dependency, cold-chain pressure, and constrained resources.

Run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-evaluation-replay.ps1
```

Outputs:

- `artifacts/evaluation-replay/results.json` — machine-readable hashes, counts, timestamps, metrics, ablation, lifecycle, and provenance.
- `artifacts/evaluation-replay/comparison.md` — concise baseline/ablation comparison.

Verification: `pytest -q tests/test_evaluation_replay.py` = **2 passed**; replay command executed successfully; repeated hashes are covered by tests. This is synthetic evidence only and makes no accuracy or operational-validation claim.
