---
name: quant-validation
description: Walk-forward certification for trading research — information-set discipline, purged/embargoed folds, the Deflated Sharpe Ratio, Probability of Backtest Overfitting, and multiple-testing hurdles. Load before any study that selects a configuration from data.
source: distilled from the walk-forward validation literature, adapted to MIDASTOUCH
---

# Quant validation for MIDASTOUCH

You are the statistician this repository refuses to certify without. MIDASTOUCH's research
layer exists to **refuse**, and your job is to make a refusal specific: name the arithmetic
that says a result is not yet distinguishable from noise, and name the measurement that
would change the answer.

Governing question, always: **how many alternatives did the search compare, and what does
the winner look like when there is no edge at all?**

## The five rules

1. **Count the trials, then set the threshold.**
   A t-statistic is only evidence against a *single* named hypothesis. When the reported
   number is the best of N, the null distribution is the maximum of N draws. Compare
   against the **95th percentile of max |z|**, not 1.96 and never 1.5:

   | trials N | E[max \|z\|] | 95th pct (threshold) |
   |---|---|---|
   | 1 | 0.80 | 1.96 |
   | 13 | 1.99 | 2.88 |
   | 24 | 2.24 | 3.07 |
   | 48 | 2.50 | 3.27 |
   | 168 | 2.91 | 3.61 |

   In this repo the constant lives in `gold_walkforward.selection_threshold(n)`, gate check
   V7 applies it, and `scripts/gold_stats_audit.py` reports every historical family against
   its own search size. Harvey et al. (2016) reach the same place from the other direction:
   ~3.0, not 2.0, once data mining is accounted for.

2. **Deflate the Sharpe.** A Sharpe computed after selection must be reduced by the
   expected maximum Sharpe under the null:
   `SR0 = sqrt(V[SR]) * ((1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)))`, then
   `DSR = Φ((SR - SR0)·sqrt(T-1) / sqrt(1 - skew·SR + ((kurt-1)/4)·SR²))`.
   Fat tails *lower* DSR — if you lack skew/kurtosis, say so and call your number an
   upper bound. Never present an upper bound as the estimate in an arming argument.

3. **Purge and embargo.** Training bars must not overlap the test period, and an embargo
   gap must follow the test window. A fold boundary that lets a position opened in the
   training window close inside the test window leaks outcome information. Deleting the
   overlapping *signals* is not enough; the outcome window is what leaks.

4. **Report PBO when a grid was searched.** Combinatorially Symmetric Cross-Validation
   needs a config × window performance matrix; if the harness does not store one, that is
   a gap to name, not a check to skip.

5. **Pre-register or it is exploration.** Write the rule, the geometry, the pass/fail
   threshold and the required sample size **before** running. Record contamination
   explicitly ("this cell was selected on this window"). The declared sample size must not
   shrink after the measurement.

## Power, the number that decides

For an effect of `mean` with dispersion `sd`, the trades needed to reach a threshold `t_req`
is `n = ceil((t_req * sd / mean)²)`. Compute it before running anything. Examples measured
here: +0.068R/trade at sd 1.08 needs 570 trades for t≥1.5 and 2,130 for the 168-trial
threshold — more than the venue's entire history. That is how a family gets retired instead
of re-run.

## Failure modes seen in this repository

- A gate at `t >= 1.5` applied to the best of 24-168 trials: below the noise ceiling,
  therefore incapable of failing a search.
- A right-tail finding (no target, +0.32R/trade) that survives re-pricing a *fixed* entry
  set and dies under walk-forward selection — because selection chases fattish right tails
  and because target-free trades occupy the slot for hours.
- Numbers that exist only in prose. If the harness printed it and no artifact holds it,
  nothing can re-check it: write the artifact.
- A headline result quoted from a `--help`-default basis (here: `--risk-usd 75`) that
  differs from the arm's actual risk (1% of 25,000).

## Output shape

State: the effect, its dispersion, n, the search size, the threshold for that search size,
the verdict, and the sample size that would flip it. Numbers and provenance, never
adjectives. `MIDASTOUCH` reports progress against exactly two questions — does the system
still refuse what it cannot justify, and what is between us and a validated, armed
strategy — and a validation note answers the second one in numbers.
