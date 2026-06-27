<#
.SYNOPSIS
  Install the Evavo Quotation Platform as a Windows Service using NSSM.

.DESCRIPTION
  Runs uvicorn (the ASGI server) under NSSM so the app starts automatically with
  the server and restarts on failure. The service runs from the backend folder so
  it reads backend\.env, and listens on the chosen port over the LAN.

  Prerequisites:
    * Python 3.11+ installed, with a virtualenv created and requirements installed.
    * NSSM available (download the single nssm.exe from https://nssm.cc/download).
    * backend\.env created from deploy\.env.production.example.
    * Database initialised:  python manage.py all   (see DEPLOY-WINDOWS.md)

.EXAMPLE
  .\install-service.ps1 -BackendDir C:\Evavo\evavo-quotation\backend `
      -PythonExe C:\Evavo\evavo-quotation\backend\.venv\Scripts\python.exe `
      -NssmExe C:\Tools\nssm\nssm.exe -Port 8000 -Workers 2
#>
param(
  [Parameter(Mandatory = $true)][string]$BackendDir,
  [Parameter(Mandatory = $true)][string]$PythonExe,
  [Parameter(Mandatory = $true)][string]$NssmExe,
  [string]$ServiceName = "EvavoQuotation",
  [int]$Port = 8000,
  [int]$Workers = 2
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) { throw "Python not found: $PythonExe" }
if (-not (Test-Path $NssmExe))   { throw "nssm.exe not found: $NssmExe (download from https://nssm.cc)" }
if (-not (Test-Path (Join-Path $BackendDir "app\main.py"))) { throw "BackendDir doesn't look like the app: $BackendDir" }
if (-not (Test-Path (Join-Path $BackendDir ".env"))) {
  Write-Warning "backend\.env not found. Copy deploy\.env.production.example to $BackendDir\.env before starting."
}

$logDir = Join-Path $BackendDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$uvicornArgs = "-m uvicorn app.main:app --host 0.0.0.0 --port $Port --workers $Workers"

# Remove any prior install so this is idempotent.
& $NssmExe stop $ServiceName 2>$null
& $NssmExe remove $ServiceName confirm 2>$null

& $NssmExe install $ServiceName $PythonExe $uvicornArgs
& $NssmExe set $ServiceName AppDirectory $BackendDir
& $NssmExe set $ServiceName DisplayName "Evavo Quotation Platform"
& $NssmExe set $ServiceName Description "Evavo cloud quotation platform (FastAPI/uvicorn)"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout (Join-Path $logDir "service.out.log")
& $NssmExe set $ServiceName AppStderr (Join-Path $logDir "service.err.log")
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760

& $NssmExe start $ServiceName

Write-Host ""
Write-Host "Service '$ServiceName' installed and started on port $Port." -ForegroundColor Green
Write-Host "Test locally:  curl http://localhost:$Port/health"
Write-Host "From the LAN:  http://<server-ip>:$Port/"
Write-Host "Open the firewall if needed:"
Write-Host "  New-NetFirewallRule -DisplayName 'Evavo $Port' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow"
