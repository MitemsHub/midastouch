# Pre-registration: the derived-stop no-target configuration (N=1)

**Declared** 2026-09-21, before the measurement. **Harness** `scripts/gold_prereg_derived_stop.py`
→ `artifacts/gold_prereg_derived_stop.json`. **Threshold** **1.96**, the single-hypothesis
value (`selection_threshold(1)`), because nothing here is selected.

## Why the stop is the component left to build

Three things are now measured and only three:

1. the trigger carries information — post-signal forward drift +0.113 ATR at 8 bars
   (t=+3.52) and +0.177 at 16 (t=+3.97), n=5,098;
2. the fixed take-profit destroys it — on identical entries, no target returns **+0.4230R**
   per trade (t=+3.28) where the arm's own 2.0R target returns **+0.0100R** (t=+0.18)
   (`docs/GOLD_NO_TARGET_SINGLE_TEST_20260921.md`);
3. **the stop was never varied in that work.** Every policy in the exit study priced against
   one risk unit — `stop = 1.0 × ATR`, held constant so the comparison would be about exits —
   and the trigger study's stop variants (1.0, 1.5) were geometry pairs, not a derivation.

So the stop is the one exit component still set by convention rather than by measurement.

## The derivation rule, declared before the number exists

Let `|MAE|` be the adverse excursion in R at the **8-bar** horizon, measured with the
discovery's own convention (`R = 1.0 × ATR` at the entry bar, pessimistic marks), over the
**discovery entry set** (session 0–24 UTC, 912 entries). Then:

> **k = the 70th percentile of `|MAE|`, and the stop is `k × ATR`.**

Rationale, fixed here so it cannot be reverse-fitted: the median adverse excursion is where
*half* the noise sits, and a stop placed at the median converts ordinary wandering into losses.
The 70th percentile keeps 70% of the measured adverse wandering *inside* the stop, leaving
~30% of entries to be stopped — a rate that is meaningful for a rule whose upside is unbounded
and whose downside is capped at 1R by construction.

**The derivation runs on the discovery set; the test runs on the arm's session, which the
derivation does not use.** The stop multiple is therefore fitted on one entry set and measured
on another, which is strictly stronger than the parent test (whose rule was both selected *and*
measured on related entries).

## The rule as tested

| | |
|---|---|
| **stop** | `k × ATR(H1)` with `k` from the derivation above |
| **take-profit** | **none** |
| **session flat** | flat by **22:00 UTC** — the frozen engine's rule, unchanged |
| **time limit** | 48 bars |
| **risk unit** | 1R = the stop distance, so a stop-out is exactly −1R and sizing follows the wider stop automatically |
| **costs** | the frozen model (spread `SPREAD_BPS`, commission `COMMISSION_PER_LOT_RT`) |
| **test entry set** | the arm's session, **06–20 UTC** (658 entries, the parent test's primary set) |

## Required sample, declared up front

From the parent test's discovery effect (`mean` +0.3221, `sd` 3.1838):

| requirement | trades |
|---|---|
| t = 1.96 | **375** |
| 80% power at α = 0.05 | **766** |

A wider stop changes the R unit and therefore the dispersion, so the verdict also computes the
implied requirement at the *realized* effect, `ceil((1.96·sd/mean)²)`, and applies the **more
demanding** of the two: `INSUFFICIENT` whenever `n` falls short of either.

## Comparators, declared

- the same rule at the conventional stop, `k = 1.0 × ATR` (the parent test's rule) — so
  re-deriving the stop is judged against not re-deriving it;
- the arm's current exit (`stop 1.0 × ATR`, target 2.0R) on the same entries, for scale.

## Secondary, declared as INFORMATION and not as selection

A sensitivity table over stop multiples and the derivation quantile is printed and stored. The
verdict uses **only** the single declared `k`; a table is there to show how flat or sharp the
ridge is, and choosing a value from it after the fact would be exactly the search this
document exists to preclude.

## Falsifiers, fixed here

- **UNSOUND DERIVATION** — the derived stop is hit on fewer than 20% or more than 70% of
  entries. That means the quantile rule was mis-specified for this excursion distribution, and
  the result may not be reported as a test of it.
- **KILL** — primary mean ≤ 0. The derived-stop no-target family is retired; no other quantile
  or multiple is then tried.
- **FAIL** — t < 1.96 at n ≥ the required sample.
- **INSUFFICIENT** — n below either requirement, whatever t says.

## Contamination, stated first

The excursion distribution, the entry sets, the trigger and the window are all the same eight
months the parent test used. Deriving the stop on the discovery set removes *that* contamination
from the test set, and nothing removes the fact that this window is where every number in this
program was discovered. **This is a pre-registered measurement, not an out-of-sample
validation**; `docs/GOLD_FORWARD_PREREG_20260921.md` remains the only instrument that can
validate a rule, and a 0.25%-risk forward record is the shortest route to it
(`docs/GOLD_NO_TARGET_SINGLE_TEST_20260921.md`).

## What would make this deployable rather than merely significant

The parent test showed the no-target rule cannot be run at the arm's 1% risk: at $250/R the
venue's $750 daily line is 3R away and 13 days were breached. A **wider stop does not fix
that by itself** — 1R becomes a larger price move, so the dollar risk per trade rises at a
fixed size. So this test also reports the same post-hoc sizing scan, labelled as post-hoc, at
1.00%, 0.75%, 0.50% and 0.25% of a $25,000 account. The rule is frozen for it; only $/R moves.

Run and verdict: `docs/GOLD_DERIVED_STOP_TEST_20260921.md`.
