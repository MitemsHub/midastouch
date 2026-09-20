#!/usr/bin/env python3
"""Three questions DAILY-ONE's own result raised, answered without touching the grid.

The protocol is frozen (`docs/GOLD_DAILY_ONE_PROTOCOL.md`) and this script does not
edit it. Each experiment here interrogates a *component* or the *evidence*, not the
signal's parameters:

1. **Is the H4 regime bit doing any work?** DAILY-ONE took its direction from a single
   comparison, `h4_close > h4_ema20`. If always-long scores about the same, then the
   "regime filter" was never a filter — it was a proxy for a market that went up, and
   the apparent edge belongs to gold's trend rather than to the logic. Controls:
   always-long, always-short, and H4 inverted.
2. **Was V4 (beats the null) noise?** The run cleared the null's p95 by 0.50R against a
   null whose maximum was +24.16R, which is exactly the margin a 32-replication p95
   cannot adjudicate. This raises the replications and reports how the p95 moves.
3. **What is the trailing-shield constraint, in loss sequences?** V8 failed on the 6%
   trail floor rather than on any single day. That makes it a property of SEQUENCES, so
   it is characterised as one: the worst run of consecutive losing days, and the largest
   risk per trade at which the account still survives.

Nothing here may add a configuration to the pre-registered grid. The grid is 4; if a
result needs a fifth configuration to look good, that is the answer.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_daily_one as d1  # noqa: E402
import gold_wfo_v2 as w2  # noqa: E402
from gold_walkforward import tstat  # noqa: E402
from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

ACCOUNT = 25_000.0
REPRODUCE_TOTAL_R = 12.83   # the frozen run's published figure, tolerance below


def run_variant(P, all_cfgs, folds, *, mode: str, rng=None) -> tuple[list[float],
                                                                   list[dict]]:
    trades = [d1.simulate(P["B"], P["hours"], P["h4_ok_long"], P["h4_ok_short"],
                          P["atr"], cfg, start=w2.WARMUP_BARS,
                          end=P["holdout_start"], rng=rng, direction_mode=mode)
              for cfg in all_cfgs]
    oos_rs, picks = d1.walk_forward(trades, all_cfgs, folds)
    return oos_rs, [t for p in picks for t in p["trades"]]


def day_series(trades: list[dict], epoch) -> list[tuple[str, float]]:
    out: dict = defaultdict(float)
    for t in trades:
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()
        out[d] += t["net_r"]
    return sorted(out.items())


def loss_sequences(days: list[tuple[str, float]]) -> dict:
    """The trailing drawdown, described as the sequences that cause it.

    The shield floors equity 6% below its high-water mark, so it is breached by a
    *run* of bad days after a good one, not by any single day. Reporting the worst run
    and the worst peak-to-trough is therefore the only description that matches the
    rule; a "worst day" number, which is what V8's window used, cannot express it.
    """
    worst_run_len, worst_run_r = 0, 0.0
    cur_len, cur_r = 0, 0.0
    for _d, r in days:
        if r < 0:
            cur_len += 1
            cur_r += r
            if cur_r < worst_run_r:
                worst_run_r, worst_run_len = cur_r, cur_len
        else:
            cur_len, cur_r = 0, 0.0
    peak, cum, worst_dd, worst_dd_pct = 0.0, 0.0, 0.0, 0.0
    for _d, r in days:
        cum += r
        peak = max(peak, cum)
        dd = peak - cum
        if dd > worst_dd:
            worst_dd, worst_dd_pct = dd, (dd / peak if peak > 0 else float("inf"))
    return {"days": len(days),
            "worst_consecutive_loss_run_days": worst_run_len,
            "worst_consecutive_loss_run_r": round(worst_run_r, 2),
            "worst_peak_to_trough_r": round(worst_dd, 2),
            "worst_drawdown_as_frac_of_peak_profit": round(worst_dd_pct, 3),
            "total_r": round(cum, 2),
            "up_days": sum(1 for _d, r in days if r > 0),
            "down_days": sum(1 for _d, r in days if r < 0)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--out", default="artifacts/gold_daily_one_ablation.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT)
    P = w2.prepare(a.symbol, bars=a.bars)
    folds, all_cfgs = P["folds"], d1.configs()
    epoch = P["epoch"]

    # ---- 0. reproduce the frozen run, so the controls are comparable ------ #
    oos_rs, oos_trades = run_variant(P, all_cfgs, folds, mode="h4")
    total = sum(oos_rs)
    print(f"=== 0. BASELINE REPRODUCTION ===")
    print(f"  {total:+.2f}R over {len(oos_trades)} trades, t {tstat(oos_rs):+.2f} "
          f"(frozen run published +{REPRODUCE_TOTAL_R}R / 119 trades)")
    if abs(total - REPRODUCE_TOTAL_R) > 0.05:
        print("  REFUSING: the baseline does not reproduce the pre-registered run. "
              "Any ablation below would be measured against a different signal.")
        return 2

    days = day_series(oos_trades, epoch)

    # ---- 1. does the H4 bit do any work? --------------------------------- #
    print("\n=== 1. DIRECTION ABLATION (is the H4 regime bit load-bearing?) ===")
    ablation = {}
    _r, base_trades = oos_rs, oos_trades
    base_days = days
    base_best = {"worst_run_r": loss_sequences(base_days)[
        "worst_consecutive_loss_run_r"]}
    print(f"  {'variant':<12} {'total R':>9} {'R/trade':>9} {'t':>7} "
          f"{'pos folds':>10} {'best-day share':>15}")
    for mode, label in (("h4", "h4 (frozen)"), ("long", "always long"),
                        ("short", "always short"), ("invert", "h4 inverted")):
        rs, tr = run_variant(P, all_cfgs, folds, mode=mode)
        tot = sum(rs)
        best, dtot, share, _nd = d1.day_share(tr, epoch)
        ablation[mode] = {"total_r": round(tot, 2), "t": round(tstat(rs), 2),
                          "positive_folds": sum(1 for x in rs if x > 0),
                          "folds": len(rs), "trades": len(tr),
                          "best_day_share": round(share, 4) if dtot > 0 else None}
        print(f"  {label:<12} {tot:+9.2f} "
              f"{tot / len(tr) if tr else 0:+9.4f} {tstat(rs):+7.2f} "
              f"{sum(1 for x in rs if x > 0):>4}/{len(rs):<5} "
              f"{100 * share if dtot > 0 else float('nan'):>14.1f}%")
    only_long = ablation["long"]["total_r"]
    verdict = ("the H4 bit is NOT doing the work - gold trended up"
               if only_long > 0.7 * total
               else "the H4 bit adds something beyond a long bias")
    print(f"\n  reading: always-long scores {only_long:+.2f}R against the frozen "
          f"signal's {total:+.2f}R ({verdict})")

    # ---- 2. was V4 noise? raise the replications -------------------------- #
    print(f"\n=== 2. NULL STABILITY ({a.reps} reps; where does the actual sit?) ===")
    rng = np.random.default_rng(d1.NULL_SEED)
    gen_order: list[float] = []
    for _ in range(a.reps):
        rs, _ = run_variant(P, all_cfgs, folds, mode="random", rng=rng)
        gen_order.append(sum(rs))
    # NOTE: prefixes are taken in GENERATION order and sorted within the prefix.
    # The first version sorted the whole list and then took prefixes of the sorted
    # list, i.e. the n SMALLEST totals, which produced the impossible reading
    # "p95 = -13.25R but max = -12.76R" and a p95 that climbed 26R with more reps.
    # A cumulative statistic must be computed over a random sample, not over the
    # bottom of the distribution.
    stability = []
    for n in (32, 64, 128, 200):
        if n > len(gen_order):
            break
        sub = sorted(gen_order[:n])
        p95 = sub[max(0, int(math.ceil(0.95 * n)) - 1)]
        stable = {"reps": n, "p95": round(p95, 2), "max": round(sub[-1], 2),
                  "median": round(sub[len(sub) // 2], 2),
                  "actual_clears": bool(total > p95),
                  "margin_r": round(total - p95, 2)}
        stability.append(stable)
        print(f"  {n:>4} reps: p95 {p95:+8.2f}R  max {sub[-1]:+8.2f}R  "
              f"median {sub[len(sub) // 2]:+8.2f}R  -> actual clears by "
              f"{total - p95:+.2f}R")
    first, last = stability[0], stability[-1]
    print(f"\n  reading: the p95 moved {last['p95'] - first['p95']:+.2f}R between 32 "
          f"and {last['reps']} reps. A margin of {first['margin_r']:+.2f}R at 32 reps "
          f"becomes {last['margin_r']:+.2f}R at {last['reps']} — "
          f"{'the PASS survives, but on a distribution that is itself uncertain' if last['actual_clears'] else 'the PASS does NOT survive more replications'}.")

    # ---- 3. the trailing shield, as sequences ----------------------------- #
    print("\n=== 3. TRAILING SHIELD: the loss sequences, not the worst day ===")
    seq = loss_sequences(base_days)
    for k, v in seq.items():
        print(f"  {k:<44} {v}")
    lo_r = rules.profit_target_usd / total
    worst_day = min(r for _d, r in base_days)
    naive_hi = rules.daily_loss_limit_usd / abs(worst_day)
    print(f"\n  the window V8 used (worst DAY):  ${lo_r:,.2f} .. ${naive_hi:,.2f}")
    r_best, prop = d1.max_surviving_risk(rules, oos_trades, epoch,
                                         lo_r, max(naive_hi, lo_r * 2))
    if r_best > 0:
        print(f"  the largest size that actually SURVIVES (bisected): ${r_best:,.2f} "
              f"per trade")
        print(f"    equity ${prop['final_equity']:,.2f}  target "
              f"{'MET' if prop['target_met'] else 'not met'}  daily breaches "
              f"{len(prop['daily_breaches'])}  shield breaches "
              f"{len(prop['shield_breaches'])}")
        print(f"  -> the true ceiling is {100 * r_best / naive_hi:.0f}% of what the "
              f"single-day bound implied. The gap IS the sequence constraint.")
    else:
        print("  NO size survives: the trail floor is breached at every size that "
              "meets the target, so this signal cannot be traded on this account.")

    out = {"baseline_total_r": round(total, 2), "baseline_t": round(tstat(oos_rs), 3),
           "trades": len(oos_trades), "ablation": ablation,
           "null_stability": stability, "loss_sequences": seq,
           "v8_naive_window": [round(lo_r, 2), round(naive_hi, 2)],
           "max_surviving_risk_usd": round(r_best, 2),
           "generated_utc": datetime.now(timezone.utc).isoformat()}
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
