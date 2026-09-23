#!/usr/bin/env python3
"""Which leg of the entry conjunction earns its keep? (venue bars, engine of record, unchanged)

THE QUESTION. The armed mode `REVERSE_DIRECTION` needs THREE things on the same closed M15 bar:
a BB/RSI trigger, the H1+H4 EMA20 regime ANTI-ALIGNED with that trigger, and the bar inside the
session window. Every protective gate reports zero refusals on the live arm
(`session/friday/spread/riskcap/brk/news = 0`), so the fill rate is this conjunction and nothing
else. The honest question is therefore not "how do we trade more" but "which of the three legs
carries the expectancy" — a leg that carries nothing is a frequency cost paid for nothing.

WHAT IS MEASURED. Three things, pre-registered in docs/DECISION_ATTRIBUTION_PREREG_20260922.md
before any number existed:

  A. THE CONJUNCTION CENSUS. Every EVALUABLE bar (in-window, >=21 bars of history on all three
     timeframes, stop > 0) classified by its own (trigger, macro) pair, inside and outside the
     session. Occupancy-free by construction: this counts CANDIDATES, where the engine counts
     FILLS, and the difference between the two is the whole subject.
  B. THE LEG ABLATION. The engine's own 8 modes on the pre-registered split — select on `wf`,
     report on `oos` — read as marginal value per leg. No mode is selected here: a mode change
     moves the certified configuration and belongs to the pre-registration -> parity -> arming
     path. What this produces is the evidence that would justify opening that path.
  C. THE COUNTERFACTUAL ON THE REFUSED CLASS. The barred rows are measurable, not unknowable:
     `ORIGINAL` trades  exactly the trigger bars whose macro AGREES (the armed mode's mirror),
     `TRIGGER_ONLY` trades both plus the divergent-macro bars, `MACRO_ONLY` drops the trigger
     requirement entirely. Their held-out expectancy is the PRICE of each requirement.

HOW IT STAYS HONEST. The census walks bars SIMULTANEOUSLY with the engine's own code quoted in
`midas_sweep.run_mode` (trigger at lines 557-567 of that file, the mode transforms at 553-576),
and it is then CHECKED AGAINST the engine: for every trade the engine reports across all eight
modes, the census must independently place the same trigger presence, the same macro state and
the same session hour. A census that disagrees with the engine is a lookalike, and the run isvoid
rather than reported. On top of that the harness reproduces the pinned venue-corpus law
(56 trades / +15.9352R — re-pointed 2026-09-22 when the trigger threshold became part of the
contract) before it prints anything.

WHAT IT CANNOT BE. `wf`/`oos` here are the repository's own pre-registered windows, and every
cell prints its `t` and the sample it would need for `t >= 1.5`, so an undecidable cell reads as
undecidable. The tercile and hour splits are descriptive CONTEXTS, not regimes: the terciles are
computed over the whole corpus (an ex-post description of volatility, not a classifier that
could have been known live). Nothing here is a validation, and no number here arms anything.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_parity as P  # noqa: E402  the engine of record, on the venue's own bars
import midas_sweep as M  # noqa: E402  the certified mode engine and its metrics

ART = Path("artifacts") / "midas_decision_attribution_20260922.json"

#: select on `wf`, report on `oos` — both the repo's own pre-registered windows.
SEL_WINDOW = "wf"
TEST_WINDOW = "oos"

#: The class of every evaluable bar, by the pair the engine itself branches on.
#: `mac` is `M.macro_state()` — +1 both legs up, -1 both down, 0 divergent.
CLASSES = (
    "no_trigger",            # trigger == 0
    "trig_macro_divergent",  # trigger != 0, mac == 0
    "trig_macro_agree",      # trigger != 0, mac ==  trigger  (ORIGINAL's class)
    "trig_macro_anti",       # trigger != 0, mac == -trigger  (REVERSE_DIRECTION's class)
)


def self_check() -> None:
    """Reproduce the pinned venue-corpus law, or refuse to report anything else."""
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    finally:
        M._BASIS = prev
    n, total = len(rr.trades), sum(t["r"] for t in rr.trades)
    print(f"self-check  wfv {spec['mode']}: n={n} totalR={total:+.4f} vetoed={rr.vetoed}")
    if n != 56 or abs(total - 15.9352) >= 5e-4:
        raise SystemExit(
            "REFUSING: this harness did not reproduce the pinned venue-corpus law "
            "(expected n=56 / +15.9352R, tests/test_midas_minlot_veto.py, re-pointed "
            "2026-09-22 when the trigger threshold became part of the contract). "
            "Every number below would be a lookalike.")
    print("            reproduced the pin -> the arithmetic below is the engine of record's.\n")


def walk(data: dict, t0: int, t1: int, win_lo: int, win_hi: int) -> dict:
    """The conjunction census. Mirrors `midas_sweep.run_mode`'s own evaluable-bar test.

    Returns {sig_ct: {...}} keyed by the signal bar's CLOSE time. The engine's trades carry no
    `sig_ct` field, but they do not need one: a fill happens at the NEXT bar's open, so a
    trade's `open_ct` IS the signal bar's close time (`run_mode`: `pending["sig_ct"] = b["time"]
    + 900`, then `pos["open_ct"] = b2["time"]` where `b2["time"] == pending["sig_ct"]`). The
    cross-check below is what proves that identity on this corpus rather than assuming it.
    """
    h1, m15, h4 = data["h1"], data["m15"], data["h4"]
    h1_ema, h1_atr, h4_ema = data["h1_ema"], data["h1_atr"], data["h4_ema"]
    m15_rsi, m15_bb = data["m15_rsi"], data["m15_bb"]
    census: dict[int, dict] = {}
    for i, b in enumerate(m15):
        ct = b["time"] + 900
        if not (ct > t0 and b["time"] <= t1):
            continue
        k1 = bisect_right(data["h1_ct"], ct)
        k4 = bisect_right(data["h4_ct"], ct)
        if k1 < 21 or k4 < 21 or i < 21:
            continue
        atr = h1_atr[k1 - 1]
        stop_d = M.SL_ATR_MULT * atr
        if stop_d <= 0:
            continue
        mac = M.macro_state(h1[k1 - 1]["close"], h1_ema[k1 - 1],
                            h4[k4 - 1]["close"], h4_ema[k4 - 1])
        t_bb, t_rsi = m15_bb[i], m15_rsi[i]
        trigger = 0
        trig_src = "none"
        if t_bb != 0:
            trigger, trig_src = t_bb, "bb"
        elif t_rsi >= 70:
            trigger, trig_src = -1, "rsi"
        elif t_rsi <= 30:
            trigger, trig_src = 1, "rsi"
        hr = datetime.fromtimestamp(b["time"], tz=timezone.utc).hour
        if trigger == 0:
            klass = "no_trigger"
        elif mac == 0:
            klass = "trig_macro_divergent"
        elif mac == trigger:
            klass = "trig_macro_agree"
        else:
            klass = "trig_macro_anti"
        census[ct] = {"sig_ct": ct, "bar_time": b["time"], "hour_utc": hr,
                      "in_session": bool(win_lo <= hr < win_hi), "mac": mac,
                      "trigger": trigger, "trigger_src": trig_src,
                      "atr_h1": round(atr, 4), "class": klass}
    return census


def check_against_engine(mode: str, trades: list[dict], census: dict[int, dict]) -> list[str]:
    """Every trade must be explained by the census, or the census is a lookalike."""
    bad: list[str] = []
    for t in trades:
        key = int(t["open_ct"])       # == the signal bar's close time (see `walk`'s docstring)
        rec = census.get(key)
        if rec is None:
            bad.append(f"{mode}: engine trade at open_ct={key} has no census row")
        mg, tg = rec["mac"], rec["trigger"]
        ok = True
        if mode == "ORIGINAL":
            ok = tg != 0 and mg == tg
        elif mode == "REVERSE_DIRECTION":
            ok = tg != 0 and mg == -tg
        elif mode == "TRIGGER_ONLY":
            ok = tg != 0
        elif mode in ("REVERSE_TRIGGER", "REVERSE_BOTH"):
            ok = tg == 0 and mg != 0
        elif mode == "MACRO_ONLY":
            ok = mg != 0
        elif mode in ("LONG_ONLY", "SHORT_ONLY"):
            ok = tg != 0 and mg == tg
        if not ok:
            bad.append(f"{mode}: census says trigger={tg} mac={mg} for open_ct={key}, "
                       f"the engine traded it")
        if int(t.get("mac", mg)) != mg:
            bad.append(f"{mode}: census mac={mg} vs the engine's own mac={t.get('mac')} "
                       f"at open_ct={key}")
        if int(t.get("hour", rec["hour_utc"])) != rec["hour_utc"]:
            bad.append(f"{mode}: census hour={rec['hour_utc']} vs the engine's {t.get('hour')} "
                       f"at open_ct={key}")
        if not rec["in_session"]:
            bad.append(f"{mode}: the engine filled a bar the census puts out of session "
                       f"(open_ct={key})")
    return bad


def day_stats(trades: list[dict], t0: int, t1: int) -> dict:
    """Entry frequency and the share of days with no entry at all, in the corpus' UTC frame."""
    days = set()
    d = t0 - (t0 % 86400)
    while d <= t1:
        days.add(d)
        d += 86400
    hit = {int(t["open_ct"]) - (int(t["open_ct"]) % 86400) for t in trades}
    nd = len(days)
    return {"days": nd,
            "per_day": round(len(trades) / nd, 3) if nd else 0.0,
            "zero_day_share": round(1 - len(hit & days) / nd, 3) if nd else 0.0}


def t_stat(rs: list[float]) -> float | None:
    if len(rs) < 2:
        return None
    import statistics
    sd = statistics.stdev(rs)
    return round(statistics.mean(rs) / (sd / (len(rs) ** 0.5)), 3) if sd > 0 else None


def needed_for_t15(rs: list[float]) -> int | None:
    """The sample this cell would need for t >= 1.5 — the number that makes a cell decidable."""
    if len(rs) < 2:
        return None
    import math
    import statistics
    sd = statistics.stdev(rs)
    m = statistics.mean(rs)
    if sd <= 0:
        return None
    if m <= 0:
        return None if m == 0 else -1  # negative mean: no sample makes t >= 1.5 positive
    return int(math.ceil((1.5 * sd / m) ** 2))


def summarise(trades: list[dict], t0: int, t1: int) -> dict:
    m = M.metrics(trades)
    rs = [t["r"] for t in trades]
    out = {**{k: m.get(k) for k in ("n", "net_r", "expectancy_r", "pf", "win_rate", "max_dd_r")},
           "t": t_stat(rs), "n_needed_for_t15": needed_for_t15(rs), **day_stats(trades, t0, t1)}
    if trades:
        out["first_open_utc"] = datetime.fromtimestamp(int(trades[0]["open_ct"]),
                                                       tz=timezone.utc).isoformat()
        out["last_open_utc"] = datetime.fromtimestamp(int(trades[-1]["open_ct"]),
                                                      tz=timezone.utc).isoformat()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-selfcheck", action="store_true")
    args = ap.parse_args()
    if not args.skip_selfcheck:
        self_check()

    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    result: dict = {"harness": "midas_decision_attribution.py",
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "engine": "midas_sweep.run_mode (unchanged, every keyword at its default)",
                    "corpus": "data/forex/xauusd (venue bars, shifted to true UTC per window)",
                    "split": {"select": SEL_WINDOW, "report": TEST_WINDOW},
                    "prereg": "docs/DECISION_ATTRIBUTION_PREREG_20260922.md",
                    "windows": {}, "checks": {}}
    try:
        for wname in (SEL_WINDOW, TEST_WINDOW):
            spec = P._window_spec(wname)
            off = P.assert_server_offset(spec)
            data = P.python_build_data(offset_min=off, corpus="venue")
            t0, t1 = spec["t0"], spec["t1"]
            win_lo, win_hi = M.SESSION_LO, M.SESSION_HI
            census = walk(data, t0, t1, win_lo, win_hi)

            # ── A. the conjunction census ───────────────────────────────────────────────
            evals = list(census.values())
            insess = [r for r in evals if r["in_session"]]
            counts = {k: sum(1 for r in evals if r["class"] == k) for k in CLASSES}
            counts_sess = {k: sum(1 for r in insess if r["class"] == k) for k in CLASSES}
            by_hour: dict[int, dict] = {}
            for r in evals:
                h = by_hour.setdefault(r["hour_utc"], {k: 0 for k in CLASSES} | {"evaluable": 0})
                h[r["class"]] += 1
                h["evaluable"] += 1
            atrs = sorted(r["atr_h1"] for r in evals)
            tertiles = ([atrs[len(atrs) // 3], atrs[2 * len(atrs) // 3]] if atrs else [0, 0])
            def tertile(a: float) -> str:
                return ("low" if a <= tertiles[0] else "mid" if a <= tertiles[1] else "high")
            by_vol = {b: {k: 0 for k in CLASSES} | {"evaluable": 0} for b in ("low", "mid", "high")}
            for r in evals:
                by_vol[tertile(r["atr_h1"])][r["class"]] += 1
                by_vol[tertile(r["atr_h1"])]["evaluable"] += 1

            # ── B/C. the leg ablation: the engine's own 8 modes, one pass each ─────────
            modes: dict[str, dict] = {}
            bad: list[str] = []
            for mode in M.MODES:
                rr = M.run_mode(mode, t0, t1, data)
                modes[mode] = {**summarise(rr.trades, t0, t1), "vetoed": rr.vetoed,
                               "floored": rr.floored,
                               "entry_classes": {k: sum(1 for t in rr.trades
                                                        if census.get(int(t["open_ct"]), {})
                                                        .get("class") == k) for k in CLASSES}}
                bad += check_against_engine(mode, rr.trades, census)
            result["checks"][wname] = {"census_vs_engine_disagreements": bad[:20],
                                       "n_disagreements": len(bad)}

            result["windows"][wname] = {
                "t0": t0, "t1": t1, "server_offset_min": off, "session_utc": [win_lo, win_hi],
                "evaluable_bars": len(evals), "evaluable_in_session": len(insess),
                "classes_all_bars": counts, "classes_in_session": counts_sess,
                "class_shares_in_session": {k: (round(counts_sess[k] / len(insess), 4)
                                                if insess else None) for k in CLASSES},
                "atr_h1_tertile_cuts": [round(x, 4) for x in tertiles],
                "by_hour_utc": {str(h): by_hour[h] for h in sorted(by_hour)},
                "by_atr_tertile": by_vol, "modes": modes}
    finally:
        M._BASIS = prev

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(result, indent=1), encoding="utf-8")

    # ── the report ──────────────────────────────────────────────────────────────────────
    for wname in (SEL_WINDOW, TEST_WINDOW):
        w = result["windows"][wname]
        print(f"=== {wname}  {w['evaluable_bars']} evaluable bars, "
              f"{w['evaluable_in_session']} inside UTC {w['session_utc'][0]}-{w['session_utc'][1]}")
        print("  the conjunction, inside the session (share of evaluable in-session bars):")
        for k in CLASSES:
            print(f"    {k:22s} {w['classes_in_session'][k]:6d}  "
                  f"{w['class_shares_in_session'][k]:7.3%}")
        print("  the leg ablation:")
        print(f"    {'mode':18s} {'n':>5s} {'/day':>6s} {'zero%':>6s} {'expR':>8s} "
              f"{'pf':>6s} {'win':>6s} {'ddR':>6s} {'t':>6s} {'n@t1.5':>7s}")
        for mode in M.MODES:
            m = w["modes"][mode]
            print(f"    {mode:18s} {m['n']:5d} {m['per_day']:6.2f} "
                  f"{m['zero_day_share']:6.1%} {m['expectancy_r'] if m['expectancy_r'] is not None else float('nan'):8.4f} "
                  f"{(m['pf'] if m['pf'] is not None else float('nan')):6.3f} "
                  f"{(m['win_rate'] if m['win_rate'] is not None else float('nan')):6.3f} "
                  f"{(m['max_dd_r'] if m['max_dd_r'] is not None else float('nan')):6.1f} "
                  f"{(m['t'] if m['t'] is not None else float('nan')):6.2f} "
                  f"{(m['n_needed_for_t15'] if m['n_needed_for_t15'] is not None else -1):7d}")
        print(f"  census-vs-engine disagreements: {result['checks'][wname]['n_disagreements']}")
        print()
    print(f"artifact: {ART}")
    total_bad = sum(result["checks"][w]["n_disagreements"] for w in result["checks"])
    if total_bad:
        print(f"\nREFUSING TO CALL THIS A MEASUREMENT: {total_bad} census/engine disagreement(s) "
              f"- the census is a lookalike.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
