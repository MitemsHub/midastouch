# GOLD WFO — THE EA'S OWN ENTRY RULE (pre-registered 2026-09-21)

**Status: PRE-REGISTERED, NOT YET RUN.** Everything below is fixed before the first number
exists. The verdict is written to `artifacts/gold_wfo_ea.json` and
`docs/GOLD_WFO_EA_VERDICT_20260921.md`, which record the sha256 of this file so a later edit
cannot silently re-baseline the result.

---

## 1. Why this protocol exists

The gate this arm is armed behind (`artifacts/gold_wfo.json`, cited by
`artifacts/live/armed.json`) is a walk-forward of a **different strategy family**.
Measured 2026-09-21:

| | the frozen gate (`scripts/gold_walkforward.py`) | the EA (`MidastouchAI.mq5` v1.19) |
|---|---|---|
| trigger | M15 EMA stack 8/21/50 or 12/26/100, strictly ordered | M15 **BB(20, 2.0) touch-back-inside or RSI(14) 70/30** |
| regime | H1 EMA stack 8/21/50, `close > EMA20` on H4 | H1 EMA20 and H4 EMA20, both agreeing |
| Bollinger / RSI | absent from the engine | the entire trigger |
| signals on the same 174 days | 7,606 (48.1% of bars) | 368 (2.3% of bars) |

They agree on the same bar **and** the same direction 258 times — **3.4%** of the gate
engine's signals. So the frozen verdict is evidence about a rule that trades ~5x more often
than the one holding the orders, and **no walk-forward of the EA's rule exists**. This
protocol is that walk-forward. It does not touch, relax or re-run the frozen one; the EMA
verdict (NOT VALIDATED, 4 of 6 legs failed) stands for the family it measured.

## 2. What a result here does and does not mean

- **Does:** it makes it possible to arm behind a verdict about the strategy that trades.
- **Does not:** it cannot validate the arm *retroactively*, and a PASS does not arm anything —
  arming is an arming-record event (`artifacts/live/armed.json`), never a protocol result.
- **Does not:** it is **not a blind test**. The window has been looked at before: every parity
  window runs this rule in `REVERSE_DIRECTION` mode, and the arming record already quotes the
  armed mode at +0.1149R/trade over n=138 (t=1.22) on part of these bars. What is genuinely
  new here is the *fold structure*, the *selection procedure*, the *control*, the *newest
  bars*, and the same legs applied to the arm's own configuration with no selection at all.
  The aggregate for one cell is a re-derivation of a known number, and is labelled as such.

## 3. Window — the venue's served window, in TWO CLOCK ERAS

The venue's own series (`data/forex/xauusd/*_upcomers.csv`, the data of record) is stamped
in the venue's clock, and the served window crosses one measured DST step. A single offset
over the whole window is not available (`midas_parity.measure_server_offset_min` returns
`None` for it — the correct refusal), so the WFO is declared **per era**, each with the
offset `configs/mt5/server_offsets.json` pins and each validated forward by a parity pass:

| era | server window | pin | forward validation |
|---|---|---|---|
| A | 2026-01-12 → 2026-03-31 | **+60 min** | wfv parity pass, 53/53 trades, max abs dR 0.0005 |
| B | 2026-04-01 → 2026-09-18 | **+120 min** | oosc parity pass, 107/107 trades, max abs dR 0.0005 |

Bars are shifted to UTC with their own era's pin (`midas_parity.python_build_data`,
`corpus="venue"`), and no fold crosses an era boundary. The two era fold lists are pooled
for the V-legs; every bar is stamped by exactly one era's offset, and no other clock
assumption is made anywhere.

The warm-up is the engine's own guard (`k1 < 21 or k4 < 21` → no signal), which is ~3.5 days
of H1/H4 history and covers the EMA20 warm-up.

## 4. The rule — fixed, exactly as the EA implements it

Not a family member: **the** rule. The trigger is BB(20, 2.0) touch-back-inside or RSI(14)
at 70/30 on the closed M15 bar; the regime is H1 EMA20 and H4 EMA20 agreeing with the
direction. These are the EA's own values (bb period/dev, rsi period/levels, macro EMA
period) and are **not swept**: sweeping them would certify a configuration no preset runs.
The implementation is `scripts/midas_sweep.py`'s — the parity-pinned engine of record — so
the rule certified here is the rule the parity harness compares against the EA.

Engine mechanics, unchanged from the frozen engine of record: entry at the next M15 open
with half-spread, exit at the level with half-spread, stop = `sl_atr_mult` x ATR(H1, 14)
(SMA-bounded, amendment 2), target = `tp_mult` R, timeout 48 M15 bars, **one position at a
time**, min-lot floor 0.01 with the amendment-6 veto (min-lot risk > 15% of the sizing basis
→ no trade), no news veto (the arm's preset has it off).

**Sizing basis: $25,000 at 0.25%** — the U25 mirror's evaluation size and the arm's armed
risk, so the fold R series is the one the arm would produce. R is stop-normalised, so the
only ways size can enter are the min-lot floor and the amendment-6 veto.

## 5. The grid — closed, 144 configurations, every axis live-runnable

| axis | values | EA input it comes from |
|---|---|---|
| mode | the 8 the EA implements | `InpMode` |
| stop | 1.0, 1.5, 2.0 x ATR(H1) | `InpSlAtrMult` |
| target | 1.5, 2.0, 3.0 R | `InpTpMult` |
| session window (UTC) | (6, 20), (13, 18) | `InpSessionStartHour` / `InpSessionEndHour` |

8 x 3 x 3 x 2 = **144**. The arm's own configuration — `ORIGINAL`, 2.0, 2.0, (6, 20) — is
in the grid as declared, and is also reported **alone, with no selection** (§7).

## 6. Structure

- **Folds:** contiguous 8-calendar-day blocks per era, from the engine's first signalable
  bar. Era A gives 9 folds, era B gives 21 — **30 folds**, matching the frozen protocol's
  structure so the two verdicts are comparable.
- **Selection:** on fold *k*, the configuration with the highest total R wins; ties are
  broken deterministically by (lower stop, lower target, lower window start, lower grid
  index), declared here and never adjusted. The pick is scored on fold *k+1* **only**. If
  every configuration scores <= 0 on fold *k*, the previous pick is carried (declared).
- **Criteria:** the frozen `docs/GOLD_WFO_PROTOCOL.md` §6 block, applied verbatim through the
  same function (`scripts/gold_walkforward.py:criteria`), with `trials=144` so V7's
  selection threshold is the 95% family-wise threshold for a 144-wide search. All of
  V1–V7 must hold.
- **Control (V4):** seeded random entry (`CONTROL_SEED`, 200 repetitions). Same engine, same
  geometry, same session window, same cost model; only *when* and *which way* is randomised,
  with as many random in-session entry bars as the controlled configuration produced trades.
  Declared difference from the frozen control, which samples the first N session bars rather
  than drawing uniformly: this control draws uniformly across the window, so it cannot
  accidentally face an easier regime.
- **Also recorded, not a pass condition:** the configuration-by-fold matrix, the
  Probability of Backtest Overfitting by CSCV
  (`scripts/gold_walkforward.py:probability_of_backtest_overfitting`), and the
  leave-one-fold-out totals, because a result carried by one fold is what the frozen verdict
  found and it should be visible here too.

## 7. Decision rule — declared now

**PASS** requires *all* of:

1. V1–V7 all hold on the selected path; **and**
2. the **declared cell** — the arm's own configuration, no selection — reaches
   `t >= 1.96` on its own fold-R series.

Anything else is **NOT VALIDATED**, recorded as such, and changes nothing about the arm: the
live order flow is authorised by `artifacts/live/armed.json` (an operator override on a
FAILED gate) and only an arming-record event changes it.

**Declared expectation: NOT VALIDATED.** Grounds, stated before the run: the two known
aggregates for this rule are +0.2336R/trade (n=42, wfv) and +0.0630R/trade (n=96, oosc),
combining to +0.1149R at t=1.22; the second half of the window showed decaying performance in
every exit study run so far; and the frozen family failed 4 of 6 legs on the same bars. A
positive total that fails V2/V5/V7 is the single most likely outcome, and would mean the same
thing the frozen verdict meant: a right-skewed distribution whose median is negative.

## 8. Reproducing

```bash
python scripts/gold_wfo_ea.py --write          # runs both eras, writes the artifact
python scripts/gold_wfo_ea.py --selftest       # pins: grid size, fold counts, clock refusal
```
