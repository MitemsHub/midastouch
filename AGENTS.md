# MIDASTOUCH — agent onboarding

> A prop-firm gold (XAUUSD) algorithmic trading program: one MQL5 expert advisor, a
> python engine of record that must agree with it trade for trade, and a research
> layer whose job is to refuse to certify things that are not true.

Read this before touching anything. It is the shortest path to not wasting a session.

## The two questions every session is reported against

1. **Does the system still refuse to do anything it cannot justify?**
2. **What is between us and a validated, armed strategy?**

Nothing else counts as progress here.

## Layout

| Path | What it is |
|---|---|
| `mql5/MIDASTOUCH/MidastouchAI.mq5` | The EA. Compiles via `scripts/compile_midas.py` (must stay 0 errors / 0 warnings). |
| `src/gold_prop/` | The XAUUSD prop-rule and execution layer (python). Never import the deleted `synthetic_trader`. |
| `scripts/` | Research harnesses, deploy/ops tooling, gates. |
| `configs/frozen_corpus.json` | The manifest of what data is of record and what was retired. |
| `configs/mt5/accounts.json` | Account → symbol resolution. Never hardcode a symbol. |
| `docs/MIDASTOUCH_PROTOCOL.md` | The binding protocol. Amendments are dated and numbered. |
| `artifacts/live/armed.json` | **The** arming record. Its existence arms nothing by itself; it names the preset it authorises. |

## Commands

```bash
python -m pytest tests -q                            # the suite (Windows; bash shell)
python scripts/compile_midas.py                      # compile the EA
python scripts/live_readiness.py                     # "are we actually trading for real?"
python scripts/morning_status.py                     # the arm's morning report
python scripts/audit_program_surface.py              # live import closure
```

**What the surface audit's numbers mean (measured 2026-09-21).** It reports `live closure
25 (22 entry points)` and `residue 46 (outside the closure)`. Residue is *not* a defect and
does not need to reach zero — it is every research harness that no live entry point imports,
including `gold_walkforward.py`. The number that must stay at zero is **dangling**: a live
module importing residue. Do not "fix" the residue count by wiring harnesses into the live
path.

**Interpreter.** This checkout has **no `.venv` of its own** (measured 2026-09-21: the
only venv on the machine belongs to the predecessor checkout, and putting its `src/` on
the import path is the cross-repository load `tests/test_local_imports.py` prevents).
Commands use the system `python` (3.14.6). Launchers resolve a repo-local `.venv` if one
is ever created and fall back to `python`, never to another project's venv.

## Hard rules

- **Never arm by editing an input.** Arming is an arming-record event. A preset with
  `InpLiveExecution=true` and no record naming it is a bug, not a shortcut.
- **Never write a validation claim you did not measure.** If a gate is unvalidated, say so
  in those words and say what would validate it.
- **The python engine and the EA are one contract.** Change both sides in the same commit
  or the parity comparison is meaningless.
- **Pre-register before measuring.** A rule written after the numbers exist is a
  description of the past, not a test.
- **Report counts, not adjectives.** "1076 passed, 10 skipped", not "tests pass".

## Skills


`.claude/skills/` holds the working skills. Load the relevant one before the kind of work
it governs:

- `quant-validation` — walk-forward, deflated Sharpe, PBO, purged CV. **Load this before
  any study that selects a configuration from data.**
- `test-automation-engineer` — determinism, flake elimination, state isolation.
- `test-results-analyzer` — turning raw results into statistically defensible claims.
