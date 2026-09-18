# FILL-COST STRESS PROTOCOL — frozen 2026-09-15, before any run

**Question:** does the certified replay edge (+4.37R / 114 trades / 60d) survive the
execution costs we have actually *measured on this account's own feed*, or was the
certification optimistic? This decides whether TJ1's current negative paper expectancy
is bad luck under conservative fills, or the certification itself was.

**Precedence:** this is a diagnostic, not an engine change. No input, geometry, or
gate changes as a result. It *informs* the arm-A/B adjudication at 30 trades and the
go-live decision only. Amendments append-only and dated.

## 1. Measured inputs (frozen, all from this account's own data)

| quantity | value | source |
|---|---|---|
| spike-path stop overshoot (mean beyond stop on fill) | **0.516R** | `stop_gap_decomposition_20260915.json`: spike_path gaps −0.631, −0.401 → mean −0.516R, n=2 |
| spike-path share of stop crossings | **21.3%** | `spike_continuation_20260915.json`: 516/2421 crossings |
| all-stops mean bar-open cost | **−0.248R/stop** | `stop_gap_decomposition_20260915.json` (n=6 original stops, CI excludes 0) |
| bar-open jumps > 0.1R | **0 in 575 opens** | same artifact, structural test |
| cascade continuation (2-min, spike vs slow) | **+0.178R, p<0.0001** | `spike_continuation_20260915.json` — the mechanism is real |

The certified baseline (`ladder` mode) fills spike-path stops **clean at the stop
level** and applies no per-tick spike overshoot. The paper evidence says real fills
do worse on ~21% of stop exits by ~0.5R. The stress ladder quantifies what that does
to the certified window.

## 2. Frozen scenario ladder

All runs: `--exit-mode ladder_spike`, the certified window, pinned harness G0 settings,
1.0% risk, $10k notional basis, spread 18.5, USD/unit/lot 1.009.

| id | spike_overshoot_r | models |
|---|---|---|
| S0 | 0.0 | certified reproduction (must match G0: +4.37R, n=114) |
| S1 | 0.251R | hybrid study's paper-measured overshoot (harness default) |
| S2 | **0.516R** | the newest measured mean, applied at measured 21.3% rate |
| S3 | 1.0R | stress bound: fill 1 full R beyond every spike-path stop |

The harness applies the overshoot to spike-path fills only, which already embodies the
measured share (the exit-mode distinguishes spike-path stops intrinsically).

## 3. Frozen decision rule

Compute `E[R/t]` for each scenario and the **decay slope** dE/d(overshoot). Then:

- **If S2 ≥ +0.02R/t** (the frozen materiality bar from VSG): the edge survives
  measured costs — the arms' negative paper runs are plausibly small-sample luck, the
  collection clock keeps running, and TJ1 adjudicates as planned. No re-baselining.
- **If S2 < +0.02R/t but S1 ≥ +0.02R/t:** the edge survives the hybrid-measured cost
  but not the newest mean — MARGINAL. Arm A/B adjudication proceeds, but any future
  certification must be re-run at S2 fills before live authorization.
- **If S1 < +0.02R/t:** the edge does not survive *already-paper-measured* costs —
  the certification was cost-blind. The negative paper arms are confirmed signal, not
  noise. **STOP spending on collection**; the strategy needs re-work (exit mechanics
  or entry quality), not more paper trades.

The slope dE/d(overshoot) also tells us exactly how many R per 60d each 0.1R of
unfilled spike slippage burns — the number that prices any exit-mechanics fix.

## 4. Outputs

`artifacts/v75_replay/fill_cost_stress_20260915.json` — one block per scenario:
n, total R, E[R/t], win rate, max DD%, worst streak, funnel counts, plus the decay
slope and the decision-rule verdict. Written once, after all runs complete.