#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ASPNET_HOST_IP,
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [string]$InstallDir = "$env:ProgramData\ArabicDiacritizer"
)
$ErrorActionPreference = 'Stop'

# An empty pin blocks installation until the artifact is independently verified.
$WinSWSha256 = ''
$WinSWUrl = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe'
if ($WinSWSha256 -notmatch '^[A-Fa-f0-9]{64}$') {
    throw 'Pin an independently verified WinSW v2.12.0 x64 SHA256 in install.ps1 before running. Nothing installed.'
}
$null = [System.Net.IPAddress]::Parse($ASPNET_HOST_IP)
$SourceDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$TargetDir = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$MachineRoot = [System.IO.Path]::GetFullPath($env:ProgramData).TrimEnd('\') + '\'
if (-not $TargetDir.StartsWith($MachineRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'InstallDir must be a subdirectory of ProgramData, never a user profile.'
}
if ($TargetDir.Equals($SourceDir, [StringComparison]::OrdinalIgnoreCase)) { throw 'Deploy to a separate directory.' }
if (Get-Service -Name ArabicDiacritizer -ErrorAction SilentlyContinue) {
    throw 'Service already exists. Follow the documented update procedure.'
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
if ($PythonExe.StartsWith([System.IO.Path]::GetFullPath($env:USERPROFILE), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use an all-users Python installation, not Python from a user profile.'
}
if (-not (Test-Path -LiteralPath (Join-Path $SourceDir '.env'))) {
    throw 'Create and configure the source .env before deployment.'
}
$UvExe = (Get-Command uv -CommandType Application).Source
function Assert-Native([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
# SIDs avoid language-dependent account names: SYSTEM, Administrators, LocalService.
# Set a protected, exact ACL before placing credentials or executable code here.
$Acl = New-Object System.Security.AccessControl.DirectorySecurity
$Acl.SetAccessRuleProtection($true, $false)
foreach ($Grant in @(@('S-1-5-18', 'FullControl'), @('S-1-5-32-544', 'FullControl'), @('S-1-5-19', 'ReadAndExecute'))) {
    $Sid = New-Object System.Security.Principal.SecurityIdentifier($Grant[0])
    $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule($Sid, $Grant[1], 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $Acl.AddAccessRule($Rule)
}
Set-Acl -LiteralPath $TargetDir -AclObject $Acl
foreach ($Name in @('app', 'pyproject.toml', 'uv.lock', '.env')) {
    Copy-Item -LiteralPath (Join-Path $SourceDir $Name) -Destination $TargetDir -Recurse -Force
}
if (Test-Path -LiteralPath (Join-Path $SourceDir 'static\index.html')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir 'static') | Out-Null
    Copy-Item -LiteralPath (Join-Path $SourceDir 'static\index.html') -Destination (Join-Path $TargetDir 'static\index.html') -Force
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'diacritizer.xml') -Destination $TargetDir -Force
foreach ($Name in @('data', 'logs')) {
    $Directory = Join-Path $TargetDir $Name
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    & icacls.exe $Directory /grant '*S-1-5-19:(OI)(CI)M' | Out-Null
    Assert-Native "ACL for $Name"
}
# Reset the copied .env ACL to inherit only the protected parent ACL.
& icacls.exe (Join-Path $TargetDir '.env') /reset | Out-Null
Assert-Native '.env ACL'

$SavedCache = $env:UV_CACHE_DIR
$SavedVenv = $env:UV_PROJECT_ENVIRONMENT
$SavedDownload = $env:UV_PYTHON_DOWNLOADS
try {
    $env:UV_CACHE_DIR = Join-Path $TargetDir '.uv-cache'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $TargetDir '.venv'
    $env:UV_PYTHON_DOWNLOADS = 'never'
    Push-Location $TargetDir
    try {
        & $UvExe sync --locked --no-dev --python $PythonExe
        Assert-Native 'uv sync'
    } finally { Pop-Location }
} finally {
    $env:UV_CACHE_DIR = $SavedCache
    $env:UV_PROJECT_ENVIRONMENT = $SavedVenv
    $env:UV_PYTHON_DOWNLOADS = $SavedDownload
}

# Download only on explicit installation, only from the official pinned release.
$Download = Join-Path $TargetDir 'diacritizer.download'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -UseBasicParsing -Uri $WinSWUrl -OutFile $Download
$ActualHash = (Get-FileHash -LiteralPath $Download -Algorithm SHA256).Hash
if ($ActualHash -ne $WinSWSha256) {
    Remove-Item -LiteralPath $Download -Force
    throw 'WinSW SHA256 mismatch. Service was not installed.'
}
$Wrapper = Join-Path $TargetDir 'diacritizer.exe'
Move-Item -LiteralPath $Download -Destination $Wrapper -Force

# Loopback is intentional. This rule alone does not grant remote access to a loopback listener.
# Windows firewall must have default inbound Block and no broader allow rules for this port.
if (Get-NetFirewallRule -Name ArabicDiacritizer-ASPNET -ErrorAction SilentlyContinue) {
    throw 'Existing firewall rule found. Inspect it before installing.'
}
$BlockingProfiles = Get-NetFirewallProfile | Where-Object { -not $_.Enabled -or $_.DefaultInboundAction -ne 'Block' }
if ($BlockingProfiles) { throw 'Enable Windows Firewall and default inbound Block for all profiles before installing.' }
New-NetFirewallRule -Name ArabicDiacritizer-ASPNET -DisplayName 'Arabic Diacritizer from ASP.NET only' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8020 -RemoteAddress $ASPNET_HOST_IP `
    -Program (Join-Path $TargetDir '.venv\Scripts\python.exe') -Profile Any | Out-Null
& $Wrapper install
Assert-Native 'WinSW install'
& $Wrapper start
Assert-Native 'WinSW start'
Write-Host "Installed ArabicDiacritizer in $TargetDir. Run verify.ps1 next."
