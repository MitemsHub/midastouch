#!/usr/bin/env python3
"""Frequency axes on the venue's own corpus: which session window, which trigger threshold?

WHY THIS FILE EXISTS. MEASURED 2026-09-22 on the live arm, from its own ledger and its own
source, three facts that together explain a fill rate of zero:

  1. `InSessionBar()` compares `InpSessionStartHour`/`EndHour` against `TimeToStruct(iTime(...))`
     — MQL5 datetimes are SERVER time — while the input comments call those hours UTC. The
     venue's clock is server = UTC+2 (measured from the ledger: a bar opening 10:00 UTC is
     stamped 12:00). So the live arm's session is UTC 04:00-18:00.
  2. The python engine of record gates on TRUE UTC: `python_build_data(corpus="venue")` shifts
     the venue's bars into UTC with the window's pinned offset, and `run_mode` compares
     `fromtimestamp(b["time"], utc).hour` against `win_lo`/`win_hi` (defaults 6/20). Inside the
     tester the EA reads UTC-stamped bars, so the tester frame agrees and parity passes; LIVE,
     the same inputs describe a different window. The certified window is UTC 06:00-20:00, so
     the live arm trades two hours the certification never covered and misses its last two.
  3. The armed mode (REVERSE_DIRECTION) requires a trigger AND the H1/H4 regime anti-aligned
     with it, so the entry rate is set by how often that confluence occurs inside the window.

This is the measurement that was missing: the same certified engine, on the same corpus, with
the window and the trigger threshold as the only two axes. It calls `midas_sweep.run_mode`
UNCHANGED (every keyword left at its certified default except `win_lo`/`win_hi`, which the
engine already exposes for exactly this) and supplies the trigger array the engine reads —
`data["m15_bb"]`, which `run_mode` takes from the data dict rather than computing.

PRE-REGISTERED (docs/FREQUENCY_AXES_PREREG_20260922.md), before any of these numbers existed:
select on `wf` (2025-09-15 -> 2026-03-31), report on `oos` (2026-04-01 -> 2026-09-16), and treat
a cell as better than the incumbent ONLY if it improves the ENTRY RATE and does not lose more
than 0.10R of expectancy or 2R of drawdown on the held-out window.

SELF-CHECK. The harness refuses to print a table unless it first reproduces the pinned law for
the engine of record on this corpus: `wfv` at the account basis = 53 trades / +14.256R
(tests/test_midas_minlot_veto.py, re-pointed 2026-09-21). That is what makes the rest of this
table the same arithmetic rather than a lookalike.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_parity as P  # noqa: E402  the engine of record, on the venue's own bars
import midas_sweep as M  # noqa: E402  the certified mode engine and its metrics

ART = "artifacts"

#: (win_lo, win_hi) in TRUE UTC. 6/20 is the certified window (`M.SESSION_LO/HI`, the tester
#: frame, and what every cited number was measured on). 4/18 is what the live arm actually
#: does today on this venue's +2 clock. 8/22 is what the preset would have to say for the
#: live arm to land on the certified hours. The rest bracket the question: is it the FRAME
#: that costs fills, or is the window simply too narrow?
WINDOWS_UTC = [(6, 20), (4, 18), (8, 22), (4, 20), (6, 22), (0, 24)]

#: The trigger threshold: 2.0 is the frozen/live value, and the two below it are the only
#: direction that can add candidate bars (a smaller k = a band that is touched more often).
BB_KS = [2.0, 1.5, 1.0]

#: Selection span first, then the held-out one. Both are the repo's own pre-registered windows
#: (`M.WINDOWS`), not windows chosen here.
SEL_WINDOW = "wf"
TEST_WINDOW = "oos"


def self_check() -> None:
    """Reproduce the pinned venue-corpus law, or refuse to report anything else."""
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    finally:
        M._BASIS = prev
    n, total = len(rr.trades), sum(t["r"] for t in rr.trades)
    print(f"self-check  wfv {spec['mode']}: n={n} totalR={total:+.4f} vetoed={rr.vetoed}")
    if n != 53 or abs(total - 14.256) >= 5e-4:
        raise SystemExit(
            "REFUSING: this harness did not reproduce the pinned venue-corpus law "
            "(expected n=53 / +14.2560R). Every number below would be a lookalike.")
    print("            reproduced the pin -> the arithmetic below is the engine of record's.\n")


def day_stats(trades: list[dict], t0: int, t1: int) -> dict:
    """Entry frequency and the share of days with no entry at all, in the corpus' UTC frame.

    The zero-entry share is the number a prop account actually feels: a configuration that
    averages 0.7 entries/day but sits flat on 60% of days does not read as "active" no matter
    what its expectancy is.
    """
    days = set()
    d = t0 - (t0 % 86400)
    while d <= t1:
        days.add(d)
        d += 86400
    hit = {int(t["open_ct"]) - (int(t["open_ct"]) % 86400) for t in trades}
    nd = len(days)
    return {
        "days": nd,
        "per_day": round(len(trades) / nd, 3) if nd else 0.0,
        "zero_day_share": round(1 - len(hit & days) / nd, 3) if nd else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-selfcheck", action="store_true")
    args = ap.parse_args()
    if not args.skip_selfcheck:
        self_check()

    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    rows = []
    try:
        for wname in (SEL_WINDOW, TEST_WINDOW):
            spec = P._window_spec(wname)
            data = P.python_build_data(offset_min=P.assert_server_offset(spec),
                                       corpus="venue")
            mc = data["m15_close"]
            bb = {}
            for k in BB_KS:
                bb[k] = [M.bb_touch(mc, i, 20, k) for i in range(len(mc))]
            for lo, hi in WINDOWS_UTC:
                for k in BB_KS:
                    data["m15_bb"] = bb[k]
                    rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data,
                                    win_lo=lo, win_hi=hi)
                    m = M.metrics(rr.trades)
                    ds = day_stats(rr.trades, spec["t0"], spec["t1"])
                    rows.append({
                        "window": wname, "win_utc": [lo, hi], "k": k, "mode": spec["mode"],
                        "n": m.get("n", 0), "per_day": ds["per_day"],
                        "zero_day_share": ds["zero_day_share"], "days": ds["days"],
                        "exp": m.get("expectancy_r"), "pf": m.get("pf"),
                        "dd": m.get("max_dd_r"), "net_r": m.get("net_r"),
                        "win_rate": m.get("win_rate"), "vetoed": rr.vetoed,
                    })
    finally:
        M._BASIS = prev

    os.makedirs(ART, exist_ok=True)
    out = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "corpus": "venue", "basis": "ACCOUNT_BASIS_USD", "axes": {
               "windows_utc": WINDOWS_UTC, "bb_k": BB_KS,
               "select": SEL_WINDOW, "test": TEST_WINDOW},
           "rows": rows}
    path = os.path.join(ART, "midas_frequency_axes_20260922.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)

    for wname in (SEL_WINDOW, TEST_WINDOW):
        print(f"=== {wname} ({'SELECT' if wname == SEL_WINDOW else 'HELD OUT'}) "
              f"| mode {rows[0]['mode']} | venue corpus, account basis ===")
        hdr = (f"{'win UTC':>9}{'k':>5}{'n':>6}{'/day':>7}{'zero-day':>10}"
               f"{'expR':>8}{'pf':>7}{'win':>7}{'ddR':>7}{'netR':>9}")
        print(hdr)
        print("-" * len(hdr))
        for r in [x for x in rows if x["window"] == wname]:
            print(f"{str(r['win_utc'][0]) + '-' + str(r['win_utc'][1]):>9}{r['k']:>5}"
                  f"{r['n']:>6}{r['per_day']:>7.2f}{r['zero_day_share']*100:>9.1f}%"
                  f"{r['exp']:>8.3f}{str(r['pf']):>7}{r['win_rate']:>7.3f}"
                  f"{r['dd']:>7.1f}{r['net_r']:>9.2f}")
        print()
    print("artifact:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
