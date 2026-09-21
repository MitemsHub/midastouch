<#
.SYNOPSIS
    Register (or show) the Windows scheduled task that supervises the paper trader.

.DESCRIPTION
    Runs scripts/paper_supervisor.cmd every N minutes, around the clock. It is
    deliberately NOT scheduled at "the gold open": the supervisor itself checks
    whether the market is open (by tick freshness) and exits 0 silently when it is
    not, so the trigger needs no timezone arithmetic and cannot drift when the venue
    changes its session times. A closed market produces no alerts -- verified: a
    weekend run prints "market closed" and exits 0.

    Default is a DRY RUN that prints the exact command. Pass -Apply to register.

    This task runs a PAPER-ONLY program. It cannot place an order: neither the
    supervisor nor the trader it invokes contains an order-sending path.

.PARAMETER Apply
    Actually create the task. Without it, nothing is changed.

.PARAMETER EveryMinutes
    Repetition interval. 20 minutes is enough to catch a newly closed M15 bar.

.EXAMPLE
    powershell -NoProfile -File scripts/install_paper_task.ps1
    powershell -NoProfile -File scripts/install_paper_task.ps1 -Apply
#>
param(
    [switch]$Apply,
    [int]$EveryMinutes = 20,
    [string]$TaskName = "MitemshubPaperSupervisor"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$wrapper = Join-Path $PSScriptRoot "paper_supervisor.cmd"

Write-Host "=== PAPER TRADER SCHEDULED TASK ==="
Write-Host "  project root : $root"
Write-Host "  wrapper      : $wrapper"
Write-Host "  task name    : $TaskName"
Write-Host "  interval     : every $EveryMinutes minutes, indefinitely"

if (-not (Test-Path $wrapper)) {
    Write-Host "REFUSING: wrapper not found at $wrapper" -ForegroundColor Red
    exit 2
}

$tr = "cmd /c `"$wrapper`""

# Probing for an existing task MUST NOT be fatal. schtasks writes "cannot find the
# file specified" to stderr for an unregistered task, and with
# $ErrorActionPreference = "Stop" PowerShell promotes native-command stderr into a
# terminating error -- so the probe for a task that does not exist yet aborted the
# installer. The exit code is the signal; the text is noise.
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$existing = schtasks /Query /TN $TaskName 2>&1
$hadExisting = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prev
if ($hadExisting) {
    Write-Host "  NOTE: a task with this name already exists and will be replaced." -ForegroundColor Yellow
    $existing | Select-Object -First 3 | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "  no existing task with this name."
}

# WHY NOT schtasks. The project path contains a space, so `schtasks /Create /TR
# "cmd /c "<path with spaces>""` needs three levels of quoting and fails with
#   ERROR: Invalid argument/option - 'C:\Users\USER\Desktop\Projects\Synthetic'
# -- measured, not assumed. The ScheduledTasks cmdlets take -Execute and -Argument
# separately, so the path is quoted exactly once and no nesting is required.
#
# No -RunLevel Elevation and no -User: it runs as the invoking user with normal
# rights, which is all a paper-only supervisor needs, and NOT asking for elevation
# means this can be registered without an administrator prompt.
$legacy = "schtasks /Create /TN `"$TaskName`" /TR `"$tr`" /SC MINUTE /MO $EveryMinutes /F"

if (-not $Apply) {
    Write-Host ""
    Write-Host "DRY RUN. To register, re-run with -Apply. It would run:"
    Write-Host ""
    Write-Host "  New-ScheduledTaskAction -Execute cmd.exe -Argument '/c \"$wrapper\"'"
    Write-Host "  New-ScheduledTaskTrigger -Once -At <now> -RepetitionInterval $EveryMinutes min"
    Write-Host "  Register-ScheduledTask -TaskName $TaskName -Force"
    Write-Host ""
    Write-Host "  (the schtasks equivalent fails on this path because it contains a space:"
    Write-Host "   $legacy)"
    Write-Host ""
    Write-Host "To remove it later:  Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
    exit 0
}

Write-Host ""
$ErrorActionPreference = "Continue"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$wrapper`""
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(2)) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "PAPER-ONLY supervisor for the Upcomers gold study (scripts/paper_supervisor.py). Sends no orders." | Out-Null
$rc = $LASTEXITCODE
if ($?) { $rc = 0 }
$ErrorActionPreference = $prev
if ($rc -ne 0) {
    Write-Host "FAILED to register (schtasks exit $rc)." -ForegroundColor Red
    Write-Host "If this was an access-denied error, register it from an elevated shell."
    exit $rc
}

Write-Host ""
Write-Host "Registered. Current state:"
$info = Get-ScheduledTask -TaskName $TaskName
$info | Select-Object TaskName, State | Format-List
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object LastRunTime, NextRunTime, NumberOfMissedRuns | Format-List
Write-Host ""
Write-Host "It writes to: $root\artifacts\live\supervisor.log (runs)"
Write-Host "              $root\artifacts\live\paper_daily.jsonl (summary per run)"
Write-Host "              $root\artifacts\live\alerts.log (alerts only)"
Write-Host ""
Write-Host "NOTE: if the project folder is renamed, re-run this installer -- the task"
Write-Host "      holds an absolute path. scripts/rename_project.py prints this reminder."
