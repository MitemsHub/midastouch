#!/usr/bin/env python3
"""Session compatibility: take the snap-back only in the hours it earns. (pre-registered)

THE HYPOTHESIS, AND WHY IT IS NOT A FITTED WINDOW. The armed rule is a SNAP-BACK — a poke outside
the M15 band, entered with the H1/H4 trend. Retail gold doctrine says trade the 13:00-17:00 UTC
London-New York overlap, where spreads tighten and price expands
(arongroups.co/forex-articles/day-trading-gold-xauusd/, 2026-07-13). Expansion is exactly where a
snap-back gets run over, so the doctrine predicts our rule should be WORSE there — and MEASURED on
the venue's own bars it is: the overlap is the arm's worst bucket in both spans while the thin
pre-London hours are its best. The spread half of the doctrine does not apply to this venue at all
(the recorded spread is FLAT at 0.2 points in every hour, printed below).

The contamination is disclosed in the pre-registration (docs/SESSION_COMPAT_PREREG_20260922.md):
the per-hour numbers were read during the browser research, so this is a STABILITY CHECK on a
hypothesis with a stated mechanism, not a blind holdout. The decision rule was fixed after seeing
them and does not move. The forward record is the real arbiter.

PRE-REGISTERED PASS RULE (on the held-out window), all four required:
  1. expectancy >= +0.10R per trade
  2. closed fills >= 60
  3. zero-entry-day share <= 45%
  4. the same direction holds on `wf`
The Welch t of kept vs dropped is reported as a description, with the honest bar for a 3-look
family (~2.4), and the verdict says in words when a pass is a restriction rather than an edge.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402
from midas_decision_attribution import day_stats, needed_for_t15, t_stat  # noqa: E402

ART = Path("artifacts") / "midas_session_compat_20260922.json"
MODE = "REVERSE_DIRECTION"
#: the arm's LIVE frame (its inputs are compared against server-stamped epochs on a +2 venue).
INCUMBENT = (4, 18)
CANDIDATE = (4, 13)
LONDON_ONLY = (7, 13)
BUCKETS = [("pre-London 04-07", 4, 7), ("London 07-13", 7, 13),
           ("overlap 13-17", 13, 17), ("late 17-18", 17, 18)]
SELECT_WINDOW, TEST_WINDOW = "wf", "oos"
MIN_EXPR, MIN_FILLS, MAX_ZERO_SHARE, T_BAR = 0.10, 60, 0.45, 2.4


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
        raise SystemExit("REFUSING: the pinned venue-corpus law did not reproduce "
                         "(n=56 / +15.9352R expected). Every number below would be a lookalike.")
    print("            reproduced the pin -> the arithmetic below is the engine of record's.\n")


def welch(a: list[float], b: list[float]):
    if len(a) < 2 or len(b) < 2:
        return None, None
    ma, mb = statistics.mean(a), statistics.mean(b)
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    return (ma - mb, (ma - mb) / se if se > 0 else None)


def spread_by_hour(m15: list[dict]) -> dict[int, float]:
    """The venue's OWN spread column by UTC hour — the claim the doctrine rests on, measured."""
    by = {}
    for b in m15:
        h = datetime.fromtimestamp(b["time"], tz=timezone.utc).hour
        by.setdefault(h, []).append(b["spread"])
    return {h: statistics.median(v) for h, v in by.items() if v}


def main() -> int:
    self_check()
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    out: dict = {"harness": "midas_session_compat.py",
                 "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "prereg": "docs/SESSION_COMPAT_PREREG_20260922.md",
                 "mode": MODE, "incumbent_utc": INCUMBENT, "candidate_utc": CANDIDATE,
                 "family_size": 3, "t_bar": T_BAR,
                 "pass_rule": {"min_expR": MIN_EXPR, "min_fills": MIN_FILLS,
                               "max_zero_day_share": MAX_ZERO_SHARE,
                               "same_direction_on_wf": True},
                 "windows": {}}
    try:
        for wname in (SELECT_WINDOW, TEST_WINDOW):
            spec = P._window_spec(wname)
            data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
            t0, t1 = spec["t0"], spec["t1"]
            spread = spread_by_hour(data["m15"])
            rows = {}
            for label, (lo, hi) in (("incumbent", INCUMBENT), ("DROP-OVERLAP", CANDIDATE),
                                    ("LONDON-ONLY", LONDON_ONLY)):
                tr = M.run_mode(MODE, t0, t1, data, win_lo=lo, win_hi=hi).trades
                rs = [t["r"] for t in tr]
                rows[label] = {
                    "win_utc": [lo, hi], "n": len(rs),
                    "expR": round(statistics.mean(rs), 4) if rs else None,
                    "totalR": round(sum(rs), 4) if rs else None,
                    "t": t_stat(rs), "n_needed_for_t15": needed_for_t15(rs),
                    **day_stats(tr, t0, t1),
                }
            inc = M.run_mode(MODE, t0, t1, data,
                             win_lo=INCUMBENT[0], win_hi=INCUMBENT[1]).trades
            cand = M.run_mode(MODE, t0, t1, data,
                              win_lo=CANDIDATE[0], win_hi=CANDIDATE[1]).trades
            kept = [t["r"] for t in cand]
            dropped_ct = {int(t["open_ct"]) for t in inc} - {int(t["open_ct"]) for t in cand}
            dropped = [t["r"] for t in inc if int(t["open_ct"]) in dropped_ct]
            diff, wt = welch(kept, dropped)
            buckets = {}
            for name, a, z in BUCKETS:
                sub = [t["r"] for t in inc if a <= int(t["hour"]) < z]
                buckets[name] = {"n": len(sub),
                                 "expR": round(statistics.mean(sub), 4) if len(sub) > 1 else None,
                                 "totalR": round(sum(sub), 4),
                                 "t": t_stat(sub),
                                 "median_spread_pts": round(statistics.median(
                                     [spread[h] for h in range(a, z) if h in spread]), 2)
                                 if any(h in spread for h in range(a, z)) else None}
            out["windows"][wname] = {
                "t0": t0, "t1": t1, "server_offset_min": P.assert_server_offset(spec),
                "spread_pts_by_hour_utc": {str(h): spread[h] for h in sorted(spread)},
                "buckets": buckets, "candidates": rows,
                "kept_vs_dropped": {"kept_n": len(kept), "dropped_n": len(dropped),
                                    "diff_expR": None if diff is None else round(diff, 4),
                                    "welch_t": None if wt is None else round(wt, 3),
                                    "dropped_totalR": round(sum(dropped), 4)}}
    finally:
        M._BASIS = prev

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")

    for wname in (SELECT_WINDOW, TEST_WINDOW):
        w = out["windows"][wname]
        print(f"=== {wname}   armed mode, buckets inside its live frame (UTC 04-18)")
        print(f"  {'bucket':18s} {'n':>4s} {'expR':>9s} {'totalR':>9s} {'t':>7s} {'spread':>8s}")
        for name, b in w["buckets"].items():
            e = "  n/a" if b["expR"] is None else f"{b['expR']:+.4f}"
            print(f"  {name:18s} {b['n']:4d} {e:>9s} {b['totalR']:+9.2f} "
                  f"{(b['t'] if b['t'] is not None else float('nan')):+7.2f} "
                  f"{(b['median_spread_pts'] if b['median_spread_pts'] is not None else float('nan')):8.2f}")
        print(f"  {'-- candidate windows':18s}")
        for label, r in w["candidates"].items():
            e = "  n/a" if r["expR"] is None else f"{r['expR']:+.4f}"
            print(f"  {label:18s} {r['n']:4d} {e:>9s} {r['totalR']:+9.2f} "
                  f"{(r['t'] if r['t'] is not None else float('nan')):+7.2f}   "
                  f"zero-days {r['zero_day_share']:.1%}  /day {r['per_day']}")
        kd = w["kept_vs_dropped"]
        print(f"  kept {kd['kept_n']} vs dropped {kd['dropped_n']}: diff {kd['diff_expR']:+}R, "
              f"Welch t {kd['welch_t']}, dropped contributed {kd['dropped_totalR']:+.2f}R")
        print()

    t = out["windows"][TEST_WINDOW]
    cand, inc = t["candidates"]["DROP-OVERLAP"], t["candidates"]["incumbent"]
    wf = out["windows"][SELECT_WINDOW]
    checks = {
        f"expR >= {MIN_EXPR}": (cand["expR"] or 0) >= MIN_EXPR,
        f"fills >= {MIN_FILLS}": cand["n"] >= MIN_FILLS,
        f"zero-day share <= {MAX_ZERO_SHARE:.0%}": cand["zero_day_share"] <= MAX_ZERO_SHARE,
        "same direction on wf": (cand["expR"] is not None and wf["candidates"]["DROP-OVERLAP"]["expR"]
                                 is not None
                                 and wf["candidates"]["DROP-OVERLAP"]["expR"] >= inc["expR"]),
    }
    print("PASS RULE — DROP-OVERLAP (UTC 04-13) vs the incumbent (04-18), held out:")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    verdict = "PASS" if all(checks.values()) else "FAIL"
    print(f"  verdict: {verdict}")
    if verdict == "PASS":
        wt = t["kept_vs_dropped"]["welch_t"]
        print(f"  NOTE: the kept-vs-dropped contrast is Welch t = {wt} against a {T_BAR} bar for a "
              f"{out['family_size']}-look family — this is a RESTRICTION consistent with both spans "
              f"and with a mechanism, not a demonstrated edge. The forward record decides.")
    out["verdict"] = verdict
    out["checks"] = {k: bool(v) for k, v in checks.items()}
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nartifact: {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
