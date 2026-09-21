# The retired corpus: one series for forward-looking code — 2026-09-21

Two bar series both answered to "the gold bars" in this repository, and on 2026-09-21 that
cost a day of misdiagnosis and one wrong cost model. This is the record of which one was
retired, where its bytes went, what may still read them, and what a number cited from them
now means.

| | **venue** (data of record) | **frozen** (retired research series) |
|---|---|---|
| path | `data/forex/xauusd/XAUUSD_{M15,H1}_upcomers.csv` | `archive/frozen_corpus/XAUUSD_{M15,H1,D1}.csv` |
| what it is | the terminal's own history for the account the EA trades (1428765) | a separately fetched 50,000-bar series, fetched from the DERIV install |
| M15 | **16,224 bars**, 2026-01-12 11:15 → 2026-09-18 20:45 UTC | **50,000 bars**, 2024-08-02 17:30 → 2026-09-16 20:45 UTC |
| H1 | 4,063 bars | 14,414 bars |
| clock | server wall clock; needs the pinned offset (see `configs/mt5/server_offsets.json`) | true UTC |
| `spread` column | **points** (raw `4` → $0.04; `42` → $0.42) | **dollars** (raw `8` → $0.08) |
| readers | every window spec, the parity spread file, the live EA | `midas_sweep.frozen_bars()` only |

---

## 1. Why the duplicate had to go

The duplicates were not two designs. They were **two vintages of the same market fetched by
two different programs**, and nothing in the repository distinguished them beyond a filename.

Inside the tick-covered window (2026-09-04 .. 09-16) they **disagree about 21 bars** — 3 only
in the retired series, 18 only at the venue:

```
only in the retired series : 2026-09-07 17:45, 18:00, 18:15
only in the venue's        : 2026-09-04 20:45; 09-07 22:00 - 23:45; 09-11 20:45;
                             09-16 22:00 - 23:45
```

The retired series stops at the venue's daily break and resumes at 00:00; the venue's own
series holds the 22:00–23:45 evening. A 12-hour timeout opened at 08:45 therefore fired at
**22:15** on one series and at **00:15** on the other — a 7,200 s difference on a trade whose
entry agreed to the second. That is exactly the venue's +120-minute offset, so the divergence
was diagnosed as a residual clock fault for a day.

The second consequence was a cost model. The unit ambiguity above (points vs dollars) meant a
staged spread file from the wrong series was **not detectable as wrong**: the file handed the
EA a flat `$0.15` half-spread where the engine of record charged `$0.42`, a constant `$0.135`
per fill. On the tick-covered window that moved a long's stop `$0.136` further out, the market
ground through the two levels **105 minutes apart**, and pushed one timeout trade to
`|dR| 0.0102` — over the harness's tolerance. Worse, that same file is the EA's BAR-mode
membership filter (`SpreadAt() == 0` → the fill is skipped), so a wrong series is also a wrong
market. `preflight` had only ever asked whether the file existed.

Neither failure was an arithmetic error. Both were caused by having two things a caller could
not tell apart. So the fix is not a comment saying "use the venue's series" — it is that there
is only one series a forward-looking pass can reach.

## 2. What was done

- **The retired series left the data of record.** `data/forex/xauusd/XAUUSD_{M15,H1,D1}.csv`
  are deleted (they remain in git history; the bytes are preserved, below).
- **It moved to `archive/frozen_corpus/`**, beside the other archived evidence
  (`archive/v75_ledgers_20260916/`), and **is committed** — a retirement that deletes the
  evidence is not a retirement, it is an unfalsifiable claim.
- **`configs/frozen_corpus.json` pins every file** by SHA-256, size, bar count, first/last
  bar, provenance, and — importantly — by `what_it_is_not` and `superseded_by`.
- **`midas_sweep.frozen_bars(stem)` is the only reader.** It resolves its own path, verifies
  the hash against that manifest, and raises `SystemExit` on a mismatch or a missing file.
  There is no `load_bars("data/.../XAUUSD_M15.csv")` call site left that could find it.
- **Parity windows declare their corpus explicitly.** `--corpus {venue,frozen}`, no default:
  a pass that names neither refuses rather than inheriting a series. `venue` is the four
  comparison windows (`tickcov`, `wfv`, `oosc`, `veto`); `wf` and `oos` alone declare
  `frozen`, because they cannot be walked on the venue's own bars at all (§3).
- **The staged spread file is derived from the declared corpus**, not trusted from disk, and
  verified bar by bar (`verify_spread_file`) before the tester is launched.

## 3. What the retirement does NOT fix — and it is the important part

**The frozen certification is evidence on a series the funded venue cannot serve.** The venue
the EA trades has no XAUUSD history before **2026-01-12 11:15 UTC** — read from the terminal,
not assumed. That is not an inconvenience in the archived window; it is a property of the
venue.

Measured, at each window's asserted offset (`corpus_alignment`):

| window | declared corpus | bars only in the retired series | bars only at the venue |
|---|---|---|---|
| `wf` (2025-09-15 → 2026-03-31) | frozen | **7,752** | 24 |
| `wfv` (2026-01-12 → 2026-03-31) | venue | 169 | 24 |
| `oosc` (2026-04-01 → 2026-09-16) | venue | 18 | 39 |
| `tickcov` (2026-09-04 → 09-16) | venue | 3 | 18 |
| `veto` (2026-05-11 → 05-16) | venue | 0 | 1 |

`wf` cannot be compared at all: 7,752 of its bars exist only in the archive, so there is no EA
side to walk through 75% of that span. The harness refuses it before stopping the terminal
rather than comparing two markets. `oos` cannot be *certified* because a `Model=4` pass there
runs on generated ticks (the venue's real ticks begin 2026-09-04) — it aborts on
`assert_declared_tick_model` when declared honestly, and is demoted to `REFUSED` when declared
on the model it can actually run.

So the certification question this program is carrying is not "which series do we use" — that
is now settled — but: **the only window this venue can certify per-tick begins 2026-09-04.**
See `docs/PARITY_ENTRY_SIGNALS_20260921.md` §5b.

## 4. What may still read the archive, and why that is not a loophole

Three readers, each deliberate and each named:

1. **`scripts/midas_sweep.py:main`** — the research sweep. Its arithmetic *is* defined on this
   series: it writes the sweep artifact that `scripts/midas_parity.py` reads as `SWEEP_ANCHOR`
   (`artifacts/midas_sweep_20260917.json`, whose `REVERSE_DIRECTION/wf` entry is **n=151,
   net_r +1.474**). Re-basing the sweep would not be a bug fix, it would change the numbers the
   anchor reproduces. It is the **reproduction path**, and it says so in its own header.

   **A correction worth keeping visible, because this document got it wrong first.** The
   obvious candidate for "the frozen artifact" is `artifacts/gold_wfo.json` and the verdict in
   `docs/GOLD_WFO_VERDICT_20260919.md`, and the first draft of this page listed both as
   computed on this archive. They are not. `scripts/gold_walkforward.py` loads its bars through
   `mt5_data.load_m5(...)` — the terminal, at run time — and re-running it on 2026-09-21
   confirms which corpus that is: its own `data` block reports **16,278 bars from 2026-01-12
   13:15**, i.e. the venue's span, not this archive's 2024-08 start. So the walk-forward verdict
   (fold-mean t = +0.52) is a **venue-corpus** number and is untouched by the retirement. That
   is the better outcome, and it is only knowable because the claim was measured instead of
   assumed — which is the whole argument for this page existing.
2. **`tests/test_midas_minlot_veto.py`** — pins the certified regression law (`n=151`,
   `+1.474R`) as a literal, which is only meaningful against the bytes it was computed on.
3. **`--window wf|oos --corpus frozen`** — the two windows that have no venue bars. They exist
   so that running one is a *declaration* rather than a silent fallback, and so the reason they
   cannot run is printed instead of assumed.

Everything else — the parity engine's `venue` path, the live EA, any new research — must read
`data/forex/xauusd/*_upcomers.csv`. `corpus_bars("venue", …)` never touches the archive, which
is pinned by test: the archive is made to raise and the venue path is asserted to be unaffected.

## 5. Two traps this export carries, recorded so they are not re-learned

- **The `iso` column lies about its frame.** The venue's CSV has
  `time,iso,…` = `1768223700,2026-01-12T13:15:00+00:00` — an epoch and a string both stamped
  `+00:00`, both actually **server wall clock** (true UTC is 11:15). Anything that reads the
  `iso` column instead of shifting the epoch will be two hours out and will look consistent.
- **One offset does not convert the whole file.** The venue's stamps move with EU DST while
  gold's daily break follows US Eastern, so the offset steps at a different moment than either
  alone implies. A single offset is valid only *within one DST era*; `configs/mt5/server_offsets.json`
  records the measured eras and the parity harness refuses a window that crosses a step.

## 6. Reproducing the frozen numbers

```
python scripts/midas_sweep.py                          # the sweep on the frozen series ->
                                                       #   artifacts/midas_sweep_<date>.json,
                                                       #   REVERSE_DIRECTION/wf = n 151, +1.474R
python -m pytest tests/test_midas_minlot_veto.py -q    # the 151-trade regression law
python scripts/midas_parity.py --window wf  --corpus frozen
python scripts/midas_parity.py --window oos --corpus frozen
```

`python scripts/gold_walkforward.py` is deliberately **not** on this list: it reads the
terminal's own history (the venue corpus) and writes the walk-forward verdict, which therefore
never depended on the archive.

If any of these stops reproducing, the first thing to check is the archive's hash — the
manifest exists so that "the numbers moved" and "the bytes moved" cannot be confused.

## 7. When a pinned series stops pinning

A hash pin makes the archive immutable, not eternal. Citations from it expire when:

- the pin is edited (the reader refuses, and the refusal names both hashes), or
- a venue series with an overlapping span becomes available, which would make a *cross*-
  market measurement possible where today there is only the 21-bar disagreement — or
- the frozen artifact is superseded by a certification on the venue's own bars, at which
  point this archive becomes history rather than evidence.
