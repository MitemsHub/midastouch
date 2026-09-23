#!/usr/bin/env python3
"""Market intraday momentum on gold, aimed at the hours the armed fade cannot join.

WHY. `docs/MIM_PREREG_20260922.md` was written first, and fixes the mechanism, the spans,
the pass rule, and the verdict wording. The operator's complaint (the arm declining a
visible recovery) is real but structural: the armed mode is a fade of extremes; the missing
basket is a with-trend family with published OOS evidence. MIM (Gao, Han, Li & Zhou, JFE
2018; replicated on commodity ETFs and Chinese futures) is the literature's with-trend
intraday family: the same asset's first half of the session predicts its second half.

THE ENGINE IS UNCHANGED. Signals ride `midas_sweep.run_mode` as `m15_bb`, mode
TRIGGER_ONLY, every geometry keyword at its certified default (2.0xATR-H1 stop, 2R target,
48-bar timeout, half-spread both sides), session window at the armed 04-18 UTC. The signal
array is nonzero ONLY on the 10:45Z bar of each day — one decision per day, made at that
bar's close, filled at the 11:00Z bar's open (the engine's signal-bar -> next-bar-open
convention, so there is no lookahead). `MOM_*` trades with r1's sign; `REV_*` against it.

DEFINITIONS (from the pre-registration, verbatim):
  r1 = close(bar opening 10:45Z) - open(bar opening 04:00Z)
  r2 = close(bar opening 17:45Z) - open(bar opening 11:00Z)     [descriptive only]
  thr = c * wilder_atr(H1, 14) at the decision bar, c in {0.0, 0.25, 0.50}
  signal = sign(r1) if |r1| > thr else 0   (at |r1| == thr exactly: no trade)
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

ART = Path("artifacts") / "midas_mim_20260922.json"
PREREG = "docs/MIM_PREREG_20260922.md"
DECISION_UTC = 10          # the 10:45Z bar opens in hour 10
SELECT_WINDOW, TEST_WINDOW = "wf", "oos"
T_BAR, MIN_TRADES, MIN_PER_DAY = 2.4, 30, 0.30
THRESHOLDS = (0.0, 0.25, 0.50)

asian_ranges = M.asian_ranges  # re-exported name parity with the sweep harness


def self_check() -> None:
    """The pinned venue-corpus law, before any MIM number is computed."""
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    finally:
        M._BASIS = prev
    n, tot = len(rr.trades), sum(t["r"] for t in rr.trades)
    print(f"self-check  wfv {spec['mode']}: n={n} totalR={tot:+.4f}")
    if n != 56 or abs(tot - 15.9352) >= 5e-4:
        raise SystemExit("REFUSING: the pinned venue-corpus law did not reproduce. "
                         "Every number below would be a lookalike.")
    print("            reproduced the pin -> the arithmetic below is the engine of record's.\n")


def day_groups(m15: list[dict]) -> dict[int, list[dict]]:
    """This venue's UTC day: bars 00:00-23:59Z (the daily break falls outside by construction)."""
    groups: dict[int, list[dict]] = {}
    for b in m15:
        d = datetime.fromtimestamp(b["time"], tz=timezone.utc).date()
        groups.setdefault(d.toordinal(), []).append(b)
    return groups


def mim_signals(m15: list[dict], h1: list[dict]) -> dict[str, list[int]]:
    """The 6 signal arrays over the whole series: 3 thresholds x {MOM, REV}.

    For each UTC day present in the m15 series: r1 from that day's 04:00Z bar's open to
    that day's 10:45Z bar's close; ATR14(H1, Wilder) read at the decision bar's index on
    the H1 series (closed H1 bars only, as the engine reads it); signal placed on the
    10:45Z bar. Days missing either anchor bar get NO signal (no guessed fill).
    """
    atr = M.wilder_atr(h1, 14)
    h1_open = {b["time"]: i for i, b in enumerate(h1)}
    arrs = {f"MOM_{c}": [0] * len(m15) for c in THRESHOLDS}
    arrs.update({f"REV_{c}": [0] * len(m15) for c in THRESHOLDS})

    day0 = min(datetime.fromtimestamp(b["time"], tz=timezone.utc).date().toordinal()
               for b in m15)
    for dkey, bars in day_groups(m15).items():
        if dkey == day0:  # the first day can lack the 04:00 anchor; skip rather than guess
            continue
        by_min = {(datetime.fromtimestamp(b["time"], tz=timezone.utc).hour,
                   datetime.fromtimestamp(b["time"], tz=timezone.utc).minute): b
                  for b in bars}
        b0, bd = by_min.get((4, 0)), by_min.get((10, 45))
        if b0 is None or bd is None:
            continue
        r1 = bd["close"] - b0["open"]
        if r1 == 0:
            continue
        # ATR read on the last H1 bar CLOSED before the decision. The decision happens at
        # the 10:45Z bar's close; the 10:00Z H1 bar closes at 11:00Z — one tick too late —
        # so the newest admissible bar is the 09:00Z one (closed 10:00Z). Closed bars only,
        # the engine's own convention; reading the 10:00Z bar would be lookahead on thr.
        h1_cut = bd["time"] - 3600
        idxs = [i for t, i in h1_open.items() if t <= h1_cut]
        if not idxs:
            continue
        atr_here = atr[max(idxs)]
        if atr_here is None or atr_here <= 0:
            continue
        i = m15.index(bd)
        for c in THRESHOLDS:
            if abs(r1) > c * atr_here:
                arrs[f"MOM_{c}"][i] = 1 if r1 > 0 else -1
                arrs[f"REV_{c}"][i] = -1 if r1 > 0 else 1
    return arrs


def predictability(m15: list[dict], t0: int, t1: int) -> dict:
    """The descriptive regression r2 = a + b*r1 (§3 of the pre-reg), plus sign contingency."""
    pairs: list[tuple[float, float]] = []
    for dkey, bars in day_groups([b for b in m15 if t0 <= b["time"] < t1]).items():
        by_min = {(datetime.fromtimestamp(b["time"], tz=timezone.utc).hour,
                   datetime.fromtimestamp(b["time"], tz=timezone.utc).minute): b
                  for b in bars}
        b0, bd, be = (by_min.get((4, 0)), by_min.get((10, 45)), by_min.get((17, 45)))
        if not (b0 and bd and be):
            continue
        r1 = bd["close"] - b0["open"]
        r2 = be["close"] - (by_min.get((11, 0)) or bd)["open"]
        pairs.append((r1, r2))
    n = len(pairs)
    if n < 3:
        return {"n_days": n}
    xs = [a for a, _ in pairs]
    ys = [b for _, b in pairs]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    b = sxy / sxx if sxx else 0.0
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in pairs]
    sxx_r = sum((x - mx) ** 2 for x in xs)
    se_b = (sum(e * e for e in resid) / (n - 2) / sxx_r) ** 0.5 if sxx_r and n > 2 else None
    agree = sum(1 for x, y in pairs if (x > 0) == (y > 0))
    return {"n_days": n, "beta": round(b, 4), "alpha": round(a, 4),
            "t_beta": round(b / se_b, 3) if se_b else None,
            "sign_agree_share": round(agree / n, 4)}


def summarise(trades: list[dict], t0: int, t1: int) -> dict:
    rs = [t["r"] for t in trades]
    m = M.metrics(trades)
    return {**{k: m.get(k) for k in ("n", "net_r", "expectancy_r", "pf", "win_rate",
                                     "max_dd_r")},
            "t": t_stat(rs), "n_needed_for_t15": needed_for_t15(rs),
            **day_stats(trades, t0, t1)}


def main() -> int:
    self_check()
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    out: dict = {"harness": "midas_mim.py", "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "prereg": PREREG, "thresholds": list(THRESHOLDS),
                 "family_size": 2 * len(THRESHOLDS),
                 "t_bar": T_BAR, "min_trades": MIN_TRADES, "min_per_day": MIN_PER_DAY,
                 "primary_cell": "MOM_0.0", "pass_rule": {
                     "primary_cell_must_clear": True,
                     "t": T_BAR, "min_trades": MIN_TRADES, "min_per_day": MIN_PER_DAY,
                     "same_sign_on_wf": True,
                     "no_REV_beats_its_MOM_on_oos": True},
                 "windows": {}}
    try:
        for wname in (SELECT_WINDOW, TEST_WINDOW):
            spec = P._window_spec(wname)
            off = P.assert_server_offset(spec)
            data = P.python_build_data(offset_min=off, corpus="venue")
            m15, h1 = data["m15"], data["h1"]
            t0, t1 = spec["t0"], spec["t1"]
            sig = mim_signals(m15, h1)
            res: dict = {}
            for name, arr in sig.items():
                d2 = {**data, "m15_bb": arr}
                rr = M.run_mode("TRIGGER_ONLY", t0, t1, d2)
                res[name] = {**summarise(rr.trades, t0, t1), "vetoed": rr.vetoed,
                             "signal_bars": sum(1 for x in arr if x != 0)}
            out["windows"][wname] = {"t0": t0, "t1": t1, "server_offset_min": off,
                                     "predictability": predictability(m15, t0, t1),
                                     "results": res}
    finally:
        M._BASIS = prev

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")

    # ── the report ──────────────────────────────────────────────────────────────────────
    for wname in (SELECT_WINDOW, TEST_WINDOW):
        w = out["windows"][wname]
        p = w["predictability"]
        print(f"=== {wname}  t0={w['t0']} t1={w['t1']}")
        if p.get("n_days"):
            print(f"  predictability: n_days={p['n_days']} beta={p['beta']} "
                  f"t_beta={p.get('t_beta')} sign_agree={p.get('sign_agree_share')}")
        print(f"  {'cell':10s} {'sig':>5s} {'n':>4s} {'/day':>6s} {'zero%':>6s} "
              f"{'expR':>8s} {'pf':>6s} {'win':>6s} {'ddR':>6s} {'t':>6s} {'n@t1.5':>8s}")
        for name, r in w["results"].items():
            e = "  n/a" if r["expectancy_r"] is None else f"{r['expectancy_r']:+.4f}"
            print(f"  {name:10s} {r['signal_bars']:5d} {r['n']:4d} {r['per_day']:6.2f} "
                  f"{r['zero_day_share']:6.1%} {e:>8s} "
                  f"{(r['pf'] if r['pf'] is not None else float('nan')):6.3f} "
                  f"{(r['win_rate'] if r['win_rate'] is not None else float('nan')):6.3f} "
                  f"{(r['max_dd_r'] if r['max_dd_r'] is not None else float('nan')):6.2f} "
                  f"{(r['t'] if r['t'] is not None else float('nan')):6.2f} "
                  f"{r['n_needed_for_t15'] if r['n_needed_for_t15'] is not None else 'inf':>8}")

    # ── the verdict, by the pre-registered rule ─────────────────────────────────────────
    oos = out["windows"][TEST_WINDOW]["results"]
    wf = out["windows"][SELECT_WINDOW]["results"]
    prim = oos["MOM_0.0"]
    checks: list[str] = []
    ok_t = prim["t"] is not None and prim["t"] >= T_BAR
    ok_n = prim["n"] >= MIN_TRADES
    ok_d = prim.get("per_day", 0) >= MIN_PER_DAY
    ok_pos = (prim["expectancy_r"] or 0) > 0
    wf_prim = wf["MOM_0.0"]
    ok_sign = (wf_prim["expectancy_r"] or 0) > 0 and (prim["expectancy_r"] or 0) > 0
    rev_beats = any((oos[f"REV_{c}"]["expectancy_r"] or 0) > (oos[f"MOM_{c}"]["expectancy_r"] or 0)
                    for c in THRESHOLDS)
    robust = sum(1 for c in THRESHOLDS
                 if oos[f"MOM_{c}"]["t"] is not None and oos[f"MOM_{c}"]["t"] >= T_BAR)
    checks.append(f"MOM_0 t>=2.4: {'PASS' if ok_t else 'FAIL'} "
                  f"(t={prim['t']}, n={prim['n']}, /day={prim.get('per_day')})")
    checks.append(f"n>=30: {'PASS' if ok_n else 'FAIL'}; per_day>=0.30: "
                  f"{'PASS' if ok_d else 'FAIL'}; mean>0: {'PASS' if ok_pos else 'FAIL'}")
    checks.append(f"same sign on wf: {'PASS' if ok_sign else 'FAIL'}")
    checks.append(f"no REV twin beats its MOM on oos: {'PASS' if not rev_beats else 'FAIL'}")
    checks.append(f"robustness: {robust}/3 MOM cells clear t-bar")
    verdict = ("PASS — begin the forward-shadow conversation"
               if all([ok_t, ok_n, ok_d, ok_pos, ok_sign, not rev_beats]) else "FAIL")
    if verdict == "FAIL":
        failed = [s for s, o in [("t", ok_t), ("n", ok_n), ("per_day", ok_d),
                                 ("mean", ok_pos), ("wf_sign", ok_sign),
                                 ("REV", not rev_beats)] if not o]
        verdict = f"FAIL — failed gate(s): {', '.join(failed)}"
    out["verdict"] = {"result": verdict, "checks": checks,
                      "mom_cells_clearing_t_bar": robust}
    ART.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nVERDICT:", verdict)
    for s in checks:
        print("  ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
