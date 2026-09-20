#!/usr/bin/env python3
"""The scheduled supervisor's pass: supervise the gold arm, place nothing.

WHY THIS FILE EXISTS. `scripts/install_paper_task.ps1` registers the Windows task
`MitemshubPaperSupervisor` against `scripts/paper_supervisor.cmd`, which in turn is
expected to call a module of this name — and neither existed in this repository.
Measured 2026-09-20:

    $ powershell -File scripts/install_paper_task.ps1
    REFUSING: wrapper not found at ...\\MIDASTOUCH\\scripts\\paper_supervisor.cmd

so the task on this machine kept running the PREDECESSOR checkout's supervisor
(`...\\Synthetic Indices Bot\\scripts\\paper_supervisor.cmd`), which is exactly why
`scripts/live_readiness.py` reports the scheduled-task leg as STALE on every run — the
one FAIL between this program and `VERDICT: READY`. An unattended machine (a VPS) has
no supervisor at all until this exists.

WHY A DELEGATE AND NOT AN IMPLEMENTATION. `scripts/midas_watchdog.py` already IS the
gold supervisor: liveness from the ledger's mtime, a PID-exact restup gated on every
ledger being flat, escalation with a restart budget, an instance lock, a parity pause
marker, the weekend policy, and the operator-managed VPS-hosting marker. A second
supervision implementation would be a second set of rules about when to restart a
terminal holding a real position. This file adds only what the scheduled-task context
needs:

  * ONE pass per task firing. The task repeats every 20 minutes; the watchdog's own
    instance lock makes an overlapping `--loop` impossible rather than merely unlikely,
    so a task firing per pass is the shape that fits.
  * ONE summary line per firing, so `artifacts/live/supervisor.log` is readable as a
    history rather than as a wall of JSON.
  * An exit code that means something to Task Scheduler: 0 when the pass completed,
    non-zero only when the watchdog's own escalation says a human must act. "No arm
    attached" is REPORTED, not failed — nothing is armed on this account, and a task
    that goes red every 20 minutes is noise that hides the real alerts.

It sends no orders and it does not arm anything: arming is an arming-record event, and
this file only ever observes, restarts a dead terminal, and writes state.

Usage (the .cmd wrapper does exactly this):
  python scripts/paper_supervisor.py            # one pass, acts if needed
  python scripts/paper_supervisor.py --dry-run  # report what would happen
  python scripts/paper_supervisor.py --status    # read-only state summary
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

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

    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {verdict} "
          f"action={action} terminal={record.get('terminal_exe', '?')} {problem}".rstrip())
    return 1 if verdict == "ALERT" else 0


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
        return 1 if bad else 0
    return one_pass(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
