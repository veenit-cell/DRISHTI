param([switch]$Integration)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Missing .venv. Run scripts/setup-backend.ps1 first." }
Push-Location (Join-Path $root "backend")
try {
  & $python -m ruff check .
  if ($Integration) {
    & $python -m pytest -p no:cacheprovider
  } else {
    & $python -m pytest -p no:cacheprovider -m "not integration"
  }
} finally { Pop-Location }
