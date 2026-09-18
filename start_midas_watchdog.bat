@echo off
rem MIDASTOUCH gold-arm watchdog launcher (run from YOUR session so it
rem survives; processes spawned by the coding agent get reaped).
rem The EA touches its paper ledger every 15 min (heartbeat); the watchdog
rem restarts the terminal (flat-check first) when the ledger goes stale.
cd /d "C:\Users\USER\Desktop\Projects\Synthetic Indices Bot"
start "MIDAS Watchdog" /MIN cmd /c ".venv\Scripts\python.exe -u scripts\midas_watchdog.py --loop 600 >> artifacts\midas_watchdog.log 2>&1"
echo Watchdog started minimized (10-min loop). Log: artifacts\midas_watchdog.log
timeout /t 2 >nul
