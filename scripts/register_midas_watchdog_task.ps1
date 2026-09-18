# Registers "MIDAS Watchdog Autostart" - a per-user logon task that launches
# start_midas_watchdog.bat, so the gold-arm watchdog survives reboots without
# anyone remembering to start it (the 2026-09-17 restart reaped the loop and
# the arms ran ~70 min unguarded; the closeout's operator routine #1 exists
# only because nothing automatic covered this).
#
# Design, per the program's constraints:
#   * USER session, interactive logon trigger - NOT the service session, NOT
#     highest privileges. The protocol (S12) says the watchdog must run from
#     the user's session; agent/service-owned processes get reaped and would
#     reintroduce the exact failure this fixes. No admin prompt needed.
#   * The task runs the CERTIFIED launcher (start_midas_watchdog.bat), never
#     python directly - the .bat stays the one audited entry point (cwd,
#     venv python, log redirection).
#   * Single-instance is enforced by the watchdog itself
#     (artifacts/midas_watchdog.lock, OS-handle-held): a logon task plus a
#     manual double-click cannot produce two loops - the loser exits loudly.
#   * Idempotent: re-running replaces the task with the same definition.
#   * -Unregister removes it (the off switch).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\register_midas_watchdog_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_midas_watchdog_task.ps1 -Unregister
param([switch]$Unregister)

$ErrorActionPreference = 'Stop'
$taskName = 'MIDAS Watchdog Autostart'
$repoRoot = Split-Path -Parent $PSScriptRoot   # repo root (parent of scripts\)
$bat = Join-Path $repoRoot 'start_midas_watchdog.bat'

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "UNREGISTERED: $taskName"
    } else {
        Write-Host "NOT PRESENT: $taskName (nothing to remove)"
    }
    exit 0
}

if (-not (Test-Path $bat)) { throw "launcher not found: $bat" }

$action    = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$bat`"" `
                                       -WorkingDirectory $repoRoot
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                                          -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
                       -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "REGISTERED: $taskName - runs start_midas_watchdog.bat at your logon (user session, no elevation)."
Write-Host "Verify:  Get-ScheduledTask -TaskName '$taskName' | Get-ScheduledTaskInfo"
Write-Host "Remove:  powershell -ExecutionPolicy Bypass -File scripts\register_midas_watchdog_task.ps1 -Unregister"
