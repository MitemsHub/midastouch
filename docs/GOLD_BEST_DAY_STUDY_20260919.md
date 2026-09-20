# Why the gold strategy's profit concentrates into single days — and why fixing it destroys it

**Run:** `scripts/gold_best_day_study.py` · **artifact:** `artifacts/gold_best_day_study.json`
**Account rules:** $25,000 · 5% target ($1,250) · 3% daily limit ($750) · 20% Best Day cap
**Window:** XAUUSD M15, 2026-01-12 → 2026-09-18, 16,224 bars, 22 folds, 48-config grid

---

## 1. The verdict, first

**There is no configuration of this strategy that both satisfies the 20% Best Day cap
and has positive expectancy.** Eight cap designs were tested — three per-day profit
caps, three per-day trade-count caps, one combination, plus the uncapped baseline —
and **0 of 8 were prop-feasible.**

Two independent reasons, and they are different kinds of reason:

| | finding |
|---|---|
| **Sizing cannot fix it** | Best Day is **scale-invariant**. Resizing by 0.1×, 1×, 10× and 100× leaves the share at exactly **55.5%**. It is a property of the day distribution's *shape*, not its size. |
| **Capping cannot fix it either** | Every cap that reduces the share also removes the edge. The mildest cap (`max 2 trades/day`) holds the SAME selection and still turns **+62.47R into −14.28R**. |

And the one rule that *is* fixable by sizing turns out to be fixable easily:

```
risk window  $20.01 .. $32.76 per trade
at $20.01: equity $26,250.07 (target MET)  survived True  daily breaches 0  shield 0
```

At ~$20 of risk per trade the daily-loss limit is **never breached** and the 6% shield
never comes close. So the daily-limit problem, which looked dire (5 breaches at the
$75 basis the project had been quoting), is purely a position-size error. **Best Day
is the only blocker, and it is the one rule size cannot touch.**

---

## 2. The mechanism: it is a day-count problem, not a lucky-trade problem

This is the part that decides what a redesign could even look like.

| measure | value | reading |
|---|---|---|
| trades | 2,267 over 102 days | median **20/day**, max **55** |
| profitable days | 44 up / 58 down | *more losing days than winning ones* |
| top **1%** of trades | **1.9%** of gross profit | **not** a few lucky trades |
| top 10% of days | 22.9% of profit | but the single best day is **55.5%** |
| corr(trades/day, day R) | **+0.538** | busy days are the profitable days |

The profit is not carried by a handful of outsized winners — the largest 1% of trades
contribute under 2% of gross profit. It is carried by **day-level aggregation**: the
strategy is a trend-follower, and a trending day produces both *more signals* and *more
profit*, so the day totals fan out. One such day banked +34.68R against a window total
of +62.47R.

That is why truncating a day is fatal. A per-day profit cap stops entering once the day
is up its allowance — which cuts the **trending** days, the ones that were going to
accumulate. The choppy days, which lose, are untouched because they never reach the cap.
The measurement says exactly this: under a 1.0R day cap the correlation **flips from
+0.538 to −0.626** — busy days become the *losing* days, because the cap has converted
"trending" into "truncated".

A per-day *trade-count* cap has the same defect for the same reason: it removes entries
from busy days, and busy days are the profitable ones. The mildest version of it, at 2
trades/day, still lands at −14.28R.

---

## 3. Cap effect separated from selection effect

Each swept variant re-selects its own configuration, which answers "what would this rule
have traded?" — but it confounds two things: the cap removing trades, and the walk-forward
picking a different config on a capped (and differently overfitted) stream. So every
variant was measured twice: once with its own selection, and once with the **uncapped
picks frozen**.

| variant | cap only (selection frozen) | with re-selection | selection effect |
|---|---|---|---|
| day cap 1.0R | **−264.03R** | −172.69R | +91.35R |
| day cap 2.0R | **−237.53R** | −199.58R | +37.95R |
| day cap 4.0R | **−236.80R** | −136.58R | +100.22R |
| max 2 trades/day | **−14.28R** | −14.95R | −0.67R |
| max 4 trades/day | **−25.12R** | −31.54R | −6.42R |
| max 8 trades/day | **−79.05R** | −95.92R | −16.87R |
| max 4/day + cap 2.0R | **−46.33R** | −35.16R | +11.17R |
| *uncapped baseline* | *+62.47R* | *+62.47R* | — |

**Selection is not the explanation.** Re-selection sometimes claws back up to +100R, and
the day-cap variants are worst *before* it — but no variant returns to positive. The cap
itself is what removes the edge.

---

## 4. What this does and does not establish

**Establishes.** For *this* signal, on *this* window, the Best Day rule is not a
constraint to be engineered around — it is in **direct conflict with the source of the
edge**. The strategy's expectancy lives in concentration the rule forbids.

**Does not establish.** That no strategy can pass Best Day. A different signal with
different temporal structure — one whose edge is spread across days rather than
accumulated within them, e.g. a low-frequency swing system taking one or two decisions
per day — is not addressed by any of this. The finding is about *this* signal's shape,
and it is a reason to change the signal, not to weaken the rule.

**Also worth stating plainly:** the uncapped baseline still has **t = +0.70**, below the
frozen gate's 1.5. So this strategy was already unarmable
(`docs/PROP_EXECUTION_LAYER.md` §"You cannot arm this on a result that hasn't earned
it"). This study adds a *second, independent* reason it cannot go on this account: even a
validated version of this edge could not be traded under a 20% Best Day cap without
being destroyed. That is a stronger statement than "the backtest failed", and it means
the gold research thread should not be revived by improving the backtest alone.

---

## 5. What changed in the code

* `scripts/gold_wfo_v2.py` — `simulate()` takes optional `day_cap_r` and `max_per_day`
  entry rules. Both default to `None`, reproducing the uncapped strategy exactly. The
  cap is applied **inside** the simulation loop, not as a filter over its output: the
  simulation holds at most one position at a time, so removing a trade frees the slot
  and a later entry fills it — a post-hoc filter would get that coupling wrong.
  Day P&L is attributed to the **exit** bar's day, because that is when the account
  changes. Data preparation is now `prepare()`, shared by the driver and the study so
  the two can never disagree about a regime gate.
* **A profiling fix worth recording:** `trailing_percentile` was 6.8s of a 6.9s
  simulation, recomputed 48 times for an **unchanged** ATR array. It depends only on the
  ATR series, not on the configuration, so `prepare()` now returns the ATR band and
  `simulate()` accepts it. The eight-variant sweep that previously overran a 600s
  timeout now completes in well under a minute. Passing the band changes no result —
  same array, same window, same percentile.

**Equivalence check:** the uncapped variant reproduces walk-forward v2's published
output exactly — **2,267 trades, +62.47R, t +0.70, 10/21 folds.** The refactor is
faithful, and that is asserted in `tests/test_best_day_cap.py` against the artifact.

---

## 6. The honest gap

**One convention is declared, not measured:** day P&L is attributed to the entry bar's
day (matching `gold_walkforward.prop_compat`, which is the referee for survival). The
cap inside `simulate` attributes to the exit bar's day. For this window the difference
is immaterial — the session flatten at 22:00 UTC and the 8h maximum hold keep almost
every trade inside one UTC day, and the count of trades where the two disagree is
reported in the artifact (`exit_day_differs`) rather than assumed to be zero. If that
number ever became large, the two conventions would have to be reconciled before the
numbers meant anything.

**The 20% cap was applied as a per-day profit ceiling, which is the conservative
reading.** The rule as written caps a day's share of *total* profit; a ceiling of
`f × target` is *sufficient* for compliance at any total ≥ target, because the largest
day can then never exceed 20% of a total that is itself at least the target. It is not
the only way to comply — a strategy could in principle bank an unusual day and make up
the share with several more — but it is the reading that cannot be gamed, and the
finding above is that this signal cannot satisfy even the conservative version.
