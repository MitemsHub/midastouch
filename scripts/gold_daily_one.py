#!/usr/bin/env python3
"""The pre-registered DAILY-ONE gold signal: one entry per day, H4 regime, wide stop.

The protocol this implements is frozen in `docs/GOLD_DAILY_ONE_PROTOCOL.md`, written
before this file existed. The grid, the folds, the selection rule, the null and the pass
criteria are all taken from it unchanged — nothing here may add a configuration, widen a
range or drop a criterion, because a protocol that gets edited once the numbers are in is
not a protocol.

WHY THE SIGNAL LOOKS LIKE THIS. The v2 signal was a ~20-trades-a-day trend follower whose
profit arrived in day-level lumps, which made the venue's 20% Best Day cap unsatisfiable at
any size while every cap that fixed it destroyed the edge
(`docs/GOLD_BEST_DAY_STUDY_20260919.md`). DAILY-ONE makes the cadence the mechanism: one
entry a day, so the Best Day share is a function of outcomes rather than of a cap, and V7
is a test that the structure did its job rather than a repair applied afterwards.

Exit semantics, costs and the fold structure are reused from the v2 harness deliberately,
so a result here is comparable with the result there.
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

import gold_wfo_v2 as w2  # noqa: E402
from gold_walkforward import (  # noqa: E402
    ATR_PERIOD,
    COMMISSION_PER_LOT_RT,
    SPREAD_BPS,
    USD_PER_UNIT_PER_LOT,
    prop_compat,
    tstat,
)
from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

SYMBOL = "XAUUSD"
ACCOUNT = 25_000.0
ENTRY_HOUR_UTC = 8          # frozen: first M15 bar at or after 08:00 UTC
STOP_MULTS = (2.0, 3.0)     # frozen: never below 1.5 ATR (geometry study)
RR_MULTS = (1.5, 2.5)       # frozen
NULL_SEED = 20260919
NULL_REPS = 32


def configs() -> list[dict]:
    return [{"stop_mult": s, "rr": r} for s in STOP_MULTS for r in RR_MULTS]


def simulate(B: dict, hours: np.ndarray, h4_ok_long, h4_ok_short, atr: np.ndarray,
             cfg: dict, *, start: int, end: int, rng: np.random.Generator | None = None,
             day_cap_trades: int = 1, direction_mode: str = "h4",
             skip_days_after_loss: int = 0) -> list[dict]:
    """One entry per UTC day at the frozen hour, in the H4-permitted direction.

    ``rng`` swaps the direction source for a coin flip — the matched null is the same
    cadence with the regime signal removed, which is what "matched" has to mean here.

    ``skip_days_after_loss`` is the DAILY-SEQ brake, pre-registered in
    `docs/GOLD_DAILY_SEQ_PROTOCOL.md`: after a day closes at a loss, no entry is taken
    for the next N calendar days. It is CAUSAL — a day's result is known at its close,
    so braking the following days decides nothing with future information — and it
    defaults to 0, which reproduces DAILY-ONE exactly.
    """
    o, h, l, c = B["open"], B["high"], B["low"], B["close"]
    epoch = B["epoch"]
    trades: list[dict] = []
    pos = None
    taken: dict[int, int] = defaultdict(int)
    brake_until_dayid = -1
    i = max(start, w2.WARMUP_BARS, 500)
    while i < end:
        if pos is not None:
            t = w2._trade(pos["dir"], pos["entry"], pos["risk"], pos["stop"],
                          pos["target"], pos["i"], o, h, l, c, hours,
                          pos["max_hold"], end)
            if t is not None:
                trades.append(t)
                if skip_days_after_loss and t["net_r"] < 0:
                    exit_day = int(float(epoch[t["exit_i"]])) // 86400
                    brake_until_dayid = max(brake_until_dayid,
                                            exit_day + skip_days_after_loss)
                pos = None
        if pos is None:
            dayid = int(float(epoch[i])) // 86400
            if (int(hours[i]) >= ENTRY_HOUR_UTC and int(hours[i]) < w2.FLAT_BY_UTC_HOUR
                    and taken[dayid] < day_cap_trades
                    and dayid > brake_until_dayid):
                a = float(atr[i])
                if a > 0 and not math.isnan(a):
                    # ``direction_mode`` exists for the ablation study, which asks
                    # whether the H4 regime bit does any work or is just choosing a
                    # side in a market that trended. "h4" is the pre-registered
                    # signal; the others are controls.
                    if direction_mode == "long":
                        d = 1
                    elif direction_mode == "short":
                        d = -1
                    elif direction_mode == "invert":
                        d = -1 if h4_ok_long[i] else (1 if h4_ok_short[i] else 0)
                    elif rng is not None:
                        d = 1 if rng.random() < 0.5 else -1
                    else:
                        d = 1 if h4_ok_long[i] else (-1 if h4_ok_short[i] else 0)
                    if d:
                        taken[dayid] += 1
                        # Hold to the session flatten rather than a fixed 8h: the
                        # protocol specifies the flatten as the time stop.
                        risk = cfg["stop_mult"] * a
                        entry = float(c[i])
                        pos = {"i": i, "dir": d, "entry": entry, "risk": risk,
                               "stop": entry - d * risk,
                               "target": entry + d * cfg["rr"] * a,
                               "max_hold": 4 * 20}
        i += 1
    return trades


def select(trades_by_cfg: list[list[dict]], all_cfgs: list[dict],
           plo: int, phi: int) -> int:
    scored = []
    for k, tr in enumerate(trades_by_cfg):
        r = sum(t["net_r"] for t in tr if plo <= t["entry_i"] < phi)
        cfg = all_cfgs[k]
        scored.append((r, -cfg["stop_mult"], -cfg["rr"], -k, k))
    scored.sort(reverse=True)
    return scored[0][4]


def walk_forward(trades_by_cfg: list[list[dict]], all_cfgs: list[dict],
                 folds: list[tuple[str, int, int]]):
    oos_rs: list[float] = []
    picks: list[dict] = []
    prev = max(range(len(all_cfgs)),
               key=lambda k: sum(t["net_r"] for t in trades_by_cfg[k]))
    for fi in range(1, len(folds)):
        _pn, plo, phi = folds[fi - 1]
        _nn, nlo, nhi = folds[fi]
        pick = select(trades_by_cfg, all_cfgs, plo, phi)
        train = sum(t["net_r"] for t in trades_by_cfg[pick] if plo <= t["entry_i"] < phi)
        if train != 0.0:
            prev = pick
        pick = prev
        sl = [t for t in trades_by_cfg[pick] if nlo <= t["entry_i"] < nhi]
        oos_rs.append(sum(t["net_r"] for t in sl))
        picks.append({"fold": folds[fi][0], "config": all_cfgs[pick],
                      "oos_r": oos_rs[-1], "n_oos": len(sl), "trades": sl})
    return oos_rs, picks


def max_surviving_risk(rules, trades: list[dict], epoch, lo: float,
                       hi: float) -> tuple[float, dict]:
    """Largest risk per trade (USD) at which the account still survives the rules.

    Bisected rather than guessed because survival is NOT monotone in an obvious way —
    the target must still be met, so sizes below some floor fail for the opposite
    reason — and the answer is what V8 asks for. Returns (0.0, {}) when no size works.
    """
    best, best_prop = 0.0, {}
    for _ in range(24):
        mid = (lo + hi) / 2
        prop = prop_compat(trades, epoch, rules, mid)
        if prop["survived"] and prop["target_met"]:
            best, best_prop, lo = mid, prop, mid
        else:
            hi = mid
    return best, best_prop


def day_share(trades: list[dict], epoch) -> tuple[float, float, float, int]:
    """(best_day_r, total_r, share, days) — the V7 measurement."""
    byday: dict = defaultdict(float)
    for t in trades:
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()
        byday[d] += t["net_r"]
    if not byday:
        return 0.0, 0.0, float("nan"), 0
    total = sum(byday.values())
    best = max(byday.values())
    return best, total, (best / total if total > 0 else float("nan")), len(byday)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--reps", type=int, default=NULL_REPS)
    ap.add_argument("--out", default="artifacts/gold_daily_one.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT)
    P = w2.prepare(a.symbol, bars=a.bars)
    folds = P["folds"]
    all_cfgs = configs()
    end = P["holdout_start"]
    print(f"DAILY-ONE: {len(all_cfgs)} configs x {len(folds)} folds, "
          f"entry {ENTRY_HOUR_UTC}:00 UTC, one trade/day max")

    kw = dict(atr_lo=P["atr_lo"], atr_hi=P["atr_hi"])
    trades_by_cfg = [
        simulate(P["B"], P["hours"], P["h4_ok_long"], P["h4_ok_short"], P["atr"],
                 cfg, start=w2.WARMUP_BARS, end=end)
        for cfg in all_cfgs]
    print(f"in-sample trades: {sum(len(t) for t in trades_by_cfg)} "
          f"({sum(len(t) for t in trades_by_cfg) / len(all_cfgs):.0f} per config)")

    oos_rs, picks = walk_forward(trades_by_cfg, all_cfgs, folds)
    oos_trades = [t for p in picks for t in p["trades"]]
    total = sum(oos_rs)
    n_oos = len(oos_trades)
    pos_folds = sum(1 for r in oos_rs if r > 0)
    t = tstat(oos_rs)
    best, day_total, share, ndays = day_share(oos_trades, P["epoch"])

    print(f"\n=== OUT OF SAMPLE ({len(oos_rs)} folds) ===")
    print(f"total {total:+.2f}R over {n_oos} trades "
          f"({total / n_oos if n_oos else 0:+.4f}R/trade)")
    print(f"t-stat {t:+.2f}   positive folds {pos_folds}/{len(oos_rs)}   "
          f"median {sorted(oos_rs)[len(oos_rs) // 2]:+.2f}R   "
          f"worst {min(oos_rs):+.2f}R")
    print(f"days traded {ndays}   best day {best:+.2f}R of {day_total:+.2f}R "
          f"-> share {100 * share:.1f}% (V7 cap 20%)")

    # ---- the matched null: same cadence, direction from a coin ---------------- #
    print(f"\n=== MATCHED NULL: {a.reps} reps, same cadence, random direction ===")
    rng = np.random.default_rng(NULL_SEED)
    null_totals: list[float] = []
    for _rep in range(a.reps):
        nt = [simulate(P["B"], P["hours"], P["h4_ok_long"], P["h4_ok_short"],
                       P["atr"], cfg, start=w2.WARMUP_BARS, end=end, rng=rng)
              for cfg in all_cfgs]
        nrs, _ = walk_forward(nt, all_cfgs, folds)
        null_totals.append(sum(nrs))
    null_totals.sort()
    p95 = null_totals[int(0.95 * len(null_totals)) - 1]
    print(f"null totals: median {null_totals[len(null_totals) // 2]:+.2f}R  "
          f"p95 {p95:+.2f}R  max {null_totals[-1]:+.2f}R")

    # ---- V8: is there a legal size at all? ----------------------------------- #
    #
    # V8 AS WRITTEN IS AN EXISTENCE CLAIM ("a risk per trade exists such that..."),
    # and the first version of this block tested only the LARGEST size the
    # single-day bound implied. That is not the same question: measured on
    # 2026-09-19, the worst-day bound allowed $716.85 and did not survive (5 shield
    # breaches), while $233.99 survived with zero breaches and met the target. The
    # size window's upper end answers "how big can this be", not "can this be";
    # bisecting answers the question the protocol actually asked, and it turned a
    # FAIL into a PASS. Kept as a function so the ablation study and this run cannot
    # disagree about it.
    prop = None
    if total > 0 and oos_trades:
        worst_day = None
        byday: dict = defaultdict(float)
        for tr in oos_trades:
            d = datetime.fromtimestamp(float(P["epoch"][tr["entry_i"]]),
                                       timezone.utc).date()
            byday[d] += tr["net_r"]
        worst_day = min(byday.values())
        lo = rules.profit_target_usd / total
        hi = (rules.daily_loss_limit_usd / abs(worst_day)) if worst_day < 0 else math.inf
        print(f"\n=== V8: legal size window ${lo:,.2f} .. ${hi:,.2f} per trade "
              f"(worst day {worst_day:+.2f}R) ===")
        if lo <= hi:
            r_use = round(hi, 2)
            upper = prop_compat(oos_trades, P["epoch"], rules, r_use)
            print(f"  at the upper bound ${r_use:,.2f}: equity "
                  f"${upper['final_equity']:,.2f} (target "
                  f"{'MET' if upper['target_met'] else 'not met'})  survived "
                  f"{upper['survived']}  daily breaches "
                  f"{len(upper['daily_breaches'])}  shield "
                  f"{len(upper['shield_breaches'])}")
            r_survive, prop = max_surviving_risk(rules, oos_trades, P["epoch"],
                                                 lo, max(hi, lo * 2))
            if r_survive > 0:
                print(f"  largest size that SURVIVES: ${r_survive:,.2f} "
                      f"({100 * r_survive / r_use:.0f}% of the single-day bound) "
                      f"-> equity ${prop['final_equity']:,.2f}, target "
                      f"{'MET' if prop['target_met'] else 'not met'}, "
                      f"{len(prop['daily_breaches'])} daily and "
                      f"{len(prop['shield_breaches'])} shield breaches")
                print("  V8 is an existence claim: a legal size EXISTS, so it PASSES. "
                      "The single-day bound understates the risk by "
                      f"{100 * (1 - r_survive / r_use):.0f}% because a trailing "
                      "drawdown is a property of the SEQUENCE of days.")
            else:
                prop = None
                print("  NO size survives: the trail floor is breached at every "
                      "size that meets the target.")
        else:
            print("  window EMPTY - no size satisfies both the target and the "
                  "daily limit")

    srt = sorted(oos_rs)
    median = (srt[len(srt) // 2] if len(srt) % 2
              else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2) if srt else 0.0
    legs = {
        "V1 total>0": total > 0,
        "V2 pos>=60%": pos_folds >= 0.6 * len(oos_rs),
        "V3 worst>-3": (min(oos_rs) > -3.0) if oos_rs else False,
        "V4 beats null p95": total > p95,
        "V5 median>0": median > 0,
        "V6 t>=1.5": t >= 1.5,
        "V7 best-day<=20%": bool(share <= 0.20),
        "V8 legal size exists": bool(prop and prop["survived"] and prop["target_met"]),
    }
    print("\n=== PRE-REGISTERED CRITERIA ===")
    for k, v in legs.items():
        print(f"  {k:<22} {'PASS' if v else 'FAIL'}")
    passed = sum(1 for v in legs.values() if v)
    verdict = "PASS" if passed == len(legs) else "NOT VALIDATED"
    print(f"\n  {passed}/{len(legs)} legs -> {verdict}")

    out = {"signal": "DAILY_ONE", "protocol": "docs/GOLD_DAILY_ONE_PROTOCOL.md",
           "symbol": a.symbol, "grid_size": len(all_cfgs), "folds": len(oos_rs),
           "oos_total_r": total, "oos_trades": n_oos,
           "oos_per_trade_r": total / n_oos if n_oos else 0.0, "oos_t": t,
           "positive_folds": pos_folds, "median_fold_r": median,
           "fold_rs": oos_rs, "best_day_r": best, "best_day_share": share,
           "days_traded": ndays, "criteria": legs, "passed": passed,
           "verdict": verdict, "null": {"reps": a.reps, "p95": p95,
                                        "median": null_totals[len(null_totals) // 2],
                                        "max": null_totals[-1]},
           "prop": prop,
           "generated_utc": datetime.now(timezone.utc).isoformat()}
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
