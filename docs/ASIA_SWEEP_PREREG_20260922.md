# Pre-registration — the Asian-range sweep, as a second setup family for the hours the snap-back loses

**Written 2026-09-22, before the run it governs. Results appended below §Results.**

## Why this, and why now

Step 1 refused to delete the overlap hours, and the reason it refused is the reason this study
exists: the armed snap-back earns `−0.0949R` in the 13:00–17:00 UTC overlap and `−0.0801R` in the
late tail, in a venue where the spread is **flat at 0.19–0.23 points in every hour** and where the
retail doctrine says those are the *best* hours of the gold day. Two readings are possible: the
hours are unusable, or **the rule is wrong for the hours**. The doctrine and the mechanism both say
the second — the overlap is where price **expands**, and expansion is what runs a snap-back over —
so the fix is a **continuation** setup aimed at exactly those hours, not a narrower window.

External support, from the 2026 preprint series reconciled in
`docs/EXTERNAL_LITERATURE_RECONCILIATION_20260922.md`: of six mechanically-defined ICT/SMC rules put
through a full walk-forward/permutation/holdout stack, **three independently constructed
liquidity-sweep mechanisms — swing-based equal highs/lows, real order blocks, and ASIAN SESSION
RANGES — unanimously agreed across 65 of 66 combined fold-selections that a swept level predicts
CONTINUATION, not the textbook reversal**, while a fourth mechanism found the textbook reversal read
should be faded. That is the single most corroborated positive reading in that literature, and it is
a *continuation* family — the same side our own measurements favour (our counter-structure fade
`REVERSE_BOTH` measures `−0.0941R` with 28.6R drawdown in both spans).

## The definitions, fixed in advance (deterministic, no subjectivity)

- **Asian range** for a UTC day = the high and the low of the venue's own M15 bars whose **open** falls
  in UTC **00:00–06:45** of that day. It is therefore fully known at **07:00 UTC**.
- **Sweep (break)** = the first bar at or after 07:00 UTC that **trades beyond** the range — a bar
  whose `high > range_high` (an up-sweep) or `low < range_low` (a down-sweep). One signal per day per
  side; the engine's one-position-at-a-time rule then governs actual exposure.
- **Reclaim** = a bar that trades beyond the range **and closes back inside it** — the textbook
  "liquidity sweep reversal" shape.

## The three variants, declared before the run

| variant | fires on | direction |
|---|---|---|
| `SWEEP_CONT` | the first sweep | **with** the break (the literature's reading) |
| `SWEEP_FADE` | the first sweep | against the break |
| `RECLAIM_REV` | a reclaim | against the break (the textbook reversal read) |

`RECLAIM_REV` is included on purpose as a **direction check**: the external paper reports that this
reading is the one that runs *backwards*. If our implementation reproduces that (it fares worst), it
is evidence that the harness is measuring the same mechanism rather than an accident of our code.

## The engine, the windows, and the pass rule

- **Engine:** `midas_sweep.run_mode`, unchanged except `win_lo`/`win_hi`; the variant is supplied as
  `data["m15_bb"]` — the array the engine already reads its trigger from — and the mode is
  `TRIGGER_ONLY` so the signal is tested on its own. Geometry/costs/sizing at their certified
  defaults (2.0×ATR(H1) stop, 2.0R target, account basis).
- **Windows (declared):** **primary = UTC 13:00–18:00** — the hours the snap-back loses in, which is
  what this setup is for. **Secondary, descriptive only = UTC 07:00–18:00** (all hours after the range
  is known). Selection on `wf`, report on `oos`.
- **Self-check, binding:** the pinned venue-corpus law `wfv REVERSE_DIRECTION n=56 / +15.9352R`
  reproduces before any table prints.
- **Pass rule (primary window, held out):** `t ≥ 2.4` (a 3-variant family), `n ≥ 30`, fills/day
  `≥ 0.30`, **and** the same sign on `wf`. All four, or the family is refused.

## Disclosures

- **The hours were selected by a measurement that already happened** (Step 1's buckets), and the
  *mechanism* was in the pre-registration of that step before these numbers existed. The variant
  definitions above are new and are fixed here for the first time.
- **8 months, one instrument.** `t ≥ 2.4` on ~60-90 trades in a 5.5-month holdout is a hard bar for
  a real effect, and a pass would still be a hypothesis for the forward record rather than an edge.
- **No EA change unless it passes.** If it passes, the port is a second entry path beside
  `ModeDecide()` in `mql5/MIDASTOUCH/MidastouchAI.mq5` **plus** its mirror in the engine of record in
  the same commit, then a parity certificate — the one-contract rule.
- **What this cannot do:** it cannot make the hours that lose money profitable by assumption. If the
  family fails, the honest conclusion is that the arm should keep its window and keep waiting.

---

# Results (appended after the run) — **VERDICT: FAIL. Nothing is ported. But the direction is real.**

Artifact `artifacts/midas_asia_sweep_20260922.json` · harness `scripts/midas_asia_sweep.py`.
Self-check reproduced first (`wfv n=56 / +15.9352R`). 178 Asian ranges were built per window.

### The pre-registered primary window (UTC 13–18 — the hours the snap-back loses in)

| variant | wf n / expR | **oos n / expR / pf / t / fills-per-day** |
|---|---|---|
| `SWEEP_CONT` | 41 / +0.0124 | **78 / +0.1228 / 1.312 / +1.07 / 0.46** |
| `SWEEP_FADE` | 44 / −0.2160 | 79 / +0.1188 / 1.302 / +1.03 / 0.47 |
| `RECLAIM_REV` | 58 / −0.0593 | 114 / +0.0331 / 1.067 / +0.34 / 0.68 |

```
PASS RULE (primary window, t >= 2.4, n >= 30, >=0.30 fills/day, same sign on wf):
  SWEEP_CONT   FAIL: t=1.068 < 2.4
  SWEEP_FADE   FAIL: t=1.027 < 2.4; sign not positive in both spans (wf -0.216, oos +0.1188)
  RECLAIM_REV  FAIL: t=0.345 < 2.4; sign not positive in both spans (wf -0.0593, oos +0.0331)
```

**Refused, and nothing reaches the EA.**

### What the run also found, which is not a pass and must not be quoted as one

The **secondary** window (UTC 07–18, declared *descriptive only* in §The engine, the windows, and the
pass rule — every hour after the range is known, not just the overlap):

| variant | oos n | expR | pf | win | t | n for t≥1.5 |
|---|---|---|---|---|---|---|
| **`SWEEP_CONT`** | **152** | **+0.1955** | **1.499** | 0.520 | **+2.21** | 71 |
| `SWEEP_FADE` | 164 | −0.1584 | 0.683 | 0.402 | −2.04 | — |
| `RECLAIM_REV` | 168 | −0.1425 | 0.706 | 0.387 | −1.82 | — |

Three things are true about that row and they have to be said together:

1. **It is the strongest measured number in this program** — `+0.1955R` per trade over 152 held-out
   trades, t +2.21, above the 1.96 single-hypothesis bar, with only 71 trades needed for t ≥ 1.5.
2. **It is not a pass and it is not even the pre-registered test.** It is the *secondary* window,
   it is one of three variants across two windows and two spans, its `wf` half is essentially zero
   (`+0.0256`, t +0.18), and its honest bar is therefore well above 2.21, not 1.96.
3. **The two direction checks are what make it worth a forward test rather than a shrug.** The mirror
   image `SWEEP_FADE` measures **−0.1584** and the textbook ICT reversal read `RECLAIM_REV` measures
   **−0.1425**. That is independently what the external series reported: a swept level predicts
   **continuation**, and the textbook reversal read is the one that runs **backwards**. Our
   implementation of the mechanism reproduces the published *direction* on our own venue — which is
   evidence the harness is measuring the mechanism and not an accident of our code.

### The decision this forces, and the one it forbids

- **Forbidden:** running another confirmatory test on the secondary window until it clears a bar.
  The window has been looked at; a re-run would be a description of the past. That is the sin the
  pre-registration exists to prevent.
- **Forced:** the only blind test left is **forward**. So the recommendation is a **shadow recorder**,
  not a trader: have the arm log, per bar, what `SWEEP_CONT` *would* have done — level, direction,
  ASIAN range, and the R it would have earned — into the ledger with **no order path at all**, then
  read it after enough trades accumulate. That is a genuinely blind, pre-registered evaluation of the
  one candidate the evidence supports, and it costs the account nothing.
- **Not changed by this study:** no preset, no input, no EA line, no arming record.
