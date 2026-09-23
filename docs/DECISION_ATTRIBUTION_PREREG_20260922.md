# Pre-registration — decision attribution: which leg of the entry conjunction earns its keep?

**Written 2026-09-22, before the sweep it governs was run.** Numbers live in
`artifacts/midas_decision_attribution_20260922.json` and in §Results (appended after).

## The question, and why it is the first one

The arm is armed, flat and has taken one trade. Every protective gate reports **zero** refusals
(`session/friday/spread/riskcap/brk/news = 0` in the live census), so inactivity is **not**
excessive filtering by the risk layer — it is the entry rule's own conjunction not occurring.
The armed mode `REVERSE_DIRECTION` requires, on the same closed M15 bar:

1. a **trigger** — BB(20, k) touch-back-inside, ELSE RSI(14) ≥ 70 / ≤ 30; and
2. the **H1 and H4 EMA20 regime anti-aligned with the trigger** (`mac == -trigger`); and
3. the bar's **server hour inside the session window**.

Three legs, one conjunction, ~0.77 entries/day on the venue's bars. The question this study
answers is not "how do we trade more" but **which of the three legs carries the expectancy**,
because a leg that carries nothing is a frequency cost paid for nothing, and a leg that carries
something must not be touched. That is the whole of "is the logic structurally too rigid":
measured, per leg, rather than asserted.

## What is measured, on what, with which engine

- **Corpus:** `data/forex/xauusd/*_upcomers.csv` — the venue's own bars (the market the EA
  trades), shifted into true UTC by each window's pinned offset, through
  `midas_parity.python_build_data(corpus="venue")`. Span: **2026-01-12 → 2026-09-18**, 16,224
  M15 bars, two clock eras (+60 / +120).
- **Engine:** `midas_sweep.run_mode`, called **unchanged** — every keyword at its certified
  default. Nothing here is a re-implementation: the mode axis is the engine's own
  (`MODES`, 8 values), and the trigger and macro are read from the arrays the engine reads.
- **Windows:** the repository's own pre-registered split — select on `wf`, report on `oos`.
  Nothing here is selected; the study reports all 8 modes on both spans.
- **Self-checks, and they are binding:**
  1. The harness must first reproduce the pinned venue-corpus law `wfv` = **53 trades /
     +14.256R** (`tests/test_midas_minlot_veto.py`), or it exits without printing a table.
  2. The **census must agree with the engine's own trades**: for every trade the engine reports
     across all 8 modes, my independently-walked census must place a trigger and a macro state
     consistent with that trade's own `mac` field and direction. A census that disagrees with
     the engine is a lookalike and the run is void. (The census walks bars independently of
     position occupancy, which is the point: it counts **candidates**, the engine counts
     **fills**.)

## The three measurements, fixed in advance

**A. The conjunction census (Phase 1 / 17).** Over every *evaluable* bar in each window —
in-window, ≥21 bars of history on all three timeframes, `stop_d > 0` — count: no trigger;
trigger with macro **agreeing**; trigger with macro **anti-aligned**; trigger with macro
**divergent** (`mac == 0`); and how many of each fall inside the session window. Reported as
counts and as shares of evaluable bars, split by UTC hour and by H1-ATR tercile.

**B. Leg ablation (Phase 2 A–H).** The 8 modes on both spans: entries, entries/day, share of
days with no entry, expectancy R, profit factor, win rate, max drawdown R. Read as marginal
value per leg:

| comparison | isolates |
|---|---|
| `TRIGGER_ONLY` vs `ORIGINAL` | what the **agreeing macro leg** costs/adds |
| `TRIGGER_ONLY` vs `REVERSE_DIRECTION` | what the **anti-aligned macro leg** costs/adds |
| `MACRO_ONLY` vs `REVERSE_TRIGGER`/`REVERSE_BOTH` | whether the trigger leg adds anything to a macro-only rule |
| `ORIGINAL` vs `REVERSE_DIRECTION` | whether the **sign** of the relationship is a real asymmetry or a coin the search fixed |
| `LONG_ONLY` vs `SHORT_ONLY` | side asymmetry |

**C. The counterfactual on the refused class.** The armed mode's refused rows are not
unmeasurable: `ORIGINAL` accepts exactly the trigger bars whose macro *agrees* (the armed mode's
mirror image), and `TRIGGER_ONLY` accepts both plus the divergent-macro ones. Their OOS
expectancy is the **price of the alignment requirement**, measured rather than assumed.

## The rule, fixed in advance

- **Selection/report split:** `wf` for anything that looks like a choice, `oos` for the claim.
- **A leg earns its keep ONLY IF**, on `oos`, removing it **loses ≥ 0.05R of expectancy per
  trade**. Otherwise the leg is a **frequency cost with no measured expectancy contribution**,
  and the finding is reported as exactly that.
- **No mode is "selected" here.** This study cannot change the armed mode: a mode change moves
  the certified configuration and must go through the pre-registration → parity → arming-record
  path like every other strategy change. What this study produces is the **evidence that would
  justify opening that path**, plus the count of what each route costs.
- **A leg that fails the test is not deleted here either.** The output is a verdict per leg:
  `CARRIES` / `COSTS WITHOUT PAYING` / `UNKNOWN (underpowered)` — the last being the honest
  answer whenever the sample cannot decide it, which on 8 months of one instrument will often
  be the case and must be said in those words.

## Disclosures before the numbers

- **The data cannot support a per-regime tribunal.** 8 months, 16,224 M15 bars, ~0.7 fills/day:
  a 7-class regime model × 6 setup families would produce cells with a handful of trades each.
  The tercile and hour splits below are **descriptive contexts, not regimes**, and the required
  sample for any claim about a cell is computed and printed beside it (`t` and the n needed for
  t ≥ 1.5), so an undecidable cell reads as undecidable rather than as a result.
- **Terciles are computed over the whole corpus** (an ex-post description of volatility, not a
  classifier that could have been known live). A tradable volatility gate would have to be
  built from trailing information and pre-registered separately.
- **Occupancy contaminates the mode differences.** A mode with more candidates holds positions
  more often, and a bar skipped while a position is open is not a refusal by the rule. The
  census (A) is occupancy-free; the mode table (B) is not, and the artifact says so per row.
- **Fills are at the next M15 open with the venue's spread, `sl_atr_mult = 2.0`, `tp = 2.0R`,
  06–20 UTC, account basis** — the armed geometry, unchanged, because the question is about the
  entry conjunction and not about the exit.

## What would make this study wrong

If the census and the engine disagree on any trade (check 2), or if a mode's advantage shows up
only in `wf` and vanishes in `oos` (the signature of a searched sign), or if the refused class's
counterfactual edge comes entirely from trades the min-lot veto should have refused (`vetoed`
is printed per cell).

---

# Results (appended after the run)

**Both self-checks passed before the table was printed.** The pinned venue-corpus law reproduced
(`wfv REVERSE_DIRECTION: n=56 totalR=+15.9352 vetoed=0`, the value re-pointed 2026-09-22 when the
trigger threshold became part of the contract), and the census agreed with the engine on
**every** trade of **all 8 modes on both spans** (`n_disagreements = 0`). The census is therefore
the engine of record's arithmetic, walked independently.

Artifact: `artifacts/midas_decision_attribution_20260922.json` · Harness:
`scripts/midas_decision_attribution.py` · Pinned by `tests/test_decision_attribution.py`.

### A. The conjunction — held out (`oos`, 2026-04-01 → 2026-09-16, 6,673 in-session bars)

| class | bars | share |
|---|---|---|
| no trigger fired | 5,516 | **82.66 %** |
| trigger, macro divergent | 353 | 5.29 % |
| trigger, macro agreeing (`ORIGINAL`'s class) | 301 | 4.51 % |
| trigger, macro anti-aligned (**armed** mode's class) | 503 | 7.54 % |

The per-hour table is flat (380–420 of every 480 bars per hour carry no trigger) and the ATR(H1)
terciles differ by little (anti-class 281 / 329 / 345 across low / mid / high). **The binding
rarity is the trigger, and it is the trigger by design.**

**The live record agrees, from its own ledger:** of the **50 distinct signal bars** the armed arm
has evaluated, **35 (70 %)** had no trigger, **5 (10 %)** were the anti-aligned class, and 10
(20 %) fell outside the session window. (The first read of those rows used the wrong field
indices and produced 84.7 % "agreeing" — it was discarded as a lookalike and the corrected read
dedupes by signal bar.)

### B/C. The leg ablation and the counterfactuals

| mode | oos n | /day | zero days | expR | pf | win | DD(R) | t | n for t≥1.5 |
|---|---|---|---|---|---|---|---|---|---|
| **REVERSE_DIRECTION (armed)** | 127 | 0.75 | 41.4 % | +0.0355 | 1.074 | 0.433 | 6.3 | +0.39 | 1,931 |
| ORIGINAL (macro agrees) | 136 | 0.81 | 34.3 % | +0.0105 | 1.011 | 0.426 | 5.9 | +0.12 | 22,878 |
| TRIGGER_ONLY (no macro gate) | 217 | **1.28** | **29.0 %** | +0.0112 | 1.012 | 0.442 | 13.3 | +0.15 | 20,249 |
| REVERSE_TRIGGER | 215 | 1.27 | 29.0 % | +0.0430 | 1.085 | 0.419 | 14.9 | +0.59 | 1,373 |
| MACRO_ONLY | 221 | 1.31 | 29.0 % | +0.0082 | 1.006 | 0.394 | 17.4 | +0.12 | 37,765 |
| SHORT_ONLY | 77 | 0.46 | 59.8 % | +0.0974 | 1.212 | 0.494 | 4.2 | +0.79 | 279 |
| LONG_ONLY | 64 | 0.38 | 66.9 % | −0.0290 | 0.925 | 0.375 | 6.9 | −0.22 | — |
| REVERSE_BOTH | 233 | 1.38 | 29.0 % | **−0.0941** | 0.792 | 0.433 | 28.6 | −1.43 | — |

Selection span `wf`, same cells: RD +0.2846 (n=56), ORIGINAL +0.2510, TRIGGER_ONLY +0.0183,
REVERSE_TRIGGER +0.2092, MACRO_ONLY +0.1759, LONG_ONLY **+0.3136**, SHORT_ONLY +0.1791,
REVERSE_BOTH −0.1174. `vetoed = 0` in every cell.

### The four verdicts the rule selected

1. **The macro-alignment leg: COSTS WITHOUT MEASURABLY PAYING.** Removing it buys **+70 %**
   fills (0.75 → 1.28/day, zero-entry days 41.4 % → 29.0 %) for **−0.0243R**, which is
   **Welch t = +0.21** — unmeasurable at either sample — and costs **+7.0R of max drawdown**
   (6.3 → 13.3). Against the pre-registered 0.05R bar the leg **fails**; against a drawdown
   criterion it is the most valuable thing in the file. Both readings are true and neither may be
   quoted alone.
2. **The trigger leg: THE BINDING RARITY, 82.66 % of in-session bars.** Nothing is filtered
   out here — the condition simply does not occur. Any frequency work has to change *this* leg or
   add a second setup, and adding a second setup is a pre-registered study, not an edit.
3. **The reversal premise: NOT ESTABLISHED.** The armed mode's premise (enter against the H1/H4
   regime at M15 extremes) beats its mirror image by **+0.0249R, Welch t = +0.19**. Its support
   comes from `wf` (+0.2846 vs +0.2510) — the span the configuration family was searched on.
4. **UNKNOWN, and it must be said in that word.** No cell on this corpus is decidable: the best
   t is +0.79 (`SHORT_ONLY`) and the best required sample is **279 trades ≈ 1.7 years** at that
   mode's own 0.46/day. At the armed configuration's own frequency, deciding its expectancy at
   t ≥ 1.5 needs **1,931 trades ≈ 7.0 years of this market**; `TRIGGER_ONLY` needs 43 years and
   `MACRO_ONLY` 79. `LONG_ONLY`, which looks best on `wf` (+0.3136), is **negative** on `oos`
   (−0.0290) — the span flip that the pre-registration named in advance as the way this study
   would be wrong, observed on the long side.

### What this is not

Not a mode change and not a validation. No line of the EA was changed by this study, and the
pre-registration's rule stands: nothing here selects a configuration — it prices the legs so the
pre-registration → parity → arming-record path can be opened knowingly, or not at all.

