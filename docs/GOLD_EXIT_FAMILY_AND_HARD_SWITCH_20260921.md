# The free exit, and the hard daily switch

**Date:** 2026-09-21 · **Harness:** `scripts/gold_exit_family_wfo.py` (new)
**Artifact:** `artifacts/gold_exit_family_wfo.json`
**Declaration (written before the run):** `docs/GOLD_PREREG_EXIT_FAMILY_20260921.md`
**Window:** the venue's served bars, 16,287 M15, 2026-01-12 .. 2026-09-21; 30 OOS folds.

---

## 1. The free exit: the selection prefers it, and the result gets worse

The declared grid (48 configurations: 2 trend sets × 2 sessions × 2 stops × 6 exit arms),
the frozen folds, the frozen V1–V6 criteria, the entry-only governor on both sides.

| | certified grid | **exit-family grid** |
|---|---|---|
| OOS trades | 270 | 231 |
| total | −30.35R | **−46.38R** |
| mean per fold | −1.01R | **−1.55R** |
| fold-mean t | −1.32 | **−2.16** |
| random-entry control | −60.98R | −12.82R |
| V1 / V2 / V3 / V4 / V5 / V6 | 5 fail | **6 fail** |
| final equity | $17,411.91 | $13,294.31 |
| shield / daily breaches | 5 / 5 | **5 / 5** |

The selection chose a target-free arm in **20 of 30 folds** (`noTarget-hold` 12,
`noTarget-48b` 4, `trail1.0/0.5-48b` 4, `tp1.5` 5, `tp2.0` 4, `tp3.0` 1) — so **the
hypothesis' first half holds and its prediction is falsified**: the out-of-sample total is
*worse* than the certified grid's, and **V4 fails**, meaning the fold selection now loses
more than random entries with the same geometry and trade counts.

**Why, stated as the mechanism rather than as bad luck.** `docs/GOLD_EXIT_CAPTURE_AND_FILTERS_20260921.md`
measured +0.3221R/trade for a target-free exit by re-pricing a **fixed** entry set. Two
things that measurement held constant are precisely what the walk-forward moves:

1. **Occupancy.** A target-free trade can run for hours, so it consumes signal slots the
   certified exit would have turned over — 231 OOS trades instead of 270, from the same
   signals. Part of the fixed-entry advantage was collecting moves that the next entry would
   otherwise have banked.
2. **Selection.** The walk-forward picks, each fold, whichever arm won the previous 8 days.
   Target-free arms have fatter right tails, so their prior-fold totals are noisier, and the
   selector chases them exactly when the win was luck. The −12.82R control makes the same
   point from the other side: what the selection is choosing is largely noise.

So the exit finding survives as a *statement about geometry* (the certified target captures
2.6% of the available excursion; an uncapped exit captures 28.6% on fixed entries) and dies
as a *deployable rule* under this selection scheme. That distinction is the result.

## 2. The hard 3% daily switch: the best total, the worst single day

Three governor policies on the certified 24-config grid, fold by fold, 1R = $250 on $25,000:

| policy | total | OOS trades | folds positive | final equity | worst day | shield/daily |
|---|---|---|---|---|---|---|
| entry-only (on the chart) | −30.35R | 270 | 11/30 | $17,411.91 | −3.23R (−$806) | 5 / 5 |
| path (mark, keep trading) | −35.71R | 390 | 8/30 | $16,072.63 | −4.79R (−$1,196) | 5 / 5 |
| **hard 3% (flatten + stand down)** | **−17.06R** | 413 | 12/30 | $20,735.01 | **−5.40R (−$1,351)** | **5 / 4** |

**What the hard switch costs, in R terms:** it is worth **+13.29R** against the entry-only
governor over this window (−17.06R vs −30.35R, i.e. roughly half the drawdown), it removes
one of the five daily breaches, and it edits the day's outcome by flattening the open trade
at the mark and refusing **3,402** further entries across **50** stood-down days (50 switch
firings).

**And the daily rule still breaches.** Worst day −5.40R = −$1,351 against the $750 cap, the
worst of the three policies. The mechanism is the same one measured twice already: marks are
**bar closes**, so a bar that crosses the line is already through it when the switch sees it —
and flattening at that mark *crystallises* the overshoot instead of letting a later recovery
inside the same day net it back. Four of the five daily breaches move to different dates
(01-29, 02-13, 03-09 remain; 04-07 is replaced), which is what a boundary draw does.

**Consequence.** The 3% daily rule cannot be enforced by *when* entries are allowed, by
*how* the open trade is marked, or by flattening at the line. The only lever with a
mechanism behind it is **risk per trade**: the wall is $750 = 3R, so the breach is a
statement about trade size, not trade selection.

## 3. What stands after these two measurements

| lever | measured effect | verdict |
|---|---|---|
| richer exit grid, fold-selected | −46.38R vs −30.35R | **worse** — falsified, per §1 |
| exit geometry, fixed entries | +0.0294R → +0.3221R | real, **not deployable** under fold selection |
| path governor (mark + keep trading) | −35.71R | worse |
| hard 3% switch (flatten + stand down) | −17.06R, still breaches | best of the three, insufficient |
| low-volatility state filter | −15.37R, breaches identical | halves the loss, not the rule |
| late-session short cell (pre-registered) | +0.0963R, t=+0.70 | insufficient evidence, decays |

Every entry-side and exit-side lever this program has measured leaves the venue's daily rule
intact. **The live arm is unchanged**: certified exit (target 2.0R per its preset),
entry-only governor, operator override, `artifacts/live/armed.json` untouched.
