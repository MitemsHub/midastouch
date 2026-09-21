# The derived-stop no-target configuration: run and verdict

**Date** 2026-09-21. **Declaration** `docs/GOLD_PREREG_DERIVED_STOP_20260921.md` (written
first). **Harness** `scripts/gold_prereg_derived_stop.py` → `artifacts/gold_prereg_derived_stop.json`.
**Window** 2026-01-12 13:15 → 2026-09-21 16:00 UTC (16,289 bars). **Threshold** t ≥ 1.96 (N=1).

## The derivation, and the check that it fired

| statistic of `|MAE|` at 8 bars (R of 1.0 ATR), n=906 | value |
|---|---|
| 25th percentile | 0.042R |
| 50th percentile | 0.694R |
| **70th percentile — the declared stop** | **1.384R** |
| 90th percentile | 2.642R |
| mean | 1.092R |

**k = 1.384 × ATR**, so 1R is 1.384 ATR and a stop-out is still exactly −1R. The stop-out rate
came back **30.0% on the discovery set** — the 70th percentile reproducing its own definition —
and **28.3% on the primary set**, both inside the declared sound band of 20–70%. The derivation
is therefore admissible as a test subject, which the declaration made a precondition.

## The result

Primary entry set (the arm's session, 06–20 UTC; entries the derivation never saw), 658 trades:

| rule | mean net R | sd | **t** | total |
|---|---|---|---|---|
| **derived stop 1.384×ATR, no target** | **+0.3726** | **2.5870** | **+3.69** | +245.1R |
| same rule, conventional stop 1.0×ATR | +0.4230 | 3.3110 | +3.28 | +278.3R |
| **the arm's live exit** (stop 1.0, target 2.0R) | +0.0100 | — | +0.18 | +6.6R |
| derived stop + target 2.0R | +0.1017 | — | +1.90 | +66.9R |

**Verdict: `POSITIVE, UNDERPOWERED`** — t=+3.69 clears 1.96 comfortably, n=658 is below the
declaration's 766 power requirement. (The realized-effect requirement was only 186 trades, so
the binding constraint is the declared power bar, not this effect's size.)

## The honest reading: the derivation bought decidability, not money

It is tempting to call a rise in t from 3.28 to 3.69 an improvement. It is not an improvement in
the thing that pays. **The mean fell by 0.0504R (−12%) while the dispersion fell by 0.724 (22%)**,
and a smaller denominator is the whole of the t gain. The derived stop converts a slightly richer
rule into a slightly poorer but far more measurable one.

That is a genuine result, stated plainly: **the 70th percentile of the adverse excursion is not
where the money is; it is where the noise is.** The excursion distribution's mean adverse move is
1.092R, so a stop at 1.384R sits past the typical wander — which is why 30% of entries still get
stopped and why the survivors' larger R denominator shrinks every winner in R terms.

**One qualification this run owes the previous document.** The parent test reported a 42×
difference from removing the target and read it as the target being the villain. The fourth row
above qualifies that: at the derived stop, the arm's own 2.0R target gives t=+1.90 — against
**t=+0.18** at the conventional stop. So the arm's live geometry is the **worst of the four**
combinations tested, and the stop/target **pair** was mis-specified together, with the target the
larger of the two terms. "The target is the only problem" was too narrow.

## The table the declaration forbade choosing from

Printed as information only; the declared `k` was not changed after seeing it:

| stop | mean net R | t |
|---|---|---|
| 0.694×ATR (the **median** |MAE|) | **+0.6031** | +3.53 |
| 0.750×ATR | +0.5044 | +3.17 |
| 1.000×ATR | +0.4230 | +3.28 |
| **1.384×ATR (declared)** | +0.3726 | +3.69 |
| 1.500×ATR | +0.3581 | +3.78 |
| 2.000×ATR | +0.3436 | **+4.39** |

The mean is highest at the tightest stop and the t is highest at the widest: **the two criteria
disagree, and neither extreme is where the declaration landed.** Worth recording, because it is
exactly the shape that produces post-hoc story-telling, and choosing the mean-maximising row now
would be the selection this entire apparatus exists to prevent. If a tighter stop is worth
testing, it needs its own declaration and its own test.

## Decay, third time

Halves in entry order: **+0.5713R (t=3.55)** then **+0.1738R (t=1.44)**. The same shape has now
appeared in the late-session short, the parent no-target test, and here. Whatever this edge is, it
is not stationary across the venue's eight months, and no version of the rule has been shown to
survive the second half at significance.

## Deployability

| risk / R | % | trades kept | worst day | vs $750 line | days beyond |
|---|---|---|---|---|---|
| $250 | 1.00% | 42 | −$790 | over | 7 |
| $187.50 | 0.75% | 51 | −$789 | over | 5 |
| $125 | 0.50% | 89 | −$788 | over | 1 |
| **$62.50** | **0.25%** | 509 | −$459 | inside | **0** |

The wider stop helps here — 7 days beyond the line at 1% risk against the parent rule's 13 — but
the conclusion is unchanged: **0.25% of a $25,000 account is the only scanned size whose worst day
stays inside the venue's rule.** Post-hoc, rule frozen, labelled as such.

## What this does not say

Not a validation. The same window discovered it; the derivation used the discovery entry set and
the test used another, which removes one kind of contamination and none of the others. Nothing
here authorises an order. The forward record remains the only instrument that can validate a rule,
and the honest summary of this run is: **a measurable, decaying, session-flat, target-free rule
whose stop is now set by the data rather than by convention, deployable only at a quarter of the
size the arm is currently running.**
