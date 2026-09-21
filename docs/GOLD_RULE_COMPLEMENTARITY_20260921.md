# ARE THE TWO RULES A PORTFOLIO? — 2026-09-21

**Verdict: NO. They are the same trade, twice.** Measured on the venue's own bars, both clock
eras, same engine and cost model as the EA walk-forward. Artifact:
`artifacts/gold_rule_complementarity.json` · Harness: `scripts/gold_rule_complementarity.py`.

| measure | result |
|---|---|
| the two rules on the same bars | EA rule 136 trades / +11.767R; gate family 260–952 trades across its 24-config grid |
| overlaps (holding intervals intersect) | 194–574 pairs, depending on configuration |
| **share of overlaps that are SAME direction** | **100% in all 24 configurations** |
| correlation of the two **daily R** series (days both traded) | median **+0.547**, range +0.465…+0.594 |
| combined worst day vs each alone | **worse than both**, in every configuration |
| worst day, and days past the $750 daily line | EA alone −$404.10 (0 past) · best gate config alone −$136.78 (0 past) · **combined −$486.71 (0 past)** |

## What this means

The 3.4% signal overlap that made the two rules look independent at the *signal* level is
misleading, and the portfolio question is the reason it matters: whenever these two rules do
hold at the same time, **it is always the same side**. There is no configuration of the gate's
frozen grid in which the pair hedges, and the daily results move together at ρ ≈ 0.55. Adding
the second rule therefore adds exposure without adding diversification: the combined worst day
(−$486.71) is deeper than either rule's own (−$404.10 / −$136.78), and the shared headroom to
the venue's 3% line shrinks accordingly.

Both rules remain inside the $750 line on this window (0 days past, each alone and combined) —
but that is the same statement the sizing scan already made about the EA rule alone, and it is
not a reason to double it.

## The caveat, stated rather than buried

The combined figure is computed under one declared convention: both rules size at the venue's
minimum lot, a trade's dollars-per-R is its own stop distance in dollars, and **one** shared
$750 line is applied to the summed daily result. No risk-splitting model is invented — a
portfolio-sized variant (each rule at half the risk) would scale both legs down together and is
*not* measured here. What is measured is the correlation and the direction agreement, and those
are what decide the question, because they are properties of the entries rather than of the
sizing.

## Consequence for the program

There is no second, independent rule in this repository to trade alongside the EA's. The
EMA-stack family — the one every frozen certification here is about — is a higher-frequency
version of the same directional bet, so a "two rules, one account" route to a validated arm
does not exist on these bars. That closes one more of the routes that looked open.
