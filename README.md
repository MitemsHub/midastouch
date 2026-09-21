# MIDASTOUCH

**A gold (XAUUSD) trading program for a prop-firm evaluation, built so that it refuses to do
anything it cannot justify.** One MT5 Expert Advisor, a Python engine of record that has to
agree with it trade for trade, and a research layer whose job is to reject things that are
not true.

There is exactly one live question here, and the repository is organised around it:

> **Is the strategy validated?** No — and this page says so in the same breath as saying the
> arm is trading, because both are true at once.

---

## Status — measured 2026-09-21

| | state |
|---|---|
| account | **1428765** @ `Upcomers-Server` (Upcomers Ltd.), XAUUSD, magic `7825001`, arm tag `U25` |
| EA | `mql5/MIDASTOUCH/MidastouchAI.mq5` → **MIDAS1.20**, compiled 0 errors / 0 warnings, deployed binary in step with its source |
| arming | **ARMED BY OPERATOR OVERRIDE** (`artifacts/live/armed.json`) — real orders go out |
| validation | **NOT VALIDATED.** The frozen walk-forward gate FAILED, and the walk-forward of the rule the arm actually trades also returned NOT VALIDATED |
| risk | **0.25%** per trade ($62.50 of the $25,000 evaluation) |
| fills | **0 opened, 0 closed.** The ledger holds 29 `ERA`, 58 `EQ`, 4 `NOFILLSUM` rows and no position row; the account's own history has no deal for this magic |
| why no fills | every evaluated bar so far was refused — mostly `no_trigger`, then `NO-TRIGGER(mac=-1)`: the H1/H4 regime is unaligned |
| supervisor | scheduled task `MitemshubPaperSupervisor` → this repository's own supervisor |
| suite | **1279 passed, 10 skipped** · live import closure 27 (22 entry points) · **0 dangling** |

Read that table for yourself — it is produced from the terminal, not from a document:

```bash
python scripts/live_readiness.py     # go/no-go, every line measured against the live terminal
python scripts/morning_status.py     # what happened: §3b is the gold arm
```

**Why an override is possible at all.** Arming is an **arming-record event**, never an input
edit. The preset generator refuses to emit a live-enabling preset while no arming record
exists; the operator's record then names the preset it authorises, and states what it does
not do. If you ever see `LIVE` on a chart with no record naming it, that is an incident.

---

## What it is

| piece | what it does |
|---|---|
| `mql5/MIDASTOUCH/MidastouchAI.mq5` | the EA: one instrument, one arm, one position at a time |
| `src/midas_prop/` | the prop layer — venue rules as arithmetic, sizing, legality, arming |
| `scripts/` | research and operations: walk-forward harnesses, the parity contract, MT5 drivers, audits |
| `tests/` | the pins — every refusal in this repo has a test that fails without it |
| `data/forex/xauusd/*_upcomers.csv` | **the data of record**: the venue's own bars, and the only forward-looking series |

## How the EA trades

| step | rule |
|---|---|
| **regime** | H1 EMA(20) **and** H4 EMA(20) must agree on a side; disagreement ⇒ no trade |
| **trigger** | on the closed **M15** bar: a Bollinger(20, 2σ) touch-back-inside, or RSI(14) at ≥ 70 / ≤ 30 |
| **mode** | `InpMode` selects how trigger and regime combine; the arm runs `ORIGINAL` (the gate certifies a different mode, and the arming record says so) |
| **stop / target** | stop = 2.0 × ATR(14) on H1 (always ATR-scaled); target = 2.0R; timeout 48 M15 bars |
| **session** | entries 06:00–20:00 **UTC** only; Friday cutoff, flat over the weekend |
| **gates before entry** | session · spread cap (spread > 1.5% of stop ⇒ veto) · staleness (no fresh bar for 30 min ⇒ stand down) · news stand-down · the prop governor below |

Sizing is 0.25% of equity, converted through the symbol's own tick value, checked against the
broker's **settled** figure (`order_calc_profit`), with the min-lot floor disclosed at init and
a veto when even the minimum lot would risk more than 15% of the basis. The authority order is
**settled > geometric > raw**, and a disagreement refuses rather than warns — a $250 intended
stop was once sized as $2,500 on this venue.

## The venue's rules, and how it refuses to break them

All four are enforced in `PropGovernorBlock()`, which gates **entries**:

| rule | guard |
|---|---|
| 3% daily loss | day-opening equity captured at the UTC rollover and reconstructed from the account's own deals after a restart; entries blocked once breached |
| 6% trailing "Dynamic Risk Shield" | measured off the equity high-water mark, derived from account history; entries blocked |
| 5% profit target | the evaluation's pass mark — a **phase transition, not a stop**: it is reported once and trading continues |
| 20% Best Day cap | one UTC day may contribute at most 20% of the target |

The shipped risk is 0.25% because it is the measured survivable size on this account: at the
EA's 1.00% default, **13 of 30 days** in the venue replay breached the $750 daily line; at
0.25% **none do** (worst day −$466.60, headroom $283.40 — and less still at the min-lot size
the account actually trades).

## Evidence: what is validated, and what is not

Nothing below is a claim; each line links the artifact or document that measured it.

- **The gate that failed, and the family it measured.** `artifacts/gold_wfo.json` — 568
  out-of-sample trades, +20.67R (+0.0364R/trade), fold-mean **t = +0.52** against a required
  ≥ 1.5, 12/30 positive folds, worst fold −8.06R. Verdict **NOT VALIDATED**
  (`docs/GOLD_WFO_VERDICT_20260919.md`).
- **That gate is not about this strategy.** It is a walk-forward of an M15 **EMA-stack**
  family — no Bollinger, no RSI anywhere in the engine that wrote it — while the EA trades
  BB/RSI. Measured: they agree on the same bar and direction **3.4%** of the time. The arming
  record's citation of it is now refused as evidence by `scripts/live_readiness.py` rather
  than presented silently (`docs/GOLD_WFO_EA_VERDICT_20260921.md` §2).
- **The walk-forward of the rule the arm actually trades** (144-configuration grid of the EA's
  own live inputs, 30 folds, two clock eras, the parity engine of record):
  `docs/GOLD_WFO_EA_VERDICT_20260921.md` — declared configuration **+12.819R over 30 folds,
  t = +1.07** against the required 1.96; the selected path reaches t = +2.00 only against a
  144-trial threshold of 3.573. **NOT VALIDATED.**
- **The session window costs nothing.** Measured with the gate off: 203 trades for +9.296R
  versus 136 for +11.767R with it on (`docs/GOLD_SESSION_HOURS_EA_VERDICT_20260921.md`). No
  per-hour claim is decidable: the declared requirement is ~4,209 trades per bucket.
- **There is no second rule to pair it with.** The repository's two rules overlap in the same
  direction **100%** of the time they overlap at all, daily-R correlation ≈ +0.55, and the
  combined worst day (−$486.71) is worse than either alone
  (`docs/GOLD_RULE_COMPLEMENTARITY_20260921.md`).
- **Parity is restricted to windows the venue can actually serve.** Real ticks begin
  2026-09-04; before that the tester manufactures them, and a pass on generated ticks can
  never be recorded as a real-tick pass (`docs/DATA_SCOPE_AND_CLOCK_20260920.md`).
- **The toll is the problem.** Gold's measured round trip is **0.02473R** against the only
  edge this program has ever measured (**+0.027R/trade gross**).

## Quickstart

```bash
python scripts/live_readiness.py          # is the arm actually able to trade, and authorised?
python scripts/morning_status.py          # what happened overnight
python scripts/compile_midas.py           # compile the EA (must stay 0 errors / 0 warnings)
python -m pytest tests -q                 # the suite; report the count, not an adjective
python scripts/audit_program_surface.py   # live import closure; the number that must be 0 is "dangling"
python scripts/midas_parity.py            # the EA-vs-python contract on a held window
python scripts/gold_wfo_ea.py             # re-run the pre-registered walk-forward of the EA's rule
```

**Interpreter.** This checkout has no `.venv` of its own (measured 2026-09-21); the commands
use the system `python` (3.14.6). The predecessor checkout has a venv — **do not borrow it**:
it carries another repository's `src/` on the import path, which is the cross-repository load
`tests/test_local_imports.py` exists to prevent.

## Repository layout

```
mql5/MIDASTOUCH/   the EA source, its presets, PRESETS.md
src/midas_prop/    the prop layer: venue rules as arithmetic, sizing, arming, paper broker
scripts/           research harnesses, the parity contract, MT5 drivers, status tools, audits
tests/             the pins
docs/              protocols, verdicts, playbooks, dated measurement records
configs/           account registry (account identity → symbol resolution), calendars, pins
data/              the venue's own bars — the data of record
artifacts/         run outputs: parity results, walk-forward artifacts, arming records
```

## Where the real documentation lives

| want | read |
|---|---|
| what is running, and how to read each signal | `docs/MIDASTOUCH_HEALTH_GUIDE.md` |
| the rule this arm trades, pre-registered and measured | `docs/GOLD_WFO_EA_PROTOCOL.md` → `docs/GOLD_WFO_EA_VERDICT_20260921.md` |
| the frozen gate and its pass criteria | `docs/GOLD_WFO_PROTOCOL.md` → `docs/GOLD_WFO_VERDICT_20260919.md` |
| the evidence standard: clocks, data scope, tick coverage, parity | `docs/DATA_SCOPE_AND_CLOCK_20260920.md` |
| the venue, the instrument, the rules, the measured numbers | `docs/MIDASTOUCH_GOLD_PLAYBOOK.md` |
| the presets and every input's meaning | `mql5/MIDASTOUCH/PRESETS.md` |
| operating rules once something is armed | `docs/MIDASTOUCH_PROTOCOL.md` |
| working rules for an agent in this repo | `AGENTS.md` |

Dated reports in `docs/` are **records**, not instructions. A live operator document may name
only scripts that exist in this repository — that is a test, not a convention
(`tests/test_operator_docs.py`).

## What this repository enforces on itself

- **Nothing is armed without a record.** The preset generator refuses to emit a live-enabling
  preset while no arming record exists.
- **The evidence must describe the strategy that trades.** `scripts/live_readiness.py` refuses
  an arming record whose cited walk-forward measured a different rule
  (`tests/test_arming_family_gate.py`).
- **No live path reaches dead code.** `scripts/audit_program_surface.py`; the number that must
  be zero is *dangling* — residue (research harnesses no live entry point imports) is not a
  defect and does not need to reach zero.
- **No file from the other program.** `scripts/program_boundary.py`, plus
  `scripts/cross_repo_duplication.py` so a shared asset cannot silently diverge.
- **Pre-register before measuring.** Grids, windows, required samples and decision rules are
  written before the numbers exist, and the artifact records the protocol's hash.
- **Report counts, not adjectives.** "1279 passed, 10 skipped", never "tests pass".

## History

MIDASTOUCH began as *Synthetic AI Trader* — Deriv synthetic indices, a Next.js dashboard,
Terraform — and that program is **retired**: its arms, terminals, presets and corpus were
deleted here on purpose. The package name survived as `src/synthetic_trader/` until the rename
to `src/midas_prop/` on 2026-09-20, because it holds no synthetic-index code and the old name
was only ever a leftover.

Where the predecessor's tooling is still visible on this surface it is labelled with what it
is and what to use instead, rather than left to look current. `tests/test_local_imports.py`
fails if anything here resolves outside this repository.

## Licence

See `LICENSE.txt`.
