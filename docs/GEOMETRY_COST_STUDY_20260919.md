# GEOMETRY / COST STUDY — pre-registered 2026-09-19 (frozen before any run)

**Status: FROZEN AT WRITE TIME.** Written before any cell of this grid was executed.
No gate, metric, grid cell or ranking rule below may be changed after the first number is
read. Results go in `artifacts/train/GEOMETRY_COST_STUDY_20260919.json` and the verdict is
appended to this file — never rewritten.

## The question

The operator's reason for returning to synthetics is cost/availability: gold is not 24/7.
The council of this program's own evidence says something different. Measured from the
broker M5 corpora plus the `symbol_info` probe, the spread is a roughly constant **~1% of a
wide stop on every volatility index**:

| index (1-tick) | min lot | spread (price) | ATR(H1) | toll @2×ATR(H1) |
|---|---|---|---|---|
| Volatility 25 | 0.5 | 0.225 | 11.299 | 1.00% |
| Volatility 50 | 4.0 | 0.016 | 0.768 | 1.04% |
| Volatility 75 | 0.01 | 16.960 | 600.620 | 1.41% |
| Volatility 100 | 1.0 | 0.180 | 7.410 | 1.22% |

Deriv prices spread proportionally to each index's own volatility, so **switching
instruments does not change the cost ratio**. The documented "5.6% toll killed Volatility 75
(1s) at M15" was therefore a *geometry* result: those scans ran stops of roughly
`1 × ATR(M15)`. The same instrument at `2 × ATR(H1)` pays ~1.4%.

**So the falsifiable question this study answers is:**

> On the certified V75 configuration applied unchanged to each of the four requested
> instruments, does the **sign of gross expectancy survive the spread as the stop widens** —
> and if a stop width does survive, is it the *same* width on all four, or does each
> instrument need its own?

If no cell survives, the honest conclusion is that this instrument family has no tradeable
net edge under this configuration, and further parameter work on it is not justified.

## What this study is NOT

- **Not an optimisation.** No parameter is searched, tuned or selected. `--stop-mult` is
  swept as a *measurement axis*, not as a parameter to be maximised. The configuration
  (pullback + momentum + mean-revert, band-fade off, TP 2.4R) is the certified V75 preset,
  unchanged.
- **Not an instrument certification.** The same V75 configuration is applied to V25/V50/V100
  precisely because that makes the four columns comparable. A configuration tuned for V75
  being mediocre on V50 is a *finding about transfer*, not a verdict on V50.
- **Not a floor study.** The minimum-equity floors were already answered by
  `scripts/instrument_census.py`: at $39.58 **every** instrument in the family is
  `CAP-VETOED`, the cheapest floor being ~$41 (V50) and the requested four needing
  $75–$99. This study therefore runs at the harness's research equity of **$300**, which
  removes the lot-floor artefact from the signal measurement. No conclusion here says
  anything about whether the operator's actual account can trade.

## Frozen grid (16 cells, one pass, no re-runs)

| axis | values |
|---|---|
| instruments | Volatility 25, 50, 75, 100 (1-tick), corpora at `artifacts/train/{v25t,v50t,v75t_census,v100_census}` |
| stop width (`--stop-mult` on the certified geometry) | 0.5, 1.0, 2.0, 3.0 |
| split | none — full corpus per instrument (see the power disclosure below) |
| equity | $300 (research basis) |
| cost model | cost-inclusive default (fills pay the spread); `CERT_COST_LEGACY=1` is the gross control |

Per-instrument spec env (the engine's own SPEC-INTEGRITY guard requires all five):

| corpus | `CERT_SPREAD` | `CERT_USD_PER_UNIT_PER_LOT` | `CERT_MIN_LOT` | `CERT_LOT_STEP` |
|---|---|---|---|---|
| v25t | 0.225 | 1.0 | 0.5 | 0.01 |
| v50t | 0.016 | 1.0 | 4.0 | 0.01 |
| v75t_census | 16.96 | 1.009 | 0.01 | 0.001 |
| v100_census | 0.18 | 1.0 | 1.0 | 0.01 |

## Frozen metrics and gates

Primary metric: **total net R** over the corpus (`sum(t["r"])`).
Control metric: **total gross R** (`sum(t["r"] - t["r_extra"])`) — the same trades before
the spread is paid. The object under test is `net / gross` and the **sign of net**.

Gate G1 (per cell, must ALL hold to be a VALIDATED-GEOMETRY candidate):
1. `n ≥ 30` closed trades
2. `total_net_r > 0`
3. `max_drawdown_R ≤ 15R`
4. `worst_loss_streak ≤ 8`

Gate G2 (the study's actual claim — must hold for the study to report a survivor):
5. at least one stop width passes G1 on **≥3 of the 4 instruments** (a geometry that only
   works on one instrument is that instrument's accident, not a geometry law)

Verdict mapping, declared now:
- G2 holds → `GEOMETRY-SURVIVES` and the surviving width becomes the pre-registered
  candidate for Phase 5, on paper.
- G2 fails but some cells pass G1 → `INSTRUMENT-SPECIFIC` — report the cells; no candidate.
- No cell passes G1 → `NO-NET-EDGE-ON-THIS-CONFIGURATION` — the study's headline, and the
  evidence that stops parameter work on the certified configuration.

## Disclosed limits (stated before the results, not after)

1. **Power is unequal.** Corpus lengths differ by design (what the broker gave us):
   v25t 20,000 M15 bars, v50t 20,000, v100_census 10,000, v75t_census 6,666. V75 — the
   instrument the configuration was tuned on — has the **shortest** series. A null result on
   V75 is therefore the weakest of the four, and the study must not present a V75 cell as
   decisive in either direction.
2. **No train/OOS split.** Splits were deliberately omitted: with 6,666–20,000 M15 bars per
   instrument, splitting would leave V75 with ~90 in-sample trades. The mitigation is that
   nothing is fitted — the grid is a fixed measurement pass. Any *candidate* that emerges
   still has to clear a fresh-window walk-forward in Phase 5 before it touches paper.
3. **Broker minimum stop distance is unmeasured for V25/V50/V100.** `CERT_MIN_STOP` is the
   V75-specific 107.70 index units. For the other three it is set to **0** (no floor
   enforced) because their values are unknown; this can only *flatter* the tight-stop cells,
   so a tight-stop pass on those instruments is the least trustworthy cell of all. It must
   be measured live before any tight-geometry candidate is armed.
4. **`usd_per_unit_per_lot` is 1.0 by family convention for V25/V50/V100** (only V75 1.009,
   V75-1s 1.0 and V100 1.0 are certified). See `docs/INSTRUMENT_SPEC_MAP.md` provenance.
5. **Corpus provenance.** The M15/H1 CSVs are exact block aggregations of cached broker M5
   bars (`scripts/build_train_corpus.py`, `PROVENANCE.txt` in each dir), not fresh broker
   M15 fetches — no terminal was running. Aggregation of H/L/O/C is exact; the only loss is
   intra-M5 path resolution, which affects neither the stop distance nor the spread toll.

## Execution record

One frozen pass, 16/16 cells, 2026-09-19. Driver: `scripts/geometry_cost_study.py`.
Artifact: `artifacts/train/GEOMETRY_COST_STUDY_20260919.json`. No gate, metric or grid cell
was changed after the first number was read.

### VERDICT: `INSTRUMENT-SPECIFIC`

G2 **FAILS**: no stop width passed G1 on 3 or more instruments (one pass at width 3.0:
Volatility 100 only). Per the pre-registered mapping there is **no candidate**.

| symbol | stop_mult | n | gross R | net R | cost drag R | max DD R | streak | sign flip | G1 |
|---|---|---|---|---|---|---|---|---|---|
| Volatility 25 | 0.5 | 225 | −1.12 | −10.62 | 9.51 | 22.56 | 8 | | |
| Volatility 25 | 1.0 / 2.0 / 3.0 | 227 | −10.87 | −18.50 | 7.63 | 29.80 | 8 | | **(degenerate — see below)** |
| Volatility 50 | 0.5 | 230 | −17.69 | −27.24 | 9.55 | 28.93 | 7 | | |
| Volatility 50 | 1.0 | 333 | +7.17 | −0.05 | 7.23 | 15.03 | 7 | **yes** | |
| Volatility 50 | 2.0 | 202 | −5.84 | −8.93 | 3.09 | 24.71 | 7 | | |
| Volatility 50 | 3.0 | 234 | −23.36 | −27.07 | 3.72 | 36.70 | 12 | | |
| Volatility 75 | 0.5 | 186 | +11.07 | **−0.06** | 11.13 | 21.36 | 6 | **yes** | |
| Volatility 75 | 1.0 | 121 | +1.26 | −2.98 | 4.24 | 21.86 | 10 | **yes** | |
| Volatility 75 | 2.0 | 135 | −0.44 | −5.08 | 4.64 | 22.11 | 6 | | |
| Volatility 75 | 3.0 | 125 | +2.73 | −1.52 | 4.25 | 21.95 | 10 | **yes** | |
| Volatility 100 | 0.5 | 130 | +7.36 | −0.35 | 7.71 | 10.40 | 5 | **yes** | |
| Volatility 100 | 1.0 | 123 | −5.08 | −10.24 | 5.17 | 16.06 | 5 | | |
| Volatility 100 | 2.0 | 125 | −4.42 | −9.53 | 5.11 | 16.85 | 8 | | |
| **Volatility 100** | **3.0** | **124** | **+13.06** | **+8.35** | 4.71 | 10.98 | 5 | | **PASS** |

### The hypothesis is REJECTED, and the sign-flip count is the reason

The pre-registered hypothesis was: *wider stops amortise the spread and preserve the sign of
edge*. On Volatility 75 — the instrument this configuration was tuned on — **six of the eight
sign-flip cells in the whole study are V75's** (0.5, 1.0, 3.0) plus V50@1.0 and V100@0.5.
The mechanism is now measured, not argued:

- **Tight stops** (V75 @0.5, `sd` 271, toll ≈6.3%): gross **+11.07R** → net **−0.06R**. The
  spread consumes **100.5%** of the gross edge. This *reproduces* the program's documented
  5.6%-toll finding on an independent corpus.
- **Widening does not rescue it.** At V75 @1.0 (`sd` 492, toll ≈3.8%) the cost drag halves to
  4.24R but the **gross edge collapses from +11.07R to +1.26R** — the wider stop stops
  catching the moves that paid for it. Net gets *worse*, not better. The trade is not
  "spread versus stop width"; widening the stop changes which trades the strategy wins.

**Therefore the study's central answer is: toll is a geometry property (confirmed), but
using geometry to fix it is not available on this configuration — the same lever that
reduces the toll also removes the edge.**

### NEW FINDING — the pre-registered sweep was partly degenerate

Not anticipated in the pre-registration and disclosed here as a defect of its own design: the
engine's **micro-balance fit** (`MICRO_FIT_PCT=1.5`, `certify_v75.py:474`) rescales the stop
whenever min-lot risk exceeds 1.5% of equity, which **overrides `--stop-mult`**. Median stop
distance per cell:

| instrument | 0.5 | 1.0 | 2.0 | 3.0 | sweep valid? |
|---|---|---|---|---|---|
| Volatility 25 (min lot 0.5) | 5.09 | 6.53 | 6.53 | 6.53 | **NO — saturated** |
| Volatility 50 (min lot 4.0) | 0.38 | 0.71 | 1.06 | 1.085 | partly (2.0→3.0 flat) |
| Volatility 75 (min lot 0.01) | 271.25 | 492.12 | 498.63 | 513.17 | partly (1.0→3.0 compressed) |
| Volatility 100 (min lot 1.0) | 3.03 | 4.30 | 4.44 | 4.77 | yes |

Consequences, stated plainly:

1. **Volatility 25's 1.0/2.0/3.0 rows are the same cell repeated.** Its study contribution is
   one valid cell plus a saturation result, not a sweep. It cannot contribute a G2 pass.
2. **The lot floor dictates the stop, not the strategy.** That is the same force the census
   found: at $39.58 every instrument is `CAP-VETOED`; at a $300 research equity the floor
   still compresses geometry on three of four.
3. **The most defensible single cell is V100 @3.0** (net +8.35R, n=124, DD 10.98R, streak 5,
   toll 3.8%) — and even it is one cell of sixteen on the *shortest-but-one* corpus, with no
   train/OOS split. Per limit 2 of the pre-registration it is **not** a validated candidate:
   it is a hypothesis to hand to a fresh-window walk-forward.

### What this study does NOT license

- No claim that Volatility 100 is tradeable by this program. One cell, one corpus, no OOS.
- No claim that any instrument is tradeable at $39.58 — the census already answered that
  (all `CAP-VETOED`).
- No parameter change to the deployed preset. None is implied and none was made.
