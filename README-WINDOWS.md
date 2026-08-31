# RescueOps — Windows Setup

This guide is for the unpacked RescueOps project running from Windows PowerShell.

## Directory layout

```text
D:\HEHEHE\
├── backend\       FastAPI application
├── frontend\      frontend application
└── .venv\         Python virtual environment
```

## Prerequisites

- Python 3.13 (the current environment uses Python 3.13)
- Node.js and npm
- PostgreSQL, or the configured hosted database

Check versions:

```powershell
python --version
node --version
npm --version
```

## Backend

```powershell
cd D:\HEHEHE
.\.venv\Scripts\Activate.ps1
```

Install dependencies from the manifest present in this checkout:

```powershell
if (Test-Path .\backend\requirements.txt) {
    python -m pip install -r .\backend\requirements.txt
} elseif (Test-Path .\requirements.txt) {
    python -m pip install -r .\requirements.txt
} elseif (Test-Path .\backend\pyproject.toml) {
    python -m pip install -e .\backend
} else {
    Write-Error "No backend dependency manifest was found."
}
```

The backend imports `pydantic_settings`, supplied by `pydantic-settings`. If it
is absent from the dependency manifest:

```powershell
python -m pip install pydantic-settings
```

## Database

The API requires the database schema. The error `relation "incidents" does not
exist` means migrations have not been applied to the configured database.

For an Alembic project, from `D:\HEHEHE\backend` run:

```powershell
python -m alembic upgrade head
```

For a Supabase project, from `D:\HEHEHE` run:

```powershell
supabase db push
```

Use the migration system included in the repository; do not create only the
`incidents` table manually.

## Start backend

```powershell
cd D:\HEHEHE\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API URL: `http://127.0.0.1:8000`

## Frontend

Use a second PowerShell window:

```powershell
cd D:\HEHEHE\frontend
npm install
npm run dev
```

Because you are already inside `frontend`, do not run `npm --prefix frontend
install`; that searches for `D:\HEHEHE\frontend\frontend\package.json`.

From the project root, the equivalent commands are:

```powershell
cd D:\HEHEHE
npm --prefix .\frontend install
npm --prefix .\frontend run dev
```

## Environment variables

If `.env.example` exists:

```powershell
cd D:\HEHEHE\backend
Copy-Item .env.example .env
```

Edit `.env` with the database URL and other settings. A temporary PowerShell
variable uses:

```powershell
$env:DATABASE_URL = "your-database-connection-string"
```

## Common errors

- `requirements.txt` not found: check `Get-Location`; use `.\requirements.txt` from `backend`, or `..\requirements.txt` if that is where the file actually exists.
- `package.json` not found: run `npm install` from `D:\HEHEHE\frontend`.
- `relation "incidents" does not exist`: apply database migrations.
- `ModuleNotFoundError: pydantic_settings`: activate `.venv` and install backend dependencies.
