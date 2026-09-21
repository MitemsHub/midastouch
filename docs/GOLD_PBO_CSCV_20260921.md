# PBO by CSCV: the selection procedure itself, measured

**Date** 2026-09-21. **Harness** `scripts/gold_governed_wfo.py --mode pbo` (1m55s) →
`artifacts/gold_pbo.json`. **Method** Combinatorially Symmetric Cross-Validation
(Bailey et al., 2017), implemented as `gold_walkforward.probability_of_backtest_overfitting`.
**Closes** the gap `docs/GOLD_DECIDABILITY_AUDIT_20260921.md` named as "could not check".

## Why this is a different question from V7

V7 asks whether the reported winner is distinguishable from noise. PBO asks whether the
**procedure that picks winners** is any good: when this walk-forward selects a configuration on
past folds, how often is the one it picks below the median on the folds it did not see? A high
PBO indicts the selection scheme rather than any single result it produced — which is what the
audit suspected and could not test.

## The result

Matrix: the frozen **24-config grid × 31 walk-forward folds**, per-fold net R for every
configuration, built through the same fold definition, bar slicing and governor as
`walk_forward()` itself. S=8 groups → **70 symmetric splits**, each half serving as
in-sample and out-of-sample in turn.

| | PBO | distinct winners | median OOS rank (of 24) | mean logit |
|---|---|---|---|---|
| **governed** (the procedure the gate certifies) | **38.6%** | 11 | **18.0** | +0.377 |
| raw (no governor) | 47.1% | — | — | — |

Full-sample best: config 10 — `emas (8,21,50), stop 1.5, tp 3.0, session 7–20`.

**How to read it.** At 47.1% the ungoverned procedure's in-sample winner lands at or below the
out-of-sample median essentially as often as a coin flip. Applying the governor improves that
to 38.6% — still more than a third of splits — and, more tellingly, the in-sample winner's
**median rank out of 24 is 18th** out-of-sample: the configuration this procedure picks
typically finishes in the bottom quarter of the field when it is finally tested. Eleven
different configurations win across the 70 splits, which is what a procedure with no stable
preference looks like.

## The estimator's own noise, measured before trusting the number

CSCV over 70 splits is a coarse estimate, so the harness was calibrated on matrices that
contain no signal at all: **24 configurations of pure Gaussian noise × 31 windows**, twelve
generated worlds. Mean PBO **0.48** — the estimator is unbiased — but the single-realisation
range was **0.186 to 0.771**. So one PBO number is a statement about the procedure with wide
error bars, and the companion statistics (median OOS rank, distinct-winner count) are the
stable part of the reading. Both are recorded in the artifact. The calibration is pinned in
`tests/test_gold_pbo_and_prereg.py` as an average over seeds rather than a single seeded
assertion, because pinning one seed pins the seed and not the method.

## What follows from it

- **Do not read the 38.6% as safety.** It is a third of splits where a selected configuration
  does not persist, on a search of only 24 alternatives. A 168-configuration search would be
  worse, which is what the audit's ceiling table already implied from the other side.
- **It independently supports the shape of the next test, not another sweep.** The single
  measurement that cleared its own threshold (the no-target exit,
  `docs/GOLD_NO_TARGET_SINGLE_TEST_20260921.md`) did so with **one declared hypothesis** — no
  selection, so no PBO to compute. That is the escape route this number points at.
- **It is a diagnostic and cannot fail or pass the gate.** It is deliberately not a V-check: a
  count of how often a procedure misfires is not a property of one run of it.

## Still open

The `--risk-usd 75` default in `gold_walkforward.py` against the arm's $250 basis
(1% of $25,000) remains unreconciled; it feeds only the `prop_compat` block, so no verdict has
moved, and the audit lists it as an open item.
