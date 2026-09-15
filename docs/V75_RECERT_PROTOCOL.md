# V75 RE-CERTIFICATION PROTOCOL — reopening the long-only config after the walkforward inversion

**Frozen pre-registration: 2026-09-14.** This document is written *before* any
evidence under it is collected. It defines the only path by which the
V75MacroEngine long-only config may be re-opened as a research question after
the walkforward inversion. It cannot change the engine by itself; a REOPEN
verdict buys a **new protocol registration**, never a direct edit.

Precedent this formalizes: `docs/MOM_STANDALONE_DUEL.md` ("if the market
regime resembles 2024–2025 again, this question can be re-registered — with
fresh data") and ledger row #11 (`docs/OPERATING_SUMMARY.md`): the 2026
deficit is edge decay, not a filterable regime state. Edge decay is a
*time* hypothesis, so re-certification is a *time*-gated protocol.

## 1. What is closed, and what this protocol reopens

Closed (2026-09-14, not reopenable under this document):

- Entry-regime filtering of the 2026 deficit — atr_z / adx / slope / rvol
  carry no separable signal at either granularity
  (`artifacts/v75_macro_engine_tester/regime_analysis_20260914.txt`).
- Exit geometry on the current sample — v2.20's 2h timeout is the measured
  optimum of the what-if grid; TP plateau 0.8–2.0R.
- The sell arm — closed by v2.10 on five-window evidence; no reopening path
  is defined here.

Reopenable by this protocol, exactly one question:

> **Does the pullback-buy edge still exist now — on data the engine has
> never influenced any decision with?**

"Reopen" means: register a NEW selection/strategy protocol and run it through
the standard chain (frozen doc → fresh-window certification → paper arm →
gate). It never means re-tuning the current engine on the accumulation
window.

## 2. The hypothesis, stated so it can lose

- **H_active:** the pullback-buy edge persisted at its train-era strength,
  μ = **+0.189R/trade** (= 966.70 USD / 53 trades ÷ 96.5 mean risk; the
  2024.01–2025.08 train expectancy that selection consumed).
- **H_decay:** the edge is materially weaker than that — the walkforward
  inversion and the 2026 segment (−236.04 on 22 entries; v2.20 full-window
  +0.118R) are its visible face.

The measured v2.20 31-month run is the reference distribution: 76 fills,
mean **+0.118R**, σ = **0.494R**, PF 1.794
(`V75_regress_v220_31m.htm`). σ = 0.494R is frozen for every power statement
below; if a future build changes sizing so the R spread moves, the bars must
be re-derived and the derivation committed before any gate is read.

## 3. The evidence: forward-only fresh tester runs, one build, no peeking

- **Window:** strictly forward from the freeze date, ≥1 full month per
  collection period, starting with a complete calendar month. The existing
  35-month real-tick cache (floor 2024.01) is research-inert for this
  protocol — it is *never* training data for a reopened candidate; its only
  use is reference replay (below).
- **Build pin:** every pass runs the exact working-tree build at freeze:
  `V75MacroEngine.mq5` sha256
  `164450e245c3134dee35a6f2f015ede91f569ad66d6159f5dac32ade7649609a`
  (v2.20, init line `V75 Macro Engine v2.20 initialized (LONG-ONLY, 2h
  timeout)`), magic 7500, tester terminal
  `49E0383CD680D7AAEC56888AFA08F49E` closed during runs. If the build
  changes mid-collection, the series restarts — no splicing across builds.
- **Runner identity gates (hard, per pass):** all fills are buys, zero
  sells; 100% of entries at bar-open; fills/month within 2× of the
  reference 2.45 (a famine or flood means the market changed, stop and
  record, do not average through it). Entry-stream invariants stay hard
  even though exit paths are design-free.
- **No parameter may be touched during collection.** Any engine edit voids
  the accumulated series (the no-hand-tuning non-negotiable, applied to a
  backtest series).
- **Reference replay (integrity, not selection):** each collection period,
  replay the trailing 6 cached months on the same build and require the
  entry stream to reconcile with the v2.20 reference pass (same buys at the
  same bar-opens). This detects silent data-quality drift (symbol spec,
  tick coverage) without ever feeding fresh data back into a decision.

## 4. Gate arithmetic (frozen; one-sided, α = 0.05, σ = 0.494R)

Let n = cumulative fresh fills, m = their mean R. Verdicts are evaluated
**only** at a collection boundary, on cumulative data, in this order:

| Check | Rule (frozen) | Fires when |
|---|---|---|
| **TRIPWIRE** | n ≥ 20 and m ≤ **−0.191R** (t₀.₀₅,₁₉ = −1.729) | edge is actively negative now — stop collecting, record CONFIRMED-DECAY, close the protocol |
| **REJECT-REOPEN** | n ≥ 44 (18 mo) and m ≤ **+0.125R** (t₀.₀₅,₄₃ = 1.681 bar) | no evidence of train-era edge at acceptable power → config stays closed |
| **REOPEN** | n ≥ 73 (30 mo) and m > **+0.096R** (t₀.₀₅,₇₂ = 1.666 bar) | edge survived forward-only → register a new selection protocol |
| **STRONG-REOPEN** | n ≥ 102 and m > **+0.081R** | same, at near-certain power — also permits re-basing the new protocol's expectations on μ ≈ +0.08R, not +0.19R |
| otherwise | n < 44 and not TRIPWIRE | KEEP COLLECTING — threshold rule, not a time-box; no interim verdicts |

Between-boundary arithmetic is recorded in the collection log but decides
nothing. Do not stop early on good-looking interim means; do not continue
past a REJECT-REOPEN "to see if it comes back."

Why these bars (computed at freeze, noncentral-t power, σ = 0.494R):

- REJECT-REOPEN (n=44, bar +0.125R): power **0.81** against H_active
  (μ=0.189R), 0.47 against μ=0.118R. Chosen so a *genuinely persistent*
  train-era edge is very likely detected at ~18 months, while a merely
  v2.20-strength edge (0.118R) is honestly acknowledged as a coin-flip at
  this n — that ambiguity is what the 30/42-month continuation resolves.
- REOPEN (n=73, bar +0.096R): power **0.95** at H_active; 0.65 at
  μ=0.118R — a v2.20-strength edge usually needs the full window.
- STRONG-REOPEN (n=102, bar +0.081R): power **0.99 / 0.77**.
- TRIPWIRE (n=20): false-fire probability 0.0005 under H_active, 0.004
  under μ=0.118R, 0.05 under μ=0 — an alarm that means what it says.

Fills cadence at the reference 2.45/month: 44 fills ≈ 18 months
(≈ 2028-03), 73 ≈ 30 months (≈ 2029-03), 102 ≈ 42 months (≈ 2030-03).
These are expected values, not deadlines — the gates count fills, not days.

## 5. Cadence

| When | Action |
|---|---|
| Monthly (first collection boundary, e.g. 1st business day) | Run one fresh-window tester pass over the closed months not yet collected; append fills to the series ledger (`artifacts/v75_macro_engine_tester/recert_series.jsonl`, one record per fill: entry ts, R, exit path); evaluate the Section 4 order; write a one-line status even when the verdict is KEEP COLLECTING |
| Quarterly | Cache-extension probe (the `cache_extension_and_walkforward_20260913` procedure) to keep the trailing real-tick cache current for reference replays; refresh the reference-replay reconciliation |
| At any verdict | Verdict row + changelog + commit (the standard study-result chain); TRIPWIRE or REJECT-REOPEN additionally appends a closure note to ledger row #11 |
| Annually | Re-freeze check: confirm build pin unchanged, runner gates unchanged, σ re-estimated from accumulated fresh data *for reporting only* — bars stay as frozen unless a sizing change forces re-derivation (Section 2) |

Anti-drift rules, binding: no interim verdicts between boundaries; no
threshold moves after data is seen; a failed gate may be *appealed* only by
pre-registering a different hypothesis (e.g. "edge exists only in high-vol
months" — which must survive the row-#11 rule that regime states showed no
separation, i.e. it starts already disfavored) with its own window and its
own bars, never by re-reading this gate.

## 6. What REOPEN buys (and what it does not)

A REOPEN verdict reopens the *research question*, not the engine. The next
step is a new frozen protocol for candidate selection on the fresh window
(what the walkforward harness `tests/v75_walkforward.py` does, but with
selection data the current engine never touched), then the standard chain:
fresh-window certification → paper arm → the pre-registered gate in
`docs/OPERATING_SUMMARY.md` §3. The LIVE preset changes only through that
chain. If the paper gate adjudicates first (TJ1/TJ2/TJ3 on the existing
arms), its verdict governs live trading regardless of this protocol's
status — the two gates are independent and neither shortcuts the other.

## 7. Provenance

- Reference distribution: `V75_regress_v220_31m.htm` (76 fills, +0.118R mean,
  σ 0.494R, PF 1.794) — the v2.20 31-month real-tick pass.
- Train-era expectancy: v210 31m per-trade table, 2024.01–2025.08 segment
  (+966.70 / 53 trades), regime analysis artifact for the join.
- Build pin: working-tree `V75MacroEngine.mq5` sha256 at freeze (above);
  compile gate `scripts/_compile_v75_terminal.ps1` (0 errors + fresh .ex5).
- Walkforward inversion record: `artifacts/v75_macro_engine_tester/
  cache_extension_and_walkforward_20260913.txt`, `walkforward_powered.json`.
- Closed-questions ledger: `docs/OPERATING_SUMMARY.md` rows #3, #6, #11.
