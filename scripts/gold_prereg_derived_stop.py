#!/usr/bin/env python3
"""Derive the stop from the measured adverse excursion, then test it once as one hypothesis.

THE DECLARATION IS `docs/GOLD_PREREG_DERIVED_STOP_20260921.md` AND CAME FIRST. It fixes: the
derivation rule (**k = the 70th percentile of |MAE| at the 8-bar horizon**, measured on the
DISCOVERY entry set), the rule under test (stop `k x ATR`, no take-profit, 48-bar limit, flat by
22:00 UTC), the test entry set (the arm's session, 06-20 UTC), the comparators, the required
sample, the falsifiers, and the prohibition on choosing from the sensitivity table.

WHY THE DERIVATION AND THE TEST USE DIFFERENT ENTRY SETS. The stop multiple is fitted on the
discovery set (session 0-24) and measured on a set the derivation never saw (06-20). That is a
strictly stronger separation than the parent test had, where the rule was both selected and
measured on related entries.

WHY 1R IS THE STOP DISTANCE. At `stop_mult = k` the risk unit is `k x ATR`, so a stop-out is
exactly -1R, the spread and commission are charged in the same unit, and widening the stop does
not quietly turn into risking more per trade. This matters for the sizing scan at the end: a
wider stop means bigger 1R in price terms, so the dollars-per-R that keeps the venue's daily
line intact is a *different* number here than in the parent test.
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
sys.path.insert(0, str(ROOT / "src"))

import gold_exit_capture as ge  # noqa: E402
import gold_governed_wfo as gg  # noqa: E402
import gold_prereg_no_target as pn  # noqa: E402
import gold_walkforward as gw  # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

T_REQ = gw.selection_threshold(1)          # 1.96: one hypothesis, no selection
QUANTILE = 0.70                            # DECLARED before the percentile was computed
HORIZON_BARS = 8                           # 2 hours on M15: where the drift is measured
RULE = {"tp": None, "trail": None, "time_bars": None}   # no target, 48 bars, flat by 22:00
PRIMARY_SESSION = (6, 20)
DISCOVERY_SESSION = (0, 24)
N_FOR_T = 375
N_FOR_POWER = 766
#: The declared FALSIFIER band on the stop-out rate. Outside it the derivation is mis-specified
#: for this excursion distribution and the run may not be reported as a test of it.
UNSOUND_LO, UNSOUND_HI = 0.20, 0.70
#: INFORMATION ONLY (the declaration forbids choosing from these).
SENSITIVITY_MULTS = (0.75, 1.0, 1.5, 2.0)
SENSITIVITY_QUANTILES = (0.50, 0.60, 0.70, 0.80)


def adverse_excursions(B: dict, entries: list[dict], atr: np.ndarray,
                       horizon: int = HORIZON_BARS) -> list[float]:
    """|MAE| per entry at `horizon` bars, in units of 1.0 x ATR (the discovery's convention).

    Only entries with at least one tradable bar before the 22:00 flat are returned; the rest
    have no measured excursion to derive from.
    """
    out: list[float] = []
    for e in entries:
        i0 = e["entry_i"]
        risk = float(atr[i0])
        if risk <= 0:
            continue
        _mfe, mae, k = ge.excursions(B, i0, e["dir"], e["entry"], risk, horizon)
        if k == 0:
            continue
        out.append(-mae)
    return out


def stop_out_rate(B: dict, entries: list[dict], atr: np.ndarray, k: float,
                  horizon: int = HORIZON_BARS) -> float:
    """Share of entries whose adverse excursion reaches the derived stop within the horizon."""
    hit = 0
    total = 0
    for e in entries:
        i0 = e["entry_i"]
        risk = float(atr[i0])
        if risk <= 0:
            continue
        _mfe, mae, kb = ge.excursions(B, i0, e["dir"], e["entry"], risk, horizon)
        if kb == 0:
            continue
        total += 1
        hit += 1 if (-mae) >= k else 0
    return hit / total if total else float("nan")


def decide(st: dict, *, unsound: bool, realized_nreq: int | None) -> tuple[str, str]:
    """The declared decision rule, including the 'more demanding of the two n' clause."""
    mean, n, t = st.get("mean_r"), st.get("n") or 0, st.get("t")
    if unsound:
        return ("UNSOUND DERIVATION",
                f"the derived stop is hit outside the declared {UNSOUND_LO:.0%}-{UNSOUND_HI:.0%} "
                f"band, so the quantile rule is mis-specified here and this may not be read as "
                f"a test of it")
    if mean is not None and mean <= 0:
        return "KILL", "primary mean <= 0 - the derived-stop no-target family is retired"
    nreq = max(N_FOR_T, realized_nreq or 0)
    if n < nreq:
        return "INSUFFICIENT", (f"n={n} < the required {nreq} "
                                f"(declared {N_FOR_T}; realized-effect requirement "
                                f"{realized_nreq})")
    if t is not None and t >= T_REQ and n < N_FOR_POWER:
        return ("POSITIVE, UNDERPOWERED",
                f"t={t:+.2f} >= {T_REQ:.2f} at n={n} < the declared {N_FOR_POWER}: positive, "
                f"explicitly not validated")
    if t is not None and t >= T_REQ:
        return "PASS", f"t={t:+.2f} >= {T_REQ:.2f} at n={n} with the power requirement met"
    return "FAIL", f"t={t:+.2f} < {T_REQ:.2f} at n={n}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_prereg_derived_stop.json")
    a = ap.parse_args(argv)

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    rules = ThunderboltClassicRules(account_size=gg.ACCOUNT_SIZE)
    window = [str(datetime.fromtimestamp(epoch[0], timezone.utc)),
              str(datetime.fromtimestamp(epoch[-1], timezone.utc))]
    print(f"venue window: {window[0]} .. {window[1]}  ({n} bars)")
    print(f"declaration: docs/GOLD_PREREG_DERIVED_STOP_20260921.md | threshold t >= {T_REQ:.2f}")

    sets = {"discovery": gg.run_grid(B, hours, ok, atr,
                                     pn.entry_config(DISCOVERY_SESSION), n),
            "primary": gg.run_grid(B, hours, ok, atr,
                                   pn.entry_config(PRIMARY_SESSION), n)}
    print(f"discovery entries (0-24 UTC): {len(sets['discovery'])}   "
          f"primary entries (06-20 UTC, the test set): {len(sets['primary'])}")

    # ---- the derivation, on the discovery set only ------------------------ #
    mae = adverse_excursions(B, sets["discovery"], atr)
    k = float(np.percentile(mae, QUANTILE * 100))
    print(f"\n== derivation on the DISCOVERY set (|MAE| in R at {HORIZON_BARS} bars, "
          f"n={len(mae)}) ==")
    for q in (0.25, 0.50, 0.70, 0.90, 0.95):
        print(f"  {q:>5.0%} percentile: {np.percentile(mae, q * 100):.3f}R")
    print(f"  mean {np.mean(mae):.3f}R   max {np.max(mae):.3f}R")
    print(f"  -> derived stop k = {k:.3f} x ATR (the declared 70th percentile), "
          f"so 1R = {k:.3f} ATR")

    hit_disc = stop_out_rate(B, sets["discovery"], atr, k)
    hit_prim = stop_out_rate(B, sets["primary"], atr, k)
    unsound = not (UNSOUND_LO <= hit_disc <= UNSOUND_HI)
    print(f"  stop-out rate: discovery {hit_disc:.1%} | primary {hit_prim:.1%} "
          f"(declared sound band {UNSOUND_LO:.0%}-{UNSOUND_HI:.0%})")
    if unsound:
        print("  !! UNSOUND: the derived stop falls outside the declared band")

    # ---- the single declared test ---------------------------------------- #
    print(f"\n== PRIMARY (06-20 UTC entries) - one declared rule, no selection ==")
    print(f"  rule: stop {k:.3f}xATR, NO target, <=48 bars, flat by {gw.FLAT_BY_UTC_HOUR}:00 UTC")
    derived = ge.simulate_policy(B, sets["primary"], atr, stop_mult=k, **RULE)
    rs = [t["net_r"] for t in derived]
    st = ge.stats(rs)
    nreq_realized = None
    if st["mean_r"] and st["sd"]:
        nreq_realized = int(math.ceil((T_REQ * st["sd"] / st["mean_r"]) ** 2))
    print(f"  {'derived stop':<34} n={st['n']:>4}  mean={st['mean_r']:+.4f}R  sd={st['sd']:.4f}  "
          f"t={st['t']:+.2f}  total={st['total_r']:+.1f}R")

    comps = {}
    for label, kw in (("same rule, stop 1.0xATR", {"stop_mult": 1.0}),
                      ("stop 1.0xATR + target 2.0R", {"stop_mult": 1.0, "tp": 2.0}),
                      ("derived stop + target 2.0R", {"stop_mult": k, "tp": 2.0})):
        tr = ge.simulate_policy(B, sets["primary"], atr, trail=None, time_bars=None,
                                tp=kw.get("tp"), stop_mult=kw["stop_mult"])
        s = ge.stats([x["net_r"] for x in tr])
        comps[label] = s
        print(f"  {label:<34} n={s['n']:>4}  mean={s['mean_r']:+.4f}R  t={s['t']:+.2f}")

    half = len(rs) // 2
    h = {"first_half": ge.stats(rs[:half]), "second_half": ge.stats(rs[half:])}
    print(f"  halves (information): first {h['first_half']['mean_r']:+.4f}R "
          f"(t={h['first_half']['t']}) | second {h['second_half']['mean_r']:+.4f}R "
          f"(t={h['second_half']['t']})")
    print(f"  realized-effect requirement (INFORMATION): {nreq_realized} trades")

    verdict, reason = decide(st, unsound=unsound, realized_nreq=nreq_realized)
    print(f"  -> {verdict}: {reason}")

    # ---- information only, per the declaration --------------------------- #
    print("\n== sensitivity (INFORMATION ONLY - the declaration forbids choosing from this) ==")
    sens = []
    for q in SENSITIVITY_QUANTILES:
        kq = float(np.percentile(mae, q * 100))
        for mult in (1.0, kq):
            s = ge.stats([x["net_r"] for x in ge.simulate_policy(
                B, sets["primary"], atr, stop_mult=mult, **RULE)])
            sens.append({"quantile": q, "stop_mult": round(mult, 4), **s})
    for m in SENSITIVITY_MULTS:
        s = ge.stats([x["net_r"] for x in ge.simulate_policy(
            B, sets["primary"], atr, stop_mult=m, **RULE)])
        sens.append({"quantile": None, "stop_mult": m, **s})
    seen = set()
    for row in sorted(sens, key=lambda r: r["stop_mult"]):
        if row["stop_mult"] in seen:
            continue
        seen.add(row["stop_mult"])
        print(f"  stop {row['stop_mult']:>6.3f}xATR   n={row['n']:>4}  "
              f"mean={row['mean_r']:+.4f}R  t={row['t']:+.2f}")

    print("\n== post-hoc SIZING scan (rule frozen; only $/R moves) ==")
    scan = pn.sizing_scan(derived, epoch, rules)
    print(f"  {'risk/R':>8} {'%':>6} {'kept':>6} {'worst day':>11} {'line':>8} {'days beyond':>12}")
    for s in scan:
        print(f"  {s['risk_usd_per_r']:>8.1f} {s['risk_pct']:>6.2f} {s['trades_kept']:>6} "
              f"{s['worst_day_usd']:>11.0f} {s['daily_limit_usd']:>8.0f} "
              f"{s['days_beyond_daily_limit']:>12}")
    usable = [s for s in scan if s["days_beyond_daily_limit"] == 0]
    print(f"  largest scanned size with every day inside the line: "
          f"{usable[0]['risk_pct']:.2f}% ({usable[0]['risk_usd_per_r']:.1f}$/R)"
          if usable else "  none of the scanned sizes keeps every day inside the line")
    print("\nNothing here is a validation: the same window discovered it. The forward record is "
          "the only instrument that can validate a rule.")

    out = {
        "declared": {
            "document": "docs/GOLD_PREREG_DERIVED_STOP_20260921.md",
            "derivation": {"statistic": f"{QUANTILE:.0%} percentile of |MAE|",
                           "horizon_bars": HORIZON_BARS, "in_r_of": "1.0 x ATR",
                           "derived_on": "discovery entry set, session 0-24 UTC",
                           "k": round(k, 4)},
            "rule": {"stop_mult": round(k, 4), "take_profit": None, "max_bars": 48,
                     "flat_by_utc_hour": gw.FLAT_BY_UTC_HOUR, "risk_unit": "the stop distance"},
            "test_entry_set": "session 06-20 UTC (primary)",
            "t_required": round(T_REQ, 4),
            "n_required_for_t": N_FOR_T, "n_required_for_power": N_FOR_POWER,
            "unsound_band": [UNSOUND_LO, UNSOUND_HI],
            "kill_rule": "primary mean <= 0 retires this family; no other quantile is tried",
            "sensitivity_is_information_only": True,
            "contamination": ("the excursion distribution, the trigger and the window are the "
                              "parent test's; the stop multiple is derived on the discovery "
                              "set and measured on a set the derivation did not use"),
        },
        "window": window, "bars": n,
        "derivation": {"n": len(mae), "mean_mae_r": round(float(np.mean(mae)), 4),
                       "percentiles": {str(q): round(float(np.percentile(mae, q * 100)), 4)
                                       for q in (0.25, 0.5, 0.60, 0.70, 0.90, 0.95)},
                       "k": round(k, 4),
                       "stop_out_rate_discovery": round(hit_disc, 4),
                       "stop_out_rate_primary": round(hit_prim, 4),
                       "unsound": bool(unsound)},
        "primary": {"stats": st, "comparators": comps, "halves": h,
                    "realized_n_requirement": nreq_realized,
                    "verdict": verdict, "reason": reason},
        "sensitivity_information_only": sens,
        "sizing_scan_post_hoc": scan,
        "verdict": verdict,
    }
    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"artifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
