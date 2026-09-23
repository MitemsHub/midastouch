#!/usr/bin/env python3
"""Cross-asset structural divergence: gold vs AUD, on the venue's own bars (pre-registered).

THE HYPOTHESIS, AND WHERE IT COMES FROM. This is the first signal in this program that does not
come from gold's own price history. An external 2026 ten-paper series — which found ZERO surviving
retail rule families in 45 combinations and ZERO surviving momentum/breakout combinations in ~46 —
reports its strongest single result as comparing GOLD's swing structure against the AUSTRALIAN
DOLLAR's: clearing permutation significance, achieving that program's maximum post-correction
Deflated Sharpe, holding on a locked holdout, and surviving a 100x cost increase, while failing its
walk-forward-efficiency gate and resting on a short history. See
docs/EXTERNAL_LITERATURE_RECONCILIATION_20260922.md. Our own audit independently says the bind is
data and that the one direction worth testing is one that adds INFORMATION rather than parameters.

NON-REPAINTING BY CONSTRUCTION, which is the whole discipline of a structural signal:

  * a swing high at H1 bar i needs high[i] > high[i-1] and high[i] > high[i+1] and
    high[i] > high[i+2], so it is CONFIRMED only at the CLOSE of bar i+2;
  * the structure direction at any moment uses only swings confirmed at or before that moment;
  * a gold M15 bar closing at ct sees only H1 bars whose CLOSE is <= ct (bisect_right on the
    close-time array — the same rule `run_mode` uses for its own macro state).
  `test_cross_asset.py` asserts each of those three, because a repainting structural signal is the
  one thing this whole exercise cannot afford.

THE ENGINE IS UNCHANGED. `midas_sweep.run_mode` is called with every keyword at its certified
default; the variant's signal is supplied as `data["m15_bb"]`, the array the engine already reads
its trigger from (the same mechanism the frequency-axes study used to sweep the threshold). Mode
`TRIGGER_ONLY`, so the macro gate is NOT applied: the signal is tested on its own.

PRE-REGISTERED in docs/CROSS_ASSET_DIVERGENCE_PREREG_20260922.md before the run. A variant passes
only if, on the held-out window, t >= 2.4 (the 95th-percentile max-|z| for a 3-variant family),
n >= 30, and fills/day >= 0.30.
"""
from __future__ import annotations

import json
import os
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402
from midas_decision_attribution import day_stats, needed_for_t15, t_stat  # noqa: E402

ART = Path("artifacts") / "midas_cross_asset_20260922.json"
CONTEXT_FILE = "AUDUSD_H1"   # the loader's own stem convention: `<SYMBOL>_<TF>` + VENUE_M15_SUFFIX
SWING_BACK, SWING_FWD = 1, 2          # declared, never swept (see the pre-registration)
SELECT_WINDOW, TEST_WINDOW = "wf", "oos"
T_THRESHOLD = 2.4                     # 95th pct of max|z| for a 3-variant family
MIN_TRADES, MIN_PER_DAY = 30, 0.30
INCUMBENT_OOS = {"mode": "REVERSE_DIRECTION", "expectancy_r": 0.0355, "n": 127,
                 "per_day": 0.75, "max_dd_r": 6.3}


def context_bars(stem: str, offset_min: int) -> tuple[list[dict], list[int]]:
    """The venue's own series for `stem`, shifted from server time to true UTC.

    Same convention as `midas_parity.venue_bars_utc` (which is gold-only by its own signature), so
    the context series is read exactly as the traded one is: the terminal's clock, minus the
    window's pinned offset.
    """
    path = os.path.join(M.DATA_DIR, f"{stem}{P.VENUE_M15_SUFFIX}.csv")
    if not os.path.isfile(path):
        raise SystemExit(f"no context series at {path} — fetch it: "
                         f"python scripts/midas_fetch_history.py --symbols {stem} --suffix _upcomers")
    shift = offset_min * 60
    bars = M.load_bars(path)
    # CLOSE times, not opens, and this is not cosmetic. `data["h1_ct"]` (which the gold leg uses)
    # is the array run_mode bisects to find "the H1 bar that had CLOSED by ct", and
    # `confirmed_swings` stamps a swing at `times[i + SWING_FWD]`. Handing it a bar's OPEN time
    # would let a signal at time t use a swing that depends on bar t's high — one full H1 bar of
    # lookahead, in the one kind of signal where repainting is the whole discipline.
    times = [b["time"] - shift + 3600 for b in bars]
    return bars, times


def confirmed_swings(highs: list[float], lows: list[float], times: list[int]) -> dict:
    """Swing highs/lows with the bar at which each becomes KNOWN.

    Returns {'sh': [(confirm_time, level)], 'sl': [...]} — append-only, in confirmation order.
    """
    sh, sl = [], []
    for i in range(SWING_BACK, len(times) - SWING_FWD):
        h, lo = highs[i], lows[i]
        if all(h > highs[i - j] for j in range(1, SWING_BACK + 1)) and \
           all(h > highs[i + j] for j in range(1, SWING_FWD + 1)):
            sh.append((times[i + SWING_FWD], h))
        if all(lo < lows[i - j] for j in range(1, SWING_BACK + 1)) and \
           all(lo < lows[i + j] for j in range(1, SWING_FWD + 1)):
            sl.append((times[i + SWING_FWD], lo))
    return {"sh": sh, "sl": sl}


def direction_at(sw: dict, ct: int) -> int:
    """Structure direction from ONLY the swings confirmed at or before `ct`.

    +1 higher highs AND higher lows · -1 lower highs AND lower lows · 0 otherwise (including
    'fewer than two confirmed swings yet'). The bisect is the anti-repainting rule in one line.
    """
    def last_two(seq):
        k = bisect_right([t for t, _ in seq], ct)
        return seq[k - 2:k] if k >= 2 else []
    hi, lo = last_two(sw["sh"]), last_two(sw["sl"])
    if len(hi) < 2 or len(lo) < 2:
        return 0
    if hi[1][1] > hi[0][1] and lo[1][1] > lo[0][1]:
        return 1
    if hi[1][1] < hi[0][1] and lo[1][1] < lo[0][1]:
        return -1
    return 0


def build_signals(gold_h1: list[dict], gold_h1_ct: list[int], gold_m15: list[dict],
                  ctx_h1: list[dict], ctx_ct: list[int]) -> dict:
    """The three variant arrays, one entry per gold M15 bar (the engine's own indexing)."""
    gold_sw = confirmed_swings([b["high"] for b in gold_h1], [b["low"] for b in gold_h1], gold_h1_ct)
    ctx_sw = confirmed_swings([b["high"] for b in ctx_h1], [b["low"] for b in ctx_h1], ctx_ct)
    out = {"DIVERGE": [], "FADE": [], "ALIGN": []}
    meta = []
    for b in gold_m15:
        ct = b["time"] + 900                      # the signal bar's CLOSE, as run_mode defines it
        gd = direction_at(gold_sw, ct)
        ad = direction_at(ctx_sw, ct)
        diverge = gd != 0 and ad != 0 and gd != ad
        align = gd != 0 and ad != 0 and gd == ad
        out["DIVERGE"].append(gd if diverge else 0)
        out["FADE"].append(-gd if diverge else 0)
        out["ALIGN"].append(gd if align else 0)
        meta.append({"ct": ct, "gold_dir": gd, "ctx_dir": ad,
                     "diverge": diverge, "align": align})
    out["_meta"] = meta
    return out


def summarise(trades: list[dict], t0: int, t1: int) -> dict:
    m = M.metrics(trades)
    rs = [t["r"] for t in trades]
    return {**{k: m.get(k) for k in ("n", "net_r", "expectancy_r", "pf", "win_rate", "max_dd_r")},
            "t": t_stat(rs), "n_needed_for_t15": needed_for_t15(rs),
            **day_stats(trades, t0, t1)}


def main() -> int:
    spec_pin = P._window_spec("wfv")
    pin = P.python_build_data(offset_min=P.assert_server_offset(spec_pin), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode(spec_pin["mode"], spec_pin["t0"], spec_pin["t1"], pin)
    finally:
        M._BASIS = prev
    n0, tot0 = len(rr.trades), sum(t["r"] for t in rr.trades)
    print(f"self-check  wfv {spec_pin['mode']}: n={n0} totalR={tot0:+.4f} vetoed={rr.vetoed}")
    if n0 != 56 or abs(tot0 - 15.9352) >= 5e-4:
        raise SystemExit("REFUSING: the pinned venue-corpus law did not reproduce "
                         "(expected n=56 / +15.9352R). Every number below would be a lookalike.")
    print("            reproduced the pin -> the arithmetic below is the engine of record's.\n")

    result: dict = {"harness": "midas_cross_asset.py",
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "prereg": "docs/CROSS_ASSET_DIVERGENCE_PREREG_20260922.md",
                    "engine": "midas_sweep.run_mode (unchanged) with data['m15_bb'] = the variant",
                    "context_symbol": CONTEXT_FILE, "swing": {"back": SWING_BACK, "fwd": SWING_FWD},
                    "pass_rule": {"t": T_THRESHOLD, "min_trades": MIN_TRADES, "min_per_day": MIN_PER_DAY},
                    "incumbent_oos_for_comparison": INCUMBENT_OOS, "windows": {}}
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        for wname in (SELECT_WINDOW, TEST_WINDOW):
            spec = P._window_spec(wname)
            off = P.assert_server_offset(spec)
            data = P.python_build_data(offset_min=off, corpus="venue")
            ctx_h1, ctx_ct = context_bars(CONTEXT_FILE, off)
            sig = build_signals(data["h1"], data["h1_ct"], data["m15"], ctx_h1, ctx_ct)
            meta = sig.pop("_meta")
            t0, t1 = spec["t0"], spec["t1"]

            rows = {}
            # the incumbent, for scale: same window, same geometry, its own signal
            base = M.run_mode("REVERSE_DIRECTION", t0, t1, data)
            rows["REVERSE_DIRECTION (armed, baseline)"] = summarise(base.trades, t0, t1)
            for name, arr in sig.items():
                d2 = {**data, "m15_bb": arr}
                res = M.run_mode("TRIGGER_ONLY", t0, t1, d2)
                rows[name] = {**summarise(res.trades, t0, t1), "vetoed": res.vetoed}

            # WINDOW-SCOPED, or the same corpus-wide counts would print twice and read as two
            # measurements. `in_meta` applies `run_mode`'s own window test (close > t0, open <= t1).
            in_meta = [m for m, b in zip(meta, data["m15"]) if m["ct"] > t0 and b["time"] <= t1]
            result["windows"][wname] = {
                "t0": t0, "t1": t1, "server_offset_min": off,
                "bars": len(in_meta), "bars_in_corpus": len(meta),
                "signal_counts": {
                    "diverge": sum(1 for m in in_meta if m["diverge"]),
                    "align": sum(1 for m in in_meta if m["align"]),
                    "gold_dir_nonzero": sum(1 for m in in_meta if m["gold_dir"] != 0),
                    "ctx_dir_nonzero": sum(1 for m in in_meta if m["ctx_dir"] != 0),
                },
                "modes": rows}
    finally:
        M._BASIS = prev

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(result, indent=1), encoding="utf-8")

    verdicts = {}
    for wname in (SELECT_WINDOW, TEST_WINDOW):
        w = result["windows"][wname]
        print(f"=== {wname}  {w['bars']} M15 bars, offset {w['server_offset_min']:+d} min")
        sc = w["signal_counts"]
        print(f"  signal bars: divergent {sc['diverge']} ({sc['diverge']/w['bars']:.2%}), "
              f"aligned {sc['align']}  |  gold structure non-zero {sc['gold_dir_nonzero']}, "
              f"AUD {sc['ctx_dir_nonzero']}")
        print(f"  {'variant':34s} {'n':>4s} {'/day':>6s} {'zero%':>6s} {'expR':>8s} "
              f"{'pf':>6s} {'win':>6s} {'ddR':>6s} {'t':>6s} {'n@t1.5':>8s}")
        for name, r in w["modes"].items():
            def f(x, d=3):
                return "  n/a" if x is None else f"{x:.{d}f}"
            print(f"  {name:34s} {r['n']:4d} {r['per_day']:6.2f} {r['zero_day_share']:6.1%} "
                  f"{f(r['expectancy_r'],4):>8s} {f(r['pf']):>6s} {f(r['win_rate']):>6s} "
                  f"{f(r['max_dd_r'],1):>6s} {f(r['t'],2):>6s} "
                  f"{(r['n_needed_for_t15'] if r['n_needed_for_t15'] is not None else -1):>8d}")
        if wname == TEST_WINDOW:
            print("\n  PASS RULE on the held-out window (t >= 2.4, n >= 30, fills/day >= 0.30):")
            for name in ("DIVERGE", "FADE", "ALIGN"):
                r = w["modes"][name]
                why = []
                if r["n"] < MIN_TRADES:
                    why.append(f"n={r['n']} < {MIN_TRADES}")
                if r["per_day"] < MIN_PER_DAY:
                    why.append(f"fills/day={r['per_day']} < {MIN_PER_DAY}")
                if r["t"] is None or r["t"] < T_THRESHOLD:
                    why.append(f"t={r['t']} < {T_THRESHOLD}")
                verdicts[name] = "PASS" if not why else "FAIL: " + "; ".join(why)
                print(f"    {name:8s} {verdicts[name]}")
        print()
    result["verdicts"] = verdicts
    ART.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"artifact: {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
