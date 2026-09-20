# The persisted day stops, and supervised paper trading

**Code:** `src/synthetic_trader/execution/prop_execution.py` (§ day ledger),
`src/synthetic_trader/execution/paper_broker.py`, `scripts/paper_trader.py`
**Tests:** `tests/test_day_ledger.py` (35 pins), `tests/test_paper_broker.py` (23 pins)
**Status:** built and verified against the live Upcomers terminal. **No order-sending
path exists in either file**, and nothing is armed.

---

## 1. The day ledger: a stop that a restart cannot clear

A stop held in a variable is exactly the stop a restart defeats: the process comes back,
today's realised P&L is zero as far as it knows, and it re-enters a day it should have
stopped trading hours ago. So the halt is persisted in
`artifacts/live/day_ledger.json`, and **a halt already on disk is honoured on the next
start whatever anything else says**.

### The two stops, derived from the venue's own limits

| stop | default | where the number comes from |
|---|---|---|
| daily **loss** stop | **$375** | `loss_stop_fraction = 0.5` of the venue's own 3% daily limit ($750) |
| day **profit** stop | **$250** | `best_day_pct` (20%) of the profit target ($1,250) |

The profit stop is not an invented number: **it is the exact ceiling that
`docs/GOLD_BEST_DAY_STUDY_20260919.md` proves is *sufficient* for Best Day compliance**
at any total at or above the target. Applying it live is what turns the study's
arithmetic into a trading rule, rather than leaving it as a backtest constraint.

### Five cases, and the refusals are the interesting ones

| situation | outcome |
|---|---|
| no ledger file, and no broker figure for today | **`unknown_day_state` — REFUSES to trade.** We cannot know what today has already done, so we do not assume it has done nothing **or** that it has done everything. This is the case a naive restart falls into. |
| no ledger file, but the broker reports today's realised P&L | derive from the broker — authoritative and restart-proof by construction |
| ledger is from an earlier date | new day; intraday stops reset (the venue's daily limit and shield are still enforced) |
| ledger for today, marked halted | **stays halted**, `halted_by_disk=True`, reported as *"a restart does not resume a stopped day"* |
| ledger for today, not halted | recomputed from the reconciled figure |

### Reconciliation takes the worse number — and that is not the whole story

Two sources disagree about today by construction: the file (what the EA saw) and the
broker (what actually happened). `reconcile_realised` returns the **lower** figure, so a
deal closed while the EA was off still counts.

**A bug my own test caught, worth recording.** Taking `min()` is right for a loss and
*wrong for a profit*: with no ledger for today and the broker reporting **+$250**, `min(0,
250)` returned zero and the day-profit stop could never bind at a restart. The correct
rule is that with **no record for today** there is nothing to reconcile against and the
broker's figure is adopted outright; `min()` applies only when both sources have a figure
for the same day. That distinction is now pinned by
`test_a_corrupt_ledger_is_still_survivable_with_broker_truth` and its neighbours.

### The stop binds before the trade, not after it

Halting *after* a loss is too late to be a stop — the trade that took the day past its
allowance has already been placed. `trade_would_breach_day_stop` checks the **prospective**
risk against the remaining allowance before the order, so a trade that would cross the
stop is refused rather than placed and then mourned.

---

## 2. Supervised paper trading

`scripts/paper_trader.py` runs the whole layer on live Upcomers prices with simulated
fills: sizing, the venue rules, both day stops, and the arming gate.

**It sends no orders.** There is no order-sending path in the file and none is imported;
the only thing that moves is `PaperAccount.balance`, which never leaves the state file.

**Fidelity is the point.** The fill engine reproduces the research harness's semantics
exactly, because a paper run that resolves ties differently cannot confirm or refute the
backtest it is measuring:

* a gap past a barrier fills at the **open**, not the barrier;
* when both barriers sit inside one bar, the **stop** is assumed first;
* costs use the harness's own model (`1.073 bps` on the entry price + `$10`/lot round
  trip), not a nicer one.

**The one decision worth arguing about:** paper mode runs *without requiring* the arming
switch — that is the entire point, since arming needs a PASS record and nothing has one.
But it is never allowed to *look* armed: the arming state is printed on every run, written
into the state file, and `--require-arming` turns the gate back into a hard block so the
same runner becomes the live rehearsal the day something does pass.

    python scripts/paper_trader.py --once            # one supervised step
    python scripts/paper_trader.py --steps 60        # catch up over recent closed bars
    python scripts/paper_trader.py --once --dry-run   # decide, write nothing

### First live run — including a defect it exposed in my own defaults

```
[2026-09-18T07:45] OPEN  long  0.23 lots @ 4,377.15  stop 4,361.23  target 4,408.99  risk $366.18
[2026-09-18T14:15] CLOSE stop  0.23 lots @ 4,361.23  net $-379.28 (-1.04R)
[2026-09-18T14:15] HALT: daily loss stop ($-379.28)
decisions this step: 36 (34 blocked, 1 opened, 1 closed)
```

The stop fired after the losing fill and **every one of the 34 subsequent candidates was
blocked** — the intended behaviour, observed rather than asserted.

But the `attempts allowed` line that run printed is the honest finding:

```
attempts allowed: 1.00 full-size losing trades before the day stops (SINGLE-SHOT DAY)
  note: the venue limit would permit 2.00
```

**The default day-loss stop and the default per-trade risk are the same dollar figure**
($375 each), so out of the box the configuration permits exactly *one* losing trade per
day. That silently undoes the reason `size_position` defaults `safety_fraction` to 0.5,
which was to admit a losing streak longer than one. It is not a bug in either component —
it is an interaction between two defaults that were each defensible alone.
`DailyStopConfig.attempts_allowed()` now computes and reports it, and the runner prints
`SINGLE-SHOT DAY` when it applies, so the choice is visible instead of accidental.

### A harness assumption that was wrong for live operation

The runner's first version carried the backtest's `i + 1 < len(ts)` guard, which exists
because the harness must close a trade inside the same pass. In a live runner there is no
following bar yet — the real exit arrives later and is resolved by the next supervised
step — so that guard made `--once` **structurally unable to ever open a position**. Found
by running it, not by reading it.

---

## 3. What this does and does not establish

**Establishes.** The execution layer has now been exercised end to end against live
Upcomers prices: a measured dollar basis, a legal size, a simulated stop, a day halt that
blocked 34 subsequent entries, and state that survives a restart. The arithmetic is no
longer only arithmetic.

**Does not establish.** Any edge. The entry source is a **placeholder** — `--source
random` (seeded, so runs reproduce) or an operator-supplied queue in
`artifacts/live/paper_signals.json`. The runner exists to exercise the plumbing daily, not
to discover alpha, and no paper result from it should be read as evidence about a
strategy. There is also no live order path, by design: the funded account is not the test
harness.
