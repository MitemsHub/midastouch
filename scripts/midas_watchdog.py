#!/usr/bin/env python3
"""MIDASTOUCH watchdog — keep the gold paper arm provably alive.

Signals (both cheap, both file/process level):
  1. DEAD TERMINAL  — no terminal64.exe running from the default install
     (path-exact PID scan, same logic the parity driver trusts).
  2. STALE LEDGER   — the paper ledger's mtime older than STALE_S. The EA
     (v1.07+) heartbeats an EQ row every 900 s, timer-driven, so mtime is a
     LIVE signal: a healthy arm cannot look stale, even on weekends.

Actions, deliberately minimal:
  - Dead terminal (and no parity hold): relaunch detached via
    v28_sweep_runner.relaunch_terminal, then verify the ledger gains a fresh
    row (EA re-init writes ERA+EQ). Verified / unverified is recorded.
  - Stale ledger with terminal alive: ALERT ONLY — the terminal is not
    killed from a scheduled script (it could be mid-trade or mid-boot).
  - Parity hold: while scripts/.midas_terminal_hold exists (written by
    `midas_parity.py --run`), the watchdog does NOTHING structural.

Loop safety: max 3 relaunches per local day (state file). Further failures
same day are alert-only with a pointed message. All alerts (kind, count,
first/last seen) land in scripts/.midas_watchdog_state.json — that file is
the interface morning_status [3b] renders.

Usage:
  python scripts/midas_watchdog.py            # check + act (cron entry)
  python scripts/midas_watchdog.py --status   # report only, no action
  python scripts/midas_watchdog.py --no-relaunch  # detect + alert only

Exit codes: 0 healthy | 1 alert recorded/acted | 2 parity hold active
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v28_sweep_runner as R  # proven terminal-control helpers (parity driver)

TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, ".midas_watchdog_state.json")
HOLD_PATH = os.path.join(HERE, ".midas_terminal_hold")

HEARTBEAT_S = 900          # EA OnTimer period (v1.07)
STALE_S = 2 * HEARTBEAT_S  # two missed heartbeats = stale
VERIFY_WAIT_S = 120        # max wait for a fresh ledger row after relaunch
MAX_RELAUNCHES_PER_DAY = 3


# ── discovery (mirrors morning_status [3b]: profile files work when dead) ──
def find_arm() -> tuple[str, str, str] | None:
    """(terminal_dir, symbol, tag) of the MIDASTOUCH chart, or None."""
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        if not os.path.isdir(td):
            continue
        for chr_f in glob.glob(os.path.join(td, "MQL5", "Profiles", "Charts", "*", "*.chr")):
            try:
                txt = open(chr_f, encoding="utf-16", errors="replace").read()
            except OSError:
                continue
            if "MidastouchAI" not in txt:
                continue
            sym_m = re.search(r"^symbol=(\S+)", txt, re.M)
            tag_m = re.search(r"^InpArmTag=(\S*)\s*$", txt, re.M)
            sym = sym_m.group(1) if sym_m else "?"
            tag = (tag_m.group(1) if tag_m else "") or "M1"
            return td, sym, tag
    return None


def ledger_mtime(td: str, sym: str, tag: str) -> float | None:
    p = os.path.join(td, "MQL5", "Files", f"MIDASTOUCH_paper_{sym}_{tag}.csv")
    return os.path.getmtime(p) if os.path.exists(p) else None


# ── state (the morning_status interface) ───────────────────────────────────
def load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            st = json.load(f)
        if isinstance(st, dict):
            return st
    except (OSError, ValueError):
        pass
    return {}


def save_state(st: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(st, f, indent=1)


def record_alert(st: dict, kind: str, detail: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    alerts = st.setdefault("alerts", {})
    a = alerts.get(kind, {"count": 0, "first": None, "last": None, "detail": "", "day": None})
    if a.get("day") != today:          # new day: reset the counter, keep history lean
        a = {"count": 0, "first": None, "last": None, "detail": "", "day": today}
    a["count"] += 1
    a["first"] = a["first"] or datetime.now().isoformat(timespec="seconds")
    a["last"] = datetime.now().isoformat(timespec="seconds")
    a["detail"] = detail
    alerts[kind] = a
    st["last_alert"] = {"kind": kind, "ts": a["last"], "detail": detail}


def relaunches_today(st: dict) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    return st.get("relaunches", {}).get("day_count", 0) if st.get("relaunches", {}).get("day") == today else 0


def bump_relaunch(st: dict) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    r = st.get("relaunches", {})
    n = r.get("day_count", 0) + 1 if r.get("day") == today else 1
    st["relaunches"] = {"day": today, "day_count": n, "last": datetime.now().isoformat(timespec="seconds")}
    return n


# ── main check ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="report only, no action")
    ap.add_argument("--no-relaunch", action="store_true", help="detect + alert only")
    args = ap.parse_args()

    now = time.time()
    st = load_state()
    hold = False
    if os.path.exists(HOLD_PATH):
        try:                                   # self-heal: drop stale holds (dead PID)
            hold_pid = int(open(HOLD_PATH).read().strip() or 0)
            os.kill(hold_pid, 0)
            hold = True
        except (ValueError, OSError):
            os.remove(HOLD_PATH)

    arm = find_arm()
    pids = R.terminal_pids_exact()
    dead = not pids
    age_s = None
    if arm:
        mtime = ledger_mtime(*arm)
        age_s = (now - mtime) if mtime else None
    stale = arm is not None and (age_s is None or age_s > STALE_S)

    if args.status:
        print(f"arm: {arm[1]} tag {arm[2]} in {os.path.basename(arm[0])[:8]}" if arm else "arm: NO CHART")
        print(f"terminal pids: {pids or 'NONE'} | ledger age: "
              f"{f'{age_s:.0f}s' if age_s is not None else 'no ledger'} | stale(>{STALE_S}s): {stale}")
        print(f"parity hold: {hold} | relaunches today: {relaunches_today(st)}/{MAX_RELAUNCHES_PER_DAY}")
        if st.get("last_alert"):
            print("last alert:", st["last_alert"])
        return 2 if hold else (1 if (dead or stale) else 0)

    if hold:
        print("HOLD: parity run active — no structural action")
        return 2

    if not arm:
        record_alert(st, "no-chart", "no MIDASTOUCH chart profile found on any terminal")
        save_state(st)
        print("ALERT no-chart — attach the gold arm chart (watchdog cannot fix this)")
        return 1

    td, sym, tag = arm

    # 1) dead terminal → relaunch (capped) + verify
    if dead:
        n = relaunches_today(st)
        if n >= MAX_RELAUNCHES_PER_DAY:
            record_alert(st, "relaunch-cap", f"{n} relaunches today, still dead — manual look needed")
            save_state(st)
            print(f"ALERT relaunch-cap — {n} relaunches today and the terminal is still dead")
            return 1
        print(f"terminal dead — relaunching ({n + 1}/{MAX_RELAUNCHES_PER_DAY} today)")
        before = ledger_mtime(td, sym, tag) or 0
        R.relaunch_terminal()
        bump_relaunch(st)
        ok = False
        deadline = time.time() + VERIFY_WAIT_S
        while time.time() < deadline:
            m = ledger_mtime(td, sym, tag) or 0
            if m > before:
                ok = True
                break
            time.sleep(5)
        if ok:
            print("relaunch verified: ledger gained a fresh row")
            st["last_relaunch"] = {"ts": datetime.now().isoformat(timespec="seconds"), "verified": True}
        else:
            record_alert(st, "relaunch-unverified", "terminal relaunched but ledger has no fresh row yet")
            st["last_relaunch"] = {"ts": datetime.now().isoformat(timespec="seconds"), "verified": False}
            print("ALERT relaunch-unverified — terminal may still be booting; next check will tell")
        save_state(st)
        return 1 if not ok else 0

    # 2) stale ledger with terminal alive → alert only
    if stale:
        detail = (f"ledger age {age_s:.0f}s > {STALE_S}s with terminal alive"
                  if age_s is not None else "ledger missing while terminal runs")
        record_alert(st, "stale-ledger", detail)
        save_state(st)
        print("ALERT stale-ledger —", detail)
        return 1

    print(f"healthy: arm {sym}/{tag}, ledger age {age_s:.0f}s, terminal pid(s) {pids}")
    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
