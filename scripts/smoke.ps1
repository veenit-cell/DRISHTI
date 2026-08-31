param(
  [string]$FrontendUrl = "http://127.0.0.1:4173",
  [string]$BackendUrl = "http://127.0.0.1:8000",
  [switch]$CheckCompose
)

$ErrorActionPreference = "Stop"
function Assert-Http($url) {
  $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
  if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) { throw "$url returned $($response.StatusCode)" }
  Write-Output "passed $url ($($response.StatusCode))"
}

Assert-Http $FrontendUrl
Assert-Http "$BackendUrl/api/v1/health/live"
Assert-Http "$BackendUrl/api/v1/health/ready"
if ($CheckCompose) {
  docker compose -f (Join-Path (Split-Path -Parent $PSScriptRoot) "infra\compose.integration.yaml") config | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Integration Compose configuration is invalid" }
  Write-Output "passed integration compose config"
}
