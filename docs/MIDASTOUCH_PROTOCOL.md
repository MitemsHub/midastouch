# MIDASTOUCH PROTOCOL — frozen 2026-09-16, BEFORE any strategy run on gold

This document freezes the rules. Nothing below may be edited after the first
sweep run; amendments append-only, dated, and motivated in their own section.
This is the same discipline that kept the V75 program honest (V28 protocol);
it transfers to gold unchanged in philosophy.

## 1. Data of record

- `data/forex/xauusd/XAUUSD_H1.csv` and `XAUUSD_M15.csv` (broker feed,
  validated 2026-09-16, research span H1 2024-04-10 → 2026-09-16 after the
  disclosed 112-day backfill hole was excluded; M15 capped at 50,000 bars
  by the terminal).
- Specs of record: `artifacts/deriv_symbols_20260916.json`
  (tick value, min lot, contract — the floor table).
- D1 is reference-only. D1 never gates a verdict.

## 2. Strategy family under test (the program's own DNA, ported)

- **Macro filter:** H4 and H1 close[1] vs EMA20[1] on each timeframe;
  ALIGNED_UP / ALIGNED_DOWN / DIVERGENT exactly as the V75 family defined it.
- **Trigger (M15):** BB(20, 2σ) band-touch with close back inside, or
  RSI(14) ≥ 70 / ≤ 30 — the reversal family. Signal fires at bar close;
  fill at next M15 open.
- **Modes (8, same vocabulary as the V28 registry):**
  ORIGINAL, REVERSE_DIRECTION, REVERSE_TRIGGER, REVERSE_BOTH,
  LONG_ONLY, SHORT_ONLY, MACRO_ONLY, TRIGGER_ONLY.
- **Exits (frozen for all modes):** SL = 2.0 × ATR(14, H1) at signal time;
  TP = 2.0 × SL distance; timeout = 48 M15 bars (12h); one position at a
  time; no re-entry while a position is open.

## 3. Cost model (frozen)

- Round-trip spread charged per trade from the **recorded per-bar spread
  column** at entry, half on each side, converted with the symbol's tick
  value; minimum spread $0.10 when the bar records 0.
- Slippage 0 (paper reality; the forward arm measures the real slip).
- Sizing: 1% of equity per trade, min-lot floor enforced and disclosed;
  R = pnl / risk_dollars; equity compounds across trades within a run.

## 4. Windows (frozen)

H1 span 2024-04-10 → 2026-09-16, contiguous, chronological:

| window | span | role |
|---|---|---|
| IS1 | 2024-04-10 → 2025-03-31 | in-sample 1 |
| IS2 | 2025-04-01 → 2026-03-31 | in-sample 2 |
| WF  | 2025-09-15 → 2026-03-31 | walk-forward (subset of IS2, mirrors V28 wf usage) |
| OOS | 2026-04-01 → 2026-09-16 | out-of-sample, touched exactly once |

M15 trigger data and H1 macro data both restricted to the window at signal
time (no look-ahead: every indicator uses closed bars only).

## 5. Gates (frozen — identical philosophy to the V75 program)

A mode is promoted to EA-build only if ALL of:
- **G1 sample:** OOS trades ≥ 30
- **G2 profitability:** OOS net R > 0 in BOTH R measures (ratio-sum and
  money-implied)
- **G3 quality:** OOS profit factor ≥ 1.30
- **G4 expectancy:** OOS expectancy ≥ +0.15R
- **G5 drawdown:** OOS max drawdown ≤ 12R
- **G6 robustness:** mode positive (net R > 0) in at least 3 of 4 windows
- **G7 toll sanity:** mean spread cost per trade ≤ 0.10R

NO-SHIP is the default verdict for every mode. A mode that fails is recorded
failing with its numbers — negative results are published, not buried.

## 6. Pre-registered hypotheses (frozen before the sweep)

- **H1 (session):** trades entered 12:00–16:00 UTC outperform the rest.
  Test: per-mode OOS split by session; frozen uplift gate +0.10R with
  n_session ≥ 20. Exploratory otherwise — never a promotion path.
- **H2 (macro-regime):** ALIGNED_UP and ALIGNED_DOWN behave differently
  (gold's trend bias). Test: per-direction OOS split; gate: same as H1.

Neither hypothesis may be used to re-select parameters after seeing OOS —
they can only qualify an already-passing mode.

## 7. Artifacts of record

`artifacts/midas_sweep_<date>.json` (all runs, all trades, all windows),
`artifacts/midas_sweep_verdict_<date>.json` (gate matrix per mode),
this protocol, and the playbook. All checksummed in the closeout manifest
of the run. Every number printed to stdout is derived from the artifact,
never from memory.

## 8. What happens after a pass

A passing mode → Step 5 EA build (`mql5/MIDASTOUCH/MidastouchAI.mq5`), with
**build parity** proven before anything else: the EA, run in the tester on
the same window, must reproduce the research engine's trades to within the
parity tolerance the V75 program used (max |dR| per trade ≤ 0.01R).
A total refusal → the verdict is published and the program stands down
honestly; no gate gets moved to manufacture a pass.

## 9. Amendment 1 — first sweep verdict (2026-09-16, appended after the run)

The sweep ran the same day as freezing; result: **ALL 8 MODES NO-SHIP**
(`artifacts/midas_sweep_verdict_20260916.json`). Closest: SHORT_ONLY
(OOS PF 1.289 vs G3's 1.30, expectancy +0.136R vs +0.15R, 2/4 windows) —
refused. REVERSE_DIRECTION PF 1.222 also refused. Gates unchanged; no
parameter was touched after OOS was seen. One implementation-fidelity fix
was applied between the two same-day passes (ORIGINAL's macro-agreement
gate per §2 was missing in the mode table; identical parameter set) —
recorded here because anything that changes results must be written down.

Standing interpretation: gold's cost geometry is excellent (G7 passed
everywhere: ~0.002–0.003R spread cost) — the family's entry edge is what
is missing on this feed, echoing the V75 registry's structure. Per §8,
no EA promotion happened on this verdict. Next steps remain within the
protocol: either a NEW pre-registered family (appended below before any
run) or forward paper collection on the plainest variant to mint real
evidence. No gate shopping.

## 10. Amendment 2 — bounded ATR + full re-sweep (2026-09-17, parity-driven)

The first build-parity attempt (WF window, REVERSE_DIRECTION) failed with
entries aligned but per-trade stop distances diverging (median ratio 0.95,
range 0.76–1.29). Instrumented proof (EA v1.02 debug dump vs the validated
CSV series, identical bars): **unbounded Wilder ATR is seed-dominated in
the tester's short preloaded bar window**, diverging up to 11% from a
deep-history-converged Wilder value on the same bars, with the gap growing
backward in time. Two engines with different history depths can never
agree on unbounded Wilder ATR; the live arm adds a third depth. Therefore:

- **ATR of record is now bounded:** SMA of True Range over the last 14
  closed H1 bars (`sma_atr` in the sweep engine, `AtrNow()` in the EA —
  pure bar computation, identical everywhere). This is an indicator
  *definition* fix, not a parameter search: every mode re-ran symmetrically.
- **Re-sweep verdict (all 8 modes, bounded ATR,
  `artifacts/midas_sweep_20260917.json`): ALL MODES NO-SHIP again.**
  Closest: SHORT_ONLY — OOS n=53, net +8.51R, PF 1.343 (G3 pass),
  expectancy +0.1605R (G4 pass), DD 7.21R (G5 pass) — but **G6 fails
  (2/4 positive windows)**: is1 +8.26R / is2 −12.11R / wf −7.25R /
  oos +8.51R. The same era-alternation signature the V75 registry
  documented for REVERSE_TRIGGER: sign belongs to the time segment, not
  the strategy. Refused; no promotion.
- Parity of the EA itself is now a *solved mechanism* (v1.03 computes the
  identical bounded ATR; entries matched to the minute in the v1.01 run),
  but per §8 parity only gates an EA build for a **passing** mode — none
  exists, so no promotion parity certificate is issued.
- **Forward paper collection starts anyway** on the plainest variant
  (ORIGINAL, tag M1): the family's real-time behavior with zero selection
  bias. The forward ledger is evidence-collection, not a profitability
  claim; it is adjudicated only under this protocol's gates, on data that
  did not exist when this amendment was frozen.

## 11. Amendment 3 — build parity certified, 150-vs-147 root-caused
        (2026-09-17, appended after the runs)

The recorded "EA 150 vs python 147" divergence (run3,
`artifacts/midas_parity_result_20260916.json`) was fully root-caused:
**three stale vintages were being compared, and the harness aligned them
positionally.** No live EA defect exists. Findings, each verified today:

1. **The frozen python artifact predates Amendment 2.**
   `midas_parity_python_wf_rd.json` (147 trades, +5.55R) reproduces *exactly*
   only under the pre-amendment **Wilder** ATR; the engine of record (bounded
   SMA ATR) yields 151 trades, +1.47R on the same WF window. The 147-run was
   valid for its day but was never refreshed after the ATR definition fix.
2. **The run3 harness predated the v1.04+ BAR-parity engine**: it omitted
   `InpBarModel` and the `InpWindowStart/End` pins entirely (the tester pass
   ran whatever the compiled defaults were) and pointed at the deployed EA
   path by luck of the legacy folder. Its 150-vs-147 counts and its
   positional per-trade diffs were both artifacts of the harness, not the
   engines — after the first misalignment every |dR| is quantization noise
   against the wrong partner trade.
3. **Tester end-date truncation**: a pass ending `ToDate=2026.03.31` cuts the
   clock at 03-31 00:00, silently dropping trades that legitimately exit
   after t1 (WF's last trade opens 03-31 19:00, times out 04-01 07:00).
   `ToDate` must extend past the research window; signal membership stays
   EA-enforced via `InpWindowEnd` (v1.09 fail-closed pin).

The parity harness (`scripts/midas_parity.py`, v2, certified today) now:
regenerates python R from the engine of record at run time (no frozen
artifact dependency, selftest-gated); pins the full BAR-parity contract;
aligns trades **by key** (open_ct, close_ct, direction — positional zip is
banned evidence, pinned by tests); reads EA evidence from the agent sandbox
ledger (OPEN/CLOSE ticket join) with the journal as a degraded fallback;
rotates stale sandbox ledgers before each pass; honors the flat-check gate
including the gold ledger explicitly (`inventory_arms` only sees V75
charts); and pauses the paper arm's watchdog for the session.

**Certified result** (`artifacts/midas_parity_result_20260917_1258.json`,
WF window, REVERSE_DIRECTION, EA v1.09 BAR model, real ticks):
python 151 trades / +1.474R vs EA 151 trades / +1.478R — **count equal,
open/close times and direction identical on all 151 pairs, max |dR| =
0.0005R ≤ 0.01R** (run artifacts `_1252` and `_1258` record the failing
149/151 ToDate discovery and the passing pass; append-only).

**Scope: this is an ENGINE parity certificate, not a promotion.** §8 gates
an EA build only for a passing mode; the re-sweep verdict (Amendment 2)
stands: ALL 8 MODES NO-SHIP. No gate moved, no parameter touched. The
forward M1 paper arm (ORIGINAL) continues as the sole evidence collector.

**Certificate 2 — OOS window (2026-09-17, same day, append-only).** The
keyed harness was parametrized per window (`midas_parity.py --window`,
per-window tester tag/calendar; WF defaults untouched — the 12 pinned
harness tests still pass) and run over the independent OOS window
(2026-04-01 → 2026-09-16 23:59; tester calendar to 2026.09.18 for the
exit-buffer). Result (`artifacts/midas_parity_result_20260917_1336.json`,
real ticks, EA v1.09 BAR, REVERSE_DIRECTION): **python 108 trades / +8.199R
vs EA 108 trades / +8.202R — count equal, all 108 pairs identical on
open/close times and direction, max |dR| = 0.0005R ≤ 0.01R, first-run PASS
with no mechanism repairs needed.** Cross-validation: the python regen
reproduces the sweep's OOS anchor exactly (n=108, +8.199R,
`midas_sweep_20260917.json`), so the certificate also re-proves the sweep
engine against itself. Engine parity now holds on both sides of the frozen
window split — the harness is demonstrably not overfit to WF. Scope
unchanged: engine parity only; no promotion; the sweep verdict stands.

**Certificate 3 — full registry matrix, OOS window (2026-09-17,
append-only).** The harness was extended to the whole 8-mode registry
(`midas_parity.py --mode …, repeatable; per-mode tester tags; per-mode
sandbox-ledger rotation; one watchdog-paused session) and ran all 8 modes
over OOS in real ticks. Result
(`artifacts/midas_parity_matrix_oos_20260917_1348.json`): **8/8 PASS —
1,165 python trades vs 1,165 EA trades, every pair keyed identical on
open/close times and direction, worst per-mode max |dR| = 0.0005R ≤ 0.01R,
and every mode's regen reproduces the frozen sweep's OOS anchor exactly**
(ORIGINAL 94/+6.555, REVERSE_DIRECTION 108/+8.199, REVERSE_TRIGGER
218/+7.424, REVERSE_BOTH 236/−19.307, LONG_ONLY 41/−1.950, SHORT_ONLY
53/+8.505, MACRO_ONLY 226/+1.561, TRIGGER_ONLY 189/+1.080). Parity on the
losing modes is certified with the same rigor as on the winning ones. The
engine-parity certificate now covers the entire registry; scope unchanged:
engine parity only, ALL-8-MODES NO-SHIP stands, no promotion.

## 12. Standing infrastructure — the paper-arm watchdog and the
        parity-session pause discipline (registered 2026-09-17)

`scripts/midas_watchdog.py` is registered as standing infrastructure for the
M1 forward paper arm, the same class of permanent surface as morning_status.
It guards the two failure modes that silently corrupt a paper evidence
program: a dead arm that stops collecting, and a live-but-drifted arm that
collects the wrong config.

**Liveness leg.** The ledger's mtime IS the arm's heartbeat (EA v1.07+
stamps it every 15 min in every terminal state). STALE_MIN = 35 min plus a
10-min grace tier; beyond that, RESTUP — a PID-exact terminal restart that
is **fail-closed on the flat check**: a dangling OPEN, an unreadable ledger,
or a rowless/garbage file is never restarted over (the EA would adopt the
dangling position). ESCALATE after 3 consecutive restups without observed
recovery. Weekend no-restart policy (closed market, flat book).

**Config-drift leg.** The terminal journal's latest `MIDASTOUCH started`
banner is compared against the repo preset pins (mode / session /
execution / exec-model). Any mismatch is remediated by the flat-checked
restart **with the pins re-spliced into the chart before relaunch** (a
defaults-running instance would clobber the chart on graceful exit).
`execution=LIVE` is drift by definition. A broken/unreadable pins file is
observe-only — never a restart trigger. The banner covers four pins; the
complete input identity — all 30 keys, chart .chr vs repo .set, byte-exact
with drift reported on ANY difference including reformatting — is checked
independently by morning status [3b] (`preset_identity`, registered
2026-09-17), which prints preset DRIFT and marks the arm unhealthy; an
unreadable repo preset reports UNVERIFIABLE, never a silent skip. Two
independent layers (watchdog remediation, [3b] observation) so a bug in
either cannot hide drift from the other.

**Pause discipline for parity/tester sessions (operative rule).** The
watchdog and a tester session must never share the terminal uncoordinated:

1. Before a parity pass, compile-and-test session, or any deliberate
   terminal stop: `python scripts/midas_watchdog.py --pause` (creates
   `scripts/.midas_watchdog_paused`). While the marker exists the watchdog
   **observes only** — it records ledger age and banner state but never
   restarts, re-splices, or escalates.
2. After the session: `python scripts/midas_watchdog.py --resume`
   (removes the marker) and one observe poll to confirm the arm is
   discovered healthy.
3. The certified parity harness enforces this itself:
   `scripts/midas_parity.py` sets the marker on entry and lifts it on exit
   **only if it set it** — a pre-existing manual pause is never clobbered.
4. Hand-editing or experimenting on the live chart is NOT sanctioned by the
   pause marker alone: pausing stops the watchdog from fighting you, but any
   chart change still must go through the certified chain (preset file →
   `set_chart_preset.py` → banner verification) or it is drift by
   construction (Addendum, 2026-09-17 closeout; §10 precedent).

**Operator contract.** The watchdog runs from the user's session via
`start_midas_watchdog.bat` (`--loop 600`, 10-minute cycle; log
`artifacts/midas_watchdog.log`; state `artifacts/midas_watchdog_state.json`).
Agent-spawned processes are reaped, so since 2026-09-17 the loop is
**autostarted at user logon** by the per-user scheduled task `MIDAS Watchdog
Autostart` (`scripts/register_midas_watchdog_task.ps1`, idempotent;
`-Unregister` removes it; interactive logon trigger, no elevation — it must
be the user's session, never a service context). The start path stays the
certified launcher, the .bat, and the loop is **single-instance by lock**:
`artifacts/midas_watchdog.lock` is held on an OS handle for the loop's life
(released automatically on exit or crash), so the logon task and a manual
launch cannot both supervise — the second exits loudly instead of doubling
restart decisions. `--status` (one observe poll), `--dry-run`, `--force`,
and `--reset-state` exist for inspection and emergencies; `--force` is an
override that lands in the log and state, like the sweep runner's override
flag.

## 13. Amendment 4 — M1 forward arm verdict rule (frozen BEFORE the first fill)

**Written 2026-09-17 with the ledger holding zero fills** (0 OPEN/CLOSE rows,
equity never moved from $50.00). This section is the only rulebook by which
the M1 forward window is judged; amendments are append-only and dated, in the
arm-D discipline (docs/ARM_D_FORWARD_TEST.md — ported verbatim where the
program allows).

**What runs.** EA MidastouchAI v1.09, paper mirror (PERTICK fills,
`InpLiveExecution=false` hard), mode ORIGINAL (the plainest variant — zero
selection bias, Amendment 2), XAUUSDmicro M15, session 06–20 UTC, $50 virtual
book — the complete pin set in `mql5/MIDASTOUCH/MidastouchAI_M1_gold.set`,
verified byte-exact by morning status [3b] `preset_identity` and guarded by
the §12 watchdog. Ledger of record:
`MIDASTOUCH_paper_XAUUSDmicro_M1.csv`.

**Hypothesis under test.** The family's entry behavior on live gold ticks —
unselected, unoptimized — accrues non-negative expectancy with bounded
drawdown under the frozen cost model. This arm is evidence-collection about
the FAMILY, not a claim about ORIGINAL: the sweep's ALL-8-MODES NO-SHIP
verdict stands regardless of this window's outcome.

**Statistics.** R-denominated from the ledger's CLOSE rows, post-era rows
only (the ledger's ERA stamps carry the EA version; a version change is a
structural abort, not a continuation). Weekly `morning_status` glances are
ops, never judgment; the window is READ monthly, first reading **2026-10-01**.
With **n** = post-era closed trades:

| verdict | condition |
|---|---|
| **VALIDATED** | n ≥ 60 AND totalR > 0 AND max drawdown ≤ 25% AND meanR ≥ 0.05 |
| **CONTINUE-UNPROVEN** | n < 60, or the gray zones (positive R, calm DD, meanR in (0, 0.05); or DD in (25%, 30%] with positive R) |
| **REJECTED** | n ≥ 60 AND (totalR < 0 OR drawdown > 30% OR meanR ≤ 0) |

- **VALIDATED** advances the family to the pre-registered live-sizing path
  (§4 non-negotiables on their own terms + the GO_LIVE_CHECKLIST truth
  table). It does NOT authorize live orders by itself.
- **REJECTED** retires the family's forward line with a data-backed negative
  and closes this window forever as a fitting target: no re-tuning against
  it, no gate re-design from it — that would destroy the independence that
  is the arm's entire purpose.
- **Structural aborts (any time, restart the clock on a FRESH ledger):**
  ledger integrity problems flagged by [3b]; `preset DRIFT` or an escalated,
  unresolved watchdog state; a loaded-but-dead engine signature; an EA
  version change. A polluted window is never judged — after a structural
  fix the ledger is archived to `artifacts/paper_ledgers/` intact and the
  window re-accrues from zero.

**Basis honesty.** At the $50 book the min-lot stop-risk is ≈$5.87
(≈11.7% per trade) — TOLERATED, same disclosure class as arm D's ~10.1%;
R-denominated statistics are unaffected by the account basis, and dollar
conclusions at larger bases go through the live-sizing machinery, never
through this $50 book.

**Multiplicity and expected duration.** ONE pre-registered forward test of
ONE unselected variant; no interim parameter changes, no peeking-driven
design edits, no second variant on this window. The [3b] `closed: 0/30` line
is the §5 G1 gate-clock display; this adjudication reads at n ≥ 60. At the
sweep's observed rates (≈0.4–0.6 trades/day in-window) n ≥ 60 needs roughly
3–5 months from the first fill; the clock starts at the first fill, not at
this freezing. Tester numbers are context, never evidence: ORIGINAL's sweep
profile (n=560 across four windows, PF 1.12–1.39, all NO-SHIP on G3/G4,
`artifacts/midas_sweep_20260917.json`) is recorded here only so the forward
result has something honest to be compared against.

## 14. Amendment 5 — the forward portfolio (frozen BEFORE the first fill,
##      2026-09-17, ledger still 0 OPEN / 0 CLOSE)

§13 froze "ONE test of ONE variant." At the operator's direction, and while
the ledger provably holds zero fills (the only moment this is legal), the
forward test is widened from one arm to a **fixed portfolio of four arms**,
each an individually certified strategy from the frozen sweep, each with
its own $50 virtual book and its own §13-style ledger:

| arm tag | mode | chart | sweep basis (OOS, `midas_sweep_20260917.json`) |
|---|---|---|---|
| M1 (live, unchanged) | ORIGINAL | chart01 | n=94, +6.555R |
| M1t | REVERSE_TRIGGER | chart02 | n=218, +7.424R |
| M1s | SHORT_ONLY | chart03 | n=53, +8.505R |
| M1m | MACRO_ONLY | chart04 | n=226, +1.561R |

(The pre-existing M1 arm keeps its tag, chart, and legacy preset file name
`MidastouchAI_M1_gold.set` — amending them would itself be a post-hoc edit;
the portfolio slot M1o is filled by M1 as-deployed.)

**Unchanged and binding:** every strategy constant, every gate (session
06–20, spread cap, Friday cutoff, staleness, one-position, 12h timeout),
the $50 virtual basis, `InpLiveExecution=false`, and the §13 verdict table
itself. This amendment changes ONLY which strategies collect evidence and
how many arms run. It is NOT a response to any forward data — there is
none. LOOSING any gate or constant remains forbidden forever.

**Adjudication:** each arm is judged independently at its own n ≥ 60 by the
frozen §13 table (VALIDATED / CONTINUE-UNPROVEN / REJECTED, monthly from
2026-10-01, structural aborts restart that arm's clock on its own fresh
ledger). The family-level promotion question is answered only when every
arm has reached its reading; a single REJECTED arm is retired alone and
closes its window as a fitting target — the other arms continue.
**Expected cadence:** the portfolio's aggregate rate is ≈3.5 trades/day
(frozen-sweep rates, same gates), so first readings are expected in weeks,
not months. Busy-by-volume at the expense of busy-by-losing remains
rejected: REVERSE_BOTH (the only busier variant) stays excluded for its
measured −19.3R OOS.

**Tooling obligation created by this amendment:** the watchdog, morning
status [3b], and the flat-check gates must treat the portfolio as N arms
(one ledger each). Until that ships, deploying more than one arm is
forbidden — an unguarded arm violates §12. (Watchdog/[3b] multi-arm
support ships with this amendment's deployment.)

## 15. Amendment 6 — min-lot risk refusal (2026-09-17, registered BEFORE
any window it can affect; register R5)

The register's review (#5) found a real defect class in both engines: when
the computed lots fall below the broker minimum, the trade is FLOORED to
the minimum and the real risk exceeds the configured risk — disclosed in
logs and ledgers ($4.55 observed vs ~$0.30 intended on day one) but never
enforced. Logging is not risk management. This amendment changes the
fill decision identically in BOTH engines (python `scripts/midas_sweep.py`,
EA v1.14), in the same commit, per the register's parity-gated class.

**The rule (frozen):** when the computed lots are below the broker minimum
(0.01), the trade fills ONLY if
`stop_d * 100.0 * 0.01 <= basis * MAX_RISK_FRACTION`
(python: `TICK_VALUE_PER_LOT=100.0`, `MIN_LOT=0.01`,
`MAX_RISK_FRACTION=0.15`; EA: `dpu`, `SYMBOL_VOLUME_MIN`,
`InpMaxRiskPct=15.0`). If the min-lot risk would EXCEED the cap (strict
inequality — exactly-at-cap fills), the trade is VETOED:

* **python** (`run_mode`, pending-fill site): the pending signal is dropped
  (`pending = None`), `RunResult.vetoed += 1`;
* **EA BAR model** (`BarFillAndManage`): pending killed, HUD note, ledger
  row `SKIP,<epoch>,RISK-CAP,<tag>` (a new row type by design — python has
  no ledger);
* **EA PERTICK paper** (`OpenPaperPosition`): veto before fill, HUD note;
* **EA live** (`LiveSendOrder`): the order is refused — basis is ACCOUNT
  EQUITY, the same quantity the sizing used.

The sizing basis is the engine's OWN basis (python/EA paper: virtual
equity at fill; EA live: account equity) — each engine vetoes against the
same quantity it sizes with. **Cap value — the measured decision:** the
certified WF corpus floors 42/151 fills at up to $277.30 = 5.5% of the
research book, and the $50 §13 arms (micro contract, ≈$4.55 day-one
min-lot risk) sit above every cap below ~10% of basis. The decision table,
frozen with the amendment: 1.5% vetoes 15 certified fills and starves the
forward arms entirely; 2% vetoes 10; 5% vetoes 1; 10% and 15% veto ZERO.
**15% is frozen** — corpus-neutral (the veto never fires on the certified
windows), arm-compatible (day-one risk passes with ≈2× margin), and still
binding on the pathology the review demanded be closed (a small book
eating a runaway stop). A 1.5% cap ported from the V75 checklist would
have silently rewritten certified behavior — the register's warning to
"port the mechanism, not the doc" was correct. A veto is NOT a structural
event: it changes the SET of trades, so this is a parity-gated amendment,
not telemetry — windows accrued under v1.10–v1.13 behavior are not
comparable with v1.14+ behavior and MUST NOT be stitched. Era rules:

1. Nothing deploys before the 2026-10-01 first monthly §13 reading.
2. The v1.14 code may compile and sit in-tree (its own fresh-ledger era
   stamp on eventual attach).
3. After the reading: deploy v1.14, fresh ledgers, windows re-accrue; the
   certified parity baseline must be renewed for v1.14 (shadow-path WF
   pass per register §3) BEFORE the deploy.

Verified corpus-neutral by measurement: with MAX_RISK_FRACTION=0.15 the
python regen of record is n=151 / +1.474R on WF with vetoed=0 — every
certified number stands — and `tests/test_midas_minlot_veto.py` enforces
that regression law permanently. The veto exists for the corner the
certified corpus never visits: small basis, runaway stop.

## 16. Amendment 7 — the data of record is re-based to the venue's own series
##      (2026-09-21, appended after the fact; §1 is superseded, not edited)

**§1's paths no longer exist, and that is deliberate.** The two series in
`data/forex/xauusd/` were not the same market: the files §1 names were fetched
from the DERIV install on 2026-09-17, while the funded account trades Upcomers,
whose own XAUUSD history begins **2026-01-12 11:15 UTC**. Inside the tick-covered
window the two disagree about **21 bars** (3 only in the research series, 18 only
at the venue) and about the units of their `spread` column (dollars vs points,
which let a staged spread file hand the EA a flat $0.15 where the engine of record
charged $0.42 — a constant $0.135 per fill that moved a stop's touch 105 minutes).

Changed, all of it on 2026-09-21:

- **Data of record = the venue's own series**: `XAUUSD_{M15,H1,D1}_upcomers.csv`
  in `data/forex/xauusd/`, the terminal's history for account 1428765.
  `scripts/midas_fetch_history.py --suffix _upcomers` is the fetch of record.
- **The research series is RETIRED and then DELETED** (2026-09-21): one commit in a
  hash-pinned archive (`archive/frozen_corpus/`, committed in `248db66`), then removed
  from the working tree, because §9-§15's certified arithmetic being stated on bytes
  nobody else can obtain is a citation that cannot be checked. `midas_sweep.frozen_bars()`
  remains as the only reader and verifies every SHA-256 in `configs/frozen_corpus.json`,
  which is what makes the restore (`git checkout 248db66 -- archive/frozen_corpus`)
  verifiable. **The arithmetic in §9-§15 stays true as history and stops being
  re-derivable** — the survey of exactly which citations that costs is in
  `docs/FROZEN_CORPUS_20260921.md` §4, and the regression law was re-pointed onto the
  venue's own bars (§16 note below).
- **Every window declares its corpus and there is no default.** Parity's four
  comparison windows declare `venue`; `wf`/`oos` declare `frozen`, because the
  venue cannot serve them (`wf`: 7,752 of its bars exist only in the archive).
- **The veto's own regression law moved with the corpus**: `tests/test_midas_minlot_veto.py`
  now pins n=53 / +14.256R / vetoed=0 on the venue's bars over 2026-01-12..03-31
  (measured 2026-09-21), instead of n=151 / +1.474R on a series that no longer exists.
  The claim being tested is unchanged: the min-lot veto does not move the engine of
  record's trade set.

**What this means for the certification, plainly**: the walk-forward verdict
  (fold-mean t = +0.52) is a **venue-corpus** number — `gold_walkforward.py` reads
  the terminal, not the archive — so the re-basing did not move it. But §4's
  window cannot be walked on the venue's own bars before 2026-01-12, and the
  venue's real ticks begin 2026-09-04, so the only window this venue can certify
  per-tick is the one since 2026-09-04.

Full record and measurements: `docs/FROZEN_CORPUS_20260921.md` and
`docs/PARITY_ENTRY_SIGNALS_20260921.md` §5c.
