@echo off
rem The scheduled task's action (MIDASTOUCH Era Ingest, daily 22:40 local = 21:40Z):
rem run the VPS-era ledger ingest so the tally artifact can never go stale unnoticed.
rem %~dp0 is this script's directory (scripts\), so the repo root is one level up --
rem the task needs no hardcoded checkout path and survives a repo move.
cd /d "%~dp0.."
C:\Python314\python.exe scripts\midas_vps_ingest.py >> artifacts\live\era_ingest_last.log 2>&1
