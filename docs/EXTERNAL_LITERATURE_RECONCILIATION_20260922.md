# EXTERNAL LITERATURE RECONCILED AGAINST THIS ARM — 2026-09-22

**The three papers named in the review packet, plus six more by the same author, read against our
own measurements.** Where they agree, where they contradict us, and where they contradict the
30-phase wish-list this program was handed.

## 0. Provenance, and the limits of what was read

| | |
|---|---|
| series | S. Mahadzva (2026), **"The Deflated Alpha Series"**, working papers 1–10, SSRN · DOIs `10.2139/ssrn.7430758` (P1), `7430898` (Fibonacci), `7430998` (ICT/SMC), `7431518` (gold↔AUD divergence), `7434881` (calendar), `7434900` (COT/carry), `7435081` (momentum/session), `7435180` (OU half-lives vs Bollinger) |
| **status** | **preprints, single author, not peer-reviewed** — the same caveat their own paper levels at the ICT material. Reconciled as *evidence*, never as authority |
| what was read | **the full abstracts via Crossref metadata** (`api.crossref.org/works?filter=orcid:0009-0001-1754-4472`, 9 items retrieved) |
| what was NOT read | **the full texts.** SSRN serves HTML and PDF behind a bot challenge (403 to `read_url`; a proxy returned the challenge page; a real Chromium tab did not clear Cloudflare). Every claim below is therefore an **abstract-level** claim, and details of their designs that an abstract omits cannot be checked here |
| their protocol | pre-registered, cost-realistic, **anchored walk-forward + locked holdout + permutation test against a random-entry null + Deflated Sharpe corrected for the program's full trial count (7,708) + a walk-forward-efficiency band** — the same family of tests this repository's `quant-validation` skill demands |
| their universe | **G10 FX majors (EURUSD, GBPUSD, USDJPY, AUDUSD) plus a metals/gold comparison**, M5→D1, 2018→Sep 2026 — *not* our venue, *not* our instrument's tick data |

---

## 1. The reconciliation, paper by paper

| # | their finding (abstract) | our measurement | verdict |
|---|---|---|---|
| **OU vs Bollinger mean reversion** (`7435180`) | A **matched free-direction Bollinger rule** is *near breakeven and nothing more*: pooled **+0.022R over 2,231 OOS trades**, **−0.044R over 1,833 holdout trades**, DSR ≈ 0.00 everywhere; the theoretically-motivated OU-conditioned version is **worse** (−0.536R OOS, pooled). Both canonical paradigms (trend and reversion) fail on this universe. | Armed `REVERSE_DIRECTION`: **+0.0355R over 127 OOS trades, t = +0.39**, DSR-equivalent nowhere near significance; `TRIGGER_ONLY` +0.0112R; every mode's required sample for t≥1.5 is 279→∞ trades. | **AGREES, POINT FOR POINT.** Their 2,231-trade pooled estimate lands 0.013R from our 127-trade one. Two independent programs, different instruments, same conclusion: **this rule family is a null at intraday resolution.** The most useful thing here is that *our* small sample is consistent with *their* large one — which is the strongest external support available for our "insufficient evidence" verdict. |
| **Paper 1: MA crossovers, Bollinger reversion, Donchian breakouts** (`7430758`) | 45 strategy×symbol×timeframe combinations, **zero clear all three gates** (permutation, DSR @ 7,708 trials, positive holdout). Best: positive WF expectancy, **fails permutation, DSR 0.00, loses money on holdout**. Robustness checks rule out trial count, sample size and non-normality as the cause. | Our own 144-configuration WFO: declared cell **t = +1.07** vs 1.96; selected path **t = +2.00 vs a 3.573 threshold**; PBO 0.186; **23 of 29 folds changed their pick**. | **AGREES.** Independently, retail technical rule *families* do not survive multiple-testing correction. It also endorses the specific number our skill uses (their 7,708-trial DSR correction vs our 168-trial max-\|z\| table). |
| **ICT/SMC: sweeps, CHoCH, FVG** (`7430998`) | No evidence the concepts work as taught. **Three independent liquidity-sweep mechanisms agree across 65 of 66 fold-selections that a swept level predicts CONTINUATION, not the reversal.** A fourth (CHoCH+FVG) finds the textbook reversal read must be **faded**. Also: a strategy's real R edge can be **smaller than the fixed per-lot commission its own tight-stop sizing forces** (repaired by a **minimum-stop-distance floor**), and an order-block implementation bug **invisible to every statistical gate** was caught only by a human reading a chart. | Our armed mode enters **with** the H1/H4 regime at an M15 extreme (a pullback-continuation, not a reversal fade) and is our best class; **`REVERSE_BOTH` — the counter-macro fade — is −0.0941R with 28.6R drawdown, negative in both spans.** Our min-lot floor sets the real risk at **$41.31 = 0.165%** of equity instead of the declared 0.25 %. | **AGREES with our strongest negative and our structure**: continuation-with-structure is worth keeping, the fade is worth never enabling. **ADDS A TESTABLE REPAIR** (a cost-based minimum stop distance — §3.2). **WARNS US** that 1,525 green tests are not a chart check. |
| **Gold↔AUD structural divergence** (`7431518`) | Their program's **strongest single result**: comparing **gold's swing structure against AUD's** clears permutation significance, achieves their **maximum post-correction DSR**, holds on a locked holdout, and **survives a 100× cost increase**. But it **fails their walk-forward-efficiency gate**, rests on a **shorter price history**, and a fresh reproduction **fell short of the original magnitude**. | **Untested here.** This repository has never tested a cross-asset structural signal; the only cross-rule study it ran (`GOLD_RULE_COMPLEMENTARITY`) tested two *gold-only* rules and found them the same trade (ρ ≈ 0.55, 100 % same direction). | **UNTESTED — and it is the only direction in the series with a surviving result.** It is also the one hypothesis that *adds information instead of adding parameters*, and it speaks to gold specifically. Registered as candidate #1 (§3.1). Their own caveat is our situation too: **short history**. |
| **Fibonacci "golden pocket" + confluence** (`7430898`) | Fading the textbook continuation works weakly (+0.041R over 1,885 OOS trades, p = 0.104). **Confluence with round numbers / moving averages makes it WORSE**: sample cut ~6×, fold-level directional consistency falls (87.5 % → 77.8 %), and the pooled mean **flips from +0.041R to −0.054R (p = 0.754)**. Their named mechanism: a **selection-bias trap where rare combined conditions win folds on a handful of lucky trades**. | We have never built a confluence or confidence layer — and the request's Phases 9/10 propose exactly that. Our own version of the same trap is already visible: `LONG_ONLY` looks best on the search span (**+0.3136R, t 1.60**) and is **negative** held out (−0.0290R). | **CONTRADICTS THE REQUEST.** The one measured attempt at evidence-combination in the literature *degraded* the signal it was layered onto. Our `LONG_ONLY` flip is the same failure at n=95. |
| **Session microstructure, opening-range breakouts, momentum** (`7435081`) | Opening-range breakouts: **all four combinations lose money** out-of-sample and on holdout, win rates 5–26 pp short of their own breakeven. VWAP/EMA pullback: near-misses (USDJPY H1 +0.266R, p = 0.063) that **reversed to −0.156R on holdout**. Cross-sectional momentum: uniformly negative, **worse at faster timeframes**. Volatility breakouts: four near-significant, **all rejected** by the full stack (three lost 4–30 % on holdout; WFE 1.6×–2.9× their ceiling). **Zero of ~46 combinations clear their bar.** Also documents a multi-leg **portfolio-accounting pitfall** (siloed per-leg sizing produced a −290 % drawdown reading no margined account could sustain). | Our trigger is a **band-extreme reversion**, not a breakout, and our measured frequency problem is on the *reversion* side. We have **no multi-setup engine** — the request's Phase 11 (four paths) would create exactly the siloed-sizing hazard they document. | **CONTRADICTS THE REQUEST'S BREAKOUT AND MOMENTUM PATHWAYS** (A: trend continuation, C: breakout confirmation) on a comparable intraday FX universe. **ADDS A DESIGN WARNING** for any multi-path engine: one sizing authority, not per-path. |
| **Calendar/seasonality** (`7434881`) | Of 96 (symbol, month, lookback) combinations, four clear a bar; the tradeable version rests on **13–18 trades per specification** and is called underpowered by its own author. The cautionary finding is the important one: adding a **five-level weekday filter as a free walk-forward dimension** made a fold-level optimiser "discover" Monday as informative — **when Monday is the worst-performing weekday in the honest sample.** | We moved **two** free dimensions this year (session window, trigger threshold k) — but **pre-registered both, selected on `wf`, and reported on a held-out span**. The `k` move survived (0.63→0.77/day, −0.003→+0.087R); the window move favoured the live frame on both spans. | **AGREES with our method and WARNS about our next step**: every added free dimension invites exactly this. Their meta-pattern — "naive, textbook-obvious technical and calendar narratives run backwards in this data" — is a reason to be *more* suspicious of the 30-phase list, not less. |
| **COT positioning and carry** (`7434900`) | Six COT methodologies: **all negative** (best p = 0.549, DSR 0.00). Carry after costs: negative, but the free-direction parameter settled on the theoretically correct sign. Their conclusion: exploitable information, if any, is **in faster, structurally-revealed features of price** — not in slow public survey/macro data. | Consistent with our design (price-only, no external data), and with our own measured negative for the news-stand-down as a *filter* (it changes no entry rule here). | **AGREES with our architecture.** It is an argument *against* adding external-data layers and *for* price-structure work — if any. |
| **Currency-crisis fragility** (`6233818`, outside the series) | Unconditional prediction fails (AUC 0.53); a **conditional interaction** under global stress is significant (2.4× crisis risk, p < 0.05), and the conditional mechanism generalises while the unconditional one does not. | Our macro-alignment leg is a conditional filter whose *expectancy* contribution is unmeasurable (+0.024R, t = 0.21) but whose *drawdown* contribution is large (6.3R vs 13.3R). | **SAME SHAPE**: conditioning changes the risk profile far more convincingly than it changes the mean. It is external support for keeping the macro leg while refusing to claim it as edge. |

---

## 2. The four sentences worth carrying

1. **The null is now externally corroborated at a sample we will never reach.** Their matched
   free-direction Bollinger rule: **+0.022R over 2,231 OOS trades**. Ours: **+0.0355R over 127**.
   Their verdict is "no"; ours is "not yet decidable". Both are the same finding, and ours is the
   one a 30-trade prop gate will never resolve.
2. **Confluence, confidence scores and rare-condition filters are measured to make things worse**
   (+0.041R → −0.054R when confluence is added; rare conditions winning folds on lucky trades) —
   which is a direct external contradiction of Phases 9 and 10 of the request.
3. **Breakout, momentum and ICT/SMC additions are measured not to work as taught** on a comparable
   intraday FX universe — a direct external contradiction of Phases 7 and 8, and the sweep study
   specifically says a swept level predicts **continuation**, i.e. the reversal-fade family is the
   side to avoid (which our own `REVERSE_BOTH` result already said at −0.094R).
4. **Their one surviving result is gold↔AUD structural divergence, and its stated weakness is
   exactly our weakness: short history.** They also needed a **locked holdout** to find that their
   reproduction fell short — another argument for the forward record this arm is already running.

## 3. What changes here (ranked, and nothing is run yet)

### 3.1 Pre-registration candidate #1 — cross-asset structural divergence (gold ↔ AUD)
The only hypothesis in the series with a surviving result, on **gold**, and it *adds information
rather than parameters*: swing structure in gold compared against swing structure in AUDUSD. It has
never been tested in this repository. What it would require: an AUDUSD series of record (the venue
serves it), a **non-repainting** swing definition fixed in advance (the request's Phase 5 is right
about that requirement), the same walk-forward + holdout + permutation treatment, and the same
required-sample column beside every cell. **This is now the single best-justified new hypothesis in
the file** — and it is *not* a new setup family bolted into the EA; it is one signal, testable
offline, before any MQL5 line is written.

### 3.2 Pre-registration candidate #2 — a cost-based minimum stop distance
Their repair for "the R edge is smaller than the commission the tight stop forces": a **minimum
stop-distance floor**. Our engine already models commission ($10/lot round-turn) and spread, and our
own stop studies show the pathology's neighbourhood from the other side — the tight-stop candidate
(0.694×ATR) had the **highest mean (+0.6031R) and the worst dispersion (sd 4.38)**, and was
**`POSITIVE, UNDERPOWERED | does not clear the program-wide hurdle`**. A stop floor is a *refusal*
rule, not a geometry optimisation: it needs one pre-registered study, and it interacts with our
min-lot problem (§3.3) in a direction we can predict.

### 3.3 The min-lot interaction, now externally named
Their cost finding and our live fill are the same story from two sides: at 0.01 lots the venue's
minimum sets the risk (**$41.31 = 0.165 %** of equity, not the declared 0.25 %), and a wider stop
raises that floor further while a tighter one runs into cost. Their literature says the repair is a
stop *floor*; our arithmetic says the same thing from the sizing side. Worth one pre-registered
study that measures both ends together instead of separately.

### 3.4 One methodological import: walk-forward efficiency
Their acceptance band (≈1.0–1.6 acceptable, 2.08 fragile, >2.5 rejected) is a check this repository
does not have, and it **caught results their p-values passed** — including their own flagship. It is
cheap to add to `gold_wfo_ea.py`/`gold_walkforward.py` beside V1–V7, and it is exactly the kind of
check that would have flagged our `LONG_ONLY` `wf`/`oos` flip before a human noticed it.

### 3.5 One operational import: a chart check that is not a test
Their bug — invisible to every statistical gate, caught by a human looking at a chart — is an
argument for the HUD and the `STATE` row being treated as *validation artifacts*, not decoration.
Our v1.21–v1.26 defects were all found by exactly that method (the operator's screenshot found the
`vEq` freeze; the ledger row found the entry-price zero). That practice should be named in the
protocol rather than left as an accident of this week.

## 4. What this reconciliation does NOT license

- **It does not arm, disarm, or change the EA.** No code was touched; the armed configuration and
  every certificate stand.
- **It does not transfer their findings to our market.** Their universe is G10 spot FX majors on
  broker quotes; ours is XAUUSD on this venue's ticks, where the spread, the min lot and the clock
  are all different. Their numbers are *reasons to test*, not results we may quote.
- **It does not make the papers evidence of record.** They are preprints, read at abstract level,
  with full texts unreachable from here. Nothing above may be cited as proof of anything in this
  repository's gates; the pre-registered studies in §3 are what would produce evidence.

## 5. The bottom line, restated with the outside world in view

Our own audit said the constraint is **data**, not design, and that the request's
six-families/seven-regimes/confidence-score direction multiplies hypotheses against eight months.
The external series says the same thing with a bigger sample and harsher arithmetic: **45 retail
rule combinations, zero surviving; ~46 intraday momentum/breakout combinations, zero surviving;
confluence and rare-condition filtering *degrading* what they were added to; and one surviving
result that rests on cross-asset structure and is admitted to be short-history fragile.** The most
valuable thing this reconciliation produced is therefore **not** a new direction to build — it is
the confirmation that the two candidate directions worth pre-registering (cross-asset structure, and
the cost/stop-floor economics) are the ones that add *information*, not parameters.

---

### Appendix — reproduction of this reconciliation

```
curl "https://api.crossref.org/works?filter=orcid:0009-0001-1754-4472&rows=20&select=title,abstract,DOI,issued"
curl "https://api.crossref.org/works?query.bibliographic=Mahadzva+deflated+Sharpe+Bollinger+G10+spot+FX&rows=5&select=title,abstract,DOI,issued"
```

Both return the abstracts quoted above; the SSRN landing pages for the same DOIs return a Cloudflare
challenge to automated fetch. Any claim in this document that is not in an abstract is marked
UNTESTED HERE, and no number in it was taken from a source this repository cannot re-query.
