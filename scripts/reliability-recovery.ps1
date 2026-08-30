param(
    [string] $BackupPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'artifacts\recovery\ev2-seeded.dump'),
    [string] $RestoreDatabase = 'ev2_recovery_demo',
    [int] $ApiPort = 8011
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $root 'infra\compose.yaml'
$python = Join-Path $root '.venv\Scripts\python.exe'
$api = "http://127.0.0.1:$ApiPort"
$started = Get-Date

if ($RestoreDatabase -notmatch '^ev2_recovery_[a-z0-9_]+$') {
    throw 'RestoreDatabase must match the safe disposable target pattern ev2_recovery_<name>.'
}
if ([IO.Path]::GetFullPath($BackupPath) -notlike "$root\artifacts\recovery\*") {
    throw 'BackupPath must remain under the repository artifacts\recovery directory.'
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing .venv Python; run the documented setup first.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'UNVERIFIED: Docker is unavailable.' }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $BackupPath) | Out-Null
docker compose -f $compose up -d --wait database
if ($LASTEXITCODE -ne 0) { throw 'UNVERIFIED: Docker database startup failed or Docker is unavailable.' }
Push-Location $root
$server = $null
try {
    Push-Location backend
    try { & $python -m app.persistence } finally { Pop-Location }
    $server = Start-Process -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$ApiPort" -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden -PassThru
    $ready = $false
    1..20 | ForEach-Object {
        if (-not $ready) {
            try { $ready = (Invoke-RestMethod -Uri "$api/api/v1/health/live" -TimeoutSec 1).status -eq 'ok' } catch { Start-Sleep -Milliseconds 250 }
        }
    }
    if (-not $ready) { throw 'Application did not become ready.' }
    $headers = @{ 'X-Dev-Identity' = 'operator'; 'Idempotency-Key' = 'recovery-seed-001' }
    $seed = Invoke-RestMethod -Method Post -Uri "$api/api/v1/operations/demo/seed" -Headers $headers
    $replayHeaders = @{ 'X-Dev-Identity' = 'operator'; 'Idempotency-Key' = 'recovery-replay-001' }
    Invoke-RestMethod -Method Post -Uri "$api/api/v1/decision-loop/demo/replay" -Headers $replayHeaders | Out-Null
    $health = Invoke-RestMethod -Method Get -Uri "$api/api/v1/health/ready"
    if ($health.status -ne 'ready') { throw 'Health verification failed.' }
    $audit = Invoke-RestMethod -Method Get -Uri "$api/api/v1/audit/integrity" -Headers @{ 'X-Dev-Identity' = 'operator' }
    if ($audit.available -and $audit.valid -ne $true) { throw 'Audit integrity verification failed.' }

    $container = (docker compose -f $compose ps -q database).Trim()
    if ([string]::IsNullOrWhiteSpace($container)) { throw 'Could not resolve the local Compose database container.' }
    docker compose -f $compose exec -T database pg_dump -U postgres -d ev2 -Fc -f /tmp/ev2-seeded.dump
    if ($LASTEXITCODE -ne 0) { throw 'Database backup failed.' }
    docker cp "${container}:/tmp/ev2-seeded.dump" $BackupPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy the disposable backup out of the container.' }
    docker compose -f $compose exec -T database rm -f /tmp/ev2-seeded.dump | Out-Null
    # Destructive SQL is permitted only for this explicitly guarded disposable target.
    docker compose -f $compose exec -T database psql -U postgres -d ev2 -c "DROP DATABASE IF EXISTS $RestoreDatabase;" | Out-Null
    docker compose -f $compose exec -T database createdb -U postgres $RestoreDatabase
    docker cp $BackupPath "${container}:/tmp/ev2-restore.dump"
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy the backup into the disposable restore container.' }
    docker compose -f $compose exec -T database pg_restore -U postgres -d $RestoreDatabase --clean --if-exists /tmp/ev2-restore.dump
    if ($LASTEXITCODE -ne 0) { throw 'Database restore failed.' }
    docker compose -f $compose exec -T database rm -f /tmp/ev2-restore.dump | Out-Null

    $query = "SELECT 'audit_events='||count(*) FROM audit_events; SELECT 'raw_reports='||count(*) FROM raw_reports; SELECT 'audit_hash='||md5(COALESCE(string_agg(COALESCE(event_hash,''),'' ORDER BY chain_sequence),'')) FROM audit_events;"
    $counts = docker compose -f $compose exec -T database psql -U postgres -d ev2 -Atc $query
    if ($LASTEXITCODE -ne 0) { throw 'Source count/hash query failed.' }
    $restoredCounts = docker compose -f $compose exec -T database psql -U postgres -d $RestoreDatabase -Atc $query
    if ($LASTEXITCODE -ne 0) { throw 'Restored count/hash query failed.' }
    if (($counts -join '').Trim() -ne ($restoredCounts -join '').Trim()) { throw 'Restore count comparison failed.' }
    Write-Output "PASS clean-start seed/replay/health/audit/backup/restore; backup=$BackupPath target=$RestoreDatabase elapsed_seconds=$([math]::Round(((Get-Date)-$started).TotalSeconds,2))"
    Write-Output "COUNTS source=$($counts -join ',') restored=$($restoredCounts -join ',')"
}
finally {
    if ($null -ne $server -and -not $server.HasExited) { Stop-Process -Id $server.Id }
    Pop-Location
}
