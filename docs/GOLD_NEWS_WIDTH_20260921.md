# Is the news stand-down real, and is ±15 minutes the right width? — measured 2026-09-21

Three questions, one instrument (XAUUSD M15), all of them answered against the venue's own bars
and its own calendar. Companion to `docs/GOLD_NEWS_SENSITIVITY_20260921.md`, which measured what
the rule costs in R; this one asks whether the rule is measuring anything at all.

| question | answer |
|---|---|
| does the +3.36R survive an extended window? | **It cannot be tested yet** — the venue has supplied 42 new bars (0.4 days) and **zero** new complete folds. The same analysis shows +3.36R is **carried by a single 8-day fold**: drop F04 and the total is **−0.41R**. |
| re-run the walk-forward with the rule baked into the selection, pre-registered | **Done, and it fails its own P1: the grid selected a different configuration in F04.** Verdict **REJECTED** — an amendment to certify, not a filter to enable. |
| should the blackout be wider or narrower than ±15 minutes? | **Neither, on this evidence.** With a horizon- and hour-matched baseline, the move across a ±15 min blackout is **1.02× ordinary**, and **10% of releases** exceed the same-horizon p90 — exactly the rate a no-effect window produces. The response does not peak at any lag, which rules out the clock as the explanation. |

---

## 1. Extending the window: not yet possible, and the fold attribution answers it anyway

`scripts/gold_news_sensitivity.py --corpus-end now` takes the corpus as it stands instead of
truncating to the certified range. In that mode the control **cannot** apply — the frozen artifact
was computed on other bars — so the harness says so out loud (`CONTROL: N/A`) rather than skipping
it, and the veto-off leg remains the reference because it is the same code on the same bars with
exactly one difference.

```
corpus   : 16266 bars  2026-01-12 13:15 UTC .. 2026-09-21 10:15 UTC   [--corpus-end now]
           vs frozen: +42 bars (0.4 days), folds 31 -> 31 — NO new complete fold
```

Folds are 8 days from the default's own first scorable bar, so an extension produces evidence only
when it completes one: **the next scorable fold boundary is 2026-09-30 13:15 UTC**, i.e. the
question "does it survive outside the frozen window" becomes answerable in about nine days, and not
before. Reporting a delta on 42 bars as if it were a second window would be exactly the kind of
claim this program exists to refuse.

What *can* be answered now is which part of the window the finding lives in, and the harness reports
it with every delta:

```
== leave-one-fold-out: does any single fold carry the whole delta? ==
  drop F03: total +4.841R (that fold carries -1.477R = 44% of the delta)
  drop F04: total -0.414R (that fold carries +3.778R = 112% of the delta)
  drop F30: total +2.301R (that fold carries +1.063R = 32% of the delta)
```

**Three folds of thirty moved. One fold carries 112% of the delta, and removing it flips the sign.**
The honest reading is not "+3.36R, probably noise" — it is that the entire effect is a single 8-day
period, in the fold where the rule changed which configuration the walk-forward selected. That is a
far weaker claim than the headline number suggests, and it is the one the artifact now carries
(`fold_attribution`).

## 2. The pre-registered amendment

The veto is applied while the walk-forward *selects*, so it can change the chosen configuration —
which is what F04 shows. That is a strategy change, and a strategy change cannot be accepted on the
strength of the window that certified the unamended strategy. So the run is pre-registered:

```
python scripts/gold_news_sensitivity.py --preregister
```

The declaration is written **before any leg is computed**, to
`artifacts/gold_news_preregistration.json`, carrying:

- the question and the hypothesis ("the veto is an entry filter, so every fold selects the same
  configuration as the certified run and only the entry set moves");
- the decision rule **P1** (no fold's selected configuration changes), **P2** (no leg pass is lost),
  **P3** (delta R is positive on the certifying window), and the verdicts they imply;
- a **SHA-256 over the protocol** — `gold_walkforward.py`, this harness, the grid, the fold
  constants, the cost model and the frozen artifact's own spec and checks. If the protocol moves
  after the declaration, the harness **refuses to run** rather than re-interpret the expectation,
  and the run is appended to the declaration (never overwritten) with its measurement time.

Result, on the frozen window:

```
== pre-registered verdict: REJECTED ==
   P1 picks changed: ['F04']
   P1: the selection changed in F04 — the rule altered the strategy's own configuration search,
       so this is an amendment to certify, not a filter to enable
```

The guarantee is procedural, not cryptographic: the digest pins the protocol and the timestamps
order the steps, but nothing stops a human editing the declaration file. What it does prevent is the
real failure mode — an expectation invented after seeing the result, and a protocol quietly changed
under a standing declaration.

It is not decorative. When the harness was later refactored (the fold attribution, then the
`--corpus-end` plumbing and a corrected print), the standing declaration stopped matching: the code
hashed to `16a8c7b4…` against the declared `c398b043…`, and the harness refused to run at all until
the declaration was deleted and re-made. It was, and the re-declared run reproduced every number to
the digit — 568 veto-off trades reproducing `gold_wfo.json` exactly, 559 veto-on, +3.36R, F04
re-selected, **REJECTED**. A declaration about a protocol that has since changed is a declaration
about a different experiment, so refusing is the only honest response; re-declaring is cheap enough
to be the standard one.

## 3. Is ±15 minutes the right width? The event study

`scripts/gold_news_event_study.py`. Two things had to be right before any number here meant
anything.

**The baseline is horizon- and hour-matched.** The first version of this measurement compared a
60-minute move to a fixed 15-minute baseline and reported "2.40×" — which is almost exactly the
square-root-of-time scaling a random walk produces (`|60m| ≈ 2 × |15m|`). It measured the horizon,
not the release. Every move is now compared to what gold does over the **same number of bars at the
same UTC hour** across the whole corpus, so 1.00× means "indistinguishable from an ordinary window
of that length at that time of day".

**The measured move is the blackout's own footprint.** Not from an arbitrary reference close and not
"the move inside the window" — which no position could have been opened into — but the path from
the **last close the rule would have allowed before** the window to the **first close it allows
after** it. That makes the horizon a measured quantity, which is what the matched baseline needs.

### Does gold move on a HIGH release?

| half-width | median move | bars | over same-horizon p90 | n |
|---|---|---|---|---|
| ±15 min | **1.02×** | 3 | **10%** | 353 |
| ±30 min | 1.08× | 5 | 9% | 353 |
| ±45 min | 1.22× | 7 | 10% | 353 |
| ±60 min | 1.10× | 9 | 10% | 353 |

Under no effect, 10% of ordinary windows exceed their own p90. **Every width sits at the null rate.**
The aggregate response to a HIGH USD release, in this corpus, is not distinguishable from gold's
ordinary behaviour at the same hour.

### The lag sweep, which is also a clock check

| lag | 15m window | over p90 | 30m window | over p90 |
|---|---|---|---|---|
| −60m | 1.02× | 8% | 1.20× | 6% |
| −45m | 1.20× | 6% | 1.04× | 5% |
| −30m | 0.89× | 7% | 0.92× | 7% |
| −15m | 1.11× | 10% | 0.98× | 7% |
| **0m** | 0.93× | 4% | 0.95× | 8% |
| +15m | 1.03× | 12% | 1.12× | 7% |
| +30m | 0.97× | 6% | 0.94× | 7% |
| +45m | 1.01× | 9% | 0.87× | 6% |
| +60m | 0.86× | 6% | 0.73× | 6% |

Flat from −60 to +60 minutes. **This is the useful negative result:** if the calendar's epochs sat
off the venue's bars — the failure every blackout rule dies of — the response would peak sharply at
the offsetting lag and the real move would be sitting outside the window. It does not. The
alignment is consistent, and the one-bar pre-release move is **1.16×** an ordinary bar, which is
anticipation-sized, not misalignment-sized. So the null result is about gold, not about the clock.

### Which releases, if any, carry a signal

| event | n | 15m | 60m | over p90 |
|---|---|---|---|---|
| 30-Year Bond Auction | 9 | 1.94× | 0.99× | 0% |
| ISM Manufacturing PMI | 8 | 1.90× | 1.04× | 0% |
| PPI m/m | 10 | 1.76× | 2.22× | **40%** |
| EIA Crude Oil Stocks Change | 34 | 1.64× | 1.45× | **26%** |
| FOMC Press Conference | 6 | 1.53× | 1.22× | 0% |
| Unemployment Rate / Nonfarm Payrolls | 8 | 1.43× | 0.70× | 12% |
| JOLTS Job Openings | 8 | 1.24× | 1.27× | 12% |

The medians are inflated by single large events (a 1.90× median off eight observations is often one
move), and 17 of the 35 named releases sit **at or below** the 10% rate a no-effect window would
show. PPI at 40% and EIA at 26% are the only two worth a second look — and with 35 names tested at
~8–34 observations each, one or two crossing 20% is what noise alone produces. **No release here
earns a wider window on its own evidence.**

### The cost side

| half-width | capture of the ±60 min move | suppressed bars | **suppressed entry bars** |
|---|---|---|---|
| ±5 / ±10 min | n/a | 207 | 66 |
| ±15 min | 58% | 398 | **122** |
| ±30 min | 68% | 731 | 245 |
| ±45 min | 99% | 1,059 | 363 |
| ±60 min | 100% | 1,345 | 484 |

Capture is measured but should not be read as protection: a window that spans 58% of a move that is
itself ordinary is not protecting anything. The column that costs something is the last one —
suppressed bars where the engine of record's own entry conditions held inside the trading session.
**Widening ±15 → ±45 minutes triples the cost (122 → 363 entry bars) to raise the response from
1.02× to 1.22×, which is still at the null rate.**

### What pinning the measurement found

Two defects surfaced while writing the pins for it — the class of thing a headline table
hides:

**A baseline table one horizon short.** `MAX_K` was 9, and the widest footprint a release
can produce is 10 bars (a release landing exactly on a bar close spans `2 × 60 min` rounded
out to the closes that bound it: 8 bars, plus the two edge closes). One short does not
misreport — `abnormal` returns `None` and the event leaves the study. It is now derived
from the width (`2 * REF_MIN // 15 + 2`) instead of written as a literal, and a test asserts
the table covers every width's footprint, because arithmetic stated as a constant drifts.

**Dropped events with no stated reason.** The printout said the unmeasured events "lack a
full ±60 min of bars". Both of this calendar's two are something else: they sit in UTC hour
23, where the corpus holds a single bar, so the release has no ordinary history of its own
to be compared against. The refusal is right — a release judged against one bar is not a
measurement — but the study now says which of the three refusals it is (`no bars`,
`no baseline`, `no reference window`) and records the counts in the artifact
(`events_dropped`), because "unmeasurable" without a reason is indistinguishable from a bug
that discarded the event.

Neither changed a reported number: re-running after both fixes reproduces the tables above
exactly, 353 of 355 events measurable, same medians, same lag profile, same cost table.

### Recommendation

**Do not widen.** The evidence supports neither widening nor enabling on the strength of +3.36R: the
aggregate response the rule exists to avoid is not distinguishable from noise at any width tested,
and the measured cost is real. If the rule is kept at all, the defensible form is to *narrow* the
scope to releases that show a response — but selection on 35 names is multiple-comparison-fragile and
would itself have to be pre-registered and certified, not adopted. What would change the answer is
tick data: a bar-close study cannot see a 90-second spike, and this venue's real ticks begin
2026-09-04.

**One scope hazard, surfaced by the study.** The calendar file is USD-only because
`MidasNewsProbe.mq5` declares `InpCurrency = "USD"`, and the EA's gate has no currency filter at all
— it blocks any HIGH row it reads. Regenerating the probe with `InpCurrency = ""` would therefore
**silently widen the rule to every currency** without touching a preset. The file's own
`# currency=` header is the record of that; nothing enforces it yet. That is the check to add before
the gate is ever switched on.

## Reproduce

```
python scripts/gold_news_event_study.py            # section 3, artifact gold_news_event_study.json
python scripts/gold_news_sensitivity.py --preregister            # sections 1 and 2
python scripts/gold_news_sensitivity.py --corpus-end now        # the extension, when it exists
```

Artifacts: `artifacts/gold_news_event_study.json`, `artifacts/gold_news_sensitivity.json`,
`artifacts/gold_news_preregistration.json`.

Tests: `tests/test_gold_news_width.py` (the measurement's conventions: the close index, the
horizon- and hour-matched baseline, the footprint against the live mask, the 10% null rate, the
disclosed drops, the cost side) and `tests/test_gold_news_sensitivity.py` (the mask's semantics,
the control, the pre-registration and its refusal).
