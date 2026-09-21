# Parity: one market, and the vetoed path — measured 2026-09-21

Two questions, one instrument. The first was "why do the EA and the python engine disagree on
the tick-covered window (9 vs 8 trades, three side mismatches) now that the news rule and the
clock are ruled out?" The second was "run a BAR parity pass on a window where the news
stand-down actually vetoes an entry, so the vetoed path is compared and not just the no-op
case". The first answered itself in a way that changes what the second could mean.

| question | answer |
|---|---|
| why 9 vs 8 on tickcov? | **The two legs were reading different bar series.** The python leg read `XAUUSD_M15.csv`; the EA ran the terminal's own history. Inside the tick-covered window they disagree about **21 bars** (18 only in the venue's series, 3 only in python's) — and one of them is the venue's last bar before its daily break, which is where the first divergent trade closed. It is a data divergence that looked exactly like the +120 min clock error. |
| did it fix the comparison? | **Partly, and the remainder is smaller and better located.** On the venue's own bars, 6 of the 9 key-matched trades agree exactly (open, close, side) instead of 2, and the 7,200 s close gap is gone. The residual is **entry-signal level**, not management. |
| the veto window | **Found, declared, and run — and the vetoed path is still NOT comparable.** The engine of record refuses 2 entries there (2026-05-12 20:00, 2026-05-14 19:45 UTC); the EA's journal shows **no NEWS VETO at all**, because its own entry set differs from python's on that window for the signal-level reason above. |

---

## 1. The corpus divergence, and why it read as a clock fault

`scripts/midas_parity.py` built the python leg from `data/forex/xauusd/XAUUSD_M15.csv` (a
separately fetched 50,000-bar series beginning 2024-08) while the tester ran the EA on the
terminal's own history — the series the live EA trades. `XAUUSD_M15_upcomers.csv` is that
history; `venue_bars_utc()` now shifts it into UTC by the offset the window asserted.

Inside the tick-covered window (2026-09-04 .. 2026-09-16, 800 python bars vs 815 venue bars):

```
only in XAUUSD_M15.csv : 2026-09-07 17:45, 18:00, 18:15
only in the venue's    : 2026-09-04 20:45; 2026-09-07 22:00 - 23:45; 2026-09-11 20:45;
                         2026-09-16 22:00 - 23:45
```

Read what that does to the first divergent trade. Python's series stops at 18:15 and resumes
at 00:00, so the 12-hour timeout opened at 08:45 could only fire at the first close after the
gap — **00:15**. The venue's own bars include 22:00, so the same timeout fired at **22:15**.
A 7,200 s difference, which is precisely the venue's +120-minute offset, on a trade whose
entry agreed to the second. Every reading of that pattern — "a residual clock asymmetry",
"the close is written in a different frame" — is wrong. It is two different markets.

With the venue's series in place, the same window gives **6 of 9 keys matching exactly**
(09-07, 09-08, 09-14, 09-15, and both 09-16 trades), against 2 before, and the remaining
R differences are within the harness's 0.01R tolerance.

### The residual, located

| | python (venue series) | EA |
|---|---|---|
| 09-07 08:45 → 22:15 TIMEOUT −1 | ✓ | ✓ |
| 09-08 08:15 → 20:15 TIMEOUT −1 | ✓ | ✓ |
| 09-09 08:00 → 20:00 TIMEOUT +1 | **extra** | — |
| 09-10 10:45 → 12:45 TP −1 | — | **extra** |
| 09-10 12:00 vs 13:00 → 12 h TIMEOUT −1 | 1 h early | 1 h late |
| 09-11 14:00 → 18:15 SL +1 | — | **extra** |
| 09-14, 09-15, 09-16 ×2 | ✓ | ✓ |

Where the two engines agree on an entry, they agree on its **management** to the second: the
12-hour timeout closes on the same bar, at the same instant, in the same direction. Everything
that still differs is an **entry signal** — one engine signals a bar the other does not, or one
bar apart. That rules out exit logic, the clock, the sizing path and the cost model as
explanations, and points at the entry-condition stack (M15 BB touch and RSI, the H1/H4 macro
EMA gate, the stop distance that comes from the H1 ATR).

### The harness now refuses to compare across two markets

`corpus_alignment()` counts the disagreement inside the window, and `run_one_mode` refuses a
pass whose python leg is not on the venue's series when it is non-zero — before the live
terminal is stopped, so the refusal costs nothing. `python_build_data(corpus="legacy")` is
unchanged, so the numbers recorded on that corpus stay reproducible; `--corpus venue` is the
data of record, and the artifact now records which one a pass used (`python_corpus`,
`corpus_alignment`).

## 2. The veto path

The tick-covered window contains **no entry the stand-down removes** — the engine of record's
own census over 2026-09-04..09-16 is zero — so a pass there compares the no-op case. Over the
frozen window the vetoes fall on 2026-05-12 20:00, 2026-05-14 19:45, 2026-06-11 20:00,
2026-06-12 13:15 and 2026-06-17 20:00 UTC, so a `veto` window (2026-05-11 .. 2026-05-16 UTC,
tester dates 2026.05.11 .. 2026.05.18 server) was declared to cover two of them.

Two things about that window are declared rather than assumed, and both are pinned by tests:

* **`Model=1`.** The venue's real ticks begin 2026-09-04, so a `Model=4` pass over May is
  downgraded to generated ticks and refused by `mt5_tester_driver.assert_declared_tick_model`
  — which is right, because this program's certification model is per-tick. What the window is
  for is the bar-level question "do both engines refuse the same entry?", which needs no
  intrabar ordering. On `Model=1` the tester states no tick model at all, the harness records
  `used: UNKNOWN`, and `recorded_verdict` demotes any key-matched **PASS** to **REFUSED**. A
  pass here can never be reported as a certificate, by construction.
* **`corpus: venue`**, because the comparison is worth nothing otherwise.

Result (`python scripts/midas_parity.py --window veto --news`, artifact
`artifacts/midas_parity_result_20260921_1044.json`, both engines with the gate ON):

```
python (REVERSE_DIRECTION) 2 trades +0.100R   engine of record vetoed 3 signals
EA BAR ledger              3 trades +0.106R
  05-13 16:45 -> 05-14 04:45  side -1 TIMEOUT   both engines, |dR| 0.0001
  05-15 06:45 -> 05-15 18:45  side -1 TIMEOUT   both engines, |dR| 0.0051
  05-11 14:15 -> 05-12 02:15  side +1 TIMEOUT   EA only
  05-12 20:00, 05-14 19:45                      python only (both refused by the veto)
PARITY: FAIL
```

**The EA's journal has no `NEWS VETO` line in this pass** — nothing but the amendment note,
`NEWS FILTER ON — … usable`, and the start banner. So the two entries the stand-down removes
are absent from the EA because the EA never signalled them, not because it refused them. The
vetoed path is therefore **not yet compared**: the same signal-level divergence that is the
residual in §1 sits in front of it. What the pass does establish is that the amendment is
runnable on both sides on a window with real vetoes, that the non-vetoed trades agree to the
second, and that the extra EA entry (05-11 14:15) is not a veto artefact.

**What would make the veto path comparable:** entry-signal parity. The next measurement is a
bar-by-bar diff of the entry conditions at the five instants above — starting with the H4
derivation, since python builds H4 from the venue's H1 series (`h4_series`) while the EA reads
the venue's own H4 bars, and the macro gate is H1+H4 EMA20. Until that agrees, no pass can say
whether the stand-down refused the same bar on both sides.

## Reproduce

```
python scripts/midas_parity.py --window tickcov --corpus venue   # the aligned window
python scripts/midas_parity.py --window veto --news              # the vetoed path (Model=1)
python -m pytest tests/test_parity_corpus.py -q                  # the pins above
```

Artifacts: `artifacts/midas_parity_result_20260921_1044.json` (veto window),
`artifacts/midas_parity_result_20260921_0918.json` (tickcov, pre-fix, for the 9-vs-8 record).
