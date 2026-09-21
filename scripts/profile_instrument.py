#!/usr/bin/env python3
"""Profile an instrument by hour of day: where it moves, where it is cheap, and how it gaps.

WHY THIS EXISTS. Every preset this repo has ever shipped was fitted to a
**synthetic** index, and our own `GENERATOR_FINGERPRINT.md` established that those
are memoryless step machines with constant volatility and **no clock** — V75 moves
the same at 03:00 as at 15:00, and it never gaps.

An equity index is the opposite on all three counts:

* it moves on a **session rhythm** (Nasdaq does most of its work in the US cash
  session and very little in Asian hours);
* its **spread varies by hour** (tight when the underlying is liquid, wide when it
  is not), so the same trade costs different amounts at different times;
* it **gaps** — overnight and over the weekend — which a stop-loss cannot protect
  against, because the fill happens after the move.

So before a single parameter is re-fitted, the instrument has to be described. That
is what this script does, and it is the first thing to run once the terminal is up.

The decisive output is `best_window`: the contiguous block of hours that maximises
movement per unit of spread cost. Trading only there is free alpha relative to
trading everywhere, and it is exactly the lever that a synthetic index never offered.

Pure functions (`atr_by_hour`, `spread_bps_by_hour`, `gap_stats`, `best_window`)
operate on plain sequences so they are unit-testable without a terminal.

Usage:
    MT5_PASSWORD='...' python scripts/profile_instrument.py \\
        --symbol NACUSD.c --login 1428765 --server Upcomers-Server \\
        --days 365 --out artifacts/nacusd_profile.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: Nasdaq and the US cash session. Used only to label the output, never to filter.
US_CASH_OPEN_UTC = 13
US_CASH_CLOSE_UTC = 21


# --------------------------------------------------------------------------- #
# Pure: hour-of-day profile
# --------------------------------------------------------------------------- #


def atr_by_hour(bars: Sequence[Mapping[str, float]]) -> dict[int, float]:
    """Mean true range per UTC hour of day.

    `bars` are dicts with ``hour`` (0-23), ``high``, ``low``, and ``close`` where
    ``close`` is the PREVIOUS bar's close for the true-range calculation. Returns
    the mean TR for each hour, averaged over however many days are supplied.

    Bin-by-hour rather than a rolling ATR on purpose: the question is not "how
    volatile is this instrument" but "**when** is it volatile", and an average over
    the whole day answers the wrong one.
    """
    buckets: dict[int, list[float]] = {}
    for b in bars:
        tr = max(
            float(b["high"]) - float(b["low"]),
            abs(float(b["high"]) - float(b["prev_close"])),
            abs(float(b["low"]) - float(b["prev_close"])),
        )
        buckets.setdefault(int(b["hour"]), []).append(tr)
    return {h: statistics.fmean(v) for h, v in buckets.items() if v}


def spread_bps_by_hour(samples: Sequence[Mapping[str, float]]) -> dict[int, float]:
    """Mean spread per UTC hour, in basis points of mid price.

    Basis points, not price units, because that is the only form in which two
    instruments or two hours can be compared. A 2-point spread on Nasdaq and a
    0.5-point spread on the S&P are not comparable numbers until both are divided
    by their own price.
    """
    buckets: dict[int, list[float]] = {}
    for s in samples:
        mid = float(s["mid"])
        if mid <= 0:
            continue
        bps = (float(s["spread"]) / mid) * 1e4
        buckets.setdefault(int(s["hour"]), []).append(bps)
    return {h: statistics.fmean(v) for h, v in buckets.items() if v}


def quality_by_hour(atr: Mapping[int, float], spread_bps: Mapping[int, float],
                    ) -> dict[int, float]:
    """Movement per unit of cost, per hour. Higher is better; this is what ranks hours.

    ``atr`` is in price units and ``spread_bps`` in basis points, so the ratio is
    scaled to be dimensionless: ATR is converted to bps of mid first. Hours with no
    spread sample are omitted rather than treated as free.
    """
    out: dict[int, float] = {}
    for h, a in atr.items():
        s = spread_bps.get(h)
        if not s or s <= 0:
            continue
        out[h] = a / (s / 1e4)  # a in bps of mid, divided by cost in bps
    return out


def best_window(quality: Mapping[int, float], hours: int = 6,
                require_contiguous: bool = True) -> tuple[list[int], float]:
    """The `hours`-long window with the highest total quality score.

    Returns the hour list and its mean score. Hours are UTC and treated as a
    circular day, so a window may wrap past midnight — sessions do not respect the
    date boundary.
    """
    if not quality:
        return [], 0.0
    if hours > len(quality):
        hours = len(quality)
    present = sorted(quality)
    if not require_contiguous:
        top = sorted(quality, key=lambda h: -quality[h])[:hours]
        return sorted(top), statistics.fmean(quality[h] for h in top)
    best: tuple[list[int], float] = ([], float("-inf"))
    for start in present:
        win = [(start + i) % 24 for i in range(hours)]
        if any(h not in quality for h in win):
            continue
        score = statistics.fmean(quality[h] for h in win)
        if score > best[1]:
            best = (sorted(win), score)
    if best[1] == float("-inf"):
        return [], 0.0
    return best


# --------------------------------------------------------------------------- #
# Pure: gap behaviour
# --------------------------------------------------------------------------- #


def gap_stats(days: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """Overnight and weekend gap statistics from daily OHLC.

    An `open` above or below the previous `close` is a gap. It is the one risk this
    EA has **never faced** — a synthetic index is continuous, so a stop was always
    filled where it was placed. On an index the market can open beyond the stop and
    the fill happens there instead, which turns "risk $75" into "risk $X".

    Returns absolute-gap percentiles plus the worst adverse gap, both directions.
    """
    gaps: list[float] = []
    weekend_gaps: list[float] = []
    for i in range(1, len(days)):
        prev_close = float(days[i - 1]["close"])
        if prev_close <= 0:
            continue
        g = (float(days[i]["open"]) - prev_close) / prev_close
        gaps.append(g)
        # A Monday open follows three calendar days of closure.
        if str(days[i].get("weekday", "")).lower().startswith("mon"):
            weekend_gaps.append(g)
    if not gaps:
        return {}
    absg = sorted(abs(g) for g in gaps)

    def pct(p: float) -> float:
        idx = min(len(absg) - 1, int(round(p * (len(absg) - 1))))
        return absg[idx] * 100.0

    return {
        "n_days": float(len(gaps)),
        "abs_gap_p50_pct": pct(0.50),
        "abs_gap_p95_pct": pct(0.95),
        "abs_gap_max_pct": absg[-1] * 100.0,
        "worst_adverse_gap_pct": min(gaps) * 100.0,
        "worst_favourable_gap_pct": max(gaps) * 100.0,
        "mean_abs_gap_pct": statistics.fmean(absg) * 100.0,
        "n_weekend_gaps": float(len(weekend_gaps)),
        "worst_weekend_gap_pct": (min(weekend_gaps) * 100.0) if weekend_gaps else 0.0,
    }


def gap_breach_multiple(gap_pct: float, stop_distance_pct: float) -> float:
    """How many times over a stop a gap of `gap_pct` blows through it.

    The number that decides whether overnight holding is permitted at all. A result
    of 3.0 means the worst historical gap moved three times the stop distance, so a
    stop would have been filled at three times the intended risk.
    """
    if stop_distance_pct <= 0:
        raise ValueError("stop_distance_pct must be positive")
    return abs(gap_pct) / stop_distance_pct


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

_HOUR_LABEL = {US_CASH_OPEN_UTC: "  <- US cash open",
               US_CASH_CLOSE_UTC: "  <- US cash close"}


def render(atr: Mapping[int, float], spread_bps: Mapping[int, float],
           quality: Mapping[int, float], window: Sequence[int],
           window_score: float, gaps: Mapping[str, float]) -> str:
    lines = ["== hourly profile (UTC) ==", "",
             f"   {'hr':>3} {'ATR':>12} {'spread_bps':>11} {'move/cost':>10}"]
    for h in range(24):
        a = atr.get(h)
        s = spread_bps.get(h)
        q = quality.get(h)
        mark = " *" if h in window else ""
        lines.append(
            f"   {h:>3} {('' if a is None else f'{a:.4f}'):>12} "
            f"{('' if s is None else f'{s:.3f}'):>11} "
            f"{('' if q is None else f'{q:.1f}'):>10}{mark}{_HOUR_LABEL.get(h, '')}"
        )
    lines += ["", f"   best {len(list(window))}-hour window (UTC): {list(window)}",
              f"   mean move/cost in window: {window_score:.1f}"]
    if gaps:
        lines += ["", "== gap behaviour (the risk a synthetic index never had) =="]
        for k, v in gaps.items():
            lines.append(f"   {k:<26} {v:>10.3f}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Live collection
# --------------------------------------------------------------------------- #


def collect(symbol: str, days: int, terminal: str | None,
            tick_days: int | None = None) -> tuple[list, list, list]:
    """Read H1 bars, tick-derived hourly spreads, and daily bars. Read-only.

    ``tick_days`` caps how many days of ticks are sampled for the spread
    estimate. Ticks are the expensive part of this function -- a liquid index
    produces millions per day -- so a caller ranking a dozen symbols at once
    should pass a small value and accept a coarser, still measured, spread.
    None keeps the original behaviour of up to 14 days.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:  # pragma: no cover
        raise SystemExit("MetaTrader5 package not installed.")

    kwargs: dict = {"timeout": 120_000}
    if terminal:
        kwargs["path"] = terminal
    if not mt5.initialize(**kwargs):
        raise SystemExit(
            f"mt5.initialize failed: {mt5.last_error()} — the terminal must be "
            "running and logged in to Upcomers-Server"
        )

    import datetime as dt

    h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, min(days * 24, 90_000))
    d1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, min(days, 5_000))
    if h1 is None or d1 is None:
        mt5.shutdown()
        raise SystemExit(f"no history for {symbol!r} — check the exact symbol name")

    bars = []
    for i in range(1, len(h1)):
        ts = dt.datetime.fromtimestamp(int(h1[i]["time"]), dt.timezone.utc)
        bars.append({"hour": ts.hour, "high": float(h1[i]["high"]),
                     "low": float(h1[i]["low"]),
                     "prev_close": float(h1[i - 1]["close"]),
                     "time": int(h1[i]["time"])})

    days_rows = []
    for r in d1:
        ts = dt.datetime.fromtimestamp(int(r["time"]), dt.timezone.utc)
        # "time" is carried so callers can detect STALE history: a terminal that
        # has never downloaded a symbol's recent bars returns old data happily,
        # and an ATR computed from 2024 would silently mis-rank the instrument.
        days_rows.append({"open": float(r["open"]), "close": float(r["close"]),
                          "weekday": ts.strftime("%a"), "time": int(r["time"])})

    # Hourly spread: sample ticks across the last few days rather than trusting a
    # single spot reading, then aggregate per hour.
    samples = []
    now = dt.datetime.now(dt.timezone.utc)
    horizon = 14 if tick_days is None else max(0, tick_days)
    for back in range(1, min(days, horizon) + 1):
        frm = now - dt.timedelta(days=back)
        ticks = mt5.copy_ticks_range(symbol, frm, frm + dt.timedelta(days=1),
                                     mt5.COPY_TICKS_ALL)
        if ticks is None:
            continue
        for t in ticks:
            bid, ask = float(t["bid"]), float(t["ask"])
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            ts = dt.datetime.fromtimestamp(int(t["time"]), dt.timezone.utc)
            samples.append({"hour": ts.hour, "mid": (bid + ask) / 2.0,
                            "spread": ask - bid})

    mt5.shutdown()
    return bars, samples, days_rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NACUSD.c")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--window-hours", type=int, default=6)
    ap.add_argument("--terminal", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    bars, samples, days = collect(a.symbol, a.days, a.terminal)
    atr = atr_by_hour(bars)
    sp = spread_bps_by_hour(samples)
    q = quality_by_hour(atr, sp)
    window, score = best_window(q, a.window_hours)
    gaps = gap_stats(days)

    print(f"== {a.symbol} — {len(bars)} H1 bars, {len(samples)} tick samples, "
          f"{len(days)} days ==")
    print(render(atr, sp, q, window, score, gaps))

    if a.out:
        p = Path(a.out)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "symbol": a.symbol, "atr_by_hour": atr,
            "spread_bps_by_hour": sp, "quality_by_hour": q,
            "best_window_utc": list(window), "best_window_score": score,
            "gap_stats": gaps,
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
