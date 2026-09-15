@echo off
rem Research-only weekly Volatility 75 shadow cycle.
rem This refreshes broker history and writes dated artifacts only.
rem It never enables the EA, changes presets, or submits orders.
cd /d "%~dp0.."
"C:\Python314\python.exe" "scripts\run_v75_shadow_cycle.py" --days 30 --train-days 10 --validation-days 5 --test-days 5 --min-samples 12 --portfolio-size 8 --recent-weight 0.65 >> "artifacts\v75_shadow_cycles\weekly.log" 2>&1
exit /b %errorlevel%
