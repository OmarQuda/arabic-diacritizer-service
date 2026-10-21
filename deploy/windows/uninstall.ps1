#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param([string]$InstallDir = "$env:ProgramData\ArabicDiacritizer")
$ErrorActionPreference = 'Stop'
$Wrapper = Join-Path ([System.IO.Path]::GetFullPath($InstallDir)) 'diacritizer.exe'
if (Get-Service -Name ArabicDiacritizer -ErrorAction SilentlyContinue) {
    Stop-Service -Name ArabicDiacritizer
    (Get-Service -Name ArabicDiacritizer).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    & $Wrapper uninstall
    if ($LASTEXITCODE -ne 0) { throw 'WinSW uninstall failed.' }
}
Get-NetFirewallRule -Name ArabicDiacritizer-ASPNET -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host 'Service and its named firewall rule removed. Deployment files, .env and correction data retained.'
