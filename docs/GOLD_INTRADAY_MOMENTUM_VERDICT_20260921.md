# Verdict: close-anchored intraday momentum on the venue's own day close

**Date:** 2026-09-21 · **Pre-registration:** `docs/GOLD_INTRADAY_MOMENTUM_PROTOCOL.md`
(declared before the run) · **Artifact:** `artifacts/gold_intraday_momentum.json` ·
**Harness:** `scripts/gold_intraday_momentum.py --selftest` (12/12)

## Verdict: **UNDECIDED AT THIS N** — and the gross effect is indistinguishable from zero

| | gross | cost | net |
|---|---|---|---|
| per day | **−0.0037R** (t −0.37) | −0.0071R | **−0.0109R** (t −1.09) |
| sd | 0.1202R | — | 0.1204R |
| n | 147 days (of 179 stamped) | | win rate 44.9% |
| MDE at 80% power, two-sided 5% | — | — | **0.0278R/day** |

The declared decision rule (`PROTOCOL.md` §Decision rule) reads: pooled mean > 0 *and* t ≥ 1.96
*and* both eras non-negative → PASS; otherwise FAIL when the effect is at or above the minimum
detectable effect; otherwise **UNDECIDED AT THIS N**. The measured net effect, 0.0109R/day, is
**2.5× smaller** than what 147 days can distinguish from zero, so the honest verdict is
*undecided* — this sample cannot reject the hypothesis **or** confirm it.

But the split between gross and net is the part that carries information, and it is decisive:

**The effect is absent before costs are charged.** Gross is −0.0037R/day with t = −0.37, on the
same 147 observations, and the paper's own regression on this window is flat: `r_LH = a + b·r_ROD`
gives **b = −0.0057** (percent, t = −0.95). Cost is not what killed the signal — there was no
signal to kill at this resolution. The gross figure is four times *smaller* than the sample's
own detectable effect (0.0128R/day gross at 80% power), which bounds the effect on this venue
at roughly **0.013R/day** even without rejecting it.

## Per era, and per month

| era | UTC window | n | gross | net |
|---|---|---|---|---|
| +60 min | 21:15–21:45 | 29 | +0.0334R (t +1.31) | +0.0306R (t +1.19) |
| +120 min | 20:15–20:45 | 118 | −0.0128R (t −1.22) | −0.0210R (t −2.00) |

**A disclosure about that second row.** Its net t of −2.00 is the only figure here that reaches
the 5% threshold, and it is **not** the declared test: it is a subsample of an era split that
was reported, not decided on, and with two eras examined a |t| of about 2 is close to what noise
supplies. The protocol is explicit that a *negative* slope rejects the momentum claim rather
than licensing a reversal, so this is recorded as an observation, not a finding: a reversion
claim into the venue's close would be a **new hypothesis needing its own pre-registration on
data this window has already consumed**, and the month split says where it would come from —
February is the only month with a positive mean:

| month | n | mean net R | | month | n | mean net R |
|---|---|---|---|---|---|---|
| 2026-01 | 3 | −0.0044 | | 2026-06 | 21 | −0.0324 |
| 2026-02 | 19 | **+0.0603** | | 2026-07 | 22 | −0.0038 |
| 2026-03 | 7 | −0.0350 | | 2026-08 | 21 | −0.0089 |
| 2026-04 | 21 | −0.0256 | | 2026-09 | 13 | −0.0135 |
| 2026-05 | 20 | −0.0409 | | | | |

## Coverage, and why the run was not void

147 of 179 stamped days qualified (82%). The 32 that did not are reported by the harness rather
than dropped silently: 20 lack the 22:00/22:15/22:30 stamps entirely (the venue's data stops at
21:45 on those days), 7 lack the day's first bar, and 5 lack other members of the set. The
protocol's void threshold — a majority of days missing, or coverage below 50% — was not
triggered, so the test is valid and the sample is not a selected subsample: the exclusions are
completeness failures, not outcome-dependent.

## Sample-size arithmetic: what would decide this

The minimum detectable effect scales as 1/√n on the measured per-day sd of 0.1204R:

| threshold to detect | days needed | ≈ years |
|---|---|---|
| 0.0278R (the current MDE) | 147 | 0.6 |
| 0.0109R (the observed net) | ≈ 956 | ≈ 3.9 |
| 0.0050R | ≈ 4,540 | ≈ 18 |

So this window — and any extension of it by months — can never decide whether the effect exists
here at the size it was observed. Saying "no edge" would be overclaiming in the other direction;
what is defensible is a **bound**: on this venue, in this instrument, the last 30 minutes of the
trading day do not carry a momentum effect of 0.013R/day or larger in gross terms.

## What this means for the arm

1. **The window the arm never trades costs it nothing measurable.** `docs/GOLD_LITERATURE_REVIEW_20260921.md`
   §A identified that the arm's session (06–20 UTC) and flat rule (22:00 UTC) leave it absent
   from the venue's final 30 minutes. That absence is now measured, and it is not a sacrifice:
   no momentum effect is detectable there, and the toll is the largest single component of what
   a trade there would earn (0.0071R/day of a 0.0109R/day net).
2. **No session-window change is justified by the literature.** The candidate ranked first in
   the review has been tested and does not clear. Candidates 2–4 there remain untested or
   undecidable at this sample, and nothing in this result promotes them.
3. **The arm's standing state is unchanged.** `artifacts/gold_wfo_ea.json` still reads NOT
   VALIDATED (t = +1.07) for the rule the EA actually trades. This study tested a *different*
   rule — a time-of-day effect, not the EA's BB/RSI trigger — so it neither helps nor hurts that
   verdict, and it authorises no input, preset or arming change.

## What would validate or overturn this

- **A longer gold history on this venue**, under the same single-series rule, taken to ≈4 years
  of days to decide the observed 0.011R/day. Multi-year venue history is not currently served.
- **The instrument the effect is actually strongest on.** Baltussen et al.'s channel is gamma
  hedging from options market makers and leveraged ETFs — an equity-index structure. Gold spot
  on a prop venue does not have it, and this measurement is consistent with that: the effect is
  reported "everywhere" across their 60-futures sample, and it is not visible here at a
  decidable size in the window they specify.
- **A falsification that would matter more than either:** if the venue's own day ended somewhere
  other than where the stamp histogram says (the 23:00 break, last M15 bar at 22:45), the test
  would be void rather than failed. It was not — every era's entry maps to the UTC hour the
  protocol predicted (21:15 and 20:15), which is itself a confirmation of the offset pin.
