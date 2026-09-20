#!/usr/bin/env python3
"""XAUUSD geometry study: the BRACKET's own bias, measured with no entry signal.

WHY THIS EXISTS. The first gold walk-forward (`docs/GOLD_WFO_VERDICT_20260919.md`)
returned NOT VALIDATED (t = +0.52) and, inside the same run, measured that the
*same geometry with random entries* lost about 0.15R per trade. There were two
readings of that number: the entry rule is worthless, or the bracket bleeds on
its own. The verdict chose the second — "entries cannot be judged on a
negative-expectancy geometry" — and that is a TESTABLE claim. This script tests
it without any entry signal at all.

THE METHOD. Enter at the close of every M15 bar in the session window, in the
long direction only (see SYMMETRY below), and measure where the bracket ends up:
stop, target, or the time stop. Sweep the stop/target pair in ATR units and the
holding horizon. The output is the map of EXPECTANCY UNDER A COIN FLIP — which
is exactly the bias an entry rule has to overcome before it has earned anything.

WHY BOTH DIRECTIONS ARE SIMULATED (correcting a first-pass error). The barrier
RESOLUTION rule is symmetric under reflection — a long's "both barriers in one
bar" condition is `low <= stop and high >= target`, a short's is `high >= stop
and low <= target`, the same set of bars. But symmetry of the RULE is not
symmetry of the DISTRIBUTION: a price series with drift is not reflection-
invariant, so E[R | long] != E[R | short]. Simulating only longs would have
folded the sample's drift into what the run calls "geometry bias".

So every cell is measured twice and decomposed:

    E_dir  = (E_long + E_short) / 2   <- the DRIFT-NEUTRAL coin flip.
                                         This is the geometry's own bias, and it
                                         is the number an entry rule must beat.
    E_drift = (E_long - E_short) / 2   <- the sample's directional drift over the
                                         holding window, which is not an edge
                                         the strategy can claim either.

TWO BOUNDS, NOT ONE NUMBER. Bar data cannot say which barrier a bar touched
first, so the answer is reported as a BAND: the pessimistic reading (stop first
on a tie) and the optimistic one (target first). A geometry whose edge exists
only in the optimistic column is an artifact of the assumption, not an edge.
Phase 2 (`--ticks`) calibrates that tie against the ~7 days of real ticks this
broker keeps.

COSTS. Booked exactly as the frozen protocol books them — the constants are
imported from `gold_walkforward` so this tool cannot drift from the protocol:
spread 1.073 bps (tick-measured, not the 2.2x tighter bar field) plus $10/lot
round trip, converted to R through the stop distance and the MEASURED
`order_calc_profit` basis (USD_PER_UNIT_PER_LOT = 100).
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

from gold_walkforward import (  # noqa: E402
    ATR_PERIOD,
    COMMISSION_PER_LOT_RT,
    FLAT_BY_UTC_HOUR,
    SPREAD_BPS,
    USD_PER_UNIT_PER_LOT,
    wilder_atr,
)
from mt5_data import load_m5  # noqa: E402

# --------------------------------------------------------------------------- #
# Study constants (declared before any result)
# --------------------------------------------------------------------------- #

SYMBOL = "XAUUSD"
EXEC_TF = "M15"
WARMUP = 500                     # ATR warmup, matching the protocol's floor
SESSION_LO, SESSION_HI = 7, 20   # the protocol's entry window, so the measured
                                 # path is the path the strategy actually faces
STOP_MULTS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)
TP_MULTS = (0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
HORIZONS = (4, 8, 16, 32, 64)    # M15 bars = 1h, 2h, 4h, 8h, 16h
MAX_HORIZON = max(HORIZONS)


# --------------------------------------------------------------------------- #
# Window matrices
# --------------------------------------------------------------------------- #

def window_matrix(arr: np.ndarray, horizon: int) -> np.ndarray:
    """``M[i, k] = arr[i + k]`` for k = 1..horizon.

    Rows whose window would run past the end of the series stay NaN, so a caller
    cannot silently score a truncated horizon as a completed one.
    """
    n = len(arr)
    m = np.full((n, horizon + 1), np.nan, dtype=float)
    for k in range(1, horizon + 1):
        if k < n:
            m[:n - k, k] = arr[k:]
    return m


def build_windows(idx: np.ndarray, o: np.ndarray, h: np.ndarray, l: np.ndarray,
                  c: np.ndarray, horizon: int) -> dict:
    """Window matrices sliced to the entry rows, built ONCE per horizon.

    Entries are a subset of the series (session bars only), so the slicing has to
    happen before any per-entry barrier is broadcast against them.
    """
    return {"o": window_matrix(o, horizon)[idx],
            "h": window_matrix(h, horizon)[idx],
            "l": window_matrix(l, horizon)[idx],
            "c": window_matrix(c, horizon)[idx]}


def session_mask(epoch: np.ndarray) -> np.ndarray:
    """Bars whose UTC hour is inside the protocol's entry window."""
    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in epoch], dtype=int)
    return (hours >= SESSION_LO) & (hours <= SESSION_HI) & (hours < FLAT_BY_UTC_HOUR)


# --------------------------------------------------------------------------- #
# The core measurement
# --------------------------------------------------------------------------- #

def bracket_outcomes(entry: np.ndarray, atr_e: np.ndarray, win: dict,
                     stop_mult: float, tp_mult: float, horizon: int,
                     *, direction: int, optimistic: bool) -> dict:
    """Coin-flip entry at ``entry``, bracket in ATR units, signed by ``direction``.

    Returns gross R in units of the stop distance, plus the exit-reason counts.
    Resolution, checked bar by bar in order:

      1. a gap through a barrier fills AT THE BAR'S OPEN (a stop cannot fill at
         its own price when the market opens beyond it);
      2. if BOTH barriers sit inside one bar, the tie is resolved per the
         ``optimistic`` flag — this is the band, not a choice;
      3. if neither is touched within ``horizon`` bars, the time stop takes the
         close of bar ``horizon``.

    Everything is written sign-generically (``direction = +1`` long, ``-1``
    short) so the two runs are provably the same rule mirrored, not two
    separately-written functions that could disagree.
    """
    d = 1 if direction > 0 else -1
    risk = np.where(stop_mult * atr_e > 0, stop_mult * atr_e, np.nan)
    sl = entry - d * stop_mult * atr_e           # stop is always behind us
    tp = entry + d * tp_mult * atr_e             # target always ahead
    n = len(entry)

    O, H, L, C = win["o"], win["h"], win["l"], win["c"]
    ADV = L if d > 0 else H    # the extreme that runs AGAINST the position
    FAV = H if d > 0 else L    # the extreme that runs FOR it

    # --- stop side: a gap through the stop fills at the open (worse than the stop)
    gap_stop = d * (O - sl[:, None]) <= 0
    stop_touch = (gap_stop | (d * (ADV - sl[:, None]) <= 0))[:, 1:]
    stop_price = np.where(gap_stop, O, np.broadcast_to(sl[:, None], O.shape))[:, 1:]

    # --- target side: a gap through the target fills at the open (worse than it)
    gap_tp = d * (O - tp[:, None]) >= 0
    tp_touch = (gap_tp | (d * (FAV - tp[:, None]) >= 0))[:, 1:]
    tp_price = np.where(gap_tp, O, np.broadcast_to(tp[:, None], O.shape))[:, 1:]

    any_stop = stop_touch.any(axis=1)
    any_tp = tp_touch.any(axis=1)
    first_stop = np.where(any_stop, stop_touch.argmax(axis=1), horizon)
    first_tp = np.where(any_tp, tp_touch.argmax(axis=1), horizon)

    if optimistic:
        take_stop = any_stop & (first_stop < first_tp)      # target wins a tie
    else:
        take_stop = any_stop & (first_stop <= first_tp)     # stop wins a tie
    take_tp = any_tp & ~take_stop

    rows = np.arange(n)
    px = np.full(n, np.nan, dtype=float)
    px[take_stop] = stop_price[rows[take_stop], first_stop[take_stop]]
    px[take_tp] = tp_price[rows[take_tp], first_tp[take_tp]]
    timed = ~(take_stop | take_tp)
    px[timed] = C[rows[timed], horizon]

    valid = np.isfinite(px) & np.isfinite(risk) & np.isfinite(entry)
    return {
        "gross": d * (px[valid] - entry[valid]) / risk[valid],
        "n": int(valid.sum()),
        "n_stop": int((take_stop & valid).sum()),
        "n_tp": int((take_tp & valid).sum()),
        "n_time": int((timed & valid).sum()),
        "risk": risk[valid],
        "entry": entry[valid],
    }


def cost_r(entry: np.ndarray, risk: np.ndarray) -> np.ndarray:
    """Round-trip toll in R: spread + commission, both normalised by the stop."""
    return (SPREAD_BPS / 1e4 * entry / risk
            + COMMISSION_PER_LOT_RT / (risk * USD_PER_UNIT_PER_LOT))


def path_stats(entry: np.ndarray, atr_e: np.ndarray, win: dict,
               horizon: int, *, direction: int = 1) -> dict:
    """How far gold actually travels, in ATR units, over ``horizon`` bars.

    MFE/MAE are the favourable/adverse extremes of the path. They do not depend
    on the ORDER the barriers were touched in, so they are assumption-free — and
    they bound what any bracket can possibly collect. Reported for BOTH
    directions: if MFE_long is systematically smaller than MFE_short on the same
    bars, the sample has drift, and that is a property of the window rather than
    of anything a strategy can claim.
    """
    H = win["h"][:, 1:]
    L = win["l"][:, 1:]
    d = 1 if direction > 0 else -1
    with np.errstate(invalid="ignore"):
        if d > 0:
            mfe = (np.nanmax(H, axis=1) - entry) / atr_e
            mae = (entry - np.nanmin(L, axis=1)) / atr_e
        else:
            mfe = (entry - np.nanmin(L, axis=1)) / atr_e
            mae = (np.nanmax(H, axis=1) - entry) / atr_e
    ok = np.isfinite(mfe) & np.isfinite(mae)
    return {"mfe": mfe[ok], "mae": mae[ok], "n": int(ok.sum())}


def _pct(a: np.ndarray, q: float) -> float:
    return float(np.percentile(a, q)) if len(a) else float("nan")


def block_se(rs: np.ndarray, block: int) -> float:
    """SE that respects the overlap between consecutive entries.

    Consecutive bars enter the same price path, so their outcomes are NOT
    independent and a naive SE would be far too small. Sampling every ``block``-th
    entry keeps the number honest: it answers "would a non-overlapping set of
    entries have said the same thing?"
    """
    sub = rs[::max(1, block)]
    if len(sub) < 2:
        return float("nan")
    return float(np.std(sub, ddof=1) / math.sqrt(len(sub)))


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_geometry_study.json")
    a = ap.parse_args(argv)

    data = load_m5(a.symbol, timeframe=EXEC_TF, bars=a.bars)
    epoch = data.array["epoch"].astype(float)
    o = data.array["open"].astype(float)
    h = data.array["high"].astype(float)
    l = data.array["low"].astype(float)
    c = data.array["close"].astype(float)
    n = len(epoch)
    atr = wilder_atr(h, l, c, ATR_PERIOD)
    print(f"{a.symbol} {EXEC_TF}: {n} bars  "
          f"{datetime.fromtimestamp(epoch[0], timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(epoch[-1], timezone.utc):%Y-%m-%d}")

    # Entry universe: session bars only, with a full horizon ahead, valid ATR.
    ok = session_mask(epoch) & np.isfinite(atr) & (atr > 0)
    ok[:WARMUP] = False
    ok[n - MAX_HORIZON:] = False
    idx = np.flatnonzero(ok)
    if len(idx) < 100:
        print("not enough entry bars to study")
        return 1
    entry, atr_e = c[idx], atr[idx]
    print(f"entry universe: {len(idx)} bars ({100*len(idx)/n:.0f}% of series), "
          f"ATR median ${np.median(atr_e):.2f} "
          f"({100*np.median(atr_e)/np.median(entry):.2f}% of price)")

    # ---- path statistics (assumption-free) ----
    print("\n=== PATH STATISTICS (ATR units, no bracket assumed) ===")
    print("MFE = best excursion FOR the trade, MAE = worst AGAINST it.")
    print(f"{'H':>4} {'dir':>6} {'medMFE':>7} {'medMAE':>7} {'P(MFE>=1)':>10} "
          f"{'P(MAE>=1)':>10} {'driftATR':>9}")
    path_rows = []
    for H in HORIZONS:
        win = build_windows(idx, o, h, l, c, H)
        fwd = (win["c"][:, H] - entry) / atr_e
        row = {"horizon": H,
               "drift_atr_mean": float(np.nanmean(fwd)),
               "drift_atr_p50": _pct(fwd, 50),
               "share_up": float(np.nanmean(fwd > 0))}
        for d, nm in ((1, "long"), (-1, "short")):
            ps = path_stats(entry, atr_e, win, H, direction=d)
            row[nm] = {"mfe_p50": _pct(ps["mfe"], 50),
                       "mfe_p90": _pct(ps["mfe"], 90),
                       "mae_p50": _pct(ps["mae"], 50),
                       "mae_p90": _pct(ps["mae"], 90),
                       "p_mfe_ge_1": float((ps["mfe"] >= 1).mean()),
                       "p_mae_ge_1": float((ps["mae"] >= 1).mean())}
            r = row[nm]
            print(f"{H:>4} {nm:>6} {r['mfe_p50']:>7.2f} {r['mae_p50']:>7.2f} "
                  f"{r['p_mfe_ge_1']:>10.1%} {r['p_mae_ge_1']:>10.1%} "
                  f"{row['drift_atr_mean']:>+9.3f}")
        print(f"{'':>4} {'':>6} forward move over H bars: mean "
              f"{row['drift_atr_mean']:+.3f} ATR, "
              f"{row['share_up']:.1%} of entries up")
        path_rows.append(row)

    # ---- the bracket map ----
    grid: list[dict] = []
    for H in HORIZONS:
        win = build_windows(idx, o, h, l, c, H)   # built once per horizon
        for s in STOP_MULTS:
            for t in TP_MULTS:
                res = {}
                for d in (1, -1):
                    res[d] = (bracket_outcomes(entry, atr_e, win, s, t, H,
                                               direction=d, optimistic=False),
                              bracket_outcomes(entry, atr_e, win, s, t, H,
                                               direction=d, optimistic=True))
                (pes_l, opt_l), (pes_s, opt_s) = res[1], res[-1]
                toll = float(cost_r(pes_l["entry"], pes_l["risk"]).mean())
                gl, gs = float(pes_l["gross"].mean()), float(pes_s["gross"].mean())
                gl_o, gs_o = float(opt_l["gross"].mean()), float(opt_s["gross"].mean())
                # E_dir is the drift-neutral coin flip: the geometry's own bias.
                # E_drift is the window's directional drift, which is not an edge.
                e_dir, e_dir_opt = (gl + gs) / 2.0, (gl_o + gs_o) / 2.0
                wr = (pes_l["n_tp"] / max(1, pes_l["n"])
                      + pes_s["n_tp"] / max(1, pes_s["n"])) / 2.0
                grid.append({
                    "horizon": H, "stop_mult": s, "tp_mult": t, "rr": t / s,
                    "n": pes_l["n"],
                    "gross_dir": e_dir, "gross_dir_opt": e_dir_opt,
                    "drift": (gl - gs) / 2.0,
                    "gross_long": gl, "gross_short": gs,
                    "net_dir": e_dir - toll, "net_dir_opt": e_dir_opt - toll,
                    "win_rate_dir": wr, "breakeven_wr": s / (s + t),
                    "time_exit_share": pes_l["n_time"] / max(1, pes_l["n"]),
                    "cost_r": toll, "se_dir": block_se(pes_l["gross"], H),
                })

    for H in HORIZONS:
        print(f"\n=== HORIZON H={H} bars ({H*15/60:.0f}h) — drift-neutral coin flip, "
              f"gross R per trade ===")
        print(f"{'stop':>5} | " + " ".join(f"tp={t:<5}" for t in TP_MULTS))
        for s in STOP_MULTS:
            cells = [f"{next(x for x in grid if x['horizon'] == H and x['stop_mult'] == s and x['tp_mult'] == t)['gross_dir']:>+7.3f}"
                     for t in TP_MULTS]
            print(f"{s:>5} | " + " ".join(cells))
        print("        (E_dir = mean of long and short; negative = the bracket itself "
              "bleeds. Stop assumed first on same-bar ties.)")

    ranked = sorted(grid, key=lambda g: abs(g["gross_dir"]))
    print("\n=== FAIREST GEOMETRIES (|E_dir| under a coin flip) ===")
    print(f"{'H':>4} {'stop':>5} {'tp':>5} {'rr':>5} {'E_dir':>8} {'E_dirOpt':>9} "
          f"{'drift':>8} {'net':>8} {'win%':>6} {'be%':>6} {'time%':>6} {'se':>7}")
    for g in ranked[:12]:
        print(f"{g['horizon']:>4} {g['stop_mult']:>5} {g['tp_mult']:>5} "
              f"{g['rr']:>5.2f} {g['gross_dir']:>+8.4f} {g['gross_dir_opt']:>+9.4f} "
              f"{g['drift']:>+8.4f} {g['net_dir']:>+8.4f} {100*g['win_rate_dir']:>5.1f}% "
              f"{100*g['breakeven_wr']:>5.1f}% {100*g['time_exit_share']:>5.1f}% "
              f"{g['se_dir']:>7.4f}")

    fair = [g for g in grid if abs(g["gross_dir"]) <= 0.02]
    print(f"\n=== {len(fair)} of {len(grid)} cells are fair "
          f"(|E_dir| <= 0.02R under a coin flip) ===")
    worst = max(grid, key=lambda g: abs(g["drift"]))
    print(f"largest drift term in the grid: {worst['drift']:+.4f}R per trade "
          f"(H={worst['horizon']}, stop={worst['stop_mult']}, tp={worst['tp_mult']}) "
          f"— that is the window's direction, not a strategy's edge.")

    out = {
        "symbol": a.symbol, "timeframe": EXEC_TF,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "bars": n,
        "window": [datetime.fromtimestamp(epoch[0], timezone.utc).isoformat(),
                   datetime.fromtimestamp(epoch[-1], timezone.utc).isoformat()],
        "entry_bars": int(len(idx)),
        "session_utc": [SESSION_LO, SESSION_HI],
        "path_statistics": path_rows,
        "grid": grid,
        "cost_model": {"spread_bps": SPREAD_BPS,
                       "commission_per_lot_rt": COMMISSION_PER_LOT_RT,
                       "usd_per_unit_per_lot": USD_PER_UNIT_PER_LOT},
    }
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
