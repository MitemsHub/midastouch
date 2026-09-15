# V75 PARAMETER TRAINING PROTOCOL — frozen 2026-09-15 before any search run

**Directive:** train the EA's parameters on data we already hold, today.
This document freezes the split, the fill model, the search space, the
selection rule, and the ship/no-ship gates BEFORE the first grid run.
Amendments are append-only and dated. Nothing here changes engine code;
the deliverable is a preset (parameters) plus a validation artifact.

## 1. Data

- Source: `artifacts/data/volatility_75_index_m15_40000bars.csv` (40,000 M15
  bars, 2025-07-13T03:45Z → 2026-09-02T19:45Z, ~417 days, broker-validated
  corpus family). H1 context aggregated from the same M15 source (h1 is used
  for regime context only in the harness).
- Training copy: `artifacts/train/m15.csv` + `artifacts/train/h1.csv`
  (harness CSV format, ISO timestamps). Run with `CERT_DATA_DIR=artifacts/train`.
- Integrity: rows deduplicated by timestamp; span verified before use.

## 2. Split (chronological, no shuffling)

| segment | window | role |
|---|---|---|
| warmup | first 200 bars of the file | indicator warmup only |
| IS (train) | 2025-08-01 → 2026-06-01 (exclusive) | search + selection |
| OOS (holdout) | 2026-06-01 → end (2026-09-02) | validation only, never searched |

The OOS window fully contains the certified fresh-60 window
(2026-07-04 → 2026-09-02), so OOS numbers are comparable to known baselines.

## 3. Fill model

- **Selection objective: `touch` mode** — first touch of a resting SL/TP
  level fills at the level. This is the M15-OHLC approximation of the live
  broker-side resting orders the engines actually use (v26.38+ semantics),
  and of per-tick paper fills since v26.38.
- **Stress check: `ladder` mode** (bar-open fills) on the winner — the
  pessimistic bound of management granularity. A winner is reported under
  both; it does not need to win under ladder to ship, but the ladder number
  is recorded next to it.
- Equity basis 300 for every run (avoids money-cap strangulation artifacts;
  R-statistics are the objective anyway). Auto-disable cascade stays ON
  (real engine behavior).

## 4. Search space (IS only)

Stage 1 grid (108 runs):
- `tp-mult`: 1.6, 1.8, 2.0, 2.4
- `stop-mult`: 0.9, 1.0, 1.15
- `be-trigger`: 0.8, 1.0, 1.2
- `plock-z`: 0.4, 0.5, 0.6 (`plock-hw` fixed 1.0)

Stage 2 (≤ 36 runs, top-8 of stage 1 only):
- `pb-min`: 0.55, 0.60 (default), 0.65
- `pb-max`: 0.70, 0.75 (default), 0.80
- `blocks`: none (default), `3,14,20` (hour blocks from prior studies)

## 5. Selection rule (frozen)

Among IS runs satisfying ALL of:
- n ≥ 80 IS trades,
- maxDD ≤ 25%,
- worst loss streak ≤ 8,
- win rate ≥ 40%,

pick the highest `total_r` (R-units); tie-break: higher n, then lower maxDD.

## 6. Ship / no-ship gates (OOS, run once for the winner)

The trained config SHIPS (preset update + artifact) only if ALL hold:
1. OOS n ≥ 25 trades,
2. OOS total_r > 0,
3. OOS maxDD ≤ 30%,
4. OOS meanR ≥ 50% of IS meanR (degradation bound),
5. OOS total_r ≥ baseline-OOS total_r + 1.0 R (beats the shipped config by
   a margin, not noise).

Baseline = current shipped parameters (all harness defaults, touch mode),
run on the same split. If no candidate passes gate 5, the honest verdict is
**"no trainable edge over the shipped config on this corpus; baseline
stands"** and nothing ships.

## 7. Amendment A (2026-09-15, written AFTER stage-1 results, BEFORE any OOS run)

Stage 1 produced **0/108 eligible candidates** (best IS ≈ −14R, DD 40–50%,
streaks 7–11). Before declaring no-trainable-edge, one bounded extension
tests the harness's remaining STRUCTURAL levers on IS only:

- `--ema-side-filter` (trade only with the H1 EMA trend side)
- `--family-throttle`
- `--min-score-bonus` 4 and 5 (stricter entry score)
- `--legacy-sl`
- the above in combination with the 6 best stage-1 geometries by R

Same eligibility bar (n ≥ 80, DD ≤ 25%, streak ≤ 8, WR ≥ 40%). If any
config is eligible, it goes to OOS under the same six gates. If none is,
the verdict is final: **no trainable edge in this strategy family on this
corpus; baseline stands** — and the certified fresh-60 +4.37R is recorded
as favorable-regime luck, not skill.

## 8. Deliverables

- `artifacts/train/TRAINING_REPORT.json` — every run's config + metrics
  (IS and OOS), the winner, the baseline rows, and the verdict.
- If shipped: updated preset file + changelog entry + checklist note.
- If not shipped: the report + changelog note; parameters stay as certified.
