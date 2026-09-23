# DECISION ENGINE AUDIT — 2026-09-22 — is the trading logic structurally too rigid?

**The request:** treat the EA as a serious research project, prove (not assume) whether the current
logic is structurally too rigid, and upgrade the decision engine into an adaptive, evidence-driven
Gold system — without a rewrite, without curve-fitting, without inventing "AI".

**The answer, measured on this program's own data, is in three parts.**

1. **The execution and risk architecture does not need rebuilding, and the live arm already proves
   it.** Every protective gate is measured at **zero refusals** on the live record, and the one
   class of veto that does fire is the entry rule's own. The machinery is not what is holding the
   arm back from trading; the *trigger* is, and by construction rather than by accident.
2. **One of the three legs of the entry conjunction does not pay for the entries it costs.**
   MEASURED this session (new harness, `scripts/midas_decision_attribution.py`): removing the
   macro-alignment requirement takes the fill rate from **0.75 → 1.28 entries/day** and costs
   **+0.024R** of held-out expectancy — a difference with **Welch t = +0.21**, i.e. not
   measurable — while **halving max drawdown (6.3R → 13.3R)**. That is the trade-off, stated as a
   price instead of an opinion. (Pre-registered bar: a leg earns its keep only if removing it
   costs ≥ 0.05R. It does not. It does, however, buy drawdown.)
3. **The binding constraint on every item on the wish-list is not the design — it is the size of
   the record.** The venue corpus is **2026-01-12 → 2026-09-18: 16,224 M15 bars, 8 months, two
   clock eras, ~0.75 fills/day**. At the armed configuration, deciding its own expectancy at
   t ≥ 1.5 needs **1,931 held-out trades ≈ 7 years of this market**; `TRIGGER_ONLY` needs 43
   years, `MACRO_ONLY` 79. A six-setup-family, seven-regime, confidence-scored engine would
   multiply the hypotheses searched against those same eight months. **That direction makes the
   validation problem strictly worse, and no amount of engineering changes it.** The first thing
   this program needs is *more of the venue's own bars*, not more logic.

Nothing in this report was written before its numbers existed: the study was pre-registered
(`docs/DECISION_ATTRIBUTION_PREREG_20260922.md`) and its self-checks are binding (below).

---

## 1. Current architecture — the map, from the source

`mql5/MIDASTOUCH/MidastouchAI.mq5`, 3,288 lines, 102 functions, one file. The decision path is
short and every stage of it is named below with its line:

```
MARKET DATA        iTime/H1/H4/M15 series (never a hardcoded symbol; accounts.json resolves it)
                   AtrNow() 854 · AtrAtShift() 631 · GetBar() 611 · SpreadAt() 597
   -> MACRO        MacroState() 886      H1 close[1] vs EMA20[1] AND H4 same  -> +1/-1/0
                   (the ONLY place the two directions are computed; the HUD re-reads this)
   -> TRIGGER      TriggerOnClosedBar() 908 / BarEvaluateSignal() 1677
                   BB(20,k) touch-back-inside  ELSE  RSI(14) >=70 / <=30
   -> MODE         ModeDecide() 933      8 modes; armed = REVERSE_DIRECTION: mac == -trigger
   -> GATES        InSessionBar() 876 · Friday cutoff · NewsVetoReason() · SpreadCapOK()
                   · min-lot risk cap · DailyBreakerTripped() 2908
   -> RISK/SIZE    SizingNumbers() 349 · ConfiguredRiskUsd() 342 · LiveSendOrder()
                   · DollarPerUnitPerLot() 698 (venue spec, not hardcoded) · min-lot floor+veto
   -> EXECUTION    live: LiveSendOrder -> broker | paper: OpenPaperPosition() 2659
   -> MANAGEMENT   BarFillAndManage() 1495 · BarManage() 1567 · PaperCheckHardExits() 2736
   -> RECORD       PaperLog() 494 · StateRowWrite() 436 · RiskAppend() 2386 · DiagMaybeWrite() 2042
                   · LiveCensusAdd() 1912 · RestoreOrVerifyLedger() 1215 · ResolveLiveIds() 1351
   -> GOVERNOR     PropPhaseCheck() 1264 · PropDayAnchorCheck() 2891 · PropDayProfitCapUsd() 2978
```

**Component disposition (Phase 1 group 2, and Phases 8/10/16/21/22 of the request).** These are
**KEEP**, with the reason measured rather than asserted — every one of them has a defect history
with a fix and a pin behind it (v1.18–v1.26 in the CHANGELOG), and none is implicated in the
fill rate:

execution handling · broker-spec handling (`DollarPerUnitPerLot` reads the venue, and the venue's
self-inconsistency is *recorded*, `SPEC` rows) · lot validation · stop-distance validation ·
spread cap · slippage/fill model · risk controls · daily loss breaker · exposure controls · prop
governor · session/Friday controls · position reconciliation · restart/recovery · telemetry ·
ledger handling · parity/diagnostic infrastructure · NOFILL diagnostics · trade management ·
error handling.

## 2. Every place a valid opportunity can be rejected — and which are accounted

The census has **nine** counters and the live record shows `session/friday/spread/riskcap/brk/
news = 0`: the entire protective layer is currently free. The strategy veto is one class
(`g_nofill_signal`, split into `notr` / `mism`). Against that, there are **five** `return` points
that refuse a bar **silently**, with no counter:

| # | site | line | accounted? |
|---|---|---|---|
| 1 | history-depth guards `Bars() < 21` (H1/H4/M15) | 1701 | **silent** |
| 2 | window membership `g_win_t0/t1` | 1711 | **silent** (tester-only) |
| 3 | `atr <= 0` / `stop_d <= 0` | 2640/2643 | **silent** |
| 4 | stale feed (`InpStaleMinutes`) | 2575 | journal only, not counted |
| 5 | mode refuse | 2597 | **counted** (`signal`, `notr`, `mism`) |
| 6 | session window | 2615 | **counted** |
| 7 | Friday cutoff | 2619 | **counted** |
| 8 | news stand-down | 2632 | **counted** |
| 9 | spread cap | 2645 | **counted** |
| 10 | min-lot risk cap | 2689 / 3067 | **counted** |
| 11 | daily breaker | 3271 | **counted** |

Rows 1–4 are the instrumentation gap this report recommends closing first (see §9): they cannot
refuse anything today (`Bars()` is in the thousands, the window is tester-only), but "cannot
refuse" is a claim about *now*, and the census should be able to say so itself.

## 3. Why the arm is inactive — three causes, measured

**(a) The trigger is the rarity, by design.** NEW, 2026-09-22 — the conjunction census over every
*evaluable* bar (in-window, ≥21 bars of history, stop > 0), inside the certified session window:

| held-out `oos` (2026-04-01 → 2026-09-16), in-session bars | count | share |
|---|---|---|
| **no trigger fired** | 5,516 | **82.66 %** |
| trigger, macro **divergent** (`mac == 0`) | 353 | 5.29 % |
| trigger, macro **agreeing** (what `ORIGINAL` trades) | 301 | 4.51 % |
| trigger, macro **anti-aligned** (what the armed mode trades) | 503 | **7.54 %** |

So of 6,673 in-session evaluable bars in five and a half months, the armed mode's *class* occurred
**503** times and produced **127** fills (occupancy and the one-bar pending rule account for the
rest). The per-hour table is flat — **380–420 of every 480 bars per hour have no trigger**; the
trigger is an extreme-reversion condition (band touch-back or RSI ≥ 70/≤ 30), and gold spends most
of its time between its bands.

**The live record says the same thing, from a different direction.** `STATE` rows are written on
every evaluated bar, so the arm's own census is derivable from its ledger: of the **50 distinct
signal bars** it has evaluated, **35 (70 %)** had no trigger at all, **5 (10 %)** were the armed
class, and **10 (20 %)** fell outside the session window.

**(b) The macro leg buys drawdown, not expectancy.** NEW, `midas_decision_attribution.py`, the
engine's own 8 modes on the pre-registered split (select on `wf`, report on `oos`):

| mode | oos n | /day | zero-entry days | expR | pf | win | max DD (R) | t | trades needed for t≥1.5 |
|---|---|---|---|---|---|---|---|---|---|
| **REVERSE_DIRECTION (armed)** | 127 | 0.75 | 41.4 % | +0.0355 | 1.074 | 0.433 | **6.3** | +0.39 | **1,931 ≈ 7.0 yr** |
| ORIGINAL (macro *agrees*) | 136 | 0.81 | 34.3 % | +0.0105 | 1.011 | 0.426 | 5.9 | +0.12 | 22,878 |
| TRIGGER_ONLY (no macro gate) | 217 | **1.28** | **29.0 %** | +0.0112 | 1.012 | 0.442 | **13.3** | +0.15 | 20,249 |
| REVERSE_TRIGGER (no-trigger bars, macro side) | 215 | 1.27 | 29.0 % | +0.0430 | 1.085 | 0.419 | 14.9 | +0.59 | 1,373 ≈ 3.0 yr |
| MACRO_ONLY | 221 | 1.31 | 29.0 % | +0.0082 | 1.006 | 0.394 | 17.4 | +0.12 | 37,765 |
| SHORT_ONLY | 77 | 0.46 | 59.8 % | +0.0974 | 1.212 | 0.494 | 4.2 | +0.79 | 279 ≈ 1.7 yr |
| LONG_ONLY | 64 | 0.38 | 66.9 % | −0.0290 | 0.925 | 0.375 | 6.9 | −0.22 | — (negative mean) |
| REVERSE_BOTH (counter-macro, no trigger) | 233 | 1.38 | 29.0 % | **−0.0941** | 0.792 | 0.433 | 28.6 | −1.43 | — (negative mean) |

`wf` for the same cells, for the record: RD +0.2846 (n=56) · ORIGINAL +0.2510 · TRIGGER_ONLY
+0.0183 · REVERSE_TRIGGER +0.2092 · MACRO_ONLY +0.1759 · LONG_ONLY **+0.3136** · SHORT_ONLY
+0.1791 · REVERSE_BOTH −0.1174. The `wf` span is 3 months and its numbers are systematically
better; **`LONG_ONLY` flips sign between spans** and `ORIGINAL` collapses from +0.251 to +0.010.
That is the signature of a searched sign, not an asymmetry, and it is why no mode is selected by
this study.

**(c) The macro gate's cost is real but not measurable, and its benefit is not the one claimed.**
`REVERSE_DIRECTION` vs `TRIGGER_ONLY` on the held-out window: **+0.0243R, Welch t = +0.21**;
`REVERSE_DIRECTION` vs `ORIGINAL` (the mirror class): **+0.0249R, t = +0.19**. The "reverse"
relationship between macro and trigger was worth about **0.025R** on this window, indistinguish-
able from zero at either sample — while the drawdown it saves (**6.3R vs 13.3R**) is large and
visible.

## 4. Which filters are too restrictive — verdict per leg

Pre-registered rule: **a leg earns its keep only if removing it costs ≥ 0.05R of held-out
expectancy per trade.**

| leg | verdict | number |
|---|---|---|
| session window | **KEEP** (as a frame question, not a filter) | The frame mismatch — live runs UTC 04–18 on this venue's +2 clock while every certificate says 06–20 — was measured and fixed 2026-09-22 (`docs/FREQUENCY_AXES_PREREG_20260922.md`): the live window is *better* on both spans. No frequency is lost to it. |
| trigger threshold k | **ALREADY MOVED, and it moved for the right reason** | 2.0 → 1.5, pre-registered, held-out: 0.63 → 0.77 entries/day, −0.003 → +0.087R, DD 7.6 → 6.5R. At k=1.0 the trigger *displaces* the RSI branch and expectancy turns negative. This is what a frequency upgrade looks like when it is measured. |
| **macro alignment leg** | **COSTS WITHOUT MEASURABLY PAYING** | Removing it: +70 % fills (0.75 → 1.28/day), −0.024R (t = 0.21), **+7.0R of drawdown**. Fails the pre-registered test; buys real protection. This is a decision for the account holder, not a defect. |
| risk gates (spread, session, Friday, news, min-lot, breaker) | **KEEP — all measured at zero refusals** | Nothing is being lost here. The min-lot floor *is* binding economically (5 of 7 live fills floored to 0.01 lots, realized risk ~$39–41 against a $62.50 budget at 0.25 % of $25,000) — that is a **sizing** fact, not a filter. |
| `REVERSE_BOTH` | **MEASURED HARMFUL** — never enable | −0.094R held-out, 28.6R DD over 233 fills, negative in both spans. |

## 5. Components that are weak (measured, not guessed)

- **The exit geometry.** `InpTpMult = 2.0R`, `InpSlAtrMult = 2.0 × ATR(H1)`, fixed for every
  regime. This program has already measured exit families (`gold_exit_family_wfo.json`,
  `docs/GOLD_EXIT_FAMILY_AND_HARD_SWITCH_20260921.md`, `gold_exit_capture.json`) and the
  no-target/tight-stop routes were refuted on this data. It is *unresolved*, not unexamined.
- **The macro leg's sign.** The armed mode's premise — enter *against* the H1/H4 regime at M15
  extremes — is better than its mirror by 0.025R on the held-out window (t = 0.19). The premise
  is **not established by measurement**; it survives on `wf` (+0.285 vs +0.251), which is the
  span the configuration family was searched on.
- **The equity/return-multiple denomoinator.** R (stop-normalised) is the right unit for
  comparability and the wrong one for a prop evaluation: expectancy must be judged against
  *dollars at the account's size*, where the min-lot floor sets the real risk per trade. The
  sizing mirror exists (`verify_sizing_live.py`, `InpRiskPercent` + floor + veto) and is legal at
  0.01 lots — this is a reporting gap more than a logic gap, but it is why "+0.03R" and "the
  account cannot size down" coexist.

## 6. Which components should be removed

**Nothing, yet.** The one class with a measured negative expectancy (`REVERSE_BOTH`) is already
disabled by configuration, and every gate is free. Deleting a leg that "looks useless" because its
Welch t is 0.21 would be exactly the unmeasured change your own Phase 30 forbids — the same
number that says the macro gate does not pay for its entries also says we cannot yet prove it is
worthless. It stays, with its price printed.

## 7. Which new components the evidence actually supports (ranked)

1. **MORE VENUE DATA — first, and it is not a strategy change.** The corpus is 8 months. The
   terminal can serve and export more of *the same venue's* history; the frozen/retired series
   cannot substitute (the repo already measured that a different source is a different market:
   `docs/FROZEN_CORPUS_20260921.md`). Everything else on this list is blocked behind this one.
2. **A volatility-conditioned risk layer, sized in dollars.** The propulsion already exists
   (`InpRiskPercent`, min-lot floor + veto, governor, breaker). What is missing is the *measured*
   rule for risk-per-trade as a function of realized volatility, and the account-size arithmetic
   that makes 0.25 % expressible. This is the only "adaptive" change with a pre-existing harness.
2. **A rejection census that names the silent exits** (§2 rows 1–4), then a live counterpart to
   the offline attribution: the `STATE` row already carries mac/trigger/session per bar, so the
   live census above cost nothing — extend `STATE`/`NOFILLSUM` with the ATR tercile and the
   rejection class so the two records are joinable by construction.
3. **Regime conditioning — only where the ternary can decide it.** One axis at a time (H1-ATR
   tercile first), pre-registered, with the required-sample column printed beside every cell. A
   seven-regime classifier is not an upgrade on this data; it is 7× the search.
4. **NOT supported by this data: six setup families, FVG/order blocks, a weighted confidence
   score, structural/liquidity engines.** Each is a hypothesis with a free parameter vector, and
   the arithmetic of §3(b) says a cell must be worth ~30–2,000 trades to be decidable. Building
   them now would produce a beautiful, unverifiable EA — which is the failure mode this program
   exists to refuse.

## 8. Proposed architecture (shape, not rewrite)

Keep the existing file's spine and its certification machinery. The change is **one seam**, not a
new engine:

```
market data (unchanged)
  -> MarketContext        a struct computed once per evaluated bar: mac/h4/h1 (existing),
                          ATR + ATR ratio vs trailing median, session bucket, spread
  -> SetupEngine          a LIST of explicit setups. Today there is one: "extreme-reversion at
                          the band with the macro anti-aligned". The list is data, each entry
                          with its own trigger predicate, its own regime compatibility, and its
                          own pre-registered record. Adding a family = adding a row + a study,
                          never editing the others.
  -> EvidenceGate         per-bar: which setups are admissible GIVEN the context, unchanged
                          protections, then the existing ModeDecide as one setup among them.
  -> Confidence           NOT a score. An EXPECTANCY STATEMENT with its sample size and its
                          t, from the pre-registered cells only; insufficient sample => no trade
                          (the "I see an opportunity but the evidence is insufficient" answer).
  -> risk/size/governor/execution/telemetry  UNCHANGED, byte-identical behaviour
```

The load-bearing property: **the EA must be able to say "insufficient evidence" and that state
must be a first-class, ledger-visible outcome** — which it can already do (`NOFILLSUM`, `STATE`)
and which is exactly why the present build is honest about not trading.

## 9. Testing plan (and what is already done)

| step | status |
|---|---|
| 1. Baseline the current EA | **DONE** — the v1.26 certificate: 9 trades, `max|dR|` 0.0004, `artifacts/midas_parity_result_20260922_1843.json`; the venue-corpus laws pinned in tests |
| 2. Instrument rejection | **DONE** (9 counters + `STATE` rows + 8-mode attribution); silent exits named in §2, to be counted |
| 3. Validate EMA/BB/RSI/reversal assumptions | **DONE THIS SESSION** (§3) — the reversal premise is +0.025R @ t=0.19; the trigger is the binding rarity |
| 4–8. Regime / structure / liquidity / setup / confidence engines | **BLOCKED on data** (§7.1). Each would be a pre-registered study with its own required-sample column |
| 9. Connect new signal engine to existing risk/execution | not started — the seam is designed in §8 |
| 10–14. Backtest, compare, OOS, walk-forward, optimize | the harness exists (`gold_wfo_ea.py`: 30 folds, V1–V7, PBO) — **the existing rule already ran it: NOT VALIDATED**, t = +1.07 against 1.96 |

## 10. Expected trade-frequency change

Measured, not simulated: **0.75 → 1.28 entries/day** if the macro-alignment requirement is
dropped, with zero-entry days **41.4 % → 29.0 %**, at a cost of **0.024R** (unmeasurable at this
sample) and **+7.0R of max drawdown**. Nothing else on the table increases frequency without
either adding a setup family (undecidable on this data) or lowering a risk gate (all of which are
free and would be a defect to weaken).

## 11. Risks of the redesign

1. **Multiple comparisons.** Every added toggle is another look at the same 8 months. The
   program's own measurement: at 144 configurations the 95 % family-wise threshold is
   **t = 3.573** — the selected path's t = +2.00 did not clear it, and **23 of 29 folds changed
   their chosen configuration**.
2. **A "confidence score" that is a fitted number wearing a label.** Your Phase 10 asks for one;
   this data cannot calibrate one. The honest version is an expectancy statement with t and n,
   which is what §8 proposes.
3. **Frequency as a goal.** More trades at +0.01R is more spread paid for noise: at this risk the
   commissions and the min-lot floor dominate the edge.
4. **Breaking certifications.** Every signal change invalidates the parity certificate, the
   venue-corpus laws and the arming record's `config_id`. That is a process cost, and this repo
   charges it correctly.
5. **Rebuilding the risk layer.** Not proposed, and it should not be: it is the part with the
   live evidence behind it.

## 12. Exact files and functions that would change (for step 2 and the §8 seam only)

| file | change |
|---|---|
| `mql5/MIDASTOUCH/MidastouchAI.mq5` | new counters at the four silent `return`s (`BarEvaluateSignal` 1701/1711, `OnTick` 2575/2640/2643); `DiagMaybeWrite()`/`DiagSnapshot()` extended with the class + ATR tercile; `HudUpdate()` line to name the top rejection class. **No signal, size or protective rule touched.** |
| `scripts/midas_decision_attribution.py` | this session's harness — extend with per-tercile and per-hour expectancy (its `by_atr_tertile` hook is already emitted) |
| `scripts/morning_status.py` | report the live class census beside `NOFILLSUM` |
| `tests/` | pin the new counters' grammar; keep the census-vs-engine cross-check as a test so the offline attribution cannot drift from the engine |
| **not** touched | `src/gold_prop/`, the governor, execution, sizing, ledger writers, parity — the certified spine |

---

## 13. The 30-phase list, dispositioned honestly

**Done and measured:** 1 (forensic audit — §1–2, with line numbers), 2 (strategy validation, §3),
23 (baseline — the v1.26 certificate *is* the baseline), 24 (OOS — the repo's own pre-registered
split; the 30-fold walk-forward with PBO already ran and says NOT VALIDATED), 26 (no parameter
explosion — nothing added), 27 (acceptance criteria — restated as *decidability*, §7), 30 (this
report).

**Already measured by this program, before the request:** 12 (ATR vs structural stops —
`GOLD_PREREG_DERIVED_STOP`, `GOLD_TIGHT_STOP_TEST`), 13 (targets/partials/trailing —
`GOLD_EXIT_FAMILY_AND_HARD_SWITCH`, `GOLD_EXIT_CAPTURE_AND_FILTERS`, `GOLD_PREREG_NO_TARGET`),
19 (no unsafe online learning — nothing learns online; the engine is deterministic by charter and
by parity test), 20 (gold execution spec — `DollarPerUnitPerLot`, `SPEC` rows, the venue's own
self-inconsistency recorded), 21 (sessions — `GOLD_SESSION_HOURS_EA` + the frequency-axes study),
22 (news/extreme conditions — `GOLD_NEWS_SENSITIVITY`, `GOLD_NEWS_WIDTH`, the fail-closed
stand-down), 25 (robustness to costs — `GOLD_COST_SENSITIVITY`).

**Blocked on data, and that is a finding rather than a delay:** 3, 4, 5, 6, 7, 8, 9, 10, 11, 14,
15, 16 (partly done — the counters exist), 17 (done offline this session; the live counterpart is
§12), 18 (regime-tagged performance — the tags can be added, the cells cannot be decided).

**The one sentence that matters.** This EA is **not structurally too rigid**; it is **structurally
thin and statistically underpowered** — one setup family, three conjunctive legs of which one is
unproven and one is expensive, measured on eight months of one instrument. The upgrade that would
actually change its future is **more of the venue's own history**, followed by an *adaptive risk*
layer and by adding setups **one pre-registered study at a time** — not a rebuilt decision engine
on data that cannot tell the difference.

---

## Appendix — provenance of every number above

| measurement | source | self-check |
|---|---|---|
| conjunction census, 8-mode ablation, counterfactuals | **NEW**: `scripts/midas_decision_attribution.py`, `artifacts/midas_decision_attribution_20260922.json`, pre-registered in `docs/DECISION_ATTRIBUTION_PREREG_20260922.md` | reproduces the pinned venue-corpus law `wfv = 56 / +15.9352R`; **0 census/engine disagreements** across all 8 modes on both spans (trigger presence, macro state, session hour, every trade) |
| live class census (50 signal bars: 70 % no trigger) | the arm's own ledger, `STATE` rows, field-verified against `StateRowWrite()`'s format string | first attempt read the wrong fields (98 rows / 84.7 % "agree") and was discarded as a lookalike; the corrected read dedupes by signal bar |
| frequency axes (window, threshold) | `docs/FREQUENCY_AXES_PREREG_20260922.md` | pinned law reproduced before the table |
| WFO verdict, PBO, V1–V7 | `docs/GOLD_WFO_EA_VERDICT_20260921.md`, `artifacts/gold_wfo_ea.json` | the harness's own protocol sha is in the artifact |
| rule complementarity (no second independent rule) | `docs/GOLD_RULE_COMPLEMENTARITY_20260921.md` | 24 configurations, all same-direction |
| silence sites | source lines, quoted in §2 | line numbers read from the file at `mql5/MIDASTOUCH/MidastouchAI.mq5` (v1.26) |

**No EA build was changed by this audit.** The deployed v1.26 binary is untouched: this session
produced one new measurement harness, one pre-registration, this report, and no change to any
signal, size, protective rule or ledger writer.
