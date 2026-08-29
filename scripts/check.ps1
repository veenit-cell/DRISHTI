$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment missing. Run the one-time setup commands in README.md.'
}

Push-Location $projectRoot
try {
    Push-Location '.\backend'
    try {
        & $pythonPath -m ruff format --no-cache --check .
        & $pythonPath -m ruff check --no-cache .
        & $pythonPath -m pytest -p no:cacheprovider
    }
    finally {
        Pop-Location
    }

    npm.cmd --prefix '.\frontend' run build
}
finally {
    Pop-Location
}
