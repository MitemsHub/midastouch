# Pre-registration: the exit family as a walk-forward axis

**Declared:** 2026-09-21, before `scripts/gold_exit_family_wfo.py` was run.
**Harness:** `scripts/gold_exit_family_wfo.py --mode exitfamily`
**Artifact:** `artifacts/gold_exit_family_wfo.json`

---

## 1. The hypothesis this tests, and why it is a pre-registration

`docs/GOLD_EXIT_CAPTURE_AND_FILTERS_20260921.md` measured, on fixed entries, that the
certified target/timeout exit captures **2.6%** of the average 8-bar favourable excursion
(1.127R) and that removing the target captures **28.6%** (+0.0294R → +0.3221R per trade,
t=3.06 over 912 trades). That measurement was made by re-pricing a **fixed** entry set, so it
could not see the thing that actually matters for a walk-forward: a longer hold changes which
later signals get a slot. **Occupancy is part of a strategy**, and only the engine can model
it.

So the exit becomes a declared axis of the frozen grid, and the same frozen selection rule
and criteria apply. The hypothesis, stated before the run: **with the target removed, fold
selection will pick a target-free configuration in a majority of folds, and the
out-of-sample fold total will improve on the certified grid's.**

## 2. The declared grid (48 configurations, fixed)

`EMA sets {8,21,50} and {12,26,100}` × `sessions 7–20 and 13–18 UTC` × `stops 1.0 and 1.5 ×
ATR` × six exit arms:

| arm | rule |
|---|---|
| `tp1.5` | stop 1.0/1.5 × ATR, target 1.5R (in the certified family) |
| `tp2.0` | target 2.0R (the live preset's own arm) |
| `tp3.0` | target 3.0R (the arm the certified grid most often picked) |
| `noTarget-hold` | no target; exit at stop or the 22:00 UTC flat only |
| `noTarget-48b` | no target; plus the EA's own `InpTimeoutMinutes=720` = 48 bars |
| `trail1.0/0.5-48b` | no target; trail after +1.0R at 0.5R distance, 48-bar timeout |

Unchanged from the frozen protocol: the instrument, the window (the venue's served bars),
the 8-day folds, the ATR band (0.20–0.95 trailing percentiles), one position at a time, the
measured cost model (spread 1.073 bps, $10/lot RT, $100/unit/lot), flat by 22:00 UTC, the
selection rule (best governed prior-fold total, with the declared tie-breaks), and the
V1–V6 criteria.

Selection is made on the **governed** prior fold and scored on the **governed** next fold —
the entry-only governor that the EA actually runs — because a configuration that only works
ungoverned is not deployable. Tie-breaks, in order: higher prior-fold total, then the
**tighter stop**, then the exit arm's declared order above, then grid index. Declared here so
a tie cannot be resolved after seeing which side wins.

## 3. Pass and kill conditions, declared in advance

* **PASS:** all six V1–V6 checks on the out-of-sample folds, plus the venue rules unbroken on
  the governed OOS sequence (no shield breach, no daily breach).
* **PROVISIONAL / NOT VALIDATED:** anything less. The gate is the gate; a better total is not
  a pass, and this document does not create a second one.
* **The hypothesis fails** if the selection does not prefer target-free arms in a majority of
  folds, or if the OOS fold total does not improve on the certified grid's −30.35R.
* **No re-specification.** The grid, the tie-breaks and the criteria are fixed above. If the
  result is disappointing, the next step is a new pre-registration with its own date, not an
  edit to this one.

## 4. What a PASS would and would not mean

A PASS here would be the first configuration in this program to clear the frozen gate, and it
would still be **out-of-sample within one window**: the folds are the protocol's OOS unit,
but the window itself is the venue's only served history. It would authorise a *pre-registered
forward test* (n ≥ 100 trades, the arithmetic in `docs/GOLD_FORWARD_PREREG_20260921.md`), not
an arming. The live arm's override record is untouched by anything in this file.
