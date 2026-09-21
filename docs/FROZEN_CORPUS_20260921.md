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
  moved to `archive/frozen_corpus/` (committed in `248db66`) and were then **deleted from the
  working tree the same day** — §5 records why, and gives the one-command restore.
- **`configs/frozen_corpus.json` pins every file** by SHA-256, size, bar count, first/last
  bar, provenance, and — importantly — by `what_it_is_not` and `superseded_by`, plus the
  deletion record and the list of citations that stopped being checkable. The pins are what
  make a restore verifiable rather than hopeful: the loader refuses bytes that do not match.
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

`wf` cannot be compared at all: 7,752 of its bars existed only in the research series, so there
is no EA side to walk through 75% of that span. The harness refuses it before stopping the
terminal rather than comparing two markets. `oos` cannot be *certified* because a `Model=4` pass
there runs on generated ticks (the venue's real ticks begin 2026-09-04) — it aborts on
`assert_declared_tick_model` when declared honestly, and is demoted to `REFUSED` when declared
on the model it can actually run.

So the certification question this program is carrying is not "which series do we use" — that
is now settled — but: **the only window this venue can certify per-tick begins 2026-09-04.**
See `docs/PARITY_ENTRY_SIGNALS_20260921.md` §5b.

## 4. The series was then DELETED, and this is exactly what that costs

Keeping the bytes had one real benefit — the certified arithmetic was computed on them — and one
real price: **it made the program's central evidence un-checkable by anyone without a copy**, on
a series that no fetch can reproduce. On 2026-09-21 the operator's call was to delete the copy
and re-point the law at the series that still exists. The record of that trade, so it is not
re-litigated from memory:

| citation | what happens to it |
|---|---|
| `tests/test_midas_minlot_veto.py` — the `n=151 / +1.474R` regression law | **RE-POINTED**, not dropped: the same claim (the min-lot veto does not move the engine of record's trade set) is now pinned on the venue's own bars — `n=53 / +14.256R` over 2026-01-12..03-31 at the account basis, `vetoed=0`, measured before pinning. |
| `artifacts/midas_sweep_20260917.json` — the sweep artifact `midas_parity` reads as `SWEEP_ANCHOR` (`REVERSE_DIRECTION/wf` = 151 / +1.474) | **No longer regenerable.** `midas_sweep.py:main` reads the deleted series and refuses. `anchor_match()` can never be satisfied again; it already reported `NO-ANCHOR` on every venue-corpus window, so no live pass loses a check it was passing. |
| `scripts/midas_sweep.py:main`, `scripts/midas_variant_research.py` | **Refuse** with the restore command, rather than silently running on the venue's bars and producing numbers that look like the certified ones. |
| `--window wf\|oos --corpus frozen` | **Unrunnable without a restore** — by construction now, not just by span. |
| `docs/MIDASTOUCH_PROTOCOL.md` §1, §10, §15; `docs/MIDASTOUCH_V2_REGISTER.md`; `docs/MIDASTOUCH_CLOSEOUT_20260917.md`; `docs/MIDASTOUCH_CLOSEOUT_20260919.md`; `docs/DATA_SCOPE_AND_CLOCK_20260920.md` | **True as history, no longer re-derivable.** Each cites 151 trades / +1.474R / max\|dR\| 0.0005 / the sweep anchor. None of them is wrong; none of them can be re-run without §5. |
| `docs/PARITY_VETO_AND_CORPUS_20260921.md` (the 21-bar disagreement), `docs/PARITY_ENTRY_SIGNALS_20260921.md` §5c (“32 of 32 sweep anchors reproduce”) | **A record now, not a check.** That is why the disagreement counts (3 / 18) are pinned in the manifest instead of living only in prose. |
| `docs/GOLD_ARMING_DECISION_20260921.md` (the certified-window row of the power table) | **Conclusion stands, sample gone.** The `+0.0098R/trade, sd 1.082` measurement is still the basis of the power argument; the 151 trades it came from can no longer be re-derived from a checkout. |

**What did *not* depend on it, named explicitly** — because the first draft of this page inferred
the opposite and had to be corrected: `artifacts/gold_wfo.json` and
`docs/GOLD_WFO_VERDICT_20260919.md` come from `scripts/gold_walkforward.py`, which loads bars
from the terminal (`mt5_data.load_m5`) at run time. Re-running it on 2026-09-21 confirms which
corpus that is: its own `data` block reports **16,278 bars from 2026-01-12 13:15** — the venue's
span, not the 2024-08 start of the deleted series. So the walk-forward verdict (fold-mean
t = +0.52) is a venue-corpus number and survives the deletion intact, as do the news
measurements (`docs/GOLD_NEWS_SENSITIVITY_20260921.md`, `docs/GOLD_NEWS_WIDTH_20260921.md`),
whose harness also imports `gold_walkforward`/`mt5_data`.

Everything else — the parity engine's `venue` path, the live EA, any new research — reads
`data/forex/xauusd/*_upcomers.csv`. `corpus_bars("venue", …)` never touches the archive, which
is pinned by test: the archive is made to raise and the venue path is asserted to be unaffected.

## 5. Restoring it, and the two traps the export carries

**Restore (one command): `git checkout 248db66 -- archive/frozen_corpus`**, then set the
manifest's `status` back to a kept state. Every file's SHA-256 is pinned, so a partial or edited
restore fails loudly instead of quietly changing what the old numbers describe. The tests that
compare against the actual bytes (`tests/test_parity_corpus.py`) skip while it is deleted and
carry that command in their skip message; the hash-pin and deletion-record tests run either way,
on a fixture of their own.

Two traps this export carries, recorded so they are not re-learned:

- **The `iso` column lies about its frame.** The venue's CSV has
  `time,iso,…` = `1768223700,2026-01-12T13:15:00+00:00` — an epoch and a string both stamped
  `+00:00`, both actually **server wall clock** (true UTC is 11:15). Anything that reads the
  `iso` column instead of shifting the epoch will be two hours out and will look consistent.
- **One offset does not convert the whole file.** The venue's stamps move with EU DST while
  gold's daily break follows US Eastern, so the offset steps at a different moment than either
  alone implies. A single offset is valid only *within one DST era*; `configs/mt5/server_offsets.json`
  records the measured eras and the parity harness refuses a window that crosses a step.## 6. Reproducing the numbers that still exist

```
python -m pytest tests/test_midas_minlot_veto.py -q    # the regression law, now on the venue's
                                                       #   own bars: n=53 / +14.256R, vetoed=0
python scripts/gold_walkforward.py                     # the walk-forward verdict (venue corpus)
python scripts/midas_parity.py --window tickcov --corpus venue   # the certifiable window
```

The deleted series' numbers need §5 first. `midas_sweep.py` and `midas_variant_research.py`
will tell you the same thing if you run them, in their refusal messages.

If one of the surviving checks stops reproducing, the first thing to establish is whether the
*bytes* moved or the *numbers* moved: the venue series is re-fetched from the terminal, so it
can legitimately grow, and `corpus_alignment()` will say so bar by bar.

## 7. When a pinned series stops pinning

A hash pin makes a series immutable, not eternal. Citations from it expire when:

- the pin is edited (the reader refuses, and the refusal names both hashes), or
- the bytes are deleted, as here — in which case the pins become the restore contract, and
the citation list in `configs/frozen_corpus.json` is what a reader is owed instead of the
numbers, or
- the series is superseded by a certification on the venue's own bars, at which point it is
  history rather than evidence — which is where this program already stands for the `wf`/`oos`
  windows.
