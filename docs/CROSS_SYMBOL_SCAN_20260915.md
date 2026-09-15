# CROSS-SYMBOL EDGE SCAN — frozen 2026-09-15 before any run

**Directive:** scan the other broker symbols we already hold data for
(V100, V75-low) through the same harness to find where this strategy
family actually has an edge. Frozen before the first run; amendments
append-only.

## 0. What already exists (honestly scoped)

- **V75 (original):** trained (NO-SHIP, 0/108) and sprinted (rebuilt entry:
  +11.9R IS / −5.7R OOS — relative win, absolute NO-SHIP). Reference rows.
- **V100:** `docs/V100_NET_EDGE_STUDY.md` already adjudicated the OLD
  configs (legacy, v2629, tp18) at true specs: gross edge dies net;
  Q1/Q2 NO; V100 stays uncertified. The **rebuilt entry has never run on
  V100** — that is this scan's open question. Canonical V100 spec
  (from the study): `CERT_SPREAD=0.26, CERT_USD_PER_UNIT_PER_LOT=1.0,
  CERT_MIN_LOT=1.0, CERT_LOT_STEP=1.0`.
- **V75 low (1s):** NO data exists anywhere in the repo. Scan action:
  attempt a live MT5 collection (terminal host is running); if the symbol
  does not exist on this broker/server, record that fact and close the
  branch. A fresh M15 series needs ≥ 30 days before any run is meaningful;
  collection alone is not evidence.

## 1. Data

- V100: `artifacts/v100_replay/` m15+h1, 71,039 M15 bars,
  2024-08-25 → 2026-09-04 (~2 years). Split:
  IS 2024-10-01 → 2026-06-01; OOS 2026-06-01 → 2026-09-04 (identical OOS
  to V75's for regime comparability).
- V75-low: only if collection succeeds; else the branch records
  NOT_AVAILABLE with the probe evidence.

## 2. Configs scanned (same on every symbol)

1. `shipped` — module defaults, ema_side off (the certified baseline).
2. `trained_best` — tp1.6/sm1.0/be1.2/pz0.5 + ema_side (training's
   best-but-ineligible row; relative anchor).
3. `rebuilt` — pb 0.60/0.70, tp1.6, be1.0, pz0.5, ema_side ON,
   MR OFF (the sprint winner).
4. `rebuilt_fullstack` — same + m15_full_stack (sprint finalist 3).

Touch fills, equity 300, risk 0.005, auto-disable ON, spec constants
explicit per symbol. **No searching on any symbol here** — fixed config
set, one pass, like-for-like across symbols.

## 3. Gates (per symbol, per config — same philosophy as before)

- **SCAN pass:** n ≥ 60, totalR > 0, DD ≤ 30%, streak ≤ 10, WR ≥ 40%.
- **OOS confirmation (only for SCAN-passers):** OOS n ≥ 20, OOS totalR > 0,
  OOS DD ≤ 30%. A symbol "has an edge" only if a config passes SCAN + OOS.
  Verdict per symbol: EDGE / NO-EDGE / INSUFFICIENT-DATA, with the gate
  matrix attached. Negative results are recorded, not buried.

## 4. Amendment A — H1 timeframe test (2026-09-15, written before any H1 run)

**Question:** does V75 (1s) become tradeable at H1, where stop distances
are larger and the relative spread toll drops? Control: V75 (1t) at H1 —
it separates "no edge at H1 anywhere" from "edge exists but cost still
dies".

- Data: H1-primary replay — the harness consumes H1 bars as its M15 feed
  (aggregated from the same broker pull, no synthetic bars) with H4 context
  aggregated from the same H1 source. No search, same four frozen configs,
  same gates as §3, one pass.
- V75(1s) H1 corpus: 24,017 H1 bars (2023-11-06 → 2026-09-15).
- Note: engine timeframe constants (MAX_HOLD=20 bars, BAND_HOLD_BARS=4,
  block-hour semantics) keep their bar meaning, so "TIME" exits now span
  20 H1 bars — this is a different-horizon test of the same logic, not a
  claim that the deployed EA runs on H1.

## 5. Amendment A results (filled after the one-pass runs)

| run | IS | OOS |
|---|---|---|
| V75(1s) H1, shipped | **+10.51R**, n=406, DD 25.7%, stk 6 — SCAN PASS | −3.97R, n=53, DD 33.8% — FAIL |
| V75(1s) H1, trained_best | −1.16R | — |
| V75(1s) H1, rebuilt | −1.98R | — |
| V75(1t) H1, shipped (control) | −16.64R, DD 67% | — |
| V75(1t) H1, trained_best | −20.31R | — |
| V75(1t) H1, rebuilt(+fs) | −4.79R, n=30 | — |

**Verdict: NO-EDGE under the frozen gates — but the binding constraint has moved.**
- The control shows the H1 horizon is not a general fix (V75-1t at H1 is
  miserable everywhere).
- On V75(1s)@H1 the spread toll drops to 1.24% of stop distance (M15 was
  5.6%; the 1t home symbol runs 2.2%) — the lowest cost burden of any
  combination tested — and the SHIPPED config posts the only SCAN pass on
  any alternative symbol or timeframe (+10.51R/406t in-sample). At H1,
  cost stops being the binding constraint.
- What fails is OOS persistence: −3.97R over the shared Jun–Sep 2026 OOS
  window (DD 33.8% breaches the 30% gate). This is the SAME failure mode
  as the home symbol's rebuilt entry (+11.9R IS → −5.7R OOS). Honest
  caveat: the OOS window is shared across all these tests — one regime
  draw, not independent confirmations. Every in-sample gain found this
  cycle dies in the same 3 months; whether that is a hostile regime or
  pervasive overfit is THE open question of the program.

## 6. Deliverables

`artifacts/train/CROSS_SYMBOL_SCAN.json` (gate matrix, all runs),
changelog entry, updated OPERATING_SUMMARY question row. Engine code and
presets untouched.
