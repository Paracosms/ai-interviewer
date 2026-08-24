$ErrorActionPreference = 'Stop'

$HostRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $HostRoot '.venv'
$PythonPath = Join-Path $VenvPath 'Scripts\python.exe'
$RequirementsPath = Join-Path $HostRoot 'requirements.txt'
$ExamplePath = Join-Path $HostRoot '.env.example'
$EnvPath = Join-Path $HostRoot '.env'

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found on PATH. Install Python 3.11+ and rerun this script."
}

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    & python -m venv $VenvPath
}

& $PythonPath -m pip install --upgrade pip
& $PythonPath -m pip install -r $RequirementsPath

if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    Copy-Item -LiteralPath $ExamplePath -Destination $EnvPath
    Write-Host "Created host/.env from .env.example. Add GEMINI_API_KEY before starting the host."
} else {
    Write-Host "Keeping existing host/.env."
}

Write-Host "Setup complete. Start the host with .\run.ps1."

