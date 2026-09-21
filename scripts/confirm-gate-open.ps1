# confirm-gate-open.ps1 — FAIL-CLOSED REWRITE 2026-09-19 (stale-flag sweep).
#
# WHY THIS WAS REWRITTEN (the false green):
#   The original hardcoded terminal dir FB9A56D617EDDDFE29EE54EBEFFE96C1, read
#   that terminal's journal for the EA's init/gate lines, then reported the
#   cblearn state. Two independent things have since ended that era:
#     * FB9A56D617EDDDFE29EE54EBEFFE96C1 no longer exists on this machine
#       (live dirs: 49E0383C + 71BF6B2A = Deriv-era, D0E8209F = Upcomers), so
#       Select-String read nothing and $hits came back EMPTY; and
#     * the learned CB spike gate itself was DELETED FROM THE EA (CHANGELOG:
#       "Deleted from the EA: every CB input ... the learned CB spike gate
#       (EWMA + MitemshubAI_cblearn persistence) ...").
#   The old script then fell through to its else branch and printed
#       "cblearn: no state files yet (fresh gate, OPEN until first trades)"
#   i.e. a FALSE GREEN asserting an OPEN gate, on a terminal that does not
#   exist, for a mechanism that is not in the EA. That is the same class of
#   stale assertion that docs/STALE_FLAG_AUDIT_20260919.md retires elsewhere.
#
# WHAT IT DOES NOW: it refuses to assert anything it cannot evidence.
#   It resolves the terminal through the SHARED resolver, requires today's
#   journal, and exits non-zero unless it actually found the EA's init/gate
#   lines. The cblearn leg is reported as RETIRED rather than OPEN.
#
# WHY IT DELEGATES (2026-09-19, second pass). This script used to re-implement
#   resolution in PowerShell -- `Get-ChildItem $termRoot -Directory` and read
#   whichever install had a journal for today. That is a SECOND implementation of
#   the exact logic scripts/mt5_terminals.py exists to centralise, and it silently
#   missed the identity rule added there: installs are now identified by the
#   ACCOUNT NUMBER in their journals, and an install belonging to an account we no
#   longer trade is excluded. A hand-rolled scan cannot know that, so it would
#   read a dead Deriv-era install's journal and grade the gate from it. The module
#   docstring has always said "so the PowerShell tools can share this one
#   implementation"; this script did not. Now it does.
$logDate = (Get-Date).ToString("yyyyMMdd")
$termRoot = Join-Path $env:APPDATA "MetaQuotes\Terminal"

$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$resolver = Join-Path $PSScriptRoot "mt5_terminals.py"

$resolved = & $py $resolver --terminal 2>$null
if ($LASTEXITCODE -ne 0 -or -not $resolved) {
    Write-Host "FAIL: no MT5 terminal for the ACTIVE ACCOUNT could be resolved." -ForegroundColor Red
    if ($resolved) {
        foreach ($line in $resolved) { Write-Host ("      " + $line) -ForegroundColor DarkGray }
    }
    Write-Host "      Nothing here is evidence that the gate is OPEN - do not read it as such." -ForegroundColor Red
    exit 1
}

$td = ($resolved | Select-Object -Last 1).ToString().Trim()
$log = Join-Path $td "MQL5\Logs\$logDate.log"

if (-not (Test-Path $log)) {
    Write-Host "FAIL: the resolved terminal has no journal for $logDate." -ForegroundColor Red
    Write-Host "      Terminal: $td" -ForegroundColor DarkGray
    Write-Host ("      Installs present under " + $termRoot + ":") -ForegroundColor DarkGray
    foreach ($d in (Get-ChildItem -Path $termRoot -Directory -ErrorAction SilentlyContinue)) {
        Write-Host ("      - " + $d.Name) -ForegroundColor DarkGray
    }
    Write-Host "      Nothing here is evidence that the gate is OPEN - do not read it as such." -ForegroundColor Red
    exit 1
}

$found = $false
Write-Host ("log: " + $log)
$hits = Select-String -Path $log -ErrorAction SilentlyContinue `
    -Pattern "MITEMSHUB AI v26\.14 started|CB-SPIKE GATE|GATE re-evaluated|TICKFADE\] armed|BLOCKED"
if (-not $hits) {
    Write-Host "  (no EA init / gate lines in this journal today)" -ForegroundColor DarkGray
} else {
    $found = $true
    $hits | Select-Object -Last 14 | ForEach-Object { Write-Host ($_.Line -replace "`r", "") }
}
Write-Host ""

# The cblearn leg is RETIRED, not OPEN: the gate it reported on is not in the
# EA any more, so the absence of MitemshubAI_cblearn_*.csv is not evidence.
Write-Host "cblearn: RETIRED - the learned CB spike gate was deleted from the EA; absence of MitemshubAI_cblearn_*.csv is NOT evidence of an OPEN gate." -ForegroundColor Yellow

if (-not $found) {
    Write-Host "FAIL: journals exist but contain no EA init/gate evidence for $logDate - the gate is UNKNOWN, not OPEN." -ForegroundColor Red
    exit 1
}

Write-Host "OK: EA init/gate evidence found in today's journal." -ForegroundColor Green
exit 0
