<#
.SYNOPSIS  Create a virtualenv and install backend dependencies.
.EXAMPLE   .\setup.ps1 -BackendDir C:\Evavo\evavo-quotation\backend
#>
param(
  [Parameter(Mandatory = $true)][string]$BackendDir,
  [string]$PythonExe = "python"
)
$ErrorActionPreference = "Stop"
Set-Location $BackendDir

& $PythonExe -m venv .venv
$venvPy = Join-Path $BackendDir ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt

Write-Host ""
Write-Host "Virtualenv ready at $BackendDir\.venv" -ForegroundColor Green
Write-Host "Python for the service:  $venvPy"
Write-Host "Next: copy deploy\.env.production.example to backend\.env and edit it,"
Write-Host "      then run:  $venvPy manage.py all"
