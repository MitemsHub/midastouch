#!/usr/bin/env python3
"""Can this account pass a 30-trade evaluation? (bootstrap of the rule's own held-out fills)

WHY THIS FILE EXISTS. The arm is armed and its operator is asking the right question in the
wrong unit: "we are not trading enough" is about COUNT, while the evaluation gate is about
SIGN. A prop evaluation needs **30 closed trades with positive expectancy**, and with a
near-zero edge the count is not what decides that — 30 more coin flips converge to a coin
flip, and 300 more converge closer to one.

WHAT IT MEASURES. Resampling (with replacement) from the armed mode's OWN held-out fills
`oos` 2026-04-01 -> 2026-09-16, the engine of record's trade set, unchanged:

  * P(net R > 0) over a 30-trade block, and the net-R distribution's p05/p50/p95;
  * the drawdown INSIDE such a block (median, p90), in R and as a share of the account at the
    measured dollar-per-R of the live fill;
  * days to reach 30 trades at each mode's own held-out frequency.

WHAT IT CANNOT BE. The resample carries the window's own mix; if that window is not the
future, this is a statement about the rule's history and not a forecast. It is a POWER
statement: it says what the gate would do to this trade distribution, repeatedly. It is not a
profitability claim, and it justifies no change to the rule.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402

MODE = "REVERSE_DIRECTION"
MODES = ("REVERSE_DIRECTION", "ORIGINAL", "TRIGGER_ONLY", "REVERSE_TRIGGER", "SHORT_ONLY")
SEL_WINDOW, TEST_WINDOW = "wf", "oos"
DRAWS, BLOCK = 20000, 30
#: the live fill's own bracket: 0.01 lots, stop 41.31 USD/oz on XAUUSD (100 oz/lot) and the
#: account it was taken on. Used ONLY to express R in account terms, never to size anything.
USD_PER_R, ACCOUNT_USD = 41.31, 25004.26
ART = Path("artifacts") / "midas_eval_power_20260922.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=DRAWS)
    args = ap.parse_args()
    rng = random.Random(20260922)

    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    out: dict = {"harness": "midas_eval_power.py",
                 "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "engine": "midas_sweep.run_mode (unchanged)",
                 "split": {"select": SEL_WINDOW, "report": TEST_WINDOW},
                 "block_trades": BLOCK, "draws": args.draws,
                 "account_usd": ACCOUNT_USD, "usd_per_r": USD_PER_R,
                 "windows": {}}
    try:
        for wname in (SEL_WINDOW, TEST_WINDOW):
            spec = P._window_spec(wname)
            data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
            days = (spec["t1"] - spec["t0"]) / 86400.0
            rows: dict[str, dict] = {}
            for mode in MODES:
                rs = [t["r"] for t in M.run_mode(mode, spec["t0"], spec["t1"], data).trades]
                if len(rs) < 5:
                    rows[mode] = {"n": len(rs), "note": "too few fills to resample"}
                    continue
                nets, dds = [], []
                for _ in range(args.draws):
                    eq = peak = dd = 0.0
                    for _ in range(BLOCK):
                        eq += rng.choice(rs)
                        peak = max(peak, eq)
                        dd = max(dd, peak - eq)
                    nets.append(eq)
                    dds.append(dd)
                nets.sort()
                dds.sort()
                rows[mode] = {
                    "n": len(rs), "expR": round(statistics.mean(rs), 4),
                    "sdR": round(statistics.stdev(rs), 4),
                    "per_day": round(len(rs) / days, 3),
                    "days_to_block": round(BLOCK / (len(rs) / days), 1),
                    "p_net_positive": round(sum(1 for x in nets if x > 0) / args.draws, 4),
                    "netR": {"p05": round(nets[int(args.draws * 0.05)], 2),
                             "median": round(nets[args.draws // 2], 2),
                             "p95": round(nets[int(args.draws * 0.95)], 2)},
                    "block_ddR": {"median": round(dds[args.draws // 2], 2),
                                  "p90": round(dds[int(args.draws * 0.9)], 2),
                                  "p90_pct_of_account": round(dds[int(args.draws * 0.9)]
                                                              * USD_PER_R / ACCOUNT_USD * 100, 2)},
                }
            out["windows"][wname] = {"t0": spec["t0"], "t1": spec["t1"],
                                     "days": round(days, 1), "modes": rows}
    finally:
        M._BASIS = prev

    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for wname in (SEL_WINDOW, TEST_WINDOW):
        w = out["windows"][wname]
        print(f"=== {wname}  {w['days']} days  (block = {BLOCK} trades, {args.draws} draws)")
        print(f"  {'mode':18s} {'n':>4s} {'expR':>8s} {'sdR':>6s} {'P(net>0)':>9s} "
              f"{'p05':>7s} {'med':>7s} {'p95':>7s} {'medDD':>6s} {'p90DD':>6s} {'days':>6s}")
        for mode, r in w["modes"].items():
            if "p_net_positive" not in r:
                print(f"  {mode:18s} {r['n']:4d}  {r.get('note')}")
                continue
            print(f"  {mode:18s} {r['n']:4d} {r['expR']:+8.4f} {r['sdR']:6.2f} "
                  f"{r['p_net_positive']:9.1%} {r['netR']['p05']:+7.2f} {r['netR']['median']:+7.2f} "
                  f"{r['netR']['p95']:+7.2f} {r['block_ddR']['median']:6.2f} "
                  f"{r['block_ddR']['p90']:6.2f} {r['days_to_block']:6.0f}")
        print()
    print(f"account basis: 1R = ${USD_PER_R} = {USD_PER_R / ACCOUNT_USD * 100:.3f}% of "
          f"${ACCOUNT_USD}; artifact: {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
