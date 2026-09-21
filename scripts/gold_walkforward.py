#!/usr/bin/env python3
"""Pre-registered walk-forward for XAUUSD. Protocol: docs/GOLD_WFO_PROTOCOL.md.

Everything here is FIXED by that protocol and must not be edited after seeing a
result: the instrument, the window, the strategy family, the 24-configuration grid,
the cost model, the fold structure, the selection rule and the pass criteria.

THE POINT OF THE EXERCISE. Gold is the cheapest sizeable instrument on the venue at
**0.0247R** per round trip (`docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` §7). The
only edge this project has ever measured is V75's **+0.027R/trade gross** — i.e. the
toll consumes 92% of it. So the question is not "does gold trend?" but "does anything
in a declared, closed grid survive the toll OUT OF SAMPLE?" The protocol's declared
expectation is NOT VALIDATED.

THREE DESIGN DECISIONS THAT MAKE THIS HONEST RATHER THAN FLATTERING:

1. **Cost uses the tick-measured spread ($0.47), not the bar field.** The M15 bars
   carry a median `spread` of 21 points = $0.21, which is the broker's *nominal*
   figure and is 2.2x tighter than what real ticks show. Using the bar field would
   have made every result look better than it is.
2. **The cost basis is `order_calc_profit`, not the spec fields.** Measured on this
   venue, `trade_tick_value` is unreliable: it implies $10 per $1.00 gold move per lot
   while the server's own calculator returns $100. `XAGUSD` is wrong the other way.
   Only the server's calculator is authoritative, so gold is pinned at
   USD_PER_UNIT_PER_LOT = 100.0 measured, never inferred.
3. **Every position is flat by 22:00 UTC.** Gold reports `swap_mode = 9`, not a
   documented MT5 mode, so its overnight carry is unverified. Declared in the protocol
   before data, and it also removes the overnight gap exposure gapX = 3.10 warns about.

Costs are booked in R (size-independent): the full spread and the full commission are
subtracted from every trade's gross R.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from mt5_data import load_m5  # noqa: E402

# --------------------------------------------------------------------------- #
# FROZEN PROTOCOL CONSTANTS -- do not tune these after seeing a result
# --------------------------------------------------------------------------- #

SYMBOL = "XAUUSD"
EXEC_TF = "M15"
FOLD_DAYS = 8
WARMUP_BARS = 480
FLAT_BY_UTC_HOUR = 22
ATR_PERIOD = 14
ATR_LOOKBACK = 500
ATR_LOW_PCT, ATR_HIGH_PCT = 0.20, 0.95

#: Measured toll. Spread is the tick-derived mean (1.073 bps of price); commission is
#: the published metals schedule, $5/lot/side. USD_PER_UNIT_PER_LOT is MEASURED from
#: mt5.order_calc_profit (1.0 lot, $1.00 move -> $100.00), not read from the spec.
SPREAD_BPS = 1.073
COMMISSION_PER_LOT_RT = 10.0
USD_PER_UNIT_PER_LOT = 100.0

EMA_SETS = ((8, 21, 50), (12, 26, 100))
STOP_MULTS = (1.0, 1.5)
TP_MULTS = (1.5, 2.0, 3.0)
WINDOWS = ((7, 20), (13, 18))
CONTROL_SEED = 20260919

H1_TF_SEC, H4_TF_SEC, M15_TF_SEC = 3600, 14400, 900


# --------------------------------------------------------------------------- #
# Pure indicators
# --------------------------------------------------------------------------- #


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Standard EMA (alpha = 2/(n+1)), seeded on the first value.

    Seeded rather than warm-started-and-NaN'd: every consumer here only reads the
    value at well past ``period``, and a seeded series has no hole to accidentally
    index into.
    """
    out = np.empty(len(values), dtype=float)
    if len(values) == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    acc = float(values[0])
    out[0] = acc
    for i in range(1, len(values)):
        acc = acc + alpha * (float(values[i]) - acc)
        out[i] = acc
    return out


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               period: int = 14) -> np.ndarray:
    """Wilder's ATR. Entry 0..period-1 are NaN so a caller cannot use a partial ATR."""
    n = len(close)
    tr = np.empty(n, dtype=float)
    tr[0] = float(high[0]) - float(low[0])
    for i in range(1, n):
        tr[i] = max(float(high[i]) - float(low[i]),
                    abs(float(high[i]) - float(close[i - 1])),
                    abs(float(low[i]) - float(close[i - 1])))
    out = np.full(n, np.nan, dtype=float)
    if n <= period:
        return out
    out[period] = tr[1:period + 1].mean()
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def trailing_percentile(values: np.ndarray, window: int, pct: float) -> np.ndarray:
    """Percentile of the trailing `window` values, computed causally.

    The value at index i is the percentile of ``values[i-window+1 : i+1]``, so it
    looks strictly backwards. Getting this wrong (e.g. using the whole-series
    percentile) is the classic way a backtest learns the future, and the ATR band is
    exactly where it would show up.
    """
    n = len(values)
    out = np.full(n, np.nan, dtype=float)
    if n < window:
        return out
    for i in range(window - 1, n):
        chunk = values[i - window + 1:i + 1]
        chunk = chunk[~np.isnan(chunk)]
        if len(chunk) >= 20:
            out[i] = float(np.percentile(chunk, pct * 100.0))
    return out


def last_closed_index(epochs: np.ndarray, t: float, tf_sec: int) -> int:
    """Index of the last bar that had FULLY CLOSED by time `t`, or -1.

    ``epoch`` is a bar's OPEN time, so a bar is closed once ``epoch + tf_sec <= t``.
    Comparing ``epoch <= t`` instead would let a live H1 bar inform an M15 decision,
    which is look-ahead.
    """
    idx = int(np.searchsorted(epochs, t - tf_sec, side="right")) - 1
    return idx


# --------------------------------------------------------------------------- #
# Strategy
# --------------------------------------------------------------------------- #


def configs() -> list[dict]:
    """The 24 pre-registered configurations, in the protocol's declared order."""
    out = []
    for emas in EMA_SETS:
        for sm in STOP_MULTS:
            for tp in TP_MULTS:
                for (lo, hi) in WINDOWS:
                    out.append({"emas": emas, "stop_mult": sm, "tp_mult": tp,
                                "win_lo": lo, "win_hi": hi})
    return out


def simulate(bars: dict, hours: np.ndarray, h1_ok_long: np.ndarray,
             h1_ok_short: np.ndarray, h4_ok_long: np.ndarray,
             h4_ok_short: np.ndarray,
             atr: np.ndarray, cfg: dict, *, start: int, end: int) -> list[dict]:
    """Run one configuration over bars[start:end). Returns trade dicts with net R.

    Exits, in priority order, checked on each bar *after* entry:
      1. gap through the stop  -> fill at the bar's OPEN (a stop cannot fill at its
         own price when the market opens beyond it);
      2. stop or target touched -> if BOTH are inside one bar, the STOP is assumed
         first. That is the pessimistic reading and the only one that cannot be
         accused of flattering the result;
      3. forced flat at FLAT_BY_UTC_HOUR -> fill at that bar's open.
    Only one position at a time: never adds, never hedges.
    """
    o, h, l, c, epoch = (bars["open"], bars["high"], bars["low"],
                         bars["close"], bars["epoch"])
    e_f, e_m, e_s = (ema(c, cfg["emas"][0]), ema(c, cfg["emas"][1]), ema(c, cfg["emas"][2]))
    atr_lo = trailing_percentile(atr, ATR_LOOKBACK, ATR_LOW_PCT)
    atr_hi = trailing_percentile(atr, ATR_LOOKBACK, ATR_HIGH_PCT)

    trades: list[dict] = []
    pos = None
    i = max(start, WARMUP_BARS, ATR_LOOKBACK)

    def hour_of(idx: int) -> int:
        return int(hours[idx])

    while i < end:
        if pos is not None:
            px = None
            if pos["dir"] > 0:
                if float(o[i]) <= pos["stop"]:
                    px = float(o[i])
                elif float(l[i]) <= pos["stop"]:
                    px = pos["stop"]
                elif float(h[i]) >= pos["target"]:
                    px = pos["target"]
            else:
                if float(o[i]) >= pos["stop"]:
                    px = float(o[i])
                elif float(h[i]) >= pos["stop"]:
                    px = pos["stop"]
                elif float(l[i]) <= pos["target"]:
                    px = pos["target"]
            forced = hour_of(i) >= FLAT_BY_UTC_HOUR
            if px is None and forced:
                px = float(o[i])
            if px is not None:
                gross = pos["dir"] * (px - pos["entry"]) / pos["risk"]
                spread_r = pos["spread_price"] / pos["risk"]
                comm_r = pos["comm_r"]
                trades.append({
                    "entry_i": pos["i"], "exit_i": i, "dir": pos["dir"],
                    "entry": pos["entry"], "exit": px,
                    "gross_r": gross, "spread_r": spread_r, "comm_r": comm_r,
                    "net_r": gross - spread_r - comm_r,
                    "forced": bool(forced and px == float(o[i])),
                })
                pos = None
        
        if pos is None and not (i + 1 < end):
            i += 1
            continue
        if pos is None:
            hr = hour_of(i)
            if cfg["win_lo"] <= hr <= cfg["win_hi"] and hr < FLAT_BY_UTC_HOUR:
                a = float(atr[i])
                lo, hi = atr_lo[i], atr_hi[i]
                band_ok = (not math.isnan(a) and not math.isnan(lo)
                           and not math.isnan(hi) and lo < a <= hi)
                if band_ok and a > 0:
                    up = (e_f[i] > e_m[i] > e_s[i])
                    dn = (e_f[i] < e_m[i] < e_s[i])
                    direction = 0
                    if up and h1_ok_long[i] and h4_ok_long[i]:
                        direction = 1
                    elif dn and h1_ok_short[i] and h4_ok_short[i]:
                        direction = -1
                    if direction:
                        risk = cfg["stop_mult"] * a
                        entry = float(c[i])
                        pos = {
                            "i": i, "dir": direction, "entry": entry, "risk": risk,
                            "stop": entry - direction * risk,
                            "target": entry + direction * cfg["tp_mult"] * a,
                            "spread_price": SPREAD_BPS / 1e4 * entry,
                            "comm_r": COMMISSION_PER_LOT_RT / (risk * USD_PER_UNIT_PER_LOT),
                        }
        i += 1
    return trades


def random_control(bars: dict, hours: np.ndarray, atr: np.ndarray, n_trades: int,
                   cfg: dict, *, start: int, end: int, seed: int) -> list[dict]:
    """Same geometry, same costs, same trade count -- only timing and direction randomised.

    This is the test that matters (protocol V4). A positive backtest can come from
    drift, from lucky streaks, or from the geometry itself; the control holds all of
    those constant and randomises the ONE thing the strategy claims as its edge --
    *when* to enter and *which way*. If the family cannot beat this, it has no edge.

    Entry bars are drawn uniformly from the same session window so the control faces
    the same volatility regime and the same clock, not an easier one.
    """
    rng = np.random.default_rng(seed)
    o, h, l, c = (bars["open"], bars["high"], bars["low"], bars["close"])
    lo_i = max(start, WARMUP_BARS, ATR_LOOKBACK)
    usable = np.array([k for k in range(lo_i, end)
                       if cfg["win_lo"] <= hours[k] <= cfg["win_hi"]
                       and hours[k] < FLAT_BY_UTC_HOUR])
    out: list[dict] = []
    if len(usable) == 0 or n_trades <= 0:
        return out
    for k in range(n_trades):
        i = int(usable[k % len(usable)])
        a = float(atr[i])
        if not (a > 0):
            continue
        direction = 1 if rng.random() < 0.5 else -1
        risk = cfg["stop_mult"] * a
        entry = float(c[i])
        stop = entry - direction * risk
        target = entry + direction * cfg["tp_mult"] * a
        px = None
        j = i + 1
        while j < end:
            hr = int(hours[j])
            if direction > 0:
                if float(o[j]) <= stop:
                    px = float(o[j]); break
                if float(l[j]) <= stop:
                    px = stop; break
                if float(h[j]) >= target:
                    px = target; break
            else:
                if float(o[j]) >= stop:
                    px = float(o[j]); break
                if float(h[j]) >= stop:
                    px = stop; break
                if float(l[j]) <= target:
                    px = target; break
            if hr >= FLAT_BY_UTC_HOUR:
                px = float(o[j]); break
            j += 1
        if px is None:
            continue
        gross = direction * (px - entry) / risk
        spread_r = (SPREAD_BPS / 1e4 * entry) / risk
        comm_r = COMMISSION_PER_LOT_RT / (risk * USD_PER_UNIT_PER_LOT)
        out.append({"entry_i": i, "gross_r": gross,
                    "net_r": gross - spread_r - comm_r})
    return out


# --------------------------------------------------------------------------- #
# Folds and criteria
# --------------------------------------------------------------------------- #


def build_folds(epochs: np.ndarray, fold_days: int = FOLD_DAYS,
                warmup: int = WARMUP_BARS) -> list[tuple[str, int, int]]:
    """Contiguous calendar folds as (name, start_idx, end_idx) over closed bars."""
    if len(epochs) <= warmup:
        return []
    t0, t_end = float(epochs[warmup]), float(epochs[-1])
    folds, cur, n = [], t0, 0
    while cur < t_end:
        nxt = cur + fold_days * 86400.0
        j = int(np.searchsorted(epochs, nxt, side="left"))
        folds.append((f"F{n+1:02d}", 0 if n == 0 else folds[-1][2], j))
        cur = nxt
        n += 1
    return [f for f in folds if f[2] - f[1] > 0]


def tstat(rs: list[float]) -> float:
    """t-statistic of the fold-level means (mirrors scripts/walkforward_v75.py)."""
    m = len(rs)
    if m < 2:
        return 0.0
    mean = sum(rs) / m
    var = sum((x - mean) ** 2 for x in rs) / (m - 1)
    return mean / (math.sqrt(var) / math.sqrt(m)) if var > 0 else 0.0


def fold_r(trades: list[dict], folds: list[tuple[str, int, int]]) -> list[float]:
    """Total net R per fold, attributing each trade to the fold of its ENTRY bar."""
    out = []
    for _name, lo, hi in folds:
        out.append(sum(t["net_r"] for t in trades if lo <= t["entry_i"] < hi))
    return out


def prop_compat(trades: list[dict], epoch: np.ndarray, rules, risk_usd: float) -> dict:
    """Would this equity path have survived the prop rules? Day granularity.

    WHY THIS IS NOT A RAW DRAWDOWN NUMBER. The Thunderbolt shield trails the equity
    high-water mark and **locks at the initial balance** once the account is 6% up. So
    a 29R give-back taken *from profit* is not the same event as a 29R drawdown taken
    from the starting balance: the first can be harmless, the second ends the account.
    Reporting peak-to-trough as an equity breach would have been wrong, which is why
    this uses the venue's own :meth:`ThunderboltClassicRules.drawdown_floor_usd`
    rather than restating the rule.

    P&L is attributed to the UTC day of the ENTRY bar.
    """
    byday: dict = {}
    for t in trades:
        day = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()
        byday[day] = byday.get(day, 0.0) + t["net_r"]
    days = sorted(byday)
    equity = rules.account_size
    peak = rules.account_size
    shield_hits, daily_hits = [], []
    best_day_r, worst_day_r = 0.0, 0.0
    for d in days:
        daily_floor = equity - rules.daily_loss_limit_usd
        equity += byday[d] * risk_usd
        peak = max(peak, equity)
        if equity < daily_floor:
            daily_hits.append((str(d), round(byday[d], 2)))
        if equity < rules.drawdown_floor_usd(peak):
            shield_hits.append((str(d), round(equity, 2)))
        best_day_r = max(best_day_r, byday[d])
        worst_day_r = min(worst_day_r, byday[d])
    total_usd = equity - rules.account_size
    best_day_usd = best_day_r * risk_usd
    return {
        "days": len(days),
        "final_equity": round(equity, 2),
        "total_usd": round(total_usd, 2),
        "target_usd": rules.profit_target_usd,
        "target_met": total_usd >= rules.profit_target_usd,
        "shield_breaches": shield_hits[:5],
        "daily_breaches": daily_hits[:5],
        "survived": not shield_hits and not daily_hits,
        "worst_day_r": round(worst_day_r, 2),
        "worst_day_usd": round(worst_day_r * risk_usd, 2),
        "daily_limit_usd": rules.daily_loss_limit_usd,
        "best_day_r": round(best_day_r, 2),
        "best_day_usd": round(best_day_usd, 2),
        "best_day_share": round(best_day_usd / total_usd, 3) if total_usd > 0 else None,
        "best_day_limit": rules.best_day_pct / 100.0,
        "best_day_ok": (best_day_usd / total_usd <= rules.best_day_pct / 100.0)
                       if total_usd > 0 else None,
    }


def criteria(rs: list[float], control_total: float) -> dict:
    """The frozen V1-V6 block from docs/GOLD_WFO_PROTOCOL.md section 6."""
    tot = sum(rs)
    pos = sum(1 for x in rs if x > 0)
    srt = sorted(rs)
    n = len(rs)
    median = (srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2) if n else 0.0
    return {
        "V1 total>0": tot > 0,
        "V2 pos>=60%": pos >= 0.6 * n,
        "V3 worst>-3": (min(rs) > -3.0) if rs else False,
        "V4 beats control": tot > control_total,
        "V5 median>0": median > 0,
        "V6 t>=1.5": tstat(rs) >= 1.5,
        "_total": tot, "_pos": pos, "_n": n, "_median": median, "_t": tstat(rs),
        "_control": control_total,
    }


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_wfo.json")
    ap.add_argument("--control-reps", type=int, default=200,
                    help="random-control repetitions; the control total is their mean")
    ap.add_argument("--risk-usd", type=float, default=75.0,
                    help="1R in dollars, for the prop-rule compatibility block")
    a = ap.parse_args(argv)

    m15 = load_m5(a.symbol, timeframe=EXEC_TF, bars=a.bars)
    h1 = load_m5(a.symbol, timeframe="H1", bars=a.bars // 4 + 100)
    h4 = load_m5(a.symbol, timeframe="H4", bars=a.bars // 16 + 100)
    B = {k: m15.array[k].astype(float) for k in
         ("epoch", "open", "high", "low", "close", "spread", "volume")}
    epoch = B["epoch"]
    n = len(epoch)
    print(f"{a.symbol} {EXEC_TF}: {n} bars  "
          f"{datetime.fromtimestamp(epoch[0], timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(epoch[-1], timezone.utc):%Y-%m-%d}")

    atr = wilder_atr(B["high"], B["low"], B["close"], ATR_PERIOD)

    # Regime flags, causal: only bars that had fully closed by the M15 bar's open time.
    h1e = h1.array["epoch"].astype(float)
    h1c = h1.array["close"].astype(float)
    h1_ef, h1_em, h1_es = (ema(h1c, k) for k in (8, 21, 50))
    h4e = h4.array["epoch"].astype(float)
    h4c = h4.array["close"].astype(float)
    h4_ef = ema(h4c, 20)

    h1_ok_long = np.zeros(n, dtype=bool)
    h1_ok_short = np.zeros(n, dtype=bool)
    h4_ok_long = np.zeros(n, dtype=bool)
    h4_ok_short = np.zeros(n, dtype=bool)
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

    folds = build_folds(epoch)
    print(f"folds: {len(folds)} x {FOLD_DAYS}d  "
          f"({datetime.fromtimestamp(epoch[folds[0][1]], timezone.utc):%m-%d} .. "
          f"{datetime.fromtimestamp(epoch[folds[-1][2] - 1], timezone.utc):%m-%d})")

    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in epoch], dtype=int)

    all_cfgs = configs()
    trades_by_cfg: list[list[dict]] = []
    for cfg in all_cfgs:
        trades_by_cfg.append(simulate(B, hours, h1_ok_long, h1_ok_short, h4_ok_long,
                                      h4_ok_short, atr, cfg, start=WARMUP_BARS, end=n))

    # ---- walk-forward: select on fold k ONLY, score that pick on fold k+1 ONLY ----
    oos_rs: list[float] = []
    picks: list[dict] = []
    prev_pick = max(range(len(all_cfgs)),
                    key=lambda k: sum(t["net_r"] for t in trades_by_cfg[k]))
    for fi in range(1, len(folds)):
        _pn, plo, phi = folds[fi - 1]
        _n2, nlo, nhi = folds[fi]
        scored = []
        for k, tr in enumerate(trades_by_cfg):
            r = sum(t["net_r"] for t in tr if plo <= t["entry_i"] < phi)
            cfgd = all_cfgs[k]
            # deterministic tie-break, declared in the protocol
            scored.append((r, -cfgd["stop_mult"], -cfgd["tp_mult"], -k, k))
        scored.sort(reverse=True)
        if scored[0][0] != 0.0:
            prev_pick = scored[0][4]
        pick = prev_pick
        oos = sum(t["net_r"] for t in trades_by_cfg[pick]
                  if nlo <= t["entry_i"] < nhi)
        oos_rs.append(oos)
        picks.append({"fold": folds[fi][0], "selected_on": folds[fi - 1][0],
                      "config": all_cfgs[pick], "oos_r": oos})

    # ---- random-entry control: SAME picks, SAME per-fold trade counts, SAME costs ---
    held_by_fold: list[int] = []
    for fi in range(1, len(folds)):
        _n2, nlo, nhi = folds[fi]
        k = _pick_index(all_cfgs, picks[fi - 1]["config"])
        held_by_fold.append(sum(1 for t in trades_by_cfg[k]
                                if nlo <= t["entry_i"] < nhi))
    n_oos_trades = sum(held_by_fold)

    oos_detail: list[dict] = []
    for fi in range(1, len(folds)):
        _n2, nlo, nhi = folds[fi]
        k = _pick_index(all_cfgs, picks[fi - 1]["config"])
        for t in trades_by_cfg[k]:
            if nlo <= t["entry_i"] < nhi:
                oos_detail.append({"fold": folds[fi][0], "entry_i": t["entry_i"],
                                   "dir": t["dir"], "net_r": t["net_r"]})

    control_totals = []
    for rep in range(a.control_reps):
        tot = 0.0
        for fi in range(1, len(folds)):
            _n2, nlo, nhi = folds[fi]
            tot += sum(t["net_r"] for t in random_control(
                B, hours, atr, held_by_fold[fi - 1], picks[fi - 1]["config"],
                start=nlo, end=nhi, seed=CONTROL_SEED + rep * 1000 + fi))
        control_totals.append(tot)
    control_total = float(np.mean(control_totals)) if control_totals else 0.0

    checks = criteria(oos_rs, control_total)
    ok = all(v for k, v in checks.items() if k.startswith("V"))

    print(f"\n== OOS folds ({len(oos_rs)}) ==")
    for p in picks:
        print(f"  {p['fold']} (picked on {p['selected_on']}): "
              f"stop={p['config']['stop_mult']} tp={p['config']['tp_mult']} "
              f"emas={p['config']['emas']} win={p['config']['win_lo']}-{p['config']['win_hi']}"
              f"  -> {p['oos_r']:+7.2f}R")
    print(f"\nOOS trades={n_oos_trades}  total={sum(oos_rs):+.2f}R  "
          f"mean={np.mean(oos_rs):+.3f}R/fold  t={tstat(oos_rs):+.2f}")
    print(f"random-entry control (mean of {a.control_reps} reps) = {control_total:+.2f}R")
    flags = " ".join(f"[{'P' if v else 'F'}]{k.split()[0]}"
                     for k, v in checks.items() if k.startswith("V"))
    verdict = ("CONTINUE-UNPROVEN" if n_oos_trades < 30
               else ("PROVISIONAL EDGE" if ok else "NOT VALIDATED"))
    print(f"  {flags}  -> {verdict}")

    # Leave-one-fold-out: is the whole total carried by a single 8-day window?
    tot_oos = sum(oos_rs)
    best_fold_r, worst_fold_r = max(oos_rs), min(oos_rs)
    print(f"\nleave-one-fold-out: dropping the BEST fold ({best_fold_r:+.2f}R) "
          f"leaves {tot_oos - best_fold_r:+.2f}R; "
          f"dropping the WORST ({worst_fold_r:+.2f}R) leaves {tot_oos - worst_fold_r:+.2f}R")

    from midas_prop.risk.upcomers_rules import ThunderboltClassicRules
    risk_usd = a.risk_usd
    prop = prop_compat(oos_detail, epoch, ThunderboltClassicRules(), risk_usd)
    print(f"\n== prop compatibility (1R = ${risk_usd:.0f} on the $25,000 account) ==")
    print(f"  {prop['days']} trading days, final equity ${prop['final_equity']:,.2f} "
          f"({prop['total_usd']:+,.2f}; target is {prop['target_usd']:,.0f} -> "
          f"{'MET' if prop['target_met'] else 'not met'})")
    print(f"  worst day {prop['worst_day_r']:+.2f}R = ${prop['worst_day_usd']:,.0f} "
          f"vs 3% daily limit ${prop['daily_limit_usd']:,.0f}")
    print(f"  best day  {prop['best_day_r']:+.2f}R = ${prop['best_day_usd']:,.0f} "
          f"= {prop['best_day_share']:.1%} of total profit vs 20% Best Day limit -> "
          f"{'OK' if prop['best_day_ok'] else 'BREACH'}")
    print(f"  shield/daily violations: {prop['shield_breaches']} {prop['daily_breaches']}"
          f"  -> {'SURVIVED' if prop['survived'] else 'BREACHED'}")

    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "spec": {
            "symbol": a.symbol, "exec_tf": EXEC_TF, "fold_days": FOLD_DAYS,
            "warmup_bars": WARMUP_BARS, "flat_by_utc_hour": FLAT_BY_UTC_HOUR,
            "spread_bps": SPREAD_BPS, "commission_per_lot_rt": COMMISSION_PER_LOT_RT,
            "usd_per_unit_per_lot": USD_PER_UNIT_PER_LOT,
            "grid": {"ema_sets": EMA_SETS, "stop_mults": STOP_MULTS,
                     "tp_mults": TP_MULTS, "windows": WINDOWS},
            "n_configs": len(all_cfgs), "control_seed": CONTROL_SEED,
            "control_reps": a.control_reps,
            "protocol": "docs/GOLD_WFO_PROTOCOL.md",
        },
        "data": {"bars": n,
                 "first": str(datetime.fromtimestamp(epoch[0], timezone.utc)),
                 "last": str(datetime.fromtimestamp(epoch[-1], timezone.utc))},
        "folds": [{"name": f[0], "start_i": f[1], "end_i": f[2]} for f in folds],
        "picks": picks,
        "oos_r_per_fold": oos_rs,
        "checks": {k: bool(v) for k, v in checks.items() if k.startswith("V")},
        "stats": {k: checks[k] for k in checks if k.startswith("_")},
        "control_total_r": control_total,
        "oos_trades": n_oos_trades,
        "leave_one_fold_out": {"without_best": round(tot_oos - best_fold_r, 2),
                               "best_fold_r": round(best_fold_r, 2),
                               "without_worst": round(tot_oos - worst_fold_r, 2),
                               "worst_fold_r": round(worst_fold_r, 2)},
        "prop_compat": prop,
        "verdict": verdict,
    }, indent=2, default=str), encoding="utf-8")
    print(f"artifact: {out}")
    return 0


def _pick_index(all_cfgs: list[dict], cfg: dict) -> int:
    """Grid index of a configuration dict (identity by value)."""
    for k, c in enumerate(all_cfgs):
        if c == cfg:
            return k
    raise KeyError(cfg)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
