param(
    [switch]$SkipGitPull,
    [switch]$MigrateSQLite,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Action
    )

    Write-Host "`n==> $Title" -ForegroundColor Cyan
    & $Action
}

function Assert-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing command: $Name"
    }
}

Assert-Command git
Assert-Command uv

if (-not (Test-Path '.\.env')) {
    throw 'Missing .env. Create it from .env.example before deployment.'
}

if (-not $SkipGitPull) {
    Invoke-Step 'Pull latest code' {
        git pull --ff-only
    }
}

Invoke-Step 'Sync Python dependencies' {
    uv sync
}

Invoke-Step 'Initialize MySQL database' {
    uv run python -c "from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME; from app.db import ensure_default_admin, init_db; init_db(); ensure_default_admin(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD); print('Database initialization completed')"
}

if ($MigrateSQLite) {
    if (Test-Path '.\data\app.db') {
        Invoke-Step 'Migrate SQLite data to MySQL' {
            uv run python migrate_to_mysql.py
        }
    }
    else {
        Write-Host "`n==> Skip SQLite migration: data/app.db not found" -ForegroundColor Yellow
    }
}

if (-not $NoStart) {
    Invoke-Step 'Start application service' {
        Start-Process -FilePath 'powershell.exe' -WorkingDirectory $repoRoot -ArgumentList @(
            '-NoExit',
            '-ExecutionPolicy',
            'Bypass',
            '-Command',
            ('Set-Location "' + $repoRoot + '"; uv run python main.py')
        )
    }
    Write-Host "`nDeployment complete. Service started in a new terminal. Default URL: http://127.0.0.1:8000" -ForegroundColor Green
}
else {
    Write-Host "`nDeployment complete. Service start skipped." -ForegroundColor Green
}