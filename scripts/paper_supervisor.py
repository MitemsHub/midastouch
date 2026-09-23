#!/usr/bin/env python3
"""The arm supervisor's pass: supervise the gold arm, place nothing.

WHY THIS FILE EXISTS. `scripts/install_paper_task.ps1` registers the Windows task that
runs this module (via `scripts/paper_supervisor.cmd`). Before 2026-09-20 the file did not
exist in this repository, so the task kept running the PREDECESSOR checkout's supervisor
(`...\\Synthetic Indices Bot\\scripts\\paper_supervisor.cmd`), which is why
`scripts/live_readiness.py` reported the scheduled-task leg as STALE on every run.

WHAT CHANGED ON 2026-09-22, AND WHY IT IS THE POINT. MEASURED that morning from this
module's own log: 54 passes in 25.3 h where a 20-minute cadence owes 76, **zero** passes in
the 01:00-06:00 UTC hours, one gap of 407 minutes. The supervisor was not broken — it was
ABSENT, because the task's principal was `Interactive` and the arm's market hours are the
hours nobody is signed in. Two things follow, and both are in this file:

  * the task is now registered to run **whether or not anyone is signed in**
    (`scripts/unattended.py` reads the task definition and says so; `live_readiness.py`
    fails the arming review until it does);
  * every pass is **recorded** (`artifacts/live/supervision_heartbeat.jsonl`, via
    `scripts/live_coverage.py`) and the interval between passes is checked against a
    pre-registered threshold. A gap is a fact about a night, and nothing else in this
    program wrote one down — the watchdog reads the ledger's age at the moment it runs,
    which cannot see the hours when it did not run.

WHY A DELEGATE AND NOT AN IMPLEMENTATION. `scripts/midas_watchdog.py` already IS the gold
supervisor: liveness from the ledger's mtime, a PID-exact restup gated on every ledger
being flat, escalation with a restart budget, an instance lock, a parity pause marker, the
weekend policy, and the operator-managed VPS-hosting marker. A second supervision
implementation would be a second set of rules about when to restart a terminal holding a
real position. This file adds only what the scheduled-task context needs:

  * ONE pass per task firing. The task repeats every `CADENCE_MIN` minutes; the watchdog's
    own instance lock makes an overlapping `--loop` impossible rather than merely
    unlikely, so a task firing per pass is the shape that fits.
  * ONE summary line per firing, so `artifacts/live/supervisor.log` is readable as a
    history rather than as a wall of JSON.
  * ONE heartbeat line per firing plus the gap check, so a night with no passes is
    *visible* rather than merely absent.
  * An exit code that means something to Task Scheduler: 0 when the pass completed and
    nothing new was found; non-zero when the watchdog's own escalation says a human must
    act, or when THIS pass raised a new heartbeat-gap alarm. A standing unacknowledged
    alarm deliberately does not re-red every pass — a task that goes red every 20 minutes
    is noise that hides the real alerts; the standing alarm is carried by
    `artifacts/live/heartbeat_gap_alarm.json`, `alerts.log` and `morning_status [3b]`
    instead, and `live_readiness.py` fails until a human acknowledges it.

It sends no orders and it does not arm anything: arming is an arming-record event, and
this file only ever observes, restarts a dead terminal, and writes state. What it
supervises is the arm as the ARMING RECORD configures it (`preset_for_tag(tag,
armed=True)`), so an armed arm is not silently repaired back to a paper pin.

Usage (the .cmd wrapper does exactly this):
  python scripts/paper_supervisor.py            # one pass, acts if needed
  python scripts/paper_supervisor.py --dry-run  # report what would happen
  python scripts/paper_supervisor.py --status    # read-only state summary
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import live_coverage as lc  # noqa: E402
import midas_watchdog as wd  # noqa: E402


def one_pass(dry_run: bool = False) -> int:
    """Run the watchdog's portfolio poll once; return the process exit code."""
    try:
        record = wd.check(dry_run=dry_run)
    except Exception:  # noqa: BLE001 — a supervisor crash must be visible, not silent
        print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} SUPERVISOR CRASH")
        traceback.print_exc()
        return 1

    action = record.get("action", "?")
    problem = record.get("problem", "")
    if action in ("PAUSED", "VPS-HOSTING"):
        # Observing-only states are the system working as designed: a parity/tester
        # session owns the terminal, or the surface has moved to hosting and local
        # remediation is meaningless. Never red.
        verdict = "OK"
    elif action == "NONE" and "no MidastouchAI chart" in problem:
        verdict = "OK"
    else:
        try:
            _, escalating = wd.watchdog_summary()
        except Exception:  # noqa: BLE001
            escalating = True
        verdict = "ALERT" if escalating else "OK"

    # The coverage record is written on every real pass, whatever the verdict. A dry run
    # writes nothing: "what would have happened" is not a pass that happened, and letting
    # it into the record would let a rehearsal count as coverage.
    coverage = {"alarm": None, "alarm_new": False}
    if not dry_run:
        coverage = lc.record_pass(record, verdict=verdict)

    line = (f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {verdict} "
            f"action={action} terminal={record.get('terminal_exe', '?')} {problem}").rstrip()
    if coverage.get("alarm"):
        line += (f" | ALARM {coverage['alarm']['kind']} "
                 f"{coverage['alarm']['gap_min']}min: {coverage['alarm']['detail']}")
    print(line)
    return 1 if (verdict == "ALERT" or coverage.get("alarm_new")) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gold-arm supervisor: one scheduled pass")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen; never restart anything")
    ap.add_argument("--status", action="store_true",
                    help="print the state summary and exit (read-only)")
    args = ap.parse_args(argv)

    if args.status:
        line, bad = wd.watchdog_summary()
        print(("! " if bad else "") + line)
        alarm = lc.alarm_line()
        if alarm:
            print(alarm)
            bad = bad or "PROBLEM" in alarm
        return 1 if bad else 0
    return one_pass(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
