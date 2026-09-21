# Pre-registration: close-anchored intraday momentum on the venue's own day close

**Date declared:** 2026-09-21 · **Declared before:** `scripts/gold_intraday_momentum.py` was run
**Artifact:** `artifacts/gold_intraday_momentum.json` · **Verdict:**
`docs/GOLD_INTRADAY_MOMENTUM_VERDICT_20260921.md`

One hypothesis. No grid, no sweep, no alternative window reported as the result. The rule is
written here *because* nothing has been measured yet: the sign, the window, the normalisation,
the cost model and the decision rule are all fixed below, and the harness implements this file
rather than choosing its own.

## Why this one

Baltussen, Da, Lammers & Martens (2021, *JFE* 142(1) 377–403) report, on 60+ futures across four
asset classes, that **the return over the rest of the day positively predicts the return over
the last 30 minutes before the market close**, and that this is distinct from intraday return
seasonality. `docs/GOLD_LITERATURE_REVIEW_20260921.md` records what that paper says and how it
was reached.

The reason it is worth one test here is not the paper's sample, it is the mismatch it exposes:
this arm's session is **06–20 UTC** and its flat rule is **22:00 UTC**, while the venue's own
trading day does not end when UTC midnights — it ends at the daily maintenance break, which
sits at **server 23:00 in every month** (it follows US Eastern, and the two DST shifts cancel).
So the last 30 minutes before the venue's close fall at **21:15–21:45 UTC** in the +60 era and
**20:15–20:45 UTC** in the +120 era — inside neither the arm's session window nor its holding
horizon. If the effect exists for gold on this venue, this arm has never been present for it.

## Declared hypothesis (H1, directional)

> The return from the venue's day open to the start of the last 30 minutes before the venue's
> daily close predicts the return over those last 30 minutes, **with the same sign**
> (`b > 0` in `r_LH = a + b·r_ROD`).

A negative, significant `b` **rejects** the momentum claim for this instrument. It is not a
licence to flip the sign and report the reverse as a finding — the sign was declared, and a
rejection is a result.

## Declared construction — every window derived from the pins, not hand-typed

Era offset is read per month from `configs/mt5/server_offsets.json` via
`midas_sweep.server_offset_for_month()`. A month containing a DST step returns `None`, which the
harness **refuses** on rather than defaulting: a single offset cannot convert an epoch in such a
month, and a guessed clock mis-aligns every key with no visible symptom.

| element | definition |
|---|---|
| day | one stamped calendar day of the venue's M15 series (stamps are server-local) |
| `r_ROD` | open of the **22:15** stamp bar ÷ open of the **00:00** stamp bar − 1 |
| `r_LH` | close of the **22:30** stamp bar ÷ open of the **22:15** stamp bar − 1 |
| `LH` window | stamps 22:15 + 22:30 = the final 30 minutes before the 23:00 break |
| entry | open of the 22:15 bar, in the direction of `sign(r_ROD)` |
| exit | close of the 22:30 bar (no stop is placed; `r_LH` is bounded by the 30-minute bar) |
| skip | `r_ROD == 0` exactly (no direction); day missing any of the 00:00 / 22:00 / 22:15 / 22:30 stamps — the 22:00 bar is a **completeness guard** (it is used in no arithmetic, it only excludes a day whose bars stop short of the close) |
| sample | every qualifying stamped day in the venue's served window; **no subsample may be substituted** |

`r_LH` is measured from the *open* of the entry bar, so entry slippage inside the bar is not
charged — which is generous to the hypothesis, and deliberately so: a PASS that needed
intra-bar perfection is not worth having.

## Declared normalisation and cost model

- **Price terms**: `r_LH` in USD per ounce, signed by the trade direction.
- **R terms**: divided by a declared stop distance of `2.0 × ATR(H1, 14)` at the entry instant —
  the arm's own geometry — so the result is comparable to the program's R language. R is used
  for the decision; dollars are reported alongside so the size-independence is visible.
- **Cost**: the repo's model, unmodified — half the **recorded** spread of each side, floored at
  `midas_sweep.SPREAD_FLOOR = $0.10`, charged as `(entry_spread/2 + exit_spread/2) / stop`.
  Recorded spread is what the venue actually quoted in that bar, not an assumption.

## Declared decision rule

Computed over the pooled sample, and reported per era as well:

| verdict | condition |
|---|---|
| **PASS** | pooled mean net R/day > 0 **and** pooled t ≥ **1.96** **and** both era means ≥ 0 |
| **FAIL** | otherwise, when the observed effect is at or above the minimum detectable effect at 80% power |
| **UNDECIDED AT THIS N** | otherwise, when the observed effect is below that threshold |

The third line is declared now so it cannot be invented afterwards. Minimum detectable effect is
`(1.96 + 0.8416) · sd(net R) / sqrt(n)` — the per-day mean an n-day sample can distinguish from
zero eight times in ten, two-sided. If the measured effect is smaller than what this sample can
see, the honest answer is *undecided*, and it must be reported in those words rather than as
"no edge".

## Declared limits, before the numbers exist

1. **One window, one instrument, ~179 days.** These are gold's last 30 minutes on one venue in
   one 8-month stretch. Any PASS is a single-window result on a short sample and is not a
   licence to arm: it would be a candidate for a *forward* test, and the arm's standing gate
   (`artifacts/gold_wfo_ea.json`, NOT VALIDATED) is unaffected either way.
2. **No mechanism claim.** The paper's channel is gamma hedging demand from options market
   makers and leveraged ETFs. This test cannot distinguish that channel from any other; a PASS
   would establish predictability, not cause.
3. **Cost realism.** The recorded bar spread is a proxy for what a 0.01-lot market order would
   pay in the last 30 minutes of the day, when the venue's quotes are typically at their widest.
   The floor at $0.10 is the repo's, and it is a floor on recorded spreads, not a cap: a bar
   recording an $0.80 spread charges $0.80.
4. **What would falsify the design, not just the hypothesis:** if the 22:15/22:30 stamps are
   absent on a majority of days (i.e. the venue's day does not end where the stamp histogram
   says it does), the harness reports the coverage shortfall and stops — the test is void, not
   failed.
