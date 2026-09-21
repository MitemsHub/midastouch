# GOLD COST-SENSITIVITY — PRE-REGISTRATION (frozen before the run)

**Date:** 2026-09-20 · **Status:** FROZEN — nothing below §3 may be edited after the run
**Script:** `scripts/gold_cost_sensitivity.py` · **Artifact:** `artifacts/gold_cost_sensitivity.json`

---

## 1. Why this exists, and why it is pre-registered

Every gold verdict on record rests on one unmeasured number: the modelled round-trip
spread of **1.073 bps** (`SPREAD_BPS` in `scripts/gold_walkforward.py`, with commission
at `$10/lot` round-turn). It has never been measured live, because this repo sends no
orders and the measurement needs a fill.

The reason this is not a formality: **DAILY-ONE fails V4 (beats the matched null) by
0.19R** at 200 replications — `+12.83R` actual against a null p95 of `+13.02R`. A cost
error of a fraction of a bar is larger than that margin. So the question "how wrong can
the cost model be before a verdict changes" is not a sensitivity nicety; for DAILY-ONE
it is the difference between a number that means something and one that does not.

The pre-registration exists because the temptation afterwards is obvious: measure the
live spread, find it worse than modelled, and then *decide* it does not matter. The
decision rule and the sweep grid are therefore fixed here, before any number exists.

## 2. What is swept, and what is held

**Swept:** the spread, as a multiplier `m` of the model, `m ∈ {0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0}`.

- `m = 0.0` is not idle curiosity. It answers "does the entry rule have a gross edge at
  all?" If the strategy only clears zero cost by a hair, then cost is the entire result
  and no honest measurement of it can rescue a verdict.
- `m = 1.0` is the model as published, and is the fidelity control.

**Held fixed:** commission at `$10/lot` round-turn (the venue's published metals
schedule — it is a schedule, not a measurement, so there is nothing to sweep), the
frozen DAILY-ONE grid (`stop_mult ∈ {2.0, 3.0} × rr ∈ {1.5, 2.5}`, 4 configs), the frozen
entry rule (one entry per UTC day at 08:00, direction from the H4 regime bit), the fold
structure, the holdout, and `NULL_SEED = 20260919`.

**Null:** the matched null (same cadence, direction from a coin) is **re-run at every cost
level**, not reused. V4 compares the actual total to the null's p95, and the null's own
total also shrinks as cost rises; reusing the `m = 1.0` null would measure the wrong
thing. **200 replications**, taken in generation order (the ordering bug that printed an
impossible `max < p95` is fixed and must not regress).

## 3. Decision rule (fixed now)

1. **Fidelity.** `m = 1.0` must reproduce the published DAILY-ONE numbers
   `+12.83R / 119 trades / t +1.33 / null p95 +13.02R / 14 of 21 positive folds`.
   If it does not, the corpus of gold verdicts is not comparable and the run is void.
2. **Break-even spread.** Report the largest `m` at which total OOS R is still `> 0`,
   converted to bps. This is the headline number: *the spread at which the edge is fully
   consumed.*
3. **Per-leg flip points.** For each of the 8 gate legs, report the largest `m` at which
   it still passes. A leg that survives `m = 3.0` is robust to a 3× cost-model error; a
   leg that fails at `m = 1.5` is a leg whose PASS is a statement about the cost model,
   not about the strategy.
4. **Applied to the live measurement.** `scripts/measure_live_costs.py` samples the
   live spread. Its output is divided by `1.073` to yield the measured `m`. The
   pre-registered reading is then mechanical:
   - measured `m ≤ 1.0` → the model is **not optimistic**; every verdict on record stands
     with its stated margin.
   - `1.0 < measured m ≤` the robustness bound → the model is optimistic, the verdicts
     stand **only** if they are among the legs that survive that `m`, and every
     non-surviving verdict must be recorded as cost-fragile.
   - measured `m >` break-even → DAILY-ONE's edge does not exist in live conditions and
     the verdict is **RETRACTED**, not merely downgraded.

**No leg may be re-scored after the live number arrives.** The live spread is an input to
this table, not a licence to revisit it.

## 4. Known limitation, stated up front

The sweep scales the spread *proportionally for all trades*. Real cost is not
proportional: it varies with session liquidity, and a wide-spread regime also tends to be
a high-volatility regime, where this strategy's stops are widest and its cost in R is
therefore smallest. So the true live cost in R may be *less* adverse than a proportional
`m` implies. That cuts in the strategy's favour and I am flagging it rather than using it
— the proportional sweep is the conservative reading, and the conservative reading is the
one that should set the verdict.

---

## 5. RESULT

**Run:** 2026-09-20 17:5x UTC · `scripts/gold_cost_sensitivity.py` ·
`artifacts/gold_cost_sensitivity.json` · 200 reps per level, same seed at every level.
*nothing above §5 was edited after the run.*

### 5a. Fidelity: PASS

`m = 1.0` reproduced `+12.83R / 119 trades / t +1.33 / null p95 +13.02R / 14 of 21
positive folds` exactly. The corpus of gold verdicts is comparable and the run stands.

```
    m     bps    totalR       t   pos   v4marg  bestday    size$  legs
  0.0   0.000    +13.40   +1.32 14/21    -2.04     9.3%   250.28  6/8
  0.5   0.536    +14.12   +1.46 14/21    -0.11     8.8%   241.86  6/8
  1.0   1.073    +12.83   +1.33 14/21    -0.19     9.6%   233.99  6/8
  1.5   1.609    +11.53   +1.20 14/21    -0.28    10.6%   226.62  6/8
  2.0   2.146    +10.24   +1.07 14/21    -0.36    11.9%   219.70  6/8
  3.0   3.219     +7.66   +0.80 14/21    -0.53    15.7%   207.05  6/8
  5.0   5.365     +2.49   +0.26 11/21    -1.10    47.2%     0.00  3/8
 10.0  10.730    -10.42   -1.13  8/21    -2.28      n/a     0.00  0/8
```

### 5b. BREAK-EVEN: 6.40 bps — the model could be 6x wrong before the edge dies

The edge is fully consumed at **`m = 5.965` → 6.40 bps**.

For scale, using the one live figure available (the readiness gate's weekend quote of
**60 points**, and `XAUUSD` really is 2 digits, so 60 points = **$0.60** — verified against
`symbol_info`, not assumed): at the live bid of **$4,377.66** that is **1.37 bps**, i.e.
**`m ≈ 1.28`** — the model *is* mildly optimistic on that quote. But a weekend quote is
wider than an in-session one, so the true session value should be at or below it, and
**at `m = 1.28` the pass set is identical to `m = 1.0` (6/8)**. Even taken at face value
and out of session, the model's error is about a quarter — a fifth of the way to
break-even, and irrelevant to V4 and V6, which fail at `m = 0`.

### 5c. THE DECISIVE FINDING: cost is not what fails DAILY-ONE

**V4 (beats the matched null) and V6 (t ≥ 1.5) FAIL AT EVERY LEVEL, INCLUDING `m = 0`.**

At `m = 0` — no spread, no commission, free trading — the arm still returns `+13.40R`
against a null p95 of `+15.44R`, and `t = +1.32`. The failures therefore cannot be
rescued, or caused, by any measurement of the live spread: **the matched-null failure is
noise, not cost.**

It is worse than "the null wins by a hair": the best t-statistic anywhere on the entire
cost curve, free trading included, is **+1.46** (at `m = 0.5`), against a 1.5 bar. There
is no cost assumption under which DAILY-ONE clears V6.

Per-leg robustness (largest `m` at which the leg passes):

| leg | survives to | reading |
|---|---|---|
| V1 total > 0 | m ≤ 5.0 | cost-robust; fails only near break-even |
| V2 pos folds ≥ 60% | m ≤ 3.0 | cost-bounded; a 3× model error would flip it |
| V3 worst fold > −3R | m ≤ 5.0 | cost-robust |
| V4 beats null p95 | **never (fails at m = 0)** | **not cost-dependent at all** |
| V5 median > 0 | m ≤ 5.0 | cost-robust |
| V6 t ≥ 1.5 | **never (best t = 1.46)** | **not cost-dependent at all** |
| V7 best-day ≤ 20% | m ≤ 3.0 | degrades as cost rises (9.6% → 47.2%) |
| V8 legal size exists | m ≤ 3.0 | size falls $234 → $207 → $0 |

### 5d. Two honest caveats on my own table

1. **Total R is NOT monotone in cost.** `m = 0.5` (+14.12R) beats `m = 0.0` (+13.40R),
   because the walk-forward *re-selects* a config at each cost level — selection is itself
   cost-dependent. So the break-even above is a local statement under an assumed single
   sign change, supported by the data (positive through `m = 5.0`, negative at `m = 10.0`)
   but not proven. The `m = 0.5` wiggle is ~0.7R and does not approach the 6× mark.
2. **The null's p95 moves between draws.** DAILY-ONE's null p95 is `+13.02R` here and
   `+15.92R` for the same arm in the DAILY-SEQ probe (different coin stream). Both exceed
   the actual `+12.83R`, so the verdict is stable — but a p95 that ranges over ~3R is a
   fat-tailed bar, and no gold verdict should be decided by a margin smaller than that.
   This strengthens the case for reporting V4 as "does not beat its null" rather than as
   the 0.19R near-miss it looked like.

### 5e. DAILY-SEQ: the failure is cost-independent too

`scripts/gold_seq_cost_probe.py` (diagnostic only — it re-scores nothing; DAILY-SEQ's
frozen 3/8 verdict stands as recorded) ran the DAILY-SEQ pipeline at `m = 0` and `m = 1`,
null 200 reps per level:

```
brake=0: +13.40R at m=0 -> +12.83R at m=1   cost-INDEPENDENT: still fails free
brake=1:  +3.44R at m=0 ->  +4.13R at m=1   cost-INDEPENDENT: still fails free
brake=2:  -1.11R at m=0 ->  -2.74R at m=1   cost-INDEPENDENT: still fails free
```

Every arm fails to beat its matched null even with the spread switched off entirely, and
the brake's collapse of the survivable size to `$0.00` is present at `m = 0` as well. So
the sequence-aware design did not fail because gold is expensive to trade; it failed for
the structural reason already recorded (a brake is reactive — it cannot prevent drawdown
it acts after, and it re-clusters the winners into fewer days, breaking V7 in the act of
trying to satisfy V8).

### 5f. What the live measurement can still change

**Nothing about DAILY-ONE or DAILY-SEQ.** Both fail at every cost including zero. The
live spread, when Sunday's session provides it, is now a **monitoring** number for the
paper run — it can only re-rank the legs in §5c, and the two legs that decide the verdict
are not on the cost axis at all.

The measurement still matters for one thing: **V2, V7 and V8 pass at 3× the model but
fail at 5×** — their exact flip lies in that interval and was not bisected (only the
break-even sign was, per §3.2). So a live spread more than three times 1.073 bps
(≈3.2 bps) would be a finding about the cost model that must be recorded and fed back
into every future gold study — even though it cannot change this verdict.

*Market state at the time of this run: closed, next open 2026-09-20 22:00 UTC (4.1h
away). `measure_live_costs.py` refuses while closed by design; the supervisor samples
once per session day and will take the first reading at the open.*
