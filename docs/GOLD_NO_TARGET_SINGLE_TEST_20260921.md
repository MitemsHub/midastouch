# The no-target exit as a single declared hypothesis: run and verdict

**Date** 2026-09-21. **Declaration** `docs/GOLD_PREREG_NO_TARGET_20260921.md` (written before
this run). **Harness** `scripts/gold_prereg_no_target.py` → `artifacts/gold_prereg_no_target.json`.
**Window** 2026-01-12 13:15 → 2026-09-21 16:00 UTC (16,289 bars, the venue's served window).
**Threshold** t ≥ 1.96 — legitimate here because N=1 (`selection_threshold(1)`), where every
other study in this program owes 3.07 or 3.61.

## The result

| entry set | n | mean net R | sd | **t** | total |
|---|---|---|---|---|---|
| **primary — the arm's session 06–20 UTC** (entries the rule was not selected on) | 658 | **+0.4230** | 3.3110 | **+3.28** | +278.3R |
| discovery — 0–24 UTC (in-sample by construction) | 912 | +0.3221 | 3.1838 | +3.06 | +293.8R |

The discovery leg reproduces `artifacts/gold_exit_capture.json` **exactly** — +0.3221R over
912 — so the harness is measuring the same thing it measured when it found this, and the
primary is a real second measurement rather than a restatement.

**Verdict: `POSITIVE, UNDERPOWERED`.** t=+3.28 clears 1.96 at n=658, which is below the
declaration's own 766-trade power requirement. The rule is therefore a *positive finding not
yet a validated rule*, exactly the category the declaration created for this case. It is not
a pass, and it is not evidence for arming.

## What the run adds that the discovery could not

**1. The target is where the money goes.** On the *same 658 entries*, nothing varying but the
exit:

| exit on identical entries | mean net R | t |
|---|---|---|
| **no target**, stop 1.0R, flat by 22:00 | **+0.4230** | **+3.28** |
| the arm's target 2.0R | **+0.0100** | +0.18 |
| the certified target 3.0R | +0.0686 | +1.03 |

The arm's own exit earns +0.01R per trade on entries that are worth +0.42R when the target is
removed. That is a **42× difference on identical signals**, and it is the cleanest measurement
this program has ever produced: same entries, same costs, one rule changed.

**2. The effect survived a change of entry set.** The rule was selected on the widest-session
(0–24) entries; the primary set is the arm's session (06–20), 658 different entries. It got
*stronger* there (+0.42R vs +0.32R). That is a stronger check than the discovery's own halves
split, and it is the reason this is worth a forward test rather than a re-run.

**3. The decay is real and is not hidden.** Halves, in entry order: first **+0.6760R**
(t=3.21), second **+0.1699R** (t=1.15). Four fifths of the total sits in the first half. This
is the same shape the pre-registered late-session short showed, and it is the strongest
argument against reading this as settled.

## The deployability leg: it is not deployable at the arm's current risk

Run against the venue's own rules (3% daily / 6% shield / Best Day $250), entry-only governor
as on the chart, primary rule:

| risk / R | % of account | trades kept | worst day | vs the $750 line | days beyond it |
|---|---|---|---|---|---|
| **$250** | 1.00% | 67 of 658 | −$805 | over | **13** |
| $187.50 | 0.75% | 59 | −$803 | over | 7 |
| $125 | 0.50% | 464 | −$806 | over | 10 |
| **$62.50** | **0.25%** | 498 | −$467 | inside | **0** |

**A non-obvious result the scan caught**: cutting risk does not shrink the worst day in
dollars between 1.00% and 0.50%, because the governor's shield vetoes far fewer trades once
the equity path is comfortable — at 0.50% it keeps 464 trades where at 0.75% it kept 59. Less
risk per trade means more trades taken, which rebuilds the day's loss. Only at 0.25% does
every day land inside the line. This is the same lesson the hard-3%-switch table gave from the
other direction: **the daily rule is a statement about size, not about entry timing.**

This scan is **post-hoc and labelled so** — the rule was frozen and only $/R moved, so it
cannot rescue or damage the statistical verdict. It is the declaration's own declared
follow-on ("if it passes and still breaches, cut risk") answered with a number.

## What this does not say

It is not a validation. The contamination is total and stated in the artifact: the rule was
discovered by a 14-policy comparison on this same window, and there is no uncontaminated
holdout inside the venue's 8 months. n=658 is short of the declared 766. The second half
decays. Nothing here authorises an order — **the forward record
(`docs/GOLD_FORWARD_PREREG_20260921.md`) is the only instrument that can validate a rule**, and
at 0.25% risk its 100-trade verdict lands far sooner than at 1%.

What it does say, and what changes the next move: the entry trigger was never the broken part,
and neither was the cost model. The **fixed take-profit** is, on the only evidence in this
program that clears a threshold appropriate to its own search size.
