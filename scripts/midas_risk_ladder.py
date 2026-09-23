#!/usr/bin/env python3
"""Does a prop-state risk ladder help THIS account, where the only downward lever is skipping?

THE CONSTRAINT. At $25,004 with the venue's 0.01-lot minimum and the measured 2xATR(H1) stop, one R
is $41.31 = 0.165% of equity. Risk quantises 0.01 lots ($41.31) / 0.02 ($82.62) / 0.03 ($123.93), so
the declared 0.25% ($62.51) is UNREACHABLE and the researched ladder's "reduce size" half is
unavailable: the only downward lever is SKIPPING an entry. That is what this measures.

THE SEQUENCE IS REAL. The armed mode's own held-out fills in the arm's live frame (UTC 04-18), in
chronological order, each with its own r, timestamp and UTC day. 1R = $41.31 at the arm's size, so
every dollar figure below is the arm's own arithmetic. Pre-registered in
docs/PROP_RISK_LADDER_PREREG_20260922.md before the run.

VARIANTS. FIXED (take everything) | LADDER (skip on two consecutive losing closes today, on the day
being down 2% of its opening equity, or on the day already 70% of the way to the $250 ceiling) |
SHIPPED (min-lot veto, 3% breaker, $250/day ceiling blocking entries once reached, 6% shield).

DISCLOSED LIMITATION: a skipped entry here does not free the slot for a later signal the way it would
live, so LADDER's fill count is UNDERSTATED and its delay OVERstated - against the variant under test.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402

ART = Path("artifacts") / "midas_risk_ladder_20260922.json"
MODE = "REVERSE_DIRECTION"
LO, HI = 4, 18                       # the arm's live frame
EQUITY, USD_PER_R = 25004.26, 41.31  # measured from the live fill's own bracket
DAILY_CAP_PCT, CEILING_USD, SHIELD_PCT = 3.0, 250.0, 6.0
LADDER_LOSS_STOP_PCT = 2.0           # two-thirds of the 3% floor
LADDER_CEILING_FRAC = 0.70           # the researched "trade smaller above 70% of target"
BLOCK, DRAWS, RESAMPLE_BLOCK = 30, 20000, 20
MIN_BLOCK_IMPROVEMENT_DELAY = 0.25
RNG = random.Random(20260922)


def day_floor(equity_open: float) -> float:
    return equity_open * DAILY_CAP_PCT / 100.0


def replay(trades: list[dict], variant: str) -> dict:
    """Walk the REAL chronological sequence once, applying the variant's rule."""
    day_pnl: dict[str, float] = defaultdict(float)
    day_open: dict[str, float] = {}
    day_losses: dict[str, int] = defaultdict(int)
    taken, equity, skipped = [], EQUITY, 0
    peak, dd, breach_days = equity, 0.0, set()
    for t in trades:
        d = datetime.fromtimestamp(int(t["open_ct"]), tz=timezone.utc).date().isoformat()
        if d not in day_open:
            day_open[d] = equity
        r = float(t["r"])
        take = True
        if variant == "LADDER":
            if day_losses[d] >= 2:
                take = False
            elif day_pnl[d] <= -LADDER_LOSS_STOP_PCT / 100.0 * day_open[d]:
                take = False
            elif day_pnl[d] >= LADDER_CEILING_FRAC * CEILING_USD:
                take = False
        elif variant == "SHIPPED":
            if day_pnl[d] >= CEILING_USD:                 # the ceiling blocks further entries
                take = False
            elif day_pnl[d] <= -day_floor(day_open[d]):   # the 3% breaker
                take = False
            if equity <= EQUITY * (1 - SHIELD_PCT / 100.0):
                take = False
        if not take:
            skipped += 1
            continue
        pnl = r * USD_PER_R
        day_pnl[d] += pnl
        if pnl < 0:
            day_losses[d] += 1
        else:
            day_losses[d] = 0
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        if day_pnl[d] < -day_floor(day_open[d]):
            breach_days.add(d)
        taken.append({"day": d, "r": r, "equity_after": equity})
    return {"fills": len(taken), "skipped": skipped, "net_r": round(sum(x["r"] for x in taken), 3),
            "net_pnl": round(sum(x["r"] for x in taken) * USD_PER_R, 2),
            "max_dd_pct": round(dd / EQUITY * 100, 3), "days": len(day_open),
            "fills_per_day": round(len(taken) / len(day_open), 3) if day_open else 0.0,
            "breach_days": len(breach_days),
            "breach_rate": round(len(breach_days) / len(day_open), 4) if day_open else 0.0,
            "eq_open": EQUITY, "eq_close": round(equity, 2)}


def block_bootstrap(day_lists: list[list[float]], variant: str,
                    zero_day_share: float) -> dict:
    """P(positive 30-trade block) by resampling REAL DAYS, not trades.

    CORRECTED AFTER THE FIRST RUN, and the reason matters. The first version resampled 30 TRADES
    and applied the ladder's day-level thresholds to that block as if the block were one day. On
    this account the observed day holds at most TWO fills (measured: 70 days with one, 30 with two,
    none with three), so a 30-trade block is ~40 calendar days and the ladder's state resets ~40
    times — while the first version reset it never. It produced LADDER P(block>0) = 45.6% against
    FIXED's 70.6%, an ARTIFACT of the mis-modelling. Days are therefore the unit here: an inert day
    is drawn at the observed rate, and the ladder's state resets at every drawn day.
    """
    pos, nets, dds, days_used = 0, [], [], []
    for _ in range(DRAWS):
        kept, used_days = [], 0
        while len(kept) < BLOCK:
            used_days += 1
            if RNG.random() < zero_day_share:
                continue
            day = list(RNG.choice(day_lists))
            pnl, consecutive_losses = 0.0, 0
            for r in day:
                skip = False
                if variant == "LADDER":
                    if consecutive_losses >= 2 or pnl <= -LADDER_LOSS_STOP_PCT / 100.0 * EQUITY \
                            or pnl >= LADDER_CEILING_FRAC * CEILING_USD:
                        skip = True
                elif variant == "SHIPPED":
                    if pnl >= CEILING_USD or pnl <= -day_floor(EQUITY):
                        skip = True
                if skip:
                    continue
                kept.append(r)
                pnl += r * USD_PER_R
                consecutive_losses = consecutive_losses + 1 if r < 0 else 0
                if len(kept) >= BLOCK:
                    break
        net = sum(kept)
        nets.append(net)
        days_used.append(used_days)
        eq = peak = dd = 0.0
        for r in kept:
            eq += r * USD_PER_R
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        dds.append(dd)
        if net > 0:
            pos += 1
    nets.sort()
    dds.sort()
    days_used.sort()
    return {"p_positive_block": round(pos / DRAWS, 4),
            "median_net_r": round(nets[DRAWS // 2], 3),
            "p05_net_r": round(nets[int(DRAWS * 0.05)], 2),
            "p95_net_r": round(nets[int(DRAWS * 0.95)], 2),
            "median_block_dd_usd": round(dds[DRAWS // 2], 2),
            "median_block_dd_pct": round(dds[DRAWS // 2] / EQUITY * 100, 3),
            "median_days_to_30": int(days_used[DRAWS // 2])}


def main() -> int:
    spec = P._window_spec("wfv")
    data_pin = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data_pin)
    finally:
        M._BASIS = prev
    n_pin, tot_pin = len(rr.trades), sum(t["r"] for t in rr.trades)
    print(f"self-check  wfv {spec['mode']}: n={n_pin} totalR={tot_pin:+.4f} vetoed={rr.vetoed}")
    if n_pin != 56 or abs(tot_pin - 15.9352) >= 5e-4:
        raise SystemExit("REFUSING: the pinned venue-corpus law did not reproduce.")
    print("            reproduced the pin -> the arithmetic below is the engine of record's.\n")

    spec = P._window_spec("oos")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
        trades = M.run_mode(MODE, spec["t0"], spec["t1"], data, win_lo=LO, win_hi=HI).trades
    finally:
        M._BASIS = prev

    rs = [float(t["r"]) for t in trades]
    raw_exp = statistics.mean(rs)
    # THE DAY IS THE UNIT THE LADDER LIVES IN, so measure it before modelling it. The within-day
    # state a ladder gates on can only be OBSERVED on days that hold more than one fill.
    by_day: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        d = datetime.fromtimestamp(int(t["open_ct"]), tz=timezone.utc).date().isoformat()
        by_day[d].append(float(t["r"]))
    day_lists = list(by_day.values())
    fills_hist = Counter(len(v) for v in day_lists)
    span_days = max(1.0, (spec["t1"] - spec["t0"]) / 86400.0)
    zero_day_share = max(0.0, 1.0 - len(day_lists) / span_days)
    worst_days = sorted((sum(v) for v in day_lists))[:3]
    day_structure = {"active_days": len(day_lists), "span_days": round(span_days, 1),
                     "zero_fill_day_share": round(zero_day_share, 4),
                     "fills_per_day_hist": {str(k): v for k, v in sorted(fills_hist.items())},
                     "max_fills_in_a_day": max(fills_hist, default=0),
                     "worst_days_r": [round(x, 3) for x in worst_days],
                     "worst_day_pct_of_equity": round(worst_days[0] * USD_PER_R / EQUITY * 100, 4)
                     if worst_days else 0.0,
                     "worst_day_pct_of_cap": round(worst_days[0] * USD_PER_R
                                                   / day_floor(EQUITY) * 100, 1) if worst_days else 0.0}
    out: dict = {"harness": "midas_risk_ladder.py",
                 "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "prereg": "docs/PROP_RISK_LADDER_PREREG_20260922.md",
                 "sequence": {"mode": MODE, "window": "oos", "frame_utc": [LO, HI],
                              "fills": len(rs), "expR": round(raw_exp, 4),
                              "total_r": round(sum(rs), 2)},
                 "account": {"equity": EQUITY, "usd_per_r": USD_PER_R,
                             "r_pct_of_equity": round(USD_PER_R / EQUITY * 100, 4),
                             "daily_cap_pct": DAILY_CAP_PCT, "ceiling_usd": CEILING_USD,
                             "shield_pct": SHIELD_PCT,
                             "quantisation": {"0.01 lots": 41.31, "0.02 lots": 82.62,
                                              "0.03 lots": 123.93,
                                              "declared_0.25pct": 62.51,
                                              "unreachable_between": [41.31, 82.62]}},
                 "day_structure": day_structure,
                 "variants": {}}
    for variant in ("FIXED", "LADDER", "SHIPPED"):
        rep = replay(trades, variant)
        boot = block_bootstrap(day_lists, variant, zero_day_share)
        rep["fills_to_30"] = round(BLOCK / rep["fills_per_day"], 1) if rep["fills_per_day"] else None
        out["variants"][variant] = {**rep, **boot}

    base, lad = out["variants"]["FIXED"], out["variants"]["LADDER"]
    # A LADDER THAT NEVER FIRES HAS NOT BEEN TESTED. The first version of this file reported the
    # daily-cap check as FAIL when BOTH sides were 0.0% - a comparison with nothing on either side
    # of it, dressed as a refutation. Whether the rule BOUND is therefore its own field, decided by
    # the ladder's own skip count, and it decides the vocabulary of the verdict.
    binding = lad["skipped"] > 0
    out["binding"] = bool(binding)
    checks: dict[str, dict] = {
        "P(positive 30-block) >= FIXED": {"pass": lad["p_positive_block"] >= base["p_positive_block"]},
        "P(daily-cap breach) < FIXED": {
            "pass": lad["breach_rate"] < base["breach_rate"],
            "vacuous": lad["breach_rate"] == base["breach_rate"]},
        "30-trade delay <= 25%": {
            "pass": lad["fills_to_30"] is not None and base["fills_to_30"] is not None
            and lad["fills_to_30"] <= base["fills_to_30"] * (1 + MIN_BLOCK_IMPROVEMENT_DELAY)},
    }
    out["checks"] = {k: bool(v["pass"]) for k, v in checks.items()}
    out["checks_vacuous"] = [k for k, v in checks.items() if v.get("vacuous")]
    if not binding:
        out["verdict"] = "NOT-BINDING"
        out["why_verdict"] = (
            f"The ladder skipped 0 of {len(rs)} fills, so nothing was tested: its within-day state "
            f"is unreachable here. `day_losses[d] >= 2` needs a THIRD fill in a day after two losing "
            f"closes, and this window's maximum is {day_structure['max_fills_in_a_day']} fills/day "
            f"(histogram {day_structure['fills_per_day_hist']}). The 2% day-stop needs -12.1R in one "
            f"day; the measured worst day is {day_structure['worst_days_r'][0]:+.2f}R "
            f"({day_structure['worst_day_pct_of_equity']:.3f}% of equity, "
            f"{day_structure['worst_day_pct_of_cap']:.1f}% of the 3% cap). The 70%-of-ceiling "
            f"condition needs +$175 banked in a day; two fills at the candidate's own expectancy hold "
            f"~$0.50. Every one of the researched triggers is therefore INERT AT THIS TRADE "
            f"FREQUENCY AND THIS LOT SIZE - which is not the same claim as 'the ladder is wrong'. "
            f"It is untestable on this arm until either the fills/day rises or the lot and stop "
            f"distance make a single day's excursion a material share of the cap. Recorded, not "
            f"implemented; the arm is unchanged.")
    else:
        out["verdict"] = "PASS" if all(out["checks"].values()) else "FAIL"
        out["why_verdict"] = "the ladder bound and its checks decided the verdict"
    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")

    print(f"sequence: {len(rs)} real held-out fills at {raw_exp:+.4f}R, 1R = ${USD_PER_R} "
          f"= {USD_PER_R / EQUITY * 100:.3f}% of ${EQUITY:,.0f}")
    print(f"risk quantises to 0.01 lots ${41.31} / 0.02 ${82.62} / 0.03 ${123.93} — the declared "
          f"0.25% (${62.51}) is unreachable\n")
    print(f"day structure: {day_structure['active_days']} active days in {day_structure['span_days']:.0f} "
          f"calendar days, {day_structure['zero_fill_day_share']:.1%} of days hold no fill, "
          f"histogram of fills/day = {day_structure['fills_per_day_hist']} "
          f"(max {day_structure['max_fills_in_a_day']})")
    print(f"  worst day {day_structure['worst_days_r'][0]:+.2f}R = "
          f"{day_structure['worst_day_pct_of_equity']:.3f}% of equity = "
          f"{day_structure['worst_day_pct_of_cap']:.1f}% of the 3% daily cap\n")
    print(f"  {'variant':9s} {'fills':>6s} {'skipped':>8s} {'netR':>8s} {'net$':>9s} "
          f"{'P(blk>0)':>9s} {'breach%':>8s} {'fills/day':>10s} {'days-to-30':>10s} {'blkDD%':>7s} {'dd%':>7s}")
    for v, r in out["variants"].items():
        print(f"  {v:9s} {r['fills']:6d} {r['skipped']:8d} {r['net_r']:+8.2f} {r['net_pnl']:+9.2f} "
              f"{r['p_positive_block']:9.1%} {r['breach_rate']:8.1%} {r['fills_per_day']:10.3f} "
              f"{(r['fills_to_30'] if r['fills_to_30'] is not None else float('nan')):10.1f} "
              f"{r['median_block_dd_pct']:7.2f} {r['max_dd_pct']:7.2f}")
    print("\nPASS RULE - LADDER vs FIXED, on the held-out sequence:")
    for k, v in checks.items():
        mark = "VACUOUS" if v.get("vacuous") else ("PASS" if v["pass"] else "FAIL")
        print(f"  {mark:8s} {k}")
    print(f"  binding: {'yes' if binding else 'NO - the ladder skipped 0 fills'}")
    print(f"  verdict: {out['verdict']}")
    if not binding:
        print(f"  0 of {len(rs)} fills skipped; max {day_structure['max_fills_in_a_day']} fills/day; "
              f"worst day {day_structure['worst_days_r'][0]:+.2f}R = "
              f"{day_structure['worst_day_pct_of_cap']:.1f}% of the cap. Recorded, not implemented.")
    print(f"\nartifact: {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
