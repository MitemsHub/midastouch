# Pre-registration: the DAILY-ONE gold signal (frozen before the run)

**Frozen:** 2026-09-19, before any run of `scripts/gold_daily_one.py` existed or any
result for this signal was computed. Everything below is a commitment, not a summary.

**Why this signal, stated as a hypothesis and not as a hope.** The walk-forward v2 signal
did not merely fail to validate (t = +0.70). `docs/GOLD_BEST_DAY_STUDY_20260919.md`
established something more specific: its profit is **day-level aggregated**
(`corr(trades/day, day R) = +0.538`, ~20 trades/day), the venue's 20% Best Day cap cannot
be satisfied at *any* position size because the share is scale-invariant, and every cap
that fixes the concentration destroys the edge. So the failure was structural, not
marginal, and the natural response is a signal **whose profit is spread across days by
construction** rather than one that has to be capped into compliance afterwards.

---

## 1. The signal, completely specified

| element | specification |
|---|---|
| instrument | XAUUSD |
| execution timeframe | M15 |
| regime permission | **H4 only**: `h4_close > h4_ema20` -> long permitted; `<` -> short permitted. One input, deliberately. The v2 signal's H1 EMA stack is dropped because it added a parameter without ever being shown to detect regime. |
| cadence | **at most ONE entry per UTC day**, at the first M15 bar at or after **08:00 UTC** |
| direction | the H4 permission at that bar (long if above, short if below). If the regime permits neither, no trade that day. |
| stop | `stop_mult x ATR14(M15)` at the entry bar |
| target | `rr x ATR14(M15)` from the entry |
| exit | target, stop, or the existing session flatten at 22:00 UTC — the same `_exit_fill` semantics as v2, unchanged |
| positions | one at a time |
| grid | **4 configurations**: `stop_mult in {2.0, 3.0}` x `rr in {1.5, 2.5}` |

**Why the cadence is the whole point.** One entry per day caps the number of trades at
~1/day by construction. That is what makes the Best Day share a function of *outcomes*
rather than of a cap, and it is why the concentration criterion below can be a
pre-registered pass/fail rather than a post-hoc repair.

**Why the stop range is 2.0-3.0 ATR.** `scripts/gold_geometry_study.py` measured the
same-bar tie assumption at a 1-ATR stop to be worth +/-0.009R and the round-trip toll at
0.0588R — 2.3x the 0.0247R the project had been quoting — because that figure assumed a
~$23 stop while a 1-ATR M15 gold stop is $9.89. At 2.0-3.0 ATR the assumption band
collapses and the toll falls to 0.0196-0.0294R. **The grid searches where the measurement
is trustworthy**, and never below 1.5 ATR.

## 2. Data and folds

* Window: XAUUSD M15, 16,224 bars, 2026-01-12 -> 2026-09-18, loaded by
  `scripts/mt5_data.py` through `scripts/gold_wfo_v2.prepare()` — the same preparation the
  v2 run used, so the two are comparable.
* Folds: the same 8-day folds, **21 selection/evaluation pairs**.
* Holdout: the **last 40 days are never used for selection or scoring** and are not
  touched by this run.

## 3. Selection rule

Identical to the frozen v2 procedure: on each fold, pick the configuration with the best
total training R, then score that pick **only** on the following fold. Deterministic
tie-breaks by `-stop_mult`, `-rr`, then index. A pick is carried forward while its training
R is non-zero. No peeking, no re-selection on the evaluation fold.

## 4. Pass criteria — the frozen gate, plus one addition

From `docs/GOLD_WFO_PROTOCOL.md` §6, unchanged:

| leg | criterion |
|---|---|
| V1 | out-of-sample total > 0 |
| V2 | >= 60% of folds positive |
| V3 | worst fold > -3R |
| V4 | beats the matched null (below) |
| V5 | median fold R > 0 |
| V6 | t-statistic of fold means >= 1.5 |

**Plus a criterion this program has now earned the right to demand — pre-registered here
and not applied afterwards:**

| leg | criterion |
|---|---|
| **V7** | **Best Day share <= 20%**: the best single trading day's profit is at most 20% of the window's total profit |
| **V8** | **implementable at a legal size**: a risk per trade exists such that the profit target is met with **zero** daily-loss-limit and zero shield breaches |

V7 and V8 exist because `GOLD_BEST_DAY_STUDY_20260919.md` showed that compliance cannot be
retrofitted by sizing (scale-invariant) or by capping (destroys the edge). A strategy that
cannot pass them is not tradeable on this account regardless of how good its t-statistic
is, so leaving them out of the gate would be pre-registering the wrong question.

## 5. The null (matched, and specified in advance)

Same cadence, same grid, same selection procedure, same folds — but the **direction** at
each entry bar is drawn by a seeded RNG (`NULL_SEED = 20260919`) instead of read from the
H4 regime. 32 replications. The bar is the **95th percentile** of the resulting OOS totals.

This is a *selection-adjusted* null: it answers "could picking the best of these 4
configurations on noise have produced this total?". It is **not** White's Reality Check and
does not claim to be.

## 6. Honest statement of what would make this protocol weak

* **4 configurations is small, and that is deliberate** — multiplicity is the reason v1's
  "+0.19R of alpha" evaporated. But a small grid also means a single lucky configuration
  can carry the result, which V2 (60% of folds positive) and the fold-level t are the
  guards against.
* **Between-day independence is assumed by V7, not tested.** The Best Day share treats days
  as the unit; if day outcomes are strongly autocorrelated the share is still the rule's
  own definition, but its sampling error is not characterised here.
* **The data's venue provenance is not audited in this protocol.** If the M15 series did
  not come from Upcomers, the cost model and the session structure are being validated
  against another venue's book. Flagged as an open item in
  `docs/REPO_IDENTITY_AND_CROSS_REPO_STATUS_20260919.md` §4 rule 6.
* **A pass here would earn a validation RECORD, not a live arm.** Arming additionally
  requires an operator arming file naming the same `config_id` and a fresh artifact hash;
  see `docs/PROP_EXECUTION_LAYER.md`.

---

## 7. RESULT — NOT VALIDATED (6 of 8 legs)

**Run:** `scripts/gold_daily_one.py` · **artifact:** `artifacts/gold_daily_one.json`
Nothing above this line was edited after the run began.

```
OUT OF SAMPLE (21 folds)
  total +12.83R over 119 trades (+0.1078R/trade)
  t-stat +1.33   positive folds 14/21   median +0.54R   worst -2.46R
  days traded 119   best day +1.23R of +12.83R -> share 9.6% (V7 cap 20%)

MATCHED NULL (32 reps, same cadence, random direction)
  median -1.70R   p95 +12.33R   max +24.16R

V1 total>0 PASS   V2 pos>=60% PASS   V3 worst>-3 PASS   V4 beats null p95 FAIL
V5 median>0 PASS  V6 t>=1.5 FAIL     V7 best-day<=20% PASS  V8 legal size PASS

Null stability, raised to 200 replications (scripts/gold_daily_one_ablation.py):
   32 reps: p95 +19.82R  max +24.16R  median -1.70R  -> actual clears by -6.99R
   64 reps: p95 +12.33R               median -1.35R  -> +0.49R
  128 reps: p95 +12.33R               median -3.94R  -> +0.49R
  200 reps: p95 +13.02R  max +24.16R  median -2.90R  -> -0.19R

Direction ablation:  h4 (frozen) +12.83R | always long -8.34R | always short
+1.18R | h4 inverted +1.13R
```

### The hypothesis was right about BOTH mechanisms

**The H4 regime bit is load-bearing.** This was the component most likely to be a proxy
for gold simply rising, and it is not — gold did *not* rise in this window:

| direction source | total R | R/trade | t |
|---|---|---|---|
| H4 regime (frozen) | **+12.83** | +0.1078 | +1.33 |
| always long | **−8.34** | −0.0701 | −0.87 |
| always short | +1.18 | +0.0099 | +0.13 |
| H4 inverted | +1.13 | +0.0095 | +0.12 |

Always-long *loses* money and inverting the regime destroys the result, so the single
comparison `h4_close > h4_ema20` is doing real work — it is the one component of this
signal shown to carry information. That is a genuinely positive finding and it narrows
where to look next.

**V7 passes at 9.6%** against a 20% cap, on 119 trading days with the best day worth
+1.23R of a +12.83R total. Compare v2, where the best day was **55.5%** and no position
size could move it. The one-entry-per-day cadence did exactly what it was designed to do:
concentration is now a property of the *outcomes* rather than something a cap has to
enforce, and the cap has 10 points of headroom instead of being breached by 35.

That is the real finding here, and it is transferable: **day-level concentration is a
cadence problem before it is a risk problem.** For this account, a signal that decides
often cannot be fixed afterwards.

### Why it still fails

**V6 (t = +1.33 against a required 1.5).** It misses, and it misses in the direction that
matters: +0.1078R per trade over 119 trades is a small edge measured over 21 folds, and
the fold-level dispersion is what puts the t below the bar.

**V4 FAILS once the replications are adequate, and the original PASS was an artifact of
its own sample size.** At 200 replications the null's 95th percentile is **+13.02R**
against the actual **+12.83R** — the signal does not beat its matched null. Two facts
about the 32-replication version of this test, both measured in
`scripts/gold_daily_one_ablation.py`:

* At 32 reps `0.95 x 32 = 30.4` lands *between two order statistics*, so "the p95" is
two different numbers depending on which neighbour is picked: **+12.33R** (the 30th
smallest) or **+19.82R** (the 31st). That 7.5R spread is larger than the margin the
run was reported to have cleared by. An under-resolved quantile cannot adjudicate a
result that sits inside the upper tail of its own null.
* The margin collapses monotonically as n grows: +0.49R at 64 and 128 reps, **-0.19R at
200**. The trend is the answer. It was reported as a PASS in good faith at the time,
and the protocol's own note (§6, "V4's 0.5R margin says the null needs more
replications") was the right instinct — the resolution is that it does not survive them.

**V8 PASSES, and it failed the first time because I implemented it wrong.** The protocol
states V8 as an *existence* claim — "a risk per trade exists such that..." — and the
first version tested only the **largest** size the single-day bound implied ($716.85,
which takes 5 shield breaches). Bisecting for the largest size that actually survives
finds **$233.99 per trade: target MET, 0 daily breaches, 0 shield breaches, final equity
$28,001.12**. A legal size does exist, so V8 passes.

The correction is worth more than the leg it fixed. **The single-day bound overstates the
survivable size by 3x**, and the gap is precisely the sequence constraint: a trailing
drawdown is a property of the *run* of days, not of any one of them. The measured shape of
that run, over 119 days:

| | |
|---|---|
| worst run of consecutive losing days | **5 days, −5.13R** |
| worst peak-to-trough | **6.41R** |
| profit at the worst peak | +0.82R |
| up days / down days | 69 / 50 |

The drawdown (6.41R) is **half the entire window's profit (12.83R)**. That is the number
that sets the legal size, and no single-day or Best Day bound can see it.

### What this changes

DAILY-ONE is plainly closer than v2 — six legs instead of four, t = +1.33 instead of
+0.70, and the concentration failure is genuinely solved rather than uncapped. It is still
**NOT VALIDATED**, no validation record is written, and the arming switch stays OFF.
Three directions follow from the numbers, and none of them is "tune the grid". The first
three items below were open questions when this section was first written; all three are
now answered by `scripts/gold_daily_one_ablation.py`, and two of the answers were negative:

1. **The shield, not Best Day, is the binding constraint** — CONFIRMED and quantified. The
   single-day bound permits $716.85 per trade; only **$233.99** survives. Further work
   should be pre-registered against the trailing-drawdown *sequence* (5 consecutive losing
   days, −5.13R; worst peak-to-trough 6.41R against a 12.83R total), which changes what a
   good signal needs to be: fewer consecutive losses, not fewer trades per day.
2. **V4 needed more replications** — ANSWERED, and it does not survive them. At 200 reps
   the actual (+12.83R) sits **below** the null's p95 (+13.02R). The PASS was an artifact
   of a 32-replication quantile that is itself ambiguous by 7.5R.
3. **Is the H4 bit doing the work?** — ANSWERED YES. Always-long *loses* 8.34R and
   inverting the regime reduces the result to noise, so the regime comparison carries real
   information. It is the only component of this signal so demonstrated, and it is where
   any continuation of this line should start.

The two negative answers do not cancel the positive one. What survives this run is a
**validated component** (the H4 regime bit), a **solved structural problem** (Best Day
compliance by cadence, 9.6% against a 20% cap), and one **newly identified binding
constraint** (the trailing shield). What does not survive is the *statistical* claim: a
t of +1.33 and a total that sits at, not above, its matched null.
