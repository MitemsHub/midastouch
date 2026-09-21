# GOLD v2 RESEARCH — 2026-09-19 (corrected geometry, corrected null)

Operator directive: *"iterate as many times as possible... continue to test and test with
the data until you are good to go."*

This records the second iteration on XAUUSD. It **corrects two defects in my own
tooling** from the first iteration, re-runs the search on the corrected basis, and
reports the verdict. It is not a validation.

---

## 0. Verdict first

**STILL NOT VALIDATED — 4 of 6 frozen criteria fail.** But the reason changed, and
the reason is now actionable.

| | v1 (`GOLD_WFO_VERDICT_20260919.md`) | **v2 (this run)** |
|---|---|---|
| OOS total | +20.67R / 568 trades | **+62.47R / 2267 trades** |
| per trade | +0.0364R | **+0.0276R** |
| t-statistic | +0.52 (needs ≥1.5) | **+0.71** — FAIL |
| positive folds | 12/30 = 40% (needs ≥60%) | **10/21 = 48%** — FAIL |
| worst fold | −8.06R (needs > −3) | **−22.32R** — FAIL |
| median fold | −0.72R (needs > 0) | **−4.16R** — FAIL |
| beats control | PASS | **PASS** (p = 0.016) |
| prop Best Day | breach (80.6% of profit) | **breach (55.5% of profit, cap 20%)** |

The **shape is the same as v1**: a positive total carried by a handful of folds, a
negative median, and a t-statistic indistinguishable from zero. The differences are
that the measurement is now trustworthy, the null is now a real null, and the
failure mode has a name (§4).

---

## 1. Correction 1 — the cost floor was 2.3× too optimistic

The number repeated across this project has been **"gold costs 0.0247R per round
trip"**. It is not wrong in general; it is wrong *for the geometry we trade*.

The toll in R is `spread_distance / stop_distance + commission / stop_distance`.
`upcomers_cost_rank` fed it the **hourly** profile ATR (~$23), but the walk-forward
executes an **M15** 1-ATR stop, which is **$9.89**. Measured on the same price
($4,377.66):

```
stop $ 9.89  (0.23% of price)  ->  spread 0.0475 + comm 0.0101 = 0.0576R
stop $23.00  (0.53% of price)  ->  spread 0.0204 + comm 0.0043 = 0.0248R   <- the quoted figure
stop $32.36  (0.74% of price)  ->  spread 0.0145 + comm 0.0031 = 0.0176R
```

So a **1-ATR M15 stop pays 0.0576R per round trip — 2.3× the floor the project has
been reasoning from.** The v1 walk-forward's own arithmetic was right (it booked cost
from the risk it actually took), so its results stand; what was wrong is the framing
"the toll eats 92% of the edge", which was computed against a stop nobody was
trading. I also stated "gold's ATR is 0.53% of price" in earlier turns — that was
the hourly figure, not the M15 one (0.23%). Correcting that here.

---

## 2. Correction 2 — v1's random control never randomised anything

`random_control()` in `scripts/gold_walkforward.py` built its entry bars as
`usable[k % len(usable)]` — **the first N usable bars in order**. Across the 200
replications only *direction* varied; the entry times were one fixed, contiguous
early slice of the window. Its result — "random entry, same geometry, −0.152R per
trade" — was therefore not a null distribution at all.

**Consequence:** the v1 conclusion *"the entry logic genuinely adds +0.19R/trade, 8×
the toll"* is not supported and should not be relied on. It was the single most
encouraging number in the first iteration, and it was an artifact. The 200 "reps"
were also near-duplicates (same entry bars), so the dispersion around that mean was
meaningless too.

`gold_wfo_v2.py` replaces it with a **matched null**: same geometry, same trade count
*per fold*, entries drawn **uniformly inside each fold**, and the **entire selection
procedure** replicated on the null data — so the comparison is against
"what could best-of-48 pick on noise have produced?", not against one config.

---

## 3. Correction 3 — the geometry was the wrong place to look, and the fix is measured

`scripts/gold_geometry_study.py` measures the bracket with **no entry signal**: a
coin-flip entry at every session bar, both directions, over 9,593 entry bars. It
decomposes

```
E_dir   = (E_long + E_short) / 2   the DRIFT-NEUTRAL coin flip = the geometry's own bias
E_drift = (E_long - E_short) / 2   the window's directional drift
```

and reports the answer as a **band** between the pessimistic and optimistic readings
of the same-bar tie, because bar data cannot say which barrier was touched first.

First, the good news about this sample: **drift is negligible**. Mean forward move
over the holding window is −0.012 to −0.051 ATR and 48.1–49.5% of entries are up. So
the bracket's bias is not a hidden directional bet.

The band is where the finding is:

| stop (ATR) | same-bar assumption band | round-trip toll |
|---|---|---|
| 0.5 | **±0.0727R** | 0.1176R |
| 0.75 | ±0.0192R | 0.0784R |
| 1.0 | ±0.0094R | 0.0588R |
| 1.5 | ±0.0037R | 0.0392R |
| 2.0 | ±0.0029R | 0.0294R |
| 2.5 | ±0.0032R | 0.0235R |
| 3.0 | ±0.0033R | 0.0196R |

Three things follow, and they are the most useful measurements in this document:

1. **v1 tested stops of 1.0 and 1.5 ATR — the worst available region.** At a 1-ATR
   stop the *measurement itself* (the tie assumption) is worth ±0.0094R, comparable
   to everything else in play, and the toll is 0.0588R.
2. **At ≥2 ATR the conclusion stops depending on the assumption** (±0.003R) and the
   toll drops to 0.0196–0.0294R — i.e. it *reaches the quoted 0.0247R floor*, which
   explains where that figure came from: it was implicitly a wide-stop number.
3. **On a wide stop the bracket is provably fair.** Many cells give
   `E_dir = +0.0000` (e.g. H=16, stop 3.0, RR 1.33: E_dir +0.0000, band 0.0049).
   So the v1 conclusion "the geometry bleeds 0.13R and entries can't be judged on
   it" was **a property of a 1-ATR M15 stop, not of gold.**

`gold_wfo_v2.py` therefore searches stops of **1.5–3.0 ATR** with holds of 16 or 32
M15 bars. That floor is justified by the band measurement above, not by a backtest
score — which is the difference between choosing a parameter and declaring a
constraint.

### Path statistics (assumption-free), M15, in ATR units

| H | dir | med MFE | med MAE | P(MFE≥1) | P(MAE≥1) |
|---|---|---|---|---|---|
| 4 (1h) | long | 0.78 | 0.82 | 38.7% | 41.5% |
| 8 (2h) | long | 1.09 | 1.18 | 53.0% | 56.7% |
| 16 (4h) | long | 1.53 | 1.80 | 65.2% | 70.3% |
| 32 (8h) | long | 2.32 | 2.77 | 75.9% | 80.4% |
| 64 (16h) | long | 3.08 | 3.80 | 82.2% | 85.5% |

---

## 4. The v2 run, and the diagnosis

Grid: 48 configurations (2 EMA sets × 4 stops × 3 RR × 2 holds), 22 folds of 8 days,
final 40 days held out untouched. 125,808 in-sample trades across the grid; 2,267
out-of-sample trades.

```
OOS total        +62.47R over 2,267 trades = +0.0276R/trade
t-statistic      +0.71      (needs >= 1.5)      FAIL
positive folds   10/21 = 48% (needs >= 60%)     FAIL
worst fold       -22.32R    (needs > -3.0)      FAIL
median fold      -4.16R     (needs > 0)         FAIL
beats null       +62.47R vs p95 -12.27R         PASS  (p = 0.016)
```

Fold by fold, the pattern is unmistakable:

```
F02  +0.96   F08 +34.89   F14 +22.82
F03  +8.73   F09 +17.55   F15 +41.23
F04 +27.99   F10 -22.32   F16 +15.24
F05 +26.40   F11  -4.33   F17 -11.13
F06 -19.26   F12  -4.16   F18 -17.95
F07  -8.30   F13  -4.86   F19 -14.35
                          F20  +3.30
                          F21 -17.77
                          F22 -12.22
```

**The strategy is trend-following, and it is regime-dependent.** Winning folds make
+0.13 to +0.36R per trade; losing folds lose −0.15 to −0.62R. The folds cluster in
runs (F02–F09 mostly positive, F10–F13 negative, F14–F16 positive, F17–F22 mostly
negative) with no ex-ante way to tell which one is starting. That is a property of
trend following, and it is exactly what the "positive folds ≥ 60%" criterion exists
to catch.

Two secondary observations from the run:

- **The selection is unstable.** The picked config changes constant between folds —
  stops 1.5, 2.0, 2.5, 3.0 all get picked, and the EMA set flips between (8,21,50)
  and (12,26,100). No configuration is robustly best; the selection is chasing noise
  inside each training fold.
- **Concentration, not absence of signal.** The null comparison passes (p = 0.016) —
  but note the null's *median* is −73.54R over the same trade count, i.e. ≈ −0.032R per
  trade, which is just the cost. So "beats the null" here means **gross expectancy is
  positive (~+0.06R/trade) while the bracket is fair** — the entry really does carry
  information. What it does not carry is *consistency*. And the prop rules agree:
  **+34.68R on the single best day is 55.5% of total profit against a 20% cap**, so
  even if the total were real, the evaluation would fail on Best Day.

A caveat I will not paper over: **p = 0.016 is resolution-limited** — with 60
replications the smallest attainable p-value is 1/61 ≈ 0.016, and the top two null
values are identical (+55.12R), so this is the floor of the test rather than a
measured tail. A 300-replication run is needed to place it properly. The direction of
the result is unlikely to flip (the strategy total is +62.47R against a null median of
−73.54R), but the number should not be quoted as precise.

---

## 5. What this changes about the plan

Armed: **nothing.** Four criteria fail and the prop Best Day rule breaks.

The next iteration is not "try more entries". It is a specific, falsifiable target:
**gate on regime.** Everything measured here says the same thing —

- the bracket is fair (E_dir ≈ 0.0000) and cheap (0.02–0.03R) on a wide stop,
- entry timing has positive gross expectancy that beats a real null,
- the losses are concentrated in identifiable-looking *runs* of folds,

so the missing piece is a causal regime filter, and the harness can now test one
honestly: pre-register the regime definition, keep the 48-config grid fixed, keep the
40-day holdout shut, and require the **same** V1–V6 criteria plus a Best Day check.
Candidates worth declaring in advance: trend efficiency (Kaufman efficiency ratio),
ADX, realised-vs-implied style vol ratios, and the sign-consistency of H4 returns.
Each must be selected on fold k and scored on k+1 only.

---

## 6. Artifacts

| what | where |
|---|---|
| geometry study (Phase 1) | `scripts/gold_geometry_study.py` → `artifacts/gold_geometry_study.json` |
| walk-forward v2 | `scripts/gold_wfo_v2.py` → `artifacts/gold_wfo_v2.json` |
| v1 (unchanged, and its null is superseded by §2) | `scripts/gold_walkforward.py`, `docs/GOLD_WFO_VERDICT_20260919.md` |
| tests | `tests/test_gold_geometry_study.py` (imports the v2 harness) and `tests/test_best_day_cap.py` — the latter pins the harness's published numbers (2,267 trades, +62.47R, t +0.70) against `artifacts/gold_wfo_v2.json`, so a refactor that moves a number fails loudly. **Corrected 2026-09-19:** this cell previously cited `tests/test_gold_wfo_v2.py`, which has never existed. |

Nothing is armed, nothing is deployed, and the EA is not built on this configuration.
