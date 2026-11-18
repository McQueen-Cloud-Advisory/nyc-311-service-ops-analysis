param([string]$Python = (Join-Path $PSScriptRoot '../.venv/Scripts/python.exe'))
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $projectRoot
try {
    & $Python -m nyc311 validate
    if ($LASTEXITCODE -ne 0) { throw 'Python validation failed.' }
    & (Join-Path $projectRoot 'infra/Test-Local.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Infrastructure validation failed.' }
} finally { Pop-Location }
