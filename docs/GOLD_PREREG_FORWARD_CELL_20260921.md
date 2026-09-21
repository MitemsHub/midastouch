# Pre-registration: the one stable state cell, tested on the forward record

**Declared** 2026-09-21T14:38:37Z (epoch **1790001518**), before a single forward trade exists.
**Harness** `scripts/gold_forward_cell_prereg.py` → `artifacts/gold_forward_cell_prereg.json`.
**Pins** `tests/test_forward_cell_prereg.py`.

State of the arm at declaration: **live under an operator override** (`artifacts/live/armed.json`)
on a walk-forward gate that **FAILED**, session 06–20 UTC, risk 1.0%. Its own forward ledger
(`MIDASTOUCH_paper_XAUUSD_U25.csv`) holds **0 closed trades** — 58 rows of flat `EQ,25000.00` and
three `ERA` stamps. Nothing in this document is a validation, and no part of it may be cited as one.

---

## 1. The hypothesis, and the selection it must disclose

**Cell:** `vol=normal | sess=06-12 | news=out`.

| axis | definition (unchanged from the study that found it) |
|---|---|
| volatility | the engine's **M15 Wilder ATR(14)** at the signal bar ÷ its **causal trailing median** over `ATR_LOOKBACK = 500` bars — `normal` is the ratio in **[0.8, 1.3)** |
| session (UTC) | **06:00 ≤ hour < 12:00**, where the hour comes from the **signal bar's open time** |
| news | **outside ±15 minutes** of a **HIGH** (top-tier) release, per `midas_prop.risk.news_calendar` — the module and window the EA's own gate reads |

**Where it came from, stated without softening.** `docs/GOLD_PERSISTENCE_STATE_20260921.md`
selected a state on H1 and froze it before touching H2. The H1 winner
(`vol=high|sess=17-22|news=out`, +1.2716R, t=+2.06) did **not** clear its priced threshold of
**2.8284** for a best-of-11 pick, so by that declaration **no state rule was carried** and the
verdict was `NO STATE RULE SURVIVES SELECTION`. This cell is one of the cells that *failed* to be
selectable — and it was then noticed because it happened to hold on **both** halves
(H1 +0.6210R, n=92; H2 +0.6918R, n=107).

So two things are true and both belong here:

- **Its effect size is contaminated.** The cell was identified by looking at H1 *and* H2. The
  +0.62R/+0.69R figures are what made it interesting, and they are why it **cannot** be used as
  the power basis of this test (see §3). They are cited in this document as the *origin* of the
  hypothesis, never as its expected value.
- **Its rank was not first.** It ranked third on H1 behind the two cells that flipped sign. That is
  evidence *against* a mechanism (it was not the best fit, only the most stable survivor) and it is
  recorded rather than explained away.

The forward record is the first data this cell has never been touched by.

## 2. What is being tested, exactly

The forward rows are stamped by the **deployed** configuration, not by the study's parent rule:

| component | deployed value |
|---|---|
| entries | mode ORIGINAL, M15 trigger (BB 20/2.0 touch + RSI 14), gated by H1 EMA(8/21/50) and H4 close vs EMA(20) |
| stop | `InpSlAtrMult = 2.0` × ATR(H1,14) |
| target | `InpTpMult = 2.0` ⇒ **+2.0R** |
| timeout / flat | 720 minutes |
| session | 06–20 UTC |
| news gate | **OFF** (`InpUseNewsFilter=false`) |
| risk | 1.0% of virtual equity |
| governor | all four venue rules gate **entries** (3% day / 6% trailing shield / 5% target / 20% Best Day) |

Two consequences that must not be glossed:

1. **The cell is a post-hoc STATE LABEL, not the arm's rule.** The arm trades through news; the
   `news=out` axis is applied by this harness to the finished record. A pass here says the
   *labelled subset* carried an edge, not that the arm gated anything.
2. **The exit geometry differs from the discovery study.** The cell's +0.62R was measured under the
   parent rule (stop 1.0×ATR, no target). The forward rows carry stop 2.0×ATR and a +2.0R target.
   A forward number is therefore **not** expected to reproduce +0.62R, and comparing it to that
   figure would be a category error.

**Primary statistic:** mean **net R** per closed **paper** trade (`OPEN`/`CLOSE` rows, which are the
rows the parity model stamps with `net_r`), restricted to rows whose signal bar falls in the cell.
Live-layer rows (`LOPEN`/`LCLOSE`) are **excluded from the statistic** and reported separately as
an execution appendix — they are a different instrument with different fills.

**Cutoff:** signal bar opening at or after epoch **1790001518**. Nothing before it counts, so the
sample cannot be assembled retrospectively.

**Frames, and the refusal built in.** Ledger epochs are broker **server** time; the session axis is
a **UTC** policy. The conversion uses the pinned era table (`configs/mt5/server_offsets.json` via
`midas_sweep.server_offset_for_month`). A month whose DST step makes the offset unresolvable
returns `None` and the row is marked **UNVERIFIABLE** — excluded, counted, never defaulted.

**Source of the label (amended, see §6).** Where the EA stamped its own state at fill time, the
label is taken **from the stamp** and the rebuild-to-UTC conversion above is kept as the CONTROL,
reconciled row by row and reported. The conversion below applies to the rebuilt path.

## 3. The declared sample, computed before any forward trade

Planning inputs, both fixed here: **MDE = +0.15 R/trade** (the program's own decidable bar, the same
one `docs/GOLD_FORWARD_PREREG_20260921.md` uses) and **sd = 1.10 R** (the deployed geometry's
measured dispersion: 1.08 combined / 1.09 armed-mode in that document's table — declared as a
planning constant, not measured on this sample).

| quantity | value |
|---|---|
| `t_required` (single hypothesis, N=1) | `selection_threshold(1)` = **1.9604** |
| **n_required** (decidability at MDE) | `power_trades(0.15, 1.10, 1.9604)` = **207 cell trades** |
| n for 80% power (`z_β = 0.8416`) | **423 cell trades** |

**Variance-only revision.** At the futility look (§4) the required final sample is recomputed from
the realized cell sd with the **same** MDE and the **same** formula. It may only **increase**. No
effect-driven revision is permitted, and no other parameter may be touched.

**The flow arithmetic, stated because it changes what this instrument is for.** The cell held **199
of 658** entries in the study = **30.2%** of the arm's flow. At the arm's measured rate
(≈0.6–1.1 entries/day) that is ≈0.18–0.34 cell trades/day, so **207 cell trades need roughly 1.7–2.9
years** and 423 need 3.5–5.9. This test therefore **cannot confirm the cell on a useful horizon. Its
usable role is falsification**: the kill rule in §4 is what can fire soon, and a positive answer is
a multi-year proposition the operator should know about now rather than discover later.

## 4. Verdicts, fixed here

| verdict | condition |
|---|---|
| **KILL** | at **n ≥ 51** cell trades, mean net R **≤ 0** → the cell is declared **dead**; it is not re-cut, and the configuration it describes is not to be revived without a new declaration |
| **NOT EVALUABLE** | n < 51 — reported with counts, projections and the reason, and never as "encouraging" |
| **FAIL** | n ≥ n_required (revised upward allowed) and **t < 1.9604** |
| **PASS** | n ≥ n_required **and** mean > 0 **and** t ≥ 1.9604 **and** the venue's rules held over the period (worst UTC day ≥ −$750) **and** no UTC day above 20% of accumulated profit |

A PASS is a **candidate**, not a validation. The futility look spends **no** efficacy alpha, so the
final threshold stays **1.9604**; there is no other look.

**Two secondaries, declared in advance so a failure of the news label cannot bury the wider cell and
a success cannot be cherry-picked from a family.** Both are reported regardless of the primary:

| | cell | threshold |
|---|---|---|
| secondary A (family of 2) | `vol=normal \| sess=06-12` — news axis unapplied | `selection_threshold(2)` = **2.2369** |
| secondary B (family of 3) | the **contrast** cell − non-cell | `selection_threshold(3)` = **2.3867** |

**Unlabellable rows.** A row whose signal bar lies beyond the data of record, or whose month has no
resolvable offset, or whose news state cannot be resolved (calendar missing / stale / uncovered /
empty at that time, in the module's own refusal phrases), **cannot be asserted to be in the cell**
and is excluded and counted. If more than **20%** of otherwise-qualifying rows are unlabellable
(the harness constant is `UNLABELLABLE_MAX = 0.20`), the harness fails loudly rather than reporting
a statistic on a shrinking subset.

A row is excluded only when **both** sources fail: an unusable *stamp* (`news=na`, `hour_utc=-1`,
`vol_ratio=0.0`, a half-written tail) falls back to the rebuilt label and is counted under
`stamp_unusable`, with its reason. `na` is a gap, never `news=out`.

**No re-specification.** After data arrives the cell, the statistic, the threshold, the MDE, the sd
and the cutoff may not change. Any change requires a new pre-registration with its own cutoff; the
old one is then a description of a past, not a test.

## 5. Who enforces this

`scripts/gold_forward_cell_prereg.py` reads the arm's own ledger, applies the cell mask through the
**same** `gold_persistence_state` axis constants that found the cell, and refuses to render any
verdict below the declared sample. `tests/test_forward_cell_prereg.py` pins the arithmetic in §3,
the thresholds in §4, and the refusal rules above, so a future edit that quietly moves the MDE or
the sample floor fails the suite instead of the operator.

## 6. Amendment A1 — the label is the arm's OWN stamp (2026-09-21, before any data)

**What changed.** The EA now writes the entry's own state into the ledger's `OPEN` row at fill time
(`InpRecordStateLabel`, v1.19e): five appended fields — `sig_ct`, `hour_utc`, `vol_ratio`, `news`,
`off_min` — describing the **signal bar**. The harness takes the label from that stamp where it can,
and keeps the rebuild as the control.

**Why, and this is the whole reason.** The declared mask rebuilt every row from the venue's data of
record, and §4 of this document already names the cost: a row newer than the last history refresh is
UNLABELLABLE, and a ledger can outlive the terminal's data folder. The 20% cap turns that from a
measurement into a stand-down, and a stand-down is not a test. With the stamp, the row carries its
own axes.

**What did NOT change**, and may not: the cell, the statistic, the cutoff, the MDE, the sd, the
sample floor (207), the futility look (51), the thresholds (1.9604 / 2.2369 / 2.3867), the news
window (15 minutes, HIGH only), the axis edges (0.8 / 1.3, and the four session bins) and the exit
table in §2. The amendment changes the INSTRUMENT's label source, at a time when the arm's forward
ledger holds **0 closed trades** — so it cannot have been written after looking at any of them.

**Why the stamp may be preferred rather than merely reported.** The stamp's volatility ratio is the
same statistic the study computed, from the same bars: a transcription of the EA's arithmetic
measures a worst relative deviation of **2.1e-08** against
`gold_walkforward.wilder_atr`+`trailing_percentile` over 34 sampled bars spanning all three
volatility bins, with the bin agreeing 34/34 (`tests/test_state_label_contract.py`). The 200-bar
recursion warm-up is what buys that bound, and a test pins that removing it loses the agreement.

**What the stamp cannot promise, stated here rather than discovered later.** Its `hour_utc` comes
from the EA's own clock cross-check (the two vendor clocks must agree), so an EA running at a venue
whose clocks disagree stamps `hour_utc=-1` and falls back; and its `news` flag uses the calendar
FILE, so a missing or stale source stamps `na` and falls back. Both fallbacks are counted
(`stamp_unusable`) and printed, and a disagreement between the stamp and the rebuild on a row both
can place is listed with both readings — because each such row could move a trade across a cell
edge, and silently absorbing that is how the forward test would stop being the registered one.
