# MitemshubAI V28 — Research & Tester Protocol

V28 exists to answer **one** question with evidence instead of opinion:

> Is this strategy losing because of the **directional interpretation**, the
> **trigger interpretation**, the **exit geometry**, the **holding period**, or
> the **combination**?

Everything below is arranged so that question is answered on identical data,
with identical execution rules, by deterministic hypotheses that each carry an
experiment ID. Nothing in V28 rewrites trading logic while it runs; the EA never
mutates itself, and `InpLiveExecution` stays `false` outside the tester.

---

## 1. What ships

| File | Role |
|---|---|
| `mql5/MITEMSHUB_AI/MitemshubAI.mq5` | v27, untouched, still the live EA |
| `mql5/MITEMSHUB_AI/MitemshubAI_v28.mq5` | v28 research framework (mode 0 = v27 semantics) |
| `scripts/v28_research.py` | experiment registry, scorecard, robustness, promotion gate |
| `tests/v75_tester_runner.py` | the headless launcher/parsers every tester run goes through |

### Strategy modes

| ID | Mode | Meaning |
|---|---|---|
| 0 | `V28_ORIGINAL` | the v27 strategy |
| 1 | `V28_REVERSE_DIRECTION` | bullish H4/H1 alignment → SELL, bearish → BUY; trigger unchanged |
| 2 | `V28_REVERSE_TRIGGER` | direction unchanged; BUY hypothesis uses overbought, SELL uses oversold |
| 3 | `V28_REVERSE_BOTH` | both inversions together |
| 4 | `V28_LONG_ONLY` | the normal signal family, BUY side only |
| 5 | `V28_SHORT_ONLY` | the normal signal family, SELL side only |
| 6 | `V28_MACRO_ONLY` | H4/H1 alignment is the signal; the M30 springboard gate is ignored |
| 7 | `V28_TRIGGER_ONLY` | M30 trigger decides direction; H4/H1 data is not required at all |

Modes 4/5 are applied *after* signal construction, so they measure the same
signal family filtered to one side — they never invent new signals.

### Tunable geometry (inputs)

| Input | Default | Hard limit (init rejects outside) | Recommended search range |
|---|---|---|---|
| `InpRiskFraction` | `0.01` | `(0, 0.10]` | 0.005 – 0.02 |
| `InpStopATRMultiplier` | `2.0` | `(0.25, 6.0]` | 1.0, 1.5, **2.0**, 2.5, 3.0 |
| `InpTargetATRMultiplier` | `4.0` | `(0.25, 12.0]` | 2.0, 3.0, **4.0**, 5.0, 6.0 |
| `InpMaxHoldMinutes` | `180` | `[15, 720]` | 30, 60, 90, 120, **180**, 240, 360 |

Out-of-range values make `OnInit` fail loudly rather than trade absurd geometry,
so an optimizer step outside these bounds produces an explicit refusal instead
of a garbage result. Ranges are deliberately **staged one axis at a time** — see §5.

---

## 2. Tester setup (identical for every candidate)

| Setting | Value |
|---|---|
| Expert | `MITEMSHUB_AI\MitemshubAI_v28` |
| Symbol | `Volatility 75 Index` (the EA refuses any other symbol) |
| Period | `M30` (the gate is an M30 new-bar gate; never change this) |
| Model | **Every tick based on real ticks** (history quality must read `100% real ticks`) |
| Deposit / currency | `10 000 USD` |
| Leverage | `1:100` |
| `InpLiveExecution` | **`true` in the tester only** (the EA suppresses all orders when false) |
| `InpDrawHud` | `false` in the tester |
| `InpStrategyMode` | the candidate's mode |
| `InpExperimentTag` | the candidate's hypothesis id (see §4) |
| Optimization criterion | **Custom max** — `OnTester()` returns whole-run cumulative R |

**Never send a partial `[TesterInputs]` set.** An INI without the full input list
silently merges with the agent's cached inputs from a previous run; that is how
a "0.30R" pass once ran as a different configuration. `scripts/v28_research.py`
always sends the complete surface and then verifies what ran.

### Terminal-host precondition (learned 2026-09-16, cost: one 15-minute timeout)

The tester terminal (`MitemshubMT5_B`) is **also arm D's live paper host** (arm
B lives on `MitemshubMT5_C` — an earlier draft of this section named arm B
here; corrected 2026-09-16 after the sweep's host verification). A
`/config` launch against an already-running terminal is a silent single-instance
no-op: no report, no agent journal, and `run_pass` burns its full 900 s timeout
(the 2026-09-15 `/portable` incident shares this signature). Every research
session must therefore run the stop → sweep → restart discipline — the
terminal is killed only after its paper arm's ledger is read and confirmed
flat, the sweep runs headless (the terminal self-exits after each pass, so
passes 2..n launch clean), and the terminal is **always** relaunched when the
sweep ends, whatever the exit code.

**The discipline is tooling, not procedure:** `scripts/v28_sweep_runner.py`
(graduated from the 2026-09-16 `_tmp` orchestrator after the trap recurred
that morning) enforces it end to end — exact terminal-path identity, arm
discovery from the terminal's own chart profiles, a ledger-flat gate that
mirrors the EA's restore rule (a dangling OPEN would come back as a live
virtual position; unreadable ledgers fail closed), the always-relaunch
`finally`, and an audit artifact at
`artifacts/v28_research/sweep_runner_last_run.json`. `run_pass` fast-fails
with the fix in the message when the tester terminal is already running, and
waits out per-pass self-exit teardown before condemning a live process.

```bash
python scripts/v28_sweep_runner.py status        # inventory + flatness only
python scripts/v28_sweep_runner.py exit-sweep --survivors V28_REVERSE_BOTH --window wf
python scripts/v28_sweep_runner.py matrix --windows is90
```

### Two ways to run

**Headless (preferred — it also registers the result):**

```bash
python scripts/v28_research.py matrix --windows is90     # 8 modes, one window
python scripts/v28_research.py matrix --windows is180
python scripts/v28_research.py matrix --windows wf
python scripts/v28_research.py matrix --windows oos
python scripts/v28_research.py equivalence               # v27 vs v28 mode 0
python scripts/v28_research.py exit-sweep --survivors V28_ORIGINAL --window is180
python scripts/v28_research.py score
python scripts/v28_research.py export                    # registry.csv / registry.json
python scripts/v28_research.py promote --hypothesis ORIGINAL_sl2_tp4_h180_r0.01
```

**Manual (MT5 GUI):** Strategy Tester → the settings above → set `InpStrategyMode`
and `InpExperimentTag` → Start. Read the `RESEARCH_RESULT` line in the Journal;
it carries the candidate identity, the whole-run P&L/R, the exit-reason split and
the geometry actually used:

```
RESEARCH_RESULT tag=ORIGINAL_sl2_tp4_h180_r0.01 mode=0 mode_name=V28_ORIGINAL
 trades=18 wins=7 losses=11 win_rate=38.89% test_pnl=-229.41 test_R=-2.3075
 sl_exits=1 tp_exits=0 timeout_exits=17 risk=0.0100 sl_atr=2.00 tp_atr=4.00
 hold_min=180 live=true
```

### Session vs test accounting

The HUD's session P&L/R reset at midnight **by design** and are therefore useless
as an optimization score. `OnTester()` scores only the whole-run counters
(`g_test_*`), which are reset once per pass in `OnInit` and never at midnight.
In the tester the EA also skips terminal global variables entirely, so one pass
can never inherit another pass's session state. The report's own
`OnTester result:` field must equal `test_R` from the `RESEARCH_RESULT` line —
that equality is the proof the score is the run, not the day.

---

## 3. Data windows (roles are fixed before any candidate runs)

The tester terminal holds V75 real ticks from **2024.01 to 2026.09** (33 months).
Four contiguous, non-overlapping 90/180-day blocks are used:

| Window | Range | Role | Why |
|---|---|---|---|
| `is180` | 2026.03.14 → 2026.09.10 | in-sample (discovery) | most recent, where hypotheses may be found |
| `is90` | 2026.06.12 → 2026.09.10 | in-sample (fast check) | subset of `is180` |
| `wf` | 2025.12.14 → 2026.03.13 | walk-forward | immediately prior, unseen during discovery |
| `oos` | 2025.09.15 → 2025.12.13 | **out-of-sample** | oldest block, deliberately reserved |

The OOS block is **never** used to choose a candidate. If a decision needs OOS
data, the decision is not allowed to be made.

---

## 4. Experiment matrix

**Stage 1 — the eight modes on one identical window** (what the loss is made of):

| # | Candidate | Window(s) |
|---|---|---|
| A | `V28_ORIGINAL` | `is90`, `is180`, `wf`, `oos` |
| B | `V28_REVERSE_DIRECTION` | same four |
| C | `V28_REVERSE_TRIGGER` | same four |
| D | `V28_REVERSE_BOTH` | same four |
| E | `V28_LONG_ONLY` | same four |
| F | `V28_SHORT_ONLY` | same four |
| G | `V28_MACRO_ONLY` | same four |
| H | `V28_TRIGGER_ONLY` | same four |

**Stage 2 — staged exit/holding sweep on the survivors only**, one axis at a
time (never a full combinatorial grid):

```
SL ATR   : 1.0, 1.5, 2.0, 2.5, 3.0
TP ATR   : 2.0, 3.0, 4.0, 5.0, 6.0
Hold min : 30, 60, 90, 120, 180, 240, 360
Risk     : 0.005, 0.01, 0.02      (sanity only; not a search dimension)
```

Each axis is a separate experiment id (`ORIGINAL_sl3_tp4_h180_r0.01`). If an axis
produces a non-monotonic, single-cell spike, that is noise — see §6.

---

## 5. Validation protocol (per promising candidate)

1. **In-sample discovery** — `is90` / `is180`.
2. **Walk-forward** — `wf`, same geometry, no edits in between.
3. **Untouched out-of-sample** — `oos`, run once, never re-tuned afterwards.
4. **Robustness** — automatically computed by the scorecard:
   * trade **bootstrap** (2 000 resamples with replacement, fixed seed `20260913`);
   * **drop-best-1 / drop-best-3** ("is the edge three lucky trades?");
   * **trade-order shuffle** (final P&L is order-invariant; drawdown is not);
   * parameter perturbations via Stage 2 (one axis at a time);
   * different contiguous windows (§3) rather than one long sample.
5. **Paper-forward testing** — only after 1–4.
6. **Live trading** — a separate, manual decision. `InpLiveExecution` stays
   `false` by default and nothing in the research layer can flip it.

### Promotion gate

`promote` refuses unless **all** of these hold for the same hypothesis:

* `is`, `wf` **and** `oos` evidence exists — a single backtest can never promote;
* every role has **≥ 30 trades** (house sample gate) — large profit on a thin
  sample is not evidence;
* OOS net P&L **> 0** and OOS cumulative R **> 0**;
* the WF P&L sign does not flip versus in-sample;
* bootstrap `p05 > 0` and profitable-share **≥ 0.80**, and drop-best-3 still > 0.

The gate is blunt on purpose. It is cheaper to reject a good candidate than to
promote a lucky one.

---

## 6. Interpretation rules

* ORIGINAL negative but REVERSE_DIRECTION strongly positive → **do not** conclude
  "reverse is the strategy". Check OOS and parameter perturbation first; a sign
  flip is usually a regime property, not a structural edge.
* ORIGINAL and REVERSE_DIRECTION both negative → suspect the **directional
  filter itself** has no predictive value.
* REVERSE_TRIGGER better than ORIGINAL → the M30 trigger may be acting as
  continuation/momentum rather than mean reversion.
* LONG_ONLY vs SHORT_ONLY differ substantially → **direction asymmetry** is the
  finding; report it as such rather than averaging it away.
* MACRO_ONLY beats the combined model → the M30 trigger may be damaging a usable
  macro signal.
* TRIGGER_ONLY beats the combined model → H4/H1 alignment is likely too
  restrictive or mistimed.
* A cell that wins on one window and loses on the next is **noise**, not a
  candidate. Non-monotonic spikes along a single axis are the same signal.

---

## 7. Anti-overfitting rules encoded in the tooling

* One hypothesis = one experiment id in `artifacts/v28_research/registry.jsonl`;
  a change after a losing run is a **new** experiment, never an edit.
* Complete explicit `[TesterInputs]` on every pass; the report's own input dump is
  the authority on what ran.
* Selection is always on one sample role and judged on another.
* Fixed bootstrap seed ⇒ the same candidate always gets the same verdict.
* Bounded optimization ranges (§1) so the optimizer cannot explore absurd geometry.
* `OnTester()` scores the whole run (cumulative R), never the midnight-reset
  session value.
* The event model stays clean: all structural signal work remains behind the M30
  new-bar gate; every-tick work is lifecycle, guardian and HUD only. Do not turn
  this into a tick-chasing strategy while optimizing, and do not change the
  signal evaluation frequency.

---

## 8. Known limitation to respect when reading results

V75 real ticks only exist from **2024.01** on this account, and the tester's own
real-tick model fills at the prevailing tick. Forward-looking claims therefore
rest on 33 months of one instrument's synthetic history, and every sample above
90 days is a single regime by construction. Treat `oos` as the only honest test
and keep it untouched.

---

## 9. Stage-2 exit-sweep adjudication — REVERSE_BOTH on is180 (2026-09-16)

Executed under this protocol, frozen before any run (orchestrator:
`scripts/_tmp_v28_sweep_orchestrator.py`; log:
`artifacts/v28_research/sweep_RB_is180_20260916.log`). 14 new registry rows
V28-0033 → V28-0046 on the stage-1 survivor `V28_REVERSE_BOTH`, one axis at a
time from the registered baseline (`sl2_tp4_h180`, is +679.49 / +6.60R, n=29,
WR 65.5%):

* **SL axis (tp4, h180): strictly monotonic, tighter is better.** sl1.0
  +11.12R → sl1.5 +8.29 → sl2.0 +6.60 → sl2.5 +5.29 → sl3.0 +4.40 (all n=29,
  identical trade sets — TP/hold dominate the exits). Tighter stops on this
  entry realize more of the same signal; no spike, no noise signature.
* **TP axis (sl2, h180): inert above 3 ATR.** tp3/tp4/tp5/tp6 rows are
  byte-identical (+679.49 / +6.604 / PF 4.33): no exit ever lands beyond 3 ATR,
  so the TP surface is flat there. tp2.0 is the only live cell (+7.12R, PF
  4.58) — a mild improvement inside the axis, not a spike.
* **Hold axis (sl2, tp4): non-monotonic.** h30 +0.48 → h60 +2.71 → h90 +3.31
  → h120 +2.56 → h180 +6.60 → h240 +6.16 → h360 +8.52. The h120 dip below h90
  is the §6 noise signature: NOT a candidate.
* **Adjudication (mechanical, per §5): every sweep cell REFUSED.** The 14 new
  cells are is-only by design (no wf/oos evidence exists), and the baseline —
  the only candidate with all three roles — fails the gate on OOS: net P&L
  −20.17, money-implied R −0.2021, ratio-sum R −0.1854, and thin samples
  (29/27/12) below the 30-trade house gate. `promote` refuses exactly on those
  grounds. Robustness on the is-only cells fails the usual ways (drop-best-3
  ≤ 0 on h30/h90/h120; sl1.0's +11.12R headline rests on 0.99 profitable
  share with the same 29 trades as the baseline — tighter SL, not new signal).
* **Standing verdict unchanged:** REVERSE_BOTH is the direction-level finding
  (the only mode positive on is90/is180/wf; ORIGINAL −8.13R on the same
  is180 window), not a promotable config. OOS remains negative/thin, the
  gate clock on the arm paper books is untouched by research, and the OOS
  block stays reserved — no OOS run was consumed by this sweep.

### §9 amendment — walk-forward completion for the SL axis (same day, frozen extension)

Per §5 step 2 (walk-forward, same geometry, no edits), the four unregistered
SL cells ran on `wf` (2025.12.14 → 2026.03.13; sl2.0 IS the baseline and
already held its wf row). Registry V28-0047 → V28-0050; runner:
`scripts/_tmp_v28_wf_sl_cells.py`, log `artifacts/v28_research/wf_SL_cells_20260916.log`;
arm D verified flat (16 ledger rows, all ERA stamps, zero OPEN/CLOSE) before
the terminal stop, banner + $50.00 veq verified after relaunch. OOS untouched.

| cell | is | wf | wf verdict |
|---|---|---|---|
| sl1.0 | +11.12R (n=29) | **−0.52R (n=29)** | **P&L sign flips vs IS** |
| sl1.5 | +8.29R (n=29) | +2.84R (n=27) | holds, degrade 0.34 |
| sl2.0 (baseline) | +6.60R (n=29) | +2.52R (n=27) | holds, degrade 0.38 |
| sl2.5 | +5.29R (n=29) | +2.01R (n=27) | holds, degrade 0.38 |
| sl3.0 | +4.40R (n=29) | +1.69R (n=27) | holds, degrade 0.38 |

* **The IS gradient does not survive its own extreme:** sl1.0 — the sweep's
  +11.12R headline — is negative on wf, the §6 "wins one window, loses on the
  next" noise signature. The tighter-is-better pattern was partly
  IS-regime-specific; only the 1.5–3.0 interior holds its sign on wf.
* **The interior is flat, not peaked:** wf R spans 1.69–2.84R across
  sl1.5→sl3.0 with no monotone structure (the IS ordering nearly inverts).
  No geometry re-selection is authorized; the robust fact is at the mode
  level — the REVERSE_BOTH signal family carries a positive wf edge across
  the whole SL interior while ORIGINAL loses on the same window.
* **Gate status unchanged:** every SL cell remains REFUSED (missing oos
  evidence, samples below 30). The promotion gate has not been re-litigated;
  the wf rows exist so the evidence base matches §5, not to argue a ship.

### §9 amendment 2 — walk-forward completion for the TP and hold axes (same day)

Per §5 step 2, the ten remaining sweep cells ran on `wf` through the permanent
runner (`scripts/v28_sweep_runner.py exit-sweep --survivors V28_REVERSE_BOTH
--window wf`; arm D verified flat pre-stop, banner + $50.00 veq verified after
relaunch; registry V28-0051 → V28-0060; OOS untouched). Every sweep cell now
holds is + wf evidence (60 registry rows).

* **TP axis wf: the inertness above 3 ATR transfers exactly.** tp3/tp4/tp5/tp6
  are identical on wf too (+250.40 / +2.516R, n=27) — no exit lands beyond 3
  ATR on either window; a structural property of the exits, not noise. tp2.0
  is the only live cell and the **best wf cell of the entire sweep** (+3.03R).
* **Hold axis wf: the IS dip was noise, and the IS optimum does not transfer.**
  h30 **−0.57R (sign flip vs IS +0.48R)**; h60 +0.35R; h90 +0.91R; h120 +1.86R
  — the §6 dip at h120 is absent on wf, confirming it as noise. The wf surface
  rises monotonically to the baseline: h180 +2.52R ≈ h240 +2.48R is the
  plateau, then h360 collapses to +0.57R (IS +8.52R → 0.067 degradation — the
  IS axis headline dies out-of-regime, same lesson as sl1.0).
* **The frozen default geometry is the wf optimum on every axis.** sl2/tp4/h180
  sits at or beside the wf peak of all three axes (SL interior flat, TP plateau
  from 3 ATR, hold plateau at 180–240). No re-selection is authorized and none
  is suggested by the data; the stage-2 conclusion is that the mode carries
  the edge and the baseline geometry is already inside the flat region.
* **Gate status unchanged:** all 15 cells REFUSED (missing oos evidence,
  samples below 30). The evidence base now matches §5 completely; the OOS
  block remains reserved and unconsumed.

### §9 amendment 3 — the OOS one-shot rule (FROZEN 2026-09-16, before any interior OOS run exists)

The stage-2 sweep produced 15 cells with is + wf evidence, but the §3 OOS
block stays reserved. Honest scoping first: 90 days of one regime yields only
~12 family trades, so an OOS run can **never** satisfy the 30-trade promotion
sample gate, and the baseline's own stage-1 OOS row (−0.185R, n=12) already
exists. The interior's single OOS run is therefore **not a promotion input**.
It is a **final historical verdict** with exactly one purpose: deciding
whether the family has earned a pre-registered FORWARD-TEST PROPOSAL (an
arm-D-style fresh-window test with its own frozen adjudication) — never a
direct ship, never re-tuning against the OOS result.

**The rule (mechanical; encoded in `scripts/v28_research.py oos-oneshot` so
it is code-checked, not prose-checked):**

1. **Eligibility, computed from the registry only.** A cell qualifies iff it
   holds both an is180 and a wf row, and: is180 cumulative R ≥ **+2.0**, wf
   cumulative R ≥ **+1.5**, the wf P&L **sign matches** is180, and wf
   drawdown ≤ **20%** of the frozen $10 000 deposit. Two exclusions are part
   of the rule: the baseline `sl2_tp4_h180` (its OOS row already exists —
   stage 1, not the interior's shot), and any cell whose is180 trade set is
   IDENTICAL to the baseline's (same n and pnl — the tp3/5/6 duplicate-exit
   rows: one strategy under three labels must not multiply the shot's
   apparent choices). Eligible today: sl1.5, sl2.5, tp2.0, h120, h240, sl3.0.
2. **The shot is single-use for the WHOLE interior.** Spending it requires an
   explicit `--cell` from the eligible list **plus a recorded `--reason`**
   (the choice is auditable against the frozen bar). One run spends it
   whatever the outcome; the spend token
   (`artifacts/v28_research/OOS_ONESHOT_TOKEN.json`) AND any interior OOS row
   in the registry both block a second run — deleting the token cannot re-arm
   it, because the registry row survives.
3. **The decision mapping is frozen.**
   - OOS drawdown > **$3 000 (30%)** → **FAMILY_RETIRED**: the family's edge
     is is/wf-local; the OOS block closes for the interior forever.
   - OOS pnl > 0 and R > 0 and n ≥ 30 → **EARNED_FORWARD_TEST_PROPOSAL**:
     the only positive outcome. It authorizes *drafting* a forward-test
     proposal for adjudication — the same bar arm D met (frozen verdict
     gates, fresh window, no fitting use of the proposal text). It does NOT
     authorize live orders, preset changes, or any OOS reuse.
   - OOS pnl > 0 but n < 30 → **CONTINUE_THIN**: no proposal on this window;
     the sign survives but the sample cannot support one. Recorded, not
     acted on.
   - OOS pnl ≤ 0 or R ≤ 0 → **FAMILY_RETIRED** (same as the DD breach: the
     one historical shot came back negative).
4. **What spending the shot changes:** nothing else. Arms, gate clocks, the
   arm-D forward test, and the §3 window roles are untouched. A
   FAMILY_RETIRED verdict retires the REVERSE_BOTH **interior from OOS
   consideration** — the mode-level wf evidence and the stage-1 registry
   remain what they are; no row is deleted, no history rewritten.
5. **Amendment bar:** changing these thresholds after any interior OOS row
   exists is an amendment-grade violation of this protocol and must be
   recorded as such in the changelog with the reason it was forced.


### §9 amendment 4 — family-level walk-forward significance (2026-09-16)

The per-cell verdicts above answer "is this geometry good". The question the
sweep actually poses is whether the MODE carries a wf edge at all. This
amendment freezes one mechanical family test (`v28_research.py wf-family`,
bar written and test-pinned before the first run against the live registry):

1. **Dedupe wf rows to distinct trade sets** — identical (n, pnl) signatures
   are verified trade-by-trade and collapsed to their baseline-geometry
   representative; a signature collision fails closed. On today's registry the
   tp3/tp5/tp6 labels collapse (three labels, one strategy — amendment 2's
   inertness finding is a property of the family, not three hypotheses).
2. **Pool the distinct trade sets** into one per-trade family sample;
   bootstrap the family against zero and against the ORIGINAL wf pool.
3. **Test**: one-sided permutation of the mean-per-trade difference, family
   vs ORIGINAL, unpaired. Unpaired is a choice, not an oversight — but the
   trades WITHIN the family pool are themselves dependent (cells share one
   window and much of one signal stream), so the p-value is approximate in
   both directions and the verdict bar below is deliberately multi-part
   rather than resting on one p-value.
4. **Verdict bar (all required)**: pooled distinct trades >= 100; family
   bootstrap p05 > 0; profitable share >= 0.80; family mean per trade >
   ORIGINAL's; permutation p <= 0.05.
5. **Scope**: descriptive, not a gate. It consumes no OOS resource, touches
   no one-shot token, and can never promote a candidate — promotion stays
   §5's per-hypothesis chain. The artifact
   (`artifacts/v28_research/wf_family_significance.json`) is timestamp-free
   and byte-deterministic for the same registry.

**Result (15 wf rows -> 12 distinct trade sets, 335 pooled distinct trades):**

- family mean per trade **+$5.02** (bootstrap p05 **-$17.04**, profitable
  share **0.948**)
- ORIGINAL wf mean per trade **-$13.08** (p05 **-$808.47**, profitable share
  **0.106**)
- mean difference **+$18.10 per trade**; permutation p(1-sided) = **0.066**
- **FAMILY_EDGE_NOT_SUPPORTED** — reasons: family bootstrap p05 <= 0;
  permutation p > 0.05.

**Reading (recorded with the result, not after it):** the mode-vs-ORIGINAL
separation in level is large and one-sided (+$18.1 per trade, 0.948 vs 0.106
profitable share), consistent with the mode-level finding in amendments 1-2.
The refusal is driven by pooled dispersion, and rightly so: the interior
deliberately contains cells that lose on wf (sl1.0 and h30 sign-flip; h60,
h90 and h360 bootstrap unprofitable in 3-5 resamples out of 10), and the exit
inertness means the family's distinct information is thinner than its 335
trades suggest. A tight interior would pass this bar; this one carries its
dead cells honestly. The verdict retires nothing: amendment 3's one-shot OOS
rule remains the family's only OOS path, unchanged and unspent.


### §9 amendment 4a — held-window extension and leave-one-cell-out sensitivity (2026-09-16)

An extension of amendment 4, recorded before its live results were read into
any decision:

1. **The aggregation now accepts any held window** (`--window wf|is90|is180`)
   and **refuses OOS in code, unconditionally** — the one-shot rule
   (amendment 3) owns that window, and a family read there would spend it.
   Other held windows write `family_significance_<window>.json`; wf keeps the
   original artifact name.
2. **`--leave-one-out` is a diagnostic, not a gate**: it drops each distinct
   cell in turn and then runs it alone, to show which cells carry the family
   verdict. It names no promotable configuration, consumes no OOS resource,
   and is pinned by offline tests.

**Results (same-day, same registry):**

- **is180 family: FAMILY_EDGE_SUPPORTED** — 10 distinct trade sets, 306 pooled
  trades, family +$18.51/trade (bootstrap p05 +$5242, profitable share 1.000)
  vs ORIGINAL -$27.03/trade (profitable share 0.000); mean difference
  +$45.55/trade, permutation p = 0.0000.
- **wf sensitivity: the whole negative verdict hangs on sl1.0.** Dropping it
  moves permutation p from 0.066 to **0.029** (verdict flips to SUPPORTED);
  every other drop stays 0.051-0.065. sl1.0 alone is a wf loser (-$2.37/trade,
  p = 0.32) — the same cell the is-adjudication flagged as the §6
  one-window-wins signature. No distinct cell passes alone (best: tp2.0,
  p = 0.051).

**Standing reading:** the mode-level separation is real in-regime (is180,
p ≈ 0) and just outside the pre-frozen bar out-of-regime (wf, p = 0.066) with
the sole drag being a cell already independently identified as noise. The bar
is NOT re-tuned: this is recorded as an honest borderline, an input to the
amendment 3 spend decision — not a reason to re-select geometry or to treat
wf as passed.


### §9 amendment 3 — executed (2026-09-16, user-authorized)

The interior's single OOS run was spent on **REVERSE_BOTH_sl2_tp2_h180_r0.01**
(reason recorded in the spend token: best wf cell, solo permutation p = 0.051,
survives every leave-one-out drop). Run through the sweep runner with arm D
verified flat pre-stop and banner-verified post-relaunch.

- Registry row **V28-0061**: n = 12, pnl **+20.55**, R **+0.225**, PF 1.07.
- Frozen decision: **CONTINUE_THIN** — positive OOS sign, but n = 12 < 30, so
  the sample cannot carry a forward-test proposal (as pre-scoped when the rule
  was frozen). Any future proposal must carry the thin-sample disclosure.
- The interior is **NOT retired** (the verdict is not FAMILY_RETIRED). What
  closes forever: re-running OOS for this interior, and tuning anything
  against this window. The one-shot token is spent; the registry row and the
  token record are the permanent receipts.

Post-spend standing (all held-window evidence, none of it OOS): mode-level
family edge confirmed in-regime (is180, p = 0.0000), borderline out-of-regime
(wf, p = 0.066, hanging on the sl1.0 cell), and the single OOS sample is
directionally positive. The path to live trading remains exactly what the
protocol always said: arm D's frozen forward window (n >= 60, positive R,
DD <= 25%) — now with the interior's historical OOS question answered.

## 10. ML signal-filter track — pre-registered BEFORE any training run (2026-09-16)

Authorized by the user (2026-09-16 program review). Scope: a decision-time
entry filter for REVERSE_BOTH — given a fired signal, take / skip. It rides
the v28 signal stream; it never creates trades, only removes or sizes down.
Deployment order is **shadow-first**: it logs counterfactual vetoes on arm
A2's live stream long before it gates anything.

### 10.1 Data — what the model may and may not eat

- Trades: the v28 tester registry (61 rows, 8,426 trades) joined to per-trade
  journal telemetry (OPEN/CLOSE lines) where the agent journals survive.
  Today that is 937 trades; the remainder is recoverable ONLY by deterministic
  re-runs under §2's pins. A trade without decision-time journal evidence is
  OUT of the feature dataset — money-only arrays support aggregate checks,
  never features. Every run prints its coverage against the 8,426.
- Bars: `artifacts/data/volatility_75_index_m15_40000bars.csv`. Features join
  at the last CLOSED bar before the entry bar-open. A trade outside bar
  coverage is excluded and counted in the report.

### 10.2 Feature freeze (v1)

- Signal identity: mode_id, trigger (one-hot), side.
- Geometry context (reported per fold — the filter must not become a silent
  geometry selector): sl_atr, tp_atr, hold_min.
- Market structure at decision time (M15, last closed bar): returns over 1/4/
  12/48 bars; ATR(14)/ATR(50) ratio; RSI(14); position in the 96-bar range;
  realized-vol regime (std of last 32 returns / prior 96); last bar spread;
  hour-of-day (sin/cos); day-of-week.
- **Leakage rule**: peak_r, hold, exit reason, and anything post-entry are
  outcome variables — forbidden as features. Only what the EA knows at the
  entry bar-open may enter.

### 10.3 Splits — walk-forward, purged, group-capped

- Folds on calendar months, expanding window, 6 folds; **embargo of one
  full calendar month** between train and validation sides (max hold is 6 h;
  the month-scale embargo covers the re-run cell adjacency).
- Group cap: each (calendar month × geometry cell) contributes at most 30
  seeded-random trades to a training fold — the sweep re-ran the same months
  across 14+ cells, and without the cap those months dominate training.
- Metrics per fold on the held-out months; aggregate = trade-weighted mean.

### 10.4 Model and the gate it must pass (frozen)

- sklearn GradientBoostingClassifier, fixed config, class_weight="balanced",
  seed 20260916. Baseline: the unfiltered book ("take everything").
- Label: R > 0. Reported per fold: filtered expR, keep-rate, win rate,
  P(win) calibration by decile.
- **Walk-forward ship gate**: per-fold expR improvement over baseline in ≥ 5
  of 6 folds AND aggregate expR uplift ≥ +0.10R/trade AND keep-rate ≥ 0.35.
  Miss any leg → the filter does not ship; no re-tuning against the folds.

### 10.5 Deployment gates (all required, in order)

1. Walk-forward pass per 10.4 with the coverage disclosure (n / 8,426).
2. Re-run check: re-evaluate unchanged on ≥ 500 freshly re-run trades from
   months NOT trained on — deterministic §2 re-runs, no feature refits.
3. Shadow on arm A2: ≥ 60 live counterfactual decisions logged (would-take /
   would-skip), veto agreement and forward expR delta reported in the weekly
   pipeline before any preset change.
4. Only then: preset/verifier amendment shipping the frozen P(win)-bucket
   table to the EA (meta-label house pattern — no runtime inference in MQL5),
   with model version + feature version stamped in the banner.

### 10.6 Honesty register

- The featurized dataset starts at 937/8,426; coverage grows only by
  re-runs, and the report must always print the ratio.
- Training data is REVERSE_BOTH-dominant by construction of the sweep; the
  filter is candidate-specific, not fleet-wide, until its own evidence says
  otherwise.
- The filter can only remove trades. It inherits the candidate's evidence
  status (§9: positive OOS sign, thin sample); it does not add significance.

### 10.7 Bucket-table consult filter for floor mode — design frozen on the §10 recon (2026-09-16)

The §10.4 walk-forward FAIL stands for the 15-feature GBC: its P(win) does
not rank out-of-window (calibration flips between folds; mean wf AUC 0.476
in the feasibility recon). The recon also found a LARGE simple structure —
(side x six-hour block) buckets span P(win) 0.32-0.90 vs a 0.56 baseline on
the 799-trade snapshot — and that the sweep contains ONLY
M30_REVERSED_EXTREME signals, so conviction class is not learnable from this
data and stays rule-based.

Therefore the floor-mode raised entry bar becomes a two-layer contract:

- **Layer 1 (authority)**: the rule-based strong-trigger bar
  (InpFloorModeConviction) remains the only veto. Unchanged.
- **Layer 2 (consult)**: the EA loads a frozen P(win) bucket table
  (scripts/signal_filter_table.py, bucket-side-tod-v0, shipped as
  MitemshubAI_filter_table_A2.csv, ACTIVATION=PASSIVE). Every floor-mode
  evaluation prints FILTER CONSULT (side, tod, p, source, decision) and
  writes an FCONSULT ledger row — the forward evidence base accrues from
  day one. A PASSIVE table NEVER vetoes; p = 0.50 means "no opinion";
  muted buckets ship as exactly 0.50.

**Activation gate (frozen; all legs, evaluated only by --certify on fresh
re-run data)**: n >= 500 featurized trades; coverage >= 50% of 8,426;
walk-forward bucket-table AUC > 0.55 in >= 5 of 6 folds with mean > 0.55;
worst single fold kept-expR delta >= -0.05R. Current state fails 4 of 5
legs (coverage 9.5%, AUC-count 3/6, mean 0.502, worst fold -0.49R). Until
every leg passes, veto authority is never granted; a certified ACTIVE
table is a new registry-of-record artifact with its own receipt.

## 11. Regime-conditional hypothesis — PRE-REGISTERED 2026-09-16 21:4x, BEFORE any conditional data was gathered

**Discovery being tested** (from the existing registry, admitted openly):
V28_REVERSE_TRIGGER is the only mass-carrying positive configuration in the
held-out windows — wf +8.88R (n=267, t=+0.94) and OOS +3.32R (n=232) — while
losing in both in-sample windows (is90 −6.75R, is180 −17.21R). Sign flip
across eras = regime hypothesis, not stationary edge.

**Frozen hypothesis**: REVERSE_TRIGGER's expectancy is positive conditional
on a decision-time regime state R, and non-positive otherwise, where R is
one of exactly two candidates frozen NOW:

  R1 = H4+H1 EMA20 macro state of the trade's entry moment
       (the EA's own macro-classification, printed in the identity banner)
  R2 = volatility regime at entry: ATR(14, H1) percentile within the
       trailing 200 bars, split at the 50th percentile (LOW vs HIGH)

**Data source**: deterministic §2 re-runs of the REVERSE_TRIGGER cells
(wf + oos windows) on the sweep runner, harvesting per-trade OPEN/CLOSE
journal lines with sim timestamps. The surviving journals hold zero
REVERSE_TRIGGER lines (checked 2026-09-16), so the re-runs ARE the data;
the registry's existing aggregates stay the historical record.

**Test design (frozen)**: condition every re-run trade on R1 and R2;
report expectancy(R=on) − expectancy(R=off) per candidate with bootstrap
95% CIs (10k resamples, seeded). Split-half stability: the conditional
edge must hold in BOTH halves of each window (chronological halves).

**Pass gate (frozen)**: at least one of R1/R2 shows conditional uplift
>= +0.10R/trade with a 95% CI excluding zero, AND the same sign in both
split halves, AND n(R=on) >= 40. Anything else = REFUSED, no re-tuning,
the verdict is recorded whatever it is.

**Honesty register**: (1) the hypothesis was generated by looking at the
wf/oos data being tested — the split-half requirement and the OOS window's
independence from the is windows are the only guards against this selection
bias, and they may fail; (2) the is-window NEGATIVITY is part of the
hypothesis — the regime split must explain it, not hide it (R must classify
the is-window losses into R=off); (3) no cell, window, or threshold may be
amended after the first conditional number exists; an amendment restarts
the whole cell with a new experiment tag.

### 11.1 VERDICT (recorded 2026-09-16 ~21:45, mechanical per the frozen gate)

REFUSED — no regime candidate meets the frozen pass gate. Deterministic
re-runs reproduced the registry exactly (wf 267 fills, oos 232, is180 521);
coverage 100%/100%/99% (5 is180 trades past the bars file's Sep-2 end,
disclosed, excluded).

- R1 (macro direction): uplift NEGATIVE in every held-out window
  (wf −0.064, oos −0.113, is180 −0.062). REVERSE_TRIGGER's 2025–26 gains
  concentrated in the ALIGNED_DOWN state; no positive leg anywhere.
- R2 (ATR percentile): the only sign-stable split — positive in wf
  (+0.093, both halves +) — FAILS the gate: CI includes zero and uplift
  < +0.10. In is180 it is significantly NEGATIVE (−0.116, CI excludes
  zero): the is-window losses concentrate in the HIGH-vol regime.

The honesty check's answer: the is-window losses DO classify (R2=HIGH),
but that same regime carried the wf gains — the conditional edge itself
flipped sign across eras. There is no stable conditional edge to ship.
Per the amendment rule: no threshold-shopping, no contrast-switching
(e.g. to ALIGNED_DOWN) inside this registration. The R1 directional
observation is recorded as the seed of a NEW pre-registration, which must
be written and frozen before any of its numbers are computed.

Artifact of record: artifacts/v28_research/regime_test_verdict.json
