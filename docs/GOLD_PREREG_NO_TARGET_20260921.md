# Pre-registration: the no-target exit as a single declared hypothesis (N=1)

**Declared** 2026-09-21, before the measurement. **Harness** `scripts/gold_prereg_no_target.py`
(writes `artifacts/gold_prereg_no_target.json`). **Threshold** 1.96, because N=1 — no
selection, so the multiplicity table in `docs/GOLD_DECIDABILITY_AUDIT_20260921.md` does not
apply to this test and `selection_threshold(1) = 1.96` is the correct comparison.

## What was already measured, and therefore what is contaminated

`artifacts/gold_exit_capture.json` (2026-09-21) compared **14 exit policies on one fixed entry
set** and found `fixed stop 1.0 only` — no take-profit — at **+0.3221R per trade, sd 3.1838,
t=+3.06 over 912 trades**, the only family in this program that clears its own
multiplicity-adjusted threshold (2.90 at 14 policies, DSR 0.7586).

**The contamination is total and is stated first**: that policy was *selected* by that
comparison, on that window, on those entries. Declaring it now removes **multiplicity**, not
**contamination**. There is no uncontaminated holdout inside the venue's 8 months — the
account's serviceable bars begin 2026-01-12 and the venue's real ticks begin 2026-09-04 — so
this is a pre-registered *measurement*, not an out-of-sample validation, and the artifact
records the same sentence.

## The rule, fixed here

Applied to entries the rule was **not** selected on, with nothing else varying:

| | |
|---|---|
| **stop** | 1.0 × ATR(H1) at the entry bar |
| **take-profit** | **none** |
| **time limit** | 48 bars |
| **session flat** | flat by 22:00 UTC (the frozen engine's rule) |
| **costs** | the frozen engine's own model: spread `SPREAD_BPS`, commission `COMMISSION_PER_LOT_RT` |
| **marks** | pessimistic: a stop touched inside a bar fills at the stop; a bar gapping through it fills at the open |

**Primary entry set (the out-of-sample half of this design).** The discovery used the widest
session, 0–24 UTC. The primary set is the arm's own session, **06–20 UTC**, with the frozen
trigger configuration `emas (8, 21, 50)` — the same trigger, a session the exit rule was not
selected on. This is the strongest separation available on this venue and it is still not a
clean time holdout: same window, same trigger family.

**Secondary (replication, labelled in-sample).** The identical rule on the discovery's 0–24
entry set. It must reproduce ≈ +0.3221R / n≈912; if it does not, the harness disagrees with
itself and the primary means nothing.

**Comparator (declared, not searched).** The arm's current exit — stop 1.0 × ATR, target
**2.0R** — and the certified geometry (target 3.0R), both on the same entries, so the
difference is the exit and not the entries.

## Required sample, computed BEFORE the run

From the discovery's effect size (`mean` +0.3221, `sd` 3.1838), `n = ceil((t·sd/mean)²)`:

| requirement | trades |
|---|---|
| reach t = 1.96 at the measured effect | **375** |
| 80% power at α = 0.05 | **766** |

## The decision rule, fixed here

- **PASS** — primary `t >= 1.96` **and** `n >= 375`. The rule is a candidate, and becomes a
  *validated* rule only on the forward record (`docs/GOLD_FORWARD_PREREG_20260921.md`).
- **POSITIVE, UNDERPOWERED** — `t >= 1.96` but `n < 766`. Reported as positive and explicitly
  not as validated; the forward record is then the only instrument that can settle it.
- **INSUFFICIENT** — `n < 375`. No verdict either way, whatever t says.
- **KILL** — primary `mean <= 0`. The no-target family is retired at that point: no narrower
  stop, no wider time limit, no other session gets tried, because re-cutting the same
  measurement until it passes is the failure mode this whole document exists to prevent.

## Also declared: deployability, not just significance

A significant rule that still breaches the venue's 3% daily line cannot be deployed at the
arm's current 1% risk (the line is 3R at that size). So the primary trades are also replayed
through the entry-only governor and the day-loss counts reported. **Declared in advance:** if
the primary passes statistically and still breaches, the finding is a *measurable effect with
a sizing problem*, and the conclusion is to cut risk — not to search for a variant that
happens not to breach.

## What would falsify this

A primary `t < 1.96` at `n >= 375`, or a primary mean ≤ 0. Either retires the no-target exit
as a deployable rule and returns the program to the entry side with the honest statement that
the exit effect does not survive a session restriction.

Full run and verdict: `docs/GOLD_NO_TARGET_SINGLE_TEST_20260921.md`.
