# GOLD WFO — VERDICT FOR THE EA'S OWN ENTRY RULE — 2026-09-21

**Verdict: NOT VALIDATED.** Recorded as frozen evidence. The protocol
(`docs/GOLD_WFO_EA_PROTOCOL.md`, sha256 in the artifact) is unchanged by this result, and the
result was computed in one run after the protocol was written.

Artifact: `artifacts/gold_wfo_ea.json` · Harness: `scripts/gold_wfo_ea.py` ·
Engine: `scripts/midas_sweep.py:run_mode` (the parity engine of record — the rule certified
here is the rule parity compares against the EA, not a re-implementation of it).

| item | value |
|---|---|
| rule | M15 BB(20, 2.0) touch-back-inside or RSI(14) 70/30, H1 EMA20 + H4 EMA20 regime |
| window | the venue's served window in **two clock eras**: A 2026-01-12→03-31 at +60, B 2026-04-01→09-18 at +120 |
| bars | 5,069 (A) + 11,156 (B) = 16,225 M15 bars |
| grid | 144 configurations: 8 modes × 3 stops × 3 targets × 2 session windows (all live inputs) |
| structure | 9 + 21 = **30 folds** of 8 days; no fold crosses an era boundary |
| sizing | $25,000 basis at 0.25% (the arm's own armed size) |
| control | 200 seeded random-entry repetitions per era, same engine/geometry/window/costs |

---

## 1. The result

**Declared cell** — the arm's own configuration (`ORIGINAL`, stop 2.0×ATR, target 2.0R,
06–20 UTC), reported with **no selection at all**, so there is no search to inflate it:

```
30 folds   total +12.819R   mean /fold +0.427R   fold-mean t = +1.07   (needs >= 1.96)
V1 total>0            PASS
V2 pos>=60%           PASS   (18/30 folds positive)
V3 worst>-3           FAIL
V4 beats control      PASS   (+12.819R vs +0.74R)
V5 median>0           PASS
V6 t>=1.5             FAIL   (+1.07)
V7 t>threshold        FAIL   (needs >= 1.96)
```

**Selected path** — the same procedure the frozen protocol uses (win on fold *k*, score on
fold *k+1* only), over the 144-wide grid:

```
29 OOS folds   total +39.584R   fold-mean t = +2.00   median +0.483R   16/29 folds positive
V1 PASS   V2 FAIL (16/29 = 55%, needs 60%)   V3 FAIL (worst fold < -3R)
V4 PASS (vs control -2.97R)   V5 PASS   V6 PASS (t +2.00 >= 1.5)
V7 FAIL (t +2.00 < 3.573, the 95% family-wise threshold at 144 trials)
PBO (CSCV over 30 windows) = 0.186 over 70 combinations
distinct picks = 23 of 29 folds
```

Two readings of the same bars, and the gap between them is the point: the selected path
looks stronger (`t = +2.00`, which clears the old 1.5 bar) **only because 144 configurations
were searched** — V7 exists to price that search, and at 144 trials the threshold is 3.573.
Once the search is priced, the result is indistinguishable from noise. Independently, PBO
0.186 says the *procedure* is not the main problem; V2/V3 say the *strategy* is: more than a
fifth of folds are negative and one fold is worse than -3R, while **23 of 29 selections
changed their mind** — a rule whose chosen configuration never settles.

## 2. Cross-check against the arming record — one row reproduces, one does not

The arming record (`artifacts/live/armed.json`) already quoted this rule in `ORIGINAL` mode on
two windows. Re-run through the engine of record at the armed parameters:

| window | arming record | this harness, just measured | |
|---|---|---|---|
| wfv 2026-01-12→03-31 | n=42, +9.810R, mean +0.2336 | **n=42, +9.810R, mean +0.2336** | reproduces exactly |
| oosc 2026-04-01→09-16 | n=96, +6.044R, mean +0.0630, t 0.57 | **n=94, +1.957R, mean +0.0208, t +0.19** | **does not reproduce** |

The oosc row was probed before reporting it as a discrepancy: neither the risk fraction
(0.25% / 0.50% / 1.00% give *identical* R, as designed — R is stop-normalised, so size only
enters through the min-lot floor) nor **any** geometry in the armed family's own space
(stop 1.0/1.5/2.0 × target 1.5/2.0/3.0 × both windows = 18 combinations, none giving n=96)
reproduces it. So one of the record's two rows is not a measurement the current corpus and
engine produce. It is recorded here as an **open discrepancy**, not smoothed over: the
reproducible number for that window is the weaker one, and the record's power statement
("~208 forward trades at +0.1149R/trade") rests partly on the row that does not check out.

## 3. What this does and does not change

- **The gate this arm is armed behind still describes a different strategy.** That is now
  measured rather than asserted, and this harness is the missing walk-forward for the rule
  that trades. Its verdict is NOT VALIDATED — the same verdict, for a different and now
  proper reason.
- **Nothing about the live arm changes.** It runs on your operator override
  (`armed.json`), which says in its own words that it is not a validation. A verdict here
  cannot arm anything: arming is an arming-record event.
- **The rule is not dead, and it is not validated.** The honest summary is the declared
  cell's number: **+0.427R per 8-day fold, t = +1.07 over 30 folds**, against a required
  1.96 — positive, underpowered, and no longer explainable as "we measured the wrong family".

## 4. The one thing that would move it

A pre-registered **forward** test, not another look at these bars. The window has now been
looked at three times (parity, the arming record, this protocol), and each look is weaker
evidence than the last. What would count:

- the arm's forward paper record reaching the declared sample at this effect size, scored by
  the fold/t criteria frozen in the protocol; or
- a venue window that has not been examined yet (a new instrument, or the same instrument on
  bars the venue serves after 2026-09-18), pre-registered before it is looked at.

Both are recorded in `artifacts/live/armed.json` as the conditions that retire the override.
