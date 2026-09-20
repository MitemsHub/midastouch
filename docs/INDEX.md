# docs/INDEX.md — one authoritative document per question

**Why this exists.** Before 2026-09-19 the repo had five documents that each read as
"current state" and none that said which one won: `OPERATING_SUMMARY.md`,
`LIVE_READINESS.md`, `MILESTONE_MEMO_v2635.md`, the root `PRODUCTION_CONFIGS.md`, and
`MIDASTOUCH_V2_REGISTER.md` named four different deployed versions (v26.35 / v26.38 /
v27.00) and two different programs. An operator had no way to tell the live truth from the
frozen history.

**The rule:** one question → one authoritative file. Everything else is evidence (frozen,
citable, never edited after the fact) or non-authoritative (kept deliberately, marked).

---

## Synthetic indices (the active program)

| Question | Authoritative file |
|---|---|
| What is the current state of this program, what changed and why? | **`docs/SYNTHETIC_REVIVAL_20260919.md`** |
| What exactly is deployed, and which preset means what? | **root `PRODUCTION_CONFIGS.md`** |
| May this EA binary/preset be deployed at all? | **`scripts/deploy_manifest.txt`** (byte pins; `sync-mt5.ps1` is fail-closed on a mismatch) |
| What is the trading geometry the revival is testing? | `docs/GEOMETRY_COST_STUDY_20260919.md` (Phase 3) |
| What authorizes real money? | `docs/SYNTHETIC_GATE_V2.md` (Phase 5) |
| What are the per-instrument specs and minimum-equity floors? | `docs/INSTRUMENT_SPEC_MAP.md` (generated) |
| What are the rules of a prop-firm venue (Upcomers), and does it offer synthetic indices? | **`docs/UPCOMERS_RULES_AUDIT_20260919.md`** (§13: why it structurally cannot, and where synthetics-only prop venues *do* exist) |
| **Which instrument should we trade on Upcomers, and what does each one cost?** | **`docs/UPCOMERS_MEASURED_COST_RANK_20260919.md`** (measured; supersedes the assumed-spread claims in `docs/UPCOMERS_INSTRUMENT_SELECTION_20260919.md`) |
| Why did the MT5 terminal refuse to connect, and is this venue 24/7? | `docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` §1–§2 |
| **Which instrument do we build the EA on, and why?** | **`docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` §7 — decision: `XAUUSD`, after the sizing-feasibility gate excluded `JPCJPY.c`** |
| **Should MIDASTOUCH be restructured into a new XAUUSD program, and where does gold work belong?** | **`docs/PROGRAM_STRUCTURE_DECISION_20260919.md`** — decision: no restructure, no reused name, no new EA folder; venue layer here, strategy layer in `MitemsHub/midastouch`. |
| Is the gold VPS surface still live, and is anything of the gold program running? | **`docs/GOLD_SURFACE_RETIREMENT_20260919.md`** — RETIRED 2026-09-19; account defunded, terminal uninstalled, watchdog retired. Evidence archived under `artifacts/archive/gold_surface_retirement_20260919/`. |
| **Did the second gold iteration validate anything, and what did the corrections change?** | **`docs/GOLD_V2_RESEARCH_20260919.md`** — STILL NOT VALIDATED (4/6 criteria), but the reason is now measured: the toll was 2.3× the quoted floor, v1's random control never randomised timing, and the failure mode is regime dependence. Run: `scripts/gold_wfo_v2.py` + `scripts/gold_geometry_study.py` |
| **What is the bracket's own bias, with no entry signal at all?** | `scripts/gold_geometry_study.py` — the assumption band and the drift-neutral coin flip; stops below 1.5 ATR are unmeasurable (±0.073R at 0.5 ATR) |
| Is any marker/flag/state file in this repo asserting an era that has ended? Does a safety control still report a verdict it cannot evidence?** | **`docs/STALE_FLAG_AUDIT_20260919.md`** — swept for existence-based flags after the VPS marker; retired the gold-era clock-offset baseline (live consumer, false alarm) and rewrote `confirm-gate-open.ps1` (false green). All seven terminal-hash-pinned operator scripts now resolve their target from evidence on disk via `scripts/mt5_terminals.py` and **refuse to report a verdict from a path they could not read** — no terminal hash remains in live code. §5.3: installs are now identified by the **account number in their journals** (`configs/mt5/accounts.json`), not by recency, so a dead Deriv-era install that merely *booted* can never be mistaken for the live one. §5.4: `scripts/refusal_sweep.py` makes the whole class automatic — it runs every diagnostic against an unreadable terminal root and passes a case only when it exits non-zero, names its cause, does **not** traceback, and writes nothing that could be read as a result. Its first run found three defects (two tracebacks, and a monitor exiting **0** while appending a non-measurement to the calibration record) plus a PowerShell tool that had been re-implementing resolution instead of delegating. `--self-check` proves the sweep can fail; a test derives its coverage so a new consumer cannot escape it. Records the residual hazard of the stale trade instruction in `Common\Files`. |
| What is the pre-registered protocol for testing a strategy on gold? | **`docs/GOLD_WFO_PROTOCOL.md`** (frozen before data; the grid, folds and V1–V6 criteria) |
| **Did any configuration produce an edge on gold out of sample?** | **`docs/GOLD_WFO_VERDICT_20260919.md` — NO. NOT VALIDATED, 4 of 6 legs failed, t = +0.52** |
| Is the popular "20/50 EMA on M15 gold" system worth trading? | **`docs/EMA_CROSS_XAUUSD_ASSESSMENT_20260919.md`** — measured: win rate 24–31% vs the claimed 45–50%, every variant negative (run: `scripts/ema_cross_gold_test.py`) |
| Run the gold walk-forward / read its artifact | `scripts/gold_walkforward.py` → `artifacts/gold_wfo.json` (+ `tests/test_gold_walkforward.py`) |
| What are the account's hard risk limits, as runnable arithmetic? | `src/synthetic_trader/risk/upcomers_rules.py` (+ `tests/test_upcomers_rules.py`) |
| **How do the rules become a lot size, and will it refuse a trade that breaches them? Can the EA be armed today?** | **`docs/PROP_EXECUTION_LAYER.md`** — sizing verified against the broker's own `order_calc_profit` (it catches the live 10× spec error), an explicit refusal when the minimum lot exceeds the budget, the Best Day rule enforced as a day-level *profit cap*, and a fail-closed arming switch that **refuses the real gold result even when the operator arms it deliberately**. Run: `scripts/verify_sizing_live.py --symbol XAUUSD --stop-price 9.89` (+ `tests/test_prop_execution.py`) |
| **Why does the gold strategy's profit concentrate into single days, and can it be fixed to pass the 20% Best Day cap?** | **`docs/GOLD_BEST_DAY_STUDY_20260919.md` — NO, and the reason is structural.** Best Day is **scale-invariant** (the share is 55.5% at 0.1×, 1×, 10× and 100× the position size), so sizing can never fix it; and all 8 cap designs tested (3 per-day profit caps, 3 trade-count caps, 1 combo + baseline) were prop-infeasible — **0/8**. The mildest cap turns +62.47R into **−14.28R with selection held fixed**. Profit is not carried by a few lucky trades (top 1% of trades = 1.9% of gross profit); it is carried by day-level aggregation — `corr(trades/day, day R) = +0.538`, and a day cap flips that to −0.626 by truncating the trending days. The one rule that *is* fixable by sizing is fixed easily: risk **$20.01–$32.76/trade** satisfies the target and the daily limit with **0 breaches** at ~$20. Run: `scripts/gold_best_day_study.py` (+ `tests/test_best_day_cap.py`) |
| **Can a stop survive a restart, and can the whole layer be exercised without risking the account?** | **`docs/PAPER_TRADING_AND_DAY_STOPS.md`** — a persisted day ledger (`artifacts/live/day_ledger.json`) with a $375 loss stop and a $250 day-profit stop (the second is exactly the Best Day ceiling the study proved sufficient), which **refuses to trade when the day's state is unknown**, and honours a halt already on disk *whatever else says otherwise*. First live paper run: a losing fill tripped the loss stop and blocked the next **34** candidates. Also caught a default interaction in my own config: the loss stop and one trade's risk are both $375, so the defaults permitted **1.00 losing trades/day** — the opposite of what `safety_fraction=0.5` exists for. `scripts/paper_trader.py` runs the full layer on live prices with simulated fills and **sends no orders**. (+ `tests/test_day_ledger.py`, `tests/test_paper_broker.py`) |
| **Does a low-frequency gold signal pass the gate, and does the Best Day cap stop being a problem?** | **`docs/GOLD_DAILY_ONE_PROTOCOL.md` — pre-registered, then run: NOT VALIDATED (6/8 legs), with two of the leg results CORRECTED after the fact.** What worked: best-day share **9.6%** vs a 20% cap (v2 was 55.5% and unfixable at any size) — the one-entry-per-day cadence solves concentration structurally; and the **H4 regime bit is load-bearing** (always-long *loses* 8.34R, H4 inverted collapses to noise), so the signal is not a disguised long bias. What failed: **t = +1.33** against a 1.5 bar, and **V4 does not survive adequate replications** (+12.83R actual vs a 200-rep null p95 of +13.02R; the original PASS rested on a 32-rep quantile that is ambiguous by 7.5R). **V8 was mis-implemented and now PASSES** — a legal size exists ($233.99/trade, 0 breaches) — which exposed the real constraint: **the trailing shield caps size at 33% of what the single-day bound implies** (worst run: 5 consecutive losing days, −5.13R; worst peak-to-trough 6.41R against a 12.83R total). Run: `scripts/gold_daily_one.py`, `scripts/gold_daily_one_ablation.py` |
| **Does a PROSPECTIVE sizing control clear all eight gate legs?** | **`docs/GOLD_PROSPECTIVE_SIZING_PROTOCOL.md` — NO. Pre-registered, run: 6/8, and `legs that changed: NONE`.** Sizing every trade so the measured 5-day run cannot breach the 6% floor leaves **V1–V7 identical**, because those legs are computed from `net_r` while risk enters `prop_compat` as a post-hoc scalar — and V8 is an existence claim, so it is size-free too. **The gate is decided without reference to sizing**, demonstrated rather than argued. V8 PASSES at the bisected survivor ($233.99/trade); V4 and V6 fail, and no risk plan moves a t-stat. The run caught **two bugs in my own work, both in the dangerous direction**: `max_dd_pct` is **6.0, a PERCENTAGE**, so the first ceiling returned **$28,673.80 per trade where only $233.99 survives (≈120× too high)**; and measuring the room from the peak rather than from current equity left the corrected form **22.5% optimistic** — so the closed form is a *pre-filter*, the sequence simulation is the authority. Run: `scripts/gold_prospective_control.py`, `tests/test_prospective_sizing.py` |
| **Is the 1.073 bps cost model the reason the gold signals fail?** | **`docs/GOLD_COST_SENSITIVITY_PROTOCOL.md` — NO. Pre-registered, run, fidelity PASS (+12.83R / 119 trades / t +1.33 / null p95 +13.02R reproduced exactly). `scripts/gold_cost_sensitivity.py` sweeps spread multipliers m ∈ {0, 0.5, 1, 1.5, 2, 3, 5, 10}, re-running the 200-rep null at every level. Break-even is **6.40 bps (m = 5.97)** — the model could be **6× wrong** before the edge dies. And the decisive result: **V4 and V6 fail at EVERY level including m = 0 (free trading)** — at zero cost the arm still returns +13.40R against a null p95 of +15.44R, and the best t anywhere on the curve is **+1.46 vs a 1.5 bar**. So DAILY-ONE fails for **signal** reasons, not cost, and no live spread measurement can change it. `scripts/gold_seq_cost_probe.py` shows DAILY-SEQ's three arms are cost-independent too (all still fail with the spread switched off entirely). Live spread still unmeasured — market opens 22:00 UTC; per the frozen rule a measured `m ≤ 1` leaves every verdict standing, and the weekend quote of 60 pts = **1.37 bps (m ≈ 1.28)**, which changes the leg set not at all. Tests: `tests/test_cost_sensitivity.py` (pins the silent no-op: a patch that misses the pricer's module leaves a flat, believable table). |
| **Can the trailing shield be fixed with a rule that reacts to losses?** | **`docs/GOLD_DAILY_SEQ_PROTOCOL.md` — NO. Pre-registered, run, and the hypothesis is FALSIFIED (3/8 legs).** The control reproduced DAILY-ONE to the decimal (+12.83R / 119 trades / t +1.33), so the brake is genuinely a no-op when off. But a consecutive-loss brake **shortens the losing run (5d → 4d) without reducing the drawdown (6.41R → 6.66R)**, cuts total R by 68%, collapses the survivable size to **$0**, and — the finding that matters — pushes the Best Day share from **9.6% back to 29.8%**: fewer trading days re-cluster the winners, undoing the exact property the one-entry-a-day cadence was built to achieve. **A trailing drawdown must be addressed prospectively, not reactively.** Run: `scripts/gold_daily_two.py` |
| **Is the research cost model right for THIS venue, and is the live spread as modelled?** | **`scripts/measure_live_costs.py`** — samples the live spread and compares it to the model's `1.073 bps` + `$10`/lot commission. **Refuses while the market is closed** (a weekend spread is much wider than in-session; verified exit 3), appends to `artifacts/live/cost_samples.jsonl`, and is wired into the paper supervisor to sample **once per session day** and alert if the model is optimistic by more than 25%. Commission is reported as **NOT MEASURED** — that needs a fill, and this repo sends no orders. |
| **Are the shared assets in this repo and `midastouch` still in step?** | **`scripts/cross_repo_duplication.py`** — three-way classification (IDENTICAL / LINE-ENDINGS ONLY / DIVERGED) so it cannot cry wolf: measured, the 8 gold `.set` presets are **semantically identical and CRLF-vs-LF different**, and one preset is byte-identical, so the pattern cannot be predicted from the extension. Only DIVERGED fails; an unreadable sibling repo is a **refusal (exit 3)**, not a pass. (+ `tests/test_cross_repo_duplication.py`) |
| **Does the paper trader actually run itself, and will I be told when it stops?** | **`scripts/paper_supervisor.py` + `scripts/install_paper_task.ps1`** — registered as task `MitemshubPaperSupervisor` (every 20 min, paper-only), appending a row per run to `artifacts/live/paper_daily.jsonl` and alerting to `artifacts/live/alerts.log` on a **day halt**, **stale state while open**, **terminal down**, or an **ARMED switch**. A closed market exits 0 and is explicitly *not* an alert (or a weekend would raise 72). Verified end-to-end by firing the task. (+ `tests/test_paper_supervisor.py`) |
| **Does any operator script report a verdict from data it never verified it had read?** | **`docs/VERDICT_PROVENANCE_AUDIT_20260919.md`** — audited the remaining verdict-producing tools for claims computed from unread input; each now **states the window it measured or refuses outright**. `funnel_diff` no longer reports `match (0 = 0)` from a window it never opened; `demo_watchdog`'s certificate now names its telemetry period (which immediately exposed that the window had ended 74 hours earlier). |
| **What would a trade actually size to right now?** | `scripts/verify_sizing_live.py` → `artifacts/prop_sizing_verification.json` (read-only; places no orders; exits non-zero when the trade is not placeable) |
| Rank the venue's symbols by round-trip cost per R (documented commissions only) | `scripts/upcomers_instrument_screen.py` |
| **Rank them by MEASURED cost per R (real ATR + tick-derived spread)** | **`scripts/upcomers_cost_rank.py`** (+ `tests/test_upcomers_cost_rank.py`) |
| What is the real symbol inventory / spread / session activity? | `scripts/venue_probe.py` |
| **When does the instrument actually move, when is it cheap, and how does it gap?** | `scripts/profile_instrument.py` (+ `tests/test_profile_instrument.py`) |
| Which presets belong to which venue/program? | `mql5/MITEMSHUB_AI/presets/upcomers/README.md` + `configs/upcomers/` |
| **Which repo owns what, what is live vs parked vs closed, and what may cross between them?** | **`docs/REPO_IDENTITY_AND_CROSS_REPO_STATUS_20260919.md`** — the boundary document. This repo is the **venue + methodology layer**; `MitemsHub/midastouch` owns the gold strategy. **Nothing is live and nothing is armed.** Measured duplication hazard: `MidastouchAI.mq5` is byte-identical in both repos, but the 8 gold `.set` pins are **semantically identical and CRLF-vs-LF different**, so a hash comparison across repos cries wolf on every `.set` file — compare them semantically. Folder rename staged in `scripts/rename_project.py` (dry-run by default). |

### The two EAs — do not confuse them

| EA | Source | Version | Role | Preset |
|---|---|---|---|---|
| **MitemshubAI** | `mql5/MITEMSHUB_AI/MitemshubAI.mq5` | **26.40** | multi-strategy (pullback / breakout / momentum / mean-revert + band-fade rig); the paper arms and the only certified live surface | `MitemshubAI_VOL75_*.set` |
| **V75MacroEngine** | `V75MacroEngine.mq5` | **2.24** | long-only M30 springboard, H4/H1 EMA alignment, `SL=2×ATR(H1)`/`TP=4×ATR(H1)`, 2h timeout (arm C) | `MitemshubAI_VOL75_FINAL.set` carries a **corrected note** because its old header described *this* EA |

> `mql5/MITEMSHUB_AI/PRODUCTION_CONFIGS.md` describes the **never-shipped v27.00**
> restructure and historically mis-cited `MitemshubAI.mq5` as its source. It is marked
> NON-AUTHORITATIVE in-file. `MitemshubAI_VOL75_FINAL.set`'s header made the same mistake
> and now carries a correction note.

### Frozen evidence — citable, never edited

These are the studies and audits that produced the verdicts still binding on the program.
Closing a question means adding a row, not rewriting one of these.

- **Audits / milestones:** `FULL_EA_AUDIT_v2635.md`, `MILESTONE_MEMO_v2635.md`
- **The stop:** `V75_CLOSEOUT_20260916.md` (indices stopped, this revival reverses it)
- **The gate era:** `OPERATING_SUMMARY.md` (the pre-registered decision tree — still the
  template `SYNTHETIC_GATE_V2.md` follows)
- **Negative results (all still binding):** `GENERATOR_FINGERPRINT.md` (V75 is a memoryless
  step machine), `Z_GATE_PROTOCOL.md`, `DRIFT_SIGMA_TRACKER.md`, `MOM_STANDALONE_DUEL.md`,
  `V100_NET_EDGE_STUDY.md`, `CROSS_SYMBOL_SCAN_20260915.md`, `V75_SPREAD_TIER_STUDY.md`,
  `V75_COST_DILUTION_STUDY.md`, `OOS_AUTOPSY_20260915.md`, `HOSTILE_VS_OVERFIT_20260916.md`,
  `ANCIENT_WINDOW_VALIDATION_20260916.md`, `TP_DUEL_FRESH_TEST.md`, `HYBRID_EXIT_STUDY.md`,
  `SPIKE_CONTINUATION_STUDY.md`, `VIABLE_SCALE_GEOMETRY_STUDY.md`
- **Operating playbooks:** `OPERATOR_GUIDE.md`, `GOVERNOR.md`, `GO_LIVE_CHECKLIST.md`,
  `DEPLOYMENT.md`, `DEPLOYMENT_RUNBOOK.md`, `NO_GO_BRANCH_PLAYBOOK.md`,
  `V75_RECERT_PROTOCOL.md`, `FILL_COST_STRESS_PROTOCOL.md`, `TRAINING_PROTOCOL_20260915.md`
- **Arm records:** `ARM_A2_RESTART.md`, `ARM_C_TEMPLATE.md`, `ARM_D_FORWARD_TEST.md`,
  `ARM_E_TP20_FORWARD_PROPOSAL.md`
- **Superseded framing:** `LIVE_READINESS.md` (v26.35 numbers, cost-gross superseded at the
  foot of the same file), `CRITIQUE_REPLICATION.md`, `PHASE3_SUMMARY.md` /
  `PHASE4_SUMMARY.md` / `PHASE5_SUMMARY.md`, `architecture.md` (describes the Python-lab +
  dashboard split; the dashboard is not part of the revival scope)
- **Research-only router:** `V75_ROUTER_ARCHITECTURE.md` (states its own scope: "does not
  feed the EA or submit orders")
- **Unrelated to this repo's scope:** `CLOUDFLARE_SETUP.md`, `DERIV_SUPPORT_EMAIL.md`,
  `META_LABELING_PIPELINE.md`, `SPRINT_ENTRY_REDESIGN_20260915.md`,
  `V75LOW_H1_TUNING_20260915.md`, `EA_UPGRADE_RESEARCH.md`, `CHANGELOG_v25_1.md`

## Venue / prop-firm question (opened 2026-09-19)

The operator is considering moving this program to a funded prop account. The question
"which venue, and can the EA legally run there?" has one authoritative file:
**`docs/UPCOMERS_RULES_AUDIT_20260919.md`**. It establishes (with primary sources) that
Upcomers carries **no synthetic indices**, that its EA policy is allowed but recently changed
(and is contradicted by third-party listings), and that its own rulebook disagrees with itself
on the daily-reset time and on the two rules that cause hard termination. Any future venue
audit belongs in this section rather than in a new top-level doc.

## MIDASTOUCH (gold — parked 2026-09-19)

| Question | Authoritative file |
|---|---|
| How was it parked, and what is still outstanding? | **`docs/MIDASTOUCH_CLOSEOUT_20260919.md`** |
| What is the frozen protocol and gate? | `docs/MIDASTOUCH_PROTOCOL.md`, `docs/MIDASTOUCH_V2_REGISTER.md` |
| Why gold at all, and what are its costs? | `docs/MIDASTOUCH_GOLD_PLAYBOOK.md` |
| Prior closeouts / readings | `MIDASTOUCH_CLOSEOUT_20260916.md`, `_20260917.md`, `MIDASTOUCH_FIRST_LIVE_TRADE.md`, `MIDASTOUCH_READING_20261001.md`, `MIDASTOUCH_HEALTH_GUIDE.md` |

The gold program is **preserved, not deleted**, and its own repository
(`Desktop/Projects/MIDASTOUCH`, origin `MitemsHub/midastouch`) remains the place its
history lives. Nothing in this tree's `mql5/MIDASTOUCH/` or `scripts/midas_*` was removed.

---

## Repo layout — which program lives where

Three programs share this tree. The rule is **one EA source per program, and presets
are namespaced, never forked.**

| Program | EA source | Presets | Configs | Status |
|---|---|---|---|---|
| **Deriv synthetic indices** | `mql5/MITEMSHUB_AI/MitemshubAI.mq5` | `mql5/MITEMSHUB_AI/*.set` | — | parked at $39.58 — every instrument CAP-VETOED on the lot floor |
| **Upcomers prop (`NACUSD.c`)** | **the same** `MitemshubAI.mq5` | `mql5/MITEMSHUB_AI/presets/upcomers/` | `configs/upcomers/` | active build from 2026-09-19 |
| **MIDASTOUCH (gold)** | `mql5/MIDASTOUCH/` | `mql5/MIDASTOUCH/*.set` | — | parked 2026-09-19 |

**Why Upcomers gets no EA folder of its own.** MIDASTOUCH has `mql5/MIDASTOUCH/`
because it is a genuinely different EA (`MidastouchAI`). Upcomers is **the same**
`MitemshubAI` pointed at a different instrument, and it needs **zero source
changes**: its symbol guard (`MitemshubAI.mq5:781`) refuses only names beginning
`crash `/`boom `, so `NACUSD.c` passes `OnInit()` untouched. Forking the source would
recreate the two-variants/five-current-documents problem this file exists to fix.
Upcomers therefore gets namespaced **presets and configs**, not a code fork — see
`mql5/MITEMSHUB_AI/presets/upcomers/README.md`.

**Guard note.** `tests/test_preset_live_guard.py` scanned presets **non-recursively**
until this folder was added, so a subfolder would have escaped the live-trading
guard silently. It is now recursive, pinned by
`test_preset_discovery_reaches_subfolders`.

## Repo name — decision (2026-09-19)

**Keep `MitemsHub/mitemshub-indices`.** Renaming was considered and rejected:

- The name is still true — it is the *indices* repository, holding the synthetic
  index program and, now, a real-index prop program.
- A rename costs a GitHub settings action, a remote re-point, a
  `deploy_manifest.txt` audit and an edit to every document citing the repo, for no
  engineering benefit.
- The problem a rename would appear to solve is discoverability, and **this file is
  already that fix.** A name is not a map.

If a rename is ever genuinely wanted, the defensible target is
`mitemshub-trading`, since `-indices` under-describes a tree that also contains the
parked gold program.

## Changing any of this

- A **frozen evidence** file is never edited. Its conclusions change only by adding a new
  authoritative document that cites it.
- A **deploy contract** change requires a deliberate `deploy_manifest.txt` pin edit plus a
  changelog entry naming the validation (see the procedure in that file's header).
- If a new document becomes authoritative, **update this index in the same change** —
  an unindexed authoritative document is how the five-way split happened the first time.
