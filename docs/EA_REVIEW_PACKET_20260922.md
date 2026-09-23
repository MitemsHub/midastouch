# EXTERNAL REVIEW PACKET — MIDASTOUCH XAUUSD EA — 2026-09-22

**Purpose:** hand a reviewer everything needed to attack this system on evidence, in one paste.
Every number below is measured and has an artifact path behind it; none is an estimate or an
aspiration. The program's own rule, which the reviewer is asked to hold us to: *never write a
validation claim you did not measure; if a gate is unvalidated, say so in those words.*

**What the reviewer is being asked for:** concrete, testable improvements to a single-instrument
(XAUUSD) intraday strategy that cannot currently be distinguished from zero edge on 8 months of
its own venue's bars — *not* a parameter list, *not* a rewrite proposal, and *not* an opinion on
whether it "looks good".

---

## 1. The system

One MQL5 EA (`mql5/MIDASTOUCH/MidastouchAI.mq5`, 3,288 lines, 102 functions) trading gold on a
prop account. A python engine of record (`scripts/midas_sweep.py:run_mode`) must agree with it
trade-for-trade; that agreement is certified on real ticks
(`artifacts/midas_parity_result_20260922_1843.json`: 9 trades, python +0.2699R vs EA +0.271R,
`max|dR|` 0.0004). Around the strategy sit certified execution/risk layers: broker-spec handling
that reads the venue (never hardcodes tick size/value/contract size), lot validation, stop-distance
validation, spread cap, a 3 % daily-loss breaker, a 5 %/6 % trailing shield, a daily profit ceiling,
a fail-closed news stand-down, position reconciliation, restart recovery, a ledger with parity
tests, and a refusal census (9 counters) that answers "why didn't it trade" from the file.

## 2. The rule, exactly

```
market data   M15 bars; H1 and H4 EMA20; H1 ATR(14) by SMA of true range; M15 BB(20, k=1.5);
              M15 RSI(14), 70/30
macro         mac = +1 if H1 close[1] > EMA20(H1)[1] AND H4 close[1] > EMA20(H4)[1]
                    -1 if both below,  0 if they disagree
trigger       +1 if the previous M15 close was ABOVE the upper band and the signal bar closed back
                  inside it;  -1 if mirrored below;  else from RSI: >=70 -> -1, <=30 -> +1
mode          REVERSE_DIRECTION: take iff trigger != 0 AND mac == -trigger, direction = -trigger
session       entries only inside a session window (06-20 UTC certified; the live arm runs 04-18
              because its own inputs are compared against server-stamped bar epochs — measured,
              and the live window turns out to be the better of the two on the venue's bars)
stop/target   2.0 x ATR(H1) stop, 2.0R target, one position at a time, fill at the next M15 open
              at the mid +/- half the venue's spread
sizing        0.25 % of equity per trade, floored to the venue's minimum lot, with a veto when the
              floored trade would exceed a 1.5 % cap
```

## 3. The evidence (all held out; `wf` = 2026-01-12→03-31 is the selection span, `oos` =
2026-04-01→2026-09-16)

| measurement | result | artifact |
|---|---|---|
| venue corpus | **16,224 M15 bars, 2026-01-12 → 2026-09-18, 8 months, two clock eras** (+60/+120) | `docs/FROZEN_CORPUS_20260921.md` |
| conjunction census | **82.66 % of in-session evaluable bars produce NO trigger**; armed class 7.54 %, its mirror 4.51 %, macro-divergent 5.29 % | `artifacts/midas_decision_attribution_20260922.json` |
| leg ablation (oos) | armed: 127 fills, 0.75/day, +0.0355R, t +0.39, DD 6.3R · no-macro-gate: 217 fills, 1.28/day, +0.0112R, DD 13.3R · counter-macro-without-trigger: **−0.0941R**, DD 28.6R | same |
| the macro gate's price | removing it costs **+0.0243R** (Welch **t = +0.21**), buys **+70 %** fills, costs **+7.0R** drawdown | same |
| the reversal premise | armed mode vs its mirror: **+0.0249R, Welch t = +0.19** — not established | same |
| **evaluation power** | P(30-trade block positive): **91.5 % on `wf`, 56.6 % on `oos`** (armed). Days per 30 trades: 106 / 40 | `artifacts/midas_eval_power_20260922.json` |
| walk-forward, the rule's own rule | 30 folds: +0.427R/fold, **t = +1.07** vs 1.96 — **NOT VALIDATED**; selected path t +2.00 vs a 144-trial threshold of **3.573**; PBO 0.186; 23 of 29 folds changed their pick | `docs/GOLD_WFO_EA_VERDICT_20260921.md` |
| frequency axes (already moved once) | k 2.0→1.5 pre-registered, held out: 0.63→0.77/day, −0.003→+0.087R; k=1.0 is negative because a narrower band *displaces* the RSI branch | `docs/FREQUENCY_AXES_PREREG_20260922.md` |
| is there a second independent rule? | **No.** 24 configurations of the other rule family: 100 % of overlapping holds were the SAME direction, daily-R correlation ρ ≈ 0.55, combined worst day worse than either alone | `docs/GOLD_RULE_COMPLEMENTARITY_20260921.md` |
| exits | target-free, tight-stop, derived-stop families all refuted on this data | `docs/GOLD_EXIT_FAMILY_AND_HARD_SWITCH_20260921.md`, `GOLD_PREREG_NO_TARGET`, `GOLD_DERIVED_STOP_TEST` |
| live account reality | first live fill: SHORT 0.01 XAUUSD @ 4333.07, closed by hand 6.6 min later (+$4.31). Stop was 4374.38 and price never got above 4352.77 in the next 4 hours: **MAE 0.48R, MFE 0.44R** — the position was never near its stop | live ledger `LOPEN`/`LCLOSE`/`LENTRY` rows |

**Account arithmetic:** 1R = **$41.31 = 0.165 %** of $25,004 (min lot 0.01 with a 2×ATR stop,
i.e. the venue's minimum lot is what sets the risk, not the 0.25 % input). The 3 % daily cap is
**18.2R** away. Median 30-trade drawdown 5.0R ≈ 0.83 % of equity; p90 9.0R ≈ 1.5 %.

## 4. Hard rules the reviewer should respect (they are the program's, not preferences)

1. **Never arm by editing an input.** Arming is an arming-record event (`artifacts/live/armed.json`).
2. **Never write a validation claim you did not measure.** If a gate is unvalidated, say so in
   those words and say what would validate it.
3. **The python engine and the EA are one contract** — change both in one commit or parity is
   meaningless.
4. **Pre-register before measuring.** A rule written after the numbers exist is a description of
   the past, not a test.
5. **Count the trials.** With N searched alternatives the threshold is the 95th percentile of
   max|z| (1.96 at N=1, 3.07 at N=24, 3.61 at N=168), never a bare 1.5.
6. **No uncontrolled online learning.** The live system must stay deterministic and auditable.

## 5. The questions (this is what we want back)

1. Given ~0.75 fills/day and a per-trade edge indistinguishable from zero, is the correct move
   (a) more data, (b) a different entry hypothesis, (c) a different *instrument-timeframe*
   expression of the same hypothesis, or (d) accepting the account's risk-limits profile and
   trading a deliberately small, cheap exposure until a forward record exists? Argue from the
   power arithmetic, not from preference.
2. **Is the reversal premise worth keeping?** `mac == -trigger` beats `mac == +trigger` by
   0.025R (t = 0.19) and halves drawdown. Is there a literature-grounded reason to expect
   counter-trend-at-extremes to work on gold specifically, or is this a fitted sign?
3. **What is the cheapest way to raise the decision rate without lowering the evidence bar?**
   Note that the census says the constraint is the trigger's rarity (82.66 % of bars) and that
   the no-trigger "pool" — `REVERSE_TRIGGER` on the macro side — is +0.043R OOS at 1.27 fills/day
   (t 0.59) while its mirror `REVERSE_BOTH` is −0.094R. Is there a *structurally* different
   trigger family that is cheap to express in MQL5 and has published out-of-sample support on
   gold, session-conditioned?
4. **The exit is a fixed 2R with a 2×ATR(H1) stop and no trailing.** Given a mean-reversion
   entry at band extremes, is a fixed 2R defensible, or is a time-stop/volatility stop the known
   right answer for this entry type? Give the specific alternative and how we would falsify it.
5. **Is the session frame the real lever?** Gold's behaviour differs by session; we measured
   only two candidate windows. What is the published session structure of XAUUSD that a
   pre-registered study should test (and with what minimum sample per session cell)?
6. **Sizing:** the venue's minimum lot makes the declared 0.25 % inexpressible (real risk
   0.165 % of equity). What is the correct way to run a prop evaluation where risk-per-trade is
   quantised by the broker? Is the answer a larger account, a larger stop, or accepting the
   quantisation?
7. **Can 8 months of one instrument ever support regime conditioning?** If not, say so plainly
   and name the minimum data requirement (bars/regimes/trades) you would insist on before any
   regime-gated logic is written.
8. **Multiple testing:** this program has already searched session windows, trigger thresholds,
   8 modes, 144-configuration grids, exit families, news filters and stop widths. Is there a
   *principled* way to consolidate that search into one deflated statement, rather than adding
   more searches on top of it?
9. **The confidence-model question.** We refuse a cosmetic score. If expectancy must be
   estimated per context, what estimator is defensible at n = 20–200 per cell (hierarchical
   shrinkage? a Bayesian prior over contexts? Kelly-fractionated sizing with an uncertainty
   term?), and how is it kept from silently becoming a fitting exercise?
10. **Forward testing.** We have a live arm with a 30-trade gate. What is the correct
    pre-registered decision rule for that forward record — what number, measured when, decides
    continue/stop — that cannot be reinterpreted after the fact?
11. **What would you delete?** Name anything in §1's infrastructure you would remove as
    complexity that has not paid for itself.
12. **What single measurement would most change your advice?** Name it; we will run it and
    pre-register it first.

## 6. What not to propose

Six new setup families · FVG / order blocks / liquidity sweeps / CHoCH as additions (they are in
the request list, and the reference for them is the "Smart Money or Costly Folklore" literature,
not a chart) · a weighted 0–100 confidence score · parameter optimisation on this window ·
any change to the risk/execution layer, which is the part with live evidence behind it · any
"learning" that changes live behaviour from a handful of trades.

## 7. File manifest a reviewer may ask for

```
mql5/MIDASTOUCH/MidastouchAI.mq5                      the EA (3,288 lines)
mql5/MIDASTOUCH/MidastouchAI_upcomers_gold_LIVE.set   the armed preset (the arm's own inputs)
scripts/midas_sweep.py                                the engine of record (run_mode)
scripts/midas_parity.py                               the parity harness + the venue corpus loader
scripts/midas_decision_attribution.py                 the conjunction census + leg ablation
scripts/midas_eval_power.py                           the 30-trade-block power bootstrap
scripts/gold_wfo_ea.py, gold_walkforward.py           walk-forward, V1-V7, PBO (CSCV)
scripts/verify_sizing_live.py                         account-layer verification on the live venue
docs/DECISION_ENGINE_AUDIT_20260922.md                the internal audit this packet summarises
docs/DECISION_ATTRIBUTION_PREREG_20260922.md          the pre-registration behind §3's census
docs/MIDASTOUCH_PROTOCOL.md                           the binding protocol (dated amendments)
artifacts/live/armed.json                             the arming record and every certificate
```

---

### Note on how this packet was produced (and the literature it could not read)

Written 2026-09-22 by the repository's own agent, from the artifacts named above; no number in it
is quoted from a source the repository cannot re-run.

Three 2026 external papers are directly on this rule family and could not be read from here —
SSRN serves them behind a bot challenge (403 to automated fetch, and the browser session did not
clear Cloudflare):

1. S. Mahadzva (2026), *Multiple Testing and the Mirage of Technical Alpha: A Deflated-Sharpe
   Reassessment of Retail Trading Rules in G10 Spot FX* — its stated rule families include
   **Bollinger-band mean reversion**, i.e. this EA's trigger.
2. S. Mahadzva (2026), *Smart Money or Costly Folklore? A Systematic Evaluation of ICT/SMC
   Concepts* — the FVG / order-block / CHoCH question in §6.
3. S. Mahadzva (2026), *Confirmation as a Reversal Signal in Gold and G10 FX* — the reversal-at-
   extremes hypothesis in §2.

They are named here as **required reading before the next strategy decision**, not as support for
any claim: this program's rule is that an unread source is not evidence. Anything they say that
contradicts §3 must be reconciled with a measurement, not with a citation.
