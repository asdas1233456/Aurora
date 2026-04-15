param(
    [switch]$SkipFullExistingE2E
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$FrontendRoot = Join-Path $RepoRoot "frontend"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit code $LASTEXITCODE)"
    }
}

function Stop-Port {
    param([int]$Port)

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    $processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        if ($processId) {
            Stop-Process -Id $processId -Force
        }
    }
}

Push-Location $RepoRoot
try {
    Invoke-Step "Frontend production build" { npm --prefix frontend run build }
    Invoke-Step "Frontend unit tests" { npm --prefix frontend run test }
    Invoke-Step "Backend, service, API, white-box, gray-box, and final API acceptance tests" { python -m pytest tests }

    Stop-Port 8010
    if (-not $SkipFullExistingE2E) {
        Push-Location $FrontendRoot
        try {
            Invoke-Step "Existing Playwright E2E regression suite" { npx playwright test }
        }
        finally {
            Pop-Location
        }
    }

    Stop-Port 8010
    Push-Location $FrontendRoot
    try {
        Invoke-Step "Final Playwright launch acceptance suite" { npx playwright test --config ..\tests\final_acceptance.playwright.config.cjs }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Final acceptance run completed successfully." -ForegroundColor Green
