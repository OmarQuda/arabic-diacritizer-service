#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:ProgramData\ArabicDiacritizer",
    [int]$TimeoutSeconds = 90,
    [switch]$AfterReboot
)
$ErrorActionPreference = 'Stop'
$TargetDir = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$HealthUri = 'http://127.0.0.1:8020/health/live'
function Get-Worker {
    $ServiceInfo = Get-CimInstance Win32_Service -Filter "Name='ArabicDiacritizer'"
    if (-not $ServiceInfo -or $ServiceInfo.State -ne 'Running') { throw 'ArabicDiacritizer is not running.' }
    $Queue = New-Object 'System.Collections.Generic.Queue[uint32]'
    $Queue.Enqueue([uint32]$ServiceInfo.ProcessId)
    $Workers = @()
    while ($Queue.Count -gt 0) {
        $ParentId = $Queue.Dequeue()
        foreach ($Child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId")) {
            $Queue.Enqueue([uint32]$Child.ProcessId)
            if ($Child.Name -eq 'python.exe' -and $Child.CommandLine -like '*-m uvicorn app.main:app*') {
                $Workers += $Child
            }
        }
    }
    if ($Workers.Count -eq 0) { throw 'No uvicorn Python descendant of the named service found.' }
    return $Workers
}
function Test-Live {
    try {
        $Result = Invoke-RestMethod -Uri $HealthUri -TimeoutSec 2
        return $Result.status -eq 'ok'
    } catch { return $false }
}
if (-not (Test-Live)) { throw 'Initial live health check failed.' }
$WorkerList = @(Get-Worker)
$WrapperProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$((Get-CimInstance Win32_Service -Filter "Name='ArabicDiacritizer'").ProcessId)"
$ExpectedWrapper = Join-Path $TargetDir 'diacritizer.exe'
if (-not $WrapperProcess.ExecutablePath -or -not $WrapperProcess.ExecutablePath.Equals($ExpectedWrapper, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Service executable does not match InstallDir. Refusing to kill anything.'
}
if ($AfterReboot) {
    $Boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $Started = $WrapperProcess.CreationDate
    if ($Started -lt $Boot) { throw 'Service process predates this boot.' }
    $Info = Get-CimInstance Win32_Service -Filter "Name='ArabicDiacritizer'"
    $Registry = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\ArabicDiacritizer'
    if ($Info.StartMode -ne 'Auto' -or $Registry.DelayedAutoStart -ne 1) { throw 'Automatic delayed startup is not configured.' }
    Write-Host "Boot time: $($Boot.ToString('o'))"
    Write-Host "Service process start: $($Started.ToString('o'))"
    Write-Host ('Boot to service process: {0:N2} seconds' -f ($Started - $Boot).TotalSeconds)
    Write-Host 'Up after reboot: PASS (live now; process times alone cannot exclude a manual start).'
    exit 0
}
$OldIds = @($WorkerList | ForEach-Object { [uint32]$_.ProcessId })
$Timer = [Diagnostics.Stopwatch]::StartNew()
# Windows venv launchers may spawn another Python. Kill only verified descendants, deepest first.
[array]::Reverse($WorkerList)
foreach ($Worker in $WorkerList) {
    Stop-Process -Id $Worker.ProcessId -Force -ErrorAction SilentlyContinue
}
$Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
while ([DateTime]::UtcNow -lt $Deadline) {
    Start-Sleep -Milliseconds 250
    if (Test-Live) {
        try {
            $NewWorkers = @(Get-Worker)
            if (@($NewWorkers | Where-Object { $OldIds -contains [uint32]$_.ProcessId }).Count -eq 0) {
                $Timer.Stop()
                Write-Host ('Restart after kill: {0:N2} seconds; /health/live=ok; new Python PID(s): {1}' -f $Timer.Elapsed.TotalSeconds, ($NewWorkers.ProcessId -join ','))
                exit 0
            }
        } catch { }
    }
}
throw "Health did not recover with new service-owned Python processes within $TimeoutSeconds seconds."
