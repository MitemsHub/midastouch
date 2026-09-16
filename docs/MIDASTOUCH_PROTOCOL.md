# MIDASTOUCH PROTOCOL — frozen 2026-09-16, BEFORE any strategy run on gold

This document freezes the rules. Nothing below may be edited after the first
sweep run; amendments append-only, dated, and motivated in their own section.
This is the same discipline that kept the V75 program honest (V28 protocol);
it transfers to gold unchanged in philosophy.

## 1. Data of record

- `data/forex/xauusd/XAUUSD_H1.csv` and `XAUUSD_M15.csv` (broker feed,
  validated 2026-09-16, research span H1 2024-04-10 → 2026-09-16 after the
  disclosed 112-day backfill hole was excluded; M15 capped at 50,000 bars
  by the terminal).
- Specs of record: `artifacts/deriv_symbols_20260916.json`
  (tick value, min lot, contract — the floor table).
- D1 is reference-only. D1 never gates a verdict.

## 2. Strategy family under test (the program's own DNA, ported)

- **Macro filter:** H4 and H1 close[1] vs EMA20[1] on each timeframe;
  ALIGNED_UP / ALIGNED_DOWN / DIVERGENT exactly as the V75 family defined it.
- **Trigger (M15):** BB(20, 2σ) band-touch with close back inside, or
  RSI(14) ≥ 70 / ≤ 30 — the reversal family. Signal fires at bar close;
  fill at next M15 open.
- **Modes (8, same vocabulary as the V28 registry):**
  ORIGINAL, REVERSE_DIRECTION, REVERSE_TRIGGER, REVERSE_BOTH,
  LONG_ONLY, SHORT_ONLY, MACRO_ONLY, TRIGGER_ONLY.
- **Exits (frozen for all modes):** SL = 2.0 × ATR(14, H1) at signal time;
  TP = 2.0 × SL distance; timeout = 48 M15 bars (12h); one position at a
  time; no re-entry while a position is open.

## 3. Cost model (frozen)

- Round-trip spread charged per trade from the **recorded per-bar spread
  column** at entry, half on each side, converted with the symbol's tick
  value; minimum spread $0.10 when the bar records 0.
- Slippage 0 (paper reality; the forward arm measures the real slip).
- Sizing: 1% of equity per trade, min-lot floor enforced and disclosed;
  R = pnl / risk_dollars; equity compounds across trades within a run.

## 4. Windows (frozen)

H1 span 2024-04-10 → 2026-09-16, contiguous, chronological:

| window | span | role |
|---|---|---|
| IS1 | 2024-04-10 → 2025-03-31 | in-sample 1 |
| IS2 | 2025-04-01 → 2026-03-31 | in-sample 2 |
| WF  | 2025-09-15 → 2026-03-31 | walk-forward (subset of IS2, mirrors V28 wf usage) |
| OOS | 2026-04-01 → 2026-09-16 | out-of-sample, touched exactly once |

M15 trigger data and H1 macro data both restricted to the window at signal
time (no look-ahead: every indicator uses closed bars only).

## 5. Gates (frozen — identical philosophy to the V75 program)

A mode is promoted to EA-build only if ALL of:
- **G1 sample:** OOS trades ≥ 30
- **G2 profitability:** OOS net R > 0 in BOTH R measures (ratio-sum and
  money-implied)
- **G3 quality:** OOS profit factor ≥ 1.30
- **G4 expectancy:** OOS expectancy ≥ +0.15R
- **G5 drawdown:** OOS max drawdown ≤ 12R
- **G6 robustness:** mode positive (net R > 0) in at least 3 of 4 windows
- **G7 toll sanity:** mean spread cost per trade ≤ 0.10R

NO-SHIP is the default verdict for every mode. A mode that fails is recorded
failing with its numbers — negative results are published, not buried.

## 6. Pre-registered hypotheses (frozen before the sweep)

- **H1 (session):** trades entered 12:00–16:00 UTC outperform the rest.
  Test: per-mode OOS split by session; frozen uplift gate +0.10R with
  n_session ≥ 20. Exploratory otherwise — never a promotion path.
- **H2 (macro-regime):** ALIGNED_UP and ALIGNED_DOWN behave differently
  (gold's trend bias). Test: per-direction OOS split; gate: same as H1.

Neither hypothesis may be used to re-select parameters after seeing OOS —
they can only qualify an already-passing mode.

## 7. Artifacts of record

`artifacts/midas_sweep_<date>.json` (all runs, all trades, all windows),
`artifacts/midas_sweep_verdict_<date>.json` (gate matrix per mode),
this protocol, and the playbook. All checksummed in the closeout manifest
of the run. Every number printed to stdout is derived from the artifact,
never from memory.

## 8. What happens after a pass

A passing mode → Step 5 EA build (`mql5/MIDASTOUCH/MidastouchAI.mq5`), with
**build parity** proven before anything else: the EA, run in the tester on
the same window, must reproduce the research engine's trades to within the
parity tolerance the V75 program used (max |dR| per trade ≤ 0.01R).
A total refusal → the verdict is published and the program stands down
honestly; no gate gets moved to manufacture a pass.

## 9. Amendment 1 — first sweep verdict (2026-09-16, appended after the run)

The sweep ran the same day as freezing; result: **ALL 8 MODES NO-SHIP**
(`artifacts/midas_sweep_verdict_20260916.json`). Closest: SHORT_ONLY
(OOS PF 1.289 vs G3's 1.30, expectancy +0.136R vs +0.15R, 2/4 windows) —
refused. REVERSE_DIRECTION PF 1.222 also refused. Gates unchanged; no
parameter was touched after OOS was seen. One implementation-fidelity fix
was applied between the two same-day passes (ORIGINAL's macro-agreement
gate per §2 was missing in the mode table; identical parameter set) —
recorded here because anything that changes results must be written down.

Standing interpretation: gold's cost geometry is excellent (G7 passed
everywhere: ~0.002–0.003R spread cost) — the family's entry edge is what
is missing on this feed, echoing the V75 registry's structure. Per §8,
no EA promotion happened on this verdict. Next steps remain within the
protocol: either a NEW pre-registered family (appended below before any
run) or forward paper collection on the plainest variant to mint real
evidence. No gate shopping.

## 10. Amendment 2 — bounded ATR + full re-sweep (2026-09-17, parity-driven)

The first build-parity attempt (WF window, REVERSE_DIRECTION) failed with
entries aligned but per-trade stop distances diverging (median ratio 0.95,
range 0.76–1.29). Instrumented proof (EA v1.02 debug dump vs the validated
CSV series, identical bars): **unbounded Wilder ATR is seed-dominated in
the tester's short preloaded bar window**, diverging up to 11% from a
deep-history-converged Wilder value on the same bars, with the gap growing
backward in time. Two engines with different history depths can never
agree on unbounded Wilder ATR; the live arm adds a third depth. Therefore:

- **ATR of record is now bounded:** SMA of True Range over the last 14
  closed H1 bars (`sma_atr` in the sweep engine, `AtrNow()` in the EA —
  pure bar computation, identical everywhere). This is an indicator
  *definition* fix, not a parameter search: every mode re-ran symmetrically.
- **Re-sweep verdict (all 8 modes, bounded ATR,
  `artifacts/midas_sweep_20260917.json`): ALL MODES NO-SHIP again.**
  Closest: SHORT_ONLY — OOS n=53, net +8.51R, PF 1.343 (G3 pass),
  expectancy +0.1605R (G4 pass), DD 7.21R (G5 pass) — but **G6 fails
  (2/4 positive windows)**: is1 +8.26R / is2 −12.11R / wf −7.25R /
  oos +8.51R. The same era-alternation signature the V75 registry
  documented for REVERSE_TRIGGER: sign belongs to the time segment, not
  the strategy. Refused; no promotion.
- Parity of the EA itself is now a *solved mechanism* (v1.03 computes the
  identical bounded ATR; entries matched to the minute in the v1.01 run),
  but per §8 parity only gates an EA build for a **passing** mode — none
  exists, so no promotion parity certificate is issued.
- **Forward paper collection starts anyway** on the plainest variant
  (ORIGINAL, tag M1): the family's real-time behavior with zero selection
  bias. The forward ledger is evidence-collection, not a profitability
  claim; it is adjudicated only under this protocol's gates, on data that
  did not exist when this amendment was frozen.
