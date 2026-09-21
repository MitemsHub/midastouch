param(
    [Parameter(Mandatory = $true)][string]$Action  # status | restart
)
$ErrorActionPreference = "SilentlyContinue"

# REPOINTED 2026-09-21. This helper used to hardcode the predecessor checkout
# ("C:\Users\USER\Desktop\Projects\Synthetic Indices Bot") for both the interpreter
# and the working directory, so `restart` either failed on a venv that does not exist
# or -- where that checkout still holds a copy of the module -- started the OTHER
# program's deploy loop from the wrong tree. The script it manages,
# scripts\midas_deploy_v118.py, lives HERE. So does the interpreter: resolve a
# repo-local .venv if one is ever created, otherwise the system python, and never
# another project's venv (its src\ would land on the import path -- the
# cross-repository load tests\test_local_imports.py exists to prevent).
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

function Get-DeployProcs {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'midas_deploy_v118' }
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
