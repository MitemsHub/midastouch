# The $25,000 parity re-run: what it exposed, measured

**Date:** 2026-09-20 · **Account:** 1428765 @ Upcomers-Server, $25,000 (not armed)
**Artifacts:** `artifacts/midas_parity_result_20260920_2033.json`,
`artifacts/midas_history_20260920-upcomers.json`, log
`artifacts/midas_parity_wf_20260920_2030.log`

## 1. What was asked

Move the parity harness onto this account's $25,000 basis **on both sides** — the EA's
tester INI and the python engine — and re-run the `wf` window so the comparison lines up.

## 2. The basis is now one number, applied to both sides

Before this change the harness claimed one window while **three books** sat under it:
tester deposit $1,000 (Deriv-era carve-out), EA paper-sizing input $5,000 (pinned to the
research engine's own `START_EQUITY`), python engine $5,000 — and the EA's prop governor
defaulted ON, sizing off whatever balance the tester handed it, while the contract never
pinned it at all.

`configs/mt5/accounts.json` now declares `account_size_usd: 25000` as the single source;
`mt5_terminals.active_account_size()` **refuses** when it is missing rather than
defaulting (defaulting is precisely how three numbers happened); the harness applies it
to the tester deposit, the EA's sizing input and the python run in one place. The governor
is **pinned off explicitly** for parity, because python models no governor — leaving it on
compares two rule sets and calls the difference an engine difference. 11 tests in
`tests/test_parity_basis.py`; one existing test had the bug written down as an invariant
(`assert InpPaperEquity == M.START_EQUITY`) and now asserts the registry basis.

## 3. The first attempt never ran at all

`PermissionError: 'C:\Program Files\MetaTrader 5\config\...ini'` — the tester driver wrote
its `/config` INI next to the executable, fine for the portable user-folder installs every
previous era used, impossible for this venue's Program Files install. It died **after**
stopping the funded account's terminal.

Fixed in `tests/mt5_tester_driver.py` (the house MT5 strategy-tester driver; it
was `tests/v75_tester_runner.py`): the INI is written to the first location that
actually accepts a write (per-install **data folder** first, install dir second, real write
rather than an `os.access` probe that lies on Windows), and it refuses naming every
candidate when none works. `midas_parity.preflight()` now checks this **before** the
terminal is stopped — the same reason its ex5 check exists. Proven with a real 2-day pass
before spending an hour: the tester read the data-folder INI, produced a report, created
the tester root, terminal relaunched.

Also fixed here: `preflight()` returned a bare list on its "no terminal resolves" path where
callers unpack `(problems, notes)`, so that diagnosis raised `ValueError` instead of printing.

## 4. The re-run completed, and it FAILS — for data reasons, not engine ones

```
REVERSE_DIRECTION  py 151tr +1.474R | EA 51tr +21.639R | max|dR| 3.00160 | keys MISMATCH | FAIL
```

Read the timestamps rather than the count: python's first trade closes ~2025-09-15, the
EA's ~2026-01-19. Three independent, measured causes.

### 4a. The venue does not have 60% of the window

```
History: XAUUSD: history synchronized from 2026.01.12 to 2026.09.15
History: XAUUSD,M15: history begins from 2026.01.12 13:15
```

Confirmed independently through the API: `copy_rates_range("XAUUSD", M15, 2025-09-15,
2025-09-22)` returns **one** bar — the earliest available, 2026-01-12 13:15. The `wf`
window runs 2025-09-15 → 2026-04-03, so the EA could only trade its last ~40% (51 trades)
while python traded all of it (151). The comparison is misaligned by construction.

### 4b. There are no real ticks

`Ticks: XAUUSD : 2026.01.14 - 2026.04.03  no real ticks, every tick generation used`, and
the report's own header reads `History Quality: 0% real ticks`. The pass ran on **generated**
ticks while python's parity model is per-tick fills. A `Model=4` request that cannot be
honoured should be declared, not silently downgraded.

### 4c. The two sides are on different clocks — and it moves with DST

The corpus of record and the venue's own bars are the *same market*: at the right offset the
median close difference is **$0.03–0.16** and the bar-to-bar return correlation is **0.9990**,
against a median $10.10 and correlation ≈0 at the raw alignment.

But "the right offset" is not constant:

| era | best offset (corpus → venue) | median \|diff\| |
|---|---|---|
| 2026-01 → 03 | **+60 min** | $0.05–0.38 |
| 2026-04 → 09 | **+120 min** | $0.03–0.16 |

The step lands between W13 and W14 — the EU DST date. The daily maintenance break
identifies which clock is which: gold's break is 21:00–22:00 UTC, and it appears at hour
**21** in the corpus but hour **23** in the venue's bars, i.e. **the corpus is stamped in
true UTC and the venue's bars in its own server clock (UTC+2 now)**.

Consequences, both real:
* The parity keyed comparison (open/close **epochs**) compares EA bar epochs in server time
  against python epochs in UTC. It cannot line up while that is true — independent of 4a.
* In the tester the EA's session gate classifies **bar epochs**, so `06:00–20:00` ran as
  04:00–18:00 UTC, two hours off from what the same EA will do live on `TimeGMT` — the EA's
  own `CLOCK:` line says exactly this and asks for the offset to be verified. Every
  tester-based certification so far traded a differently-timed session from the live one.

### 4d. The corpus was not this venue's, and nothing said so

`scripts/midas_fetch_history.py` hardcoded
`C:\Program Files\MetaTrader 5 Terminal\terminal64.exe` — the **Deriv** install, which no
longer exists on this machine — and produced no provenance record. Prices are consistent
with the venue once the clock is normalised, so the corpus is not wrong, but it is another
venue's series, unlabelled, and it reaches back to 2024 while the funded venue starts
2026-01-12.

Fixed: the fetcher now resolves the install by **account identity** (`mt5_ops.terminal_exe()`)
and refuses otherwise, `--suffix` writes a differently-sourced corpus *alongside* rather than
over it, and the artifact records terminal path, build, data folder, account, server, balance
and the per-timeframe first/last bar. The venue's own corpus, fetched today:

```
XAUUSD H1   4063 bars  2026-01-12 -> 2026-09-18  OK
XAUUSD M15 16224 bars  2026-01-12 -> 2026-09-18  OK
XAUUSD D1    179 bars  2026-01-12 -> 2026-09-18  REF
HISTORY (M15/H1 = research timeframes): ALL CHECKS PASS
```

## 5. A P0 sizing bug, found by measuring the same spec

The EA's `DollarPerUnitPerLot()` computed `tick_value / tick_size` and preferred the broker's
value when the geometric check disagreed. On this venue:

| source | says | verdict |
|---|---|---|
| `trade_contract_size` 100 × `trade_tick_size` 0.01 | $1.00 / tick | consistent with the settled price |
| `SYMBOL_TRADE_TICK_VALUE` | **0.10** / tick | the odd one out |
| `order_calc_profit(1 lot, +$1.00)` | **$100.00** | what the account actually pays |

So `tv/ts` gave **10** where the truth is **100**, and the EA printed its warning and used
the broker value anyway. Measured consequence at today's ATR (H1 17.22 → 2×ATR stop $34.44):
an intended **$250 (1% of $25,000)** stop would have been sized as **$2,500 (10%)** — two
thirds of the 6% trailing budget in one trade.

Fixed on both sides with one authority order — **settled > geometric > raw** — and a refusal
where previously there was only a warning. `floor_zone.SymbolData.calibrated_tick_value` (the
python twin, which had the mirror-image rule) now takes the settled value, reports the 0.90
disagreement instead of swallowing it, and `fetch_symbol_data` measures the settled value via
`order_calc_profit`. Recompiled: **0 errors, 0 warnings**.

## 6. What this means, and what is not done

Parity on `wf` is not a verdict about the EA. It cannot be produced on this venue, because
the window predates the venue's history, its ticks are generated, and the two sides are
labelled on different clocks. A FAIL that a reader could mistake for an engine disagreement
is worse than a refusal.

Still open, in order:
1. ~~**Normalise the clock** in the parity contract (EA bar epochs from server time to UTC,
   with the pinned offset asserted)~~ — **done, §7.**
2. **Re-scope the certified window** to what the venue can serve (2026-01-12 →), and re-run
   the walk-forward gate there. The current certification covers a series the account will
   never trade. (The walk-forward gate has since been re-run on the venue's own bars and
   reproduces the frozen verdict: 568 OOS trades, +20.67R, t = +0.52, 4 of 6 legs fail →
   **not validated**.)
3. ~~**Declare the tick model** the tester actually used, and fail when `Model=4` silently
   becomes generated ticks~~ — **done, §9.** Note what closing it revealed: on this venue a
   per-tick parity pass is not currently *possible*.
4. ~~**Decide the tick model deliberately** (§9)~~ — **decided and implemented, §10.**
   Certification is RESTRICTED to windows the venue can serve per-tick; `tickcov` is that
   window, and it has now been run (§10).

Nothing is armed: `InpLiveExecution=false` in both presets, and no signal has passed the gate.

## 7. One clock, pinned and asserted — and the pin is demonstrably the right one

`scripts/midas_parity.py` now carries the offset as a **per-window pin**
(`server_offset_min`) and `assert_server_offset()` re-derives it from the venue's own bars,
per month, before anything is stopped or run. It **refuses** two ways: when the offset is not
constant across the window (the +60 → +120 EU-DST step means one number would mis-align
every key on one side of the step), and when a pinned offset no longer matches the venue's
bars. `wf` (2026-01-14 → 2026-04-03 research window) sits wholly on the **+60** side and is
pinned there; `oos` sits wholly on **+120**.

Only the EA's epochs move (`to_utc`); its R, side and reason are its own measurements and are
frame-independent. The contract itself stays declared in **UTC** — `build_inputs(offset_min=)`
translates the session window, the Friday cutoff and the window pins into the EA's server
frame, so `06:00–20:00` finally means 06:00–20:00 **UTC on both sides** instead of running as
04:00–18:00 on the EA's side.

That the direction and size are right is not assumed — it is measurable on the raw ledger. On
the `oos` run's own ledger, converting the EA's epochs by −7200 s is the transform that
**maximises** key agreement:

| applied to raw EA epochs | open_ct hits | close_ct hits |
|---|---|---|
| 0 (no normalisation) | 1 / 105 | 2 / 105 |
| ±3600 s | 1 / 105 | 0–1 / 105 |
| **−7200 s (the pin)** | **79 / 105** | **75 / 105** |
| ±14400 s | 1–3 / 105 | 1–2 / 105 |

## 8. The re-run: the keys do not line up, and the headline dR is the harness's own noise

The `oos` window was re-run on one clock (2026.04.01 → 2026.09.18, pinned **+120 min**, asserted
before the terminal was stopped; artifact `artifacts/midas_parity_result_20260920_2212.json`):

```
REVERSE_DIRECTION  py 108tr +8.199R | EA 105tr -4.548R | max|dR| 3.00070 | keys MISMATCH | FAIL
```

**The keyed comparison does not line up** — 105 EA trades against 108 python, 26 with no key on
the other side, 29 the other way. But the headline `max |dR| 3.00070` is not a per-trade
divergence: `keyed_compare` zips **positionally** and only *checks* the keys, so after the first
misalignment every later dR is measured against the wrong partner — the failure its own
 docstring calls out as “run3's lesson”. Align strictly by key instead and the picture is
different:

| on the 69 trades where both sides agree on open_ct **and** close_ct | |
|---|---|
| side disagreements | **0 / 69** |
| within the 0.01R tolerance | 59 / 69 |
| max \|dR\| | **0.1149R** |

The divergence is therefore in trade **selection**, not execution — and at least 6 of the
unmatched pairs are the *same setup entered on a different bar*, identified by an identical
exit:

```
EA 2026-08-27 09:45 -> close 17:00  side -1  r -1.0020
py 2026-08-27 10:00 -> close 17:00  side -1  r -1.0021     dR 0.0001, entry 15 min apart
```

That shape is real evidence *about* the two engines, but §9 means this particular pass cannot
carry it: most of its bars were fabricated, so its entries and exits are MT5's invention. Treat
§8 as the shape to re-measure on a tick-covered window, not as a verdict.

## 9. The pass ran on generated ticks and the guard let it through — now it cannot

§4b recorded the downgrade and item 3 above asked for a refusal. The refusal existed and **did
not fire**, because the evidence regex `\breal ticks\b` matched the words inside a statement
whose meaning is the opposite:

```
Ticks: XAUUSD : real ticks begin from 2026.09.04 00:00:00
```

For the `oos` window starting 2026.04.01, that is **156 of 170 days (92%) fabricated** while the
INI declared `Model=4`. The earliest real gold tick this venue serves is 2026-09-04, so this is
not a local cache that can be warmed — it is the venue's tick depth.

Fixed in `tests/mt5_tester_driver.py`, and the vocabulary is MT5's own, taken from every journal
on the machine rather than guessed:

| statement | verdict |
|---|---|
| `no real ticks, every tick generation used` | generated |
| `real ticks absent for N minutes … every tick generation used` | generated |
| `real ticks begin from <date>` | generated **unless** `<date>` ≤ the pass's own `FromDate` |
| `real ticks begin from <date>`, window unknown | generated — fail closed, it cannot be shown to cover |
| `generating based on real ticks` (the `Tester:` line) | the tester announcing its **source**; written for a partial-coverage run too, so it is **not** coverage |
| `History Quality: N%` (report) | `N == 100` real, else generated |
| nothing at all | unknown → refused for a declared real-tick model |

`detect_tick_model()` therefore takes the window the pass declared, and `run_pass()` hands it its
own `FromDate`. Verified against the **actual bytes of that pass**, sliced from its own launch
line: it is now refused, naming “real ticks begin from 2026.09.04, but the window starts
2026.04.01 — 156 day(s) of it ran on generated ticks”.

Second lock, in `scripts/midas_parity.py`: `recorded_verdict()` demotes a key-matched **PASS** to
**REFUSED** unless the recorded tick model is `real`, so even if the driver's refusal is later
refactored away, an artifact cannot carry a PASS the ticks did not produce. The artifact now
carries `tick_model` next to the comparison. 26 tests in `tests/test_tester_tick_model.py`.

**Consequence.** Both certified windows are now *refused* rather than FAIL: `wf` is entirely
un-ticked and `oos` is 92% un-ticked. Per-tick parity — the program's evidence standard — cannot
currently be produced on this venue for any window longer than its tick depth. That is a
stronger and more useful statement than the FAIL it replaces, and it is item 4 above.

## 10. The decision: certify only where the venue serves ticks — and the first honest run

**Decision (implemented).** Parity certification is **restricted to tick-covered windows**,
not re-declared as a bar-replay model. The bar-replay option was rejected on its merits, not
for effort: a bar replay decides intrabar order — which of SL and TP was touched first — by a
rule the two engines do not share (python's rule is SL-first; MT5's OHLC walk is O→H→L→C), and
"declaring" that away would move a real disagreement into a constant instead of removing it.

So `WINDOW_SPECS["tickcov"]` (and `midas_sweep.WINDOWS["tickcov"]`) is scoped to what this
venue actually serves — **2026-09-04 → 2026-09-16**, pinned **+120 min**, tester dates
`2026.09.04` → `2026.09.18`. `TICK_COVERAGE_START` in `tests/mt5_tester_driver.py` is the
measured constant (`Ticks: XAUUSD : real ticks begin from 2026.09.04`), and a test asserts the
window starts at or after it, so a stale constant cannot quietly re-open the hole.

**The run** (`artifacts/midas_parity_result_20260920_2304.json`, REVERSE_DIRECTION, $25,000):

```
tick model: REAL (journal: real ticks from 2026.09.04, at or before the window start 2026.09.04)
python 8tr -1.602R | EA 9tr -1.047R | keys MISMATCH | PARITY FAIL
```

This is the first parity evidence on this venue that fabricated-tick contamination cannot
explain. Read it key-aligned rather than positionally (the harness's headline is still the
positional zip of §8):

| | |
|---|---|
| shared keys (both engines took the same bar) | **6** |
| side agreement on them | **6 / 6** |
| within 0.02R | **5 / 6** — e.g. `09-08 08:15` ea **+0.9890** vs py **+0.9877**, `09-15 08:15` ea −1.0030 vs py −1.0027 |
| genuinely different | EA 3 trades the python engine did not take, python 2 the EA did |

**What that means.** Where the two engines agree to take a trade, they agree on the fills: a
per-trade difference of ≤0.02R is quantisation, and it says the execution model is faithful.
What remains is **entry selection** — which M15 bars produce a signal — around five trades a
fortnight on the only window where this can be measured honestly. That is a far sharper target
than "parity fails", and it is a research question rather than a plumbing one.

**Also fixed the same day (found while auditing the EA for this run).** The EA's two *day*
rules — the 3% daily cap and the 20% Best Day ceiling — both took their baseline from "the
equity when this code was first reached today", which is the day's first **entry attempt**, not
00:00 UTC. A 3% loss taken at 07:00 was therefore re-anchored away by the 09:00 entry attempt and
the breaker never tripped for a day the venue had already counted as breached; and a restart
forgot the day entirely, because the baseline lived in a variable. `PropDayAnchorCheck()` now
takes both baselines on every tick at the UTC rollover and reconstructs the day's opening equity
from the EA's own closed deals when it starts mid-day (`eq − today's realised P&L`, exact at the
rollover itself). Recompiled **0 errors / 0 warnings**, and the fixed build is the one the
`tickcov` run above exercised on real ticks. `tests/test_midas_prop_day_anchor.py` pins it,
including that the lazy anchors cannot come back; `test_midas_time.py`'s UTC day-key pin now
follows the key to its new home rather than being dropped.
