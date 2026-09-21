# The decidability audit — does any number this program has measured clear its own search cost?

**Date** 2026-09-21. **Harness** `scripts/gold_stats_audit.py` (re-runnable; writes
`artifacts/gold_stats_audit.json`). **Gate change** protocol Amendment 8 (§17).

This is the audit the program had never run on itself. Every study here ends with a
t-statistic, and the arming gate used `t >= 1.5` — a threshold for **one** hypothesis.
None of these studies tested one. The stored artifacts hold 168 entry geometries, 24
trigger cells, 14 exit policies and a 24-config walk-forward grid, and in each case the
number reported is the **best of them**.

## The arithmetic this changes

When the reported result is the best of N trials, its null distribution is the maximum of
N draws, not a single draw. Measured here by seeded Monte Carlo (`gold_walkforward.
max_abs_z_stats`):

| trials searched | E[max \|z\|] | 95th pct — **the threshold to beat** |
|---|---|---|
| 1 | 0.797 | **1.960** |
| 5 | 1.569 | 2.567 |
| 13 | 1.993 | 2.883 |
| 24 | 2.237 | **3.071** |
| 48 | 2.495 | 3.274 |
| 168 | 2.913 | **3.612** |

The 1.96 everybody quotes is the N=1 cell of this table. A gate at 1.5 is below every cell,
including the single-test one — which is why it could not fail a search. Harvey et al.
(2016) reach the same number from the data-mining side (~3.0, not 2.0).

## Every entry-side family is below its own noise threshold

| family (trials) | best member | n | mean R | t | threshold | verdict | DSR (upper bound) |
|---|---|---|---|---|---|---|---|
| entry geometry, governed (168) | 7–20h, stop 1.5, tp 3.0 | 302 | +0.0316 | **+0.40** | 3.61 | **below** | 0.0037 |
| entry geometry, ungoverned (168) | 12–16h, stop 1.5, tp 3.0 | 270 | +0.0816 | **+0.94** | 3.61 | **below** | 0.5272 |
| trigger conditional cells (24) | aligned DOWN × 17–22 UTC | 469 | +0.1329 | **+2.36** | 3.07 | **below** | 0.1447 |
| exit geometry, fixed entries (14) | fixed stop 1.0, **no target** | 912 | +0.3221 | **+3.06** | 2.90 | **CLEARS** | 0.7586 |

Read the third row against the way this was reported when it was found: at t=+2.36 the
short-side late-window cell looked significant against 1.96 and looked *arbitrable*. It is
2.36 where noise over 24 cells produces 3.07. It was never evidence, and the pre-registered
follow-up (`docs/GOLD_PREREG_LATE_SHORT_20260921.md`) already said so from the other side:
**INSUFFICIENT EVIDENCE**, n=120 against a declared 190.

**One thing clears: the exit geometry.** `fixed stop 1.0, no target` at +0.3221R over 912
trades, t=+3.06 against a threshold of 2.90 for the 14 policies compared — marginal, and it
is the one measurement in this program that is both large and adequately sampled. It is
also the one whose **deployability** the exit-family walk-forward falsified
(`docs/GOLD_EXIT_FAMILY_AND_HARD_SWITCH_20260921.md`): selection on the governed prior fold
picked a target-free arm in 20 of 30 folds and produced −46.38R with fold-mean t=−2.16.

Those two results are not in conflict, and the distinction is the useful part: *re-pricing a
fixed entry set* measures the exit, while *walk-forward selection* re-picks the entry set and
the occupancy, and a target-free trade holds the slot for hours. The finding is a property of
the exit geometry that has not yet been shown to survive as a **rule**.

## What would flip the answer, in trades

Required sample at the measured effect size, `n = ceil((t_req·sd/mean)²)`:

| sample | n | mean R | valid t | trades for t≥1.5 | trades for its own threshold |
|---|---|---|---|---|---|
| venue, combined 2026-01-12…09-16 | 160 | +0.0680 | +0.79 | 570 | **2,130** (t≥3.61) |
| pre-registered late short | 120 | +0.0963 | +0.70 | 552 | 3,201 |
| exit geometry, no target | 912 | +0.3221 | +3.06 | 22 | 375 |

The program's live question — a configuration reaching +0.15R/trade — clears a *single*
pre-registered test at roughly `(1.96·1.08/0.15)² ≈ 200` trades. That is the target worth
aiming at, because it is inside the venue's reach (this account does ~240 trades/year).
The current +0.068R family needs 2,130 trades for its own selection threshold — about
**9 years** of this arm's flow. That is not a patience problem, and the honest conclusion is
that the entry family is the wrong search, not an unfinished one.

The exit geometry's 375-trade requirement is already met by the 912 trades that produced it.
So the next step that is worth doing is not more entry search: it is a **pre-registered,
single-hypothesis** exit test (N=1, threshold 1.96) with the no-target rule declared in
advance — the shape of test this measurement has never been given.

## The amended gate, applied to the frozen record

`artifacts/gold_wfo.json` predates V7 and is **not regenerated**: re-running the harness on
today's bars would move V1–V6 as well, which is a re-baseline, not an amendment. Applying
the amendment to the record's own stored stats instead:

```
artifact verdict: NOT VALIDATED
its stored stats: t = +0.524 over 30 folds
V7 threshold for 24 trials searched: 3.07
-> V7 FAILS   (the record already printed NOT VALIDATED, so the amendment
               cannot have weakened it)
```

## Gaps this audit could not close

- ~~**PBO (CSCV)** needs a config × window performance matrix.~~ **CLOSED 2026-09-21.**
  `scripts/gold_governed_wfo.py --mode pbo` now retains the frozen grid's config × fold
  matrix and computes it: **PBO = 38.6% governed, 47.1% raw**, with the in-sample winner's
  median out-of-sample rank at **18th of 24**. The estimator was calibrated on pure-noise
  matrices first (mean 0.48, single-realisation range 0.186-0.771), so the number carries
  its own error bars. Full record: `docs/GOLD_PBO_CSCV_20260921.md`, artifact
  `artifacts/gold_pbo.json`, pins `tests/test_gold_pbo_and_prereg.py`.
- **DSR is an upper bound.** No artifact stores per-trade returns, so skew/kurtosis are
  assumed normal. Fat tails — this program measures sd up to 3.18R — make the true DSR
  *lower*. Conservative for a refusal, wrong for an arming argument, and said so.
- **Two headline samples exist only in prose.** The venue 160-trade and first-quarter
  53-trade samples from `docs/GOLD_ARMING_DECISION_20260921.md` were printed by a shell
  command that stored nothing, so nothing re-checks them. They are carried in the audit as
  `TRANSCRIBED` and labelled as such. The harness should write an artifact.
- **A basis mismatch**: `scripts/gold_walkforward.py` defaults `--risk-usd 75` while the arm
  trades 1% of 25,000 = 250. The certified checks do not consume it — only the `prop_compat`
  block does — so no verdict moves, but the two bases should be reconciled.

## Re-running it

```bash
python scripts/gold_stats_audit.py          # the tables above, plus artifacts/gold_stats_audit.json
python -m pytest tests/test_gold_walkforward.py -q   # the V7 pins
```

The ceilings are seeded, so these numbers reproduce exactly.
