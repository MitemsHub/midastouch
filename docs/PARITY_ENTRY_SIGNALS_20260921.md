# Why the two engines generated different entry signals on the same bars

**2026-09-21.** Question: the EA and the python engine of record were being walked through
the same window and produced **9 trades vs 8**, with three side disagreements. Same bars,
same clock (ruled out earlier), same news stance (ruled out earlier). This is the term-by-term
diff of the entry conditions, and the answer.

**Answer, in one line: the two engines were reading different H4 bars.** The macro gate is
`H1 close vs EMA20` **and** `H4 close vs EMA20`, and python derived H4 by bucketing H1 on the
**Unix epoch** (`t0 = t - t % 14400` → 00/04/08/12/16/20 UTC) while the venue — and therefore
the EA, which reads the terminal's own `PERIOD_H4` — buckets on the **server day**
(02/06/10/14/18/22 UTC on this account). A two-hour offset means *every* H4 bar is a different
bar: different close, different EMA20, different macro state. Fixed in `h4_series(h1,
offset_min)`; with the venue's grid the same window reproduces the EA's entry set **9 of 9,
nothing left over in either direction**.

Behind that fix sat a **second divergence** the diagnosis exposed: the recorded-spread file
staged for the tester was still a dump of the *legacy* series (flat $0.15) while python charged
the *venue* series' recorded spread ($0.42) on the same bars. That is the fill-price difference
that made one stop's touch land 105 minutes late. Both are fixed; the window now **passes**.

---

## 1. The terms that are NOT the cause, each measured

| term | how it was checked | result |
|---|---|---|
| clock | both legs on one frame, offset asserted | `+120 min`, normalised before anything ran |
| M15 (trigger series) | venue CSV vs the terminal's own history, 2026-09-04..09-18 | **999/999 bars, 0 OHLC differences** |
| H1 (macro + ATR series) | same comparison, H1 | **248/248 shared bars, 0 OHLC differences** |
| trigger rule | python's trigger vs the EA's own, recovered exactly | **9/9** (`side = -trigger` in REVERSE_DIRECTION, so the EA's trigger is `-side`) |
| session gate | harness shifts the EA's inputs by the offset | `06:00-20:00 UTC` on both sides; no entry sits near a boundary |
| ATR | EA ledger `atr` column vs python's `stop_d/2`, all 9 trades | agree to **max 3.4e-4** — the 5-dp export's rounding, not a different formula |
| news stand-down | one rule, imported by both | OFF, 0 vetoes on this window |

So: the data is identical, the clock is identical, the trigger is identical, the session is
identical, the ATR is identical. What was left was the macro gate's H4 leg.

## 2. The cause: the H4 grid

The venue's own grid, read from the terminal, not inferred:

```
H4: server 09-08 00:00 -> UTC 09-07 22:00   server 09-08 04:00 -> UTC 09-08 02:00
    server 09-08 08:00 -> UTC 09-08 06:00   server 09-08 12:00 -> UTC 09-08 10:00   ...
python's epoch bucketing:                    UTC 00:00 / 04:00 / 08:00 / 12:00 / 16:00 / 20:00
```

`h4_series(..., offset_min=120)` now reproduces the venue's boundaries exactly (verified against
the terminal's own series: `01-12 10:00, 14:00, 18:00, 22:00`). The default `offset_min=0` still
reproduces the old epoch alignment, which is why the frozen legacy-corpus numbers did not move.

### The scoreboard at the EA's nine entries

In `REVERSE_DIRECTION` the engine takes `direction = -trigger` and requires `mac == -trigger`,
so **the EA's own macro state at its signal bar equals its ledger `side`**. That makes the EA's
term recoverable exactly, without trusting any reconstruction:

| signal bar (UTC) | EA side (= EA mac) | epoch grid | venue grid |
|---|---|---|---|
| 09-07 08:45 | −1 | −1 ✓ | −1 ✓ |
| 09-08 08:15 | −1 | −1 ✓ | −1 ✓ |
| 09-10 10:45 | −1 | **0 ✗** | −1 ✓ |
| 09-10 13:00 | −1 | −1 ✓ | −1 ✓ |
| 09-11 14:00 | **+1** | **0 ✗** | +1 ✓ |
| 09-14 09:30 | −1 | −1 ✓ | −1 ✓ |
| 09-15 08:15 | −1 | −1 ✓ | −1 ✓ |
| 09-16 10:45 | +1 | +1 ✓ | +1 ✓ |
| 09-16 18:30 | +1 | +1 ✓ | +1 ✓ |

**epoch grid 7/9. venue grid 9/9.** The two misses are exactly the two entries only the EA took.

### The five divergent instants, each accounted for

| signal bar (UTC) | which leg | why |
|---|---|---|
| 09-09 08:00 | python-only | epoch grid says `mac=+1` where the EA's bar says **0** → python invented an entry |
| 09-10 10:45 | EA-only | epoch grid says **0** where the EA's says `-1` → python suppressed the EA's entry |
| 09-11 14:00 | EA-only | epoch grid says **0** where the EA's says `+1` → python suppressed the EA's entry |
| 09-10 12:00 | python-only | both grids signal; under the epoch grid python was **flat** there (it never took 10:45), so it entered a bar the EA was already positioned through |
| 09-10 13:00 | EA-only | the mirror image: the epoch-grid python was still holding the 12:00 trade, so it skipped the bar the EA took |

Four instants are the gate itself; the remaining two are **position-state coupling** through the
first four — a refused entry changes when a position is open, which changes which later bars are
even eligible. All five are accounted for by the grid alone.

**Why the gate is knife-edge, and why that matters.** The macro gate compares a *close* to an
*EMA*, so it flips whenever the two are within the gap between them — a grid error of two hours
moves the EMA by tens of dollars, but any small series difference can flip a single bar too. It
has no hysteresis. That is a property of the strategy, not a bug, and it is exactly why the
comparison has to be run on one market, one grid and one clock.

## 3. The second divergence, found by doing the first one

Diffing the terms per trade surfaced a fill-price offset that was **sign-consistent and
constant**: the EA's entry was always ~$0.135 better than python's (higher for a short, lower
for a long). Recovered from each engine's own record:

```
bar (server)   EA ledger spread   python charged   venue corpus
1788777900     0.15               0.42             0.42
1789142400     0.15               0.42             0.42
```

The file staged for the tester — `MIDASTOUCH_spread_M15.csv`, bundled by `#property tester_file`
— still held the **legacy** series' spreads while the python leg read the **venue** corpus. On
the tick-covered window the staged file had **14,373 values that disagree, 1,009 bars missing,
34,785 extra**. Consequences, both measured:

* the fill differs by half the spread difference, so the whole stop ladder shifts: a long's stop
  sat $0.136 further from its fill, and the market ground through the two levels 105 minutes
  apart (`close_ct_mismatches: [4]`);
* one TIMEOUT trade reached `|dR| 0.0102` — just over tolerance.

And the file has a **second job** that makes a wrong series worse than a missing one: the EA's
`SpreadAt()` returns 0.0 for a bar the file does not hold, and the BAR fill path skips those
bars. The file **is** the BAR-mode membership filter, so a stale one is also a different market.
`preflight` had only ever asked whether the file existed.

## 4. The fix

`scripts/midas_parity.py`:

* `corpus_bars(corpus, offset_min)` — the M15 bars of the corpus of record, in UTC.
* `spread_rows(bars, offset_min)` — the staged file's rows: **server** epoch (the frame the EA
  looks a bar up in: `SpreadAt(iTime(...))` inside the tester) and the corpus's own dollar value,
  floored at `SPREAD_FLOOR`, which is what python charges per bar. A file left in UTC is read one
  offset late on every bar — invisible on a flat series, which is how it survived.
* `stage_spread_file` / `verify_spread_file` / `ensure_spread_file` — derive, then **prove**:
  value disagreements, bars the corpus has and the file does not, and bars the file has and the
  corpus does not, each named with the bar that differs.
* `main()` calls `ensure_spread_file` **before the terminal is stopped**, and aborts if the file
  cannot be made to be the corpus. `preflight(expert, expected_spread=...)` now checks contents
  instead of existence.

Pinned by five tests in `tests/test_parity_corpus.py`: the server frame and one row per corpus
bar, a legacy dump being refused bar-by-bar, restaging being idempotent, an absent/empty file
refusing, and the end-to-end identity — **for every trade the engine of record takes, the
half-spread it charged equals the value the staged file hands the EA for that same bar.**

## 5. The result

`python scripts/midas_parity.py --window tickcov` — real ticks from 2026-09-04, both legs on the
venue corpus, gate OFF:

```
REVERSE_DIRECTION   py 9tr -1.098R | EA 9tr -1.096R | max|dR| 0.00050 | keys OK | PASS

count match: True     open_ct: True     close_ct: True     side: True
max |dR|: 0.0005      over tolerance: 0
tick model used: real (venue's real ticks begin 2026.09.04, at the window start)
artifact: artifacts/midas_parity_result_20260921_1107.json
```

Nine trades is a small window, and it is the only one this venue can certify on real ticks.
`anchor NO-ANCHOR` is expected and not a defect: the frozen sweep anchor was computed on the
legacy corpus, so the venue leg has nothing to anchor against.

## 5b. The same check on the long windows, and the two that cannot be run

Nine trades is thin, so the alignment was re-run where there is more of it. Two of the four
declared windows turned out not to be runnable at all, and both refused rather than mis-align:

* **`wf` (2025-09-15..2026-03-31) cannot be compared.** The venue's own history begins
  2026-01-12 — read from the terminal, not assumed: first M15 bar 11:15 UTC, H1 11:00, H4
  10:00. **7,752 of `wf`'s bars exist only in the legacy file**, so there is no EA side to walk
  through most of it. The harness refuses outright: *"the python leg would run on a different
  market than the EA"*. Nothing was stopped and nothing was run.
* **`oos` (2026-04-01..09-16) is not certifiable as declared.** Run at its declared `Model=4`,
  the pass **aborted** after running: *"declared Model=4 (every tick based on real ticks) but
  ran on GENERATED ticks ... real ticks begin from 2026.09.04, but the window starts 2026.04.01
  — 156 day(s) of it ran on generated ticks"*. The tick-model rule from the 2026-09-20 work
  fired for real, on a real pass, and refused to let it be recorded.

So the long windows are compared on the model they can actually run. `wfv` (2026-01-12..03-31,
`+60`) and `oosc` (2026-04-01..09-16, `+120`) were added as declared windows that state
`Model=1` deliberately and can therefore never be certificates — `recorded_verdict` demotes a
key-matched PASS to REFUSED, which is what it did. What they do produce is the comparison:

| window | span | trades | keys (count / open / close / side) | max |dR| | over tol | verdict |
|---|---|---|---|---|---|---|
| **tickcov** (real ticks) | 2026-09-04..09-18 | 9 vs 9 | all agree | 0.0005 | 0 | **PASS** |
| **wfv** | 2026-01-12..03-31 | **53 vs 53** | all agree | 0.0005 | 0 | REFUSED (Model=1) |
| **oosc** | 2026-04-01..09-16 | **107 vs 107** | all agree | 0.0005 | 0 | REFUSED (Model=1) |
| veto | 2026-05-11..05-16 | 4 vs 4 | all agree | 0.0004 | 0 | REFUSED (Model=1) |

**173 trades, three windows, every key agreeing and `max|dR|` 0.0005 everywhere** — the entry
signals, the fills and the exits all line up on the venue's own bars. `anchor NO-ANCHOR` is
expected on every venue-corpus window: the frozen sweep anchor was computed on the legacy
series, so there is nothing for it to anchor against.

One boundary worth recording, because it is a measured property of the data and not a choice:
the venue series is stamped in **server wall clock**, so a single offset converts it to UTC
only *within one DST era*. The harness measures the offset per month and refuses a window that
crosses the step — `wfv` fits entirely in the `+60` era (Jan/Feb/Mar `+60`, April unresolvable),
`oosc` entirely in `+120`. That is also why the walk-forward corpus cannot be one continuous
window from 2026-01-12.

## 5c. Re-run after the duplicate series was retired, and what the archive still has to prove

Later on 2026-09-21 the legacy series was **retired from the data of record**: it moved to
`archive/frozen_corpus/`, hash-pinned by `configs/frozen_corpus.json`, readable only through
`midas_sweep.frozen_bars()`, and the parity windows now *declare* their corpus with no default
(`venue` for the four comparison windows, `frozen` only for `wf`/`oos`, which have no venue bars
to walk). Docs: **`docs/FROZEN_CORPUS_20260921.md`**.

Every window was then re-run on that wiring. Nothing moved:

| window | span | corpus | trades | open / close / side | max \|dR\| | over tol | tick model | verdict |
|---|---|---|---|---|---|---|---|---|
| **tickcov** | 2026-09-04 .. 09-18 | venue | 9 vs 9 | all agree | 0.0005 | 0 | 4 / **real** | **PASS** |
| **veto** | 2026-05-11 .. 05-16 | venue | 4 vs 4 | all agree | 0.0004 | 0 | 1 / unknown | REFUSED |
| **wfv** | 2026-01-12 .. 03-31 | venue | **53 vs 53** | all agree | 0.0005 | 0 | 1 / unknown | REFUSED |
| **oosc** | 2026-04-01 .. 09-16 | venue | **107 vs 107** | all agree | 0.0005 | 0 | 1 / unknown | REFUSED |

The two long windows are the answer to "do the keys still agree at scale": **160 trades across
`wfv` + `oosc`, 0 mismatches on any key, 0 trades over the 0.01R tolerance**, on top of the 13
real-tick trades. The REFUSED verdicts on the three `Model=1` windows are the harness holding
its own line: a key-matched PASS there is demoted because the tester ran on generated ticks, so
none of them can become a certificate. Only `tickcov` is certifiable, and it passed on real ticks.

### The archive still reproduces the evidence it was kept for — measured, not asserted

Re-running `scripts/midas_sweep.py` against the archived bytes reproduces **32 of 32 sweep
anchors exactly** (`n` and `net_r` for every mode × window), including the one parity reads as
its anchor: `REVERSE_DIRECTION/wf` = **151 trades, +1.474R** — the same law
`tests/test_midas_minlot_veto.py` pins as a literal. That is the point of keeping the bytes: the
numbers that predate the venue's history are still reproducible on demand.

**One correction, recorded because the first draft of the frozen-corpus page got it wrong.**
`artifacts/gold_wfo.json` and the verdict in `docs/GOLD_WFO_VERDICT_20260919.md` are *not*
archive-corpus numbers. `scripts/gold_walkforward.py` loads bars from the terminal at run time
(`mt5_data.load_m5`), and re-running it confirms which corpus that is: its own `data` block
reports **16,278 bars from 2026-01-12 13:15**, i.e. the venue's span, not the archive's 2024-08
start. So the walk-forward verdict is a **venue-corpus** number and was never at risk from this
retirement — a better outcome than assumed, and only knowable because the claim was measured. It
is now pinned by a test, so the inference cannot be re-made: `gold_walkforward.py` must not
start reading the archive, and the manifest must name the walk-forward artifact as a
non-consumer.

### A repair the retirement exposed in the live tooling

`scripts/midas_first_fills_audit.py` (the per-trade rule audit of the paper ledger) read
`XAUUSD_H1.csv` — a filename that no longer exists — so every stop-geometry check would have
reported UNVERIFIABLE on every future trade instead of failing. It now reads the venue's own
`XAUUSD_H1_upcomers.csv`, and it no longer grades a **server-stamped** ledger epoch against a
**UTC** session rule: the ledger is written with `TimeCurrent()` (broker server time), so the
session and Friday checks convert through the same pinned era table the parity clock uses, and
disclose `UNVERIFIABLE` for a month whose DST step makes the offset unresolvable rather than
assuming UTC. The era table now has one home (`midas_sweep.server_offset_*`); parity reads it
instead of holding a second copy of the DST rules.

## 6. What this does and does not mean

* **Does**: the two engines now describe one market, on one grid, one clock and one cost model,
  bar for bar, on the only window with real ticks — and the harness refuses, before stopping the
  terminal, a pass whose spread series is not the corpus it declared.
* **Does not**: change the walk-forward verdict — which is now known to be a *venue-corpus* number
  (§5c), so the retirement could not have moved it, and a re-run confirms it did not. Fold-mean t
  is still +0.52 against ≥ 1.5, gold's
  measured toll is still 0.02473 R against a +0.027 R best-ever edge, and **nothing is armed**.
  Parity passing says the engines agree; it says nothing about whether the strategy is good.
* **Open**: the EA's own INIT error text still tells the operator to run
  `scripts/midas_sweep.py --dump-spreadfile`, a flag that no longer exists — the harness derives
  the file now. Fixing the text means recompiling the EA and re-certifying this build, so it is
  deliberately left for a build that changes something else.
* **Open**: the news calendar file has the same provenance question (one staged file, two
  engines). It is currently produced by `MidasNewsProbe.mq5` reading the venue's own calendar, so
  both sides read one file — but nothing verifies it is the venue's, the way the spread series
  now is.
