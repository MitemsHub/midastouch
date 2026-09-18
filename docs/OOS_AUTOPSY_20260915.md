# OOS AUTOPSY — rebuilt entry — frozen gate design 2026-09-15

Autopsy data: `artifacts/train/AUTOPSY_TRADES.json` (IS n=137 +11.89R /
OOS n=40 −5.73R, touch fills, equity 300).

## 1. Autopsy findings (data, not choices)

- OOS loss is entirely short-side: BEARISH/SELL 10 trades, WR 10%, −6.11R.
  BULLISH/BUY: +0.38R, WR 50%. MOM+PB legs: −5.40R OOS (IS: −0.07R).
- IS edge is entirely short-side: BEARISH/SELL 80 trades +16.46R WR 56.2%;
  BUYs negative even in-sample (−4.57R). PB legs +11.96R IS.
- Market context: IS year = grinding bear (≈49k → 29.5k); OOS = violent
  bull recovery (≈29.5k → 47k). The H1 regime classifier lags the recovery,
  labels downswings BEARISH, and the family sells into a bull.
- Rejected gate axes (recorded, not pursued — overfit traps):
  hour-of-day (n per cell too small, unstable across windows), ATR-percent
  band (mid-band is the best IS bucket and the worst OOS bucket — not
  separable by vol percentile).

## 2. Participation gates (frozen before any gated run)

- **HTF-SLOPE (primary):** a PB-family trade may only point in the
  direction of the 24-hour slope of H1 EMA100 (SELL requires slope < 0,
  BUY requires slope > 0). Rationale: the family trades pullback
  continuation; a counter-slope entry contradicts its own thesis. This is
  the "switch the family off in hostile conditions" gate: hostile = the
  higher trend runs against the entry.
- **NO-MOM (secondary):** disable MOM legs entirely (kills lone-MOM —
  already demoted — and MOM+PB combos). Rationale: MOM+PB is the only
  strategy bucket negative in BOTH windows.
- **BOTH = HTF-SLOPE + NO-MOM is the pre-declared primary candidate.**
  The single-knob variants are diagnostics; the verdict is declared on
  BOTH only.

## 3. Evaluation rule (frozen before running)

- IS preservation: totalR_IS ≥ +8.0 AND n_IS ≥ 60 (the gate must not
  destroy the edge it protects).
- OOS improvement: totalR_OOS > −5.73 (the ungated baseline) — reported;
  ship gates re-applied on top (OOS totalR > 0, DD ≤ 30%, n ≥ 25).
- Replication check (honesty, not a gate): the same HTF-SLOPE gate on the
  V75(1s)@H1 shipped candidate (IS +10.51R) must not collapse (≥ +5R).
- Multiplicity note: 3 gated configs touch OOS; the primary is BOTH.

## 4. Results (filled after the runs)

| config | IS (preserve ≥ +8R, n ≥ 60) | OOS (ship gates) | verdict |
|---|---|---|---|
| ungated baseline | +11.89R, n=137, DD 14.6% | −5.73R, n=40, DD 13.8% | reference |
| HTF_SLOPE | +12.78R, n=135 | −6.57R, n=40 (1 veto) | fails — near-inert here |
| NO_MOM | +11.85R, n=118, DD 12.9% | **+1.53R, n=25, DD 3.8%** | **all gates PASS** |
| **BOTH (primary)** | **+12.74R, n=116, DD 11.3%** | **+1.53R, n=25, DD 3.8%** | **all gates PASS** (+ IS improvement) |

- **Attribution (honest):** the OOS fix comes entirely from NO_MOM —
  the gate vetoed 22 OOS MOM-leg trades, which is exactly the −5.40R
  MOM+PB OOS bleed from §1. HTF-SLOPE vetoes only 0–2 trades on the home
  symbol (the H1 regime classifier already enforces most of the slope
  condition) and alone is OOS-neutral-to-worse. Its value is elsewhere:
  on the V75(1s)@H1 candidate it removed 20 counter-slope trades worth
  −11.65R — **+10.51R → +22.16R IS** (replication bar was ≥ +5R: PASS).
- **Degradation gate (training §6) also passes for BOTH:** OOS meanR
  0.061 vs IS meanR 0.110 → ratio 0.56 ≥ 0.5.
- **Circularity caveat, on the record:** the NO_MOM fix was designed from
  this same OOS window's autopsy, so the OOS pass is not independent
  evidence — it is a diagnosis-then-verify loop on one window. What this
  study legitimately produces is a **gated candidate that qualifies for
  forward testing** (rebuilt entry + BOTH gates), not a validated
  strategy. An independent window (forward test or a later backtest
  window) is the only clean judge.
- **Tooling note:** the harness function's default `TP_MULT_CERT=2.4` is
  the legacy geometry, not the deployed preset's 1.8 — any default-
  argument call silently tests TP 2.4. Two replication attempts were
  discarded for exactly this reason (plus one for post-import env
  switching caching instrument constants); all recorded rows are the
  corrected ones.
