# GOLD WFO PROTOCOL — pre-registered 2026-09-19, before any result exists

**State at write time:** zero trades simulated on gold in this repository, zero configurations
evaluated, no parameter looked at. This file is frozen *before* the harness is run so that
nothing in it can be fitted to an outcome. Same discipline as `docs/SYNTHETIC_GATE_V2.md`
(written with zero arms and zero trades) and `docs/MIDASTOUCH_PROTOCOL.md` §13.

**Question this answers:** *can any configuration of the declared strategy family produce
positive out-of-sample expectancy on `XAUUSD` net of the measured toll?* It does **not**
answer "is gold a good instrument" — that was settled in
`docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` §7 (gold is the cheapest sizeable
instrument at 0.0247R).

---

## 1. What is declared, and what is forbidden

**Declared before data:** the instrument, the data window, the timeframe, the strategy
family, the parameter grid, the cost model, the fold structure, the selection rule, the
pass criteria and the verdict rule. All of it appears below.

**Forbidden after data:** adding a parameter to the grid; widening a threshold because a
fold "almost" passed; re-using a rejected window to select a new geometry; reporting the
best fold; reporting in-sample performance as evidence. If the grid fails, the grid fails.

---

## 2. Instrument and data (fixed)

| item | value | why |
|---|---|---|
| instrument | **`XAUUSD`** | cheapest sizeable instrument on the venue: 0.0247R, gapX 3.10 |
| execution timeframe | **M15** | matches the repo's proven structure and gives enough trades for `n≥30` |
| regime timeframes | **H1 and H4** | direction agreement and higher-timeframe trend |
| source | `Upcomers-Server` via `scripts/mt5_data.py` | terminal-authenticated, `.npy` cached |
| window | **2026-01-12 → 2026-09-18** | all history the venue serves (16,224 M15 bars) |
| warm-up | first **480 M15 bars** excluded (~5 days) | indicator and ATR-percentile burn-in |

This is **one instrument, one broker, one 8-month regime stretch**. That is a standing
limitation of every result here and is restated in the verdict.

---

## 3. Cost model (measured, not assumed)

The toll is what makes this whole exercise necessary, so it is taken from measurement:

| component | value | source |
|---|---|---|
| spread, round trip | **1.073 bps of price** | tick-derived mean, `artifacts/profile_XAUUSD.json` (365d) |
| spread, in USD | **$0.47** at 4,376 | 1.073e-4 × 4,376 |
| commission | **$5 / lot / side → $10 round trip** | Upcomers published schedule; `upcomers_rules.py` |
| commission in bps | **0.229 bps** | $10 on 1 lot = 10 oz notional |
| **total round trip** | **≈ 0.0247R at a 1-ATR stop** | §7c of the measured cost rank |

Two deliberate modelling decisions:

1. **The bar-embedded `spread` field is NOT used.** It reports a median of 21 points =
   $0.21, which is the broker's *nominal* figure and is **2.2× tighter** than the $0.47
   measured from real ticks. Using the nominal number would flatter every result. The
   tick-derived figure is the honest one and the harness must be run with it.
2. **No overnight carry is modelled, because no overnight position is allowed.** `XAUUSD`
   reports `swap_mode = 9`, which is not a documented MT5 swap mode, so its carry is
   **unverified** (measured cost rank §7b). The protocol therefore requires every position
   to be **flat before the session end (21:00 UTC)**. This is declared *now*, before
   results, and it is also the conservative choice: it removes the overnight gap exposure
   that `gapX = 3.10` warns about.

**Every entry pays half the spread and every exit the other half**; commission is charged on
both legs. Gross and net R are both reported so the toll's contribution is visible.

---

## 4. Strategy family (fixed, closed grid)

A single trend-continuation family, because the measured profile says gold's movement is
concentrated in the London/US window and is directionally persistent there. Stratified by
**structure** (is H1/H4 aligned?), **timing** (which UTC hours?), and **geometry** (stop and
target as ATR multiples).

**Entry (long; short is the mirror):**
1. `EMA_fast > EMA_mid > EMA_slow` on M15 (closed bars only, no look-ahead);
2. `EMA_fast > EMA_mid > EMA_slow` on H1, and `close > EMA_fast` on H4 — regime agreement;
3. entry bar's hour ∈ the declared session window;
4. `ATR(M15,14)` at signal time is between the 20th and 95th percentile of its own trailing
   500-bar distribution — no dead tape, no post-shock spike;
5. no position currently open (one position at a time — never adds, never hedges);
6. exit: stop at `stop_mult × ATR`, target at `tp_mult × ATR`, **or forced flat at 21:00 UTC**.

**Grid (24 configurations, declared in full):**

| dimension | values | n |
|---|---|---|
| EMA set on M15 | (8, 21, 50), (12, 26, 100) | 2 |
| `stop_mult` | 1.0, 1.5 | 2 |
| `tp_mult` | 1.5, 2.0, 3.0 | 3 |
| session window (UTC) | 07–20, 13–18 | 2 |

Nothing else varies. No trailing stop, no breakeven, no time exit other than 21:00 UTC, no
partial fills, no pyramiding. **24 configurations is the entire search space**; 24 is
declared up front because an unbounded grid is how a backtest manufactures an edge.

---

## 5. Fold structure and selection rule (fixed)

* Folds are **contiguous calendar blocks of 8 days** starting after warm-up
  (`FOLD_DAYS=8`, the frozen value used by `scripts/gold_walkforward.py`).
* **Walk-forward, not in-sample:** for each fold *k*, the best configuration is selected
  using **only fold k's data**; that configuration is then evaluated on **fold k+1** and
  only that result counts. Selection and scoring never share a bar.
* If fold *k* produced no trades for any configuration, the previous selection carries
  forward and the fold is recorded as such.
* Ties in selection are broken by **lower `stop_mult`, then lower `tp_mult`, then the
  earlier grid index** — deterministic, declared here so no tie-break is chosen after the fact.
* The reported figures are the **concatenation of the OOS folds only.**

---

## 6. Pass criteria (frozen; ALL must hold, else NOT VALIDATED)

Adapted verbatim from the V1–V6 block in `scripts/gold_walkforward.py`, with V4 replaced by
a stronger test than "beats the reference config":

```
V1. OOS total R > 0
V2. positive in >= 60% of OOS folds
V3. worst OOS fold R > -3.0
V4. OOS total R > a seeded RANDOM-ENTRY control with identical trade count,
    identical geometry and identical cost model
V5. median OOS fold R > 0
V6. OOS fold-mean t-stat >= 1.5
```

**V4 is the one that matters.** A positive backtest can come from drift, from the cost model,
or from a handful of lucky trades. The random control holds trade count, holding logic,
geometry and costs identical and randomises *only the entry timing and direction* (seed
declared in the artifact, fixed at 20260919). If the family cannot beat coin-flip timing
after the same costs, it has no edge and no amount of V1 goodness changes that.

**There is no "almost passed."** A single failed leg is NOT VALIDATED.

---

## 7. Verdict rule (declared before data)

```
selected-config OOS total is computed
│
├─ ALL of V1..V6 hold
│     → PROVISIONAL EDGE. Research-only. Does NOT authorise live or paper trading:
│       legs A, D and E of SYNTHETIC_GATE_V2.md still require a certified fresh-window
│       cell, >=30 closed paper trades and paper/tick reconciliation. A walk-forward on
│       one 8-month window cannot satisfy any of those, and this document says so now.
│
├─ V1..V3 hold but V4 fails
│     → NO EDGE. The family is indistinguishable from random entry after cost. REJECTED.
│
├─ V1 fails (OOS total <= 0)
│     → REJECTED. Recorded as a closed window. May not be re-fitted on this data.
│
└─ fewer than 30 OOS trades
      → CONTINUE-UNPROVEN. Insufficient evidence either way; NOT a pass.
```

**Pre-declared expectation.** Every gate this project has run has ended NOT VALIDATED. The
family above is a *reasonable* family, not a promising one, and gold's measured toll is
0.0247R against a best-ever measured edge of +0.027R. **The most likely outcome is REJECTED
or NO EDGE**, and that outcome is a useful result: it is the difference between "we have not
looked" and "we looked and there is nothing there."

---

## 8. The news stand-down is NOT part of the certified contract (decided 2026-09-21)

The rule exists and both engines apply it identically (`midas_prop.risk.news_calendar`, one
file, one vocabulary, one judged instant). The question this section settles is narrower: is
it part of *this* contract — the frozen walk-forward that certified the strategy — or an
amendment that must be certified on its own terms?

**It is an amendment. The certified contract is news-OFF, and every preset ships it OFF.**

The evidence, all of it reproducible from this repo:

1. **It changes what the walk-forward SELECTS, not only what it takes.** Applying the veto
   during selection on the frozen window (2026-01-12 → 2026-09-18, 16,224 M15 bars, 31 folds)
   re-selects the grid's configuration in **F04**. A pre-registered run
   (`scripts/gold_news_sensitivity.py --preregister`, expectation and decision rule written
   to `artifacts/gold_news_preregistration.json` *before* either leg ran) judges that against
   P1 — "no fold's selected configuration changes" — and returns **REJECTED**. The
   configuration a strategy is certified with cannot be re-chosen by an amendment and still
   be the certified one.
2. **The delta is one eight-day fold.** Veto ON is +3.36R on +20.67R (568 → 559 trades, t
   +0.524 → +0.618), and the leave-one-fold-out attribution puts **112% of it in F04**:
   drop that fold and the total is **−0.41R**. Three folds of thirty moved at all.
3. **The effect the rule exists to avoid is not measurable at its own width.** With a
   horizon- and hour-matched baseline, gold's move across a ±15-minute HIGH blackout is
   **1.02× ordinary**, and 10% of releases beat the same-horizon p90 — exactly the rate a
   no-effect window produces (`docs/GOLD_NEWS_WIDTH_20260921.md`). The lag sweep is flat from
   −60 to +60 minutes, which rules out the calendar sitting off the venue's bars as the
   explanation.
4. **Its cost is real.** 398 of 16,224 corpus bars (2.45%) are inside a blackout, and 122 of
   them are bars where the engine of record's own entry conditions held inside the session —
   opportunities the rule removes to protect against a 1.02× move.

**What follows, and what does not.** The frozen window stays news-OFF and its artifacts are
not re-run. Any decision to trade with the gate on is a *new* strategy claim: it needs its own
pre-registered walk-forward and its own certification, which is what the amendment's
measurement is for. Nothing here licenses enabling it — and nothing here forbids measuring it
again on a new window. The rule itself stays in the EA and in the engine of record, shipping
off, because a rule that can only be enabled by a registered amendment must remain
replayable on both sides.
