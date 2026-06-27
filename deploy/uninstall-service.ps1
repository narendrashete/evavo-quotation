<#
.SYNOPSIS  Stop and remove the Evavo Quotation Platform Windows Service.
.EXAMPLE   .\uninstall-service.ps1 -NssmExe C:\Tools\nssm\nssm.exe
#>
param(
  [Parameter(Mandatory = $true)][string]$NssmExe,
  [string]$ServiceName = "EvavoQuotation"
)
$ErrorActionPreference = "Continue"
& $NssmExe stop $ServiceName
& $NssmExe remove $ServiceName confirm
Write-Host "Service '$ServiceName' removed." -ForegroundColor Green
