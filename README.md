# MIDASTOUCH

**The XAUUSD program on the Upcomers $25,000 evaluation** — one MT5 Expert Advisor
(`mql5/MIDASTOUCH/MidastouchAI.mq5`, account **1428765** @ `Upcomers-Server`, magic
7825001, arm tag `U25`) plus the Python layer that measures it, scores it, and refuses
to arm it without evidence.

**It is not trading, and it is not validated.** `InpLiveExecution=false` in every preset,
`artifacts/live/armed.json` is absent, and no gold signal has passed the frozen
walk-forward gate. Arming is an **arming-record event**, never an input edit: if you ever
see `LIVE` on a chart while that record is missing, that is an incident, not a milestone.
The strategy is real work; it has not earned a live order yet.

---

## 1. What is running right now

Measured on 2026-09-20, read-only, on this machine:

| surface | state |
|---|---|
| MT5 terminal | `terminal64.exe` running (build 6204, `C:\Program Files\MetaTrader 5`) |
| gold arm attached | **no** — the report prints `no MIDASTOUCH chart attached - gold arm not running` |
| live execution | **OFF** in every preset, and no arming record exists |
| validation | **NOT VALIDATED** — the walk-forward verdict of 2026-09-19 stands |
| paper supervisor task | `MitemshubPaperSupervisor` exists and is `Ready`, but its action runs the **predecessor checkout's** own supervisor script (in `Synthetic Indices Bot`, not here), so it supervises nothing in this repository |

Reproduce that table whenever you like:

```bash
python scripts/live_readiness.py    # go/no-go, measured against the running terminal
python scripts/morning_status.py    # what happened: [3b] is the gold arm, [1]-[3] are retired inventory
```

`scripts/live_readiness.py` is the one that matters. Every line is a measurement, not a
document lookup, and the exit code is non-zero unless every precondition holds — including
the scheduled-task leg, which is what catches the stale predecessor task above. The
reasoning behind each line, and the two legs that are *supposed* to look "off", are in
`docs/MIDASTOUCH_HEALTH_GUIDE.md`.

---

## 2. What the EA does when it trades

One instrument, one arm, one position at a time, intraday-first.

| piece | rule |
|---|---|
| **regime** | H1 EMA(20) **and** H4 EMA(20) must agree on a side; disagreement ⇒ no regime, no trade |
| **trigger** | on the **closed M15 bar**: a band touch-back (previous bar closed outside BB(20, 2σ), signal bar closed back inside) or RSI(14) at an extreme (≥ 70 / ≤ 30) |
| **mode** | `MODE_REVERSE_DIRECTION` (the certified default): the trade happens only when the trigger **contradicts** the regime, and then it takes the **regime's side** — buy strength or a failed dip inside an uptrend, sell the mirror in a downtrend |
| **stop** | 2.0 × ATR(14) on H1 — ATR-scaled always, never a fixed dollar distance |
| **target** | 2.0R = 2 × the stop; untouched positions time out after 48 M15 bars (720 min) |
| **session** | entries only 06:00–20:00 **UTC**; Friday cutoff 20:00 UTC, flat over the weekend by default |

Five gates stand between a signal and an order, all checked **before** the entry: the
session band, the spread cap (veto when spread > 1.5 % of the stop distance), the staleness
guard (no fresh bar for 30 min ⇒ stand down, which also covers gold's holidays), the news
stand-down, and the prop governor below.

The **news stand-down** (±15 min around top-tier USD releases, entry-only — it may never
block an exit) is implemented and ships **off** in every preset. It is fail-closed: a
source that is missing, stale, uncovered, truncated, or **empty** vetoes entries and names
which one it is, because an empty calendar means *cannot see the news*, not *no news*. The
events come from one shared file the EA refreshes from the venue's own calendar — the
Python API has no calendar at all, and the strategy tester refuses the call
(`GetLastError() = 4014`). It is off for two stated reasons: the certified corpus and the
walk-forward were measured without it, and this venue's calendar availability is still
unmeasured, so switching it on may do nothing or may hold the arm until the source is
real. `docs/MIDASTOUCH_HEALTH_GUIDE.md` §5a carries the decision, the refusal vocabulary,
and the single journal line that answers it.

**Sizing** is 1 % of equity per trade, converted through the symbol's own tick value with a
geometric identity check pinned against the broker's *settled* value (`order_calc_profit`),
with the min-lot floor disclosed at init and a veto when even the minimum lot would risk
more than 15 % of the sizing basis. The authority order is **settled > geometric > raw**,
and disagreements **refuse** rather than warn — that rule exists because a $250 intended
stop was once sized as $2,500 on this venue.

---

## 3. The venue's rules, and how the EA refuses to break them

Upcomers Thunderbolt Classic. All four are enforced in `PropGovernorBlock()`, which gates
**entries** — it does not manage or force-close open positions except the Friday flat, and
that limit is deliberate and documented.

| rule | the guard |
|---|---|
| **3 % daily loss** (one UTC day) | day-opening equity is captured **at the UTC rollover on every tick**, and reconstructed from the account's own closed deals when the EA starts mid-day, so a restart does not forget the day. Comments on — entries blocked once breached |
| **6 % trailing "Dynamic Risk Shield"** | measured off the equity high-water mark, derived from the account's own history (with a peak override for a restart inside a drawdown); entries blocked |
| **5 % profit target** | the evaluation's **pass mark**, and a challenge rule only — the funded phase has none. So reaching it is a **phase transition, not a stop**: the EA reports it once and keeps trading, because the funded account is where the strategy is supposed to earn. The funded phase's own limits (daily DD, max single-trade loss) are still unverified with the venue, so the challenge guards below stay in force and the transition print says so |
| **20 % Best Day cap** | a single UTC day may contribute at most 20 % of the target, anchored to the same rollover as the daily cap |

Which parts of that rule set are still **unverified by the venue** — and what the EA does
while they are — is stated in `docs/MIDASTOUCH_GOLD_PLAYBOOK.md` §3 and the rules audit
`docs/UPCOMERS_RULES_AUDIT_20260919.md`. The playbook does not claim an edge and neither
does this page: instrument selection is finished, and its measured answer is that gold's
toll is **0.02473 R per trade** against the only edge this program has ever measured
(**+0.027 R/trade gross**).

---

## 4. What is not running, and why

Stated plainly, because a front page that omits this is a sales page:

- **The walk-forward gate says no.** 568 out-of-sample trades, **+20.67 R** (+0.0364 R per
  trade), fold-mean **t = +0.52** against a required ≥ 1.5, 12/30 positive folds against a
  required 60 %, worst fold −8.06 R against a required > −3.0, median fold −0.72 R. It beats
  the seeded random-entry control; it fails four of six pre-registered legs, and one
  profitable path breaches the Best Day cap. Verdict: **NOT VALIDATED**, window closed —
  `docs/GOLD_WFO_VERDICT_20260919.md`, protocol in `docs/GOLD_WFO_PROTOCOL.md`.
- **Per-tick parity is restricted to windows the venue can serve.** This venue's real ticks
  begin **2026-09-04**; before that the tester manufactures them. The parity contract now
  records the tick model in every artifact and **refuses** a window it cannot cover (both
  previously certified windows are now REFUSED rather than FAIL), and a key-matched PASS is
  demoted unless the ticks were real. Decision and evidence:
  `docs/DATA_SCOPE_AND_CLOCK_20260920.md` §4b.
- **The EA's fills look faithful where the engines agree; the entry selection does not.**
  On the tick-covered window the tester produced 9 trades against the Python engine's 8,
  and on the trades where both engines pick the same bars the fills agree to within 0.02 R —
  so the open gap is **which bars signal**, not how they fill.
- **The scheduled supervisor is not this repo's.** See §1 — it points at the predecessor
  checkout, so nothing supervises the gold paper arm. Re-pointing it is an operator action
  with its own record, not a commit.
- **This venue's economic calendar has not been read successfully yet.** The tester cannot
  call it and the terminal's news base is 428 bytes, so the news gate's source is
  unproven here — which is why the gate ships off. The EA's own init line settles it in
  one read once the gate is switched on (health guide §5a).

---

## 5. Where the real documentation lives

| want | read |
|---|---|
| what is running, and how to read each signal | `docs/MIDASTOUCH_HEALTH_GUIDE.md` |
| the venue, the instrument, the rules, the measured numbers | `docs/MIDASTOUCH_GOLD_PLAYBOOK.md` |
| the evidence standard: clocks, data scope, tick coverage, parity state | `docs/DATA_SCOPE_AND_CLOCK_20260920.md` |
| the validation gate and its frozen pass criteria | `docs/GOLD_WFO_PROTOCOL.md` |
| the verdict that gate returned | `docs/GOLD_WFO_VERDICT_20260919.md` |
| the venue's rule set as audited | `docs/UPCOMERS_RULES_AUDIT_20260919.md` |
| the presets and every input's meaning | `mql5/MIDASTOUCH/PRESETS.md` |
| operating rules once something is armed | `docs/MIDASTOUCH_PROTOCOL.md` |

Dated reports in `docs/` (`*_2026091*.md`) are **records**, not instructions. A live
operator document may name only scripts that exist in this repo — that is a test, not a
convention (`tests/test_operator_docs.py`).

---

## 6. Repository layout

```
mql5/MIDASTOUCH/      the EA source (MidastouchAI.mq5), its presets and PRESETS.md
src/midas_prop/       the prop layer: venue rules as arithmetic, sizing/legality/arming,
                      the paper broker. (Called `synthetic_trader` until 2026-09-20; it
                      holds no synthetic-index code, and importing the old name is a
                      test failure by design.)
scripts/              research and operations: the walk-forward harness, the parity
                      contract, the MT5 drivers, the status tools, the audits
tests/                the pins — every refusal in this repo has a test that fails without it
docs/                 the playbook, the health guide, the protocols, the dated records
configs/              account registry (account identity → symbol resolution) and shortlists
data/                 this venue's own bars (the data of record)
artifacts/            run outputs: parity results, the walk-forward artifact, verification traces
```

Day-to-day commands:

```bash
python scripts/compile_midas.py          # compile the EA (0 errors / 0 warnings)
python -m pytest tests -q                # expect 0 failed; report the count
python scripts/audit_program_surface.py  # live import closure, dangling residue
python scripts/gold_walkforward.py       # re-run the research gate
python scripts/midas_parity.py           # the EA-vs-python contract
```

**Interpreter.** This checkout has **no `.venv` of its own** today — the commands above
are written for `python`, which on this machine is 3.14.6 at `C:\Python314`. The
predecessor checkout does have a venv: **do not borrow it.** It carries *that* project's
`src/` on the import path, which is the cross-repository load that
`tests/test_local_imports.py` exists to prevent — the same mistake, one layer down. If you
create a repo-local `.venv`, the operator documents may name it again: the interpreter pin
in `tests/test_operator_docs.py` requires any venv path a document names to exist.

---

## 7. The rules this repository holds itself to

These are enforced, not aspirational — each one is a script and a test:

- **Nothing is armed without a record.** The preset generator refuses to emit a
  live-enabling preset while no arming record exists (`scripts/gold_preset_upcomers.py`).
- **No live path reaches dead code.** `scripts/audit_program_surface.py` reports the live
  import closure and any dangling reference; the answer is expected to be **0 dangling**.
- **No file from the other program.** `scripts/program_boundary.py` fails on a foreign
  program file in either checkout; `scripts/cross_repo_duplication.py` fails when a shared
  asset (the paper broker in particular) silently diverges between them.
- **An operator document may name only tools that exist.** `tests/test_operator_docs.py`.
- **A pass has to be produced by the model it declares.** A tester run on generated ticks
  can never be recorded as a real-tick pass (`tests/mt5_tester_driver.py` + the recording
  rule in `scripts/midas_parity.py`).
- **The same clock on both sides.** The EA's tester epochs are converted from venue server
  time to UTC through a per-window pin that is **asserted** from the venue's own bars and
  refuses when the offset is not constant (`scripts/midas_parity.py`).

---

## 8. History: the predecessor program

MIDASTOUCH began as *Synthetic AI Trader* — Deriv synthetic indices (V75/V100), a Next.js
dashboard, Terraform — and that program is **retired**: its arms, terminals, presets and
corpus were deleted here on purpose, and its package name survived only as
`src/synthetic_trader/` until the rename to `src/midas_prop/` on 2026-09-20.

Two consequences you will meet in this repo:

- **The predecessor's README used to be this file.** It is retired from here: it now lives
  in its own checkout (`Synthetic Indices Bot`, remote `MitemsHub/mitemshub-indices`), and
  the earlier revision remains in this repository's history. Nothing in it described this
  account, and the `synthetic_trader` package name it refers to still resolves to *that*
  checkout — which is exactly how a test can pass while grading another repository's file.
  `tests/test_local_imports.py` fails if anything here resolves outside this repo.
- **Residue is reported, not hidden.** Where the predecessor's tooling is still visible on
  this surface (the retired inventory in `scripts/morning_status.py`, the stale scheduled
  task in §1, retired-era text inside the tester driver) it is labelled with what it is and
  what to use instead — rather than quietly left to look current.
