# Verdict: reversal into the venue's close, on the unconsumed slice

**Date:** 2026-09-21 · **Pre-registration:** `docs/GOLD_REVERSAL_INTO_CLOSE_PROTOCOL.md`
(declared before the run) · **Artifact:** `artifacts/gold_reversal_into_close.json` ·
**Harness:** `scripts/gold_reversal_into_close.py --selftest` (13/13)

## Verdict: **UNDECIDED AT THIS N** — and the point estimate leans *against* the hypothesis

| | gross | cost | net | t | n | MDE |
|---|---|---|---|---|---|---|
| **primary sample** (declared) | **−0.0157R** | 0.0067R | **−0.0224R/day** | **−0.58** | 22 | 0.1088 |
| auxiliary (descriptive, pre-declared) | +0.0042R | 0.0168R | −0.0125R/day | −0.33 | 9 | 0.1050 |

(Per era, as recorded: the primary's 19 +60-era days net −0.0292R (t −0.65) and its 3 +120-era
15:45-UTC days net +0.0213R (t +0.68); the auxiliary's 8 +60-era days net −0.0125R (t −0.29)
with one +120-era day too few to form a block.)

The declared regression wants **b < 0** for H2. It came out **b = +0.0107 (t = +0.34)** in the
primary sample: indistinguishable from zero, and pointing the wrong way. Both samples are
inside their own minimum detectable effect — 22 days can see only ~0.11R/day — so the honest
reading is that **neither direction is decidable on the days this study could use**, and the
reversal hint does not survive as a tradable claim.

Disclosed rather than buried, because it is the same rows: the **mirror (momentum) direction**
on these same 22 days nets **+0.0090R/day, t +0.23**. That is a third look at the momentum
hypothesis and is reported as descriptive only. It is not evidence for the momentum study either
— 22 days decide nothing in either direction.

## The sample, corrected against my own pre-registration

The protocol characterised the primary sample as "US early-close days". Measured, it is **two
populations**, and the larger one is not what I said:

| subset | n | mean net | t | what it is |
|---|---|---|---|---|
| **Mar 9–27** | 15 | −0.0030R | −0.07 | the **US-DST-only window**: US DST began 2026-03-08, EU DST began 2026-03-29, so between them the two shifts do **not** cancel. The venue's close followed US Eastern to server 22:00 while the server clock still read +60, so the day's final bars are stamped 21:30→21:45 instead of 22:30→22:45. |
| other early closes | 7 | −0.0639R | −0.73 | 01-23, 01-26, 01-27, 02-16, 06-19, 07-03, 09-07 — genuine early closes (holidays) |
| dropped | 1 | — | — | 2026-01-12, the series' first day: 39 bars, below the declared 40-bar minimum |

One more correction to the declaration: the protocol described the auxiliary as "all 32
unconsumed days", which cannot be right while the primary takes 22 of them. As run, the
auxiliary is the **9** days left after the primary and the dropped day — declared as descriptive
either way, and now stated as what it actually covered rather than what the protocol said.

The DST cluster is exactly Mon–Fri across the weeks of Mar 9–13, 16–20 and 23–27 — the phase
misalignment `configs/mt5/server_offsets.json` warns about, showing up in the bar stamps. It
matters two ways: those days' final 30 minutes are the venue's *real* close (21:00 UTC, same
UTC instant as a standard day), which makes them more comparable to the consumed window than the
protocol assumed; and it means my "early close" framing was wrong for 15 of the 22. The subset
that is genuinely a different regime — thin holiday closes — carries only 7 days and decides
nothing at all (MDE 0.2465R).

## The pooled number is one day's story

The primary mean of −0.0224R/day is dominated by a single observation: **2026-01-27 at
−0.5856R**, a large adverse excursion into that day's close. Removing it moves the sample mean
to **+0.0045R/day** — the sign of the pooled estimate depends on one day out of 22. With sd
0.1821R/day (inflated by that same day), the arithmetic is:

| effect to detect | days required (80% power) |
|---|---|
| 0.02R/day | **≈ 650** |
| 0.0046R/day (the cost-inclusive reversal hint declared up front) | **≈ 12,300** |
| 0.1088R/day (what these 22 days can see) | 22 |

So the reversal hint, once the toll is paid in both directions, is ~12,000 observations away —
about 47 years at one observation per day. **The existing gold history cannot decide it, and no
plausible extension of it can either.**

## The forward primary, unchanged and not yet testable

The one genuinely un-consumed direction is forward from the venue's 2026-09-21 close. The
harness already supports it (`--forward`), and the declared required sample stands: ~650
observations for a 0.02R/day effect, ~250 for 0.03R/day. Nothing can be claimed from it early,
and tonight contributes one observation.

## What this does and does not change

1. **H2 is not supported and not refuted.** The cost-inclusive arithmetic that made the +120
   era's −2.00 t-statistic interesting ($+0.0046$R/day, not +0.021R/day) is the reason it was
   never a promising candidate, and the unconsumed days give it a point estimate in the wrong
   direction on a sample that decides nothing.
2. **No session, preset, input or arming change follows from it.** The arm is armed on the
   operator's override behind a FAILED gate (`artifacts/gold_wfo_ea.json`, NOT VALIDATED,
   t = +1.07) and this study tested a time-of-day effect, not the EA's trigger.
3. **The consumed window stays consumed.** It supplied the hypothesis and is named as such in
   both documents; it was not re-tested with the sign flipped, which is the failure this
   programme's pre-registration discipline exists to prevent.
4. **What would overturn this:** a much longer un-consumed gold history (years, not months), or
   the same test on an instrument whose prop venue serves its own history far enough back for
   ~650 clean observations. Neither exists in this checkout today.
