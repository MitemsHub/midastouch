#!/usr/bin/env python3
"""Walk-forward v2 for XAUUSD: fair geometry, honest null, multiplicity control.

WHAT CHANGED FROM v1 AND WHY (all three are corrections of my own tooling, not
tuning to a result — the reasons are measurements, recorded in
`docs/GOLD_GEOMETRY_AND_NULL_CORRECTIONS_20260919.md`):

1. GEOMETRY. v1 tested stops of 1.0-1.5 ATR. The geometry study
   (`scripts/gold_geometry_study.py`) then measured that at a 1-ATR M15 stop the
   same-bar tie assumption is worth +/-0.009R and the round-trip toll is 0.0588R
   - 2.3x the 0.0247R the project had been quoting, because that figure silently
   assumed a ~$23 stop while a 1-ATR M15 stop is $9.89. At 2.0-3.0 ATR the
   assumption band collapses to +/-0.003R, the toll falls to 0.0196-0.0294R, and
   the drift-neutral coin flip is measurably unbiased (E_dir ~ 0.0000). So this
   tool searches where the measurement is trustworthy and the toll is real.
   It never uses a stop below 1.5 ATR, and that floor is justified by the band,
   not by a backtest score.

2. THE NULL. v1's control built its entry bars as `usable[k % len(usable)]` - the
   FIRST n usable bars in order - so it did not randomise timing at all; only
   direction varied across reps. Its "-0.152R random entry" was one contiguous
   early slice of the window, which is why the entry rule looked like +0.19R of
   alpha. Here entries are drawn uniformly over the whole window, and the null is
   built by replicating the ENTIRE selection procedure, not a single config.

3. MULTIPLICITY. "Iterate as many times as possible" is not a free lunch: a grid
   of G configs over F folds has a best-of-G selection bias, so a positive OOS
   total means nothing on its own. This tool therefore reports the OOS total
   against the distribution produced by running the SAME selection procedure on
   random-entry data (`--reps` replications). That distribution is the bar.

   Note the deliberate asymmetry: this measures a SELECTION-ADJUSTED null, not a
   full White's Reality Check. It answers "could picking the best of this grid on
   noise have produced this total?" - it does not recentre the statistic.

HONEST READ OF ITS OUTPUT. E_dir ~ 0 means the BRACKET is fair; it does not mean
there is an edge. The bracket being fair is necessary, not sufficient: the entry
rule still has to produce a positive net after the ~0.02R toll. If the OOS total
does not clear the null, the answer is still "do not arm".
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from gold_walkforward import (  # noqa: E402
    ATR_HIGH_PCT,
    ATR_LOOKBACK,
    ATR_LOW_PCT,
    ATR_PERIOD,
    COMMISSION_PER_LOT_RT,
    FLAT_BY_UTC_HOUR,
    H1_TF_SEC,
    H4_TF_SEC,
    SPREAD_BPS,
    USD_PER_UNIT_PER_LOT,
    build_folds,
    criteria,
    ema,
    last_closed_index,
    prop_compat,
    trailing_percentile,
    tstat,
    wilder_atr,
)
from mt5_data import load_m5  # noqa: E402

SYMBOL = "XAUUSD"
EXEC_TF = "M15"
WARMUP_BARS = 480
FOLD_DAYS = 8
SESSION_LO, SESSION_HI = 7, 20

#: Declared before any run. The 1.5 floor is the geometry study's finding, not a
#: tuned parameter: below it the conclusion depends on the same-bar tie and the
#: toll exceeds 0.039R.
EMA_SETS = ((8, 21, 50), (12, 26, 100))
STOP_MULTS = (1.5, 2.0, 2.5, 3.0)
RR_MULTS = (1.0, 1.5, 2.0)
MAX_HOLDS = (16, 32)          # M15 bars: 4h and 8h
HOLDOUT_DAYS = 40             # last ~2 months never used for selection
NULL_SEED = 20260919


def configs() -> list[dict]:
    out = []
    for emas in EMA_SETS:
        for sm in STOP_MULTS:
            for rr in RR_MULTS:
                for hold in MAX_HOLDS:
                    out.append({"emas": emas, "stop_mult": sm, "rr": rr,
                                "max_hold": hold})
    return out


def _exit_fill(direction: int, stop: float, target: float, o: np.ndarray,
               h: np.ndarray, l: np.ndarray, c: np.ndarray, hours: np.ndarray,
               i: int, max_hold: int, end: int) -> tuple[float | None, int, str]:
    """Bar-by-bar exit. Returns (fill price, exit index, reason).

    Order inside a bar: gap through a barrier fills at the OPEN; then if BOTH
    barriers sit inside the bar the STOP is assumed first (pessimistic, the only
    reading that cannot flatter the result); then the time stop at ``max_hold``;
    then the session flatten.
    """
    j = i + 1
    last = min(end - 1, i + max_hold)
    while j <= last:
        if direction > 0:
            if float(o[j]) <= stop:
                return float(o[j]), j, "gap_stop"
            if float(l[j]) <= stop:
                return stop, j, "stop"
            if float(h[j]) >= target:
                return target, j, "target"
        else:
            if float(o[j]) >= stop:
                return float(o[j]), j, "gap_stop"
            if float(h[j]) >= stop:
                return stop, j, "stop"
            if float(l[j]) <= target:
                return target, j, "target"
        if int(hours[j]) >= FLAT_BY_UTC_HOUR:
            return float(o[j]), j, "flatten"
        j += 1
    if j <= end - 1:
        return float(c[last]), last, "time"
    return None, i, "unclosed"


def _trade(direction: int, entry: float, risk: float, stop: float, target: float,
           i: int, o, h, l, c, hours, max_hold: int, end: int) -> dict | None:
    px, j, why = _exit_fill(direction, stop, target, o, h, l, c, hours, i,
                            max_hold, end)
    if px is None:
        return None
    gross = direction * (px - entry) / risk
    spread_r = SPREAD_BPS / 1e4 * entry / risk
    comm_r = COMMISSION_PER_LOT_RT / (risk * USD_PER_UNIT_PER_LOT)
    return {"entry_i": i, "exit_i": j, "dir": direction, "exit_reason": why,
            "gross_r": gross, "net_r": gross - spread_r - comm_r}


def simulate(B: dict, hours: np.ndarray, h1_ok_long, h1_ok_short, h4_ok_long,
             h4_ok_short, atr: np.ndarray, cfg: dict, *, start: int,
             end: int, day_cap_r: float | None = None,
             max_per_day: int | None = None, atr_lo=None,
             atr_hi=None) -> list[dict]:
    """The declared strategy: EMA alignment, dual-timeframe regime, ATR band.

    ``day_cap_r`` implements the one venue rule that constrains the ENTRY RULE
    rather than the position size. The venue caps any single day's profit at 20%
    of total profit, which in practice is a ceiling on what one day may bank; so
    once a day has already realised ``day_cap_r``, no further entry is taken
    until the next UTC day. Profit is attributed to the day of the EXIT bar, not
    the entry bar, because that is the moment the account actually changes.

    ``max_per_day`` is the cruder sibling: at most N entries per UTC day, counted
    on the entry bar. It exists because the measured concentration turned out to
    be a *trade-count* problem before it was a profit problem — ~22 entries a day,
    each a small independent draw, aggregates into daily swings of tens of R.

    Both default to ``None``, which reproduces the uncapped strategy exactly, so
    every existing caller and result is unchanged. Any cap is applied inside the
    loop rather than as a filter over its output: the simulation holds at most one
    position at a time, so removing a trade frees the slot and a later entry can
    fill it. A post-hoc filter would get that coupling wrong.

    ``atr_lo``/``atr_hi`` are the ATR percentile band. They are accepted rather
    than computed because they depend only on the ATR series and NOT on the
    configuration, while :func:`trailing_percentile` is by far the most expensive
    thing here -- profiled at 6.8s of a 6.9s simulation, i.e. it was being
    recomputed 48 times for one unchanged array. :func:`prepare` returns them so
    every caller can pass them. Passing them changes nothing about the result:
    same array, same window, same percentile, deterministic.
    """
    o, h, l, c = B["open"], B["high"], B["low"], B["close"]
    epoch = B["epoch"]
    e_f, e_m, e_s = (ema(c, k) for k in cfg["emas"])
    if atr_lo is None:
        atr_lo = trailing_percentile(atr, ATR_LOOKBACK, ATR_LOW_PCT)
    if atr_hi is None:
        atr_hi = trailing_percentile(atr, ATR_LOOKBACK, ATR_HIGH_PCT)
    trades: list[dict] = []
    by_day: dict[int, float] = {}
    by_day_n: dict[int, int] = {}
    pos = None
    i = max(start, WARMUP_BARS, ATR_LOOKBACK)
    while i < end:
        if pos is not None:
            t = _trade(pos["dir"], pos["entry"], pos["risk"], pos["stop"],
                       pos["target"], pos["i"], o, h, l, c, hours,
                       cfg["max_hold"], end)
            if t is not None:
                trades.append(t)
                if day_cap_r is not None:
                    d = int(float(epoch[t["exit_i"]])) // 86400
                    by_day[d] = by_day.get(d, 0.0) + t["net_r"]
                pos = None
        if pos is None and i + 1 < end:
            hr = int(hours[i])
            dayid = int(float(epoch[i])) // 86400
            spent = (day_cap_r is not None
                     and by_day.get(dayid, 0.0) >= day_cap_r)
            if max_per_day is not None and by_day_n.get(dayid, 0) >= max_per_day:
                spent = True
            if not spent and SESSION_LO <= hr <= SESSION_HI and hr < FLAT_BY_UTC_HOUR:
                a = float(atr[i])
                lo, hi = float(atr_lo[i]), float(atr_hi[i])
                if (not math.isnan(a) and not math.isnan(lo) and not math.isnan(hi)
                        and lo < a <= hi and a > 0):
                    up = e_f[i] > e_m[i] > e_s[i]
                    dn = e_f[i] < e_m[i] < e_s[i]
                    d = 0
                    if up and h1_ok_long[i] and h4_ok_long[i]:
                        d = 1
                    elif dn and h1_ok_short[i] and h4_ok_short[i]:
                        d = -1
                    if d:
                        risk = cfg["stop_mult"] * a
                        entry = float(c[i])
                        pos = {"i": i, "dir": d, "entry": entry, "risk": risk,
                               "stop": entry - d * risk,
                               "target": entry + d * cfg["rr"] * a}
                        if max_per_day is not None:
                            by_day_n[dayid] = by_day_n.get(dayid, 0) + 1
        i += 1
    return trades


def fold_usable(hours: np.ndarray, atr: np.ndarray,
                folds: list[tuple[str, int, int]], end: int) -> list[np.ndarray]:
    """Session bars with a valid ATR and an exit bar available, per fold."""
    out = []
    for _fn, lo, hi in folds:
        lo_i = max(lo, WARMUP_BARS, ATR_LOOKBACK)
        out.append(np.array([k for k in range(lo_i, min(hi, end))
                             if SESSION_LO <= int(hours[k]) <= SESSION_HI
                             and int(hours[k]) < FLAT_BY_UTC_HOUR
                             and np.isfinite(atr[k]) and atr[k] > 0
                             and k + 1 < end], dtype=int))
    return out


def random_entries(B: dict, hours: np.ndarray, atr: np.ndarray, cfg: dict,
                   counts: list[int], usable_by_fold: list[np.ndarray], *,
                   end: int, rng: np.random.Generator) -> list[dict]:
    """A MATCHED null: same geometry and the same trade count PER FOLD, entries
    drawn uniformly inside each fold.

    This is the fix to v1's control. v1 built entries as `usable[k % len]` - the
    first N usable bars in order - so it never randomised timing; only direction
    varied across reps, and the "random" expectancy was one contiguous slice of
    the window. Here the entry bar inside each fold is a uniform draw, and the
    per-fold count is matched to what the strategy actually took in that fold, so
    the null faces the same number of positions in the same periods.
    """
    o, h, l, c = B["open"], B["high"], B["low"], B["close"]
    out: list[dict] = []
    for fu, cnt in zip(usable_by_fold, counts):
        if cnt <= 0 or len(fu) == 0:
            continue
        picks = rng.choice(fu, size=min(int(cnt), len(fu)), replace=False)
        for i in sorted(int(k) for k in picks):
            d = 1 if rng.random() < 0.5 else -1
            a = float(atr[i])
            risk = cfg["stop_mult"] * a
            entry = float(c[i])
            t = _trade(d, entry, risk, entry - d * risk, entry + d * cfg["rr"] * a,
                       i, o, h, l, c, hours, cfg["max_hold"], end)
            if t is not None:
                out.append(t)
    return out


def _select(trades_by_cfg: list[list[dict]], all_cfgs: list[dict],
            plo: int, phi: int) -> int:
    """Protocol selection rule: best total R on the fold, deterministic tie-break."""
    scored = []
    for k, tr in enumerate(trades_by_cfg):
        r = sum(t["net_r"] for t in tr if plo <= t["entry_i"] < phi)
        cfgd = all_cfgs[k]
        scored.append((r, -cfgd["stop_mult"], -cfgd["rr"], -k, k))
    scored.sort(reverse=True)
    return scored[0][4]


def walk_forward(trades_by_cfg: list[list[dict]], all_cfgs: list[dict],
                 folds: list[tuple[str, int, int]]) -> tuple[list[float], list[dict]]:
    """Select on fold k, score that pick on fold k+1 only. Carries a stale pick."""
    oos_rs: list[float] = []
    picks: list[dict] = []
    prev = max(range(len(all_cfgs)),
               key=lambda k: sum(t["net_r"] for t in trades_by_cfg[k]))
    for fi in range(1, len(folds)):
        _pn, plo, phi = folds[fi - 1]
        _nn, nlo, nhi = folds[fi]
        pick = _select(trades_by_cfg, all_cfgs, plo, phi)
        train = sum(t["net_r"] for t in trades_by_cfg[pick]
                    if plo <= t["entry_i"] < phi)
        if train != 0.0:
            prev = pick
        pick = prev
        oos = sum(t["net_r"] for t in trades_by_cfg[pick]
                  if nlo <= t["entry_i"] < nhi)
        oos_rs.append(oos)
        picks.append({"fold": folds[fi][0], "selected_on": folds[fi - 1][0],
                      "config": all_cfgs[pick], "oos_r": oos,
                      "n_oos": sum(1 for t in trades_by_cfg[pick]
                                   if nlo <= t["entry_i"] < nhi)})
    return oos_rs, picks


def prepare(symbol: str = SYMBOL, bars: int = 60000) -> dict:
    """Load the symbol and build every array the strategy and the folds need.

    Extracted from :func:`main` so that the walk-forward driver and the Best Day
    study (`scripts/gold_best_day_study.py`) share ONE definition of the regime
    gates, the ATR, the session hours and the fold boundaries. A second copy of
    this would eventually disagree with the first about a gate, and two studies
    that disagree about a gate are not comparable — the comparison would be
    measuring the divergence, not the hypothesis.
    """
    m15 = load_m5(symbol, timeframe=EXEC_TF, bars=bars)
    h1 = load_m5(symbol, timeframe="H1", bars=bars // 4 + 100)
    h4 = load_m5(symbol, timeframe="H4", bars=bars // 16 + 100)
    B = {k: m15.array[k].astype(float) for k in
         ("epoch", "open", "high", "low", "close")}
    epoch = B["epoch"]
    n = len(epoch)
    print(f"{symbol} {EXEC_TF}: {n} bars  "
          f"{datetime.fromtimestamp(epoch[0], timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(epoch[-1], timezone.utc):%Y-%m-%d}")
    atr = wilder_atr(B["high"], B["low"], B["close"], ATR_PERIOD)
    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in epoch], dtype=int)

    h1e, h1c = h1.array["epoch"].astype(float), h1.array["close"].astype(float)
    h1_ef, h1_em, h1_es = (ema(h1c, k) for k in (8, 21, 50))
    h4e, h4c = h4.array["epoch"].astype(float), h4.array["close"].astype(float)
    h4_ef = ema(h4c, 20)
    z = np.zeros(n, dtype=bool)
    h1_ok_long, h1_ok_short = z.copy(), z.copy()
    h4_ok_long, h4_ok_short = z.copy(), z.copy()
    for i in range(n):
        t = float(epoch[i])
        k = last_closed_index(h1e, t, H1_TF_SEC)
        if k >= 0:
            h1_ok_long[i] = h1_ef[k] > h1_em[k] > h1_es[k]
            h1_ok_short[i] = h1_ef[k] < h1_em[k] < h1_es[k]
        m = last_closed_index(h4e, t, H4_TF_SEC)
        if m >= 0:
            h4_ok_long[i] = h4c[m] > h4_ef[m]
            h4_ok_short[i] = h4c[m] < h4_ef[m]

    # Holdout: the last HOLDOUT_DAYS are never used for selection or scoring.
    holdout_start = n - int(HOLDOUT_DAYS * 24 * 4)
    return {"m15": m15, "h1": h1, "h4": h4, "B": B, "epoch": epoch, "n": n,
            "atr": atr, "hours": hours,
            "atr_lo": trailing_percentile(atr, ATR_LOOKBACK, ATR_LOW_PCT),
            "atr_hi": trailing_percentile(atr, ATR_LOOKBACK, ATR_HIGH_PCT),
            "h1_ok_long": h1_ok_long,
            "h1_ok_short": h1_ok_short, "h4_ok_long": h4_ok_long,
            "h4_ok_short": h4_ok_short, "holdout_start": holdout_start,
            "folds": [f for f in build_folds(epoch) if f[2] <= holdout_start]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--reps", type=int, default=60,
                    help="replications of the WHOLE selection procedure on random entries")
    ap.add_argument("--out", default="artifacts/gold_wfo_v2.json")
    a = ap.parse_args(argv)

    P = prepare(a.symbol, bars=a.bars)
    B, epoch, n = P["B"], P["epoch"], P["n"]
    atr, hours = P["atr"], P["hours"]
    h1_ok_long, h1_ok_short = P["h1_ok_long"], P["h1_ok_short"]
    h4_ok_long, h4_ok_short = P["h4_ok_long"], P["h4_ok_short"]
    holdout_start, folds = P["holdout_start"], P["folds"]
    print(f"folds in the search window: {len(folds)} x {FOLD_DAYS}d "
          f"(holdout: last {HOLDOUT_DAYS}d, {n - holdout_start} bars, untouched)")
    if len(folds) < 6:
        print("not enough folds")
        return 1

    all_cfgs = configs()
    print(f"grid: {len(all_cfgs)} configurations (stops {STOP_MULTS} ATR, "
          f"RR {RR_MULTS}, holds {MAX_HOLDS} bars)")

    trades_by_cfg = [simulate(B, hours, h1_ok_long, h1_ok_short, h4_ok_long,
                              h4_ok_short, atr, cfg, start=WARMUP_BARS,
                              end=holdout_start, atr_lo=P["atr_lo"],
                              atr_hi=P["atr_hi"]) for cfg in all_cfgs]
    tot_trades = sum(len(t) for t in trades_by_cfg)
    best_cfg_i = max(range(len(all_cfgs)),
                     key=lambda k: sum(t["net_r"] for t in trades_by_cfg[k]))
    print(f"in-sample trades across the grid: {tot_trades} "
          f"(best config alone: {len(trades_by_cfg[best_cfg_i])})")

    oos_rs, picks = walk_forward(trades_by_cfg, all_cfgs, folds)
    total = sum(oos_rs)
    n_oos = sum(p["n_oos"] for p in picks)
    per_trade = total / n_oos if n_oos else 0.0
    print(f"\n=== OUT OF SAMPLE (walk-forward, {len(oos_rs)} folds) ===")
    print(f"total {total:+.2f}R over {n_oos} trades = {per_trade:+.4f}R/trade")
    print(f"t-stat {tstat(oos_rs):+.2f}   positive folds "
          f"{sum(1 for r in oos_rs if r > 0)}/{len(oos_rs)}   "
          f"worst {min(oos_rs):+.2f}R   median {sorted(oos_rs)[len(oos_rs)//2]:+.2f}R")

    # ---- multiplicity control: replicate the WHOLE procedure on random entries ----
    print(f"\n=== MULTIPLICITY CONTROL: {a.reps} replications of the selection "
          f"procedure on random entries ===")
    held = [p["n_oos"] for p in picks]
    usable_by_fold = fold_usable(hours, atr, folds, holdout_start)
    fold_counts = [[sum(1 for t in trades_by_cfg[k] if nlo <= t["entry_i"] < nhi)
                    for _fn, nlo, nhi in folds] for k in range(len(all_cfgs))]
    rng = np.random.default_rng(NULL_SEED)
    null_totals: list[float] = []
    for _rep in range(a.reps):
        null_trades = [random_entries(B, hours, atr, cfg, fold_counts[k],
                                      usable_by_fold, end=holdout_start, rng=rng)
                       for k, cfg in enumerate(all_cfgs)]
        nrs, _null_picks = walk_forward(null_trades, all_cfgs, folds)
        null_totals.append(sum(nrs))
    null_totals.sort()
    p95 = null_totals[int(0.95 * len(null_totals))]
    p99 = null_totals[int(0.99 * len(null_totals))]
    beat = sum(1 for x in null_totals if x >= total)
    pval = (beat + 1) / (len(null_totals) + 1)
    print(f"null OOS total: median {null_totals[len(null_totals)//2]:+.2f}R  "
          f"p95 {p95:+.2f}R  p99 {p99:+.2f}R  max {null_totals[-1]:+.2f}R")
    print(f"strategy {total:+.2f}R  ->  p = {pval:.3f} "
          f"({'BEATS' if total > p95 else 'does NOT beat'} the p95 null)")

    verd = criteria(oos_rs, null_totals[len(null_totals) // 2])
    print("\n=== FROZEN CRITERIA ===")
    for k in ("V1 total>0", "V2 pos>=60%", "V3 worst>-3", "V4 beats control",
              "V5 median>0", "V6 t>=1.5"):
        print(f"  {k:<16} {'PASS' if verd[k] else 'FAIL'}")

    rules, risk_usd = None, 75.0
    try:
        from midas_prop.risk.upcomers_rules import ThunderboltClassicRules
        rules = ThunderboltClassicRules(account_size=25000.0)
    except Exception as exc:  # pragma: no cover
        print(f"(prop block unavailable: {exc})")
    prop = {}
    if rules is not None:
        # Only the trades the walk-forward actually exposed: the config picked on
        # fold k-1, scored inside fold k.
        oos_trades: list[dict] = []
        for fi in range(1, len(folds)):
            _nn, nlo, nhi = folds[fi]
            k = next(i for i, c in enumerate(all_cfgs)
                     if c == picks[fi - 1]["config"])
            oos_trades += [t for t in trades_by_cfg[k] if nlo <= t["entry_i"] < nhi]
        prop = prop_compat(oos_trades, epoch, rules, risk_usd)
        print(f"\n=== PROP COMPAT (1R = ${risk_usd:.0f}) ===\n"
              f"  final equity ${prop['final_equity']:,.2f} "
              f"(target ${prop['target_usd']:,.0f}: "
              f"{'MET' if prop['target_met'] else 'not met'})\n"
              f"  survived: {prop['survived']}   best day "
              f"{prop['best_day_r']:+.2f}R = {100*(prop['best_day_share'] or 0):.1f}% "
              f"of profit (cap {rules.best_day_pct:.0f}%: "
              f"{'OK' if prop['best_day_ok'] else 'BREACH'})")
        # Trade-level dump: concentration is the question this run raised, and
        # answering it needs the per-trade rows, not just fold totals.
        for t in oos_trades:
            t["utc"] = datetime.fromtimestamp(float(epoch[t["entry_i"]]),
                                              timezone.utc).isoformat()
        oos_dump = oos_trades

    out = {"symbol": a.symbol, "timeframe": EXEC_TF, "grid_size": len(all_cfgs),
           "generated_utc": datetime.now(timezone.utc).isoformat(),
           "window": [datetime.fromtimestamp(epoch[0], timezone.utc).isoformat(),
                      datetime.fromtimestamp(epoch[-1], timezone.utc).isoformat()],
           "holdout_bars": int(n - holdout_start),
           "oos_total_r": total, "oos_trades": n_oos,
           "oos_per_trade_r": per_trade, "oos_t": tstat(oos_rs),
           "oos_folds": len(oos_rs), "fold_rs": oos_rs,
           "positive_folds": sum(1 for r in oos_rs if r > 0),
           "picks": picks, "criteria": {k: bool(v) for k, v in verd.items()},
           "null": {"reps": a.reps, "median": null_totals[len(null_totals)//2],
                    "p95": p95, "p99": p99, "max": null_totals[-1],
                    "p_value": pval, "beats_p95": total > p95},
           "prop": prop, "held_by_fold": held,
           "oos_trade_dump": oos_dump if rules is not None else []}
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
