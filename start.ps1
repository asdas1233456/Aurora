param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"

Set-Location $projectRoot

Write-Host ""
Write-Host "Aurora starting..." -ForegroundColor Cyan
Write-Host "Project root: $projectRoot"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js was not found. Please install Node.js 20+ first."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Please install npm first."
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Please install Python 3.11+ first."
}

if (-not (Test-Path $frontendRoot)) {
    throw "frontend directory was not found."
}

if (-not (Test-Path ".venv\\Scripts\\python.exe")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

if (-not (Test-Path ".env")) {
    Write-Host "Creating .env file..." -ForegroundColor Yellow
    Copy-Item .env.example .env
}

if (-not (Test-Path ".venv\\Scripts\\uvicorn.exe")) {
    Write-Host "Installing backend dependencies..." -ForegroundColor Yellow
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

if (-not (Test-Path (Join-Path $frontendRoot "node_modules"))) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
    Set-Location $frontendRoot
    npm install
    Set-Location $projectRoot
}

Write-Host "Building React frontend..." -ForegroundColor Yellow
Set-Location $frontendRoot
npm run build | Out-Host
Set-Location $projectRoot

Write-Host ""
Write-Host "Starting FastAPI app with built frontend..." -ForegroundColor Green
Write-Host "Open: http://127.0.0.1:$Port"
Write-Host ""

$env:API_PORT = "$Port"
.\.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port $Port
