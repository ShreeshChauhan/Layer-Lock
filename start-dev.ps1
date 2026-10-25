# Vite starts the API if needed and stops only the backend it owns on exit.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Install the backend dependencies in .venv first (see docs/INTEGRATION.md).'
}
Push-Location $projectRoot
try {
    Set-Location (Join-Path $projectRoot 'frontend')
    & npm.cmd run dev
} finally {
    Pop-Location
}
