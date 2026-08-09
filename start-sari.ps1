param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".env")) {
    Write-Error "The .env file is missing. Run 'Copy-Item .env.example .env', then replace the password and token placeholders."
}

$envText = Get-Content -LiteralPath ".env" -Raw
if ($envText -match '(?m)^POSTGRES_PASSWORD=replace-' -or $envText -match '(?m)^OCR_SERVICE_TOKEN=replace-') {
    Write-Error "Replace the POSTGRES_PASSWORD and OCR_SERVICE_TOKEN placeholders in .env before starting Sari."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not installed or is not available in PATH. Install Docker Desktop for Windows first."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker Desktop is not running. Start it, wait until it is ready, then run this script again."
}

Write-Host "Building and starting the complete local Sari stack..." -ForegroundColor Cyan
docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) {
    Write-Error "Sari failed to start. Run 'docker compose logs --tail=100 frontend backend ocr-gateway database'."
}

$appPort = 8080
$portSetting = Get-Content -LiteralPath ".env" | Where-Object { $_ -match '^APP_PORT=' } | Select-Object -Last 1
if ($portSetting) {
    $candidatePort = ($portSetting -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if ($candidatePort -match '^\d+$') {
        $appPort = [int]$candidatePort
    }
}

$appUrl = "http://127.0.0.1:$appPort"
Write-Host "Sari is ready at $appUrl" -ForegroundColor Green
Write-Host "PostgreSQL, FastAPI, and OCR remain private inside Docker."

if (-not $NoBrowser) {
    Start-Process $appUrl
}
