# VERDICT PROVENANCE AUDIT — 2026-09-19

**The question.** Which operator scripts compute a *verdict* from data they never
verified they had read, and what do they need to say instead?

**The rule applied.** A verdict is admissible only when the run can state **(a)**
what it read, **(b)** how much of it, and **(c)** the period it covers. Where any
of those is unknown, the script must say so or refuse — never print a verdict
whose scope it has not established.

This is the third pass over the same fault class, which is why it is now a rule
rather than a list of fixes. The first two:

* `docs/STALE_FLAG_AUDIT_20260919.md` §5.2 — resolution: tools pinned to installs
  that no longer existed read nothing and reported anyway.
* §5.4 — the class check: `scripts/refusal_sweep.py` runs every diagnostic against
  an unreadable terminal and fails any that does not refuse.

This pass looks at a **different dimension**. `refusal_sweep` proves a tool refuses
when its *path* is unreadable. It says nothing about a tool that reads a
readable path and gets nothing usable — a zero-row file, an empty journal, a
dataset three days old. Those produce identical output to "nothing happened".

---

## 1. Found and fixed: `funnel_diff.py` graded an unopened window

The comparison table grades each funnel counter `match (0 = 0)` or
`match (~0 both sides)` when both sides are zero. Both sides being zero has two
explanations — *the funnel did not fire* and *nothing was read* — and downstream
they are indistinguishable.

Worse, the reader swallowed the distinction explicitly:

```python
try:
    txt = io.open(jf, encoding="utf-16", errors="replace").read()
except OSError:
    continue          # <- a journal that could not be read counted as "no firings"
```

With a resolved-but-empty install, every counter is 0, `journal_days` is empty,
and the summary reads **"funnel clean"**. That is the false green in its
comparison form.

**Fixed.** `grep_host` now returns `journals_seen` and `journals_unreadable`; the
run refuses (`exit 2`) when no journal was read at all, or when every journal
present was unreadable; and it prints the window it actually covered:

```
live window read: 3 journal(s) across 1 host(s), 3 day(s), 0 unreadable
```

## 2. Found and fixed: `demo_watchdog.py` certified an unstated period

`CERTIFIED (33 pass / 0 fail / 2 warn)` reads as *"the demo arm is healthy now"*.
It is computed from whatever rows are on disk, and **nothing stated the period**.

The fix adds `telemetry_window()`, which counts files, events, unreadable files
and unparsable lines, and reports the span:

```
window: 2026-09-04 21:26 .. 2026-09-16 21:15 — 271 event(s) from 2 file(s), newest 73.9h old
WARN  verdict covers a STALE window: newest telemetry event is 73.9h old
      (2026-09-16 21:15) — this certifies a past period, not the current arm
```

**And that is itself a finding.** The demo arm's telemetry ends **73.9 hours**
before the verdict was printed. Three days of silence was being certified as
health, because the script never asked. It now does, and says so.

An empty-but-readable telemetry set is a **FAIL** (files present, zero events
parsed); no parsable timestamps is a **WARN** that the period is UNKNOWN.

---

## 3. Already covered — no change needed

| script | why it is already sound |
|---|---|
| `atr_drift_monitor.py` | refuses (`exit 2`) and appends nothing when it cannot read the market — fixed in `refusal_sweep`'s first run |
| `midas_drift_drill.py` | refuses before seeding if it cannot resolve a chart |
| `go_live_rehearsal.py` | every check returns PASS/FAIL with its evidence lines; a missing terminal is a clean refusal |
| `set_chart_preset.py` | fails closed on a missing chart or absent `<inputs>` block |
| `verify_sizing_live.py` | refuses without a measured `order_calc_profit` basis; states equity, basis and stop in the report |
| `confirm-gate-open.ps1` | prints **UNKNOWN, not OPEN** and exits 1 without EA evidence |

Also verified by `refusal_sweep`: all eight refuse cleanly when the path is
unreadable, and none tracebacks.

---

## 4. The rule, going forward

**A verdict must state its provenance: what was read, how much, and over what
period.** Concretely, any script that prints a conclusion must:

1. **count what it read** — files, rows, journals, events — and report the count,
   not just the conclusion;
2. **never map "could not read" onto "nothing happened"** — a swallowed
   `OSError`/`JSONDecodeError` in a loop that feeds a verdict is a defect;
3. **refuse when nothing was read**, or print **UNKNOWN** and exit non-zero;
4. **state the period** — a result over stale data is a historical statement, not
   a health check, and the two must not print alike.

Two scripts now do all four. The rest of the class is covered for the path
dimension by `refusal_sweep.py`, and its coverage test derives the consumer list
from source so a new script cannot escape.

**Still open, deliberately recorded rather than silently left:** the remaining
verdict-emitting scripts in `scripts/` (`daily_scoreboard.py`, `paper_weekly.py`,
`check_wip_liveness.py`, the `boom*`/`cb_*` backtest family and others) were not
individually audited for the *period* dimension in this pass. The rule in §4 is
the standard they must meet; a follow-up sweep should assert it mechanically the
way `refusal_sweep` asserts the path dimension, rather than relying on review.
