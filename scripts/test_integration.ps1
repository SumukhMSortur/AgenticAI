param(
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
} else {
    $python = $PythonPath
}

if (-not (Test-Path $python)) {
    throw "Project virtual environment not found: $python"
}

& $python -m pytest backend\tests -m integration -v
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
