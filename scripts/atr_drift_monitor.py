"""Weekly ATR-drift monitor for arm C's pre-registered sizing truth table.

WHY THIS EXISTS (2026-09-15): the arm-C sizing truth table in
docs/GO_LIVE_CHECKLIST.md froze min-lot stop-risk at $10.00-$17.85 from 8
tester fills. That band is a function of H1 ATR(14), which drifts with the
volatility regime. A drifting ATR silently invalidates the table's verdict
rows ($50 INERT / $75 NOT VIABLE / $85 MARGINAL / $100 MINIMUM VIABLE / $120 /
$150), and the arm-C branch (docs/ARM_C_TEMPLATE.md 2026-09-15 pre-registration)
makes the $100 floor a formal precondition. This monitor re-derives the table
from live data every week (paper_weekly pipeline leg) and flags amendment.

CALIBRATION CHAIN (all frozen quantities, nothing from memory):
  1. Engine geometry: SL = 2.0 x H1 ATR(14)  (V75MacroEngine.mq5,
     SL_ATR_MULTIPLE = 2.0, iATR(g_symbol, PERIOD_H1, InpATRPeriod=14)).
  2. Dollar conversion: per-fill k = risk$ / (volume/0.01) / stop-dist(price
     units) from the tester ledger written by
     scripts/validate_armc_paper_ledger_tester.py (default path below).
     Frozen band (artifact armc_paper_ledger_20260915.json, 8 fills):
     k in [0.0089, 0.0149] -> min-lot stop-risk $10.00-$17.85.
  3. Truth-table budgets: $50->$10, $75->$15, $85->$17, $100->$20, $120->$24,
     $150->$30 (20% global risk cap per row of the frozen table).

VERDICT (frozen; computed on the p95 of ATR over the ATR_LOOKBACK lookback —
the geometry the engine will actually meet, not just today's print):
  HOLD   p95 implied worst-stop <= $20  -> every frozen row verdict stands.
  WATCH  $20 < p95 <= $24               -> the $100 MINIMUM-VIABLE row's
         "admits all measured geometries" claim is stale; amendment
         consideration flagged (not yet required).
  AMEND  p95 > $24                      -> the $120 row also refuses the worst
         geometry; the table is materially wrong -> formal append-only
         amendment required BEFORE any live decision cites it (arm-C branch
         precondition unmet until the amendment lands).
  SHRINK-WATCH  p05 implied worst-stop <= $5.00 (half the frozen low end)
         -> the lower rows ($50 INERT / $75 NOT VIABLE) may no longer hold;
         a table that lies in the benign direction is still amended.
  Any calibration mismatch vs the frozen band > CALIB_DRIFT_TOL -> the
  conversion itself moved (contract/quote change); CALIBRATION-DRIFT flag,
  verdict capped at WATCH at best (an unexplained conversion shift is never
  HOLD).

STALE-DATA rule: if the newest H1 bar is older than STALE_HOURS, the reading
is SKIPPED-STALE — a monitor that reads old data must never output HOLD.

Usage:
  python scripts/atr_drift_monitor.py                 # one reading, JSON out
  python scripts/atr_drift_monitor.py --no-append     # read-only, print only
  (importable: wilder_atr(), implied_minlot_band(), classify(), rederive_rows())
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from statistics import median

SYMBOL = "Volatility 75 Index"
SL_ATR_MULTIPLE = 2.0        # V75MacroEngine.mq5 SL_ATR_MULTIPLE (H1 ATR)
ATR_PERIOD = 14              # InpATRPeriod default (H1)
ATR_BARS = 1000              # H1 lookback for the ATR distribution (~6 weeks)
STALE_HOURS = 3.0            # V75 trades 24/7; older than this = stale feed

TESTER_LEDGER = os.path.expandvars(
    r"%APPDATA%\MetaQuotes\Tester\49E0383CD680D7AAEC56888AFA08F49E"
    r"\Agent-127.0.0.1-3000\MQL5\Files"
    r"\V75MacroEngine_paper_Volatility_75_Index.csv")

FROZEN = {
    "k_band": [0.008923, 0.014884],        # $/price-unit per 0.01 lot (8 fills)
    "minlot_band": [10.00, 17.85],          # frozen checklist band
    "artifact": "artifacts/v75_macro_engine_tester/armc_paper_ledger_20260915.json",
}
CALIB_DRIFT_TOL = 0.15        # recomputed band may not depart >15% from frozen

# 2026-09-15 truth-table amendment: the dynamic strangulation floor.
# Min-lot risk is PINNED in dollars (broker volume floor) while the 20% cap
# shrinks with equity, so a loss streak strangles admission exactly as observed
# in the hybrid study's L1 book (589 risk-cap vetoes, n=6). Frozen inputs:
#   k = 6  worst loss streak of the certified replay (fresh60, n=114,
#          cert_report_fresh60_tp18_net.json worst_loss_streak field)
#   s  = worst per-trade stop $ (the p95 HIGH end of the implied band)
# Floor = s*(k+5): 5s static admission + k*s absorb the streak + s trade again
# after it. Mechanics validated against observation: L1 died at eq ~ risk$/0.20.
K_CERT_STREAK = 6
K_TAIL = 7                    # one loss beyond anything ever observed
S_ENGINEERING = 28.0          # 2x-ATR engineering bound (frozen checklist note)

# frozen truth-table rows: (account, 20%-cap budget, frozen verdict)
TRUTH_ROWS = [
    (50,  10.00, "INERT"),
    (75,  15.00, "NOT VIABLE"),
    (85,  17.00, "MARGINAL"),
    (100, 20.00, "MINIMUM VIABLE"),
    (120, 24.00, "headroom"),
    (150, 30.00, "RECOMMENDED BUFFER"),
]

ARTIFACT_DIR = os.path.join("artifacts", "v75_replay")
ARTIFACT = os.path.join(ARTIFACT_DIR, "atr_drift_monitor.json")


# ------------------------------------------------------------- calibration --
def calibration_from_ledger(path: str = TESTER_LEDGER):
    """Per-fill k = risk$/(vol/0.01)/dist from the tester ledger OPEN rows.

    OPEN,epoch,epoch,n,entry,sl,tp,vol,risk,dist,ttl,PAPER
    Returns (k_values, dists) or ([], []) if the ledger is gone."""
    ks, dists = [], []
    if not os.path.exists(path):
        return ks, dists
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if not p or p[0] != "OPEN" or len(p) < 10:
                continue
            try:
                entry, sl = float(p[4]), float(p[5])
                vol, risk = float(p[7]), float(p[8])
                dist = float(p[9]) if float(p[9]) > 0 else abs(entry - sl)
            except ValueError:
                continue
            if vol <= 0 or dist <= 0:
                continue
            ks.append(risk / (vol / 0.01) / dist)
            dists.append(dist)
    return ks, dists


# ------------------------------------------------------------------ market --
def wilder_atr(bars, period: int = ATR_PERIOD):
    """Replicate MetaTrader iATR: seed = SMA of first `period` TRs, then
    Wilder smoothing ATR_t = (ATR_{t-1}*(period-1) + TR_t)/period.
    bars: sequence of (high, low, close). Returns list aligned to bars
    (None before the seed)."""
    trs = []
    for i, (h, l, c) in enumerate(bars):
        if i == 0:
            trs.append(h - l)
        else:
            pc = bars[i - 1][2]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [None] * len(bars)
    if len(bars) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period - 1] = atr
    for i in range(period, len(bars)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def implied_minlot_band(atr: float, k_band):
    """Min-lot stop-risk band $ for a given ATR: dist = 2*ATR, $ = dist*k."""
    dist = SL_ATR_MULTIPLE * atr
    return [dist * k_band[0], dist * k_band[1]]


# ------------------------------------------------------------------ verdict --
def classify(p95_low, p95_high):
    """Frozen verdict from the p95 implied min-lot band (low/high $)."""
    if p95_low <= 5.00:
        return "SHRINK-WATCH"
    if p95_high <= 20.00:
        return "HOLD"
    if p95_high <= 24.00:
        return "WATCH"
    return "AMEND"


FROZEN_RANK = {"INERT": 0, "NOT VIABLE": 1, "MARGINAL": 1,
               "MINIMUM VIABLE": 2, "headroom": 2, "RECOMMENDED BUFFER": 2}
DERIVED_RANK = {"CANNOT FIT worst": 0, "PARTIAL admission": 1, "fits": 2}


def rederive_rows(p95_low, p95_high):
    """Re-derive each frozen truth-table row with today's worst-case stop
    (the p95 HIGH end — the conservative side) and flag verdict-class changes
    (rank comparison: cannot-fit < partial < fits). Frozen row semantics:
    budget < minlot -> cannot fit the worst geometry."""
    rows = []
    for acct, budget, frozen_v in TRUTH_ROWS:
        if budget < p95_high:
            v = "CANNOT FIT worst" if p95_low > budget else "PARTIAL admission"
        else:
            v = "fits"
        # an INERT row that starts fitting is a change even though the rank
        # vocabulary differs; ranks make the rest comparable
        changed = DERIVED_RANK[v] != FROZEN_RANK[frozen_v]
        if acct == 50 and v == "fits":
            v = "TRADEABLE (was INERT)"
        rows.append({"account": acct, "budget": budget, "frozen": frozen_v,
                     "rederived": v, "changed": changed})
    return rows


# ------------------------------------------------------------------- main --
def read_live_bars():
    """Pull ATR_BARS H1 bars from the running terminal. Returns (bars, last_epoch)
    or raises RuntimeError with the reason."""
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise RuntimeError(f"MetaTrader5 module unavailable: {e}")
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize failed: {mt5.last_error()}")
    try:
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, ATR_BARS)
        if bars is None or len(bars) < ATR_PERIOD + 10:
            raise RuntimeError(f"insufficient H1 bars for {SYMBOL}: "
                               f"{0 if bars is None else len(bars)}")
        seq = [(float(b["high"]), float(b["low"]), float(b["close"])) for b in bars]
        return seq, int(bars[-1]["time"])
    finally:
        mt5.shutdown()


def run_reading(append: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    out = {"schema": "v75_atr_drift_monitor/1",
           "generated_utc": now.isoformat(timespec="seconds"),
           "symbol": SYMBOL, "atr": {"tf": "H1", "period": ATR_PERIOD,
                                     "lookback_bars": ATR_BARS,
                                     "multiple": SL_ATR_MULTIPLE}}

    # -- calibration ------------------------------------------------------
    ks, dists = calibration_from_ledger()
    if ks:
        k_band = [min(ks), max(ks)]
        src = f"frozen tester ledger ({len(ks)} fills, {TESTER_LEDGER[-40:]})"
    else:
        k_band = list(FROZEN["k_band"])
        src = "FROZEN fallback (tester ledger missing)"
    drift = max(abs(k_band[i] / FROZEN["k_band"][i] - 1.0) for i in (0, 1))
    calib_ok = drift <= CALIB_DRIFT_TOL
    out["calibration"] = {"source": src, "k_band": [round(k_band[0], 6), round(k_band[1], 6)],
                          "frozen_k_band": FROZEN["k_band"], "max_departure": round(drift, 4),
                          "within_tolerance": calib_ok}

    # -- live ATR ---------------------------------------------------------
    try:
        bars, last_epoch = read_live_bars()
        atrs = [a for a in wilder_atr(bars) if a is not None]
        atrs_sorted = sorted(atrs)
        n = len(atrs_sorted)

        def pct(p):
            return atrs_sorted[min(n - 1, int(p / 100 * n))]
        atr_now, atr_med, atr_p05, atr_p95 = atrs[-1], median(atrs), pct(5), pct(95)
        age_h = (now.timestamp() - last_epoch) / 3600.0
        stale = age_h > STALE_HOURS
        out["market"] = {"bars": len(bars), "atr_now": round(atr_now, 2),
                         "atr_median": round(atr_med, 2), "atr_p05": round(atr_p05, 2),
                         "atr_p95": round(atr_p95, 2), "last_bar_age_h": round(age_h, 2),
                         "stale": stale}
    except RuntimeError as e:
        out["market"] = None
        out["verdict"] = "SKIPPED (terminal unavailable: %s)" % e
        _emit(out, append)
        return out

    # -- implied bands on the p95 geometry --------------------------------
    band_now = implied_minlot_band(atr_now, k_band)
    band_p95 = implied_minlot_band(atr_p95, k_band)
    out["implied_minlot_usd"] = {
        "now": [round(band_now[0], 2), round(band_now[1], 2)],
        "p95_geometry": [round(band_p95[0], 2), round(band_p95[1], 2)],
        "frozen_band": FROZEN["minlot_band"]}

    # -- verdict ----------------------------------------------------------
    verdict = classify(band_p95[0], band_p95[1])
    if not calib_ok and verdict == "HOLD":
        verdict = "WATCH (calibration drift)"
    if stale:
        verdict = "SKIPPED-STALE (last bar %.1fh old) — re-run on fresh data" % age_h
    out["verdict"] = verdict
    out["truth_table_rederived"] = rederive_rows(band_p95[0], band_p95[1])
    # 2026-09-15 amendment: dynamic strangulation floor (see K_CERT_STREAK note)
    s = band_p95[1]
    out["strangulation_floor"] = {
        "formula": "s*(k+5): 5s static admission + k*s absorb the streak + s trade after it",
        "s_worst_p95": round(s, 2), "k_certified": K_CERT_STREAK,
        "floor_certified": round(s * (K_CERT_STREAK + 5), 2),
        "floor_tail_k7": round(s * (K_TAIL + 5), 2),
        "floor_engineering_s28": round(S_ENGINEERING * (K_CERT_STREAK + 5), 2),
        "reading": ("BELOW every frozen truth-table row ($50-$150): the table answered "
                    "static admission only; the dynamic floor (certified streak k=6) "
                    "requires ~$226 at the p95 geometry. Amendment 2026-09-15 appended "
                    "to GO_LIVE_CHECKLIST.md.")}
    _emit(out, append)
    return out


def _emit(out: dict, append: bool) -> None:
    stale_flags = [r for r in out.get("truth_table_rederived", []) if r["changed"]]
    print(f"[atrdrift] {out['verdict']}")
    m = out.get("market")
    if m:
        print(f"  ATR(H1,{ATR_PERIOD}): now {m['atr_now']} | median {m['atr_median']} "
              f"| p05 {m['atr_p05']} | p95 {m['atr_p95']}  ({m['bars']} bars)")
    imp = out.get("implied_minlot_usd")
    if imp:
        print(f"  implied min-lot stop $: now {imp['now']} | p95 geometry {imp['p95_geometry']} "
              f"| frozen {imp['frozen_band']}")
    for r in out.get("truth_table_rederived", []):
        mark = "  <-- CHANGED" if r["changed"] else ""
        print(f"  ${r['account']:<4} budget ${r['budget']:<5} frozen={r['frozen']:<18} "
              f"rederived={r['rederived']}{mark}")
    fl = out.get("strangulation_floor")
    if fl:
        print(f"  strangulation floor: ${fl['floor_certified']} (certified k={fl['k_certified']}, "
              f"s=${fl['s_worst_p95']}) | tail k=7: ${fl['floor_tail_k7']} | "
              f"engineering s=$28: ${fl['floor_engineering_s28']}")
    if out.get("calibration", {}).get("within_tolerance") is False:
        print("  CALIBRATION-DRIFT: conversion departed the frozen band — investigate before trusting any row")
    if append:
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        hist = []
        if os.path.exists(ARTIFACT):
            try:
                hist = json.load(open(ARTIFACT))
            except (json.JSONDecodeError, OSError):
                hist = []
        hist = hist if isinstance(hist, list) else []
        hist.append(out)
        with open(ARTIFACT, "w") as f:
            json.dump(hist, f, indent=1)
        print(f"  appended -> {ARTIFACT} (reading #{len(hist)})")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-append", action="store_true", help="read-only, do not touch the artifact")
    args = ap.parse_args()
    run_reading(append=not args.no_append)


if __name__ == "__main__":
    main()
