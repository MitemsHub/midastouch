@echo off
REM Wrapper for the Windows scheduled task "MIDASTOUCH Arm Supervisor".
REM
REM WHY A WRAPPER AND NOT A DIRECT COMMAND. A scheduled task cannot redirect output, so a
REM task pointed straight at the python script would discard every message the supervisor
REM produces -- including its alerts. This redirects to a log, and it resolves the
REM interpreter and the script from ITS OWN location (%~dp0) rather than from a hardcoded
REM path, so renaming the project folder only requires re-running the installer, not
REM editing this file.
REM
REM MEASURED, 2026-09-20: this file did not exist in this repository, so
REM scripts/install_paper_task.ps1 refused ("wrapper not found") and the task kept running
REM the PREDECESSOR checkout's supervisor -- the single FAIL in scripts/live_readiness.py,
REM and the reason an unattended (VPS) machine had no supervision at all.
REM
REM MEASURED, 2026-09-22: the task was registered with an INTERACTIVE principal, so it ran
REM only while a user was signed in -- 54 passes in 25.3 h where a 20-minute cadence owes
REM 76, zero passes in the 01:00-06:00 UTC hours, one gap of 407 minutes. The interpreter
REM resolution below was never the problem; the principal was. The installer now registers
REM S4U + at-startup + wake-to-run, and scripts/unattended.py reads the registered task
REM back and says whether that is actually true.
REM
REM The interpreter resolution is still load-bearing: this checkout has no .venv of its own,
REM and the venv that exists belongs to the predecessor checkout, whose src/ would land on
REM the import path. Fall back to the system python, never to another project's venv.
setlocal
set HERE=%~dp0
set PY=%HERE%..\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
if not exist "%HERE%..\artifacts\live" mkdir "%HERE%..\artifacts\live"
"%PY%" "%HERE%paper_supervisor.py" %* >> "%HERE%..\artifacts\live\supervisor.log" 2>&1
exit /b %ERRORLEVEL%
