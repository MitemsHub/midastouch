#!/usr/bin/env python3
"""Is the second-half decay regime-driven? Select a state on H1, freeze it, test it on H2.

THE DECLARATION IS `docs/GOLD_PREREG_PERSISTENCE_STATE_20260921.md` AND CAME FIRST. Three things
in it decide the whole design and are implemented literally below:

* **TIME split at the window midpoint**, not a trade-order split. The last three studies split by
  trade order and could only report the second half as a caveat; H1 and H2 here are disjoint
  calendar periods, so an H1-selected state tested on H2 is tested forward in time.
* **the selection is priced.** A cell chosen as the best of 24 (vol x session x news) or 12
  (without news) must clear `selection_threshold(n_cells)`. If no cell clears it, NO state rule is
  carried forward -- that is a declared outcome, not an invitation to re-cut the bins.
* **the composition decomposition runs with no selection at all**, because that is the part of the
  question ("is the decay regime-driven?") that can be answered without choosing a winner:
  `mean_H2_at_H1_mix = sum_c w_H1(c) * mean_H2(c)` against H2's own mean.

The news axis is measured only from a calendar that passes `news_calendar`'s own freshness and
coverage check; otherwise it is dropped and the reason recorded, because a state split built on an
unusable calendar is a label with nothing behind it.
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
import midas_first_fills_audit as ffa  # noqa: E402
from midas_prop.risk import news_calendar as nc  # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

SESSIONS = ((0, 6, "00-06"), (6, 12, "06-12"), (12, 17, "12-17"), (17, 22, "17-22"))
VOL_BINS = ((0.0, 0.8, "low"), (0.8, 1.3, "normal"), (1.3, 9e9, "high"))
NEWS_WINDOW_MIN = 15
MIN_CELL_N = 30                 # declared minimum for a cell to be selectable on H1
ROBUSTNESS_STOP = 1.384         # declared: the previous declaration's stop, same frozen cell
RULE = {"tp": None, "trail": None, "time_bars": None}
PRIMARY_SESSION = (6, 20)
EXIT_STOP = 1.0                 # the parent rule's stop: the geometry is NOT re-optimised here


def news_axis(epoch: np.ndarray, n: int) -> tuple[np.ndarray | None, str | None]:
    """Per-bar "inside a top-tier blackout" mask, or (None, reason) when unmeasurable.

    Reads the SAME module, window and filter the EA uses at runtime, and refuses on the module's
    own freshness/coverage terms rather than inventing a weaker one.
    """
    try:
        import midas_parity  # noqa: PLC0415  (imported late: it reaches for the terminal)
        path = midas_parity.news_calendar_path()
    except Exception as exc:                                     # pragma: no cover - env dependent
        return None, f"the calendar path could not be resolved ({type(exc).__name__}: {exc})"
    if path is None:
        return None, "no terminal data folder, so no calendar path could be resolved"
    if not Path(path).is_file():
        return None, f"the calendar is absent at {path}"
    try:
        cal = nc.read_calendar(path)
    except nc.CalendarUnusable as exc:
        return None, f"the calendar at {path} is unusable: {exc}"
    except Exception as exc:
        return None, f"the calendar at {path} could not be parsed ({type(exc).__name__}: {exc})"
    problem = nc.source_problem(cal, int(epoch[n - 1]))
    if problem:
        return None, f"the calendar is unusable at the window end: {problem}"
    events = nc.top_tier_events(cal)
    if not events:
        return None, "the calendar carries no top-tier events for this window"
    mask = np.zeros(n, dtype=bool)
    for i in range(n):
        if nc.blackout_reason(events, int(epoch[i]), NEWS_WINDOW_MIN):
            mask[i] = True
    return mask, f"{len(events)} top-tier events, +/-{NEWS_WINDOW_MIN} min, HIGH only"


def label_of_values(ratio: float, hour: int, news: bool | None) -> str:
    """The declared cell label from MEASURED values rather than a bar index.

    Split out of `cell_of` so the binning exists ONCE. The forward harness labels the arm's own
    ledger rows from the state the EA stamped at fill time (raw volatility ratio, UTC hour, news
    proximity), and a second copy of these edges would be a second definition of the cell — which
    is how two engines end up claiming one policy while measuring two.

    `news=None` drops the axis (the two-axis label); a `nan` ratio or an hour outside every bin
    yields `?` rather than raising, because a label that cannot be placed is a fact a caller has to
    be able to see rather than an exception it can skip.
    """
    vol = next((name for lo, hi, name in VOL_BINS if lo <= ratio < hi), "?")
    h = int(hour)
    sess = next((name for lo, hi, name in SESSIONS if lo <= h < hi), "?")
    parts = [f"vol={vol}", f"sess={sess}"]
    if news is not None:
        parts.append("news=IN" if news else "news=out")
    return "|".join(parts)


def cell_of(i: int, ok: dict, atr: np.ndarray, atr_med: np.ndarray, hours: np.ndarray,
            news_mask: np.ndarray | None) -> str:
    """The declared cell label for the entry bar `i`."""
    ratio = float(atr[i]) / float(atr_med[i]) if atr_med[i] else float("nan")
    news = None if news_mask is None else bool(news_mask[i])
    return label_of_values(ratio, int(hours[i]), news)


def stats(rs: list[float]) -> dict:
    return ge.stats(rs)


#: The five state fields the EA APPENDS to the ledger's OPEN row at fill time (v1.19e), in order.
#: Defined by the WIRE CONTRACT (`midas_first_fills_audit`) and imported, not re-typed: the reader
#: owns the grammar, and a second copy of it is a second definition of the same row.
STATE_FIELDS = ffa.STATE_FIELDS


def decompose(by_cell_1: dict[str, list[float]], by_cell_2: dict[str, list[float]]) -> dict:
    """Split the H1->H2 change into COMPOSITION and WITHIN-STATE parts, with no selection.

    `mean_H2_at_H1_mix = sum_c w_H1(c) * mean_H2(c)` is what the second half would have averaged
    if its state mix had matched the first half's, cells weighted as H1 weighted them. Comparing
    three numbers answers the regime question without choosing a winner:

    * counterfactual near H1's mean  -> the states moved (composition),
    * counterfactual near H2's actual -> the states stopped paying (within-state).

    Cells present in H1 but absent in H2 are excluded from the counterfactual, and the surviving
    weight `w_cov` is reported, so a large exclusion cannot masquerade as a finding.
    """
    cells = sorted(set(by_cell_1) | set(by_cell_2))
    n1, n2 = len([x for v in by_cell_1.values() for x in v]), len([x for v in by_cell_2.values() for x in v])
    w1 = {c: len(by_cell_1.get(c, [])) / n1 for c in cells} if n1 else {}
    w2 = {c: len(by_cell_2.get(c, [])) / n2 for c in cells} if n2 else {}
    mean2 = {c: (sum(v) / len(v) if v else None) for c, v in by_cell_2.items()}
    covered = [c for c in cells if mean2.get(c) is not None]
    w_cov = sum(w1[c] for c in covered)
    counter = (sum(w1[c] * mean2[c] for c in covered) / w_cov) if w_cov else None
    return {"cells": cells, "w1": w1, "w2": w2, "mean2": mean2,
            "total_variation": 0.5 * sum(abs(w1[c] - w2[c]) for c in cells),
            "h2_at_h1_mix_mean_r": counter, "weight_covered": w_cov}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_persistence_state.json")
    a = ap.parse_args(argv)

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    rules = ThunderboltClassicRules(account_size=gg.ACCOUNT_SIZE)
    first, last = float(epoch[gw.WARMUP_BARS]), float(epoch[n - 1])
    mid = first + (last - first) / 2.0
    print(f"venue window: {datetime.fromtimestamp(first, timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(last, timezone.utc):%Y-%m-%d}  ({n} bars)")
    print(f"TIME split at {datetime.fromtimestamp(mid, timezone.utc):%Y-%m-%d %H:%M} UTC "
          f"(declared: the window midpoint, not a trade-count split)")
    print("declaration: docs/GOLD_PREREG_PERSISTENCE_STATE_20260921.md")

    entries = gg.run_grid(B, hours, ok, atr, pn.entry_config(PRIMARY_SESSION), n)
    trades = ge.simulate_policy(B, entries, atr, stop_mult=EXIT_STOP, **RULE)
    for t in trades:
        t["ct"] = float(epoch[t["entry_i"]])
    print(f"rule under study: stop {EXIT_STOP}xATR, NO target, <=48 bars, flat 22:00 | "
          f"{len(trades)} trades")

    # ---- the news axis, or an honest reason why not ----------------------- #
    news_mask, news_note = news_axis(epoch, n)
    print(f"news axis: {'MEASURED' if news_mask is not None else 'NOT MEASURABLE'} - {news_note}")

    atr_med = gw.trailing_percentile(atr, gw.ATR_LOOKBACK, 0.5)
    for t in trades:
        t["_cell"] = cell_of(t["entry_i"], ok, atr, atr_med, hours, news_mask)
    n_cells = len({t["_cell"] for t in trades})
    t_cell = gw.selection_threshold(n_cells)
    h1 = [t for t in trades if t["ct"] < mid]
    h2 = [t for t in trades if t["ct"] >= mid]
    print(f"cells present: {n_cells}  -> selection threshold for a best-of-{n_cells}: "
          f"t >= {t_cell:.3f}")
    print(f"H1 (before the midpoint): {len(h1)} trades   H2: {len(h2)} trades")

    # ---- the unfiltered rule, both halves --------------------------------- #
    s1, s2 = stats([t["net_r"] for t in h1]), stats([t["net_r"] for t in h2])
    print(f"\n== the rule with no state filter ==")
    print(f"  H1  n={s1['n']:>4} mean={s1['mean_r']:+.4f}R  sd={s1['sd']:.4f}  t={s1['t']:+.2f}")
    print(f"  H2  n={s2['n']:>4} mean={s2['mean_r']:+.4f}R  sd={s2['sd']:.4f}  t={s2['t']:+.2f}")

    # ---- descriptive: composition vs within-state (NO selection) --------- #
    print("\n== descriptive decomposition (no selection; declared to run regardless) ==")
    by_cell_1: dict[str, list[float]] = {}
    by_cell_2: dict[str, list[float]] = {}
    for t in h1:
        by_cell_1.setdefault(t["_cell"], []).append(t["net_r"])
    for t in h2:
        by_cell_2.setdefault(t["_cell"], []).append(t["net_r"])
    dec = decompose(by_cell_1, by_cell_2)
    cells, w1, w2 = dec["cells"], dec["w1"], dec["w2"]
    mean2, counter, tv = dec["mean2"], dec["h2_at_h1_mix_mean_r"], dec["total_variation"]
    print(f"  weight covered by the counterfactual: {dec['weight_covered']:.3f} of H1's trades")
    print(f"  H1 mix vs H2 mix: total variation of the state distribution = {tv:.3f}")
    print(f"  H2 actual mean                     = {s2['mean_r']:+.4f}R")
    print(f"  H2 at H1's state mix (counterfactual) = "
          f"{counter:+.4f}R" if counter is not None else "  counterfactual unavailable")
    if counter is not None:
        gap = s1["mean_r"] - s2["mean_r"]
        explained = (counter - s2["mean_r"]) / gap if gap else float("nan")
        print(f"  H1-H2 gap = {gap:+.4f}R, of which {explained:+.1%} is COMPOSITION "
              f"(a change in which states occurred) and {1 - explained:+.1%} is WITHIN-STATE")
    top = sorted(cells, key=lambda c: -(len(by_cell_1.get(c, []))))[:6]
    print(f"  {'cell':<40} {'H1 n':>5} {'H1 mean':>9} {'H2 n':>5} {'H2 mean':>9}")
    for c in top:
        m1 = (sum(by_cell_1[c]) / len(by_cell_1[c])) if by_cell_1.get(c) else None
        print(f"  {c:<40} {len(by_cell_1.get(c, [])):>5} "
              f"{(f'{m1:+.4f}' if m1 is not None else '-'):>9} "
              f"{len(by_cell_2.get(c, [])):>5} "
              f"{(f'{mean2[c]:+.4f}' if mean2.get(c) is not None else '-'):>9}")

    # ---- the declared selection, on H1 only ------------------------------- #
    print(f"\n== H1 selection (declared: highest H1 mean among cells with n >= {MIN_CELL_N}) ==")
    eligible = {c: v for c, v in by_cell_1.items() if len(v) >= MIN_CELL_N}
    if not eligible:
        print(f"  no cell reaches n >= {MIN_CELL_N} in H1")
        chosen, chosen_st, verdict, reason = None, None, "NO STATE RULE SURVIVES SELECTION", \
            f"no H1 cell reaches the declared minimum of {MIN_CELL_N} trades"
    else:
        chosen = max(eligible, key=lambda c: sum(eligible[c]) / len(eligible[c]))
        chosen_st = stats(eligible[chosen])
        print(f"  chosen on H1: {chosen}  n={chosen_st['n']} mean={chosen_st['mean_r']:+.4f}R "
              f"t={chosen_st['t']:+.2f}  (best of {len(eligible)} eligible of {n_cells} cells)")
        if chosen_st["t"] is None or chosen_st["t"] < t_cell:
            verdict = "NO STATE RULE SURVIVES SELECTION"
            reason = (f"the H1 winner's t={chosen_st['t']:+.2f} does not reach "
                      f"{t_cell:.3f}, the threshold for a best-of-{n_cells} pick")
        else:
            verdict, reason = "FROZEN - carrying it to H2", \
                f"H1 t={chosen_st['t']:+.2f} >= {t_cell:.3f} at n={chosen_st['n']}"
        print(f"  -> {verdict}: {reason}")

    h2_frozen = None
    if chosen is not None and verdict.startswith("FROZEN"):
        frozen_h2 = [t for t in h2 if t["_cell"] == chosen]
        h2_frozen = stats([t["net_r"] for t in frozen_h2])
        print(f"\n== H2 test of the frozen cell (SINGLE hypothesis, threshold 1.96) ==")
        print(f"  {chosen}")
        if h2_frozen["n"] < MIN_CELL_N:
            print(f"  H2 n={h2_frozen['n']} < {MIN_CELL_N}: INSUFFICIENT")
            verdict = "INSUFFICIENT (H2 sample)"
        elif h2_frozen["mean_r"] is None or h2_frozen["mean_r"] <= 0:
            print(f"  H2 mean={h2_frozen['mean_r']:+.4f}R -> KILL: the state rule is dead")
            verdict = "KILL"
        else:
            print(f"  H2 n={h2_frozen['n']} mean={h2_frozen['mean_r']:+.4f}R "
                  f"sd={h2_frozen['sd']:.4f} t={h2_frozen['t']:+.2f}")
            if h2_frozen["t"] >= gw.selection_threshold(1):
                verdict = "PASS (candidate state rule)"
                print(f"  -> PASS: t={h2_frozen['t']:+.2f} >= 1.96 on a frozen, H1-selected cell")
            else:
                verdict = "FAIL"
                print(f"  -> FAIL: t={h2_frozen['t']:+.2f} < 1.96 - the state does not carry "
                      f"the first-half behaviour forward")

    # ---- declared robustness line: same FROZEN cell, the derived stop ----- #
    rob = None
    if chosen is not None:
        alt = ge.simulate_policy(B, entries, atr, stop_mult=ROBUSTNESS_STOP, **RULE)
        for t in alt:
            t["_cell"] = cell_of(t["entry_i"], ok, atr, atr_med, hours, news_mask)
            t["ct"] = float(epoch[t["entry_i"]])
        sel = [t["net_r"] for t in alt if t["ct"] >= mid and t["_cell"] == chosen]
        rob = stats(sel)
        # LABELLED POST-HOC: when the H1 winner fails the priced threshold, the declaration says
        # step 5 does NOT run. This line is therefore an extra observation, not the declared test,
        # and it must carry that label wherever it is quoted.
        print(f"\n== POST-HOC observation, OUTSIDE the declaration: the H1 winner's cell at stop "
              f"{ROBUSTNESS_STOP}xATR ==")
        print(f"  (the declaration fixed that no cell is carried to H2 when the H1 selection "
              f"fails its threshold; this is what happened to the cell that failed)")
        print(f"  H2 n={rob['n']} mean={rob['mean_r']:+.4f}R t={rob['t']:+.2f}")

    print("\nNothing here is a validation: one forward half of one window. The forward record "
          "remains the only instrument that can validate a rule.")

    out = {
        "declared": {"document": "docs/GOLD_PREREG_PERSISTENCE_STATE_20260921.md",
                     "split": "time, at the window midpoint",
                     "axes": {"volatility": "ATR vs causal trailing median (0.8x / 1.3x)",
                              "session_utc": [s[2] for s in SESSIONS],
                              "news": f"+/-{NEWS_WINDOW_MIN} min around HIGH releases"},
                     "min_cell_n": MIN_CELL_N,
                     "cells_present": n_cells,
                     "t_required_selection": round(t_cell, 4),
                     "t_required_h2": round(gw.selection_threshold(1), 4),
                     "geometry_not_reoptimised": True,
                     "contamination": ("the trigger and the exit geometry were found on this same "
                                       "window; H2 is a holdout for the STATE conditioning only")},
        "window": [str(datetime.fromtimestamp(first, timezone.utc)),
                   str(datetime.fromtimestamp(last, timezone.utc))],
        "midpoint": str(datetime.fromtimestamp(mid, timezone.utc)),
        "news_axis": {"measured": news_mask is not None, "note": news_note},
        "unfiltered": {"h1": s1, "h2": s2},
        "descriptive_composition": {"total_variation": round(tv, 4),
                                    "weight_covered": round(dec["weight_covered"], 4),
                                    "h2_actual_mean_r": s2["mean_r"],
                                    "h2_at_h1_mix_mean_r": (round(counter, 4)
                                                            if counter is not None else None),
                                    "gap_r": round(s1["mean_r"] - s2["mean_r"], 4),
                                    "cells": {c: {"h1_n": len(by_cell_1.get(c, [])),
                                                  "h2_n": len(by_cell_2.get(c, [])),
                                                  "h1_mean_r": (round(sum(by_cell_1[c])
                                                                      / len(by_cell_1[c]), 4)
                                                                if by_cell_1.get(c) else None),
                                                  "h2_mean_r": (round(mean2[c], 4)
                                                                if mean2.get(c) is not None else None)}
                                              for c in cells}},
        "h1_selection": {"chosen_cell": chosen, "h1_stats": chosen_st,
                         "eligible_cells": len(eligible) if eligible else 0},
        # `carried_to_h2` is load-bearing: when the H1 selection fails its priced threshold the
        # declaration forbids carrying a cell, so `stats` is None and the only thing recorded is
        # which candidate was REJECTED. Labelling that field "frozen_cell" invited a reader to
        # take a rejected candidate for a live rule.
        "h2_test": {"carried_to_h2": bool(h2_frozen is not None), "candidate_cell": chosen,
                    "stats": h2_frozen},
        "robustness_stop_1_384": rob,
        "robustness_is_post_hoc_not_declared": True,
        "verdict": verdict, "reason": reason,
    }
    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"artifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
