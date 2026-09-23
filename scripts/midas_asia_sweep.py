#!/usr/bin/env python3
"""The Asian-range sweep as a second setup family, aimed at the hours the snap-back loses in.

WHY. Step 1 (docs/SESSION_COMPAT_PREREG_20260922.md) measured the armed snap-back earning -0.0949R
in the 13:00-17:00 UTC overlap and -0.0801R in the late tail, on a venue whose spread is FLAT at
0.19-0.23 points in every hour. The hours are not expensive; the RULE is wrong for them: the overlap
is where gold expands, and expansion runs a snap-back over. So the fix is a continuation setup for
those hours rather than a narrower window.

EXTERNAL SUPPORT. A 2026 preprint series (reconciled in docs/EXTERNAL_LITERATURE_RECONCILIATION_
20260922.md) put six mechanically-defined ICT/SMC rules through a full stack and found THREE
independently built liquidity-sweep mechanisms - equal highs/lows, order blocks, and ASIAN SESSION
RANGES - agreeing across 65 of 66 fold-selections that a swept level predicts CONTINUATION, while a
fourth found the textbook reversal read should be FADED. That is the literature's most corroborated
positive, and it is a continuation family.

DEFINITIONS (fixed in the pre-registration, deterministic):
  * Asian range for a UTC day = high/low of the venue's own M15 bars opening 00:00-06:45 UTC;
  * sweep  = the first bar at/after 07:00 UTC trading beyond that range (one signal per day per side);
  * reclaim = a bar trading beyond the range AND closing back inside it.
Variants: SWEEP_CONT (with the break) | SWEEP_FADE (against) | RECLAIM_REV (against, the textbook
reading - included as a direction check: the literature says this one runs backwards).

THE ENGINE IS UNCHANGED: `midas_sweep.run_mode` with the variant supplied as `data["m15_bb"]`, mode
TRIGGER_ONLY, every other keyword at its certified default. Bar i's high/close sets arr[i], and the
engine fills at bar i+1's open - the same convention every other trigger uses, so there is no
lookahead (see tests/test_asia_sweep.py).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402
from midas_decision_attribution import day_stats, needed_for_t15, t_stat  # noqa: E402

ART = Path("artifacts") / "midas_asia_sweep_20260922.json"
# THE MECHANISM MOVED INTO THE ENGINE MODULE 2026-09-22, and this harness now imports it.
# `asian_ranges` / `build_signals` were defined here and called once; the forward shadow
# recorder is the second caller, and two copies of a mechanism is how a program certifies
# one rule while recording another. `build_signals` is kept as the name this harness and the
# published artifact were written against; the definition is `M.sweep_signals`.
VARIANTS = M.SWEEP_VARIANTS
RANGE_HOURS = M.ASIAN_RANGE_HOURS
PRIMARY = (13, 18)                 # the hours the snap-back loses in
SECONDARY = M.SWEEP_WINDOW         # every hour after the range is known (descriptive)
SELECT_WINDOW, TEST_WINDOW = "wf", "oos"
T_BAR, MIN_TRADES, MIN_PER_DAY = 2.4, 30, 0.30

asian_ranges = M.asian_ranges
build_signals = M.sweep_signals


def self_check() -> None:
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    finally:
        M._BASIS = prev
    n, tot = len(rr.trades), sum(t["r"] for t in rr.trades)
    print(f"self-check  wfv {spec['mode']}: n={n} totalR={tot:+.4f} vetoed={rr.vetoed}")
    if n != 56 or abs(tot - 15.9352) >= 5e-4:
        raise SystemExit("REFUSING: the pinned venue-corpus law did not reproduce. "
                         "Every number below would be a lookalike.")
    print("            reproduced the pin -> the arithmetic below is the engine of record's.\n")


def summarise(trades: list[dict], t0: int, t1: int) -> dict:
    rs = [t["r"] for t in trades]
    m = M.metrics(trades)
    return {**{k: m.get(k) for k in ("n", "net_r", "expectancy_r", "pf", "win_rate", "max_dd_r")},
            "t": t_stat(rs), "n_needed_for_t15": needed_for_t15(rs), **day_stats(trades, t0, t1)}


def main() -> int:
    self_check()
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    out: dict = {"harness": "midas_asia_sweep.py",
                 "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "prereg": "docs/ASIA_SWEEP_PREREG_20260922.md",
                 "variants": list(VARIANTS), "family_size": len(VARIANTS), "t_bar": T_BAR,
                 "primary_utc": list(PRIMARY), "secondary_utc": list(SECONDARY),
                 "pass_rule": {"t": T_BAR, "min_trades": MIN_TRADES, "min_per_day": MIN_PER_DAY,
                               "same_sign_on_wf": True},
                 "windows": {}}
    try:
        for wname in (SELECT_WINDOW, TEST_WINDOW):
            spec = P._window_spec(wname)
            data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
            sig = build_signals(data["m15"])
            t0, t1 = spec["t0"], spec["t1"]
            res = {}
            for variant, arr in sig.items():
                for label, (lo, hi) in (("primary", PRIMARY), ("secondary", SECONDARY)):
                    d2 = {**data, "m15_bb": arr}
                    rr = M.run_mode("TRIGGER_ONLY", t0, t1, d2, win_lo=lo, win_hi=hi)
                    res[f"{variant}|{label}"] = {**summarise(rr.trades, t0, t1),
                                                 "vetoed": rr.vetoed,
                                                 "signal_bars": sum(1 for x in arr if x != 0)}
            out["windows"][wname] = {"t0": t0, "t1": t1,
                                     "server_offset_min": P.assert_server_offset(spec),
                                     "asian_range_days": len(asian_ranges(data["m15"])),
                                     "results": res}
    finally:
        M._BASIS = prev

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")

    for wname in (SELECT_WINDOW, TEST_WINDOW):
        w = out["windows"][wname]
        print(f"=== {wname}   {w['asian_range_days']} Asian ranges built "
              f"(primary window UTC {PRIMARY[0]}-{PRIMARY[1]}, secondary {SECONDARY[0]}-{SECONDARY[1]})")
        print(f"  {'variant|window':28s} {'sig':>5s} {'n':>4s} {'/day':>6s} {'zero%':>6s} "
              f"{'expR':>8s} {'pf':>6s} {'win':>6s} {'ddR':>6s} {'t':>6s} {'n@t1.5':>8s}")
        for key, r in w["results"].items():
            e = "  n/a" if r["expectancy_r"] is None else f"{r['expectancy_r']:+.4f}"
            print(f"  {key:28s} {r['signal_bars']:5d} {r['n']:4d} {r['per_day']:6.2f} "
                  f"{r['zero_day_share']:6.1%} {e:>8s} "
                  f"{(r['pf'] if r['pf'] is not None else float('nan')):6.3f} "
                  f"{(r['win_rate'] if r['win_rate'] is not None else float('nan')):6.3f} "
                  f"{(r['max_dd_r'] if r['max_dd_r'] is not None else float('nan')):6.1f} "
                  f"{(r['t'] if r['t'] is not None else float('nan')):6.2f} "
                  f"{(r['n_needed_for_t15'] if r['n_needed_for_t15'] is not None else -1):8d}")
        print()

    t = out["windows"][TEST_WINDOW]["results"]
    wf = out["windows"][SELECT_WINDOW]["results"]
    verdicts = {}
    for v in VARIANTS:
        r = t[f"{v}|primary"]
        w = wf[f"{v}|primary"]
        why = []
        if r["n"] < MIN_TRADES:
            why.append(f"n={r['n']} < {MIN_TRADES}")
        if r["per_day"] < MIN_PER_DAY:
            why.append(f"fills/day={r['per_day']} < {MIN_PER_DAY}")
        if r["t"] is None or r["t"] < T_BAR:
            why.append(f"t={r['t']} < {T_BAR}")
        if (r["expectancy_r"] or 0) <= 0 or (w["expectancy_r"] or 0) <= 0:
            why.append(f"sign not positive in both spans (wf {w['expectancy_r']}, "
                       f"oos {r['expectancy_r']})")
        verdicts[v] = "PASS" if not why else "FAIL: " + "; ".join(why)
    print("PASS RULE — primary window (UTC 13-18), held out:")
    for v, verdict in verdicts.items():
        print(f"  {v:12s} {verdict}")
    out["verdicts"] = verdicts
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nartifact: {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
