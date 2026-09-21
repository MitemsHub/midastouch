# What the news stand-down costs the certified corpus — measured 2026-09-21

Instrument: **XAUUSD M15**, the frozen walk-forward window **2026-01-12 13:15 → 2026-09-18 22:45**
UTC (16,224 bars, 31 folds), replayed twice through the *same* code
(`scripts/gold_news_sensitivity.py` imports `scripts/gold_walkforward.py` — the grid, the fold
structure, the selection rule, the cost model, the control seed and V1–V6 are not re-implemented).

## Why this was worth a measurement

`docs/MIDASTOUCH_GOLD_PLAYBOOK.md` carries a standing policy — no new entries within ±15 minutes
of a top-tier USD release — and the EA can enforce it (`InpUseNewsFilter`, v1.19c). The frozen
walk-forward was produced with **no news rule at all**: `docs/GOLD_WFO_PROTOCOL.md` never mentions
one. So switching the gate on does not "add protection" to a certified strategy; it **changes the
strategy**, and that change had never been priced. "It can only help" is exactly the kind of claim
this program refuses to make without a number.

## The calendar, and why it is the venue's own

The only source of record is the venue's terminal. The Python API exposes **no calendar function**
(269 names, none calendar-related) and the Strategy Tester cannot call one (`CalendarValueHistory`
→ `-1`, error **4014**), so `mql5/MIDASTOUCH/MidasNewsProbe.mq5` was attached once, live, with its
window opened to cover the frozen corpus, and wrote `MIDASTOUCH_news_calendar.csv`:

| | |
|---|---|
| events | 2,719 (369 HIGH) |
| coverage | 2026-01-02 → 2026-09-24 UTC |
| source | `mt5_economic_calendar`, generated 2026-09-21 07:44 UTC |
| blackout bars in the corpus | **398 of 16,224 (2.45%)** |

## The control, without which this is not evidence

The veto-**OFF** leg must reproduce `artifacts/gold_wfo.json`. It does, exactly — 568 trades,
total **+20.667938R**, t **+0.524267**, control **−86.600606R**, and every per-fold R to 1e-9. The
script **refuses to report** if that fails, so a difference between the legs cannot be an artefact
of the harness.

## Result

| | trades | total R | mean R/fold | t | control | V1 | V2 | V3 | V4 | V5 | V6 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| veto OFF (certified) | 568 | +20.67 | +0.689 | +0.524 | −86.60 | P | F | F | P | F | F |
| veto ON (±15 m HIGH) | **559** | **+24.03** | **+0.801** | **+0.618** | −85.47 | P | F | F | P | F | F |
| change | −9 (−1.6%) | **+3.36** | +0.112 | +0.094 | +1.13 | — | — | — | — | — | — |

Per fold, the veto moved the result in exactly **three** folds — F03 (−1.48R), F04 (+3.78R, where
the fold's **selected configuration changed**) and F30 (+1.06R) — and changed nothing in the other
27. A signal census counted independently of position state: **156 of 10,392** entry-condition bars
(1.50%) sit inside a blackout.

## What this does and does not say

1. **The stand-down does not rescue the gate.** V2, V3, V5 and V6 fail identically with the veto on.
   The strategy is still not validated, and the gate's verdict is unchanged by this amendment.
2. **It is not a free subtraction of the worst trades.** Total R went *up* because the nine removed
   entries were net negative — and because one fold's `CHANGED` pick moved with them. A rule that
   alters which configuration a fold selects is a change to the strategy, not a filter on top of it.
3. **The effect is small and one-window.** ±3.36R on a +20.67R total is inside the noise this
   program has already documented (the fold-mean t is +0.52 either way). It is not evidence that the
   veto helps, only that on this window it did not visibly hurt.
4. **The calendar is retrospective.** MetaQuotes serves history, so these are the events as they are
   known *now*; the EA in real time sees the calendar as published, and releases are occasionally
   added, revised or rescheduled. That makes this an accurate measure of the rule's exposure and an
   approximate measure of any single live day.
5. **Two header defects were found by taking the measurement, and both are fixed.** The probe derived
   its window and offset headers from `TimeCurrent()` — the time of the **last tick** — which right
   after a launch is stale: it wrote `server_offset_min=-318` for a UTC+2 venue, and the EA announced
   `offset=-5 h 19 min`. The `epoch_utc` column was never affected (verified self-consistent with
   `time_utc`), which is why these results stand. Both now derive the offset from `TimeTradeServer()`,
   and the EA's banner prints `CLOCK: UNVERIFIED OFFSET` rather than a confident wrong number.

## Reproduce

```
python scripts/gold_news_sensitivity.py \
  --calendar "<terminal data>\\MQL5\\Files\\MIDASTOUCH_news_calendar.csv"
```

Artifact: `artifacts/gold_news_sensitivity.json`. Tests: `tests/test_gold_news_sensitivity.py`
(the judged instant — the bar's **close**, matching the EA's `TimeGMT()` on the same bar — the
symmetric inclusive window, HIGH-only, and the control refusal).
