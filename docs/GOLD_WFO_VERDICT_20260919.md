# GOLD WFO VERDICT — 2026-09-19

**Verdict: NOT VALIDATED.** 4 of 6 pre-registered legs fail. Recorded as frozen evidence;
the protocol (`docs/GOLD_WFO_PROTOCOL.md`) is unchanged and this window is now **closed**.

Artifact: `artifacts/gold_wfo.json` · Harness: `scripts/gold_walkforward.py` ·
Pins: `tests/test_gold_walkforward.py` (17 tests)

| item | value |
|---|---|
| instrument | `XAUUSD` (M15 execution, H1+H4 regime) |
| data | 16,224 M15 bars, 2026-01-12 → 2026-09-18, 142 trading days |
| structure | 31 folds × 8 days → **30 out-of-sample folds, 568 OOS trades** |
| selection | best of the frozen 24-config grid on fold *k*, scored on fold *k+1* only |
| cost model | measured: spread 1.073 bps + $10/lot round-trip commission = **0.0247R** |

---

## 1. The result

```
OOS total            +20.67R over 568 trades  =  +0.0364R per trade
fold-mean t-stat     +0.52          (V6 needs >= 1.5)   FAIL
positive folds       12 / 30 = 40%  (V2 needs >= 60%)   FAIL
worst fold           -8.06R         (V3 needs > -3.0)   FAIL
median fold          -0.72R         (V5 needs > 0)      FAIL
OOS total > 0        yes                                PASS
beats random entry   +20.67R vs -86.60R                 PASS
```

**The number to sit with is t = +0.52.** This is not "a promising result that needs more
data" — it is a result indistinguishable from zero, on 568 trades, with a *negative median
fold*. The mean is positive only because the distribution is right-skewed.

## 2. One window out of thirty carries the entire result

```
dropping the BEST fold  (+30.99R) leaves  -10.32R
dropping the WORST fold ( -8.06R) leaves  +28.73R
```

A single 8-day window (F08) is worth more than the whole 8-month total. Remove it and the
family **loses money**. This is exactly the failure mode the gate exists to catch and the
reason V2/V5 are in the criteria rather than total R alone: a strategy whose entire
expectancy lives in one window is a lottery ticket, not an edge — and on a 3%/6% prop
account the drawdown arrives before the payoff.

## 3. What the random-entry control revealed (the most useful finding)

The control holds geometry, trade count, session window and costs identical and randomises
**only entry timing and direction**. Mean of 200 seeded repetitions:

| | per trade | over 568 trades |
|---|---|---|
| random entry, same geometry | **−0.152R** | −86.60R |
| the strategy | **+0.0364R** | +20.67R |
| **difference = the timing signal** | **+0.189R** | |

Two conclusions, and the second corrects a framing this program has been carrying:

1. **The declared geometry has negative expectancy with random timing** (−0.152R/trade).
   The dominant cause is not the spread — it is the **forced 22:00 UTC flatten**, which
   truncates trades that would have reached target, plus gap-through-stop fills. That is a
   structural property of the design, not of gold.
2. **The entry logic is genuinely adding ~+0.19R/trade of timing information.** That is
   **8× the 0.0247R toll**. So on this evidence, **cost was never the binding constraint**;
   consistency was. The program's standing framing — "the toll eats the edge" — is true of
   the toll but was the wrong diagnosis of what is missing.

**Caveat:** the control draws uniformly from in-window bars while the strategy is
conditional, so the +0.189R gap mixes entry *timing* with entry *conditioning*, and the two
groups are not matched on trade duration. It is the right comparison for "does this signal
know something?", not a pure timing measurement.

## 4. Prop compatibility — survived the shield, breached Best Day

P&L attributed to the UTC day of entry, evaluated with the venue's own rule arithmetic
(`ThunderboltClassicRules`, 1R = $75 on the $25,000 account):

```
142 trading days   final equity $26,550.10  (+$1,550.10; 5% target $1,250 -> MET)
worst day          -4.33R = -$325   vs 3% daily limit $750           OK
shield/daily       no violations                                     SURVIVED
best day          +16.65R = $1,249  = 80.6% of total profit
                                    vs 20% Best Day cap              BREACH
```

Two things worth stating precisely, because the obvious reading of each is wrong:

* **The 29.16R peak-to-trough in the fold curve is NOT an equity breach.** The shield trails
  the high-water mark and locks at the initial balance, and that drawdown was taken *from
  profit* ($2,187) while the account was up $3,424. Computing the shield floor properly, it
  survives. Reporting raw peak-to-trough as "8.7% of equity, limit exceeded" would have been
  a false claim, and this is exactly why §7 of the cost-rank doc insists on the rule
  arithmetic rather than a restatement.
* **The Best Day rule is breached anyway** — 80.6% of profit on a single day against a 20%
  cap. So even if the statistical gate had passed, **this result would be disqualified by the
  prop rulebook**. Two independent disqualifications.

## 5. Consequences (binding)

Per protocol §7: **REJECTED**, and this window may not be re-fitted. Specifically forbidden:

* adding trailing stops, breakeven, partial exits or any other mechanism to this grid;
* changing the session-flatten rule and re-scoring on 2026-01-12..2026-09-18;
* re-running with a different fold length, seed or cost assumption and reporting the better
  number;
* treating the +30.99R fold as evidence of anything.

The **legitimate** follow-ups that fall out of this measurement, all of which require a
**fresh window**:

1. **The forced-flat rule is expensive** (−0.13R/trade of the control's baseline). Worth a
   pre-registered test — but gold's `swap_mode = 9` carries are unverified, so permitting
   overnight holding requires resolving §7b of the cost-rank doc first.
2. **The geometry is wrong, not the signal.** A random-entry expectancy of −0.152R means the
   stop/target pair needs re-deriving from gold's own path statistics before any entry study
   is meaningful. Researching entries on a negative-expectancy geometry is what produced this
   ambiguous result.
3. **Profit concentration must be a first-class criterion.** The Best Day breach was
   foreseeable and was not in the gate. A future protocol should carry a concentration leg.

## 6. Limitations (stated, not buried)

* One instrument, one broker, **one 8-month regime stretch**. Nothing here generalises.
* M15 OHLC only — intrabar sequencing is approximated (stop-before-target when both are
  touched), which is the pessimistic direction but still an approximation.
* The measured spread is a 2–3 day tick sample; a wider spread would worsen every number
  and a tighter one would not rescue a t-statistic of 0.52.
* `tp_mult` 3.0 was selected in 12 of 30 folds and supplied the largest wins; the grid is
  small (24) by design but that is still 24 chances to overfit, which V2/V5 exist to punish.

## 7. What this does *not* say

It does **not** say gold is a bad instrument — the cost work stands, gold remains the
cheapest sizeable instrument at 0.0247R, and the timing signal here (+0.19R over random) is
the largest entry edge this program has measured on any instrument. It says that **this
family, on this geometry, on this window, is not an edge**, and that the next attempt must
start from gold's path statistics rather than from an entry rule.

And the honest summary against history: V75's certified net expectancy was **+0.038R/trade,
t = 0.35**. Gold's out-of-sample is **+0.036R/trade, t = 0.52**. Two instruments, two
programs, two years of machinery — the same answer, and both are zero.
