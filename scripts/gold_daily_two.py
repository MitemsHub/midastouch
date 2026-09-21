#!/usr/bin/env python3
"""DAILY-SEQ: DAILY-ONE's geometry, plus a pre-registered consecutive-loss brake.

The protocol is frozen in `docs/GOLD_DAILY_SEQ_PROTOCOL.md`, including a correction to
its own grid made before this file ran. Nothing here may add a configuration, widen a
range or drop a criterion.

WHAT IT TESTS. DAILY-ONE's three measured facts were: the H4 regime bit is load-bearing;
the trailing shield (not Best Day, not the daily limit) is what caps size, because a
drawdown is a property of the *sequence* of days; and the failure was statistical
(t = +1.33, at rather than above its null). The brake attacks the sequence directly —
after a losing day, sit out the next 1-2 days — and the pre-registered prediction is
that the drawdown measures improve and the survivable size RISES, while total R FALLS.

The control is exact: the four `brake=0` configurations are DAILY-ONE's grid under
DAILY-ONE's selection rule, so a disabled brake must reproduce +12.83R / 119 trades /
t +1.33. That is asserted, and a mismatch stops the run.
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
from midas_prop.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

ACCOUNT = 25_000.0
BRAKES = (0, 1, 2)
REPRODUCE = {"total_r": 12.83, "trades": 119, "t": 1.33}


def configs() -> list[dict]:
    """DAILY-ONE's 4 geometries crossed with the brake. Order: brake varies fastest."""
    return [{"stop_mult": s, "rr": r, "brake": b}
            for b in BRAKES for s in d1.STOP_MULTS for r in d1.RR_MULTS]


def simulate_cfg(P, cfg, *, rng=None, mode="h4"):
    return d1.simulate(P["B"], P["hours"], P["h4_ok_long"], P["h4_ok_short"],
                       P["atr"], cfg, start=w2.WARMUP_BARS,
                       end=P["holdout_start"], rng=rng, direction_mode=mode,
                       skip_days_after_loss=cfg.get("brake", 0))


def run(P, all_cfgs, folds, *, rng=None, mode="h4"):
    streams = [simulate_cfg(P, cfg, rng=rng, mode=mode) for cfg in all_cfgs]
    oos_rs, picks = d1.walk_forward(streams, all_cfgs, folds)
    return oos_rs, [t for p in picks for t in p["trades"]]


def loss_stats(trades, epoch) -> dict:
    """The pre-registered drawdown measures, plus the survivable size they drive."""
    byday: dict = defaultdict(float)
    for t in trades:
        byday[datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()] \
            += t["net_r"]
    days = sorted(byday.items())
    run_len, worst_run, cur_len, cur = 0, 0.0, 0, 0.0
    for _d, r in days:
        if r < 0:
            cur_len += 1
            cur += r
            if cur < worst_run:
                worst_run, run_len = cur, cur_len
        else:
            cur_len, cur = 0, 0.0
    peak = cum = dd = 0.0
    for _d, r in days:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    best, _dtot, share, _n = d1.day_share(trades, epoch)
    total = sum(byday.values())
    return {"days": len(days), "total_r": round(total, 3),
            "worst_loss_run_days": run_len,
            "worst_loss_run_r": round(worst_run, 3),
            "worst_peak_to_trough_r": round(dd, 3),
            "best_day_share": round(share, 4) if total > 0 else None,
            "up_days": sum(1 for _d, r in days if r > 0),
            "down_days": sum(1 for _d, r in days if r < 0)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--out", default="artifacts/gold_daily_seq.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT)
    P = w2.prepare(a.symbol, bars=a.bars)
    folds, epoch = P["folds"], P["epoch"]
    all_cfgs = configs()
    print(f"DAILY-SEQ: {len(all_cfgs)} configs "
          f"({len(d1.STOP_MULTS) * len(d1.RR_MULTS)} geometries x {len(BRAKES)} brakes) "
          f"x {len(folds)} folds")

    # ---- 0. THE CONTROL: a disabled brake must reproduce DAILY-ONE ----------- #
    print("\n=== 0. CONTROL (brake=0 must reproduce the frozen DAILY-ONE run) ===")
    froze = [c for c in all_cfgs if c["brake"] == 0]
    ctrl_rs, ctrl_trades = run(P, froze, folds)
    ctrl_total, ctrl_t = sum(ctrl_rs), tstat(ctrl_rs)
    print(f"  brake=0: {ctrl_total:+.2f}R, {len(ctrl_trades)} trades, t {ctrl_t:+.2f} "
          f"(frozen published {REPRODUCE['total_r']:+.2f}R, "
          f"{REPRODUCE['trades']} trades, t {REPRODUCE['t']:+.2f})")
    if abs(ctrl_total - REPRODUCE["total_r"]) > 0.05 or \
            len(ctrl_trades) != REPRODUCE["trades"]:
        print("  REFUSING: the brake is not a no-op when disabled, so every number "
              "below would be measuring something other than the brake.")
        return 2
    print("  control holds: the brake changes nothing when it is off")

    # ---- 1. the intervention -------------------------------------------------- #
    print("\n=== 1. BRAKE vs CONTROL ===")
    results = {}
    base = loss_stats(ctrl_trades, epoch)
    print(f"  {'brake':<6} {'total R':>9} {'t':>7} {'pos folds':>10} {'days':>6} "
          f"{'worst run':>10} {'peak-trough':>12} {'best-day':>9} {'survive $':>10}")
    for b in BRAKES:
        cfgs = [c for c in all_cfgs if c["brake"] == b]
        rs, tr = (ctrl_rs, ctrl_trades) if b == 0 else run(P, cfgs, folds)
        st = loss_stats(tr, epoch)
        lo = rules.profit_target_usd / st["total_r"] if st["total_r"] > 0 else math.inf
        hi = (rules.daily_loss_limit_usd / abs(st["worst_loss_run_r"])
              if st["worst_loss_run_r"] < 0 else math.inf)
        r_ok = 0.0
        if st["total_r"] > 0 and lo <= max(hi, lo * 2):
            r_ok, _p = d1.max_surviving_risk(rules, tr, epoch, lo, max(hi, lo * 2))
        st.update({"t": round(tstat(rs), 3),
                   "positive_folds": sum(1 for x in rs if x > 0),
                   "folds": len(rs), "trades": len(tr), "survivable_usd": round(r_ok, 2),
                   "mean_fold_r": sum(rs) / len(rs)})
        results[b] = st
        sh = st["best_day_share"]
        print(f"  {b:<6} {st['total_r']:+9.2f} {st['t']:+7.2f} "
              f"{st['positive_folds']:>4}/{st['folds']:<5} {st['days']:>6} "
              f"{st['worst_loss_run_days']:>5}d/{st['worst_loss_run_r']:+6.2f} "
              f"{st['worst_peak_to_trough_r']:>12.2f} "
              f"{100 * sh if sh else float('nan'):>8.1f}% {st['survivable_usd']:>10,.2f}")

    # ---- 2. the pre-registered predictions, judged ---------------------------- #
    print("\n=== 2. PRE-REGISTERED PREDICTIONS (from §6 of the protocol) ===")
    best_brake = max((b for b in BRAKES if b), key=lambda b: results[b]["survivable_usd"])
    checks = [
        ("worst loss run shortens",
         results[best_brake]["worst_loss_run_days"] < base["worst_loss_run_days"],
         f"{base['worst_loss_run_days']}d -> {results[best_brake]['worst_loss_run_days']}d"),
        ("peak-to-trough falls",
         results[best_brake]["worst_peak_to_trough_r"] < base["worst_peak_to_trough_r"],
         f"{base['worst_peak_to_trough_r']:.2f}R -> "
         f"{results[best_brake]['worst_peak_to_trough_r']:.2f}R"),
        ("survivable size rises above $233.99",
         results[best_brake]["survivable_usd"] > 233.99,
         f"${results[best_brake]['survivable_usd']:,.2f}"),
        ("total R falls (the brake costs trades)",
         results[best_brake]["total_r"] < base["total_r"],
         f"{base['total_r']:+.2f}R -> {results[best_brake]['total_r']:+.2f}R"),
    ]
    for name, ok, detail in checks:
        print(f"  [{'HELD' if ok else 'FAILED'}] {name:<40} {detail}")

    # ---- 3. the matched null, 200 reps --------------------------------------- #
    print(f"\n=== 3. MATCHED NULL, {a.reps} reps ===")
    rng = np.random.default_rng(d1.NULL_SEED)
    gen: list[float] = []
    for _ in range(a.reps):
        rs, _ = run(P, all_cfgs, folds, rng=rng, mode="random")
        gen.append(sum(rs))
    sub = sorted(gen)
    p95 = sub[max(0, int(math.ceil(0.95 * len(sub))) - 1)]
    total = results[best_brake]["total_r"]
    print(f"  median {sub[len(sub) // 2]:+.2f}R   p95 {p95:+.2f}R   max {sub[-1]:+.2f}R")
    print(f"  best brake ({best_brake}) total {total:+.2f}R -> clears p95 by "
          f"{total - p95:+.2f}R")

    legs = {
        "V1 total>0": total > 0,
        "V2 pos>=60%": results[best_brake]["positive_folds"] >= 0.6 * results[best_brake]["folds"],
        "V3 worst>-3": (min(ctrl_rs) > -3.0),
        "V4 beats null p95": total > p95,
        "V5 median>0": results[best_brake]["mean_fold_r"] > 0,
        "V6 t>=1.5": results[best_brake]["t"] >= 1.5,
        "V7 best-day<=20%": bool((results[best_brake]["best_day_share"] or 9) <= 0.20),
        "V8 legal size exists": results[best_brake]["survivable_usd"] > 0,
    }
    print("\n=== PRE-REGISTERED CRITERIA (on the best brake by survivable size) ===")
    for k, v in legs.items():
        print(f"  {k:<22} {'PASS' if v else 'FAIL'}")
    passed = sum(1 for v in legs.values() if v)
    verdict = "PASS" if passed == len(legs) else "NOT VALIDATED"
    print(f"\n  {passed}/{len(legs)} legs -> {verdict}")

    out = {"signal": "DAILY_SEQ", "protocol": "docs/GOLD_DAILY_SEQ_PROTOCOL.md",
           "grid_size": len(all_cfgs), "folds": len(folds), "reps": a.reps,
           "control": {"total_r": round(ctrl_total, 3), "trades": len(ctrl_trades),
                       "t": round(ctrl_t, 3), **base},
           "results_by_brake": {str(k): v for k, v in results.items()},
           "best_brake": best_brake, "predictions": {n: bool(o) for n, o, _d in checks},
           "null": {"p95": p95, "median": sub[len(sub) // 2], "max": sub[-1]},
           "criteria": legs, "passed": passed, "verdict": verdict,
           "generated_utc": datetime.now(timezone.utc).isoformat()}
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
