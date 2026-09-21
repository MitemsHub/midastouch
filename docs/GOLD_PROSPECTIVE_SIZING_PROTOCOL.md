# PROSPECTIVE DRAWDOWN CONTROL — PRE-REGISTERED PROTOCOL

**Written before implementation.** Run: `scripts/gold_prospective_control.py`
Artifact: `artifacts/gold_prospective_control.json`
Date: 2026-09-20 · Symbol: XAUUSD · Account basis: $25,000 (Upcomers Thunderbolt Classic)

---

## 1. THE QUESTION

DAILY-SEQ closed off the *reactive* answer to the trailing shield: a brake that sits out
days after a loss shortened the losing run (5 → 4 days) but did **not** reduce the
drawdown (6.41 → 6.66R), drove the survivable size to **$0**, and broke Best Day
compliance (9.6% → 29.8%). Every one of those failures has one cause — a brake acts after
the loss, so the equity damage is already taken, and it then removes profitable days.

So: can a **prospective** control — one that reserves shield room *before* the run arrives
— clear all eight gate legs?

## 2. THE CONTROL, AS FROZEN

Size every trade at

```
risk  <=  (equity - drawdown_floor_usd(peak_equity)) / (run_days * |worst_day_r|)
```

where `run_days` and `worst_day_r` are **measured** from the signal's own day-level R
series by `worst_loss_run`, not chosen. The signal is DAILY-ONE's frozen core, unchanged:
one entry per day at 08:00 UTC, direction from the single H4 regime bit, 4-vector
geometry, no brake. Nothing about the signal is tuned here — only the risk plan.

The dividing line that matters: room is the distance from **current equity** down to a
floor anchored to the **peak**, because the shield trails the high-water mark and locks
at the initial balance once 6% up.

## 3. PRE-REGISTERED PREDICTIONS

| # | Prediction | Rationale |
|---|---|---|
| P1 | V1–V7 are invariant to the sizing rule | They are computed from `net_r`; risk enters `prop_compat` as a post-hoc scalar |
| P2 | V8 passes, scored as the bisected existence claim it is | An existence claim is size-free; scoring it *at* a size is the mis-implementation that already reported FAIL once |
| P3 | The ceiling is below the single-day bound | That bound cannot see a run |
| P4 | No sizing rule clears all eight legs | The blocked legs are statistical, not dollar-denominated |
| P5 | The closed form is conservative against the bisected survivable size | If it is not, it is unsafe as a live rule |

## 4. RESULT — 6/8, NOT VALIDATED. The control cannot reach the legs that fail.

```
frozen signal reproduced: 119 trades, 119 days, +12.83R, t +1.33
measured sequence: worst single day -1.05R, worst run 5 days -5.13R, peak-to-trough 6.41R

sizing rule                        risk per trade
single-day bound (worst day)          $716.85   optimistic: cannot see a run
simulated survival (bisected)         $233.99   what V8 has been asking for
prospective sequence ceiling          $286.74   5-day run at -1.05R/day

leg                     single-day  prospective
V1 total>0                    PASS         PASS
V2 pos>=60%                   PASS         PASS
V3 worst>-3                   PASS         PASS
V4 beats null p95             FAIL         FAIL
V5 median>0                   PASS         PASS
V6 t>=1.5                     FAIL         FAIL
V7 best-day<=20%              PASS         PASS
V8 legal size exists          PASS         PASS

6/8 legs -> NOT VALIDATED
legs that changed: NONE

P1 CONFIRMED   P2 CONFIRMED   P3 CONFIRMED   P4 CONFIRMED   P5 **FALSIFIED**
```

**The headline is `legs that changed: NONE`.** This was expected and it is still the
result: V1–V7 cannot move because `prop_compat` applies risk as a scalar to an R series it
does not otherwise touch, and V8 is an existence claim, so it is a property of the trade
sequence rather than of any chosen size. **The gate is decided without reference to
sizing.** "Size it better" was never a route to arming this signal, and now that is
demonstrated rather than argued.

V8 passes once scored correctly: a legal size **exists** ($233.99 — target met, no daily
breach, no shield breach). The two failing legs are V4 (does not beat its 200-replication
matched null, +12.83R against p95 +13.02R) and V6 (t = +1.33 against a 1.5 bar). Both are
statistical statements about the signal, and no risk plan changes a t-stat.

## 5. WHAT THE RUN CAUGHT IN MY OWN WORK — TWO BUGS, BOTH IN THE DANGEROUS DIRECTION

**The ceiling was 100× too high.** The first implementation computed
`peak_equity * rules.max_dd_pct`, and `max_dd_pct` is **6.0 — a percentage, not a
fraction**. On a $25,000 account that produced `$28,673.80` of authorised risk per trade
where only `$233.99` survives: an operator following that number would have traded roughly
**120× the survivable size**. Fixed by deriving the room from the venue's own
`drawdown_floor_usd` via a new `shield_room_usd` accessor, so the arithmetic lives in one
place. Pinned by `tests/test_prospective_sizing.py::TestShieldRoom`, which asserts the
room is $1,500 **and explicitly that it is not** $150,000.

**The room was measured from the wrong level.** Corrected for units the ceiling still came
out `$286.74` against the bisected `$233.99` — **22.5% optimistic**, which is what P5
predicted would falsify the design. The cause: the room had been taken from the peak, but
the account is not standing on the peak. It is `equity - drawdown_floor_usd(peak)`. The
function now takes the current equity (defaulting to the peak, the most permissive case)
and the test asserts that a lower equity strictly tightens the ceiling.

**So the closed form is a PRE-FILTER, NOT AN AUTHORITY.** After both corrections it is
still above the survivable size in the most favourable case, and live use only tightens it
by an amount this run cannot bound. The live rule is therefore
`min(closed-form recomputed at current equity each day, bisected survivor)`, with the
sequence simulation as the authority — stated in the function's own docstring so no caller
can read it as a licence.

The unit error is worth generalising: **a percentage-vs-fraction mix-up in a risk
parameter is silent, plausible, and directional.** It did not raise, and `$28,673.80` on a
$25,000 account is not obviously absurd to a reader who has not computed the shield by
hand. Only running the number against the simulation exposed it.

## 6. WHAT THIS ESTABLISHES

1. **The prospective control works as designed and still does not clear the gate.** It
   fixes the *sizing* failure — V8 goes from FAIL (mis-scored at the bound) to PASS — and
   it cannot touch V4/V6.
2. **The trailing shield is survivable, at ~$200/trade**, i.e. approximately one
   hundredth of the risk the single-day rule alone would authorise.
3. **Two independent blockers now stand against this signal**, and they need different
   work: the shield needs a size plan (solved), while V4/V6 need a *better or different
   signal* (not solved, and not solvable by any execution-layer change).
4. **No verification record exists and nothing is armed.** These are research numbers.

## 7. LIMITS, STATED PLAINLY

- One window (2026-01-12 → 2026-09-18), 119 trading days. The run estimate is 5 days; a
  longer history could easily produce 7, which would cut the ceiling by ~30%.
- The null p95 is **reused** from DAILY-ONE's 200-replication run rather than re-derived:
  the null is a property of the signal and this study changes only the risk plan, so
  re-running 800 simulations would reproduce a number that cannot move.
- The surviving size is bisected over an interval whose upper end comes from a day-level
  bound. Both DAILY-SEQ ($194.92) and the ablation ($233.99) are correct answers to
  different bisection intervals; "about $200 per trade" is the defensible statement and no
  verdict should rest on the third digit.
