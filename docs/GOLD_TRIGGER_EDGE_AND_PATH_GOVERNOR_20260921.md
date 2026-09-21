# Where the edge could live, and whether a path-protecting governor saves the rules

**Date:** 2026-09-21 · **Harnesses:** `scripts/gold_trigger_edge.py` (new),
`scripts/gold_governed_wfo.py --governor path` (extended)
**Artifacts:** `artifacts/gold_trigger_edge.json`, `artifacts/gold_governed_wfo_path.json`
**Window:** the venue's served history, `XAUUSD M15, 16,283 bars, 2026-01-12 .. 2026-09-21`

---

## 1. The trigger is not noise — the exits and the average are the problem

Measured forward drift after **every signal bar**, in ATR units, with no exit rule attached
(5,098 entries; session 0–24 so nothing is pre-filtered):

| horizon | n | mean move (ATR) | t |
|---|---|---|---|
| 8 M15 bars (2h) | 5,098 | **+0.113** | **+3.52** |
| 16 M15 bars (4h) | 5,098 | **+0.177** | **+3.97** |

So the entry condition does carry information: the market drifts in the signal's direction
after it fires, at t ≈ 3.5–4. Meanwhile the same entries, taken through the strategy's own
exits, cost model and 1R sizing, average **≈ 0R/trade** (the 168-geometry sweep's best:
+0.0316R governed, +0.0816R ungoverned). **The trigger is not the whole problem; what
happens between the entry and the exit is**, which is a materially different conclusion from
"the strategy has no edge" and it is the first time this program has separated the two.

## 2. Slicing the entries: four cells are decidable on this window

Mean net R per trade by cell, with **the sample the cell would need for t ≥ 1.5** — the
column that decides whether a cell is tradeable or merely interesting:

| cell | n | mean R | t | needs |
|---|---|---|---|---|
| **aligned DOWN × 17–22 UTC (late)** | 469 | **+0.1329** | +2.36 | **190** |
| **Wednesday** | 1,264 | **+0.1221** | +3.10 | **296** |
| **H1 ATR > 1.3× median (high vol)** | 1,278 | **+0.0785** | +2.07 | **669** |
| 06–12 UTC (London) | 1,080 | +0.0688 | +1.59 | 964 |
| aligned DOWN (all hours) | 2,787 | +0.0278 | +1.07 | 5,471 |
| aligned UP (all hours) | 2,311 | **−0.0405** | −1.45 | — |
| low volatility (<0.8× median) | 134 | **−0.3522** | −3.42 | — |
| Thursday | 955 | −0.0946 | −2.22 | — |

The structure is consistent across three of the four dimensions: **the short side carries
the edge and the long side destroys it** (aligned DOWN +0.028 vs aligned UP −0.041 — the
same split appears as `direction`), and the worst states are the quiet ones (low ATR,
low-volatility cells are the only strongly negative ones).

**The artefact test says the cells are not stable.** Taking the best hour×regime cell at
EACH exit geometry, the winner changes with the target, and its t-statistic never clears
1.5:

| geometry | best cell | n | mean R | t |
|---|---|---|---|---|
| stop1.0 tp1.5 | aligned DOWN × late | 131 | +0.0552 | +0.57 |
| stop1.0 tp2.0 | aligned DOWN × late | 111 | +0.1273 | +1.04 |
| stop1.0 tp3.0 | aligned UP × London | 72 | +0.2705 | +1.21 |
| stop1.5 tp2.0 | aligned DOWN × late | 78 | +0.1856 | +1.72 |
| stop1.5 tp3.0 | aligned UP × London | 52 | +0.1712 | +0.83 |

24 cells were tested and 4 are "decidable on this window" — that is what selection over
24 cells looks like, and the window is the one the gate is judged on. **Everything in this
section is exploration.** What it licences is a pre-registered test of ONE cell, not a
strategy change: the honest candidates in order of sample size are **short-only entries in
the 17–22 UTC window when the H1 and H4 trends are both down** (190 trades needed) and
**a high-volatility (>1.3× median ATR) filter** (669 needed). The rest, including the
Wednesday cell, should be treated as noise until a declared test says otherwise.

## 3. The path governor: better on total, still breaching the venue

`govern_path()` adds the half the EA's governor does not have (`docs/GOLD_GOVERNED_WFO_20260921.md`
§3): a **pre-empted day kill switch** (refuse an entry when one more full loss would reach
the 3% line; exit an open position at the bar the mark touches it), a **soft-stop ladder**
(risk re-derived from the drawdown band — 1.00 / 0.50 / 0.25 / 0.00 at 0–2% / 2–4% / 4–6% /
≥6% from peak), and a **shield-floor exit** rather than a shield-floor-entry-block. Marks are
bar closes, so an intra-bar touch is one bar late — declared, and it makes the governor look
*slightly worse* than a tick-checking EA, which is the direction a risk study should err.

Frozen walk-forward, same grid, same folds, governor inside the selection:

| | entry-only governor | **path governor** |
|---|---|---|
| OOS trades | 270 | 390 |
| total | −30.35R | **−35.71R** |
| fold-mean t | −1.32 | −1.73 |
| random-entry control | −60.98R | −41.90R |
| V1/V2/V3/V5/V6 | 5 fail | **5 fail** |
| final equity | $17,411.91 | $16,072.63 |
| worst day | −3.23R (−$806) | **−4.79R (−$1,196)** |
| shield / daily breaches | 5 / 5 | **5 / 5** |

**The answer to the question asked is no: the venue's rules are still broken.** The path
governor is *worse* on every aggregate than the entry-only one (−35.71R vs −30.35R, over
390 trades instead of 270 — scaled risk fits more entries under the fixed $250/day Best Day
cap, and each of those extra entries pays the toll), the fold-mean t is worse (−1.73 vs
−1.32), the worst single day is worse (−4.79R vs −3.23R), and the breach counts are
identical at 5 shield and 5 daily.

One units bug was caught by its own test while building this, and it is worth recording
because it is the exact failure mode a modelled risk rule dies of: the first version of the
pre-empted day switch compared `day_pnl` (in R) against `daily_limit` (in USD), so the
comparison could never be true and the switch silently measured nothing — the first run
looked *better* than the entry-only governor for the wrong reason. The numbers above are
the corrected run.

The reason is now measurable rather than arguable: **the 3% daily rule is a property of the
outcome distribution, not of entry timing.** A day reaches −3R because an allowed trade
closed beyond the line — the exit that stops it is the bar-close mark, one bar late, and on
a fast bar the trade is already through. The only controls that would bound it are
smaller risk per trade, a wider stop/lower size pair, or not taking the low-volatility
states where the per-trade mean is −0.35R. All three are strategy changes, and the first
two are exactly what the soft-stop ladder and the ATR filter in §2 test.

## 4. What this changes about the live arm

The arm on 1428765 runs ORIGINAL mode with `InpPropGuard` on: the **entry-only** governor,
which is the weaker of the two policies measured here, on a configuration whose own
governed walk-forward is negative. Nothing about the override record changes.

What is new, and what the operator now has that they did not:

1. A measured statement that the **entry trigger carries information** (+0.11 ATR at 2h,
   t=3.5) while the **average trade carries none** — so any future work belongs in exits,
   sizing and filtering, not in inventing a new signal.
2. Two candidate cells with a required sample, and a clear negative result for the long
   side and for low-volatility states.
3. A demonstration that **no governor policy of the kinds modelled here prevents the venue
   rules from being breached** — which retires "add a kill switch" as a fix and leaves risk
   sizing and state filtering as the remaining levers.
