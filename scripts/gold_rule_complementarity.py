#!/usr/bin/env python3
"""Are the two rules this repository contains complementary enough to trade together?

The program now holds two entry rules on the same instrument:

* **the EA's rule** — M15 BB(20,2.0) touch-back-inside or RSI(14) 70/30, H1/H4 EMA20 regime,
  8 modes, 06-20 UTC. This is what the live arm trades (`scripts/midas_sweep.py`, the parity
  engine of record).
* **the gate's family** — M15 EMA stack (8/21/50 or 12/26/100) with an H1 EMA stack and H4
  close-vs-EMA20 regime, plus an ATR percentile band (`scripts/gold_walkforward.py`). Every
  frozen certification in this repository is about this one.

They agree on the same bar and direction only 3.4% of the time, which raises a real question
rather than a rhetorical one: if the two populations barely overlap, do they diversify — a
portfolio of two nearly independent rules — or do they double the same drawdown?

WHAT IS MEASURED, all on the venue's own bars, both eras, same clock pins as the EA
walk-forward: trade counts and hourly shape; overlap (holding intervals intersect) and how
often an overlap is SAME-direction (double exposure) versus offsetting; the correlation of the
two daily R series; and one shared $750 daily-loss line applied to the COMBINED daily result.

SIZING CONVENTION (declared, because a portfolio claim in dollars needs one): both rules size
at the venue's minimum lot 0.01, so a trade's dollars-per-R is its own stop distance in dollars
(price × $100/lot/unit × 0.01). No risk-splitting model is invented: the study reports what one
shared daily line does to the combined series, and says so where that is the whole answer.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from calendar import timegm
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_walkforward as gw      # noqa: E402
import midas_parity as P           # noqa: E402
import midas_sweep as M            # noqa: E402

ARTIFACT = ROOT / "artifacts" / "gold_rule_complementarity.json"

ERAS = (("A", "2026-01-12", "2026-03-31", 60),
        ("B", "2026-04-01", "2026-09-18", 120))
BASIS_USD = 25000.0
RISK_FRACTION = 0.0025
MIN_LOT = 0.01
DOLLARS_PER_UNIT = 100.0        # measured on this venue (order_calc_profit)
DAILY_LINE_USD = 750.0          # 3% of the $25,000 evaluation
EA_CELL = {"mode": "ORIGINAL", "sl": 2.0, "tp": 2.0}


def iso_ts(date_str: str) -> int:
    return timegm(datetime.strptime(date_str, "%Y-%m-%d").timetuple())


def shift_bars(path: Path, offset_min: int) -> list[dict]:
    return [{**b, "time": b["time"] - offset_min * 60} for b in M.load_bars(str(path))]


def utc_hour(t: float) -> int:
    return datetime.fromtimestamp(t, timezone.utc).hour


def utc_day(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


# --- the EA's rule -----------------------------------------------------------


def ea_trades(era) -> list[dict]:
    _n, s_start, s_end, off = era
    t0, t1 = iso_ts(s_start) - off * 60, iso_ts(s_end) + 86400 - off * 60
    data = P.python_build_data(news=False, offset_min=off, corpus="venue")
    res = M.run_mode(EA_CELL["mode"], t0, t1, data, sl_atr_mult=EA_CELL["sl"],
                     tp_mult=EA_CELL["tp"], win_lo=6, win_hi=20,
                     risk_fraction=RISK_FRACTION)
    return [{"rule": "ea", "open_ct": t["open_ct"], "close_ct": t["close_ct"],
             "dir": t["side"], "r": t["r"], "usd_per_r": t["risk_d"]} for t in res.trades]


# --- the gate's family -------------------------------------------------------


def ema_family_grid_trades(era) -> tuple[list[list[dict]], list[dict]]:
    """Every configuration of the frozen EMA grid, on ONE era, with the same cost model."""
    _n, s_start, s_end, off = era
    t0, t1 = iso_ts(s_start) - off * 60, iso_ts(s_end) + 86400 - off * 60
    m15 = shift_bars(Path(M.DATA_DIR) / f"XAUUSD_M15{P.VENUE_M15_SUFFIX}.csv", off)
    h1 = shift_bars(Path(M.DATA_DIR) / f"XAUUSD_H1{P.VENUE_M15_SUFFIX}.csv", off)
    h4 = shift_bars(Path(M.DATA_DIR) / f"XAUUSD_H4{P.VENUE_M15_SUFFIX}.csv", off) \
        if (Path(M.DATA_DIR) / f"XAUUSD_H4{P.VENUE_M15_SUFFIX}.csv").is_file() \
        else M.h4_series(h1, offset_min=off)
    keep = [i for i, b in enumerate(m15) if t0 <= b["time"] <= t1]
    bars = {k: np.array([m15[i][k] for i in keep], dtype=float)
            for k in ("open", "high", "low", "close", "time")}
    bars["epoch"] = bars.pop("time")
    atr = gw.wilder_atr(bars["high"], bars["low"], bars["close"], gw.ATR_PERIOD)
    h1c = np.array([b["close"] for b in h1], dtype=float)
    h4c = np.array([b["close"] for b in h4], dtype=float)
    h1e, h4e = (np.array([b["time"] for b in h1], dtype=float),
                np.array([b["time"] for b in h4], dtype=float))
    ef, em, es = (gw.ema(h1c, k) for k in (8, 21, 50))
    h4ef = gw.ema(h4c, 20)
    ok = {k: np.zeros(len(bars["close"]), dtype=bool)
          for k in ("h1l", "h1s", "h4l", "h4s")}
    for i in range(len(bars["close"])):
        t = float(bars["epoch"][i])
        a = gw.last_closed_index(h1e, t, gw.H1_TF_SEC)
        if a >= 0:
            ok["h1l"][i] = ef[a] > em[a] > es[a]
            ok["h1s"][i] = ef[a] < em[a] < es[a]
        b = gw.last_closed_index(h4e, t, gw.H4_TF_SEC)
        if b >= 0:
            ok["h4l"][i] = h4c[b] > h4ef[b]
            ok["h4s"][i] = h4c[b] < h4ef[b]
    hours = np.array([utc_hour(x) for x in bars["epoch"]], dtype=int)
    out = []
    for cfg in gw.configs():
        tr = gw.simulate(bars, hours, ok["h1l"], ok["h1s"], ok["h4l"], ok["h4s"], atr, cfg,
                         start=gw.WARMUP_BARS, end=len(bars["close"]))
        rows = []
        for x in tr:
            i = int(x["entry_i"])
            risk_pts = cfg["stop_mult"] * float(atr[i])
            rows.append({"rule": "ema", "open_ct": float(bars["epoch"][i]),
                         "close_ct": float(bars["epoch"][int(x["exit_i"])]) + 900.0,
                         "dir": int(x["dir"]), "r": float(x["net_r"]),
                         "usd_per_r": risk_pts * DOLLARS_PER_UNIT * MIN_LOT})
        out.append(rows)
    return out, [cfg for cfg in gw.configs()]


# --- comparison --------------------------------------------------------------


def overlaps(a: list[dict], b: list[dict]) -> dict:
    """Pairs whose holding intervals intersect, and whether they double the same side."""
    same, opp, n = 0, 0, 0
    j0 = 0
    for x in sorted(a, key=lambda t: t["open_ct"]):
        for y in b:
            if y["close_ct"] < x["open_ct"] or y["open_ct"] > x["close_ct"]:
                continue
            n += 1
            if y["dir"] == x["dir"]:
                same += 1
            else:
                opp += 1
    return {"overlapping_pairs": n, "same_direction": same, "offsetting": opp,
            "share_same_direction": round(same / n, 3) if n else None, "px": j0}


def daily(rows: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in rows:
        d = utc_day(t["open_ct"])
        out[d] = out.get(d, 0.0) + t["r"]
    return out


def daily_usd(rows: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in rows:
        d = utc_day(t["open_ct"])
        out[d] = out.get(d, 0.0) + t["r"] * t["usd_per_r"]
    return out


def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def budget(usd: dict[str, float], line: float) -> dict:
    days = sorted(usd)
    worst = min((usd[d] for d in days), default=0.0)
    past = [d for d in days if usd[d] < -line]
    return {"days": len(days), "total_usd": round(sum(usd.values()), 2),
            "worst_day_usd": round(worst, 2),
            "worst_day_pct_of_line": round(worst / -line * 100.0, 1),
            "days_past_the_line": len(past),
            "line_usd": line}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    M.use_basis(BASIS_USD)
    ea: list[dict] = []
    grid_by_era: list[list[list[dict]]] = []
    cfgs: list[dict] = []
    for era in ERAS:
        ea.extend(ea_trades(era))
        tr, cfgs = ema_family_grid_trades(era)
        grid_by_era.append(tr)
    print(f"EA rule (armed cell, 06-20 UTC): {len(ea)} trades, "
          f"total {sum(t['r'] for t in ea):+.3f}R")

    # Compare against EVERY configuration of the frozen grid, so the answer cannot hinge on
    # one pick; the per-configuration numbers are reported as a range and a median.
    stats = []
    for ci, cfg in enumerate(cfgs):
        ema = [t for era_rows in grid_by_era for t in era_rows[ci]]
        ov = overlaps(ea, ema)
        ed, md = daily(ea), daily(ema)
        days = sorted(set(ed) | set(md))
        corr = pearson([ed.get(d, 0.0) for d in days], [md.get(d, 0.0) for d in days])
        both = [d for d in days if d in ed and d in md]
        corr_both = pearson([ed[d] for d in both], [md[d] for d in both]) if both else None
        eu, mu = daily_usd(ea), daily_usd(ema)
        combined = {d: eu.get(d, 0.0) + mu.get(d, 0.0) for d in set(eu) | set(mu)}
        stats.append({
            "cfg": {k: cfg[k] for k in ("emas", "stop_mult", "tp_mult", "win_lo", "win_hi")},
            "ema_trades": len(ema), "ema_total_r": round(sum(t["r"] for t in ema), 3),
            "ema_mean_r": round(sum(t["r"] for t in ema) / len(ema), 4) if ema else None,
            "overlap": ov, "corr_all_days": None if corr is None else round(corr, 3),
            "corr_days_both_traded": None if corr_both is None else round(corr_both, 3),
            "days_both_traded": len(both),
            "budget_ea_alone": budget(eu, DAILY_LINE_USD),
            "budget_ema_alone": budget(mu, DAILY_LINE_USD),
            "budget_combined": budget(combined, DAILY_LINE_USD),
        })

    best = max(stats, key=lambda s: s["ema_total_r"])
    shares = [s["overlap"]["share_same_direction"] for s in stats
              if s["overlap"]["share_same_direction"] is not None]
    corrs = [s["corr_days_both_traded"] for s in stats
             if s["corr_days_both_traded"] is not None]
    print(f"gate family (frozen {len(cfgs)}-config grid, same bars): trades "
          f"{min(s['ema_trades'] for s in stats)}-{max(s['ema_trades'] for s in stats)}, "
          f"corr(daily R on days both traded) median "
          f"{sorted(corrs)[len(corrs)//2] if corrs else None}, "
          f"same-direction share of overlaps median "
          f"{sorted(shares)[len(shares)//2] if shares else None}")
    print(f"\n{'cfg':<26} {'n_ema':>6} {'ov':>5} {'same%':>6} {'corr':>6} "
          f"{'ea worst':>9} {'ema worst':>10} {'both worst':>11} {'both past':>9}")
    for s in stats:
        c = s["cfg"]
        label = (f"{c['emas']} s{c['stop_mult']} t{c['tp_mult']} w{c['win_lo']}-{c['win_hi']}")
        print(f"{label:<26} {s['ema_trades']:>6} {s['overlap']['overlapping_pairs']:>5} "
              f"{(s['overlap']['share_same_direction'] or 0)*100:>5.1f}% "
              f"{(s['corr_days_both_traded'] or 0):>6.3f} "
              f"{s['budget_ea_alone']['worst_day_usd']:>9.2f} "
              f"{s['budget_ema_alone']['worst_day_usd']:>10.2f} "
              f"{s['budget_combined']['worst_day_usd']:>11.2f} "
              f"{s['budget_combined']['days_past_the_line']:>9}")
    print(f"\nEA alone: worst day {stats[0]['budget_ea_alone']['worst_day_usd']:.2f} USD, "
          f"{stats[0]['budget_ea_alone']['days_past_the_line']} days past the "
          f"${DAILY_LINE_USD:,.0f} line")
    print(f"best-by-total gate config alone: worst day "
          f"{best['budget_ema_alone']['worst_day_usd']:.2f} USD, "
          f"{best['budget_ema_alone']['days_past_the_line']} days past the line")
    print(f"combined (that config + the EA rule): worst day "
          f"{best['budget_combined']['worst_day_usd']:.2f} USD, "
          f"{best['budget_combined']['days_past_the_line']} days past the line")

    out = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "harness": "scripts/gold_rule_complementarity.py",
           "rules": {"ea": {**EA_CELL, "window": "06-20 UTC",
                            "engine": "scripts/midas_sweep.py:run_mode"},
                     "gate_family": {"grid": f"{len(cfgs)} configurations of "
                                              "scripts/gold_walkforward.py",
                                     "note": "compared across ALL of them, not one pick"}},
           "eras": [{"era": e[0], "server_window": [e[1], e[2]], "offset_min": e[3]}
                    for e in ERAS],
           "sizing_convention": {"min_lot": MIN_LOT, "dollars_per_unit": DOLLARS_PER_UNIT,
                                 "usd_per_r": "each trade's own stop distance in dollars",
                                 "daily_line_usd": DAILY_LINE_USD,
                                 "no_risk_split_modelled": True},
           "ea_trades": len(ea), "ea_total_r": round(sum(t["r"] for t in ea), 3),
           "per_config": stats,
           "day_r_correlation_median": (sorted(corrs)[len(corrs) // 2] if corrs else None),
           "same_direction_share_median": (sorted(shares)[len(shares) // 2] if shares else None)}
    if args.write:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(out, indent=1))
        print(f"\nartifact: {ARTIFACT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
