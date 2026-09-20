#!/usr/bin/env python3
"""Supervise the paper trader: run it, append a daily summary, alert on trouble.

WHAT THIS IS FOR. `scripts/paper_trader.py` is a single supervised step. Something has
to decide *when* to take that step and notice when it stops being taken — otherwise a
paper run dies quietly and the first sign of trouble is an empty log, which is
indistinguishable from a quiet week.

THREE ALERTS, and why each exists:

1. **The day halted.** The ledger stopped trading for the day, for loss or for profit.
   That is the system working, not failing — but it is exactly the event an operator
   needs to know about, because it is the moment the account stopped doing anything.
2. **Stale state while the market is open.** The trader's last successful write is
   older than the tolerance. A paper run that silently stops is worse than one that
   errors, because nothing surfaces.
3. **The market being closed is NOT an alert.** It exits 0 and says so. The trigger
   fires every 20 minutes around the clock so it needs no timezone arithmetic; the
   supervisor decides whether there is anything to do, and a weekend must not
   manufacture 72 alerts.

Alerts are written to `artifacts/live/alerts.log` (append-only) and to stdout with an
`ALERT` prefix. There is deliberately NO outbound notification: sending mail needs
credentials this repo does not hold, and a half-configured alert path is one nobody
trusts. The log is the interface.

    python scripts/paper_supervisor.py            # one supervised cycle
    python scripts/paper_supervisor.py --force    # run even if the market looks closed
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LIVE = ROOT / "artifacts" / "live"
STATE = LIVE / "paper_state.json"
LEDGER = LIVE / "day_ledger.json"
SUMMARY = LIVE / "paper_daily.jsonl"
ALERTS = LIVE / "alerts.log"
COSTS = LIVE / "cost_samples.jsonl"

MARKET_OPEN_TICK_AGE_S = 900
STALE_TOLERANCE_MIN = 45


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _tick_age(now: datetime, symbol: str = "XAUUSD") -> float | None:
    """Seconds since the last tick, or None if the terminal cannot be asked."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    try:
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        return now.timestamp() - float(t.time)
    finally:
        mt5.shutdown()


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sampled_today(today: str) -> bool:
    """Whether a live cost sample already exists for this UTC day.

    Read from the JSONL the cost tool appends to, so the supervisor needs no state of
    its own and a manual run of the tool also suppresses the automatic one.
    """
    if not COSTS.is_file():
        return False
    try:
        for line in COSTS.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("utc", "").startswith(today):
                return True
    except (OSError, ValueError):
        return False
    return False


def _money(v, *, signed: bool = True) -> str:
    """Render a dollar figure that may be ABSENT, without crashing on it.

    ``signed=False`` for a BALANCE: a balance is a level, not a delta, and rendering
    one as "$+24,620.72" reads as a mistake even though it is not.

    Found by the tests: a state file with no `account.balance` made
    ``f"{balance:,.2f}"`` raise TypeError on None — after the summary had already been
    written, so the supervisor died with a traceback instead of returning its exit
    code. A missing balance is not an error condition; a supervisor that cannot report
    "unknown" is.
    """
    if v is None:
        return "unknown"
    try:
        return f"${float(v):+,.2f}" if signed else f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "unknown"


def _alert(text: str) -> None:
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    with ALERTS.open("a", encoding="utf-8") as fh:
        fh.write(f"{_utc().isoformat(timespec='seconds')} ALERT {text}\n")
    print(f"ALERT {text}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--steps", type=int, default=60,
                    help="bars to catch up over when the trader runs")
    ap.add_argument("--force", action="store_true",
                    help="run even if the market appears closed")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    now = _utc()
    print(f"=== PAPER SUPERVISOR — {now:%Y-%m-%d %H:%M UTC} ({now:%a}) ===")

    age = _tick_age(now, a.symbol)
    if age is None:
        _alert("cannot read a tick for " + a.symbol +
               " — the terminal is down, logged out, or the symbol is unresolvable. "
               "The paper trader cannot run.")
        return 2
    print(f"  last {a.symbol} tick: {age / 60:.0f} min ago")
    if age > MARKET_OPEN_TICK_AGE_S and not a.force:
        print(f"  market closed (tick older than "
              f"{MARKET_OPEN_TICK_AGE_S / 60:.0f} min). Nothing to supervise — "
              f"exiting 0 without touching state. A closed market is not an alert.")
        return 0

    # ---- staleness, checked BEFORE running so a dead trader is visible --------- #
    prev = _read(STATE)
    if prev is not None:
        last = prev.get("summary", {}).get("utc") or prev.get("last_run_utc")
        if last:
            try:
                then = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                mins = (now - then).total_seconds() / 60.0
                if mins > STALE_TOLERANCE_MIN:
                    _alert(f"paper state is {mins:.0f} min old (tolerance "
                           f"{STALE_TOLERANCE_MIN}) while the market is open — the "
                           f"trader may have stopped running")
            except ValueError:
                _alert(f"paper state has an unparseable timestamp {last!r}; staleness "
                       f"cannot be judged")
    else:
        print("  no prior paper state — this is the first supervised run")

    # ---- the live cost measurement, ONCE per UTC day during the session ------ #
    # Wired here rather than into its own scheduled task because the supervisor
    # already knows whether the market is open, and a cost sample taken while it is
    # closed would be a false reading (weekend spreads are much wider). Once per day
    # is enough: it answers "is the model optimistic?", which is not a question that
    # changes between bars.
    today = now.date().isoformat()
    if not a.dry_run and not _sampled_today(today):
        cost_cmd = [sys.executable, str(HERE / "measure_live_costs.py"),
                    "--symbol", a.symbol, "--samples", "20", "--interval", "3"]
        print("  sampling live costs for today (once per session day)")
        cp = subprocess.run(cost_cmd, capture_output=True, text=True, cwd=str(ROOT))
        for line in (cp.stdout or "").strip().splitlines()[-4:]:
            print(f"    | {line}")
        if cp.returncode == 1:
            _alert("the live spread is materially wider than the research cost model "
                   "(measure_live_costs.py exited 1). Verdicts that turned on a "
                   "small margin should be re-run with the measured cost.")
        elif cp.returncode != 0:
            print(f"    | cost measurement exited {cp.returncode}; not an alert "
                  f"(a closed/quiet market is the usual cause)")

    # ---- run the trader ------------------------------------------------------ #
    cmd = [sys.executable, str(HERE / "paper_trader.py"),
           "--symbol", a.symbol, "--steps", str(a.steps)]
    if a.dry_run:
        cmd.append("--dry-run")
    print(f"  running: {' '.join(Path(c).name for c in cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print(f"    | {line}")
    if proc.returncode != 0:
        _alert(f"paper trader exited {proc.returncode}: "
               f"{(proc.stderr or '').strip().splitlines()[-1] if proc.stderr else 'no stderr'}")
        return proc.returncode

    # ---- summarise and alert on the ledger ----------------------------------- #
    state = _read(STATE) or {}
    summary = state.get("summary", {})
    ledger = summary.get("ledger") or (_read(LEDGER) or {})
    acct = summary.get("account", {})
    row = {
        "utc": now.isoformat(timespec="seconds"),
        "symbol": a.symbol,
        "paper": True,
        "armed": summary.get("armed"),
        "balance": acct.get("balance"),
        "open_position": bool(acct.get("position")),
        "closed_fills": len(acct.get("closed", [])),
        "realised_today_usd": ledger.get("realised_usd"),
        "entries_today": ledger.get("entries"),
        "halted": bool(ledger.get("halted")),
        "halt_reason": ledger.get("halt_reason", ""),
        "decisions": len(summary.get("decisions", [])),
        "dry_run": a.dry_run,
    }
    if row["armed"]:
        _alert("the arming file is present and the gate reports ARMED. This "
               "supervisor and the paper trader never send orders, but an armed "
               "switch means something else in the system now believes it may.")
    if row["halted"]:
        _alert(f"day ledger HALTED for {a.symbol} ({row['halt_reason']}) with "
               f"{_money(row['realised_today_usd'])} realised today. Entries are "
               f"stopped for the rest of the day by design — this is the stop "
               f"working, and it is reported because it is the moment the account "
               f"stopped acting.")

    if not a.dry_run:
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        with SUMMARY.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"  appended to {SUMMARY.name}: balance "
              f"{_money(row['balance'], signed=False)}, "
              f"realised today {_money(row['realised_today_usd'])}, "
              f"halted={row['halted']}")
    else:
        print("  --dry-run: summary not appended")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
