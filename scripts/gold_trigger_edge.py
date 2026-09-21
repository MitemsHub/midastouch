#!/usr/bin/env python3
"""Does the entry trigger have a conditional edge anywhere? (venue bars, decidable or not)

THE QUESTION THIS ANSWERS. The governed walk-forward and the 168-geometry sweep both came
back at +0.03R/trade — which is not "the strategy is bad at these settings", it is "the
average trade is indistinguishable from zero at any sample this decade can produce". An
average over a heterogeneous population can hide a real conditional edge, and this program
has never measured one: every result so far (V75's +0.027R, the venue window's +0.068R, the
168-sweep's +0.0816R) is an average over ALL hours, ALL regimes and ALL volatility states.

So this slices the trigger's own entries and reports, per cell, the mean net R, its t, and
**the sample the cell would need for t >= 1.5**. That last column is the point of the whole
exercise: a cell can look spectacular and still be undecidable, and a cell that is
undecidable cannot be traded no matter how good the number beside it is.

WHAT IS MEASURED, and what is deliberately not.

  * `net_r` per trade is the strategy's own realised result — trigger, exit rule, spread
    and commission all included, from the frozen engine (`gold_walkforward.simulate`).
  * The cells are CONTEXT read at the entry bar, never at the exit: hour of entry (UTC),
    the H1/H4 regime class, the day of week, the H1 ATR tercile, and the alignment between
    the H1 and H4 trend legs.
  * The trigger's own **forward drift** is measured separately, in ATR units, over 8 and
    16 M15 bars from every signal bar. That is the part that does not depend on the exit
    rule: if the raw post-signal drift is zero, no exit geometry can manufacture an edge
    out of it, and if it is positive the exits are leaving money behind.

WHAT IT CANNOT BE. Every cell here is found on the same window the gate is judged on, so a
cell with a large mean is a **hypothesis**, and the report says so on every line: the
required sample is what a pre-registered test of that cell would need, and the cells with
the most trades are the ones with the least selection. Nothing here is a pass.
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

import gold_governed_wfo as gg  # noqa: E402  (venue data, governor, power arithmetic)
import gold_walkforward as gw  # noqa: E402

#: The widest session the venue trades, so the cells are not pre-filtered by one window.
OPEN_CFG = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 3.0,
            "win_lo": 0, "win_hi": 24}
#: Exit geometries: if a conditional edge only appears at one target multiple it is an
#: exit artefact, so every cell is reported for all of them and the report keeps the one
#: that survives across the row.
EXITS = ((1.0, 1.5), (1.0, 2.0), (1.0, 3.0), (1.5, 2.0), (1.5, 3.0))

HOUR_BUCKETS = ((0, 6, "00-06 (Asia)"), (6, 12, "06-12 (London)"),
                (12, 17, "12-17 (NY)"), (17, 22, "17-22 (late)"))
FORWARD_HORIZONS = (8, 16)


def regime_class(i: int, ok: dict) -> str:
    """The trend context at the entry bar, as one readable class."""
    h1l, h1s = bool(ok["h1_long"][i]), bool(ok["h1_short"][i])
    h4l, h4s = bool(ok["h4_long"][i]), bool(ok["h4_short"][i])
    if h1l and h4l:
        return "aligned UP"
    if h1s and h4s:
        return "aligned DOWN"
    if h4l or h4s:
        return "H4 trend, H1 against"
    return "H1 trend, H4 against"


def cell_stats(rs: list[float], t_target: float = 1.5) -> dict:
    n = len(rs)
    if n == 0:
        return {"n": 0, "mean_r": None, "t": None, "needed": None}
    mean = sum(rs) / n
    var = sum((x - mean) ** 2 for x in rs) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "mean_r": round(mean, 4), "sd": round(sd, 4), "t": round(t, 2),
            "needed": gg.power_trades(mean, sd, t_target)}


def group_by(trades: list[dict], key_fn) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for t in trades:
        out.setdefault(key_fn(t), []).append(t)
    return out


def report_cells(title: str, groups: dict[str, list[dict]], *, min_n: int = 20) -> list[dict]:
    rows = []
    print(f"\n  -- {title} --")
    print(f"    {'cell':<22} {'n':>5} {'meanR':>9} {'sd':>6} {'t':>6} {'needs (t>=1.5)':>14}")
    for name in sorted(groups, key=lambda k: -len(groups[k])):
        st = cell_stats([t["net_r"] for t in groups[name]])
        rows.append({"cell": name, **st})
        flag = "  <-- decidable now" if (st["needed"] or 10**9) <= st["n"] else ""
        if st["n"] < min_n:
            continue
        print(f"    {name:<22} {st['n']:>5} {st['mean_r']:>+9.4f} "
              f"{(st['sd'] or 0):>6.2f} {st['t']:>+6.2f} "
              f"{(st['needed'] if st['needed'] is not None else '-'):>14}{flag}")
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_trigger_edge.json")
    a = ap.parse_args(argv)

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    first = datetime.fromtimestamp(epoch[0], timezone.utc)
    last = datetime.fromtimestamp(epoch[-1], timezone.utc)
    print(f"{a.symbol} {gw.EXEC_TF} {n} bars {first:%Y-%m-%d} .. {last:%Y-%m-%d} "
          f"(venue's served window)")

    # ---- the trigger's entries, at every exit geometry -------------------- #
    all_trades: list[dict] = []
    per_exit: dict[str, list[dict]] = {}
    for (sm, tp) in EXITS:
        cfg = dict(OPEN_CFG, stop_mult=sm, tp_mult=tp)
        trades = gg.run_grid(B, hours, ok, atr, cfg, n)
        per_exit[f"stop{sm} tp{tp}"] = trades
        for t in trades:
            t["_geom"] = f"stop{sm} tp{tp}"
        all_trades.extend(trades)

    overall = cell_stats([t["net_r"] for t in all_trades])
    print(f"\nALL entries (session 0-24, all {len(EXITS)} exit geometries): "
          f"n={overall['n']} mean={overall['mean_r']:+.4f}R sd={overall['sd']:.2f} "
          f"t={overall['t']} -> needs {overall['needed']} trades for t>=1.5")

    # ---- context at the entry bar ----------------------------------------- #
    atr_pct = gw.trailing_percentile(atr, gw.ATR_LOOKBACK, 0.5)
    for t in all_trades:
        i = t["entry_i"]
        t["_hour"] = datetime.fromtimestamp(float(epoch[i]), timezone.utc).hour
        t["_weekday"] = datetime.fromtimestamp(float(epoch[i]), timezone.utc).strftime("%a")
        t["_regime"] = regime_class(i, ok)
        ratio = float(atr[i]) / float(atr_pct[i]) if float(atr_pct[i]) > 0 else 1.0
        t["_vol"] = "low (<0.8x med)" if ratio < 0.8 else (
            "high (>1.3x med)" if ratio > 1.3 else "normal")
        t["_bias"] = "long" if t["dir"] > 0 else "short"

    def bucket(t: dict) -> str:
        for lo, hi, name in HOUR_BUCKETS:
            if lo <= t["_hour"] < hi:
                return name
        return "22-24 (off)"

    sections: dict[str, list[dict]] = {}
    sections["hour (UTC)"] = report_cells("hour of entry (UTC)", group_by(all_trades, bucket))
    sections["regime"] = report_cells("H1/H4 regime class", group_by(all_trades, lambda t: t["_regime"]))
    sections["weekday"] = report_cells("weekday", group_by(all_trades, lambda t: t["_weekday"]))
    sections["volatility"] = report_cells("H1 ATR vs median", group_by(all_trades, lambda t: t["_vol"]))
    sections["bias"] = report_cells("direction", group_by(all_trades, lambda t: t["_bias"]))
    sections["regime x hour"] = report_cells(
        "regime x hour (the two-way split)",
        group_by(all_trades, lambda t: f"{t['_regime']} | {bucket(t)}"), min_n=15)

    # ---- does it hold at every exit geometry, or is it one target? -------- #
    print("\n  -- the best hour/regime cell at EACH exit geometry (the artefact test) --")
    print(f"    {'geometry':<14} {'cell':<30} {'n':>5} {'meanR':>9} {'t':>6}")
    by_geom: dict[str, list[dict]] = {}
    for gname, trades in per_exit.items():
        cells = group_by(trades, lambda t: f"{t['_regime']} | {bucket(t)}")
        best = max(cells, key=lambda k: (cell_stats([x['net_r'] for x in cells[k]])["mean_r"]
                                         or -9))
        st = cell_stats([x["net_r"] for x in cells[best]])
        by_geom[gname] = [{"cell": best, **st}]
        print(f"    {gname:<14} {best:<30} {st['n']:>5} {st['mean_r']:>+9.4f} {st['t']:>+6.2f}")

    # ---- the trigger's raw forward drift, in ATR units -------------------- #
    print(f"\n  -- forward drift after every signal bar (no exit rule attached) --")
    closes = B["close"]
    print(f"    {'horizon':>8} {'n':>6} {'mean ATR':>10} {'t':>7}")
    drift = []
    for h in FORWARD_HORIZONS:
        moves = []
        for t in all_trades:  # one observation per signal bar's trade, at that entry
            i = t["entry_i"]
            j = min(i + h, n - 1)
            if j <= i or atr[i] <= 0:
                continue
            moves.append(t["dir"] * (closes[j] - closes[i]) / float(atr[i]))
        mean = sum(moves) / len(moves)
        var = sum((x - mean) ** 2 for x in moves) / (len(moves) - 1)
        sd = math.sqrt(var)
        tstat = mean / (sd / math.sqrt(len(moves))) if sd > 0 else 0.0
        drift.append({"horizon_bars": h, "n": len(moves), "mean_atr": round(mean, 4),
                      "t": round(tstat, 2)})
        print(f"    {h:>6} bars {len(moves):>6} {mean:>10.4f} {tstat:>7.2f}")

    best_cells = sorted(
        [r for rows in sections.values() for r in rows if r["n"] >= 20],
        key=lambda r: -(r["mean_r"] or -9))[:5]
    decidable = [r for rows in sections.values() for r in rows
                 if r["needed"] is not None and r["needed"] <= r["n"] and r["mean_r"] > 0]
    print("\n  -- summary --")
    print(f"    cells with >= 20 trades: "
          f"{sum(1 for rows in sections.values() for r in rows if r['n'] >= 20)}")
    print(f"    cells that are decidable on this window (needed <= n, mean > 0): "
          f"{len(decidable)}")
    for r in best_cells:
        print(f"    best: {r['cell']:<34} n={r['n']} mean={r['mean_r']:+.4f} "
              f"t={r['t']} needs {r['needed']}")

    out = {"spec": {"symbol": a.symbol, "bars": n,
                    "window": [first.isoformat(), last.isoformat()],
                    "open_config": {k: str(v) for k, v in OPEN_CFG.items()},
                    "exit_geometries": [f"stop{s} tp{p}" for s, p in EXITS],
                    "note": "exploration on the gate's own window — a hypothesis, never a pass"},
           "overall": overall, "per_exit_best_cell": by_geom,
           "sections": sections, "forward_drift": drift,
           "decidable_cells": decidable, "best_cells": best_cells}
    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nartifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
