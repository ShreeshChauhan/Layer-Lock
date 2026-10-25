# Start the API and dashboard together. Ctrl+C stops the API launched by this script.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Install the backend dependencies in .venv first (see DASHBOARD_INTEGRATION.md).'
}
$apiProcess = $null
Push-Location $projectRoot
try {
    $apiProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'backend.log') -RedirectStandardError (Join-Path $projectRoot 'backend-error.log')
    Start-Sleep -Seconds 2
    if ($apiProcess.HasExited) {
        throw 'Backend failed to start. Check backend-error.log; stop any existing backend on port 8000 before using this launcher.'
    }
    Write-Host 'Backend started. Live View loads automatically; use Enable vision in the dashboard to start failure detection.'
    Set-Location (Join-Path $projectRoot 'frontend')
    & npm.cmd run dev
} finally {
    if ($apiProcess -and -not $apiProcess.HasExited) {
        # Stop this launcher's API and its owned inference child process together.
        & taskkill.exe /PID $apiProcess.Id /T /F 2>$null | Out-Null
    }
    Pop-Location
}
