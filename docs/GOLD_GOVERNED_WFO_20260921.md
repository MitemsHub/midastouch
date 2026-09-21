# The governor inside the walk-forward, and the geometry that would have to exist

**Date:** 2026-09-21 · **Harness:** `scripts/gold_governed_wfo.py` (new, this commit)
**Artifacts:** `artifacts/gold_governed_wfo.json` (governed walk-forward, 24 configs × 31 folds),
`artifacts/gold_governed_wfo_sweep{0,1,2}of3.json` (the 168-geometry sweep, in three strides)
**Data:** the venue's own served history — `XAUUSD M15, 16,283 bars, 2026-01-12 .. 2026-09-21`,
read from the terminal by `mt5_data.load_m5`, the same loader the frozen walk-forward uses.

---

## 1. What was unmeasured, and is now measured

`docs/GOLD_ARMING_DECISION_20260921.md` recorded the decision not to arm and named the gap:
*"the replay that reaches the 5% target puts 80.6% of the profit in one day, against the
venue's 20% Best Day cap. The governor gates ENTRIES to prevent exactly that; its effect on
that window has NOT been measured."*

This measures it, twice over:

1. **The governed walk-forward** — the frozen 24-configuration grid and the frozen fold
   structure, but selection is now made on the **governed** prior fold and scored on the
   **governed** next fold. The EA's refusals are part of the strategy being tested, not a
   badge applied to a result afterwards.
2. **The geometry sweep** — 168 session / stop / target combinations on the same window, to
   answer the question the gate cannot: *is there a candidate anywhere near big enough to be
   decidable?*

### The governor is the EA's, not a restatement

`govern()` mirrors `PropGovernorBlock()` in `mql5/MIDASTOUCH/MidastouchAI.mq5`:
the 3% daily-loss breaker, the 6% trailing shield through `drawdown_floor_usd` (the clamped
floor, not a raw peak-to-trough), and the Best Day cap

```
cap = size × target_pct × best_day_pct = 25,000 × 0.05 × 0.20 = $250 per UTC day = 1R
```

Two approximations are declared because they are the only places the replay is not the EA,
and both make the replay's governor **laxer** than the chart's, so the numbers below are an
upper bound on what the live arm would have taken:

* the EA evaluates the governor against **floating** equity every tick; the replay evaluates
  **realised** equity at the entry bar;
* the EA re-anchors the day from a per-tick equity snapshot; the replay re-anchors at the
  first entry of each UTC day.

---

## 2. Result 1 — with the governor inside, nothing clears the gate

| | governed | frozen (ungoverned) WFO |
|---|---|---|
| OOS folds | 30 | 30 |
| OOS trades | **270** | (the frozen run's own count) |
| total | **−30.35R** | +0.52 fold-mean t |
| mean per fold | **−1.012R** | — |
| t (fold means) | **−1.32** | +0.52 |
| random-entry control | −60.98R (mean of 200) | — |
| V1 total>0 | **FAIL** | PASS |
| V2 positive folds ≥ 60% | **FAIL** | FAIL (12/30) |
| V3 worst fold > −3R | **FAIL** | FAIL |
| V4 beats control | PASS | PASS |
| V5 median fold > 0 | **FAIL** | FAIL |
| V6 fold-mean t ≥ 1.5 | **FAIL** | FAIL |
| **verdict** | **NOT VALIDATED (5 of 6 fail)** | NOT VALIDATED (4 of 6 fail) |

The governed strategy still beats its random-entry control (it is not noise), and it still
loses money on the venue's own bars.

## 3. Result 2 — the governor does not prevent the venue's rules from being broken

On the governed OOS sequence (122 trading days, final equity **$17,411.91**, −$7,588.09):

* worst day **−3.23R = −$806** against the $750 (3%) daily limit — **over**;
* best day **+2.97R = $742**; the share is *undefined because the run lost money*, and the
  20% Best Day rule is a constraint on profit, so it cannot be "passed" by losing;
* **5 shield breaches** (2026-02-17, 03-09, 03-10, 03-12, 04-23) and **5 daily-limit
  breaches** (01-29, 02-13, 02-17, 03-09, 04-07);
* verdict: **BREACHED**.

**Why a governor that gates entries cannot prevent this**, and why this is structural
rather than a bug: the rules are conditions on the **equity path**, while the governor is a
condition on **entries**. It can refuse to start a new position, but it cannot stop the
position already open from closing through the daily floor or the shield floor. The Best
Day cap is enforced against its *ceiling* (1R/day) precisely because the share is not
knowable in advance — so on a day where the first trade runs to +3R, the governor's cap is
crossed by the *outcome* of a trade it correctly allowed.

## 4. Result 3 — no geometry reaches a decidable edge

Across all 168 geometries (7 sessions × 3 stops × 4 targets × 2 trend sets), on the venue's
served window:

| | governed | ungoverned |
|---|---|---|
| best mean R/trade | **+0.0316R** (n=302, t=0.40) | **+0.0816R** (n=270, t=0.94) |
| geometries with mean > 0 | **1 of 168** | 62 of 168 |
| geometries at ≥ +0.15R with n ≥ 100 | **0** | **0** |
| trades needed for t ≥ 1.5 at the best effect | **4,227** (≈18 years at 0.65 trades/day) | 1,151 |

The single geometry that survives the governor at all is session **07–20 UTC, stop 1.5×ATR,
target 3.0R, EMAs (8,21,50)**: 168 Best Day vetoes and 7 daily-loss vetoes out of 477
candidate trades — i.e. the governor keeps 63% of the entries and still returns +0.0316R.
Its own power number, at the measured standard deviation of 1.37R, is **4,227 trades**.

The governor also *costs* more than it saves on almost every other geometry, and the reason
is legible in the veto counts: the Best Day cap is 1R, so a day whose first trade wins is
closed for business — the cap removes winners at the same rate it removes losers
(658 → 70 trades, 270 → 18 trades on the same configuration).

**Exploration, not a test.** The sweep re-uses the very window the gate is judged on, so
the +0.0816R above is a hypothesis with no out-of-sample status. It is reported because it
bounds the search: even *in* sample, with the governor off, nothing in this family reaches
half the +0.15R that a decidable forward test would need.

---

## 5. What this means for the live arm

The arm on account 1428765 runs `InpMode=0` (ORIGINAL) with `InpPropGuard` on. These
results say two things about it, and the operator should have both in view:

1. **The governor is not a safety net against the venue's limits.** Measured: it gates
   entries, and the equity path still breached the 3% daily cap five times and the 6%
   shield five times in the governed replay. The shield's protection comes from position
   risk and the soft-stop ladder, not from `PropGovernorBlock()`.
2. **Governing the selection does not create an edge; it removes trade count.** If an
   override is being held open, it is being held open on a configuration whose own
   governed walk-forward is negative, whose best geometry in a 168-point sweep is
   +0.0316R/trade, and whose venue rules were breached in the only replay that modelled
   them faithfully.

This **does not change the record**: `artifacts/live/armed.json` remains an operator
override on a failed gate, and `docs/GOLD_ARMING_DECISION_20260921.md` remains unedited.
What it changes is the list of what would retire the override — see
`docs/GOLD_FORWARD_PREREG_20260921.md`, which pre-registers the forward test, its power,
and the number at which the configuration is declared dead.

---

## 6. Reproducing this

```bash
# governed walk-forward (24 configs x 31 folds, ~60s)
python scripts/gold_governed_wfo.py --mode governed --control-reps 200 \
    --out artifacts/gold_governed_wfo.json

# the sweep is 168 geometries; each slice is ~3.5 min
python scripts/gold_governed_wfo.py --mode sweep --slice 0 3 --out artifacts/gold_governed_wfo_sweep0of3.json
python scripts/gold_governed_wfo.py --mode sweep --slice 1 3 --out artifacts/gold_governed_wfo_sweep1of3.json
python scripts/gold_governed_wfo.py --mode sweep --slice 2 3 --out artifacts/gold_governed_wfo_sweep2of3.json
```

Slices are stride-based, so each spans the whole grid and a partial sweep is comparable to
a full one. The governor's own semantics are pinned in `tests/test_gold_governed_wfo.py`,
including the three refusal paths and the exact USD cap derived from the preset.
