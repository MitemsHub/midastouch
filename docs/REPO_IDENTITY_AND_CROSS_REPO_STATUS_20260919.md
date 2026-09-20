# Repo identity and cross-repo status — what lives where, what is live, and what may cross

**Date:** 2026-09-19 · **State of record.** This is the single document that says which
repository owns what, which trading program is live, parked or closed, and what is
allowed to move between the two repos.

**Why it is needed.** There are two repos, one folder name that no longer describes its
contents, and — measured below — the *same* EA source and the *same* eight presets
physically present in both. Nothing in this project was ambiguous enough to cause an
incident yet, which is exactly why it should be written down before one exists.

---

## 1. What this repo actually is

**It is the venue and methodology layer.** It is not "a synthetic indices bot", and the
name has been wrong since the synthetic program closed. It owns:

| area | where |
|---|---|
| Upcomers rule model (3% daily, 6% shield, Best Day, min-hold) | `src/synthetic_trader/risk/upcomers_rules.py` |
| Execution layer: cost-aware sizing, prop legality, the arming switch | `src/synthetic_trader/execution/prop_execution.py` |
| The frozen validation gate and its criteria | `docs/SYNTHETIC_GATE_V2.md`, `docs/GOLD_WFO_PROTOCOL.md` |
| Cost model (spread, commission, the measured toll per stop geometry) | `scripts/gold_walkforward.py`, `docs/GEOMETRY_COST_STUDY_20260919.md` |
| Research harnesses and their verdicts | `scripts/gold_*.py`, `docs/GOLD_*.md` |
| Operator diagnostics, terminal resolution, refusal sweep | `scripts/*.py`, `docs/STALE_FLAG_AUDIT_20260919.md` |
| Rule/provenance audits | `docs/UPCOMERS_RULES_AUDIT_20260919.md`, `docs/VERDICT_PROVENANCE_AUDIT_20260919.md` |

### The name

**Target folder name: `Upcomers-Venue`.** The rename is staged in
`scripts/rename_project.py` (dry-run by default; `--apply` performs it). It moves the
directory **then** rewrites the live path references, in that order, so a failed move
leaves the repo consistent rather than half-renamed.

The **remote is deliberately left alone** — it stays
`https://github.com/MitemsHub/mitemshub-indices.git`. Renaming a remote is a two-step
operation (rename on GitHub, *then* `git remote set-url`), and pointing the remote at a
name that does not exist yet breaks `git push` silently. The script prints both commands
instead of guessing.

Path references in **dated historical documents are left as written** — the phase plans
under `docs/superpowers/plans/` say "Synthetic Indices Bot" because that is what the
folder was called on 2026-07-04, and a record that has been rewritten to match the
present is no longer a record. Only instructions meant to be followed *now* are updated.

---

## 2. The two repositories

| | **this repo** | **MIDASTOUCH** |
|---|---|---|
| local path | `Desktop/Projects/Synthetic Indices Bot` → `Upcomers-Venue` | `Desktop/Projects/MIDASTOUCH` |
| remote | `github.com/MitemsHub/mitemshub-indices` | `github.com/MitemsHub/midastouch` |
| branch | `synthetic-revival-v2` | `main` |
| owns | venue + methodology: rules, cost model, the portable gate, execution layer, operator tooling, research | gold strategy: `MidastouchAI.mq5`, the 8 gold `.set` pins, the certified corpus, ~25 gold test suites |
| EA folders present | `mql5/MIDASTOUCH`, `mql5/MITEMSHUB_AI`, `mql5/SynthCallExecutor.mq5` | `mql5/MIDASTOUCH` |

A third remote, **`midastouch-archive` → `MitemsHub/midastouch.git`**, exists in this repo
with its **push URL deliberately disabled** (`PUSH-DISABLED-use-mitemshub-indices`), so
this repo can never push over the gold one. That guard should stay.

---

## 3. Program status ledger

| program | venue | repo | status |
|---|---|---|---|
| **MitemshubAI** — V75 volatility-index synthetics | Deriv | this repo `mql5/MITEMSHUB_AI/` | **CLOSED.** Derive-era account unfunded and the terminal uninstalled. Parked, not deleted: the V75 research and gate are the portable machinery the gold work reuses. |
| **MIDASTOUCH** — gold (XAUUSDmicro) | Deriv | both repos | **CLOSED.** Went live unprofitable on a $39.58 account; its only trade closed at −$0.50. |
| **Upcomers XAUUSD research** | Upcomers | this repo `scripts/`, `docs/` | **RESEARCH ONLY, NOT VALIDATED.** Walk-forward v2: t = +0.70, 10/21 folds positive — below the frozen gate on every axis. |
| **Prop execution layer** | Upcomers | this repo `src/synthetic_trader/execution/` | **BUILT, INERT.** Sizing and legality verified live; the arming switch is OFF and no validation record has ever existed. |
| **SynthCallExecutor** | Upcomers | this repo `mql5/SynthCallExecutor.mq5` | **PLUMBING, NOT ARMED.** Executes call files; every terminal disposition now archives the file by rename so presence alone can never re-fire a call. |
| **Operator diagnostics** | — | this repo `scripts/` | **ACTIVE.** `refusal_sweep.py` is the entry point; it proves each diagnostic refuses rather than reporting an unearned verdict. |

**Nothing is live. Nothing is armed. No account is being traded by this repo.**

---

## 4. The boundary: what may cross

1. **Gold strategy assets are authoritative in `mitemshub/midastouch`.** That is
   `MidastouchAI.mq5`, the eight `MidastouchAI_*_gold.set` pins, and the certified
   corpus. This repo's `mql5/MIDASTOUCH/` is a mirror kept for harness convenience.
   **Never edit the EA or a preset in this repo** — an edit here reaches nobody and
   silently forks the strategy.
2. **Venue and methodology assets are authoritative here.** `midastouch` must not import
   the Upcomers rule model, the cost model or the arming gate: it is a strategy repo, and
   a strategy repo that also carries the venue's rules becomes a second source of truth
   for them.
3. **Nothing crosses without three things:** a hash recorded on both sides, the gate
   criteria frozen *where they will be consumed*, and the operator arming switch OFF.
4. **Compare `.set` files semantically, never by md5.** Measured, not theorised: the
   eight presets in the two repos are **semantically identical (0 differing lines after
   normalising line endings)** but differ in line termination — this repo's copies are
   LF, `midastouch`'s are CRLF. A hash comparison across repos will therefore report a
   difference on every `.set` file that exists in both, forever. A divergence check that
   always cries wolf is worse than none.
5. **`MidastouchAI.mq5` is byte-identical in both repos** (77,710 bytes, md5
   `930ad8f9ee…`). That is the one file where a hash comparison *is* meaningful, and it
   should be checked whenever either copy changes.
6. **Validate only on the venue's own price series.** Deriv's and Upcomers' XAUUSD are
   different brokers' books. Any dataset used to justify a decision on the Upcomers
   account must be traceable to Upcomers, and the provenance of the current gold window
   (2026-01-12 → 2026-09-18, loaded via `scripts/mt5_data.py`) should be confirmed and
   recorded before it is used to arm anything.

---

## 5. What this document does not claim

* It does not claim the engine, symbol suffix or spread model on Upcomers are fully
  characterised — the rule pack is audited, the *execution* venue's micro-behaviour is
  not.
* It does not claim the gold window's data provenance (rule 6) — that is flagged as an
  open item, not asserted.
* It does not authorise anything. Every row in §3 that could trade says, in its own
  words, why it cannot.
