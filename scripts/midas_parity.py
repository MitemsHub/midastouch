#!/usr/bin/env python3
"""MIDASTOUCH Step 5 — build parity (protocol §8).

Runs MidastouchAI.ex5 in the strategy tester on the WF window with the exact
frozen inputs, then aligns the EA's per-trade "Trade R:" lines (in order)
with the python research engine's per-trade R for the same window/mode.

Tolerance: max |dR| <= 0.01R per trade (the V75 house standard) AND identical
trade count. Divergences are reported per trade — a systematic skew names the
mechanism (fill model, spread source, timeout boundary) rather than waving it
through. Terminal must be STOPPED (run_pass fast-fails otherwise).

Output: artifacts/midas_parity_result_<date>.json
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, "scripts")
sys.path.insert(0, "tests")

import v75_tester_runner as T                       # noqa: E402
import v28_sweep_runner as R                        # noqa: E402

# --- point the house runner at the default install (49E0 data folder) -------
from pathlib import Path
T.TERMINAL_EXE = Path(R.TERM_EXE)
T._BASE_TESTER_INI["Symbol"] = "XAUUSD"
T._BASE_TESTER_INI["Period"] = "M15"
T._BASE_TESTER_INI["Leverage"] = "1000"
T._BASE_TESTER_INI["Deposit"] = "1000"

EXPERT = r"MITEMSHUB_AI\MidastouchAI"
TAG = "midas_wf_rd"

INPUTS = {
    "InpMagic": "7801001",
    "InpArmTag": "M1",
    "InpMode": "1",                  # REVERSE_DIRECTION
    "InpMacroEmaPeriod": "20",
    "InpBBPeriod": "20",
    "InpBBDev": "2.0",
    "InpRSIPeriod": "14",
    "InpRSIUpper": "70.0",
    "InpRSILower": "30.0",
    "InpAtrPeriod": "14",
    "InpSlAtrMult": "2.0",
    "InpTpMult": "2.0",
    "InpTimeoutMinutes": "720",
    "InpSessionStartHour": "6",
    "InpSessionEndHour": "20",
    "InpSpreadCapPctStop": "1.5",
    "InpFridayCutoffHour": "20",
    "InpUseNewsFilter": "false",
    "InpStaleMinutes": "30",
    "InpRiskPercent": "1.0",
    "InpLiveExecution": "false",
    "InpPaperEquity": "5000.0",   # = python START_EQUITY: identical sizing path
}

DATES = ("2025.09.15", "2026.03.31")
TRADE_R_RE = re.compile(r"Trade R: ([+-]?\d+\.\d+)")


def journal_trade_rs(snaps: dict) -> list[float]:
    """All 'Trade R:' values in the appended journal bytes, in order."""
    out: list[float] = []
    for log in T.journal_paths():
        offset = snaps.get(log, 0)
        try:
            blob = log.read_bytes()[offset:].decode("utf-16-le", "ignore")
        except OSError:
            continue
        out += [float(m) for m in TRADE_R_RE.findall(blob)]
    return out


def main() -> int:
    # terminal must be stopped
    pids = R.terminal_pids_exact()
    if pids:
        print(f"terminal running (pids {pids}) — stopping first")
        R.stop_terminal(pids)

    snaps = T.journal_snapshots()
    print(f"journal anchors: {[str(p.name) + '@' + str(o) for p, o in snaps.items()]}")
    print(f"running tester pass tag={TAG} expert={EXPERT} dates={DATES} "
          f"symbol={T._BASE_TESTER_INI['Symbol']} (real ticks; first run may download — be patient)")
    res = T.run_pass(TAG, INPUTS, timeout_s=3600, dates=DATES, expert=EXPERT)
    print("tester metrics:", json.dumps(res.get("report_stats", res), default=str)[:400])

    import time
    time.sleep(8)   # agent flushes its journal after the report appears
    ea_rs = journal_trade_rs(snaps)
    py_rs = json.load(open("artifacts/midas_parity_python_wf_rd.json"))

    n = min(len(ea_rs), len(py_rs))
    diffs = [abs(a - b) for a, b in zip(ea_rs[:n], py_rs[:n])]
    max_d = max(diffs) if diffs else None
    count_match = len(ea_rs) == len(py_rs)
    tol = 0.01
    verdict = ("PASS" if count_match and max_d is not None and max_d <= tol
               else "FAIL")

    print("=" * 70)
    print(f"python trades: {len(py_rs)}  sumR {sum(py_rs):+.3f}")
    print(f"EA trades:     {len(ea_rs)}  sumR {sum(ea_rs):+.3f}")
    print(f"count match:   {count_match}")
    print(f"max |dR|:      {max_d}")
    print(f"PARITY:        {verdict}")
    if verdict == "FAIL":
        for i, (a, b) in enumerate(zip(ea_rs[:n], py_rs[:n])):
            if abs(a - b) > tol:
                print(f"  trade {i}: ea {a:+.4f} vs py {b:+.4f} (dR {a-b:+.4f})")
        if not count_match:
            print(f"  trade-count skew: ea has {len(ea_rs)-len(py_rs):+d} trades")

    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "expert": EXPERT, "tag": TAG, "dates": DATES, "symbol": "XAUUSD",
        "python": {"n": len(py_rs), "sum_r": round(sum(py_rs), 4)},
        "ea": {"n": len(ea_rs), "sum_r": round(sum(ea_rs), 4)},
        "count_match": count_match,
        "max_abs_dR": max_d,
        "tolerance": tol,
        "verdict": verdict,
        "per_trade_dR": [round(a - b, 5) for a, b in zip(ea_rs[:n], py_rs[:n])],
    }
    path = f"artifacts/midas_parity_result_{datetime.now():%Y%m%d}.json"
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    print("artifact:", path)

    # restore the terminal for the paper arm step
    R.relaunch_terminal()
    print("terminal relaunched")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
