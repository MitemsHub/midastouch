#!/usr/bin/env python3
"""One-shot evaluation of an EXTERNALLY-SPECIFIED system: the 20/50 EMA cross on M15 gold.

WHY THIS EXISTS. On 2026-09-19 the operator supplied a social-media system for XAUUSD:

    "Two lines. That's the entire system. 20 EMA + 50 EMA on the 15M chart.
     Cross up = long. Cross down = short. SL, TP, RR - the indicator plots all three."
    Math slide: "1:2.5 RR = $125 target ... 1:2.5 needs >29% win rate to profit
                 ... realistic on 20/50 EMA: 45-50% win ... 3W/2L per week = +$275 net"

Its arithmetic checks out (break-even at 2.5R is 28.6%), so the system cannot be dismissed
on its maths. The load-bearing claim is the **45-50% win rate**, which is the one number the
carousel asserts without evidence. This script measures that number on real Upcomers gold.

DISCIPLINE. The ONLY free parameter is the stop distance, because the carousel never states
it ("the indicator plots all three" is not a specification). Three values are declared up
front and ALL THREE are reported -- the best is not cherry-picked. Reward:risk is fixed at
theirs (2.5). Entry is a plain cross with no regime filter, no ATR band and no session filter,
because that is what "two lines, that's the entire system" means.

HONEST CAVEAT, stated before the result: this is the same 2026-01-12..2026-09-18 window that
the gold walk-forward already used, so it is NOT a clean out-of-sample test. The system,
however, is specified *externally* and is not selected from this data, so a NEGATIVE result is
decisive while a positive one would only be suggestive.

Cost is the measured venue toll: spread 1.073 bps of price + $10/lot round-trip commission on
a gold lot worth $100 per $1.00 move (measured with mt5.order_calc_profit, not from the spec
fields, which are 10x wrong on this venue for XAUUSD).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mt5_data import load_m5  # noqa: E402
from gold_walkforward import ema, wilder_atr  # noqa: E402

#: The system's own constants, from the carousel.
EMA_FAST, EMA_SLOW = 20, 50
REWARD_RISK = 2.5
ATR_PERIOD = 14
FLAT_BY_UTC_HOUR = 22

SPREAD_BPS = 1.073          # measured, tick-derived
COMMISSION_PER_LOT_RT = 10.0
USD_PER_UNIT_PER_LOT = 100.0


def cost_r_per_trade(entry_price: float, stop_distance: float) -> float:
    """Round-trip toll in R: spread + commission, both expressed against the stop."""
    spread_price = SPREAD_BPS / 1e4 * entry_price
    return (spread_price / stop_distance
            + COMMISSION_PER_LOT_RT / (stop_distance * USD_PER_UNIT_PER_LOT))


def crosses(fast: np.ndarray, slow: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bars where fast crosses above (up) or below (down) slow, on closed values."""
    up = np.zeros(len(fast), dtype=bool)
    dn = np.zeros(len(fast), dtype=bool)
    up[1:] = (fast[1:] > slow[1:]) & (fast[:-1] <= slow[:-1])
    dn[1:] = (fast[1:] < slow[1:]) & (fast[:-1] >= slow[:-1])
    return up, dn


def run(bars: dict, atr: np.ndarray, hours: np.ndarray, *, stop_mult: float,
        flatten: bool, start: int) -> list[dict]:
    """Their system, one position at a time. Returns trades with gross/net R.

    A contrary cross while a position is open is IGNORED (no reversal): the carousel says
    cross up = long, cross down = short, which does not authorise reversing an open trade,
    and the conservative reading is the one that must be tested.
    """
    o, h, l, c, epoch = (bars["open"], bars["high"], bars["low"],
                         bars["close"], bars["epoch"])
    up, dn = crosses(ema(c, EMA_FAST), ema(c, EMA_SLOW))
    trades: list[dict] = []
    pos = None
    i = start
    n = len(c)
    while i < n:
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
            if px is None and flatten and int(hours[i]) >= FLAT_BY_UTC_HOUR:
                px = float(o[i])
            if px is not None:
                gross = pos["dir"] * (px - pos["entry"]) / pos["risk"]
                trades.append({
                    "entry_i": pos["i"], "exit_i": i, "dir": pos["dir"],
                    "entry": pos["entry"], "exit": px,
                    "gross_r": gross, "cost_r": pos["cost_r"],
                    "net_r": gross - pos["cost_r"],
                    "entry_epoch": float(epoch[pos["i"]]),
                    "exit_epoch": float(epoch[i]),
                })
                pos = None
        if pos is None and (up[i] or dn[i]):
            a = float(atr[i])
            if a > 0 and not np.isnan(a):
                d = 1 if up[i] else -1
                risk = stop_mult * a
                entry = float(c[i])
                pos = {"i": i, "dir": d, "entry": entry, "risk": risk,
                       "stop": entry - d * risk,
                       "target": entry + d * REWARD_RISK * risk,
                       "cost_r": cost_r_per_trade(entry, risk)}
        i += 1
    return trades


def summarize(trades: list[dict], folds_days: float) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    wins = [t for t in trades if t["net_r"] > 0]
    gross_wins = [t for t in trades if t["gross_r"] > 0]
    net = [t["net_r"] for t in trades]
    weeks = folds_days / 7.0
    return {
        "n": n,
        "win_rate_net": len(wins) / n,
        "win_rate_gross": len(gross_wins) / n,
        "expectancy_r": float(np.mean(net)),
        "gross_expectancy_r": float(np.mean([t["gross_r"] for t in trades])),
        "total_r": float(np.sum(net)),
        "avg_cost_r": float(np.mean([t["cost_r"] for t in trades])),
        "trades_per_week": n / weeks,
        "wins_per_week": len(wins) / weeks,
        "losses_per_week": (n - len(wins)) / weeks,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--stop-mults", default="0.5,1.0,1.5",
                    help="the ONE undocumented parameter; all values are reported")
    ap.add_argument("--out", default="artifacts/ema_cross_gold.json")
    a = ap.parse_args(argv)

    v = load_m5(a.symbol, timeframe="M15", bars=a.bars)
    A = v.array
    bars = {k: A[k].astype(float) for k in
            ("open", "high", "low", "close", "spread", "volume")}
    bars["epoch"] = A["epoch"].astype(float)
    epoch = bars["epoch"]
    n = len(epoch)
    atr = wilder_atr(bars["high"], bars["low"], bars["close"], ATR_PERIOD)
    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in epoch], dtype=int)
    start = max(100, ATR_PERIOD + 1)
    span_days = (epoch[-1] - epoch[start]) / 86400.0

    print(f"{a.symbol} M15: {n} bars  "
          f"{datetime.fromtimestamp(epoch[0], timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(epoch[-1], timezone.utc):%Y-%m-%d}  "
          f"({span_days:.0f} calendar days)")

    # ---- do their factual claims about gold even hold? ---------------------
    fast, slow = ema(bars["close"], EMA_FAST), ema(bars["close"], EMA_SLOW)
    up, dn = crosses(fast, slow)
    n_cross = int(up.sum() + dn.sum())
    print(f"\n== their claims about gold ==")
    print(f"  EMA20/50 crosses: {n_cross} in {span_days:.0f}d "
          f"= {n_cross / (span_days / 7):.1f} per week "
          f"({n_cross / span_days:.2f} per day)")
    # Daily range is max(high) - min(low) WITHIN the day. Summing the 96 M15 ranges
    # instead measures path length, not range, and overstated this by ~20x on the first
    # run -- which is exactly how a plausible-looking claim gets checked wrongly.
    d_hi: dict = {}
    d_lo: dict = {}
    for i in range(1, n):
        d = datetime.fromtimestamp(float(epoch[i]), timezone.utc).date()
        hi, lo = float(bars["high"][i]), float(bars["low"][i])
        d_hi[d] = hi if d not in d_hi else max(d_hi[d], hi)
        d_lo[d] = lo if d not in d_lo else min(d_lo[d], lo)
    ranges = np.array([d_hi[d] - d_lo[d] for d in sorted(d_hi)])
    med = float(np.median(ranges))
    print(f"  daily high-low range: median ${med:.2f} "
          f"(p10 ${np.percentile(ranges, 10):.2f}, p90 ${np.percentile(ranges, 90):.2f}) "
          f"= {med/np.median(bars['close'])*100:.2f}% of price "
          f"-> the 'moves $20-$40 a day' claim is "
          f"{'CONSISTENT' if 15 <= med <= 45 else ('UNDERSTATED' if med > 45 else 'OVERSOLD')}")
    brk = 1.0 / (1.0 + REWARD_RISK)
    print(f"  break-even win rate at {REWARD_RISK:g}R = {brk:.1%} (their '>29%' is correct)")

    # ---- the system itself -------------------------------------------------
    results = {}
    print(f"\n== the system, exactly as specified (only the stop distance varies) ==")
    print(f"{'stop':>6} {'flatten':>8} {'trades':>7} {'win%net':>8} {'win%grs':>8} "
          f"{'gross exp':>10} {'cost/R':>8} {'net exp':>9} {'totalR':>9} {'W/wk':>6} {'L/wk':>6}")
    for sm in [float(x) for x in a.stop_mults.split(",")]:
        for flatten in (False, True):
            tr = run(bars, atr, hours, stop_mult=sm, flatten=flatten, start=start)
            s = summarize(tr, span_days)
            key = f"stop{sm:g}_flat{int(flatten)}"
            results[key] = {"stop_mult": sm, "flatten": flatten, **s}
            if s["n"] == 0:
                print(f"{sm:>6g} {str(flatten):>8} {0:>7}")
                continue
            print(f"{sm:>6g} {str(flatten):>8} {s['n']:>7} "
                  f"{s['win_rate_net']:>7.1%} {s['win_rate_gross']:>8.1%} "
                  f"{s['gross_expectancy_r']:>+10.4f} {s['avg_cost_r']:>8.4f} "
                  f"{s['expectancy_r']:>+9.4f} {s['total_r']:>+9.1f} "
                  f"{s['wins_per_week']:>6.1f} {s['losses_per_week']:>6.1f}")

    print(f"\n  claimed: 45-50% win rate, 3W/2L per week")
    print(f"  break-even: {brk:.1%}")

    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "spec": {"symbol": a.symbol, "timeframe": "M15", "ema_fast": EMA_FAST,
                 "ema_slow": EMA_SLOW, "reward_risk": REWARD_RISK,
                 "spread_bps": SPREAD_BPS,
                 "commission_per_lot_rt": COMMISSION_PER_LOT_RT,
                 "usd_per_unit_per_lot": USD_PER_UNIT_PER_LOT,
                 "source": "operator-supplied social-media system",
                 "caveat": "same window as the gold walk-forward; NOT clean OOS"},
        "bars": n, "span_days": span_days, "crosses": n_cross,
        "median_daily_range_usd": float(np.median(ranges)),
        "break_even_win_rate": brk,
        "results": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nartifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
