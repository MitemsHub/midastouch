# The tight stop (median adverse excursion), priced: run and verdict

**Date** 2026-09-21. **Declaration** `docs/GOLD_PREREG_TIGHT_STOP_20260921.md` (written first).
**Harness** `scripts/gold_prereg_tight_stop.py` → `artifacts/gold_prereg_tight_stop.json`.
**Window** 2026-01-12 13:15 → 2026-09-21 16:15 UTC (16,290 bars).

## The question, and the honest answer

The question was whether the criterion the sensitivity table suggested — *the mean is maximised by
stopping at the median adverse excursion* — survives being tested properly. It does not.

| | | |
|---|---|---|
| candidate | stop **0.6941 × ATR** (median `|MAE|`, 8 bars, discovery set, n=906) | stop-out rate **49.2%** — inside the declared band and ≈50% as the median implies |
| result | n=658, mean **+0.6031R**, sd **4.3838**, **t=+3.53**, total **+396.8R** | — |
| required | **393** trades for its own threshold, **673** for 80% power, **690** for the program-wide hurdle | n=658 fails two of the three |
| **verdict** | **`POSITIVE, UNDERPOWERED \| does not clear the program-wide hurdle`** | t=+3.53 ≥ 2.73 (own, 8 stops), n below 673, and t < 3.61 (168-geometry scale) |

**Mechanically it clears the search that produced it** — 3.53 > 2.725, so the candidate is not
explained away by the 8-way pick alone. That is the one thing it does. Everything else it fails:

1. **Power.** n=658 against the declared 673. The declaration made that binding, and 15 trades is
   a strange thing to die on, but the rule was fixed before the number, which is the point.
2. **The program-wide hurdle.** Priced at the 168-geometry scale the threshold is 3.612 and
   t=+3.53 falls short. The declared wording for this case applies verbatim: it clears its own
   search and does not clear the program-wide one.
3. **The advantage over the conventional stop is not itself significant.** The paired comparison
   the declaration required — same 658 entries, one geometry changed — gives
   **+0.1801R per trade, sd 1.8757, t=+2.46**, which is **below the 2.725 threshold**. So the
   candidate's headline mean is real, and its *edge over the stop we already had* is not
   distinguishable from noise at the multiplicity-adjusted bar.

## The shape of the criterion's failure

The tight stop is the **highest mean and the highest variance** in the table: sd **4.3838** against
3.3110 at the conventional stop and 2.5874 at the previous declaration's. That is what
"mean-maximising" turned out to mean — a 0.694×ATR stop normalises every outcome by a small
denominator, so a winner's R is inflated and so is the blowout's, and the engine's own
pessimistic marks (a stop fills where it was touched; a bar gapping through fills at the open)
land on the tight stop hardest.

Its deployability is the worst of the three, from the same cause:

| risk / R | % | trades kept | worst day | days beyond $750 |
|---|---|---|---|---|
| $250 | 1.00% | **6** | −$835 | 2 |
| $187.50 | 0.75% | 47 | −$827 | 4 |
| $125 | 0.50% | 102 | −$825 | 3 |
| **$62.50** | **0.25%** | 496 | −$479 | **0** |

At the arm's own 1% risk the governor keeps **six trades out of 658** — the equity path is violent
enough that the shield shuts the rule down almost immediately. Once again 0.25% is the only
scanned size whose every day lands inside the venue's rule.

## Decay, fourth time

Halves in entry order: **+0.9892R (t=3.47)** then **+0.2170R (t=1.17)**. Four studies now show the
same profile — late-session short, the parent no-target rule, the derived stop, and this — with
most of the total in the first half and the second half not significant in any of them. That
regularity is more informative than any of the individual means: **whatever this trigger finds, it
is not stationary across the venue's eight months**, and no choice of exit geometry has changed
that.

## What the criterion test actually concluded

Standing back from the numbers: the mean is maximised at the tightest stop, the t is maximised at
the widest, and neither extreme survives the accounting. The sensitivity ridge is **flat enough
in t (3.17–4.39 across all 8 stops) that the choice of stop is not where this program's problem
lives** — every stop in the table produced a positive mean with t in a narrow band, and every one
of them is the same rule with a different denominator. Chasing the stop is chasing a constant
factor.

That is a more useful conclusion than a new winner would have been, and it is the reason this
evaluation was worth running even though the candidate's numbers were known in advance: **the
exit geometry is not the missing piece; the persistence of the edge is.** The next test that can
change the answer is the forward record at the size the rule is actually deployable at, where
"does the second half look like the first" is answerable outside this window.

## Facts, not validation

Not a validation, and the strongest statement of that is structural: **the candidate's own numbers
were produced by the run that suggested it**, so this run could only ever price the selection, not
test the effect. Nothing here authorises an order. The arm is untouched.

Standing summary of the three exit studies, all on the same window with the same trigger:
a target-free rule returns ≫ a 2R-target rule on identical entries; a wider stop buys
significance without buying mean; a tighter stop buys mean without buying significance; and every
variant decays in the second half.
