$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment missing. Run the one-time setup commands in README.md.'
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'npm.cmd is required. Install Node.js 22 or newer.'
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker with Compose is required for the local PostgreSQL/PostGIS profile.'
}

Push-Location $projectRoot
try {
    docker compose -f '.\infra\compose.yaml' up -d --wait database

    Push-Location '.\backend'
    try {
        & $pythonPath -m app.persistence
    }
    finally {
        Pop-Location
    }

    $backend = Start-Process -FilePath $pythonPath `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory (Join-Path $projectRoot 'backend') `
        -WindowStyle Hidden `
        -PassThru
    $frontend = Start-Process -FilePath 'npm.cmd' `
        -ArgumentList 'run', 'dev' `
        -WorkingDirectory (Join-Path $projectRoot 'frontend') `
        -WindowStyle Hidden `
        -PassThru

    Write-Output 'EV2 started: frontend http://127.0.0.1:5173 | API http://127.0.0.1:8000'
    Write-Output 'Press Ctrl+C to stop the application processes.'
    try {
        while (-not $backend.HasExited -and -not $frontend.HasExited) {
            Start-Sleep -Seconds 1
            $backend.Refresh()
            $frontend.Refresh()
        }
        if ($backend.HasExited) {
            throw "Backend exited unexpectedly with code $($backend.ExitCode)."
        }
        throw "Frontend exited unexpectedly with code $($frontend.ExitCode)."
    }
    finally {
        foreach ($process in @($backend, $frontend)) {
            if ($null -ne $process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id
            }
        }
    }
}
finally {
    Pop-Location
}
