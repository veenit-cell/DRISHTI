param(
  [switch]$Offline
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$python = Join-Path $root ".venv\Scripts\python.exe"
$auditArgs = @("audit", "--audit-level=high")
if ($Offline) { $auditArgs += "--offline" }

Push-Location $frontend
try { & npm.cmd @auditArgs } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "npm audit did not complete cleanly" }

if (-not (Test-Path $python)) {
  Write-Output "blocked backend security check: .venv is unavailable"
  exit 2
}
${pipAudit} = Join-Path $root ".venv\Scripts\pip-audit.exe"
if (-not (Test-Path $pipAudit)) {
  Write-Output "blocked backend security check: pip-audit is not installed"
  exit 2
}
Push-Location (Join-Path $root "backend")
try { & $pipAudit --strict } finally { Pop-Location }
