#!/usr/bin/env python3
"""MIDASTOUCH Step 4 — gold research sweep (XAUUSD, frozen protocol).

Implements docs/MIDASTOUCH_PROTOCOL.md exactly:
  - data of record: data/forex/xauusd/XAUUSD_{H1,M15}.csv
  - macro filter on closed H4+H1 (close[1] vs EMA20[1], V75-family rule)
  - M15 trigger: BB(20,2) band-touch-with-close-back-inside, or RSI(14) 70/30
  - 8 registry modes, frozen exits (SL=2xATR_H1, TP=2R, timeout 48 M15 bars)
  - cost model: per-bar recorded spread, min $0.10, half each side
  - sizing: 1% of a $5,000 virtual book (the standard-symbol floor-table
    equity; R is lot-invariant so micro deployment scales identically),
    min-lot floor enforced and disclosed
  - windows IS1 / IS2 / WF / OOS as frozen; OOS touched by the same pass
  - gates G1..G7 evaluated per mode; NO-SHIP default

--selftest runs the in-file checks (causality, spread, SL-first, timeout,
floor sizing, R identity) on synthetic data before any real run is trusted.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from bisect import bisect_right
from datetime import datetime, timezone

DATA_DIR = os.path.join("data", "forex", "xauusd")
ART = "artifacts"
POINT = 0.01
TICK_VALUE_PER_LOT = 100.0        # $ per 1.0 price unit per 1.0 lot (100 oz)
MIN_LOT = 0.01
START_EQUITY = 5000.0            # the CERTIFIED research basis: the §13 corpus was
                                 # fitted at $5,000 and its artifacts are stated in
                                 # R, which is lot-invariant except where the
                                 # min-lot floor binds. Do not change it to make a
                                 # number look better — see _BASIS below for how a
                                 # run on another account is stated instead.
RISK_FRACTION = 0.01

#: Run-scoped sizing basis. `None` means "the certified research basis" (ab
#: START_EQUITY); a parity run sets it to the LIVE account's basis, because parity
#: claims the EA and this engine agree on ONE account, not on two arbitrarily
#: different books. Where the min-lot floor binds, the basis changes the trade set —
#: which is exactly what a basis change has to be measured against, not assumed away.
_BASIS: float | None = None


def use_basis(basis_usd: float) -> None:
    """Size this run's simulated account at `basis_usd`."""
    global _BASIS
    val = float(basis_usd)
    if val <= 0:
        raise ValueError(f"sizing basis must be positive, got {basis_usd!r}")
    _BASIS = val


def equity_basis() -> float:
    """The equity every simulated run starts from (override, else certified)."""
    return START_EQUITY if _BASIS is None else _BASIS
# Amendment 6 (2026-09-17, register R5): a min-lot floor that would push the
# real risk past this fraction of the sizing basis VETOES the trade in BOTH
# engines (python here; EA InpMaxRiskPct — same formula against each engine's
# own contract value and basis). 15% is the MEASURED choice, frozen on safety
# grounds with the decision table in protocol amendment 6: the certified WF
# corpus floors 42/151 fills at up to 5.5% of the book, so any cap below ~6%
# re-writes certified behavior (1.5% would veto 15+ fills, 2% ten), and on
# the $50 §13 arms (micro contract, ~$4.55 day-one min-lot risk) anything
# below ~10% starves the forward windows entirely. 15% vetoes ZERO certified
# fills, passes day-one arm risk with margin, and still blocks the pathology
# the review demanded: a small book eating a runaway stop.
MAX_RISK_FRACTION = 0.15
SPREAD_FLOOR = 0.10               # dollars, when the bar records 0
SL_ATR_MULT = 2.0
TP_MULT = 2.0
TIMEOUT_BARS = 48
SESSION_HOURS = (12, 16)          # H1 (frozen hypothesis window)

WINDOWS = {
    "is1": ("2024-04-10T00:00", "2025-03-31T23:59"),
    "is2": ("2025-04-01T00:00", "2026-03-31T23:59"),
    "wf":  ("2025-09-15T00:00", "2026-03-31T23:59"),
    "oos": ("2026-04-01T00:00", "2026-09-16T23:59"),
    # The TICK-COVERED window: this venue serves real gold ticks only from 2026-09-04,
    # so this is the one window where a `Model=4` pass is genuinely the per-tick model
    # the parity contract claims. Short by construction — the venue's depth decides it,
    # not taste. See docs/DATA_SCOPE_AND_CLOCK_20260920.md §9-10.
    "tickcov": ("2026-09-04T00:00", "2026-09-16T23:59"),
}
MODES = ["ORIGINAL", "REVERSE_DIRECTION", "REVERSE_TRIGGER", "REVERSE_BOTH",
         "LONG_ONLY", "SHORT_ONLY", "MACRO_ONLY", "TRIGGER_ONLY"]


# ── data ────────────────────────────────────────────────────────────────────
def load_bars(path: str) -> list[dict]:
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            rows.append({"time": int(r["time"]),
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"]),
                         "spread": float(r["spread"]) * POINT})
    return rows


def ema(vals: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out, e = [], vals[0]
    for i, v in enumerate(vals):
        e = v if i == 0 else v * k + e * (1 - k)
        out.append(e)
    return out


def wilder_atr(bars: list[dict], n: int = 14) -> list[float]:
    out, atr = [], None
    prev_close = bars[0]["close"]
    trs = []
    for i, b in enumerate(bars):
        tr = max(b["high"] - b["low"],
                 abs(b["high"] - prev_close), abs(b["low"] - prev_close))
        prev_close = b["close"]
        trs.append(tr)
        if i < n:
            atr = sum(trs) / len(trs)
        else:
            atr = (atr * (n - 1) + tr) / n
        out.append(atr)
    return out


def sma_atr(bars: list[dict], n: int = 14) -> list[float]:
    """Bounded ATR (protocol amendment 2): SMA of True Range over the last n
    CLOSED bars. Unbounded Wilder ATR can never be parity-tested: the tester
    preloads only a short bar window before the test start, so its Wilder
    recursion is seed-dominated while a deep-history engine is converged
    (measured divergence up to 11% on the same bars, 2026-09-16). A bounded
    definition computes identically on both engines and live."""
    out: list[float] = []
    prev_close = bars[0]["close"]
    trs: list[float] = []
    for b in bars:
        tr = max(b["high"] - b["low"],
                 abs(b["high"] - prev_close), abs(b["low"] - prev_close))
        prev_close = b["close"]
        trs.append(tr)
        if len(trs) > n:
            trs.pop(0)
        out.append(sum(trs) / len(trs))
    return out


def rsi_wilder(closes: list[float], n: int = 14) -> list[float]:
    out: list[float] = [50.0] * len(closes)
    gains = losses = 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            gains += g / n
            losses += l / n
            if i == n:
                out[i] = 100 - 100 / (1 + (gains / losses if losses else 1e9))
        else:
            gains = (gains * (n - 1) + g) / n
            losses = (losses * (n - 1) + l) / n
            out[i] = 100 - 100 / (1 + (gains / losses if losses else 1e9))
    return out


def bb_touch(closes: list[float], i: int, n: int = 20, k: float = 2.0) -> int:
    """+1 closed above upper then back inside; -1 below lower then back in."""
    if i < n:
        return 0
    win = closes[i - n + 1:i + 1]
    mid = sum(win) / n
    sd = math.sqrt(sum((x - mid) ** 2 for x in win) / n)
    up, lo = mid + k * sd, mid - k * sd
    prev = closes[i - 1]
    if prev > mid + k * sd and closes[i] < up:
        return 1
    if prev < mid - k * sd and closes[i] > lo:
        return -1
    return 0


def h4_series(h1: list[dict]) -> list[dict]:
    out: list[dict] = []
    cur = None
    cur_t0 = None
    for b in h1:
        t0 = b["time"] - (b["time"] % 14400)
        if cur_t0 != t0:
            if cur:
                out.append(cur)
            cur_t0, cur = t0, {"time": t0, "open": b["open"], "high": b["high"],
                               "low": b["low"], "close": b["close"]}
        else:
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
    if cur:
        out.append(cur)
    return out


def macro_state(h1_close: float, h1_ema: float,
                h4_close: float, h4_ema: float) -> int:
    """+1 ALIGNED_UP, -1 ALIGNED_DOWN, 0 DIVERGENT (V75-family rule)."""
    h1_up, h4_up = h1_close > h1_ema, h4_close > h4_ema
    if h1_up and h4_up:
        return 1
    if not h1_up and not h4_up:
        return -1
    return 0


# ── engine ──────────────────────────────────────────────────────────────────
class RunResult:
    def __init__(self):
        self.trades: list[dict] = []
        self.final_equity = equity_basis()
        self.vetoed = 0


def minlot_risk_exceeds_cap(stop_d: float, basis: float) -> bool:
    """Amendment 6 veto predicate: would the MIN-LOT trade risk more than
    MAX_RISK_FRACTION of the sizing basis? Pure; the EA mirrors this exact
    formula (InpMaxRiskPct) at its three sizing sites. "Exceeds" is strict:
    exactly-at-cap fills."""
    return stop_d * TICK_VALUE_PER_LOT * MIN_LOT > basis * MAX_RISK_FRACTION


def run_mode(mode: str, t0: int, t1: int, data: dict) -> RunResult:
    h1, m15, h4 = data["h1"], data["m15"], data["h4"]
    h1_ema, h1_atr = data["h1_ema"], data["h1_atr"]
    h4_ema = data["h4_ema"]
    m15_close = data["m15_close"]
    m15_rsi, m15_bb = data["m15_rsi"], data["m15_bb"]

    res = RunResult()
    equity = equity_basis()
    pos = None
    pending = None
    floored = 0

    # index pointers via bisect over close-times
    for i, b in enumerate(m15):
        ct = b["time"] + 900                     # close time of this M15 bar
        in_window = ct > t0 and b["time"] <= t1

        # 1) fill a pending signal at THIS bar's open (protocol: "fill at
        #    next M15 open"), then manage the fresh position on this bar.
        #    Valid ONLY on the immediate next bar (b.time == sig_ct); anything
        #    else kills the pending signal — no stale entries.
        if pending is not None and pos is None and in_window \
                and b["time"] == pending["sig_ct"]:
            side = 1 if pending["direction"] > 0 else -1
            sp_open = max(b["spread"], SPREAD_FLOOR)
            fill = b["open"] + side * sp_open / 2
            stop_d = pending["stop_d"]
            risk_frac_dollars = equity * RISK_FRACTION
            lots = risk_frac_dollars / (stop_d * TICK_VALUE_PER_LOT)
            if lots < MIN_LOT:
                if minlot_risk_exceeds_cap(stop_d, equity):
                    # Amendment 6: the floored trade would exceed the risk
                    # cap — veto. No position is constructed; the vetoed bar
                    # runs no signal detection (mirrors the EA BAR caller's
                    # `if(!may_signal) continue`; pending is dead, same-bar
                    # re-entry is impossible by construction).
                    res.vetoed += 1
                    pending = None
                    continue
                lots, floored = MIN_LOT, floored + 1
            risk_d = stop_d * TICK_VALUE_PER_LOT * lots
            pos = {"side": side, "entry": fill,
                   "sl": fill - side * stop_d,
                   "tp": fill + side * stop_d * TP_MULT,
                   "open_ct": b["time"], "lots": lots, "risk_d": risk_d,
                   "sp": sp_open, "closed": False, "mfe": 0.0, "mae": 0.0,
                   "hour": pending["hour"], "mac": pending["mac"],
                   "mode": mode}
            pending = None

        # 2) manage the open position across this bar (SL-first on ties)
        if pos:
            pending = None
            _manage(pos, b, res, equity)
            if pos.get("closed"):
                equity = pos["equity_after"]
                pos = None
            continue

        if not in_window:
            pending = None
            continue

        # 3) signal detection on the bar that just CLOSED (time = ct)
        k1 = bisect_right(data["h1_ct"], ct)
        k4 = bisect_right(data["h4_ct"], ct)
        if k1 < 21 or k4 < 21 or i < 21:
            continue

        atr = h1_atr[k1 - 1]
        stop_d = SL_ATR_MULT * atr
        if stop_d <= 0:
            continue
        mac = macro_state(h1[k1 - 1]["close"], h1_ema[k1 - 1],
                          h4[k4 - 1]["close"], h4_ema[k4 - 1])

        # trigger on this closed M15 bar
        t_bb, t_rsi = m15_bb[i], m15_rsi[i]
        trigger = 0
        if t_bb != 0:
            trigger = t_bb
        elif t_rsi >= 70:
            trigger = -1                        # RSI overbought -> short signal
        elif t_rsi <= 30:
            trigger = 1

        # mode transformations (V28 registry vocabulary, documented here):
        #   ORIGINAL          trigger fires, macro must agree with it
        #   REVERSE_DIRECTION trigger fires, direction inverted, macro agrees
        #   REVERSE_TRIGGER   enter only where NO trigger fired, macro side
        #   REVERSE_BOTH      enter only where NO trigger fired, anti-macro side
        #   LONG_ONLY/SHORT_ONLY  ORIGINAL entries filtered to one side
        #   MACRO_ONLY        no trigger requirement, macro direction
        #   TRIGGER_ONLY      trigger direction, no macro gate
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
        else:  # TRIGGER_ONLY
            take, direction = trigger != 0, trigger
        if not take or direction == 0:
            continue

        # 4) session gate (frozen policy: entries only 06:00-20:00 UTC),
        #    then STASH the signal — it fills at the next bar's open.
        hr = datetime.fromtimestamp(b["time"], tz=timezone.utc).hour
        if not (6 <= hr < 20):
            continue

        pending = {"direction": direction, "stop_d": stop_d,
                   "hour": hr, "mac": mac, "sig_ct": ct}
    res.floored = floored
    return res


def _manage(pos: dict, b: dict, res: RunResult, equity: float) -> None:
    """Manage an open position across one M15 bar. SL-first on ties."""
    if pos.get("closed"):
        return
    side, stop_d = pos["side"], pos["risk_d"] / (pos["lots"] * TICK_VALUE_PER_LOT)
    # excursions (M15 h/l), in R
    if side > 0:
        fav = (b["high"] - pos["entry"]) / stop_d
        adv = (pos["entry"] - b["low"]) / stop_d
    else:
        fav = (pos["entry"] - b["low"]) / stop_d
        adv = (b["high"] - pos["entry"]) / stop_d
    pos["mfe"] = max(pos["mfe"], fav)
    pos["mae"] = max(pos["mae"], adv)

    exit_px, reason = None, None
    if side > 0:
        if b["low"] <= pos["sl"]:
            exit_px, reason = pos["sl"], "SL"
        elif b["high"] >= pos["tp"]:
            exit_px, reason = pos["tp"], "TP"
    else:
        if b["high"] >= pos["sl"]:
            exit_px, reason = pos["sl"], "SL"
        elif b["low"] <= pos["tp"]:
            exit_px, reason = pos["tp"], "TP"
    bars_held = b["time"] + 900 - pos["open_ct"]
    if exit_px is None and bars_held >= TIMEOUT_BARS * 900:
        sp = max(b["spread"], SPREAD_FLOOR)
        exit_px = b["close"] - side * sp / 2
        reason = "TIMEOUT"
    if exit_px is None:
        return

    sp = max(b["spread"], SPREAD_FLOOR)
    if reason in ("SL", "TP"):
        # exit at the level; charge the exit half-spread on top
        exit_px = exit_px - side * sp / 2
    move = (exit_px - pos["entry"]) * side
    pnl = move * TICK_VALUE_PER_LOT * pos["lots"]
    r = pnl / pos["risk_d"]
    equity = equity + pnl
    res.trades.append({
        "open_ct": pos["open_ct"], "close_ct": b["time"] + 900,
        "side": pos["side"], "entry": round(pos["entry"], 3),
        "exit": round(exit_px, 3), "reason": reason,
        "lots": pos["lots"], "risk_d": round(pos["risk_d"], 2),
        "pnl": round(pnl, 2), "r": round(r, 4),
        "mfe_r": round(pos["mfe"], 3), "mae_r": round(pos["mae"], 3),
        "hour": pos["hour"], "mac": pos["mac"], "mode": pos["mode"],
        "spread_cost_r": round(pos["sp"] / stop_d, 4) if stop_d else 0,
        "bars_held": bars_held // 900})
    pos["closed"] = True
    pos["equity_after"] = equity


# ── metrics + gates ─────────────────────────────────────────────────────────
def metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    rs = [t["r"] for t in trades]
    pnls = [t["pnl"] for t in trades]
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    cum, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {
        "n": len(trades),
        "net_pnl": round(sum(pnls), 2),
        "net_r": round(sum(rs), 3),
        "expectancy_r": round(sum(rs) / len(rs), 4),
        "pf": round(gw / gl, 3) if gl > 0 else None,
        "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 3),
        "max_dd_r": round(dd, 2),
        "mean_spread_cost_r": round(sum(t["spread_cost_r"] for t in trades) / len(trades), 4),
        "mean_mfe_r": round(sum(t["mfe_r"] for t in trades) / len(trades), 3),
        "mean_mae_r": round(sum(t["mae_r"] for t in trades) / len(trades), 3),
    }


def gates(oos: dict, window_nets: dict) -> tuple[bool, list[str]]:
    why: list[str] = []
    if oos.get("n", 0) < 30:
        why.append(f"G1 n={oos.get('n', 0)} < 30")
    if oos.get("n", 0) and not (oos["net_r"] > 0):
        why.append("G2 OOS net_r not positive")
    pf = oos.get("pf")
    if pf is None or pf < 1.30:
        why.append(f"G3 pf={pf} < 1.30")
    if oos.get("n", 0) and oos["expectancy_r"] < 0.15:
        why.append(f"G4 expectancy {oos['expectancy_r']} < +0.15R")
    if oos.get("n", 0) and oos["max_dd_r"] > 12:
        why.append(f"G5 dd {oos['max_dd_r']}R > 12R")
    pos_w = sum(1 for v in window_nets.values() if v > 0)
    if pos_w < 3:
        why.append(f"G6 positive windows {pos_w}/4 < 3")
    if oos.get("n", 0) and oos["mean_spread_cost_r"] > 0.10:
        why.append(f"G7 spread cost {oos['mean_spread_cost_r']}R > 0.10R")
    return (not why), why


# ── selftest ────────────────────────────────────────────────────────────────
def selftest() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'} {name}")
        ok &= bool(cond)

    # causality: EMA/ATR at index i must not change when future bars change
    bars = [{"time": 3600 * i, "open": 1, "high": 2, "low": 0.5,
             "close": 1 + (i % 5) * 0.1, "spread": 0} for i in range(100)]
    a1 = sma_atr(bars)[50]
    bars2 = [dict(b) for b in bars]
    for b in bars2[60:]:
        b["high"] += 100
    check("ATR causality (sma, bounded)", abs(a1 - sma_atr(bars2)[50]) < 1e-12)
    check("sma_atr window bound",
          abs(sma_atr(bars)[99] - sum(max(bars[i]["high"] - bars[i]["low"],
                                         abs(bars[i]["high"] - bars[i - 1]["close"]),
                                         abs(bars[i]["low"] - bars[i - 1]["close"]))
                                       for i in range(86, 100)) / 14) < 1e-9)

    # spread: a buy opened and closed same bar at close pays full spread
    r = RunResult()
    pos = {"side": 1, "entry": 100.05, "sl": 90, "tp": 110, "open_bar": 0,
           "open_ct": 0, "lots": 0.01, "risk_d": 10.0, "sp": 0.10,
           "closed": False, "mfe": 0, "mae": 0, "hour": 12, "mac": 1,
           "mode": "T", "equity_after": None}
    b = {"time": 85500, "open": 100, "high": 101, "low": 99, "close": 100,
         "spread": 0.0}
    _manage(pos, b, r, START_EQUITY)
    # entry paid +0.05; timeout exit pays close - 0.05 -> net one full spread
    check("spread charged once round-trip",
          abs(r.trades[0]["pnl"] - (-0.10 * TICK_VALUE_PER_LOT * 0.01)) < 1e-9)

    # SL-first tie-break: bar touching both SL and TP must close at SL
    r = RunResult()
    pos = {"side": 1, "entry": 100, "sl": 99, "tp": 101, "open_bar": 0,
           "open_ct": 0, "lots": 0.01, "risk_d": 1.0, "sp": 0.0,
           "closed": False, "mfe": 0, "mae": 0, "hour": 12, "mac": 1,
           "mode": "T"}
    b = {"time": 900, "open": 100, "high": 101, "low": 99, "close": 100,
         "spread": 0.0}
    _manage(pos, b, r, START_EQUITY)
    check("SL-first on tie", r.trades[0]["reason"] == "SL")

    # timeout: 48 M15 bars later closes at TIMEOUT
    r = RunResult()
    pos = {"side": 1, "entry": 100, "sl": 90, "tp": 110, "open_bar": 0,
           "open_ct": 0, "lots": 0.01, "risk_d": 1.0, "sp": 0.0,
           "closed": False, "mfe": 0, "mae": 0, "hour": 12, "mac": 1,
           "mode": "T"}
    b = {"time": TIMEOUT_BARS * 900, "open": 100, "high": 100.5, "low": 99.5,
         "close": 100.2, "spread": 0.0}
    _manage(pos, b, r, START_EQUITY)
    check("timeout fires at 48 bars", r.trades[0]["reason"] == "TIMEOUT")

    # R identity: pnl / risk == move / stop
    t = r.trades[0]
    check("R identity", abs(t["r"] - (t["pnl"] / t["risk_d"])) < 1e-6)

    # macro rule
    check("macro aligned up", macro_state(2, 1, 2, 1) == 1)
    check("macro divergent", macro_state(2, 3, 2, 1) == 0)
    print("SELFTEST:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 2


# ── main ────────────────────────────────────────────────────────────────────
def iso_to_ts(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    h1 = load_bars(os.path.join(DATA_DIR, "XAUUSD_H1.csv"))
    m15 = load_bars(os.path.join(DATA_DIR, "XAUUSD_M15.csv"))
    h4 = h4_series(h1)
    data = {
        "h1": h1, "m15": m15, "h4": h4,
        "h1_ct": [b["time"] + 3600 for b in h1],
        "h4_ct": [b["time"] + 14400 for b in h4],
        "h1_ema": ema([b["close"] for b in h1], 20),
        "h1_atr": sma_atr(h1),   # amendment 2: bounded ATR for parity
        "h4_ema": ema([b["close"] for b in h4], 20),
        "m15_close": [b["close"] for b in m15],
        "m15_rsi": rsi_wilder([b["close"] for b in m15]),
        "m15_bb": [0] * len(m15),
    }
    mc = data["m15_close"]
    for i in range(len(m15)):
        data["m15_bb"][i] = bb_touch(mc, i)

    results: dict = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "modes": {}}
    verdicts: dict = {}
    for mode in MODES:
        results["modes"][mode] = {}
        window_nets: dict = {}
        for wname, (a, bnd) in WINDOWS.items():
            rr = run_mode(mode, iso_to_ts(a), iso_to_ts(bnd), data)
            m = metrics(rr.trades)
            m["floored_lots"] = rr.floored
            results["modes"][mode][wname] = m
            window_nets[wname] = m.get("net_r", 0)
        ok, why = gates(results["modes"][mode]["oos"], window_nets)
        verdicts[mode] = {"verdict": "EDGE" if ok else "NO-SHIP",
                          "reasons": why}
        o = results["modes"][mode]["oos"]
        print(f"{mode:<20} OOS n={o.get('n', 0):>4} netR={o.get('net_r', 0):>8.2f} "
              f"pf={o.get('pf')} exp={o.get('expectancy_r')} ddR={o.get('max_dd_r')} "
              f"-> {verdicts[mode]['verdict']}")

    os.makedirs(ART, exist_ok=True)
    out = os.path.join(ART, f"midas_sweep_{datetime.now():%Y%m%d}.json")
    with open(out, "w") as fh:
        json.dump({"results": results, "verdicts": verdicts}, fh, indent=1)
    print("artifact:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
