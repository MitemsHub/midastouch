# CONTROLLING FOR THE SESSION GATE (pre-registered 2026-09-21)

**Question:** the live arm refuses entries outside 06–20 UTC, and that gate discards 41% of the
EA rule's signals (151 of 368 on the venue's 174 days). Measured per UTC hour, do the discarded
hours carry the same per-trade edge as the kept ones, or only more trades?

**Status: PRE-REGISTERED, THEN RUN.** Grid, rule, engine, clock and decision rule are fixed
below before the first number. Result: `artifacts/gold_session_hours_ea.json`, recorded in
`docs/GOLD_SESSION_HOURS_EA_VERDICT_20260921.md`.

---

## 1. Structure

- **Rule and engine:** the same declared cell as the EA walk-forward — `ORIGINAL`, stop
  2.0×ATR(H1), target 2.0R, `scripts/midas_sweep.py:run_mode` (the parity engine of record).
- **The session gate is REMOVED** (`win_lo=0, win_hi=24`) for this study only. Measuring what a
  gate discards requires running with it off; the live arm keeps it, and no result here changes
  a preset. Cost model, min-lot floor and amendment-6 veto are unchanged.
- **Window:** the venue's served window in the same two clock eras the EA walk-forward used
  (A: 2026-01-12→03-31 at +60 min; B: 2026-04-01→09-18 at +120 min), pooled. Bars are stamped
  by their own era's pin; the hour of a trade is the UTC hour of its signal bar.
- **Sizing:** $25,000 basis at 0.25% (the arm's own armed size). R is stop-normalised.

## 2. The required sample, computed BEFORE the run

A per-hour bucket is a t-test on that hour's trades. At the declared effect size — **+0.10R per
trade**, rounded *up* from the walk-forward's own pooled +0.20R/trade so the requirement cannot
be flattered — against the measured dispersion of this rule (sd ≈ 3.31R, the same figure the
frozen study reports):

| requirement | trades | in-session days at ~0.75 trades/day |
|---|---|---|
| `t >= 1.96` at +0.10R | **≈ 4,210** | ≈ 5,600 days ≈ 15 years |
| 80% power at +0.10R | ≈ 8,570 | ≈ 11,400 days ≈ 31 years |

**So the declaration is that this study is UNDERPOWERED BY CONSTRUCTION, and that is the
result to report if it comes out that way.** Eight months of one instrument cannot decide an
hour bucket's edge at this effect size, and a study that reported a per-hour winner from 8
months without this arithmetic would be reporting noise. The per-hour table below is therefore
**descriptive**, and the only comparison that even approaches decidability is the *pooled*
outside-window bucket (~150 trades against ~220 kept) — still well short of 4,210.

## 3. Decision rule, declared now

- **Futility first.** If `n < 4,210` in a bucket, that bucket is reported as **NOT EVALUABLE**
  and no claim is made about it, positive or negative — including the "discarded hours are
  worse" claim the current gate implicitly makes.
- **The pooled comparison** (outside 06–20 vs inside) is reported as a difference of means with
  its t, and is **NOT a pass/fail gate**: it selects no configuration and changes no preset.
- **Pre-declared expectation: UNDERPOWERED.** The honest reading of the pre-existing evidence
  is that the shipped gate was chosen by a pre-registered study of the same window and should
  not be re-opened by a second look at it; a change to the session window would require a
  *forward* test at the sample above, not this table.
- **What would make the hour question decidable:** years of forward record at this flow, or an
  effect size ≥ 0.5R/trade, which this rule has never shown on any window.

## 4. Reproducing

```bash
python scripts/gold_session_hours_ea.py --write
python scripts/gold_session_hours_ea.py --selftest   # required-sample arithmetic, era split
```
