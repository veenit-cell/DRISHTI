$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment missing.' }
Push-Location (Join-Path $root 'backend')
try {
    $json = & $python -c "import json; from app.evaluation_replay import run_replay; print(json.dumps(run_replay(), indent=2, sort_keys=True))"
    if ($LASTEXITCODE -ne 0) { throw 'Evaluation replay failed.' }
    $out = Join-Path $root 'artifacts\evaluation-replay\results.json'
    New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
    $json | Set-Content -Encoding utf8 -Path $out
    $data = $json | ConvertFrom-Json
    $comparison = @" 
# Synthetic evaluation replay

This is a deterministic synthetic comparison, not real-world validation.

| Metric | Baseline / ablation | Dependency-aware |
|---|---:|---:|
| Critical failures identified before threshold | $($data.baseline.critical_failures_before_threshold) | $($data.dependency_aware.critical_failures_before_threshold) |
| Infeasible assignments proposed | $($data.baseline.infeasible_assignments) | $($data.dependency_aware.infeasible_assignments) |
| Unknown sectors surfaced | $($data.baseline.unknown_sectors_surfaced) | $($data.dependency_aware.unknown_sectors_surfaced) |
| Explanation completeness | $($data.baseline.explanation_completeness) | $($data.dependency_aware.explanation_completeness) |

Records: $($data.record_count) visible, $($data.future_records_excluded) future record excluded. Result hash: `$($data.result_hash)`.
Lifecycle: commander approval → acknowledgement → en route → completion → outcome → audit verification.
"@
    $comparison | Set-Content -Encoding utf8 -Path (Join-Path (Split-Path $out) 'comparison.md')
    Write-Output "Wrote $out"
    Write-Output $json
}
finally { Pop-Location }
