#!/usr/bin/env python3
"""P6 — consistent-daily-income study (register §2b row P6, 2026-09-18).

Operator directive: the live arm should trade as actively as the market
honestly allows, prioritizing CONSISTENT small daily profit ("$0.45 × 66
trades = $30/day") with compounding doing the scaling. This study measures
the two axes that drive fill density and daily smoothness which the
2026-09-16/09-18 sweeps never touched:

  * entry timeframe:  M5 vs the certified M15
  * TP shape:         1.0 / 1.5 / 1.8 / 2.0 × stop distance
  * BB k-grid:        1.0 / 1.5 / 2.0 (RSI bands stay 70/30 frozen)

 scored on DAILY CONSISTENCY, per the operator's framing:

  * pos_days   = % of trading days with net pnl > 0
  * med_day    = median daily profit ($) on the $5,000 study book
    (scaled to any account: pnl ∝ risk fraction × equity)
  * tot_r / pf / n stay in the record as the certified-quality cross-check

PRE-REGISTERED RANKING (fixed BEFORE results were seen — no peeking):
  winner = the highest full-span config by (pos_days, med_day) among configs
  whose quality gates hold: n >= 60 trades over the window AND pf >= 1.15
  AND tot_r > 0. A config failing the quality gates is INELIGIBLE regardless
  of daily smoothness — consistency without edge is a savings account with
  fees. Ties break toward the higher timeframe (cheaper, closer to the
  certified engine).

OOS LAW (added before any OOS number was seen): the M5 corpus's Jan–Mar
segment is in-sample; every M5 row must ALSO qualify on the Apr→Sep OOS
segment alone (same gates). The full-span ranking is the selection basis
(and therefore optimistic); the OOS leg is the honest verdict. If the
full-span winner fails OOS, selection walks down the ranking; if none
survive, P6 concludes NO-SHIP and nothing is amended.

CORPORA (both, per the register's two-corpus law):
  * certified corpus  data/forex/xauusd/XAUUSDmicro_M15.csv (2024-04 → 2026-09)
  * M5 broker fetch   data/forex/xauusd/XAUUSDmicro_M5.csv  (2026-01 → live;
    terminal depth ceiling 50k bars — provenance in midas_p6_m5_fetch.json)
  * live-window M15   data/live/XAUUSD_M15.csv

Engine: the certified primitives (ema, sma_atr, rsi_wilder, bb_touch,
macro_state, _manage) with a parameterized timeframe and TP multiple. The
M15 path is byte-compatible with the certified sweep (tp_mult=2.0 must
reproduce its baseline within tolerance); the M5 path reuses the exact same
management across 5-minute bars — TIMEOUT_BARS is wall-clock seconds in
_manage, so 12h holds on both timeframes.

NOT a certified engine; output is a research artifact + ranked table.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from bisect import bisect_right
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_sweep as ms  # certified primitives

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "artifacts")

CERT_M15 = os.path.join(REPO, "data", "forex", "xauusd", "XAUUSDmicro_M15.csv")
CERT_H1 = os.path.join(REPO, "data", "forex", "xauusd", "XAUUSDmicro_H1.csv")
M5_CSV = os.path.join(REPO, "data", "forex", "xauusd", "XAUUSDmicro_M5.csv")
LIVE_M15 = os.path.join(REPO, "data", "live", "XAUUSD_M15.csv")
LIVE_H1 = os.path.join(REPO, "data", "live", "XAUUSD_H1.csv")

TPS = [1.0, 1.5, 1.8, 2.0]
KS = [1.0, 1.5, 2.0]

# M5 window split: in-sample calibration (Jan→Mar) vs OOS verdict (Apr→Sep).
M5_IS_END = "2026-04-01T00:00"


def utc_date(ct: int) -> str:
    return datetime.fromtimestamp(ct, tz=timezone.utc).strftime("%Y-%m-%d")


def build_data(h1_csv: str, entry_csv: str, tf_seconds: int) -> dict:
    h1 = ms.load_bars(h1_csv)
    ent = ms.load_bars(entry_csv)
    h4 = ms.h4_series(h1)
    closes = [b["close"] for b in ent]
    return {
        "h1": h1, "ent": ent, "tf": tf_seconds,
        "h1_ct": [b["time"] + 3600 for b in h1],
        "h4_ct": [b["time"] + 14400 for b in h4],
        "h4": h4,
        "h1_ema": ms.ema([b["close"] for b in h1], 20),
        "h1_atr": ms.sma_atr(h1),
        "h4_ema": ms.ema([b["close"] for b in h4], 20),
        "close": closes,
        "rsi": ms.rsi_wilder(closes),
        "bb": {},
    }


def run_p6(data: dict, k: float, tp_mult: float, t0: int, t1: int) -> list[dict]:
    """Certified signal/management bookkeeping, re-indexed to the entry TF.

    Identical to the certified sweep's ORIGINAL mode: trigger = BB touch or
    RSI band poke; take = trigger == macro tide; session 06–20 UTC; SL =
    2×H1 ATR; fill = open ± half-spread; min-lot risk veto; _manage handles
    SL-first exits, half-spread exit cost, and the 12h wall-clock timeout.
    tp_mult replaces the frozen TP_MULT=2.0 constant.
    """
    ent, h1, h1_ema, h1_atr = data["ent"], data["h1"], data["h1_ema"], data["h1_atr"]
    h4, h4_ema = data["h4"], data["h4_ema"]
    tf = data["tf"]
    closes, rsi = data["close"], data["rsi"]
    bb = data["bb"][k]
    trades: list[dict] = []
    res = _Res(trades)
    pos = None
    pending = None
    equity = ms.START_EQUITY
    for i, b in enumerate(ent):
        ct = b["time"] + tf
        in_window = ct > t0 and b["time"] <= t1
        if pending is not None and pos is None and in_window and b["time"] == pending["sig_ct"]:
            side = 1 if pending["direction"] > 0 else -1
            sp_open = max(b["spread"], ms.SPREAD_FLOOR)
            fill = b["open"] + side * sp_open / 2
            stop_d = pending["stop_d"]
            risk_d = stop_d * ms.TICK_VALUE_PER_LOT * ms.MIN_LOT
            if risk_d > equity * ms.MAX_RISK_FRACTION:
                pending = None
                continue
            pos = {"side": side, "entry": fill, "sl": fill - side * stop_d,
                   "tp": fill + side * stop_d * tp_mult, "open_ct": b["time"],
                   "lots": ms.MIN_LOT, "risk_d": risk_d, "sp": sp_open,
                   "closed": False, "mfe": 0.0, "mae": 0.0,
                   "hour": pending["hour"], "mac": pending["mac"], "mode": "ORIGINAL"}
            pending = None
        if pos:
            pending = None
            ms._manage(pos, b, res, equity)
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
        mac = ms.macro_state(h1[k1 - 1]["close"], h1_ema[k1 - 1],
                             h4[k4 - 1]["close"], h4_ema[k4 - 1])
        t_bb = bb[i]
        t_rsi = rsi[i]
        trigger = 0
        if t_bb != 0:
            trigger = t_bb
        elif t_rsi >= 70:
            trigger = -1
        elif t_rsi <= 30:
            trigger = 1
        if trigger == 0 or mac != trigger:
            continue
        hr = datetime.fromtimestamp(b["time"], tz=timezone.utc).hour
        if not (6 <= hr < 20):
            continue
        pending = {"direction": trigger, "stop_d": ms.SL_ATR_MULT * atr,
                   "hour": hr, "mac": mac, "sig_ct": ct}
    return trades


class _Res:
    """Minimal RunResult shim for certified _manage."""
    def __init__(self, trades: list):
        self.trades = trades
        self.final_equity = ms.START_EQUITY
        self.vetoed = 0


def daily_metrics(trades: list[dict]) -> dict:
    """The operator's scoreboard: per-UTC-day PnL on the $50 virtual book."""
    if not trades:
        return {"n": 0}
    by_day: dict[str, float] = {}
    for t in trades:
        d = utc_date(t["close_ct"])
        by_day[d] = by_day.get(d, 0.0) + t["pnl"]
    days = sorted(by_day)
    vals = [by_day[d] for d in days]
    pos_days = sum(1 for v in vals if v > 0)
    return {
        "n": len(trades),
        "days_traded": len(days),
        "pos_days_pct": round(100.0 * pos_days / len(vals), 1),
        "med_day": round(statistics.median(vals), 2),
        "mean_day": round(statistics.fmean(vals), 2),
        "worst_day": round(min(vals), 2),
        "best_day": round(max(vals), 2),
    }


def qualify(m: dict, total_r: float, pf) -> tuple[bool, list[str]]:
    """Pre-registered quality gates — consistency without edge is void."""
    why: list[str] = []
    if m.get("n", 0) < 60:
        why.append(f"n={m.get('n', 0)} < 60")
    if pf is None or pf < 1.15:
        why.append(f"pf={pf} < 1.15")
    if not total_r > 0:
        why.append("net_r not positive")
    return (not why), why


def main() -> int:
    corpora = []
    if os.path.exists(CERT_M15):
        corpora.append(("cert-m15", CERT_H1, CERT_M15, 900))
    if os.path.exists(M5_CSV):
        corpora.append(("m5", CERT_H1, M5_CSV, 300))
    if os.path.exists(LIVE_M15):
        corpora.append(("live-m15", LIVE_H1, LIVE_M15, 900))

    results = []
    for name, h1_csv, ent_csv, tf in corpora:
        data = build_data(h1_csv, ent_csv, tf)
        ent_t = data["ent"]
        t0 = ent_t[0]["time"]
        t1 = ent_t[-1]["time"] + tf
        span_days = (t1 - t0) / 86400
        for k in KS:
            arr = [0] * len(data["close"])
            for i in range(len(arr)):
                arr[i] = ms.bb_touch(data["close"], i, 20, k)
            data["bb"][k] = arr
        for tp in TPS:
            for k in KS:
                tr = run_p6(data, k, tp, t0, t1)
                m = ms.metrics(tr)
                dm = daily_metrics(tr)
                ok, why = qualify(dm, m.get("net_r", 0), m.get("pf"))
                results.append({
                    "corpus": name, "tf_min": tf // 60, "k": k, "tp_r": tp,
                    "span_days": round(span_days, 1),
                    "n": dm.get("n", 0),
                    "per_day": round(dm.get("n", 0) / max(span_days, 1), 2),
                    "tot_r": m.get("net_r", 0), "pf": m.get("pf"),
                    "exp_r": m.get("expectancy_r", 0),
                    "pos_days_pct": dm.get("pos_days_pct", 0),
                    "med_day": dm.get("med_day", 0),
                    "worst_day": dm.get("worst_day", 0),
                    "eligible": ok, "gate_why": why,
                })

    results.sort(key=lambda r: (r["eligible"], r["pos_days_pct"], r["med_day"]),
                 reverse=True)
    winners = [r for r in results if r["eligible"]]

    # OOS adjudication for the M5 corpus (Jan–Mar is in-sample; the same
    # 12 M5 configs are re-run on Apr→Sep alone under identical gates).
    oos_rows: list[dict] = []
    if os.path.exists(M5_CSV):
        d5 = build_data(CERT_H1, M5_CSV, 300)
        t0_oos = int(datetime.fromisoformat(M5_IS_END + "+00:00").timestamp())
        t1_oos = d5["ent"][-1]["time"] + 300
        span_oos = round((t1_oos - t0_oos) / 86400, 1)
        for k in KS:
            arr = [0] * len(d5["close"])
            for i in range(len(arr)):
                arr[i] = ms.bb_touch(d5["close"], i, 20, k)
            d5["bb"][k] = arr
        for tp in TPS:
            for k in KS:
                tr = run_p6(d5, k, tp, t0_oos, t1_oos)
                m = ms.metrics(tr)
                dm = daily_metrics(tr)
                ok, why = qualify(dm, m.get("net_r", 0), m.get("pf"))
                oos_rows.append({
                    "k": k, "tp_r": tp, "span_days": span_oos,
                    "n": dm.get("n", 0),
                    "per_day": round(dm.get("n", 0) / max(span_oos, 1), 2),
                    "tot_r": m.get("net_r", 0), "pf": m.get("pf"),
                    "exp_r": m.get("expectancy_r", 0),
                    "pos_days_pct": dm.get("pos_days_pct", 0),
                    "med_day": dm.get("med_day", 0),
                    "worst_day": dm.get("worst_day", 0),
                    "eligible": ok, "gate_why": why,
                })
    oos_by_cfg = {(r["k"], r["tp_r"]): r for r in oos_rows}

    def oos_clean(r: dict) -> bool:
        if r["corpus"] != "m5":
            return True  # M15 corpora carry the certified sweep's own OOS evidence
        o = oos_by_cfg.get((r["k"], r["tp_r"]))
        return bool(o and o["eligible"])

    winner = next((r for r in winners if oos_clean(r)), None)

    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol": "P6 consistent-daily-income study (register §2b, 2026-09-18)",
        "ranking_pre_registered": "max (pos_days_pct, med_day) subject to n>=60, pf>=1.15, net_r>0; ties → higher TF",
        "m5_provenance": "data/forex/xauusd/XAUUSDmicro_M5.csv via terminal API (midas_p6_m5_fetch.json)",
        "winner": winner,
        "m5_oos": oos_rows,
        "results": results,
    }
    path = os.path.join(ART, "midas_p6_income_study_20260918.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)

    print(f"artifact {path} | configs: {len(results)} | eligible: {len(winners)}")
    print(f"{'corpus':<10}{'tf':>4}{'k':>5}{'tp':>5}{'n':>6}{'/day':>6}"
          f"{'posD%':>7}{'medD$':>7}{'worD$':>7}{'totR':>8}{'pf':>7}  ok")
    for r in results:
        print(f"{r['corpus']:<10}{r['tf_min']:>4}{r['k']:>5}{r['tp_r']:>5}"
              f"{r['n']:>6}{r['per_day']:>6}{r['pos_days_pct']:>7}"
              f"{r['med_day']:>7}{r['worst_day']:>7}{r['tot_r']:>8}"
              f"{str(r['pf']):>7}  {'YES' if r['eligible'] else 'no ' + '; '.join(r['gate_why'])}")
    if oos_rows:
        print("\n--- M5 OOS adjudication (Apr-Sep alone, same gates) ---")
        for r in sorted(oos_rows, key=lambda x: (x["eligible"], x["pos_days_pct"]), reverse=True):
            print(f"k={r['k']:<4} tp={r['tp_r']:<4} n={r['n']:>4} {'/day':<5}{r['per_day']:>5}"
                  f"  posD%={r['pos_days_pct']:>5}  medD$={r['med_day']:>7}"
                  f"  totR={r['tot_r']:>7}  pf={r['pf']}  "
                  f"{'PASS' if r['eligible'] else 'FAIL: ' + '; '.join(r['gate_why'])}")
    if winner:
        print(f"\nWINNER (pre-registered ranking + OOS law): {winner['corpus']} "
              f"k={winner['k']} tp={winner['tp_r']}R -- "
              f"{winner['pos_days_pct']}% positive days, median ${winner['med_day']}/day "
              f"(on $5,000 book), pf {winner['pf']}, {winner['n']} trades")
    else:
        print("\nNO-SHIP: no config survived the pre-registered gates + OOS law.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
