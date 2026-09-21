# What the exits give back, and whether filtering the losing states saves the rules

**Date:** 2026-09-21 · **Harnesses:** `scripts/gold_exit_capture.py` (new),
`scripts/gold_governed_wfo.py --exclude-lowvol` (extended)
**Artifacts:** `artifacts/gold_exit_capture.json`, `artifacts/gold_governed_wfo_lowvol.json`
**Window:** the venue's served history, 2026-01-12 .. 2026-09-21 (16,284 M15 bars).
**Status:** every number here is exploration on the window the gate is judged on.

---

## 1. The market offers roughly a ±1R range after the signal, and the exits keep 2.6% of it

Excursion after each of 906 signal entries, in R (risk = 1.0 × ATR at the entry bar), the
same entries the exit study then re-prices:

| horizon | MFE | MAE | t(MFE) |
|---|---|---|---|
| 4 bars (1h) | 0.709R | −0.738R | +22.1 |
| 8 bars (2h) | **1.127R** | −1.092R | +24.2 |
| 16 bars (4h) | 1.715R | −1.672R | +25.7 |
| 32 bars (8h) | 2.516R | −2.329R | +26.7 |
| 48 bars (12h) | 3.141R | −2.700R | +26.1 |

The distribution is almost symmetric: the average signal bar is followed by **at least** a
1.1R favourable move and a 1.1R adverse one within two hours. The +0.113 ATR drift measured
in the trigger study is a *tilt* on a wide two-sided range, not a directional gift. That is
the whole reason the exits dominate the outcome — and it explains why every entry-side
filter this program has tried moved the average by hundredths of an R.

## 2. The certified exit is the worst of the policies tested

Same 912 entries, only the exit varies, costs included (spread 1.073 bps + $10/lot RT):

| policy | mean net R | t | total | capture of the 8-bar MFE |
|---|---|---|---|---|
| **stop 1.0R, no target** | **+0.3221** | **+3.06** | +293.8R | **28.6%** |
| stop 1.0R + trail (act 0.5R, dist 0.5R) | +0.1687 | +2.10 | +153.9R | 15.0% |
| stop 1.0R + trail (act 1.0R, dist 0.5R) | +0.1677 | +2.05 | +152.9R | 14.9% |
| stop 1.0R + trail (act 1.0R, dist 1.0R) | +0.1562 | +1.83 | +142.4R | 13.9% |
| stop 1.0R + target 6.0R | +0.1804 | +2.24 | +164.6R | 16.0% |
| stop 1.0R + time exit 16 bars | +0.0767 | +1.11 | +70.0R | 6.8% |
| **stop 1.0R + target 3.0R (the certified pair)** | **+0.0294** | +0.52 | +26.8R | **2.6%** |
| stop 1.0R + target 2.0R | −0.0315 | −0.69 | −28.8R | −2.8% |
| stop 1.0R + target 1.0R | −0.0660 | −2.02 | −60.2R | −5.9% |

The ordering is monotone in the target: **every target below 2.5R loses money, and the
smaller the target the worse it is.** Capping the upside with a 1R stop is the worst of both
worlds — it takes the full -1R when the bar goes against, and refuses the +1.1R when it goes
with. The certified 3.0R target captures 2.6% of the available 8-bar excursion; removing the
target captures 28.6%.

**Caveats, before this is read as a fix.** (1) "No target" holds to the 48-bar/22:00 flat
rule, so trades live up to 12 hours and the exposure profile is not the certified one.
(2) 13 policies were compared and this is the best of them on one window — the selection
effect is real and unpriced. (3) The +3.06 t-statistic is on 912 trades, which *is* enough
sample, which is exactly why it must be re-measured out of sample rather than adopted. What
is established here is narrower and safer: **the exit, not the trigger, is where this
strategy's upside is being given back**, and the certified target is the specific component
costing the most.

## 3. Filtering the low-volatility states halves the loss and does not save the rules

`--exclude-lowvol` suppresses signals whose H1 ATR is below 0.8 × its trailing median — the
−0.3522R/trade cell from the trigger study — **in-engine**, through a new optional
`signal_mask` on `gold_walkforward.simulate` (`None` by default, so the frozen path is
byte-identical; the frozen artifact's checks are the proof). Filtering the finished trade
list instead would have freed the suppressed signal's slot and reported a sequence the EA
could not trade.

| | certified grid | **+ low-vol filter** |
|---|---|---|
| OOS trades | 270 | 254 |
| total | −30.35R | **−15.37R** |
| fold-mean t | −1.32 | **−0.75** |
| random-entry control | −60.98R | −71.25R |
| V1/V2/V3/V5/V6 | 5 fail | **5 fail** |
| final equity | $17,411.91 | $21,157.09 |
| worst day | −3.23R (−$806) | −3.23R (−$806) |
| shield / daily breaches | 5 / 5 | **5 / 5** |

**The answer to the question asked is no.** Filtering removes almost half the loss (−15.37R
vs −30.35R, and the fold t improves from −1.32 to −0.75) but the breach counts are identical
and — this is the informative part — **the daily-breach dates are the same five days**
(2026-01-29, 02-13, 02-17, 03-09, 04-07). The days that breach the 3% rule are not low-
volatility days; their damage comes from trades taken in ordinary or high volatility, which
the filter keeps. So the daily cap is not a state-selection problem, and §2's exit finding is
the only lever this study leaves standing for it.

## 4. The three results together

1. **Entry side:** the trigger carries a real but small tilt (+0.113 ATR at 2h, t=3.5) on a
   wide two-sided excursion (±1.1R). Filters over it move the mean by hundredths of an R.
   The one pre-registered candidate derived from it (`docs/GOLD_PREREG_LATE_SHORT_20260921.md`)
   came in at +0.0963R over 120 trades, t=+0.70, with four fifths of the total in the first
   half — INSUFFICIENT EVIDENCE, and it decays.
2. **Exit side:** the certified target is the single most costly component measured so far;
   removing it is worth ~0.29R/trade on this window (+0.0294 → +0.3221), and trailing exits
   recover about half of that (+0.17R). This is the first exit-side measurement in the
   program and it identifies a specific, testable change.
3. **Rules:** neither governor policy (entry-only or path) nor the low-volatility filter
   stops the venue's 3% and 6% rules from being breached. The declared late-session short
   rule removes the shield breaches entirely (0 vs 5) while leaving daily breaches (3), which
   locates the daily problem outside regime selection.

**The live arm is unchanged.** It runs the certified exit (target 2.0R per its preset) with
the entry-only governor, under an operator override, and nothing in this document alters
`artifacts/live/armed.json` or the recommendation in `docs/GOLD_ARMING_DECISION_20260921.md`.
