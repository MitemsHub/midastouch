# Pre-registration — the Asian-range sweep continuation, recorded FORWARD with no order path

**Written 2026-09-22, before the recorder exists.** The recorder is the EA build `MIDAS1.28` plus
its python mirror; the accumulating artifact is `artifacts/sweep_shadow_forward.json`, resolved by
`scripts/midas_sweep_shadow.py`. Nothing in this document may be edited once rows exist.

## Why this exists, and what it is not

`docs/ASIA_SWEEP_PREREG_20260922.md` tested this mechanism on the venue's own bars and **refused it**:
the pre-registered primary window (UTC 13–18) failed its own bar on all three variants, so nothing was
ported. But the same run reported — clearly labelled as *descriptive only, not the pre-registered test*
— the secondary window (UTC 07–18, every hour after the Asian range is known):

| variant | oos n | expR | pf | win | t |
|---|---|---|---|---|---|
| **`SWEEP_CONT`** | **152** | **+0.1955** | **1.499** | 0.520 | **+2.21** |
| `SWEEP_FADE` | 164 | −0.1584 | 0.683 | 0.402 | −2.04 |
| `RECLAIM_REV` (the textbook ICT read) | 168 | −0.1425 | 0.706 | 0.387 | −1.82 |

That is the strongest measured number in this program. It is **not a pass**: it is the *secondary*
window, its `wf` half is essentially zero (+0.0256, t +0.18), and it is one of six cells (three
variants × two windows) that have now been looked at. **The pre-registration of the study it came
from is explicit about what comes next, and this document is that step:**

> *"the only blind test left is forward. So the recommendation is a shadow recorder, not a trader:
> have the arm log, per bar, what `SWEEP_CONT` would have done — level, direction, ASIAN range, and
> the R it would have earned — into the ledger with no order path at all, then read it after enough
> trades accumulate."*

**What this is not.** It is not arming anything, not widening a gate, not a mode change, and not a
claim that the arm will trade more. The armed configuration is untouched to the digit. This records
one hypothesis, blind, from the next bar onward, at a cost to the account of nothing.

## The mechanism, fixed here, defined once

The definition lives in **`scripts/midas_sweep.py`** (`asian_ranges`, `sweep_signals`) and in the
EA's `AsianRangeDay()`/`SweepShadowRow()`. It is the same code the published study ran, moved out of
`scripts/midas_asia_sweep.py` into the engine module so there is exactly one definition rather than
two that can drift.

- **Asian range** for a UTC day = the high and the low of the venue's own M15 bars whose **open**
  falls in **UTC hour ∈ [0, 7)** of that same UTC day. It covers 00:00–06:45 UTC and is therefore
  **fully known at 07:00 UTC**.
- **Sweep** = the **first** bar whose open is at or after UTC 07:00 that **trades beyond** the range:
  `high > range_high` is an up-sweep, `low < range_low` is a down-sweep. **One signal per UTC day per
  side**, and the bar that produced it is flagged `first`.
- **Reclaim** = a bar that trades beyond the range **and closes back inside it**. Recorded as a flag
  only; it defines the textbook reversal reading, which is the *failure* direction here.
- **`SWEEP_CONT` direction = the sweep side.** With the break. That is the only hypothesis tested.
  The two failure readings (`SWEEP_FADE` = `−side`, `RECLAIM_REV` = `−side` on a reclaim bar) are
  **derivable from the recorded row** and are deliberately not stored as extra directions, so the
  record cannot later be read as if three hypotheses had been tested.

## Non-repainting, by construction, and pinned rather than asserted

A row for the bar closing at `ct` may read **only** bars whose open is `< ct`. The range is complete
before 07:00 UTC and is never revised. `tests/test_sweep_shadow.py` pins this directly: perturbing a
later bar's high or low must not move a single earlier row. (The cross-asset study found exactly this
class of defect — a context leg read in *open* times when the signal leg used *closes*, giving the
context series one H1 bar of lookahead. It was caught by reading the code against its own claim, and
the pin here exists so this mechanism cannot repeat it.)

## The frame

True UTC throughout. The ledger's bar epochs are **server**-stamped, so every reader shifts them by
the arm's **own measured `off_min`** — the offset the EA writes into its `STATE` row beside the
`ERA` row — and the row prints `off_min` for audit. It is **never** a recomputed
`venue_offset_min(now)`: reading a server epoch as UTC is a plausible two-hour lie this repository has
already paid for, and today's DST step is the same width as the effects being measured.

## The window, and why it needs no frame argument

Eligibility is **UTC hour ∈ [7, 18)** — the sweep cannot exist before 07:00, and 18:00 is the hour the
study's secondary window ends at. This coincides exactly with the arm's own live gate
(`InpSessionStartHour=6` … `EndHour=20` compared against broker-server hours, i.e. UTC 04–18), so the
shadow's window sits entirely inside the hours the arm already evaluates and **no frame normalisation
is required for eligibility**. The frame is still printed per row, because being able to check it is
the point.

## What is recorded, by which program, into which artifact

**The EA writes the setup; python resolves the outcome.** The EA cannot know the future, and a
record that contains a claim the writer could not have measured is not evidence — so the EA never
writes an R.

- **`MIDAS1.28`, one `SWEEPSHADOW` row per evaluated bar inside the declared window** (not only on
  sweeps, so the record can show the days it did not fire — which is what a frequency claim needs),
  appended to the arm's own ledger beside the `STATE` row it already writes for that same bar.
  Fields (13):
  `SWEEPSHADOW,<write_epoch>,<sig_open>,<utc_day>,<asian_hi>,<asian_lo>,<range_bars>,<side>,<first>,<reclaim>,<stop_d>,<off_min>,<version>`
  where `stop_d` is `InpSlAtrMult × AtrNow()` — the arm's own ATR(H1) read over the last closed H1
  bars, i.e. the same value its entry path sizes from, so the certified geometry is not restated
  here but reused. **There is no separate `dir` field, and that is deliberate:** `side` is nonzero
  only on the first sweep of that day on that side, so it *is* `SWEEP_CONT`'s direction; `SWEEP_FADE`
  (= `−side`) and `RECLAIM_REV` (= `−side` on a reclaim bar) are derivable from the row. Storing a
  second identical field would let this record later read as if three hypotheses had been tested.
  **A bar outside the window, or a bar for which no offset may be named
  (`STATE_OFF_UNKNOWN`), writes no row at all** — the window and the frame are the claim, and a row
  that could not state either is not evidence.
- **No order path.** `SweepShadowRow()` is called from exactly one place, beside the existing
  `StateRowWrite()` inside `TrackFreshM15Bar()`, so the shadow rides the same evaluated bar as the
  live decision and cannot diverge from it. It contains no `OrderSend`, consults no governor, and
  increments no `g_nofill_*` counter. `tests/test_midas_v128_record.py` pins both facts.
- **`scripts/midas_sweep_shadow.py` is the resolver** (research harness; it adds no live entry
  point). It reads the ledger's rows and resolves each recorded setup to a closed hypothetical
  outcome **through the engine of record's own `run_mode`** — `mode="TRIGGER_ONLY"`, the sweep signal
  array, `win_lo=7, win_hi=18`, and every other keyword at its certified default (2.0×ATR(H1) stop,
  2.0R target, 48-bar timeout, half-spread charged on entry and exit, `SPREAD_FLOOR` when a bar
  records none). No outcome arithmetic is re-implemented: the number is the engine's.
- **Binding self-check.** The resolver must independently reconstruct the sweep signal array and
  agree with the EA's own rows on **every** recorded bar, or it exits without reporting. A lookalike
  recorder is worth nothing. It also prints, as first-class output, **coverage**: the engine's own
  count of eligible setups in the span against the number of rows the arm actually recorded, so a
  bar the terminal missed is *visible* rather than silently excluded. (Today's session lost roughly
  an hour to a terminal stop; a recorder that hides that would be lying by omission.)

## The verdict vocabulary, fixed in advance

Four words, and only four. A reader must be able to tell which one is speaking without
reading the code that chose it.

| word | means |
|---|---|
| **`ACCUMULATING`** | N < 60 resolved outcomes. The only quotable word below the target, and no interim number may be quoted alongside it. |
| **`PASS`** | all four tests below hold. |
| **`FAIL`** | one of tests 1–3 failed, and the verdict names which. |
| **`VOID`** | the recorder is measuring something else: either the EA's rows and the independently rebuilt signal array disagree on a bar, or the direction checks inverted forward. This invalidates the **recorder**, not the hypothesis, and it is a different outcome from `FAIL` on purpose. |

## The evaluation rule, fixed in advance

- **Do not look until N ≥ 60 resolved outcomes.** Below that, the honest word is *accumulating*, and
  no interim number is quotable. An interim read that crosses 60 is not permitted to become the read.
- **Then evaluate once**, and the family passes ONLY IF **all** hold:
  1. **`t ≥ 2.4`** on `SWEEP_CONT`'s forward outcomes. The program's own rule for a searched family is
     the 95th-percentile max-|z| for the family size; six cells of this mechanism have already been
     examined (three variants × two windows) and the external series searched further still, so 2.4 is
     an **understatement** of the true search and is used as the floor, not as comfort.
  2. **`n ≥ 60`** resolved outcomes and **fills/day ≥ 0.30**.
  3. **mean forward R > 0**, with the **zero-entry-day share** printed beside it. A configuration that
     averages ~0.9 fills/day but sits flat on most days is not one a prop account can be evaluated on,
     whatever its expectancy.
  4. **The two direction checks must hold in the forward record as well**: the derived `SWEEP_FADE`
     mean must be **negative** and the derived `RECLAIM_REV` mean must be **negative**. This is an
     internal-validity test no parameter search can fake: if the forward record flips the direction
     that the study and the external literature both reported, then the thing being recorded is not
     the mechanism that was measured, and the correct verdict is **VOID** rather than PASS or FAIL.
- Failing any of 1–3 is a **FAIL**, and the verdict says which. `VOID` under (4) is a different word
  and a different outcome: it invalidates the recorder, not the hypothesis.

## Disclosures, before any number exists

- **The hypothesis arrived pre-selected.** It was the surviving cell of a study that looked at six,
  on a window the study itself declined to call a test. `t ≥ 2.4` is therefore a floor. Nothing here
  can be reported as a discovery.
- **One instrument, eight months of venue history, and no multi-year depth.** The required sample for
  the *effect size* observed in the secondary window (~0.20R) is on the order of 70 trades — which is
  why a forward record is feasible at all — but the sample for a *confident* claim at the armed
  configuration's own frequency was computed at 1,931 trades ≈ 7.0 years. That number is not fixed by
  this recorder; it is the ceiling on what this program can ever conclude.
- **The base rate is against us.** Of this program's last four alternative leads — cross-asset
  structural divergence, close-anchored intraday momentum, the Asian sweep's own primary window, and
  the session-window variants — three died on this venue and the fourth is undecided at its sample.
  A reader should price this document accordingly, and this sentence is here so that they can.
- **Cost model, stated plainly.** The engine charges the half-spread on entry and on exit and
  `SPREAD_FLOOR = 0.10` when a bar records none. It does **not** charge a separate per-lot commission,
  so a venue that charges one would make every unresolved-outcome R here optimistic by that amount.
  That is a known, named limitation of the number, not an oversight.
- **Sizing is the account basis** (`ACCOUNT_BASIS_USD`), because R-multiples are lot-invariant; the
  shadow trades nothing, so no lot, no veto and no governor applies to it.

## What would make this wrong

1. **A repaint.** Any row whose value moves when a later bar is perturbed. Pinned against, and the
   pin is the first thing to re-run if a number here ever looks too good.
2. **A disagreement** between the EA's rows and the resolver's independently rebuilt signal array.
   The resolver refuses to report in that case; if it ever refuses, the recorder is the finding.
3. **A forward record whose direction checks invert** (`SWEEP_FADE` or `RECLAIM_REV` turning
   positive). Verdict `VOID`: the recorder is measuring something else.
4. **Coverage so poor that the rows are a subsample.** Printed on every run; if the arm recorded a
   minority of the eligible setups, the record describes the terminal's uptime rather than the rule.

---

# Result

**Accumulating. N = 0.** No rows exist yet. Nothing in this document may be quoted as a result until
the rule above has been satisfied in full, and the interim state is written in that one word.
