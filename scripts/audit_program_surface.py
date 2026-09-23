#!/usr/bin/env python3
"""Which scripts still serve the live program, and which are the residue of dead ones?

WHY THIS EXISTS. This repo has carried three programs in sequence: the synthetic/indices
engine (V75, Boom/Volatility indices), the Deriv-era MIDASTOUCH gold arm on a $1,000
account trading `XAUUSDmicro`, and now the Upcomers MIDASTOUCH gold arm on $25,000
trading `XAUUSD`. The scripts from all three sit side by side in `scripts/`, and file
names do not say which era they belong to — `midas_deploy_v118.py` and
`midas_feed_history.py` look equally current. Deleting the wrong one breaks the live
chain; keeping the wrong one leaves a script that will be run against the new account.

So this tool does not guess. It computes the *transitive import closure* of the entry
points the current program actually uses, and reports everything outside that closure as
residue. The rule it enforces is one-directional and mechanical:

    a module outside the closure may not be imported by a module inside it.

A live entry point that reaches into dead code is not a live entry point — it is a
half-finished migration, and it fails this audit loudly. That check is the whole reason
the tool is not just a "list the files" script: when `compile_midas.py` (needed to build
the EA) still imported the V75 sweep runner, only the closure boundary made it visible.

Usage:
    python scripts/audit_program_surface.py            # report + exit 0
    python scripts/audit_program_surface.py --strict   # exit 1 on residue or dangling

It reads and parses only. It never deletes anything.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"

#: Entry points of the CURRENT program (Upcomers MIDASTOUCH gold on XAUUSD).
#: Adding a name here is a claim that the program needs it; removing one is a claim
#: that it does not. Both claims are reviewable, which is the point.
LIVE_ENTRY_POINTS = (
    # operator surface
    "morning_status.py",
    "midas_watchdog.py",
    "paper_weekly.py",
    "midas_verdict.py",
    # EA build + chart/preset configuration
    "compile_midas.py",
    "gold_preset_upcomers.py",
    "set_chart_preset.py",
    # terminal + data access
    "mt5_probe.py",
    "mt5_data.py",
    "fetch_market_data.py",
    "midas_fetch_history.py",
    "midas_fetch_m5.py",
    # validation and measurement
    "midas_parity.py",
    "midas_first_fills_audit.py",
    "midas_drift_drill.py",
    "daily_scoreboard.py",
    "midas_adaptive.py",
    "floor_zone.py",
    "midas_sweep.py",
    "check_wip_liveness.py",
    # the era classifier the ledgers are read through
    "era.py",
    # the scheduled supervisor itself (2026-09-22): the task that runs with nobody signed
    # in, records one coverage heartbeat per pass (live_coverage) and verifies its own
    # schedule (unattended) and host (host_power). Leaving it out of this list made the
    # three modules that answer "was anything watching at 03:00" read as residue, which is
    # the opposite of true — they are the live surface's own evidence.
    "paper_supervisor.py",
    # this audit is itself part of the live surface: without it listed here it
    # reports itself as residue, which trains the reader to ignore the report
    "audit_program_surface.py",
)


def local_imports(path: Path) -> set[str]:
    """Top-level module names imported by `path` (relative imports excluded).

    An unparseable file raises rather than returning an empty set: a file that cannot
    be parsed cannot be certified as having no dependencies, and silently treating it
    as a leaf is exactly how a live dependency would be missed.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def closure(entry_points: tuple[str, ...]) -> set[str]:
    available = {p.stem for p in SCRIPTS.glob("*.py")}
    seen: set[str] = set()
    stack = [Path(e).stem for e in entry_points]
    missing = [e for e in entry_points if not (SCRIPTS / e).exists()]
    if missing:
        raise SystemExit(f"entry point(s) missing from scripts/: {', '.join(missing)}")
    while stack:
        stem = stack.pop()
        if stem in seen:
            continue
        seen.add(stem)
        for dep in local_imports(SCRIPTS / f"{stem}.py"):
            if dep in available and dep not in seen:
                stack.append(dep)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if residue exists or a live module imports it")
    args = ap.parse_args()

    live = closure(LIVE_ENTRY_POINTS)
    all_modules = {p.stem for p in SCRIPTS.glob("*.py")}
    residue = sorted(all_modules - live)

    dangling = {}
    for stem in sorted(live):
        reached = {d for d in local_imports(SCRIPTS / f"{stem}.py") if d in residue}
        if reached:
            dangling[stem] = sorted(reached)

    print(f"scripts/: {len(all_modules)} modules")
    print(f"  live closure   {len(live):>3}   ({len(LIVE_ENTRY_POINTS)} entry points)")
    print(f"  residue        {len(residue):>3}   (outside the closure)")
    print()
    print("RESIDUE — serves no live entry point:")
    for stem in residue:
        print(f"  {stem}")
    print()
    if dangling:
        print("DANGLING — live modules importing residue (a half-finished migration):")
        for stem, deps in dangling.items():
            print(f"  {stem}.py -> {', '.join(deps)}")
    else:
        print("DANGLING — none: no live module imports residue.")

    if args.strict and (residue or dangling):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
