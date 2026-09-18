param(
    [Parameter(Mandatory = $true)][string]$Action  # status | restart
)
$ErrorActionPreference = "SilentlyContinue"
$py = "C:\Users\USER\Desktop\Projects\Synthetic Indices Bot\.venv\Scripts\python.exe"
$repo = "C:\Users\USER\Desktop\Projects\Synthetic Indices Bot"

function Get-DeployProcs {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'deploy_v118' }
}

switch ($Action) {
    "status" {
        $p = Get-DeployProcs
        Write-Output ("count=" + @($p).Count)
        $p | ForEach-Object { Write-Output ("pid=" + $_.ProcessId) }
    }
    "restart" {
        Get-DeployProcs | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force
            Write-Output ("stopped " + $_.ProcessId)
        }
        Start-Sleep -Seconds 1
        Start-Process -FilePath $py `
            -ArgumentList "scripts/midas_deploy_v118.py", "--watch" `
            -WorkingDirectory $repo -WindowStyle Hidden
        Start-Sleep -Seconds 5
        $p = Get-DeployProcs
        Write-Output ("now_running=" + @($p).Count)
        $p | ForEach-Object { Write-Output ("pid=" + $_.ProcessId) }
    }
}
