#!/usr/bin/env python3
"""Decidability audit: does any number this program measured clear its own selection cost?

WHY THIS EXISTS. Every study in this repo ends with a t-statistic, and the gate that
decides arming uses `t >= 1.5`. That threshold assumes ONE hypothesis was tested. None
of them were. Measured trial counts from the stored artifacts: 168 entry geometries
(7 sessions x 3 stops x 4 targets x 2 trend sets), 24 trigger cells, 13 exit policies,
48 exit-family arms. When a search reports the best of N trials, the best-of-N maximum
is a random variable whose expectation under the null is not zero -- at N=168 with
independent trials it is about 2.9 standard errors. A t of 1.5 is therefore not
evidence of anything; it is roughly half of what pure noise produces when you look at
168 answers and keep the largest.

The literature this program is held to says the same thing in three different ways:
Harvey et al. (2016) argue the conventional 2.0 hurdle should be ~3.0 once data mining
is accounted for; Bailey & Lopez de Prado (2014) give the Deflated Sharpe Ratio, which
substitutes the *expected maximum* Sharpe under the null for zero; and CSCV computes
the Probability of Backtest Overfitting. This script implements the first two on the
numbers already stored here and reports the third as a gap with the artifact it needs.

WHAT IT COMPUTES, AND FROM WHAT.

  * `expected_max_abs_z(N)` -- the null ceiling, by Monte Carlo. The honest comparison
    for "the best t we found" is not 1.96 or 1.5, it is this number.
  * `deflated_sharpe(...)` -- DSR per Bailey & Lopez de Prado, using the trial-to-trial
    variance of the Sharpe estimates, which the stored artifacts do allow (each trial
    carries n, mean_r and sd).
  * exact Student-t confidence intervals for the samples that were NOT selections
    (single pre-registered or single-configuration measurements).
  * `needed_n(...)` -- trades required to reach a given threshold at the measured
    effect size, which is the number that decides whether a rule is worth pursuing.

APPROXIMATIONS, DECLARED. The stored artifacts carry no per-trade returns, so DSR is
computed with the normal-shape assumption (skew 0, kurtosis 3). This OVERSTATES DSR:
the DSR denominator is sqrt(1 - skew*SR + ((kurt-1)/4)*SR^2), so the fat tails this
program measures (exit polices show sd up to 3.18 R) would make the denominator larger
and the ratio smaller. Read every DSR below as an upper bound. Population skew/kurtosis
for the selection candidates need per-trade arrays, which is named as a gap at the end.

PROVENANCE. Families are read from `artifacts/*.json`; the scripts that write them are
named in each family's own `source` field. Two headline samples from
`docs/GOLD_ARMING_DECISION_20260921.md` exist only as printed numbers, not as artifacts
-- they are carried in `TRANSCRIBED` and labelled as such, because a number that is not
stored cannot be re-checked and that is itself worth seeing in the output.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))  # noqa: E402
#: ONE implementation of the selection threshold, shared with the gate. The engine owns
#: it because V7 applies it; this audit reports against the same function rather than
#: carrying a second copy that could quietly disagree.
from gold_walkforward import configs as _wf_configs, max_abs_z_stats, selection_threshold  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ARTIFACTS = ROOT / "artifacts"

#: Euler-Mascheroni, used by the DSR's expected-maximum-Sharpe term.
EULER_GAMMA = 0.5772156649015329


def deflated_sharpe(sr: float, n_obs: int, n_trials: int, sr_variance: float,
                    skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    `sr` is the selected strategy's Sharpe per observation (mean/sd of the trade
    returns), `sr_variance` the variance of the Sharpe estimates ACROSS the trials that
    were compared. Returns the probability that the selected result exceeds what the
    best of `n_trials` null strategies would have produced.
    """
    if n_trials < 2 or sr_variance <= 0 or n_obs < 3:
        return float("nan")
    e = math.e
    z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * e))
    sr0 = math.sqrt(sr_variance) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * sr * sr))
    return float(stats.norm.cdf((sr - sr0) * math.sqrt(n_obs - 1) / denom))


def t_ci(mean: float, sd: float, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Exact Student-t interval. Used for samples that were not selections."""
    half = stats.t.ppf(0.5 + conf / 2.0, n - 1) * sd / math.sqrt(n)
    return mean - half, mean + half


def needed_n(mean: float, sd: float, t_req: float) -> int | None:
    """Trades required for `t_req` at this effect size, or None if the mean is not positive."""
    if mean <= 0 or sd <= 0:
        return None
    return int(math.ceil((t_req * sd / mean) ** 2))


def load(rel: str):
    p = ARTIFACTS / rel
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


#: Samples that were a SELECTION: (family, label, n, mean_r, sd, trials_tested, source).
#: `trials_tested` is the count of alternatives the family searched; it is what the
#: ceiling is computed against, so it is stated per family rather than guessed globally.
def selected_families() -> list[dict]:
    fams: list[dict] = []

    rows: list[dict] = []
    for part in ("gold_governed_wfo_sweep0of3.json", "gold_governed_wfo_sweep1of3.json",
                 "gold_governed_wfo_sweep2of3.json"):
        d = load(part)
        if d:
            rows.extend(d["sweep"]["rows"])
    if rows:
        best_g = max(rows, key=lambda r: r["governed"]["mean_r"])
        best_u = max(rows, key=lambda r: r["ungoverned"]["mean_r"])
        # Trial-to-trial variance of the Sharpe estimate: the DSR's expected-maximum
        # term is driven by how WIDELY the compared trials' Sharpes scatter, which is
        # exactly what the stored per-row (mean_r, sd) pairs give.
        sr_var_g = float(np.var([r["governed"]["mean_r"] / r["governed"]["sd"]
                                 for r in rows if r["governed"]["sd"]]))
        sr_var_u = float(np.var([r["ungoverned"]["mean_r"] / r["ungoverned"]["sd"]
                                 for r in rows if r["ungoverned"]["sd"]]))
        fams.append({
            "family": "geometry sweep (entry-only governor)",
            "label": f"{best_g['config']['win_lo']}-{best_g['config']['win_hi']}h "
                     f"stop {best_g['config']['stop_mult']} tp {best_g['config']['tp_mult']}",
            "n": best_g["governed"]["n"], "mean_r": best_g["governed"]["mean_r"],
            "sd": best_g["governed"]["sd"], "trials": len(rows),
            "sr_variance": sr_var_g,
            "source": "scripts/gold_governed_wfo.py --sweep (artifacts/gold_governed_wfo_sweep*of3.json)",
        })
        fams.append({
            "family": "geometry sweep (ungoverned)",
            "label": f"{best_u['config']['win_lo']}-{best_u['config']['win_hi']}h "
                     f"stop {best_u['config']['stop_mult']} tp {best_u['config']['tp_mult']}",
            "n": best_u["ungoverned"]["n"], "mean_r": best_u["ungoverned"]["mean_r"],
            "sd": best_u["ungoverned"]["sd"], "trials": len(rows),
            "sr_variance": sr_var_u,
            "source": "scripts/gold_governed_wfo.py --sweep (artifacts/gold_governed_wfo_sweep*of3.json)",
        })

    d = load("gold_trigger_edge.json")
    if d and d.get("best_cells"):
        b = max(d["best_cells"], key=lambda c: c["mean_r"])
        n_cells = sum(len(v) for v in d.get("sections", {}).values())
        all_cells = [c for v in d.get("sections", {}).values() for c in v]
        fams.append({
            "family": "trigger conditional cells",
            "label": b["cell"], "n": b["n"], "mean_r": b["mean_r"], "sd": b["sd"],
            "trials": n_cells,
            "sr_variance": float(np.var([c["mean_r"] / c["sd"] for c in all_cells if c.get("sd")])),
            "source": "scripts/gold_trigger_edge.py (artifacts/gold_trigger_edge.json)",
        })

    d = load("gold_exit_capture.json")
    if d and d.get("policies"):
        ps = [p for p in d["policies"] if p.get("n")]
        b = max(ps, key=lambda p: p["mean_r"])
        fams.append({
            "family": "exit geometry (fixed entry set, re-priced)",
            "label": b["policy"], "n": b["n"], "mean_r": b["mean_r"], "sd": b["sd"],
            "trials": len(ps),
            "sr_variance": float(np.var([p["mean_r"] / p["sd"] for p in ps if p.get("sd")])),
            "source": "scripts/gold_exit_capture.py (artifacts/gold_exit_capture.json)",
        })

    return fams


#: Single pre-registered / single-configuration measurements: not selections, so a
#: plain t interval is the right instrument. `transcribed` marks the ones whose source
#: is a document rather than an artifact -- re-checkable only by re-running the harness.
def single_measurements() -> list[dict]:
    out: list[dict] = []
    d = load("gold_prereg_late_short.json")
    if d:
        p = d["pooled"]
        out.append({"label": "late-session short (pre-registered, declared n=190)",
                    "n": p["n"], "mean_r": p["mean_r"], "sd": p["sd"],
                    "source": "docs/GOLD_PREREG_LATE_SHORT_20260921.md + artifact",
                    "transcribed": False})
    d = load("gold_exit_family_wfo.json")
    if d:
        for name, blk in d.get("hard_day", {}).items():
            if blk.get("trades"):
                out.append({"label": f"hard-day policy: {name}", "n": blk["trades"],
                            "mean_r": blk["mean_r"], "sd": None,
                            "source": "scripts/gold_exit_family_wfo.py + artifact",
                            "transcribed": False})
    # Venue-window headline samples measured in a shell and recorded in a document;
    # carried here so the audit can see that they are NOT artifact-backed.
    out.append({"label": "venue, first quarter 2026-01-12..03-31",
                "n": 53, "mean_r": 0.269, "sd": None,
                "source": "docs/GOLD_ARMING_DECISION_20260921.md (transcribed; no artifact)",
                "transcribed": True})
    out.append({"label": "venue, combined 2026-01-12..09-16",
                "n": 160, "mean_r": 0.068, "sd": 1.082,
                "source": "docs/GOLD_ARMING_DECISION_20260921.md (transcribed; no artifact)",
                "transcribed": True})
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit the full computed table")
    a = ap.parse_args(argv)

    report: dict = {"ceilings": {}, "selections": [], "singles": [], "gaps": []}

    print("=" * 78)
    print("THE NULL CEILING — what the largest t looks like when there is no edge at all")
    print("=" * 78)
    print(f"  {'trials searched':>16}  {'E[max |z|]':>12}  {'95th pct (the threshold to beat)':>32}")
    for n in (1, 5, 13, 24, 48, 168):
        m, q = max_abs_z_stats(n)
        report["ceilings"][n] = {"mean": round(m, 3), "q95": round(q, 3)}
        note = "  <- the conventional 1.96 is this cell at N=1" if n == 1 else ""
        print(f"  {n:>16}  {m:>12.3f}  {q:>32.3f}{note}")
    print("\n  The program's own gate requires t >= 1.5. At 168 trials, noise alone")
    print("  reaches about 2.9. A gate below the noise ceiling cannot fail a search.")

    print()
    print("=" * 78)
    print("SELECTIONS — the best of a family, measured against ITS OWN search size")
    print("=" * 78)
    fams = selected_families()
    for f in fams:
        n, mean, sd, trials = f["n"], f["mean_r"], f["sd"], f["trials"]
        t = mean / sd * math.sqrt(n) if sd else float("nan")
        ceil = report["ceilings"].get(trials) or {}
        if not ceil:
            m, q = max_abs_z_stats(trials)
            ceil = {"mean": round(m, 3), "q95": round(q, 3)}
            report["ceilings"][trials] = ceil
        sr = mean / sd if sd else float("nan")
        # Trial-to-trial Sharpe variance, for the DSR's expected-maximum term. Computed
        # from the family's own rows below when available; otherwise NaN and reported.
        sr_var = f.get("sr_variance", float("nan"))
        dsr = deflated_sharpe(sr, n, trials, sr_var) if sr_var == sr_var else float("nan")
        clears = t > ceil["q95"] if t == t else False
        row = {**{k: f[k] for k in ("family", "label", "n", "mean_r", "sd", "trials", "source")},
               "t": round(t, 3), "ceiling_mean": ceil["mean"], "ceiling_q95": ceil["q95"],
               "dsr": None if dsr != dsr else round(dsr, 4),
               "clears_ceiling": bool(clears)}
        report["selections"].append(row)
        print(f"  {f['family']}  [{trials} trials]")
        print(f"    best: {f['label']}  n={n}  mean={mean:+.4f}R  sd={sd:.4f}  t={t:+.2f}")
        print(f"    null ceiling for {trials} trials: mean {ceil['mean']:.2f}, "
              f"95th pct {ceil['q95']:.2f}   -> "
              f"{'CLEARS' if clears else 'BELOW the threshold (what noise produces here)'}")
        if dsr == dsr:
            print(f"    deflated Sharpe (upper bound, normal-shape): {dsr:.4f}")
        print()

    print("=" * 78)
    print("NOT SELECTIONS — single pre-registered or single-configuration samples")
    print("=" * 78)
    for s in single_measurements():
        n, mean, sd = s["n"], s["mean_r"], s.get("sd")
        t = mean / sd * math.sqrt(n) if sd else None
        lo, hi = (t_ci(mean, sd, n) if sd else (None, None))
        txt = f"  {s['label']:<52} n={n:>4}  mean={mean:+.4f}R"
        if t is not None:
            txt += f"  t={t:+.2f}  95% CI [{lo:+.4f}, {hi:+.4f}]"
        print(txt)
        print(f"      source: {s['source']}")
        if s.get("transcribed"):
            print("      TRANSCRIBED - no artifact holds these trades, so nothing re-checks them")
        need15 = needed_n(mean, sd, 1.5) if sd else None
        q168 = (report["ceilings"].get(168) or max_abs_z_stats(168))
        q168 = q168["q95"] if isinstance(q168, dict) else q168
        need29 = needed_n(mean, sd, q168) if sd else None
        if need15 or need29:
            print(f"      trades needed: t>=1.5 -> {need15}   "
                  f"t>={q168:.2f} (168-trial threshold) -> {need29}")
        report["singles"].append({**s, "t": None if t is None else round(t, 3),
                                  "ci95": [None, None] if sd is None else [round(lo, 4), round(hi, 4)],
                                  "needed_t15": need15, "needed_t29": need29})

    print()
    print("=" * 78)
    print("THE AMENDED GATE, RE-APPLIED TO THE FROZEN WALK-FORWARD RECORD")
    print("=" * 78)
    frozen = load("gold_wfo.json")
    if frozen:
        st = frozen.get("stats", {})
        t_frozen = st.get("_t")
        trials = frozen.get("trials_searched") or len(_wf_configs())
        t_req = selection_threshold(trials)
        print(f"  artifact: artifacts/gold_wfo.json   recorded verdict: {frozen.get('verdict')}")
        print(f"  its own stored stats: t={t_frozen:+.3f} over {st.get('_n')} folds")
        print(f"  V7 threshold for {trials} trials searched: {t_req:.2f}")
        print(f"  -> V7 {'PASSES' if t_frozen >= t_req else 'FAILS'}   "
              f"(the record already printed NOT VALIDATED, so the amendment cannot "
              f"have weakened it)")
        report["frozen_recheck"] = {"t": t_frozen, "trials": trials,
                                    "v7_threshold": round(t_req, 3),
                                    "v7_pass": bool(t_frozen >= t_req),
                                    "verdict": frozen.get("verdict")}
    else:
        print("  no artifacts/gold_wfo.json present - nothing to re-apply")

    print()
    print("=" * 78)
    print("GAPS — what this audit could NOT check")
    print("=" * 78)
    gaps = [
        "Probability of Backtest Overfitting (CSCV) needs a config x fold performance "
        "matrix. The sweep artifact stores pooled per-config stats only; "
        "scripts/gold_governed_wfo.py would have to keep per-fold R per config.",
        "DSR uses the normal shape (skew 0, kurtosis 3) because no artifact stores "
        "per-trade returns. Fat tails make the true DSR LOWER, so every DSR here is an "
        "upper bound -- the conservative direction for a refusal, the wrong direction "
        "for an arming decision.",
        "The two venue-window headline samples from the arming decision exist only as "
        "printed numbers. The harness that produced them should write an artifact.",
        "The frozen walk-forward artifact predates V7, so its stored checks are V1-V6. "
        "It is NOT regenerated here on purpose: re-running the harness on today's bars "
        "would move V1-V6 too, which is a re-baseline, not an amendment. The amended "
        "verdict above is computed from the record's own stored t and fold count.",
        "scripts/gold_walkforward.py defaults --risk-usd to 75 while the arm trades 1% "
        "of 25,000 = 250. The certified checks do not consume it (only the prop_compat "
        "block does), so no verdict moves -- but the two bases should be reconciled.",
    ]
    for g in gaps:
        print(f"  - {g}")
        report["gaps"].append(g)

    out = ARTIFACTS / "gold_stats_audit.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    if a.json:
        print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
