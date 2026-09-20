# ASSESSMENT — the "20/50 EMA on M15 gold" system (operator-supplied, 2026-09-19)

**Source:** a social-media carousel handed to the architect, not a repo hypothesis. It was
therefore evaluated as **externally specified**: the rules are their rules, and only the one
thing they never state (the stop distance) was chosen — three values, all reported, none
cherry-picked.

**Reproduce:** `python scripts/ema_cross_gold_test.py` → `artifacts/ema_cross_gold.json`

**Measured on:** `XAUUSD` M15, 16,224 bars, 2026-01-12 → 2026-09-18 (248 calendar days),
real Upcomers data, the venue's measured toll (spread 1.073 bps + $10/lot round-trip on a lot
worth $100 per $1.00 move).

**Caveat stated up front:** this is the same window the gold walk-forward already used, so it
is **not** a clean out-of-sample test. But the system is specified *externally* and was not
selected from this data, so a negative result is decisive while a positive one would only
have been suggestive.

---

## 1. What the carousel gets right

Credit where it is due — this is not a nonsense system, and two of its claims check out:

| claim | verdict |
|---|---|
| "1:2.5 needs >29% win rate to profit" | **CORRECT.** Break-even at 2.5R is `1/3.5 = 28.6%`. |
| "XAUUSD moves $20–$40 a day" | **UNDERSTATED.** Measured median daily high-low = **$106.14** (p10 $64, p90 $197) = 2.33% of price. Gold moves more than they claim, which is in their favour. |
| "Two lines, no FVG, no order blocks, no ICT" | Sound instinct. Complexity is not edge, and the repo's own cost study says the same. |
| Behavioural slide ("you'll want to widen the stop — don't", "boring execution is what profitable looks like") | **The best slide in the set, and the only advice that reliably makes money.** |

## 2. What it gets wrong, measured

```
  stop  flatten  trades  win%net  win%grs  gross exp   cost/R   net exp    totalR   W/wk   L/wk
   0.5    False     307   28.7%    28.7%    -0.0273   0.1250   -0.1522     -46.7    2.5    6.2
   0.5     True     307   27.4%    28.0%    -0.0567   0.1250   -0.1817     -55.8    2.4    6.3
     1    False     301   24.3%    24.3%    -0.1653   0.0625   -0.2277     -68.5    2.1    6.4
     1     True     301   25.9%    26.6%    -0.1356   0.0625   -0.1981     -59.6    2.2    6.3
   1.5    False     268   28.0%    28.0%    -0.0276   0.0412   -0.0688     -18.4    2.1    5.4
   1.5     True     277   31.0%    31.4%    +0.0067   0.0415   -0.0348      -9.6    2.4    5.4

  claimed: 45-50% win rate, 3W/2L per week        break-even: 28.6%
```

**(a) The 45–50% win rate never appears.** Measured 24.3%–31.4% gross across every variant.
The claim is **~1.6× the observation**. The whole system rests on this one number.

**(b) The two slides contradict each other.** "3W/2L per week" is a **60%** win rate, which is
not "45–50% realistic". The source asserts 60% in its example and 45–50% in its line above it,
and the truth is **24–31%**.

**(c) The observed win rate is exactly the no-edge baseline.** At 2.5R a coin flip wins
`1/3.5 = 28.6%` of the time. Measured: 24–31%. Gross expectancy is therefore ~0 — best case
**+0.0067R/trade**, and negative in five of six variants. **A 20/50 EMA cross on M15 gold
produces, within measurement error, no directional information at all.**

**(d) Cost is never mentioned, and it is the entire difference between break-even and losing.**
The carousel spends a slide on the maths and none on spread or commission. Measured toll:
**0.041R at a 1.5-ATR stop, up to 0.125R at a 0.5-ATR stop** — i.e. 4–12.5% of the risk on
every trade, and over ~300 trades that is **11R to 38R of pure toll**. That converts a
break-even system into a losing one, which is precisely what the table shows. Every variant
lost money: **−9.6R to −68.5R over eight months.**

**(e) "You need one clean trend a day. Gold gives three."** Measured **1.25 crosses/day**
(8.8/week), so the *frequency* is broadly right — but the *follow-through* is not, which is
what claim (c) shows.

**(f) "Same behaviour for 20+ years — that's the edge."** **This is a logical error and the
most dangerous line in the set.** A random walk has perfectly stable behaviour for 20+ years
and an edge of exactly zero. Persistence of behaviour is not edge; it is the null hypothesis.
Only the win rate *relative to break-even* is an edge, and theirs is zero before cost.

**(g) 1% risk per trade is prop-fatal on this account.** On Thunderbolt Classic the daily cap is
3%. At 1% risk that is **three consecutive losses**, and the measured loss rate is ~71%.
On any day with three trades, `0.71³ ≈ 36%` — roughly a third of busy days end in a daily
breach. The carousel is written for a personal account, not a 3%/6% funded one.

## 3. The independent second opinion

This is not the first test of this idea in this repo. The **pre-registered gold walk-forward**
(`docs/GOLD_WFO_PROTOCOL.md`) already contained an EMA-alignment family on M15 gold —
`(8,21,50)` and `(12,26,100)` — but *with* the additions this carousel omits: H1 and H4
regime agreement, an ATR percentile band, session windows, and ATR-multiple stops.

That, too, came back **NOT VALIDATED** (`docs/GOLD_WFO_VERDICT_20260919.md`): t = +0.52, 40%
positive folds, one 8-day window carrying the whole result.

**Two independent tests — one a bare cross, one a filtered refinement — agree that M15 gold
EMA alignment has no measurable edge.** The refined version did not save it either, which is
the stronger statement: filtering this idea does not repair it.

## 4. What would make it worth pursuing

Not a parameter. The system is not under-tuned, it is **directionless**, and no stop, target,
timeframe or session tweak adds information to a signal whose win rate already equals the
coin flip.

The honest path, in order:

1. **Re-derive the geometry from gold's own path statistics**, not from a round-number RR.
   The walk-forward's random-entry control came in at **−0.152R/trade**, meaning even the
   *geometry* was working against it.
2. **Find a signal that beats break-even gross on a fresh window** before paying any cost.
   At 2.5R that means clearing 28.6% gross by a measurable margin, and it must clear it
   *before* spread and commission are deducted.
3. **Price the toll first, always.** At M15 the toll is 4–12.5% of R per trade; any system
   quoting a win rate without quoting its measured cost is not a system yet.

**Verdict on the carousel: the arithmetic is right, the premise is unverified, the cost is
missing, and the measured result is a loss.** It is a competent-looking restatement of a
coin flip.
