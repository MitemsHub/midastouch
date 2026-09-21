#!/usr/bin/env python3
"""LIVE READINESS — a go/no-go check for the Upcomers account, in one command.

Answers the only question that matters before a session: *is every precondition for
trading actually satisfied right now?* Each line is measured against the running
terminal, not read from a document, and the exit code is non-zero unless every
precondition holds.

It deliberately reports the ARMING gate as its own leg and does not treat "OFF" as a
failure to be fixed. Arming requires a walk-forward PASS record; nothing has one, and
no amount of readiness elsewhere substitutes for it. The distinction this tool exists
to preserve:

  1. **Operational readiness** — terminal connected, correct account, AutoTrading on,
     symbols resolvable, market open. These can be made true today.
  2. **Authorisation** — a validated configuration and an operator arming act. These
     cannot be manufactured, and a system that confuses (1) with (2) will trade an
     unvalidated signal the moment it is technically capable of doing so.

Usage:
  python scripts/live_readiness.py                # full check
  python scripts/live_readiness.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from midas_prop.execution.prop_execution import (  # noqa: E402
    ArmingGate,
    GateCriteria,
)

SYMBOL = "XAUUSD"
ARM_PATH = ROOT / "artifacts" / "live" / "armed.json"
VALIDATION_PATH = ROOT / "artifacts" / "live" / "validation_record.json"
ACCOUNTS_JSON = ROOT / "configs" / "mt5" / "accounts.json"

#: The EA whose binary a chart loads, and the record `scripts/compile_midas.py --deploy`
#: writes at the moment it produces it (see the leg below for why a record and not a
#: re-computation).
EA_SOURCE = ROOT / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
EA_EX5_NAME = "MidastouchAI.ex5"
BUILD_RECORD = ROOT / "artifacts" / "midas_build.json"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def deployed_build_state(source: Path, deployed: list[Path],
                         record: Path | None = None) -> tuple[str, str]:
    """Is the binary a chart would load the one this SOURCE produces?

    Returns `("ok" | "stale" | "unconfirmed", detail)`. Three states, not two, and the
    third is the point: a build whose provenance cannot be checked must not render green,
    which is the same four-state discipline `add()` uses everywhere else here.

    WHY THIS LEG EXISTS. A chart loads whatever `.ex5` sits in the Experts tree. On
    2026-09-20 the terminal held a 20:17 build while the 23:02 source compiled clean at a
    different size, and the only symptom was a byte count in a log line — so every pin in
    this repo could describe a build that was not the one running. Timestamps alone catch
    an OLD binary; they cannot catch one REPLACED after the fact, and MetaEditor is not
    bit-reproducible, so the recorded pair is the only available provenance.
    """
    if not source.is_file():
        return "stale", f"the EA source is missing from the tree ({source})"
    missing = [str(p) for p in deployed if not p.is_file()]
    if missing:
        return "stale", (f"no binary where a chart loads it: {', '.join(missing)} — "
                          f"attach would load nothing, or a build from another tree")
    if record is not None and record.is_file():
        try:
            entry = json.loads(record.read_text(encoding="utf-8"))["targets"].get(
                source.stem)
        except (OSError, ValueError, KeyError, TypeError):
            return "unconfirmed", (f"the build record at {record} cannot be read, so the "
                                   f"deployed build's provenance is UNKNOWN")
        if not entry:
            return "stale", (f"the build record at {record} has no entry for "
                             f"{source.stem}")
        now_src = _sha256(source)
        if entry.get("source_sha256") and now_src != entry["source_sha256"]:
            return "stale", (f"the deployed build belongs to a DIFFERENT source: source "
                             f"{now_src[:8]} vs deployed-from "
                             f"{entry['source_sha256'][:8]} — re-run "
                             f"scripts/compile_midas.py --deploy")
        want = entry.get("ex5_sha256", "")
        for p in deployed:
            if want and _sha256(p) != want:
                return "stale", (f"{p.name} is not the binary that was compiled: ex5 "
                                 f"{_sha256(p)[:8]} vs recorded {want[:8]}")
        return "ok", (f"{source.stem}: source {now_src[:8]} == the source the deployed "
                       f"binary was built from ({len(deployed)} copy(s) hash-checked)")
    # No record: timestamps are all we have, and they only prove the ORDER of writes.
    newest_bin = max(p.stat().st_mtime for p in deployed)
    if source.stat().st_mtime > newest_bin:
        return "stale", (f"the deployed binary predates its source (source newer by "
                         f"{(source.stat().st_mtime - newest_bin) / 60:.0f} min) and "
                         f"there is no build record — re-run "
                         f"scripts/compile_midas.py --deploy")
    return "unconfirmed", (f"no build record at {record or '-'}: the binary is NEWER than "
                           f"the source, but that is not proof it was built from it"
                           f" (the compiler is not bit-reproducible) — run "
                           f"scripts/compile_midas.py --deploy")


#: The gold week as this venue trades it, in UTC. MEASURED, not assumed: the daily
#: break and the Friday close are in docs/MIDASTOUCH_GOLD_PLAYBOOK.md §4 (gold is 24/5,
#: ~1h break around 21:00-22:00 UTC, weekend closed, flat over the weekend by policy).
GOLD_OPEN_HOUR_UTC = 22        # Sunday 22:00 UTC the week begins
GOLD_CLOSE_HOUR_UTC = 21       # Friday 21:00 UTC the week ends


def _last_sunday(year: int, month: int) -> datetime:
    """00:00 UTC on the last Sunday of a month (the EU DST rule's anchor)."""
    d = datetime(year, month, 1, tzinfo=timezone.utc) + timedelta(days=31)
    d = d.replace(day=1) - timedelta(days=1)          # last day of `month`
    return (d - timedelta(days=(d.weekday() + 1) % 7)).replace(
        hour=0, minute=0, second=0, microsecond=0)


def venue_offset_min(now: datetime) -> int:
    """The venue's server clock, in minutes ahead of UTC, at `now`.

    MEASURED, 2026-09-20: the tester's bar epochs sit **+60** through January-March and
    **+120** from April (docs/DATA_SCOPE_AND_CLOCK_20260920.md), a single step at the EU
    DST boundary — the server runs on Central European time. Without this, every reading
    taken from a server-stamped epoch is wrong by two hours, in a direction nobody
    notices: a fresh tick reports an age of -120 min and a closed market can report as
    open.

    The parity contract still derives its own pin per window from the venue's own bars
    and REFUSES when it is not constant — that stricter reading stays the authority for
    anything certified. This rule exists so the live checks read the same clock.
    """
    dst_start = _last_sunday(now.year, 3) + timedelta(hours=1)    # 01:00 UTC
    dst_end = _last_sunday(now.year, 10) + timedelta(hours=1)     # 01:00 UTC
    return 120 if dst_start <= now < dst_end else 60


def gold_session(now: datetime) -> tuple[bool, str]:
    """Is gold trading at `now` (UTC), and why — one rule, stated once.

    Sun 22:00 -> Fri 21:00, with a ~1h daily break 21:00-22:00 on Mon-Thu. The schedule
    is what makes the tick reading meaningful, and vice versa: a live tick inside a
    closed session is a data problem, not an opportunity.
    """
    wd, hh = now.weekday(), now.hour          # Monday=0 .. Sunday=6
    if wd == 5:
        return False, "weekend (Friday 21:00 -> Sunday 22:00 UTC)"
    if wd == 6:                                # Sunday
        return (True, "open (week) at %02d:00 UTC" % hh) if hh >= GOLD_OPEN_HOUR_UTC \
            else (False, "weekend, opens today %02d:00 UTC" % GOLD_OPEN_HOUR_UTC)
    if wd == 4 and hh >= GOLD_CLOSE_HOUR_UTC:  # Friday from the close
        return False, "weekend (closed from Friday %02d:00 UTC)" % GOLD_CLOSE_HOUR_UTC
    if hh == GOLD_CLOSE_HOUR_UTC:              # the daily break, Mon-Thu
        return False, "daily break (%02d:00-%02d:00 UTC)" % (GOLD_CLOSE_HOUR_UTC,
                                                             GOLD_OPEN_HOUR_UTC)
    return True, "open (Sun %02d:00 -> Fri %02d:00 UTC)" % (GOLD_OPEN_HOUR_UTC,
                                                            GOLD_CLOSE_HOUR_UTC)


def next_gold_open(now: datetime) -> datetime:
    """When the next session starts, or `now` itself when one is already running.

    MEASURED DEFECT, 2026-09-20: this returned the next *Sunday* unconditionally, so at
    Sunday 22:27 UTC — 27 minutes into the week — it printed "next gold open in 167.5h",
    a week away. Under time pressure that is the most dangerous wrong answer this tool can
    give, so the open-hour boundary is now part of the rule rather than an afterthought.
    """
    open_now, _ = gold_session(now)
    if open_now:
        return now
    if now.weekday() == 6:                     # Sunday before the open
        return now.replace(hour=GOLD_OPEN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now.weekday() in (0, 1, 2, 3):          # Mon-Thu inside the daily break
        return now.replace(hour=GOLD_OPEN_HOUR_UTC, minute=0, second=0, microsecond=0)
    days = (6 - now.weekday()) % 7             # Friday from the close, or Saturday
    return (now + timedelta(days=days)).replace(
        hour=GOLD_OPEN_HOUR_UTC, minute=0, second=0, microsecond=0)


def _scheduled_task_target(name: str) -> tuple[Path | None, str]:
    """The file a scheduled task would actually run, or (None, reason).

    Three outcomes are kept distinct on purpose: a path, "no such task", and "could not
    ask". Collapsing the last two would render an unanswerable check as a pass, which is
    the exact defect this repo audits elsewhere.
    """
    import re
    import subprocess

    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-ScheduledTask -TaskName '{name}').Actions | "
             "ForEach-Object { $_.Execute + ' ' + $_.Arguments }"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    text = (out.stdout or "").strip()
    if out.returncode != 0 or not text:
        return None, "not registered"
    m = re.search(r'"([^"]+\.(?:cmd|bat|exe|ps1))"', text) or \
        re.search(r"(\S+\.(?:cmd|bat|exe|ps1))", text)
    if not m:
        return None, f"no runnable path in the action ({text!r})"
    return Path(m.group(1)), ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="do not touch the MT5 bridge at all; forces the "
                         "terminal-unavailable refusal (for machines with no "
                         "terminal, and for scripts/refusal_sweep.py)")
    args = ap.parse_args()

    if args.offline:
        # NOTE --offline is NOT equivalent to an empty %APPDATA%: the MT5 python
        # bridge locates a RUNNING terminal independently of %APPDATA%, so pointing
        # APPDATA at an empty directory does not stop this script connecting. That
        # was measured on 2026-09-19 and is why an explicit flag is the only way to
        # force the refusal path.
        print("TERMINAL UNAVAILABLE: --offline was requested", file=sys.stderr)
        print("REFUSING: readiness cannot be assessed without the terminal. A "
              "readiness report produced from no terminal would be a verdict about "
              "a source that was never read.", file=sys.stderr)
        return 3

    now = datetime.now(timezone.utc)
    term_data: Path | None = None
    checks: list[tuple[str, bool, str]] = []
    report: dict = {"utc": now.isoformat(timespec="seconds"),
                    "weekday": now.strftime("%A")}

    def add(name: str, ok: bool, detail: str, *, blocking: bool = True) -> None:
        """Record one check as (name, ok, detail, blocking).

        Four states, not two, because two of them are routinely conflated:

        * **PASS** — measured and satisfied.
        * **FAIL** — measured and unsatisfied, and it blocks.
        * **WARN** — could NOT be confirmed. This is NOT a pass. A check that
          cannot reach an answer must not render green, which is the whole defect
          class this repo audits elsewhere (see `docs/VERDICT_PROVENANCE_AUDIT_20260919.md`).
        * **OFF** — a known, deliberate, non-blocking state: the arming switch.
        """
        checks.append((name, ok, detail, blocking))
        if not ok and blocking:
            report.setdefault("failures", []).append(name)

    # ---- 1. operational -------------------------------------------------- #
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        add("MetaTrader5 module", False, f"not installed: {exc}")
        mt5 = None

    if mt5 is not None:
        if not mt5.initialize():
            add("terminal connection", False,
                f"mt5.initialize() failed, code {mt5.last_error()}")
        else:
            ti = mt5.terminal_info()
            ai = mt5.account_info()
            add("terminal connection", ti is not None,
                f"build {getattr(ti, 'build', '?')} @ {getattr(ti, 'path', '?')}")
            if ti is not None and getattr(ti, "data_path", ""):
                # The running terminal's OWN data folder, so the binary checked below is
                # the one a chart here would load — not the one a sibling install holds.
                term_data = Path(str(ti.data_path))
            if ti is not None:
                add("AutoTrading enabled", bool(ti.trade_allowed),
                    "Tools > Options > Expert Advisors > Allow Algo Trading"
                    if not ti.trade_allowed else "allowed")
                add("terminal connected", bool(ti.connected),
                    "disconnected from the server" if not ti.connected else "connected")
            if ai is None:
                add("account logged in", False, "account_info() returned None")
            else:
                report["account"] = {"login": int(ai.login), "server": ai.server,
                                     "company": getattr(ai, "company", ""),
                                     "currency": ai.currency,
                                     "equity": float(ai.equity),
                                     "balance": float(ai.balance),
                                     "leverage": int(ai.leverage),
                                     "trade_allowed": bool(ai.trade_allowed),
                                     "trade_expert": bool(ai.trade_expert)}
                add("account logged in", True,
                    f"{int(ai.login)} @ {ai.server} "
                    f"({getattr(ai, 'company', '?')})")
                expected = None
                if ACCOUNTS_JSON.is_file():
                    try:
                        reg = json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
                        act = reg.get("active", {})
                        # The key is 'account'; 'login' is accepted as a fallback so a
                        # registry written in the other convention still compares.
                        expected = act.get("account") or act.get("login")
                    except (OSError, ValueError):
                        expected = None
                if expected is None:
                    add("account matches the registry", False,
                        f"NO USABLE REGISTRY at {ACCOUNTS_JSON.name}: the terminal's "
                        f"account ({int(ai.login)}) cannot be confirmed as the one "
                        f"we intend to trade. Not a pass — an unconfirmed check.",
                        blocking=False)
                else:
                    add("account matches the registry",
                        int(ai.login) == int(expected),
                        f"terminal {int(ai.login)} vs registry {expected}")
                add("expert trading allowed on the account", bool(ai.trade_expert),
                    "the SERVER side of algo trading is off"
                    if not ai.trade_expert else "allowed")

            info = mt5.symbol_info(SYMBOL)
            tick = mt5.symbol_info_tick(SYMBOL)
            if info is None:
                add(f"{SYMBOL} available", False,
                    "symbol not found — check the suffix on this server")
            else:
                add(f"{SYMBOL} available", True,
                    f"{getattr(info, 'description', '')} "
                    f"spread {info.spread} pts, min lot {info.volume_min:g}")
                if tick is not None:
                    # The venue stamps epochs on ITS clock, so the raw difference is the
                    # server offset, not an age. Convert with the measured offset before
                    # judging freshness — otherwise a live tick reads as "-120 min ago"
                    # and a stale one can round to zero.
                    off_min = venue_offset_min(now)
                    tick_utc = (datetime.fromtimestamp(float(tick.time), tz=timezone.utc)
                                - timedelta(minutes=off_min))
                    age = (now - tick_utc).total_seconds()
                    sched_open, why = gold_session(now)
                    live = age < 900
                    report["tick"] = {"bid": float(tick.bid), "ask": float(tick.ask),
                                      "venue_offset_min": off_min,
                                      "tick_utc": tick_utc.isoformat(timespec="seconds"),
                                      "age_seconds": round(age),
                                      "session": why}
                    add("market open (live tick)", sched_open and live,
                        f"feed {'live' if live else 'STALE'} "
                        f"(last tick {age / 60:.0f} min ago, venue clock "
                        f"UTC{off_min // 60:+d}) | schedule: {why}")
                else:
                    add("market open (live tick)", False, "no tick available")

    # ---- 1b. operator-managed state that can silently point at a past era - #
    #
    # A Task Scheduler entry embeds an ABSOLUTE path, so renaming this folder leaves the
    # task pointing at a directory that no longer exists. It then fires on schedule and
    # fails every time — which looks exactly like "nothing to report", because a task
    # that cannot start writes no log line either. That is the same defect class as the
    # stale VPS hosting record audited on 2026-09-19: a marker whose mere presence, or
    # whose stale content, keeps asserting an arrangement that has ended.
    #
    # Measured, not assumed: the action is read back from the scheduler and its target
    # must resolve to a file INSIDE the repo root this script is running from.
    task_name = "MitemshubPaperSupervisor"
    task_path, task_err = _scheduled_task_target(task_name)
    if task_err:
        add(f"scheduled task {task_name}", False,
            f"could not be queried ({task_err}) — the supervisor's schedule is "
            f"UNCONFIRMED, not absent", blocking=False)
    elif task_path is None:
        add(f"scheduled task {task_name}", False,
            "not registered: nothing is supervising the paper run. Reinstall with "
            "scripts/install_paper_task.ps1 -Apply if it should be running.",
            blocking=False)
    else:
        inside = ROOT in task_path.parents or task_path.parent == ROOT
        add(f"scheduled task {task_name}", inside and task_path.is_file(),
            f"target {task_path}" if inside and task_path.is_file() else
            (f"STALE: the task points at {task_path}, which is outside {ROOT} "
             f"or no longer exists. Re-run scripts/install_paper_task.ps1 -Apply."
             if not inside else f"target missing: {task_path}"))

    # ---- 1c. the deployed EA build ---------------------------------------- #
    #
    # Everything else here can be true while a chart runs an engine nobody pinned: the
    # source is the description, the .ex5 is what executes, and nothing in between is
    # automatic. So the binary's provenance is a readiness leg, not a footnote.
    deployed_bins = [ROOT / "mql5" / "MIDASTOUCH" / EA_EX5_NAME]
    if term_data is not None:
        deployed_bins.append(term_data / "MQL5" / "Experts" / "MIDASTOUCH" / EA_EX5_NAME)
    build_state, build_detail = deployed_build_state(EA_SOURCE, deployed_bins, BUILD_RECORD)
    if term_data is None:
        # The repo copy is the record; the TERMINAL copy is what a chart loads. Checking
        # one and calling it confirmed would be exactly the kind of green this repo audits
        # out, so an unchecked terminal downgrades an otherwise clean build to WARN.
        build_state = "ok" if build_state == "stale" else "unconfirmed"
        build_detail += (" | the terminal's Experts tree could NOT be checked (no running "
                         "terminal): the repo copy is not what a chart loads")
    report["build"] = {"state": build_state, "detail": build_detail,
                       "checked": [str(p) for p in deployed_bins]}
    add("deployed EA build matches its source", build_state == "ok", build_detail,
        blocking=(build_state == "stale"))

    # ---- 2. authorisation ------------------------------------------------ #
    # TWO QUESTIONS, TWO ANSWERS (2026-09-21). `ArmingGate` answers "may the PYTHON
    # execution path trade?" — it wants a `validation_record.json`, and it is still OFF.
    # The operator's record answers "has the account holder authorised the EA to trade?"
    # They were conflated here, and the result was the worst possible report on a live
    # arm: after the operator override this script printed "NOT AUTHORISED" while the
    # EA was placing real orders on 1428765. Execution is the operator's; EVIDENCE is
    # the gate's; each is reported as itself below.
    gate = ArmingGate(arm_path=ARM_PATH, validation_path=VALIDATION_PATH,
                      criteria=GateCriteria())
    arming = gate.evaluate()
    report["python_execution_gate"] = {"armed": arming.armed,
                                       "reasons": list(arming.reasons)}
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import mt5_ops  # noqa: PLC0415 — one reader for "are we live?"
        state = mt5_ops.arming_state(str(ROOT))
    except Exception as exc:      # pragma: no cover — unreadable record, never a crash
        state = {"armed": False, "override": False, "arm": "",
                 "summary": f"arming state unreadable: {exc}"}
    arming_armed = bool(state["armed"])
    arming_override = bool(state["override"])
    report["arming"] = {"armed": arming_armed, "override": arming_override,
                        "arm": state.get("arm", ""), "summary": state["summary"],
                        "python_gate": arming.armed}
    # Authorisation is never a blocking machine failure: a machine cannot be fixed into
    # being authorised.
    add("operator authorisation", arming_armed, state["summary"], blocking=False)
    add("python execution gate", arming.armed,
        "; ".join(arming.reasons)[:180], blocking=False)
    add("operator arming file present", ARM_PATH.is_file(),
        str(ARM_PATH) if ARM_PATH.is_file() else f"absent ({ARM_PATH})",
        blocking=False)
    add("validation record present", VALIDATION_PATH.is_file(),
        str(VALIDATION_PATH) if VALIDATION_PATH.is_file()
        else "absent — nothing has passed the walk-forward gate", blocking=False)

    # ---- 2b. does the evidence the record cites describe THIS strategy? --- #
    # A verdict about a different strategy is not evidence for this arm, and until
    # 2026-09-21 nothing here checked. `artifacts/live/armed.json` cites
    # `artifacts/gold_wfo.json` — a walk-forward whose only trigger axis is an M15 EMA stack,
    # with no Bollinger or RSI anywhere in the engine that wrote it — while the EA trades a
    # BB(20,2.0)/RSI(14) trigger. The two rules agree on the same bar and direction 3.4% of the
    # time, so the cited verdict is about a different strategy. Silence is the failure mode
    # here, which is why an UNDISCLOSED mismatch BLOCKS while a recorded one is named and
    # passes: what is being prevented is the presentation, not the operator's decision.
    family = gate.evidence_family()
    report["evidence_family"] = family
    family_ok = family["state"] in ("match", "disclosed-mismatch", "no-arm-record")
    add("evidence describes this strategy", family_ok, family["reason"][:230],
        blocking=(family["state"] == "mismatch"))

    # ---- 3. market hours, stated so nobody has to guess ------------------- #
    nxt = next_gold_open(now)
    hours = (nxt - now).total_seconds() / 3600.0
    report["next_gold_open_utc"] = nxt.isoformat(timespec="minutes")
    report["hours_to_open"] = round(hours, 1)

    # ---- verdict ---------------------------------------------------------- #
    auth_names = {"operator authorisation", "python execution gate",
                  "operator arming file present",
                  "validation record present", "account matches the registry"}
    blocking = [c for c in checks if c[1] is False and c[3]]
    operational_ok = not blocking
    verdict = (("AUTHORISED_BY_OPERATOR_OVERRIDE" if arming_override else "READY_TO_TRADE")
               if operational_ok and arming_armed else
               "OPERATIONALLY_READY_BUT_NOT_AUTHORISED" if operational_ok else
               "NOT_READY")
    report["verdict"] = verdict

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if operational_ok else 1

    print(f"=== LIVE READINESS — {now:%Y-%m-%d %H:%M UTC} ({now:%A}) ===")
    print()
    for name, ok, detail, is_blocking in checks:
        if ok:
            mark = "PASS"
        elif not is_blocking:
            mark = "OFF " if name == "python execution gate" else "WARN"
        else:
            mark = "FAIL"
        print(f"  [{mark}] {name:<38} {detail}")
    print()
    if arming_override:
        print(f"  authorisation: ARMED BY OPERATOR OVERRIDE ({state.get('arm', '?')}) — real "
              f"orders are being placed. NO validation record exists: this is the "
              f"account holder's decision on a FAILED gate, not a strategy that passed.")
    if family["state"] in ("mismatch", "disclosed-mismatch", "unknown"):
        print(f"  evidence: {family['reason']}")
    elif arming_armed:
        print("  authorisation: ARMED — a recorded validation plus the operator's act.")
    else:
        print("  authorisation: NOT ARMED — the venue gate is a separate condition from "
              "machine readiness, and it is the only one that cannot be fixed by "
              "configuring anything.")
    print()
    if hours <= 0.0:
        print(f"  market: OPEN — gold trades Sun 22:00 -> Fri 21:00 UTC "
              f"(daily break {GOLD_CLOSE_HOUR_UTC:02d}:00-{GOLD_OPEN_HOUR_UTC:02d}:00)")
    else:
        print(f"  market: closed — next gold open {nxt:%Y-%m-%d %H:%M} UTC "
              f"({hours:.1f}h away)")
    print()
    if verdict == "AUTHORISED_BY_OPERATOR_OVERRIDE":
        print("VERDICT: AUTHORISED BY OPERATOR OVERRIDE — TRADING, NOT VALIDATED.")
        print("  Real orders go out at the preset's declared risk. The walk-forward gate")
        print("  did not pass and no validation record exists; see artifacts/live/armed.json")
        print("  for the numbers the override was taken on, and what would retire it.")
        if family["state"] == "disclosed-mismatch":
            print("  AND the gate it cites measured a DIFFERENT STRATEGY — the record says so;")
            print("  see docs/GOLD_WFO_EA_VERDICT_20260921.md for the walk-forward of the")
            print("  rule this arm actually trades (also NOT VALIDATED).")
    elif verdict == "READY_TO_TRADE":
        print("VERDICT: READY TO TRADE.")
    elif verdict == "OPERATIONALLY_READY_BUT_NOT_AUTHORISED":
        print("VERDICT: OPERATIONALLY READY, NOT AUTHORISED.")
        print("  Everything the venue requires of the machine is satisfied. What is")
        print("  missing is a strategy that has passed the walk-forward gate, and")
        print("  that is not something this script can arrange.")
    else:
        print("VERDICT: NOT READY.")
        for n in report.get("failures", []):
            print(f"  blocking: {n}")
    # The evidence refusal is its own statement, and it is NOT a machine fault: the terminal,
    # the account, the build and the market can all be perfect while this fails, because what
    # fails is a practice — citing another strategy's verdict as this arm's evidence. Saying
    # so explicitly keeps "NOT READY" from being misread as "the arm is not trading".
    if family["state"] == "mismatch":
        print()
        print("REFUSAL: the arming record cites a verdict about a DIFFERENT STRATEGY and does")
        print("  not say so, so it is refused as this arm's evidence. This is not a machine")
        print("  fault — the operational legs above are unchanged by it, and the arm keeps")
        print("  trading on the operator's override. What it refuses is the presentation.")
        print("  To clear it: cite a walk-forward of the EA's own rule (artifacts/gold_wfo_ea.json")
        print("  exists and is NOT VALIDATED either), or record the mismatch in the arming")
        print(f"  record under 'gate_family_mismatch': {family['reason'][:150]}")
    return 0 if operational_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
