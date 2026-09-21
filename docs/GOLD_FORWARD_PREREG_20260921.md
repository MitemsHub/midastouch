# Pre-registration: the arm's forward record, its power, and the number that kills it

**Declared:** 2026-09-21, before the first live fill on account 1428765.
**Status of what it governs:** the arm is **live under an operator override**
(`artifacts/live/armed.json`) on a walk-forward gate that **FAILED**. Nothing in this file
is a validation, and nothing here may be cited as one.

---

## 1. Why a pre-registration and not a "30-trade clock"

The paper arm's ledger line reads `closed: N/30`. Thirty trades is a **minimum-sample
floor**, not a test. At the effect sizes this program has actually measured, the arithmetic
is unforgiving:

| sample | mean R/trade | sd R | SE at n=30 | what 30 trades can distinguish |
|---|---|---|---|---|
| venue window, combined (160 trades) | +0.068 | 1.08 | 0.197 | a +0.40R/trade edge |
| armed ORIGINAL mode, venue window (138 trades) | +0.115 | 1.09 | 0.199 | a +0.40R/trade edge |
| best geometry found in the 168-point sweep | +0.032 | 1.37 | 0.250 | a +0.50R/trade edge |

At n = 30 the standard error is ~0.20R/trade, so what a 30-trade record can certify is an
edge **three to fifteen times larger than the effects this program has measured** — 3.4x the
armed mode's +0.115R, 5.7x the window's +0.068R, 15x the sweep's best +0.032R. A positive
30-trade record is therefore consistent with the null at roughly the same rate a coin is, and
"closed 30/30, totalR positive" must never be read as a pass. That sentence is the reason
this file exists.

**Corrected 2026-09-21:** this paragraph previously said "five to six times larger than any
this program has measured". That is true of the +0.068R row (5.7x) and false of the armed mode
(3.4x), which is the row the live override actually runs; the multiples are now stated per row
and pinned in `tests/test_gold_forward_prereg.py`.

## 2. The substitution rate, stated before the data arrives

At n = 100 the standard error falls to ~0.11R/trade (sd 1.09), which makes **+0.15R/trade**
decidable at the gate's own threshold of t ≥ 1.5 (t = 0.15 / 0.109 = 1.38, and the
pre-registered floor for a *decidable* forward test is t ≥ 1.5, requiring ≈ 120 trades at
that effect size). This is the number every earlier document in this program converged on,
and it is the number in the decided threshold below.

## 3. The pre-registered test

* **Sample:** **100** closed trades with a recorded `net_r` on the ORIGINAL-mode forward
  arm, entered after 2026-09-21T13:25Z. Trades before this declaration are excluded, so the
  sample cannot be assembled retrospectively.
* **Statistic:** mean net R per trade, with the fold/trade-level t on the same 100 trades.
* **PASS condition (all four):** mean R > 0 · t ≥ 1.5 · the venue's 3%/6% rules unbroken over
  the period (`prop_compat` on the live ledger's closed rows) · no single UTC day above 20%
  of the accumulated profit.
* **Anything less is NOT VALIDATED.** A positive mean with t < 1.5 is "insufficient
  evidence", never "promising"; this program has already paid for that distinction once
  (four of six gate checks failed on a +1.474R certified window).
* **The kill rule:** at **n = 100**, a mean of **≤ 0R/trade** declares the configuration
  **dead** — the arm is disarmed, `InpLiveExecution` returns to `false`, and the reason is
  recorded as a result rather than a setback. The same applies earlier at any point where
  the venue's own rules halt the account, which ends the evaluation outright.
* **No re-specification after seeing the sample.** Changing the threshold, the window, the
  mode, or the statistic after data arrives invalidates the test and must be recorded as a
  new pre-registration with its own start date.

## 4. What would retire the override without waiting for n = 100

Any one of these is sufficient, and each is checkable today:

1. A governed walk-forward that passes — i.e. V1–V6 on a window the venue can serve, with
   the governor applied inside selection (`scripts/gold_governed_wfo.py --mode governed`).
   **Measured 2026-09-21: 5 of 6 fail, −30.35R over 270 OOS trades.**
2. A geometry at ≥ +0.15R/trade over ≥ 100 out-of-sample trades.
   **Measured 2026-09-21: none in 168 geometries; the best is +0.0816R in sample.**
3. A forward sample at ~208 trades reaching +0.115R/trade (the armed mode's own measured
   effect), which is roughly ten months at the observed ~0.65 trades/day.
4. The venue halting the account.

## 5. Where this is enforced rather than written down

`tests/test_gold_forward_prereg.py` pins the arithmetic in §1–§3 against the harness's own
`power_trades()`, so a future edit that quietly changes the declared effect size or the kill
threshold fails the suite. **Added 2026-09-21:** that file did not exist until then — this
paragraph named an enforcing mechanism that was not there, and a tree-wide guard now fails any
document that does it again (`tests/test_operator_docs.py`, the test-reference rule). The paper arm's own ledger line (`closed: N/30`) is explicitly
**not** the test: it reports the sample floor, and the arm's status is reported from
`artifacts/live/armed.json` by `scripts/morning_status.py` and `scripts/live_readiness.py`.

## 6. Signature of intent

The operator authorised live execution in their own words on 2026-09-21 while this
pre-registration says the evidence did not support it. That is recorded in
`artifacts/live/armed.json` as an override. This file is the part that makes the override
**bounded**: it names the sample that can confirm it, the number that kills it, and the
fact that neither exists yet.
