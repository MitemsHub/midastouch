#!/usr/bin/env python3
"""Frequency × quality sweep for the MIDAS mode registry (research artifact).

Extends scripts/midas_sweep.py's certified engine with two parameter axes:
  * BB k-multiple   (the P5 adaptive axis, register §2b)
  * RSI band pair   (70/30 frozen baseline vs wider/narrower)

NOT a certified engine: it reuses the certified primitives (ema, sma_atr,
rsi_wilder, bb_touch, h4_series, macro_state, run_mode's exact bookkeeping)
but takes the axes as parameters. Output: artifacts JSON + a ranked table.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_sweep as ms  # certified primitives

DATA_DIR = os.path.join("data", "live")
ART = "artifacts"
MODES = ms.MODES
BB_KS = [1.0, 1.5, 2.0, 2.5, 3.0]
RSI_BANDS = [(70, 30), (75, 25), (80, 20), (65, 35)]


def build_data() -> dict:
    h1 = ms.load_bars(os.path.join(DATA_DIR, "XAUUSD_H1.csv"))
    m15 = ms.load_bars(os.path.join(DATA_DIR, "XAUUSD_M15.csv"))
    h4 = ms.h4_series(h1)
    return {
        "h1": h1, "m15": m15, "h4": h4,
        "h1_ct": [b["time"] + 3600 for b in h1],
        "h4_ct": [b["time"] + 14400 for b in h4],
        "h1_ema": ms.ema([b["close"] for b in h1], 20),
        "h1_atr": ms.sma_atr(h1),
        "h4_ema": ms.ema([b["close"] for b in h4], 20),
        "m15_close": [b["close"] for b in m15],
        "m15_rsi": ms.rsi_wilder([b["close"] for b in m15]),
        "m15_bb": {},   # k -> list
    }


def run_config(data: dict, mode: str, bb: list[int], rsi_hi: int, rsi_lo: int,
               t0: int, t1: int, atr_lo: float | None = None,
               atr_hi: float | None = None) -> list[dict]:
    """run_mode with parameterized bb array + RSI bands (identical bookkeeping).

    atr_lo/atr_hi (optional, research-only): skip signals whose H1 ATR is
    below/above the bound (absolute price units). None disables the bound —
    the default keeps the function byte-compatible with the 2026-09-18 sweep.
    """
    h1, m15, h4 = data["h1"], data["m15"], data["h4"]
    h1_ema, h1_atr, h4_ema = data["h1_ema"], data["h1_atr"], data["h4_ema"]
    m15_rsi = data["m15_rsi"]
    trades: list[dict] = []
    pos = None
    pending = None
    equity = ms.START_EQUITY
    from bisect import bisect_right
    for i, b in enumerate(m15):
        ct = b["time"] + 900
        in_window = ct > t0 and b["time"] <= t1
        if pending is not None and pos is None and in_window and b["time"] == pending["sig_ct"]:
            side = 1 if pending["direction"] > 0 else -1
            sp_open = max(b["spread"], ms.SPREAD_FLOOR)
            fill = b["open"] + side * sp_open / 2
            stop_d = pending["stop_d"]
            risk_d = stop_d * ms.TICK_VALUE_PER_LOT * ms.MIN_LOT  # micro floor sizing
            if risk_d > equity * ms.MAX_RISK_FRACTION:
                pending = None
                continue
            pos = {"side": side, "entry": fill, "sl": fill - side * stop_d,
                   "tp": fill + side * stop_d * ms.TP_MULT, "open_ct": b["time"],
                   "lots": ms.MIN_LOT, "risk_d": risk_d, "sp": sp_open,
                   "closed": False, "mfe": 0.0, "mae": 0.0,
                   "hour": pending["hour"], "mac": pending["mac"], "mode": mode}
            pending = None
        if pos:
            pending = None
            ms._manage(pos, b, _Res(trades), equity)
            if pos.get("closed"):
                equity += trades[-1]["pnl"]
                pos = None
            continue
        if not in_window:
            pending = None
            continue
        k1 = bisect_right(data["h1_ct"], ct)
        k4 = bisect_right(data["h4_ct"], ct)
        if k1 < 21 or k4 < 21 or i < 21:
            continue
        atr = h1_atr[k1 - 1]
        if atr <= 0:
            continue
        if atr_lo is not None and atr < atr_lo:
            continue
        if atr_hi is not None and atr > atr_hi:
            continue
        mac = ms.macro_state(h1[k1 - 1]["close"], h1_ema[k1 - 1],
                             h4[k4 - 1]["close"], h4_ema[k4 - 1])
        t_bb = bb[i]
        t_rsi = m15_rsi[i]
        trigger = 0
        if t_bb != 0:
            trigger = t_bb
        elif t_rsi >= rsi_hi:
            trigger = -1
        elif t_rsi <= rsi_lo:
            trigger = 1
        if mode == "ORIGINAL":
            take, direction = trigger != 0 and mac == trigger, trigger
        elif mode == "REVERSE_DIRECTION":
            take, direction = trigger != 0 and mac == -trigger, -trigger
        elif mode == "REVERSE_TRIGGER":
            take, direction = trigger == 0 and mac != 0, mac
        elif mode == "REVERSE_BOTH":
            take, direction = trigger == 0 and mac != 0, -mac
        elif mode == "LONG_ONLY":
            take, direction = trigger == 1 and mac == 1, 1
        elif mode == "SHORT_ONLY":
            take, direction = trigger == -1 and mac == -1, -1
        elif mode == "MACRO_ONLY":
            take, direction = mac != 0, mac
        else:
            take, direction = trigger != 0, trigger
        if not take or direction == 0:
            continue
        hr = datetime.fromtimestamp(b["time"], tz=timezone.utc).hour
        if not (6 <= hr < 20):
            continue
        pending = {"direction": direction, "stop_d": ms.SL_ATR_MULT * atr,
                   "hour": hr, "mac": mac, "sig_ct": ct}
    return trades


class _Res:
    """Minimal RunResult shim so certified _manage can append trades."""
    def __init__(self, trades: list):
        self.trades = trades
        self.final_equity = ms.START_EQUITY
        self.vetoed = 0


def main() -> int:
    data = build_data()
    mc = data["m15_close"]
    t0 = mc.__len__() and data["m15"][0]["time"]
    t1 = data["m15"][-1]["time"] + 900
    for k in BB_KS:
        arr = [0] * len(mc)
        for i in range(len(mc)):
            arr[i] = ms.bb_touch(mc, i, 20, k)
        data["m15_bb"][k] = arr

    span_days = (t1 - t0) / 86400
    rows = []
    for k in BB_KS:
        for rhi, rlo in RSI_BANDS:
            for mode in MODES:
                tr = run_config(data, mode, data["m15_bb"][k], rhi, rlo, t0, t1)
                m = ms.metrics(tr)
                rows.append({"k": k, "rsi": f"{rhi}/{rlo}", "mode": mode,
                             "n": m.get("n", 0),
                             "per_month": round(m.get("n", 0) / (span_days / 30.4), 2),
                             "net_r": m.get("net_r", 0),
                             "exp": m.get("expectancy_r", 0),
                             "pf": m.get("pf"),
                             "win": m.get("win_rate", 0),
                             "dd": m.get("max_dd_r", 0)})
    rows.sort(key=lambda r: (r["n"] > 0, r["exp"], r["n"]), reverse=True)
    out = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "span_days": round(span_days, 1), "rows": rows}
    os.makedirs(ART, exist_ok=True)
    path = os.path.join(ART, "midas_variant_research_20260918.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"span {span_days:.0f} days | configs: {len(rows)} | artifact {path}")
    print(f"{'mode':<18}{'k':>5}{'rsi':>7}{'n':>6}{'/mo':>7}{'netR':>9}{'exp':>8}{'pf':>7}{'win':>6}{'dd':>6}")
    for r in rows[:28]:
        print(f"{r['mode']:<18}{r['k']:>5}{r['rsi']:>7}{r['n']:>6}{r['per_month']:>7}"
              f"{r['net_r']:>9.2f}{r['exp']:>8.3f}{str(r['pf']):>7}{r['win']:>6.2f}{r['dd']:>6.1f}")
    print("\n--- baseline (frozen) ORIGINAL k=2.0 70/30 for reference ---")
    for r in rows:
        if r["mode"] == "ORIGINAL" and r["k"] == 2.0 and r["rsi"] == "70/30":
            print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
