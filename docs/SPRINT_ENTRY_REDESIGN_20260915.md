# ENTRY REDESIGN SPRINT — frozen 2026-09-15 before any candidate run

**Directive:** rebuild the entry around the measured EMA-side effect and
iterate candidates on the training harness until one survives the frozen
OOS gates. This document freezes families, budget, ranking, and the
finalist/OOS procedure BEFORE the first run. Amendments append-only.

## 0. Ground truth carried from the training protocol

- Data: `artifacts/train/` (40k-bar corpus, 417 days). IS 2025-08-01→2026-06-01
  (search), OOS 2026-06-01→2026-09-02 (validation only, ≤ 3 finalist runs +
  1 baseline run — nothing else may touch it).
- Fill model: touch (broker-side resting-order approximation). Equity 300,
  risk_frac 0.005, auto-disable ON, spec-integrity constants set.
- **Fidelity finding to test:** the deployed V75 preset runs
  `InpUseBandFade=false` (certify_v75.py USE_BAND_FADE), but the harness
  emits BF legs — the certified +4.37R and the −15.1R baseline-OOS include
  BF trades the live engine cannot take. Family A runs each candidate with
  BF off (live-faithful) and BF on (harness-faithful) to price this gap.

## 1. The kernel (what is being rebuilt)

Training's one real signal: the EMA-side filter (veto a pullback entry when
price has closed through M15 EMA20 against the trend) flipped the family
−15R → +1.5R on IS. Every candidate keeps `ema_side = ON` and treats
**trend-side pullback (PB)** as the core entry. MR/BF/MOM are context legs.

## 2. Candidate families (IS only)

- **A — geometry around the kernel:** pb band (pb_lo, pb_hi) ∈
  {0.50, 0.60} × {0.70, 0.80}; tp_mult ∈ {1.6, 1.8}; be_trigger ∈ {0.8, 1.0};
  bf ∈ {off, on}. 32 runs.
- **B — structure tightenings:** m15 full stack (eF>eM>eS for longs);
  h1_sep (H1 EMA separation) 0.20 vs 0.30; disable_mr on/off; mom_confirm
  (PB requires a same-direction MOM body leg). On the best-2 A geometries.
  ≤ 64 runs.
- **C — refinement of the top-2 B configs:** pb band fine steps ±0.05.
  ≤ 12 runs.

Total budget ≤ ~120 IS runs (~2 min at 0.5 s/run). Anchors (not candidates):
lab-vs-harness equivalence must be EXACT (same n, totalR, DD) for
ema_side off and on before any candidate counts.

## 3. Ranking and finalists (frozen)

Eligibility (same bars as training): n ≥ 80, DD ≤ 25%, streak ≤ 8,
WR ≥ 40%. Rank by totalR; tie-break n then DD. **Finalists: top 3
structurally-distinct configs.** No OOS run may happen before finalists are
fixed and written into the sprint log.

## 4. OOS gates (unchanged, frozen in TRAINING_PROTOCOL §6)

1. n ≥ 25, 2. totalR > 0, 3. DD ≤ 30%, 4. OOS meanR ≥ 50% of IS meanR,
5. OOS totalR ≥ baseline-OOS totalR + 1.0R (baseline re-run fresh this
sprint), 6. the finalist's ladder stress row recorded (not gated).
SHIP requires ALL of 1–5 on at least one finalist. Multiplicity is honestly
noted: 3 finalist tests, not 120.

## 5. Deliverables

`artifacts/train/SPRINT_REPORT.json` (equivalence proof, all IS runs,
finalists, OOS rows, gate results, verdict), protocol doc, changelog.
If SHIP: preset spec + deployment are a SEPARATE step requiring the
standard compile/sync/restart discipline — this sprint only certifies
parameters.
