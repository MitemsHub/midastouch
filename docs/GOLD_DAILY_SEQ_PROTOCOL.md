# Pre-registration: DAILY-SEQ, the sequence-aware gold signal (frozen before the run)

**Frozen:** 2026-09-19, before `scripts/gold_daily_two.py` ran or any result for this
signal existed. Everything above §9 is a commitment.

**What this is built on, and what it is built against.** DAILY-ONE left three measured
facts (`docs/GOLD_DAILY_ONE_PROTOCOL.md`, `scripts/gold_daily_one_ablation.py`):

1. The **H4 regime bit is load-bearing** — always-long loses 8.34R where the regime
   direction makes 12.83R, and inverting it collapses the result to noise. This is the
   only component of the signal demonstrated to carry information, so it is the core.
2. The **trailing shield, not Best Day and not the daily limit, is the binding
   constraint on size** — the single-day bound allowed $716.85 per trade while only
   **$233.99** survived, and the cause is the *sequence*: a worst run of **5 consecutive
   losing days (−5.13R)** and a worst peak-to-trough of **6.41R against a 12.83R total**.
3. The drawdown is half the profit, so the account's own trail floor — not the strategy's
   expectancy — decides how much can be risked, which decides whether the dollar target
   is reachable at all.

Against those, the failure was statistical: **t = +1.33** against a required 1.5, and a
total that sits *at* its matched null (+12.83R vs a 200-rep p95 of +13.02R) rather than
above it.

**The hypothesis.** The losing runs are the mechanism behind both the drawdown and the
weak t-statistic: a run of losses both deepens the peak-to-trough and adds variance that
t scales against. If entries are suppressed for a short window after a losing day, then
(a) the worst run shortens, (b) the survivable size rises, and (c) t improves because the
fold-level dispersion falls. **This is a falsifiable claim about three specific numbers,
and if the brake does not move the drawdown it has failed regardless of what it does to
total R.**

---

## 1. The intervention, completely specified

The signal is DAILY-ONE — one entry per UTC day at the first M15 bar at or after **08:00
UTC**, direction from **H4 (`h4_close > h4_ema20` = long, `<` = short)**, stop
`stop_mult x ATR14(M15)`, target `rr x ATR14(M15)`, exit on target/stop/22:00 UTC
session flatten, one position at a time — **plus exactly one new rule**:

> **The consecutive-loss brake.** When a day closes at a loss, no entry is taken for the
> next **`brake` calendar days**. The day's result is known at its close, so the brake is
> causal: nothing is decided with information from the future.

## 2. The grid — 12 configurations: DAILY-ONE's geometry, crossed with the brake

| parameter | values | source |
|---|---|---|
| `stop_mult` | 2.0, 3.0 | frozen in DAILY-ONE (never below 1.5 ATR: the geometry study) |
| `rr` | 1.5, 2.5 | frozen in DAILY-ONE, **unchanged** |
| `brake` (days skipped after a loss) | 0, 1, 2 | the intervention under test; 0 is the control |

**A correction to this protocol, made before the run and recorded rather than quietly
edited.** The first version fixed `rr = 2.0` and justified it as "DAILY-ONE's most-selected
value". That was wrong: DAILY-ONE's grid was `rr in {1.5, 2.5}`, so 2.0 was never tested,
and the `brake=0` row would not have been a control against anything. Keep the geometry
**identical** to DAILY-ONE and vary only the intervention.

That choice buys the strongest check available: **the four `brake=0` configurations are
exactly DAILY-ONE's grid under exactly its selection rule, so a disabled brake must
reproduce the frozen run's published numbers (+12.83R, 119 trades, t +1.33).** If it does
not, the brake code is not a no-op when disabled and every result below is void. That
assertion is enforced in `scripts/gold_daily_two.py` and it stops the run rather than
reporting.

## 3. Data, folds, selection

Unchanged from DAILY-ONE so the two are directly comparable: XAUUSD M15, 16,224 bars,
2026-01-12 → 2026-09-18, via `gold_wfo_v2.prepare()`; the same 8-day folds (21
selection/evaluation pairs); the **last 40 days untouched**; the same selection rule (best
training R on fold k−1, scored only on fold k, deterministic tie-breaks by
`-stop_mult`, `-brake`, then index, carried forward while training R is non-zero).

## 4. Pass criteria — all eight legs

V1 total > 0 · V2 ≥ 60% folds positive · V3 worst fold > −3R · **V4 beats the matched null
at 200 replications** · V5 median fold > 0 · V6 t ≥ 1.5 · **V7 best-day share ≤ 20%** ·
**V8 a legal size exists** (target met with zero daily and zero shield breaches, found by
bisection, because V8 is an existence claim and testing only the upper bound is the
mistake that was made once already).

## 5. The null — 200 replications, and the reason for that number

Same cadence, same grid, same selection procedure, same folds; direction drawn by a seeded
RNG (`NULL_SEED = 20260919`) instead of read from H4. **200 replications, not 32.** This is
not tuning after the fact: DAILY-ONE's V4 PASS came from a 32-replication p95 that was
ambiguous by **7.5R** (the 30th and 31st order statistics of 32 differ by that much), and at
200 reps the signal fell below the null. A gate that adjudicates using a quantile it cannot
resolve is not a gate.

The bar is the **95th percentile** of the resulting OOS totals. This is a *selection-adjusted*
null ("could picking the best of 6 configurations on noise have produced this?"), **not**
White's Reality Check, and it does not claim to be.

## 6. Pre-registered predictions, so the result can embarrass the hypothesis

Written now, before the run:

* The worst run of consecutive losing days should fall from **5** at `brake=0`.
* The worst peak-to-trough should fall from **6.41R** (against a 12.83R DAILY-ONE total).
* The **max surviving risk should rise above $233.99 per trade**, and that — not the raw
  R total — is what makes the dollar target reachable at a size the shield tolerates.
* Total R should **fall**, because sitting out days removes trades. If total R does *not*
  fall, one of the two implementations is wrong, and that is a bug to investigate rather
  than a discovery.

## 7. What would falsify the hypothesis

Any of: the drawdown measures do not improve; the surviving size does not rise; t does not
improve; or the improvement comes only at `brake=2` (a two-day brake on a 119-day window is
buying a better drawdown by trading so rarely that the result is a small-sample artifact —
V2 and the fold count are the guards against being fooled by it).

## 8. Honest statement of the protocol's weaknesses

* **Capability cost of the §2 correction:** the honest version of this protocol tests the
  brake *within* DAILY-ONE's geometry, not whether a different geometry would suit a brake
  better. A brake that looks useless here could still be useful at a tighter `rr`.
* **A brake is a form of trend-following on the equity curve**, and equity curves are
  autocorrelated in a way 21 folds may not resolve. The brake could be fitting noise in the
  loss sequence; the `brake=0` control is the only defence here, and it is a weak one.
* **This is the third pass over one window.** DAILY-ONE, its ablation and now DAILY-SEQ all
  read the same 21 folds in the same search window. Each pass that finds something raises
  the prior that the *next* pass finds nothing real, and the frozen gate — not the
  narrative — is what decides.
* **A pass earns a validation record, not an arm.** Arming additionally needs an operator
  arming file naming the same `config_id`, a fresh artifact hash, and the readiness gate.

---

## 9. RESULT — NOT VALIDATED (3 of 8 legs), and the hypothesis is FALSIFIED

**Run:** `scripts/gold_daily_two.py` · **artifact:** `artifacts/gold_daily_seq.json`
Nothing above this line was edited after the run except the pre-run §2 correction.

```
CONTROL (brake=0)  +12.83R, 119 trades, t +1.33   <- exactly the frozen DAILY-ONE numbers
brake  total R      t   pos folds  days  worst run   peak-to-trough  best-day  survive $
  0    +12.83  +1.33   14/21      119   5d/ -5.13        6.41          9.6%     $194.92
  1     +4.13  +0.50    9/21       90   4d/ -4.09        6.66         29.8%       $0.00
  2     -2.74  -0.28   11/21       76   5d/ -5.13        8.03          n/a        $0.00

MATCHED NULL (200 reps): median -0.34R   p95 +15.79R   max +25.40R
best brake (1) total +4.13R -> clears p95 by -11.66R

V1 PASS  V2 FAIL  V3 PASS  V4 FAIL  V5 PASS  V6 FAIL  V7 FAIL  V8 FAIL  ->  3/8
```

**The control is the strongest part of this result:** the four `brake=0` configurations
reproduced DAILY-ONE to the decimal (+12.83R, 119 trades, t +1.33), which proves the brake
is genuinely a no-op when disabled and that everything below is measuring the brake and
nothing else.

### Predictions, judged

| pre-registered prediction (§6) | outcome |
|---|---|
| worst loss run shortens | **HELD** — 5 days → 4 days |
| peak-to-trough falls | **FAILED** — 6.41R → 6.66R (worse), and 8.03R at brake=2 |
| survivable size rises above $233.99 | **FAILED** — $194.92 → **$0.00** |
| total R falls (the brake costs trades) | **HELD** — +12.83R → +4.13R |

**So the hypothesis is falsified, and the reason is structural rather than statistical.**
The brake shortens the losing *run* without reducing the *drawdown*: a brake is
**reactive** — it acts after a loss, so it cannot prevent the equity damage that loss
already caused, and it removes profitable days while doing so. Total R falls by 68% while
the peak-to-trough is unchanged or worse, which makes the drawdown-relative-to-profit
worse, not better. The survivable size collapses to zero because no size can reach the
dollar target from +4.13R inside the trail floor.

### The finding that matters most

**The brake undoes the one thing DAILY-ONE got right.** Best-day share goes from **9.6% →
29.8%** at brake=1: trading fewer days clusters the winners into fewer days, pushing the
signal straight back toward the concentration failure that the one-entry-a-day cadence was
designed to avoid. A rule intended to fix the *drawdown* broke the *Best Day* compliance
instead — two constraints that the previous two studies treated as separate turned out to
be coupled through the trade count.

**What this closes.** "Attack the trailing shield with a reactive sequence rule" is now a
measured dead end, not an open question. A trailing drawdown has to be addressed
**prospectively** — declining the trade that starts the run, or sizing so the run cannot
breach — because any rule that waits for the loss has already lost.

### One honest caveat on the control's own number

The control's survivable size reads **$194.92** here against **$233.99** in the ablation,
and both are correct: each bisects over a different interval (this run bounds it by the
worst *run*, −5.13R → a $146 ceiling; the ablation by the worst *day*, −1.05R → $716).
The quantity is real but its resolution is ±$40 depending on the search bounds, so
"about $200 per trade" is the honest statement and no verdict should hinge on the third
digit. This is a limitation of the measurement, recorded rather than smoothed over.
