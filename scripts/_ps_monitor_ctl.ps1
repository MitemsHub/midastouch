param(
    [Parameter(Mandatory = $true)][string]$Action  # status | restart
)
$ErrorActionPreference = "SilentlyContinue"

# REPOINTED 2026-09-21, same defect as _ps_deploy_ctl.ps1: the interpreter and the
# working directory named the predecessor checkout, while the script it manages
# (scripts\midas_lv_broker_monitor.py) lives HERE. A control script that targets the
# wrong tree reports "0 running" about a program that is not this one, which reads
# exactly like "nothing to see".
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

function Get-MonitorProcs {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'midas_lv_broker_monitor' }
}

switch ($Action) {
    "status" {
        $p = Get-MonitorProcs
        Write-Output ("count=" + @($p).Count)
        $p | ForEach-Object { Write-Output ("pid=" + $_.ProcessId) }
    }
    "restart" {
        Get-MonitorProcs | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force
            Write-Output ("stopped " + $_.ProcessId)
        }
        Start-Sleep -Seconds 1
        Start-Process -FilePath $py `
            -ArgumentList "scripts/midas_lv_broker_monitor.py", "--loop", "60" `
            -WorkingDirectory $repo -WindowStyle Hidden
        Start-Sleep -Seconds 4
        $p = Get-MonitorProcs
        Write-Output ("now_running=" + @($p).Count)
        $p | ForEach-Object { Write-Output ("pid=" + $_.ProcessId) }
    }
}
