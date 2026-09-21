@echo off
rem MIDASTOUCH gold-arm watchdog launcher (run from YOUR session so it
rem survives; processes spawned by the coding agent get reaped).
rem The EA touches its paper ledger every 15 min (heartbeat); the watchdog
rem restarts the terminal (flat-check first) when the ledger goes stale.
rem
rem WHY THIS WAS REWRITTEN (2026-09-21). This file is the ONLY entry point the
rem "MIDAS Watchdog Autostart" scheduled task runs, and it was pointing at the
rem predecessor checkout: `cd /d "...\Projects\Synthetic Indices Bot"` followed by
rem that repository's `.venv\Scripts\python.exe`. Measured on this machine: that
rem venv does not exist and this checkout has no venv at all, so the task's two
rem possible outcomes were "cmd cannot find the interpreter" or -- worse, where
rem the sibling still holds a copy -- "the OTHER program's watchdog runs", with the
rem gold arm unguarded in both. That is a dead arm nobody notices, which is the
rem exact failure `register_midas_watchdog_task.ps1` was written to prevent.
rem
rem The resolution below is the one `scripts\paper_supervisor.cmd` already uses and
rem documents: resolve the interpreter and the script from THIS file's own location
rem (%~dp0), prefer a repo-local .venv if one is ever created, and otherwise fall
rem back to the system python -- never to another project's venv, whose src\ would
rem land on the import path.
setlocal
set HERE=%~dp0
pushd "%HERE%"

set PY=%HERE%.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

if not exist "%HERE%scripts\midas_watchdog.py" (
    echo FAIL: scripts\midas_watchdog.py not found under "%HERE%" - refusing to start nothing.
    popd
    exit /b 1
)
if not exist "%HERE%artifacts" mkdir "%HERE%artifacts"

start "MIDAS Watchdog" /MIN cmd /c ""%PY%" -u scripts\midas_watchdog.py --loop 600 >> artifacts\midas_watchdog.log 2>&1"
echo Watchdog started minimized (10-min loop). Log: %HERE%artifacts\midas_watchdog.log
echo Interpreter: %PY%
popd
timeout /t 2 >nul
