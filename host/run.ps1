$ErrorActionPreference = 'Stop'

$HostRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $HostRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "The host virtual environment is missing. Run .\setup.ps1 from the host directory first."
}

if (-not (Test-Path -LiteralPath (Join-Path $HostRoot '.env') -PathType Leaf)) {
    throw "host/.env is missing. Run .\setup.ps1, then add GEMINI_API_KEY to host/.env."
}

Push-Location $HostRoot
try {
    & $PythonPath -m interviewer @args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

