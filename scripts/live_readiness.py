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
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from synthetic_trader.execution.prop_execution import (  # noqa: E402
    ArmingGate,
    GateCriteria,
)

SYMBOL = "XAUUSD"
ARM_PATH = ROOT / "artifacts" / "live" / "armed.json"
VALIDATION_PATH = ROOT / "artifacts" / "live" / "validation_record.json"
ACCOUNTS_JSON = ROOT / "configs" / "mt5" / "accounts.json"


def next_gold_open(now: datetime) -> datetime:
    """The next Sunday 22:00 UTC — when the gold week begins.

    Measured against the calendar rather than assumed: if this is wrong the answer
    "the market is closed" is wrong too, and that is the one conclusion a person
    under time pressure is most likely to act on without checking.
    """
    days_ahead = (6 - now.weekday()) % 7  # Monday=0 .. Sunday=6
    cand = (now + timedelta(days=days_ahead)).replace(hour=22, minute=0, second=0,
                                                      microsecond=0)
    if cand <= now:
        cand += timedelta(days=7)
    return cand


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
                    age = now.timestamp() - float(tick.time)
                    report["tick"] = {"bid": float(tick.bid), "ask": float(tick.ask),
                                      "age_seconds": round(age)}
                    add("market open (live tick)", age < 900,
                        f"last tick was {age / 60:.0f} min ago")
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

    # ---- 2. authorisation ------------------------------------------------ #
    gate = ArmingGate(arm_path=ARM_PATH, validation_path=VALIDATION_PATH,
                      criteria=GateCriteria())
    arming = gate.evaluate()
    report["arming"] = {"armed": arming.armed, "reasons": list(arming.reasons)}
    # The arming switch is reported as an AUTHORISATION state, never as a blocking
    # machine failure: it is OFF by design, and its being OFF is correct until a
    # configuration passes the gate. It is excluded from `failures` deliberately.
    add("arming switch", arming.armed,
        "; ".join(arming.reasons)[:180], blocking=False)
    add("operator arming file present", ARM_PATH.is_file(),
        str(ARM_PATH) if ARM_PATH.is_file() else f"absent ({ARM_PATH})",
        blocking=False)
    add("validation record present", VALIDATION_PATH.is_file(),
        str(VALIDATION_PATH) if VALIDATION_PATH.is_file()
        else "absent — nothing has passed the walk-forward gate", blocking=False)

    # ---- 3. market hours, stated so nobody has to guess ------------------- #
    nxt = next_gold_open(now)
    hours = (nxt - now).total_seconds() / 3600.0
    report["next_gold_open_utc"] = nxt.isoformat(timespec="minutes")
    report["hours_to_open"] = round(hours, 1)

    # ---- verdict ---------------------------------------------------------- #
    auth_names = {"arming switch", "operator arming file present",
                  "validation record present", "account matches the registry"}
    blocking = [c for c in checks if c[1] is False and c[3]]
    operational_ok = not blocking
    verdict = ("READY_TO_TRADE" if operational_ok and arming.armed else
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
            mark = "OFF " if name == "arming switch" else "WARN"
        else:
            mark = "FAIL"
        print(f"  [{mark}] {name:<38} {detail}")
    print()
    print(f"  authorisation: {'ARMED' if arming.armed else 'NOT ARMED'} — the venue "
          f"gate is a separate condition from machine readiness, and it is the "
          f"only one that cannot be fixed by configuring anything.")
    print()
    print(f"  market: next gold open {nxt:%Y-%m-%d %H:%M} UTC "
          f"({hours:.1f}h away)")
    print()
    if verdict == "READY_TO_TRADE":
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
    return 0 if operational_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
