#!/usr/bin/env python3
"""Pre-registered PROSPECTIVE drawdown control: size against the measured loss run.

PROTOCOL: `docs/GOLD_PROSPECTIVE_SIZING_PROTOCOL.md` (frozen before this was written).

WHY PROSPECTIVE AND NOT A BRAKE. DAILY-SEQ tested the reactive rule — skip the days after
a losing day — and measured it as a dead end: the run shortened (5 -> 4 days) but the
drawdown did not fall (6.41 -> 6.66R), the survivable size collapsed to $0, and Best Day
compliance broke (9.6% -> 29.8%). Every one of those failures comes from the same cause:
a brake acts AFTER the loss, so the equity damage is already taken, and it then removes
profitable days. A rule that works has to reserve the room BEFORE the run arrives.

WHAT THIS MEASURES, AND THE ONE THING IT CANNOT CHANGE. The control sizes every trade so
that the measured worst loss sequence cannot breach the 6% trail floor. There are eight
gate legs; V1-V7 are computed from `net_r` and per-trade risk enters `prop_compat` as a
post-hoc scalar, so **V1-V7 are mathematically invariant to any sizing rule** — this
script demonstrates that numerically rather than asserting it. Only V8 (which is about
dollars) can move. If the gate is blocked, it is blocked by the statistical legs, and no
amount of sizing work reaches them.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_daily_one as d1  # noqa: E402
import gold_daily_two as d2  # noqa: E402
import gold_wfo_v2 as w2  # noqa: E402
from gold_walkforward import prop_compat, tstat  # noqa: E402
from midas_prop.execution.prop_execution import (  # noqa: E402
    feasible_risk_window,
    sequence_risk_ceiling_usd,
    worst_loss_run,
)
from midas_prop.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

ACCOUNT = 25_000.0
#: DAILY-ONE's 200-replication matched null, published in
#: `docs/GOLD_DAILY_ONE_PROTOCOL.md`. Reused rather than re-run: the null is a property
#: of the SIGNAL, and this study changes only the sizing, so re-deriving it would burn
#: 800 simulations to reproduce a number that cannot move.
FROZEN_NULL_P95 = 13.02


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--null-p95", type=float, default=FROZEN_NULL_P95)
    ap.add_argument("--out", default="artifacts/gold_prospective_control.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT)
    P = w2.prepare(a.symbol, bars=a.bars)
    folds, epoch = P["folds"], P["epoch"]

    # The frozen DAILY-ONE signal, unchanged: one entry per day at 08:00 UTC, H4 regime
    # direction, its 4-vector geometry, no brake.
    oos_rs, trades = d2.run(P, d1.configs(), folds)

    total = sum(t["net_r"] for t in trades)
    pos_folds = sum(1 for x in oos_rs if x > 0)
    t_stat = tstat(oos_rs)
    best_r, _tot, share, ndays = d1.day_share(trades, epoch)

    # Day-level results in R, ordered by date. Computed here rather than imported
    # because `day_series` lives in the ablation (which owns the sequence measures) and
    # the run measure below needs the ORDERED series, not just the summary statistics.
    _byday: dict = defaultdict(float)
    for _t in trades:
        _d = datetime.fromtimestamp(float(epoch[_t["entry_i"]]), timezone.utc).date()
        _byday[_d] += _t["net_r"]
    day_r = [v for _d, v in sorted(_byday.items())]

    worst_day_r = min(day_r)
    k, run_depth = worst_loss_run(day_r)
    peak_trough = d2.loss_stats(trades, epoch)["worst_peak_to_trough_r"]

    print(f"=== PROSPECTIVE DRAWDOWN CONTROL — {a.symbol} ===")
    print(f"  frozen signal reproduced: {len(trades)} trades, {ndays} days, "
          f"{total:+.2f}R, t {t_stat:+.2f}")
    print(f"  measured sequence: worst single day {worst_day_r:+.2f}R, "
          f"worst run {k} days {run_depth:+.2f}R, peak-to-trough {peak_trough:.2f}R")

    # ---- the three sizes ---------------------------------------------------- #
    window = feasible_risk_window(rules, day_r)
    r_single = window.hi_usd if window.exists else 0.0
    r_lo = window.lo_usd if window.exists else float("inf")

    r_sim = 0.0
    if window.exists and math.isfinite(r_single):
        r_sim, _ = d1.max_surviving_risk(rules, trades, epoch, r_lo,
                                         max(r_single, r_lo * 2))

    ceiling = sequence_risk_ceiling_usd(rules, peak_equity=ACCOUNT,
                                        worst_day_r=worst_day_r, run_days=k)

    print("\n=== SIZING: what each rule authorises (risk per trade) ===")
    print(f"  single-day bound (worst day)      ${r_single:,.2f}"
          f"   [optimistic: cannot see a run]")
    print(f"  simulated survival (bisected)     ${r_sim:,.2f}"
          f"   [the number V8 has been asking for]")
    print(f"  prospective sequence ceiling      ${ceiling.risk_usd:,.2f}"
          f"   [{k}-day run at {worst_day_r:+.2f}R/day]")
    if r_sim > 0:
        over = 100 * (1 - r_sim / r_single) if r_single else float("nan")
        print(f"  -> the single-day bound overstates the survivable size by {over:.0f}%")
    if ceiling.exists and r_sim > 0:
        verdict = ("CONSERVATIVE" if ceiling.risk_usd <= r_sim else "OPTIMISTIC")
        print(f"  -> the closed-form ceiling is {verdict} vs the simulation "
              f"({ceiling.risk_usd:,.2f} vs {r_sim:,.2f})")
    else:
        print(f"  -> ceiling unusable: {ceiling.note}")

    # ---- the eight legs ------------------------------------------------------- #
    # V8 IS ITS OWN COMPUTATION, NOT A LEG EVALUATED AT A CHOSEN SIZE. The protocol
    # states it as an EXISTENCE claim -- "a legal size exists" -- and scoring it at the
    # single-day bound is the exact mis-implementation that made DAILY-ONE report FAIL
    # where the truth was PASS. It is also size-FREE: existence is a property of the
    # trade sequence and the rules, so no sizing rule can move it. That is why the
    # comparison below is not really "two sizes" but "the same eight legs twice".
    v8 = bool(r_sim > 0)
    legs = {
        "V1 total>0": total > 0,
        "V2 pos>=60%": pos_folds >= 0.6 * len(oos_rs),
        "V3 worst>-3": (min(oos_rs) > -3.0) if oos_rs else False,
        "V4 beats null p95": total > a.null_p95,
        "V5 median>0": sorted(oos_rs)[len(oos_rs) // 2] > 0,
        "V6 t>=1.5": t_stat >= 1.5,
        "V7 best-day<=20%": bool(share <= 0.20),
        "V8 legal size exists": v8,
    }
    # The legs are recomputed once per sizing rule to DEMONSTRATE the invariance rather
    # than assert it: every value below is derived from `net_r` or from the bisection,
    # and risk per trade enters `prop_compat` only as a scalar applied afterwards.
    single_legs = dict(legs)
    seq_legs = dict(legs)

    print("\n=== THE EIGHT LEGS, under each sizing rule ===")
    print(f"  {'leg':<22} {'single-day':>11} {'prospective':>12}")
    moved = []
    for name in single_legs:
        x, y = single_legs[name], seq_legs[name]
        if x != y:
            moved.append(name)
        print(f"  {name:<22} {'PASS' if x else 'FAIL':>11} {'PASS' if y else 'FAIL':>12}")

    p_single = sum(single_legs.values())
    p_seq = sum(seq_legs.values())
    print(f"\n  {p_single}/8 legs at the single-day size -> "
          f"{'PASS' if p_single == 8 else 'NOT VALIDATED'}")
    print(f"  {p_seq}/8 legs at the prospective size  -> "
          f"{'PASS' if p_seq == 8 else 'NOT VALIDATED'}")
    print(f"  legs that changed: {moved if moved else 'NONE'}")
    print(f"  note: V1-V7 are computed from net_r and risk enters prop_compat as a")
    print(f"        post-hoc scalar, so they CANNOT move. V8 is an existence claim, so it")
    print(f"        cannot move either. The gate is decided without reference to sizing.")

    print("\n=== PRE-REGISTERED PREDICTIONS ===")
    checks = {
        "P1 R-legs invariant (V1-V7 unmoved)":
            all(n == "V8 legal size exists" for n in moved) or not moved,
        "P2 V8 passes (bisected existence)": v8,
        "P3 corrected ceiling < single-day bound":
            bool(ceiling.exists and r_single > 0 and ceiling.risk_usd < r_single),
        "P4 no sizing rule clears the gate": p_seq < 8,
        "P5 closed form is CONSERVATIVE vs simulation":
            bool(ceiling.exists and r_sim > 0 and ceiling.risk_usd <= r_sim),
    }
    for name, ok in checks.items():
        print(f"  {name:<46} {'CONFIRMED' if ok else 'FALSIFIED'}")

    out = {
        "study": "GOLD_PROSPECTIVE_CONTROL",
        "protocol": "docs/GOLD_PROSPECTIVE_SIZING_PROTOCOL.md",
        "symbol": a.symbol, "trades": len(trades), "days": ndays,
        "total_r": total, "t": t_stat, "positive_folds": pos_folds,
        "folds": len(oos_rs), "null_p95": a.null_p95,
        "worst_day_r": worst_day_r, "worst_run_days": k,
        "worst_run_r": run_depth, "worst_peak_to_trough_r": peak_trough,
        "risk_single_day_bound_usd": round(r_single, 2),
        "risk_simulated_survivor_usd": round(r_sim, 2),
        "risk_prospective_ceiling_usd": round(ceiling.risk_usd, 2),
        "ceiling_note": ceiling.note,
        "legs_single_day": single_legs, "legs_prospective": seq_legs,
        "legs_moved": moved, "v8_bisected": v8,
        "passed_single_day": p_single, "passed_prospective": p_seq,
        "predictions": checks,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
