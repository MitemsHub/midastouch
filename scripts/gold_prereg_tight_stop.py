#!/usr/bin/env python3
"""Evaluate the tight stop (median adverse excursion) against the search that produced it.

THE DECLARATION IS `docs/GOLD_PREREG_TIGHT_STOP_20260921.md` AND CAME FIRST. Two facts make this
run unlike the previous two, and both are stated there:

* **the candidate's numbers already exist** -- it is the mean-maximising row of the previous
  run's sensitivity table -- so this cannot be a fresh test of the effect. It is an evaluation of
  whether the effect survives being the BEST OF A SEARCH;
* **that search had 8 distinct stop multiples in it**, so the threshold is
  `selection_threshold(8) = 2.725`, not the single-hypothesis 1.96. The candidate does not get to
  skip the multiplicity accounting merely because a table printed it.

The two thresholds are computed, not quoted: the number of trials is read from the parent
artifact's own `sensitivity_information_only` list, so the price paid for the selection is
measured from the record that performed the selection. A second hurdle at the program-wide scale
(168 entry geometries) is reported separately and is declared in the document in advance -- a
candidate that clears its own search and not that one is reported as exactly that.
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
import gold_prereg_derived_stop as gd  # noqa: E402
import gold_prereg_no_target as pn  # noqa: E402
import gold_walkforward as gw  # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

#: The declared trial counts. The candidate's own search is measured from the parent record; the
#: program-wide scale is the entry-geometry sweep the audit counted.
PARENT_ARTIFACT = ROOT / "artifacts" / "gold_prereg_derived_stop.json"
DECLARED_TRIALS_OWN = 8
PROGRAM_TRIALS = 168
QUANTILE = 0.50                       # the tight candidate: the MEDIAN adverse excursion
RULE = {"tp": None, "trail": None, "time_bars": None}
PRIMARY_SESSION = (6, 20)
DISCOVERY_SESSION = (0, 24)
UNSOUND_LO, UNSOUND_HI = 0.20, 0.70
Z_POWER = 1.959963985 + 0.8416212336  # two-sided 5% + 80% power


def trials_from_parent(path: Path = PARENT_ARTIFACT) -> int | None:
    """How many distinct stops the parent run actually compared, or None if unreadable.

    Measured rather than asserted: the price of a selection is what the record that made it
    examined. `artifacts/` is gitignored, so a missing record means the count is UNKNOWN, and the
    declared value is then both recorded and flagged rather than silently trusted.
    """
    if not path.is_file():
        return None
    rows = json.loads(path.read_text(encoding="utf-8")).get("sensitivity_information_only") or []
    return len({r["stop_mult"] for r in rows}) or None


def required_n(mean: float, sd: float, t_req: float, power: bool = False) -> int | None:
    if not mean or mean <= 0 or not sd:
        return None
    z = (t_req + (Z_POWER - 1.959963985)) if power else t_req
    return int(math.ceil((z * sd / mean) ** 2))


def decide(st: dict, *, unsound: bool, t_own: float, t_prog: float,
           n_own: int | None, n_power: int | None) -> tuple[str, str]:
    """The declared verdict, including the two-hurdle wording fixed in the document."""
    mean, n, t = st.get("mean_r"), st.get("n") or 0, st.get("t")
    if unsound:
        return ("UNSOUND DERIVATION",
                f"stop-out rate outside the declared {UNSOUND_LO:.0%}-{UNSOUND_HI:.0%} band")
    if mean is not None and mean <= 0:
        return "KILL", "mean <= 0 - the tight-stop family is retired"
    if n_own and n < n_own:
        return "INSUFFICIENT", f"n={n} < {n_own} required to reach t={t_own:.3f}"
    if t is None:
        return "INSUFFICIENT", "no t statistic could be formed"
    if t < t_own:
        return ("FAIL", f"t={t:+.2f} < {t_own:.2f} - the candidate does not clear the search "
                        f"that produced it")
    base = (f"t={t:+.2f} >= {t_own:.2f} at n={n}"
            + (f", below the {n_power}-trade power requirement" if n_power and n < n_power else ""))
    verdict = "PASS" if (n_power and n >= n_power) else "POSITIVE, UNDERPOWERED"
    if t < t_prog:
        return (verdict + " | does not clear the program-wide hurdle",
                base + f"; also t < {t_prog:.2f} (the {PROGRAM_TRIALS}-geometry scale)")
    return (verdict + " | clears the program-wide hurdle too",
            base + f"; and t >= {t_prog:.2f}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_prereg_tight_stop.json")
    a = ap.parse_args(argv)

    t_own = gw.selection_threshold(DECLARED_TRIALS_OWN)
    t_prog = gw.selection_threshold(PROGRAM_TRIALS)
    measured_trials = trials_from_parent()
    if measured_trials is not None and measured_trials != DECLARED_TRIALS_OWN:
        print(f"WARNING: the parent record compared {measured_trials} stops, the declaration says "
              f"{DECLARED_TRIALS_OWN}. Using the DECLARED value; the mismatch is recorded.")

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    rules = ThunderboltClassicRules(account_size=gg.ACCOUNT_SIZE)
    window = [str(datetime.fromtimestamp(epoch[0], timezone.utc)),
              str(datetime.fromtimestamp(epoch[-1], timezone.utc))]
    print(f"venue window: {window[0]} .. {window[1]}  ({n} bars)")
    print(f"declaration: docs/GOLD_PREREG_TIGHT_STOP_20260921.md")
    print(f"thresholds: own search ({DECLARED_TRIALS_OWN} stops) t >= {t_own:.3f}   "
          f"program-wide ({PROGRAM_TRIALS}) t >= {t_prog:.3f}")

    sets = {"discovery": gg.run_grid(B, hours, ok, atr,
                                     pn.entry_config(DISCOVERY_SESSION), n),
            "primary": gg.run_grid(B, hours, ok, atr,
                                   pn.entry_config(PRIMARY_SESSION), n)}
    mae = gd.adverse_excursions(B, sets["discovery"], atr)
    k_tight = float(np.percentile(mae, QUANTILE * 100))
    print(f"\n== the candidate, re-derived on the discovery set (n={len(mae)}) ==")
    print(f"  median |MAE| at {gd.HORIZON_BARS} bars = {k_tight:.4f} x ATR  "
          f"(the parent table's row: 0.6941)")
    hit = gd.stop_out_rate(B, sets["primary"], atr, k_tight)
    unsound = not (UNSOUND_LO <= hit <= UNSOUND_HI)
    print(f"  stop-out rate on the primary set: {hit:.1%} "
          f"(declared band {UNSOUND_LO:.0%}-{UNSOUND_HI:.0%})"
          + ("  !! UNSOUND" if unsound else ""))

    print(f"\n== PRIMARY (06-20 UTC, 658 entries) - the same measurement, now priced ==")
    tight = ge.simulate_policy(B, sets["primary"], atr, stop_mult=k_tight, **RULE)
    rs = [t["net_r"] for t in tight]
    st = ge.stats(rs)
    n_own = required_n(st["mean_r"], st["sd"], t_own)
    n_power = required_n(st["mean_r"], st["sd"], t_own, power=True)
    n_prog = required_n(st["mean_r"], st["sd"], t_prog)
    print(f"  tight stop {k_tight:.4f}xATR   n={st['n']}  mean={st['mean_r']:+.4f}R  "
          f"sd={st['sd']:.4f}  t={st['t']:+.2f}  total={st['total_r']:+.1f}R")
    print(f"  required: {n_own} trades for its own threshold, {n_power} for 80% power at it, "
          f"{n_prog} for the program-wide hurdle")

    # Declared and required: paired comparison on the SAME entries.
    print("\n== paired comparison, same 658 entries ==")
    comps = {}
    for label, mult in (("tight 0.694xATR", k_tight), ("conventional 1.0xATR", 1.0),
                        ("previous declaration 1.384xATR", 1.384)):
        s = ge.stats([x["net_r"] for x in ge.simulate_policy(
            B, sets["primary"], atr, stop_mult=mult, **RULE)])
        comps[label] = s
        print(f"  {label:<32} mean={s['mean_r']:+.4f}R  sd={s['sd']:.4f}  t={s['t']:+.2f}")
    base = [x["net_r"] for x in ge.simulate_policy(B, sets["primary"], atr, stop_mult=1.0, **RULE)]
    # Paired BY ENTRY: the two rules take the same entries and exit at different times, so the
    # difference per entry is the geometry, with the entry set held fixed.
    paired = [x["net_r"] - y for x, y in zip(tight, base)]
    pst = ge.stats(paired)
    print(f"  PAIRED difference vs 1.0xATR: {pst['mean_r']:+.4f}R per trade (sd {pst['sd']:.4f}, "
          f"t={pst['t']:+.2f}) - the geometry effect with the entries held fixed")

    half = len(rs) // 2
    halves_stats = {"first_half": ge.stats(rs[:half]), "second_half": ge.stats(rs[half:])}
    print(f"  halves (information): first {halves_stats['first_half']['mean_r']:+.4f}R "
          f"(t={halves_stats['first_half']['t']}) | second "
          f"{halves_stats['second_half']['mean_r']:+.4f}R (t={halves_stats['second_half']['t']})")

    verdict, reason = decide(st, unsound=unsound, t_own=t_own, t_prog=t_prog,
                             n_own=n_own, n_power=n_power)
    print(f"\n  -> {verdict}\n     {reason}")

    print("\n== post-hoc SIZING scan (rule frozen; only $/R moves) ==")
    scan = pn.sizing_scan(tight, epoch, rules)
    for s in scan:
        print(f"  {s['risk_pct']:>5.2f}% ({s['risk_usd_per_r']:>6.1f}$/R) kept {s['trades_kept']:>4}  "
              f"worst day {s['worst_day_usd']:>7.0f}$ vs {s['daily_limit_usd']:.0f}$  "
              f"days beyond {s['days_beyond_daily_limit']}")
    usable = [s for s in scan if s["days_beyond_daily_limit"] == 0]
    print(f"  largest scanned size with every day inside the line: "
          f"{usable[0]['risk_pct']:.2f}%" if usable else "  none of the scanned sizes is clean")
    print("\nNothing here is a validation. The candidate's own numbers came from the run that "
          "suggested it; this run prices that, and cannot replace the forward record.")

    out = {
        "declared": {
            "document": "docs/GOLD_PREREG_TIGHT_STOP_20260921.md",
            "candidate": {"statistic": f"{QUANTILE:.0%} percentile of |MAE| (the median)",
                          "horizon_bars": gd.HORIZON_BARS, "resolved_mult": round(k_tight, 4)},
            "rule": {"stop_mult": round(k_tight, 4), "take_profit": None, "max_bars": 48,
                     "flat_by_utc_hour": gw.FLAT_BY_UTC_HOUR},
            "trials_declared_own": DECLARED_TRIALS_OWN,
            "trials_measured_in_parent_record": measured_trials,
            "trials_program_wide": PROGRAM_TRIALS,
            "t_required_own": round(t_own, 4), "t_required_program": round(t_prog, 4),
            "n_required_own": n_own, "n_required_power": n_power, "n_required_program": n_prog,
            "unsound_band": [UNSOUND_LO, UNSOUND_HI],
            "kill_rule": "mean <= 0 retires the tight-stop family; no other quantile follows",
            "contamination": ("the candidate's numbers were produced by the run that suggested it; "
                              "no uncontaminated holdout exists inside the venue window"),
        },
        "window": window, "bars": n,
        "candidate": {"median_mae_r": round(k_tight, 4),
                      "stop_out_rate_primary": round(hit, 4), "unsound": bool(unsound)},
        "primary": {"stats": st, "comparators": comps, "paired_vs_1_0atr": pst,
                    "halves": halves_stats, "verdict": verdict, "reason": reason},
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
