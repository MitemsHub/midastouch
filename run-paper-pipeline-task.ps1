# Scheduled-task wrapper: weekly paper pipeline run.
# Invoked by the "SyntheticIndicesPaperPipeline" scheduled task (Sundays).
# Mirrors scripts/paper_pipeline_weekly.cmd so either entry point works;
# the pipeline is read-only and idempotent (arm-D accrual keeps the first
# row of each day, one row per day, --force never fires from the schedule).
$repo = 'C:\Users\USER\Desktop\Projects\Synthetic Indices Bot'
Set-Location $repo
& "$repo\.venv\Scripts\python.exe" "$repo\scripts\paper_pipeline.py" *>> "$repo\artifacts\v75_replay\paper_pipeline_sched.log"
exit $LASTEXITCODE
