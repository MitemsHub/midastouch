# Pre-registration: the tight stop (median adverse excursion), with its selection cost priced

**Declared** 2026-09-21, before this run. **Harness** `scripts/gold_prereg_tight_stop.py` →
`artifacts/gold_prereg_tight_stop.json`. **Candidate** stop = **0.694 × ATR** — the **median**
`|MAE|` at 8 bars over the discovery set.

## The two things that make this different from the last two tests

**1. The numbers already exist.** The candidate is the row that maximised the mean in the parent
run's sensitivity table (`artifacts/gold_prereg_derived_stop.json`,
`sensitivity_information_only`):

| stop | n | mean net R | sd | t |
|---|---|---|---|---|
| **0.694×ATR** | 658 | **+0.6031** | **4.3838** | +3.53 |
| 0.750×ATR | 658 | +0.5044 | 4.0788 | +3.17 |
| 1.000×ATR | 658 | +0.4230 | 3.3110 | +3.28 |
| 1.384×ATR (previous declaration's stop) | 658 | +0.3726 | 2.5870 | +3.69 |
| 2.000×ATR | 658 | +0.3436 | 2.0080 | +4.39 |

So **this run cannot be a fresh test of the effect.** The effect is measured; what is *not* yet
measured is whether it survives being the maximum of a search. That is the only question this
document can honestly ask, and it is the question being asked.

**2. It is a 1-of-8 selection, so the threshold is not 1.96.** The candidate was chosen by taking
the largest mean over the **8 distinct stop multiples** the parent table examined. A best-of-8
maximum has its own null distribution:

| search size | threshold (95th pct of max \|z\|) |
|---|---|
| 1 (a declared hypothesis) | 1.960 |
| **8 (this candidate's own search)** | **2.725** |
| 168 (every entry geometry this program has swept) | 3.612 |

The primary threshold is therefore **2.725**, not 1.96. This is the discipline the program applies
to every other family; a candidate picked off a table does not get to skip it, and declaring it
"N=1" now would be exactly the post-hoc story-telling the apparatus exists to prevent.

## The hypothesis, fixed here

| | |
|---|---|
| **stop** | median `|MAE|` at 8 bars, measured on the **discovery** entry set (session 0–24) |
| **take-profit** | **none** |
| **session flat** | flat by 22:00 UTC |
| **time limit** | 48 bars |
| **risk unit** | the stop distance, so a stop-out is exactly −1R |
| **test entry set** | the arm's session, **06–20 UTC** (658 entries) |

## Required sample, computed up front from the candidate's own effect

`mean` +0.6031, `sd` 4.3838, `n` 658:

| requirement | trades |
|---|---|
| reach its **own** threshold (2.725) | **393** |
| 80% power at that threshold | **673** |
| reach the **program-wide** threshold (3.612, 168 trials) | **690** |

## The verdict rules, fixed here

- **UNSOUND DERIVATION** — stop-out rate outside the declared 20–70% band. (At the median, this
  should be ≈50% by construction; if it is not, the derivation and the measurement disagree.)
- **KILL** — mean ≤ 0. The tight-stop family is retired, and no other quantile of the excursion
  distribution is tried.
- **PASS** — `t ≥ 2.725` **and** `n ≥ 673`.
- **POSITIVE, UNDERPOWERED** — `t ≥ 2.725` but `n < 673`.
- **FAIL** — `t < 2.725` at `n ≥ 393`.
- **INSUFFICIENT** — `n < 393`.

**And a second hurdle, reported separately and declared in advance.** The candidate was also
surfaced by a program whose entry-side search has covered 168 geometries. Priced at that scale the
threshold is **3.612**, and the candidate's t is **+3.53**. The declaration fixes the wording for
that case: a candidate that clears its own search but not this one is reported as
**"clears its own search; does not clear the program-wide hurdle"** — never as validated, and
never with the weaker number quoted alone.

## What is being tested, stated precisely

Not "is +0.6031R per trade real?" (it is measured; the question is what it is worth after
selection). What is being tested is the **criterion** that produced it: *the mean is maximised by
stopping at the median adverse excursion.* That criterion is falsified if, once the selection is
priced, the candidate either fails its threshold, or is underpowered, or turns out to be
undeployable, or its advantage over the conventional stop vanishes on a paired comparison.

The paired comparison is declared and required: the **same 658 entries**, tight stop vs 1.0×ATR vs
the previous declaration's 1.384×ATR, with the differences reported per trade.

## Contamination

Total, as before: the same window, the same entries, the same trigger, and — worse than the
previous two tests — the candidate's own numbers were produced by the run that suggested it. There
is no uncontaminated holdout inside the venue's eight months.
`docs/GOLD_FORWARD_PREREG_20260921.md` remains the only instrument that can validate a rule.

Run and verdict: `docs/GOLD_TIGHT_STOP_TEST_20260921.md`.
