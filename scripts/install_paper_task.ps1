<#
.SYNOPSIS
    Register (or show) the Windows scheduled task that supervises the MIDASTOUCH gold
    arm UNATTENDED.

.DESCRIPTION
    Runs scripts/paper_supervisor.cmd every N minutes, around the clock, **whether or not
    anyone is signed in**. It is deliberately NOT scheduled at "the gold open": the
    supervisor itself checks whether the market is open (by tick freshness) and exits 0
    silently when it is not, so the trigger needs no timezone arithmetic and cannot drift
    when the venue changes its session times. A closed market produces no alerts --
    verified: a weekend run prints "market closed" and exits 0.

    WHY THIS CHANGED ON 2026-09-22 (the file name is history; the task is not paper-scoped
    and never was "paper-only" in the sense that mattered). MEASURED from the supervisor's
    own log: over 25.3 h the previous configuration produced 54 passes where a 20-minute
    cadence owes 76, with ZERO passes in the 01:00-06:00 UTC hours and a single gap of 407
    minutes. The task was Ready, its last run was minutes old, and the arm was unguarded
    for most of a night -- because the principal was Interactive, i.e. it runs only while
    a user is signed in, and the arm's market hours are exactly the hours nobody is. So:

      * LogonType S4U   -> "run whether or not the user is signed on". This is the fix.
      * a BootTrigger   -> supervision begins at power-on with nobody signed in, and
                           survives the reboot that reaps everything else.
      * -WakeToRun      -> a sleeping host runs no task, and a task that cannot start
                           writes no log line either, so the night reads like a quiet
                           market.
      * ExecutionTimeLimit 0 -> a pass that hangs on a terminal query is not killed
                           mid-restart.

    THE HOST STILL HAS TO HOLD UP ITS END, and that is not something this installer can
    assume: measured here, "Allow wake timers" is DISABLED and the only standby state is S0
    Low Power Idle, so a WakeToRun task cannot wake this laptop and its lid policy is not
    even exposed by powercfg. The installer therefore PRINTS the posture (via
    scripts/host_power.py) and refuses to call the result unattended; the arm's home for
    unattended operation is a host with no lid and no user session to lose.

    Default is a DRY RUN that prints the exact command. Pass -Apply to register.

    This task runs a supervisor. It places no orders and it arms nothing: arming is an
    arming-record event (artifacts/live/armed.json), and neither this installer, the
    supervisor nor the watchdog it calls contains an order-sending path.

.PARAMETER Apply
    Actually create the task, and unregister the legacy interactive supervisor
    (MitemshubPaperSupervisor) it replaces. Without it, nothing is changed.

.PARAMETER EveryMinutes
    Repetition interval. 20 minutes is enough to catch a newly closed M15 bar, and it must
    match live_coverage.CADENCE_MIN -- the coverage alarm is stated relative to it.

.PARAMETER Unregister
    Remove the task and exit.

.PARAMETER KeepLegacy
    Register the new task but KEEP the legacy interactive one, so both supervise for a
    trial period. This is the honest option while the arm is LIVE-armed: an Interactive
    task runs in the signed-in desktop session, where the watchdog's stop-and-relaunch of
    the MT5 GUI is demonstrably able to work, and whether an S4U task can do the same is
    UNVERIFIED. Remove the legacy task once a pass from the new one is on the record
    (artifacts/live/supervision_heartbeat.jsonl).

.PARAMETER TaskName
    Defaults to "MIDASTOUCH Arm Supervisor".

.EXAMPLE
    powershell -NoProfile -File scripts/install_paper_task.ps1
    powershell -NoProfile -File scripts/install_paper_task.ps1 -Apply
    powershell -NoProfile -File scripts/install_paper_task.ps1 -Unregister
#>
param(
    [switch]$Apply,
    [switch]$Unregister,
    [switch]$KeepLegacy,
    [int]$EveryMinutes = 20,
    [string]$TaskName = "MIDASTOUCH Arm Supervisor",
    [string]$LegacyTaskName = "MitemshubPaperSupervisor"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$wrapper = Join-Path $PSScriptRoot "paper_supervisor.cmd"
$user = "$env:USERDOMAIN\$env:USERNAME"

# The interpreter: a repo-local .venv if one ever exists, else the system python. Never
# another checkout's venv -- that would put a sibling project's src/ on the import path
# (the same rule the .cmd wrapper follows, enforced by tests/test_launcher_paths.py).
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

function Invoke-UnattendedReport([string]$name) {
    Write-Host ""
    Write-Host "Unattended check (the scheduler's own XML, not this script's intent):"
    & $py (Join-Path $PSScriptRoot "unattended.py") $name
    Write-Host ""
    Write-Host "Host power posture (a scheduled pass that cannot wake the host does not happen):"
    & $py (Join-Path $PSScriptRoot "host_power.py")
}

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "UNREGISTERED: $TaskName"
    } else {
        Write-Host "NOT PRESENT: $TaskName (nothing to remove)"
    }
    exit 0
}

Write-Host "=== MIDASTOUCH ARM SUPERVISOR - SCHEDULED TASK ==="
Write-Host "  project root : $root"
Write-Host "  wrapper      : $wrapper"
Write-Host "  task name    : $TaskName"
Write-Host "  principal    : $user (S4U - runs whether or not the user is signed on)"
Write-Host "  triggers     : at startup + every $EveryMinutes minutes, indefinitely, wake-to-run"
Write-Host "  repeating    : $EveryMinutes min (live_coverage.CADENCE_MIN)"

if (-not (Test-Path $wrapper)) {
    Write-Host "REFUSING: wrapper not found at $wrapper" -ForegroundColor Red
    exit 2
}

# Probing for an existing task MUST NOT be fatal. schtasks writes "cannot find the
# file specified" to stderr for an unregistered task, and with
# $ErrorActionPreference = "Stop" PowerShell promotes native-command stderr into a
# terminating error -- so the probe for a task that does not exist yet aborted the
# installer. The exit code is the signal; the text is noise.
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$legacy = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue
$ErrorActionPreference = $prev
if ($legacy) {
    Write-Host "  NOTE: the legacy interactive task '$LegacyTaskName' exists" -ForegroundColor Yellow
    Write-Host "        (logon=$($legacy.Principal.LogonType)). -Apply replaces it with this one."
}

if (-not $Apply) {
    Write-Host ""
    Write-Host "DRY RUN. To register, re-run with -Apply. It would register:"
    Write-Host ""
    # Single-quoted everywhere the text contains PowerShell metacharacters ($, "): a
    # double-quoted string interpolates $true into the word True, so the printed command
    # would not be the command - and a dry run whose printout is wrong is worse than no
    # dry run, because it is what gets re-typed.
    Write-Host ('  Register-ScheduledTask -TaskName ''' + $TaskName + ''' -Xml <definition> -Force')
    Write-Host ''
    Write-Host '  ...whose XML says (a task XML, NOT the cmdlets: MEASURED 2026-09-22, this'
    Write-Host '     module''s trigger objects cannot express WakeToRun at all - the property is'
    Write-Host '     simply absent, and setting it throws):'
    Write-Host '    <LogonType>S4U</LogonType>                      (runs whether or not signed in)'
    Write-Host '    <BootTrigger>                                   (boot, with nobody signed in)'
    Write-Host ('    <Repetition><Interval>PT' + $EveryMinutes + 'M</Interval>        (the pinned cadence)')
    Write-Host '    <WakeToRun>true</WakeToRun>                      (a sleeping host runs nothing)'
    Write-Host '    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>    (no kill mid-restart)'
    Write-Host ('    <Command>cmd.exe</Command> <Arguments>/c "' + $wrapper + '"</Arguments>')
    Write-Host ''
    Write-Host '  (the schtasks equivalent fails on this path because it contains a space:'
    Write-Host ('   schtasks /Create /TN "' + $TaskName + '" /TR "cmd /c "' + $wrapper + '"" /SC MINUTE /MO ' + $EveryMinutes + ' /F) - and it cannot express WakeToRun either')
    Write-Host '  ...and it would remove the legacy interactive task, if present:'
    Write-Host ('      Unregister-ScheduledTask -TaskName ''' + $LegacyTaskName + ''' -Confirm:$false')
    Write-Host '      (pass -KeepLegacy to run BOTH for a trial night and remove the old one later)'
    Write-Host ""
    Write-Host "To remove it later:  powershell -NoProfile -File scripts/install_paper_task.ps1 -Unregister"
    Write-Host "Needs an ELEVATED shell (S4U: 'run whether or not the user is signed on')."
    Invoke-UnattendedReport $TaskName
    exit 0
}

Write-Host ""

# WHY THE TASK IS REGISTERED FROM XML AND NOT FROM THE CMDLETS.
# MEASURED 2026-09-22 on this machine: `New-ScheduledTaskTrigger -Once` has no -WakeToRun
# parameter, and the trigger objects the ScheduledTasks module hands back expose exactly
# {Enabled, EndBoundary, ExecutionTimeLimit, Id, Repetition, StartBoundary, RandomDelay} --
# `$trigger.WakeToRun = $true` fails with "The property 'WakeToRun' cannot be found on this
# object". The first version of this installer did exactly that, swallowed the non-
# terminating error, and then printed "Registered" over a task that had NOT been created.
# A registration that cannot express "wake the host" is not the task this program needs,
# so the definition is written as the Task Scheduler's own XML -- the same artifact
# scripts/unattended.py reads back to verify it.
# The section order and the element shapes below mirror what THIS scheduler writes itself:
# `Export-ScheduledTask` on the legacy task returns RegistrationInfo, Principals, Settings,
# Triggers, Actions, a TimeTrigger holding StartBoundary then Repetition (and NOTHING else),
# and <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>. MEASURED 2026-09-22 while
# getting this wrong twice: a <WakeToRun> child of <TimeTrigger> is rejected outright --
# "The task XML contains an unexpected node ... (15,9):WakeToRun" -- so the wake flag lives
# in <Settings>, which is where a "wake the computer to run this task" task carries it.
#
# AND THE <Settings> CHILDREN HAVE A REQUIRED ORDER -- MEASURED 2026-09-22 on the first real
# -Apply: with them in a merely sensible order the registration was REFUSED -- "The task XML
# contains an unexpected node ... (32,7):UseUnifiedSchedulingEngine" -- and the installer fell
# back to the cmdlet path, which CANNOT express WakeToRun. The task then existed, ran on its
# cadence, and would have stayed silent on a sleeping host: the leg this whole installer exists
# for was the one silently lost, and the only reason it was caught is that the installer reads
# the scheduler's XML back and refuses to call the result a pass. The order below is the
# schema's: AllowStartOnDemand first, then the policies, then WakeToRun, then Enabled/Hidden,
# then IdleSettings, then ExecutionTimeLimit/Priority/RunOnlyIfIdle, then
# UseUnifiedSchedulingEngine last. If a future edit reorders these, WakeToRun disappears again.
$start = (Get-Date).AddMinutes(1).ToString("yyyy-MM-ddTHH:mm:sszzz")
$esc = [System.Security.SecurityElement]::Escape($wrapper)
$desc = ("Supervises the MIDASTOUCH gold arm whether or not anyone is signed in " +
         "(scripts/paper_supervisor.py). It is scoped to the ARM, not to a paper run: it " +
         "supervises whichever preset the arming record names. It places no orders.")
$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$user</Author>
    <Description>$desc</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>$user</UserId>
      <LogonType>S4U</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <WakeToRun>true</WakeToRun>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
  </Settings>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT1M</Delay>
    </BootTrigger>
    <TimeTrigger>
      <StartBoundary>$start</StartBoundary>
      <Repetition>
        <Interval>PT$($EveryMinutes)M</Interval>
        <Duration>P3650D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c "$esc"</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

# TRY THE XML IN PROGRESSIVELY SMALLER FORMS, and report which one this scheduler accepts.
# WHY A CHAIN AND NOT ONE GUESS. MEASURED 2026-09-22: this machine's scheduler rejects
# `<UseUnifiedSchedulingEngine>` with "The task XML contains an unexpected node ...
# (32,7):UseUnifiedSchedulingEngine" even in the position the published schema documents for
# it -- and the first fix (reordering the whole <Settings> block to that schema) changed the
# line number and nothing else. Guessing one element per attempt costs an elevated round trip
# and can lose the wake flag again, so the optional nodes are dropped ONE AT A TIME until the
# scheduler takes the definition, and the variant that was accepted is printed. The nodes below
# are the only ones this task does not need: `UseUnifiedSchedulingEngine` (an engine-selection
# hint, irrelevant to a boot trigger plus a repetition), `IdleSettings` (the task is explicitly
# NOT idle-gated -- RunOnlyIfIdle is false), and `Hidden`/`Enabled` (cosmetic; a registered task
# is enabled by default and this one is never hidden). `WakeToRun`, the S4U principal, the boot
# trigger and the repetition are NEVER dropped: a task without them is not the task.
$optionalNodes = @(
    @{ name = 'UseUnifiedSchedulingEngine'; re = '(?m)^\s*<UseUnifiedSchedulingEngine>.*?</UseUnifiedSchedulingEngine>\r?\n' },
    @{ name = 'IdleSettings'; re = '(?ms)^\s*<IdleSettings>.*?</IdleSettings>\r?\n' },
    @{ name = 'Hidden'; re = '(?m)^\s*<Hidden>.*?</Hidden>\r?\n' },
    @{ name = 'Enabled'; re = '(?m)^\s*<Enabled>.*?</Enabled>\r?\n' }
)
$variants = @()
$variants += @{ label = 'as written'; xml = $taskXml }
$trimmed = $taskXml
$dropped = @()
foreach ($node in $optionalNodes) {
    $trimmed = [regex]::Replace($trimmed, $node.re, '')
    $dropped += $node.name
    $variants += @{ label = ('without ' + ($dropped -join ', ')); xml = $trimmed }
}

$accepted = $null
$refusals = @()
foreach ($v in $variants) {
    try {
        Register-ScheduledTask -TaskName $TaskName -Xml $v.xml -Force -ErrorAction Stop | Out-Null
        $accepted = $v.label
        break
    } catch {
        $refusals += "$($v.label): $($_.Exception.Message)"
    }
}
if ($null -ne $accepted -and $accepted -ne 'as written') {
    Write-Host "XML registration accepted in a REDUCED form: $accepted" -ForegroundColor Yellow
    Write-Host "  the scheduler refused the fuller definition(s):"
    foreach ($r in $refusals) { Write-Host "    $r" }
    Write-Host "  WakeToRun is still carried by the accepted form; scripts/unattended.py reads"
    Write-Host "  the scheduler's own XML back and is the thing to trust, not this line."
}
$wakeExpressed = $null -ne $accepted
if (-not $wakeExpressed) {
    Write-Host "XML registration refused in every form:" -ForegroundColor Yellow
    foreach ($r in $refusals) { Write-Host "    $r" }

    # FAIL-SOFT, AND LOUD ABOUT IT -- but only after EVERY XML form was refused (the blocks
    # above), because the cmdlet path cannot express the wake flag: the unattended part of the
    # requirement (S4U + boot trigger + cadence) is still worth having, so it is registered
    # through the cmdlets -- the shape the legacy task proves this module can produce -- and the
    # missing leg is REPORTED, never assumed. A registration that silently drops "wake the host"
    # is a task that does not run at 03:00 and says nothing, which is the failure being fixed.
    Write-Host "Falling back to the cmdlet registration, WITHOUT wake-to-run." -ForegroundColor Yellow
    $wakeExpressed = $false
    $fbAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$wrapper`""
    $fbBoot = New-ScheduledTaskTrigger -AtStartup
    $fbRepeat = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
        -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $fbSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $fbPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $fbAction `
            -Trigger $fbBoot, $fbRepeat -Settings $fbSettings -Principal $fbPrincipal `
            -Description $desc -Force -ErrorAction Stop | Out-Null
    } catch {
        Write-Host "FAILED to register: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        Write-Host "S4U registration ('run whether or not the user is signed on') needs an"
        Write-Host "ELEVATED shell - measured 2026-09-22 as 'Access is denied' (0x80070005)."
        Write-Host "Nothing was changed. Re-run this exact command from an administrator prompt:"
        Write-Host ""
        Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Apply"
        exit 5
    }
}
$ErrorActionPreference = $prev

# VERIFY, THEN SAY IT. The registration above is not trusted to have worked because it did
# not throw: the task is read back from the scheduler, and if it is not there this exits
# non-zero WITHOUT touching the legacy task. The earlier version of this script printed
# "Registered. Current state:" and then let the following Get-ScheduledTask fail with
# "No MSFT_ScheduledTask objects found" - a report that lied about the one thing it was run
# to do, which is the failure class this whole change exists to remove.
$made = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $made) {
    Write-Host "REFUSING to report success: $TaskName is not registered after the call." -ForegroundColor Red
    Write-Host "The legacy task was left untouched. Investigate before re-running."
    exit 5
}

Write-Host "Registered and read back from the scheduler:"
$made | Select-Object TaskName, State | Format-List
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object LastRunTime, NextRunTime, NumberOfMissedRuns | Format-List
if (-not $wakeExpressed) {
    Write-Host ""
    Write-Host "WARNING: wake-to-run is NOT set on this task (this scheduler refused the XML" -ForegroundColor Yellow
    Write-Host "that carries it). The task runs whether or not anyone is signed in, but it will" -ForegroundColor Yellow
    Write-Host "not wake a sleeping host: python scripts/unattended.py will report the missing" -ForegroundColor Yellow
    Write-Host "leg rather than a pass, and live_readiness stays red. Do not read a quiet night as" -ForegroundColor Yellow
    Write-Host "a healthy one until that leg is green." -ForegroundColor Yellow
}

if ($legacy -and -not $KeepLegacy) {
    # The replaced task is unregistered only AFTER the replacement is in place: the other
    # order has a window with no supervisor at all, and this change exists because
    # windows with no supervisor are the failure being fixed.
    Unregister-ScheduledTask -TaskName $LegacyTaskName -Confirm:$false
    Write-Host "Removed the legacy interactive task: $LegacyTaskName"
} elseif ($legacy) {
    # -KeepLegacy: run both for a trial period. This is the honest default for an arm that
    # is already LIVE-armed -- an Interactive task runs in the signed-in desktop session,
    # where the watchdog's stop-and-relaunch of the MT5 GUI is demonstrably able to work,
    # and whether an S4U task can do the same is UNVERIFIED. Both are one-pass supervisors;
    # the watchdog's instance lock guards the loops, not these, and the two schedules sit
    # minutes apart, so a pass from each is two reads of the same state, not a race.
    Write-Host "KEPT the legacy task: $LegacyTaskName (running both, ~minutes apart)." -ForegroundColor Yellow
    Write-Host "  remove it once a pass from the new task is on the record:"
    Write-Host "    Unregister-ScheduledTask -TaskName '$LegacyTaskName' -Confirm:`$false"
}

Write-Host "It writes to: $root\artifacts\live\supervisor.log (runs)"
Write-Host "              $root\artifacts\live\supervision_heartbeat.jsonl (one line per pass)"
Write-Host "              $root\artifacts\live\alerts.log (alarms only)"
Write-Host ""
Write-Host "Measure the night:  $py scripts\live_coverage.py            (the last complete night)"
Write-Host "                    $py scripts\live_coverage.py --hours 24"
Invoke-UnattendedReport $TaskName
Write-Host ""
Write-Host "NOTE: if the project folder is renamed, re-run this installer -- the task"
Write-Host "      holds an absolute path. scripts/rename_project.py prints this reminder."
