# Is the decay regime-driven? Run and verdict

**Date** 2026-09-21. **Declaration** `docs/GOLD_PREREG_PERSISTENCE_STATE_20260921.md` (written
first). **Harness** `scripts/gold_persistence_state.py` → `artifacts/gold_persistence_state.json`.
**Split** time, at the window midpoint: **2026-05-22 09:52 UTC** — 327 trades before, 331 after.
**Rule** stop 1.0×ATR, no take-profit, ≤48 bars, flat 22:00 UTC; the geometry was not re-optimised.

## Answer 1: the decay is not regime-driven — it is within-state

The descriptive decomposition, which picks no winner and therefore cannot be corrupted by the cell
search:

| | |
|---|---|
| state distribution, H1 vs H2 (**total variation**) | **0.110** — barely moved |
| counterfactual weight covered | 0.985 (so the answer is not an artefact of absent cells) |
| H2 actual | **+0.1625R** |
| H2 reweighted to H1's state mix | **+0.1094R** |
| H1−H2 gap | +0.5242R → **−10.1% composition, +110.1% within-state** |

Reading it: H2 did not lack the states that paid. Reweighting H2 to match H1's mix would have made
it **slightly worse**, not better. The same states were present and stopped paying. **"The regime
changed" is falsified as an explanation of this decay**, and the negative composition share is the
signature of that: the mix shifted marginally *in H2's favour* and it still lost.

Unfiltered halves: H1 **+0.6867R** over 327 trades (sd 3.833, t=+3.24), H2 **+0.1625R** over 331
(sd 2.679, t=+1.10). Note this is a **time** split, so unlike the four previous trade-order splits
it is the same statement about calendar periods, and the decay survives the stricter test.

## Answer 2: no state carries the first-half behaviour out of sample

The news axis measured cleanly for once — **369 top-tier HIGH events, ±15 minutes**, from the same
module, window and filter the EA uses at runtime — so the grid had all three axes and **11 cells**
were populated. That sets the price of a pick at `selection_threshold(11) = 2.828`.

| cell | H1 n | H1 mean | H2 n | H2 mean |
|---|---|---|---|---|
| vol=normal \| sess=06-12 | 92 | +0.6210 | 107 | **+0.6918** |
| vol=normal \| sess=12-17 | 91 | +0.8961 | 88 | +0.1980 |
| **vol=high \| sess=17-22** (the H1 winner) | 38 | **+1.2716** | 29 | **−0.1947** |
| vol=normal \| sess=17-22 | 37 | +0.0224 | 33 | −0.1208 |
| vol=high \| sess=12-17 | 30 | +1.2199 | 47 | −0.2798 |
| vol=high \| sess=06-12 | 23 | +0.1455 | 15 | −0.8758 |

The H1 selection picked **high volatility × 17–22 UTC** at **+1.2716R, t=+2.06** — best of the 5
cells that met the declared `n ≥ 30`. Against the single-test 1.96 that looks significant. Against
the priced 2.828 it is refused:

> **`NO STATE RULE SURVIVES SELECTION`** — the H1 winner's t=+2.06 does not reach 2.828, the
> threshold for a best-of-11 pick.

Per the declaration, nothing was carried to H2, and the artifact records
`carried_to_h2: false` with `stats: null` — so a later reader cannot mistake the rejected candidate
for a live rule.

**One post-hoc observation, labelled as outside the declaration** (which fixed that a failed
selection carries nothing): the rejected cell at the previous declaration's 1.384×ATR stop returns
**−0.1803R over 29 H2 trades (t=−0.94)**. So had the rule been carried, the second half would have
lost money on it. That is *not* the declared test and is reported only because it points the same
way.

## The one thing worth carrying forward, and why it is not carried yet

`vol=normal × sess=06-12 × news=out` is the only large cell that held: **H1 +0.6210R (n=92)** then
**H2 +0.6918R (n=107)** — same sign, similar size, on both sides of a time split, with 199 trades
in total. It is the most interesting object this study produced.

**It was not chosen, and it must not be read as a finding.** It ranked *third* on H1, behind two
high-volatility cells that flipped; picking it now would be selecting on the second half, which is
precisely what the declaration forbids and what the priced threshold exists to block. Its honest
status is **a candidate for a future pre-registered test** with its own declaration and its own
required sample — not a result, and not a reason to loosen anything.

## What the four studies together now say

Every exit geometry decays (means +0.68→+0.17, +0.57→+0.17, +0.99→+0.22, and here +0.69→+0.16 on a
strict time split), the state mix does not explain it, the stop multiple is a constant factor rather
than the missing piece, and the take-profit is a real but partial villain. The consistent reading is
that **this trigger's profitability on this window is period-specific**, not regime-conditional. Two
explanations fit the evidence equally well — an edge that decayed, or a rule fitted to the first
half — and **eight months of one instrument cannot distinguish them.** Only the forward record can,
which makes `docs/GOLD_FORWARD_PREREG_20260921.md` at the deployable size the highest-value thing
this program can run next, and makes any further geometry search on this window worthless.

Nothing here is a validation, and nothing here authorises an order. The arm is untouched.
