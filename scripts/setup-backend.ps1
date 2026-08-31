param(
  [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  throw "Python 3.12-3.13 is required. Install Python, then rerun scripts/setup-backend.ps1."
}
if (-not (Test-Path $python)) {
  & py -3.13 -m venv $venv
  if ($LASTEXITCODE -ne 0) { & py -3.12 -m venv $venv }
}
if (-not $SkipInstall) {
  & $python -m pip install --upgrade pip
  Push-Location (Join-Path $root "backend")
  try { & $python -m pip install -e ".[dev]" } finally { Pop-Location }
}
Write-Output "Backend environment ready at $venv"
