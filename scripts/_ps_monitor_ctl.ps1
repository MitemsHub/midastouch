param(
    [Parameter(Mandatory = $true)][string]$Action  # status | restart
)
$ErrorActionPreference = "SilentlyContinue"
$py = "C:\Users\USER\Desktop\Projects\Synthetic Indices Bot\.venv\Scripts\python.exe"
$repo = "C:\Users\USER\Desktop\Projects\Synthetic Indices Bot"

function Get-MonitorProcs {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'lv_broker_monitor' }
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
