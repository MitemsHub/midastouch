# The arming decision: not armed, and what would change that — 2026-09-21

The operator asked to go live. This is the record of the answer, because in this program
arming is an artifact, not a setting, and an operator override is only meaningful if it is
written down next to the evidence it overrides.

**Decision: the EA stays `InpLiveExecution=false`. No arming record is written. The paper arm
runs on, supervised.**

The reason is not procedure. It is that the strategy's own evidence, measured on the bars the
funded account actually trades, does not support placing an order — and the arithmetic below
says more evidence would take years to arrive, which is a fact about the effect size, not about
patience.

---

## 1. What "going live" requires, mechanically

| gate | state |
|---|---|
| `artifacts/live/armed.json` | absent — the switch defaults OFF |
| `artifacts/live/validation_record.json` | absent — nothing has passed the walk-forward gate |
| preset `InpLiveExecution` | `false` in both presets; the generator **refuses** to emit a live-enabling file without the arming record |
| EA internals | `InpLiveExecution` is the sole switch (`MidastouchAI.mq5`), so the record is the only thing standing between this repo and real orders |

So "arm it" means hand-writing the two records whose absence *is* the safety mechanism. That is
forging a validation. It is not something to do as a side effect of a request to get set up.

## 2. The gate, as pre-registered, on the venue's own bars

Re-run 2026-09-21 (`artifacts/gold_wfo.json`; 31 folds, 16,278 bars from 2026-01-12):

| check | required | measured | |
|---|---|---|---|
| V1 total R | > 0 | +20.67R | pass |
| V2 positive folds | ≥ 60% | 12/30 = **40%** | **fail** |
| V3 worst fold | > −3R | fails | **fail** |
| V4 beats random control | yes | −86.60R control | pass |
| V5 median fold | > 0 | **−0.72R** | **fail** |
| V6 fold-mean t | ≥ 1.5 | **+0.52** | **fail** |

**Four of six fail.** And the replay that does reach the 5% target (+$1,550 on $25,000) puts
**80.6% of that profit in one day** ($1,249) against the venue's 20% Best Day cap — the EA's own
governor exists to refuse exactly those entries, and its effect on that window has never been
measured. So the one number that looks like success would not have been produced by the governed
EA.

## 3. What the venue's own bars say, per trade

Same mode, same basis, python leg of the certified parity runs (0 mismatches against the EA,
`max|dR|` 0.0005), grouped by where in the venue's history they fall:

| sample | window | trades | mean R/trade | sd | t | total |
|---|---|---|---|---|---|---|
| certified window (retired corpus, since **deleted** — so this sample is no longer re-derivable from a checkout; `docs/FROZEN_CORPUS_20260921.md` §4) | 2025-09-15 → 2026-03-31 | 151 | **+0.0098** | 1.082 | **+0.11** | +1.474R |
| venue, first quarter | 2026-01-12 → 03-31 | 53 | **+0.2690** | 1.159 | +1.69 | +14.256R |
| venue, next 5.5 months | 2026-04-01 → 09-16 | 107 | **−0.0312** | 1.025 | −0.31 | −3.338R |
| venue, combined | 2026-01-12 → 09-16 | **160** | **+0.0682** | 1.081 | **+0.80** | +10.918R |

Two things stand out, and both argue against arming:

**The sign flips, on the same venue, on the same code, with parity proven.** The first quarter
averages +0.27R/trade; the following five and a half months average −0.03R/trade. That is not a
filtered-out cost or a clock artefact — the two legs agree on every key in both windows. It is
either a regime that has already ended or 53 trades of luck, and nothing here distinguishes them.

**The good quarter is not one day, which makes it harder rather than easier.** Best day 34% of
its total (without it, +9.39R), 21 of 41 days positive — so it is not a single spike to dismiss.
A genuine-looking good quarter followed by a genuine-looking flat five months is exactly the
shape that needs more data, not less.

## 4. How much more data — and this is the part that decides it

Sample size needed to reach the gate's own `t ≥ 1.5` at each measured effect size:

| effect size | trades needed | at the observed rate (~0.65/day) |
|---|---|---|
| certified window, +0.0098R | **27,657** | **~99 years** |
| venue combined, +0.0682R | **565** | **~2.4 years** |
| venue first quarter, +0.269R | 42 | ~2 months *(the number that would justify arming — if it held)* |

The certified edge is **1/110th of a standard deviation per trade** (0.0098 against sd 1.082).
Costs are not the binding constraint: the measured toll is 0.02473R/trade against a net
+0.0682R on the venue sample, so cost eats about a quarter of the gross. **Noise is the binding
constraint.** The strategy is not being blocked by a gate that is too strict; it is being
measured against an edge too small to see.

## 5. Therefore the forward paper clock is NOT a route to arming

The go-live grammar (`morning_status` [3b], `docs/MIDASTOUCH_PROTOCOL.md` §12) reads: ≥ 30
closed trades on the attached arm with positive expectancy, plus tick reconciliation, plus a
certified watchdog. **30 trades at sd ≈ 1.08 makes the standard error 0.20R/trade**, so that
gate's own bar — "positive expectancy" — is cleared by luck roughly as often as by edge, and
30 trades can neither confirm nor falsify anything about a 0.07R effect. It is a *plumbing*
gate: it proves the EA writes ledgers, survives restarts and reconciles ticks on a live chart.
Treating it as validation would be building on an error, which is precisely what this program
has spent a day not doing elsewhere.

So: the paper arm keeps running — it is the only honest way to keep the plumbing proven and to
add venue bars to the record — and **nobody should read its 30th trade as permission to arm.**

## 6. What WOULD change the decision (falsifiable, pre-registered here)

1. **Venue out-of-sample reaches the bar**: ≥ 100 trades on the venue's own bars with mean
   ≥ 0.15R/trade and t ≥ 1.5 in a pre-registered window, with the governor and the 20% Best Day
   cap applied *inside* the selection — not as a post-hoc filter on an ungoverned replay.
2. **The good quarter is not a regime**: either it extends forward on paper at ≥ +0.15R/trade
   over ≥ 100 trades, or it is declared dead. Today it is 53 trades either way.
3. **The effect size is raised by construction** — fewer, larger-edge trades — so that 100
   trades can carry a verdict. At +0.27R/trade that is 42 trades; at +0.0098R it is 27,657.
   Nothing about the gate changes; only the numerator does.

Any of those can be measured. None of them is a config change, and none of them is this week.

## 7. What is running instead, right now

- The paper mirror is attached and accruing: tag `U25`, `InpMode=0`, session 06:00–20:00 UTC,
  news-off, 1% risk, ledger fresh and flat at $25,000.00, 0/30 closed.
- `MitemshubPaperSupervisor` now points at **this** repo (it pointed at the predecessor
  checkout, which was the single `live_readiness` FAIL), every 20 minutes.
- `MIDAS Watchdog Autostart` is registered and the loop is running; it can see the arm on the
  attach route a VPS uses and its drift guard is live against the repo pins.
- `live_readiness`: **OPERATIONALLY READY, NOT AUTHORISED.** That is the intended resting state
  until §6 is satisfied.
