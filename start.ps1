# One-command local launch (Windows PowerShell).
#   .\start.ps1            build if needed, then serve on http://127.0.0.1:8000
#   .\start.ps1 -Rebuild   force re-ingest and frontend rebuild
param([switch]$Rebuild, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    Write-Host '> Creating Python venv'
    python -m venv .venv
}
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Write-Host '> Installing Python requirements'
& $py -m pip install -q -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

if ($Rebuild -or -not (Test-Path frontend\dist)) {
    Write-Host '> Building frontend'
    Push-Location frontend
    npm install --no-audit --no-fund
    npm run build
    Pop-Location
    if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
}

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host '> Created .env from .env.example - add GEMINI_API_KEY for chat answers (offline mode works without it)'
}

Push-Location backend
if ($Rebuild -or -not (Test-Path ..\data\meridian.db)) {
    Write-Host '> Building knowledge database'
    & $py -m app.ingest.run
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'ingest failed' }
}
Write-Host "> Serving on http://127.0.0.1:$Port"
& $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port
Pop-Location
