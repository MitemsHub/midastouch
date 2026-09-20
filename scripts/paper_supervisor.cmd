@echo off
REM Wrapper for the Windows scheduled task "MitemshubPaperSupervisor".
REM
REM WHY A WRAPPER AND NOT A DIRECT COMMAND. A scheduled task cannot redirect output,
REM so a task pointed straight at the python script would discard every message the
REM supervisor produces -- including its alerts. This redirects to a log, and it
REM resolves the interpreter and the script from ITS OWN location (%~dp0) rather than
REM from a hardcoded path, so renaming the project folder only requires re-running the
REM installer, not editing this file.
setlocal
set HERE=%~dp0
set PY=%HERE%..\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
if not exist "%HERE%..\artifacts\live" mkdir "%HERE%..\artifacts\live"
"%PY%" "%HERE%paper_supervisor.py" --steps 60 >> "%HERE%..\artifacts\live\supervisor.log" 2>&1
exit /b %ERRORLEVEL%
