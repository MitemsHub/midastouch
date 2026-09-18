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

## 11. Amendment 3 — outcome-level parity certified (2026-09-17, parity-driven)

Amendment 2 called the EA's parity "solved" on the strength of entry
timestamps alone. The subsequent certification-grade comparison proved that
wrong: 150 EA trades vs 151 python with entries aligned but outcomes
diverging (SL-vs-TIMEOUT splits, different stop distances, a truncated
tail). Root-caused over three EA revisions; every cause below is proven by
instrumented tester runs, not inferred:

1. **Wilder ATR is not parity-achievable in the tester** (Amendment 2's
   fix stands): the bounded SMA-ATR definition stays the ATR of record.
2. **Per-tick execution cannot mirror a bar-model backtest**: the EA's
   per-tick timeout fired ~15 min before python's bar-close timeout, and
   live-tick spreads differ from the broker-recorded per-bar spread series
   the python engine prices with. **Execution model of record for parity
   (and for any certification run) is now the BAR model** (`InpBarModel`):
   the EA replays completed bars in python's exact pass order — fill at
   next bar open, manage on the full bar, signal on the closed bar, bar-
   close timeout, prices taken from the bar series plus the **shared
   recorded-spread series** (`artifacts/MIDASTOUCH_spread_M15.csv`, written
   from the same CSV python prices with; loaded via
   `#property tester_file`).
3. **Shift-space ATR chaining bug** (v1.05, found by dumping the EA's
   actual 14-bar TR window at the first signal — bars byte-identical to
   the CSV, manual SMA over them = python's 7.9243 exactly, EA computed
   9.3565): the TR chain walked newest→oldest while chaining each TR to
   the close of the bar one shift *newer* instead of one shift *older*.
   13 of 14 TRs referenced the wrong close → stops inflated ~18% → every
   downstream outcome diverged, including one lost fill (a mis-stopped
   prior trade still held the position over the next signal, and python's
   no-signal-while-in-position rule silently skipped it). Fixed: chain
   oldest→newest from close(k+14). This is the bug Amendment 2's "entries
   aligned" evidence could not see.
4. **Loop-domain exactness**: the EA's replay processes every bar in
   python's exact domain (`t0 < open <= t1+900`), suppresses signals on
   any bar where a position existed at bar start, and keeps managing open
   positions past window end — python's semantics, bar for bar.
5. **Tick model**: parity passes run the tester on **1-minute OHLC
   (Model=1)** so every M15 bar receives tick events; the BAR model prices
   nothing from ticks, so the model affects timing only. (Real-tick mode
   skips OnTick on zero-tick bars, which truncates the replay — the cause
   of a 9-trade tail loss in an intermediate build.)

**Certificate.** `scripts/midas_parity.py` (prepare/run/compare, artifact
`artifacts/midas_parity_result_20260917.json`, tag `midas_wf_rd_bar`,
window `wf`/REVERSE_DIRECTION, dates 2025.09.15→2026.04.03):
**EA v1.06 BAR model vs python sweep engine — 151/151 trades, identical
entries, exits, reasons and prices; 0 mismatching rows; max |dR| 0.0005
vs tolerance 0.01.** Regression fingerprint: current engine reproduces the
staged baseline (match). The v1.06 build is therefore **certification-
ready**: any future mode that passes the gates can be certified for
shipping without further EA work. Per §8 this certificate gates the *EA
build*, not a strategy: the sweep verdict remains **all modes NO-SHIP**,
and the live paper arm (M1, now on v1.06) continues as forward-evidence
collection. PERTICK remains the live execution model; the BAR model exists
for certification parity and shares all signal math with it.

## 12. Amendment 4 — PRE-REGISTERED: London/NY-overlap session hypothesis (H3)

**Status: hypothesis frozen 2026-09-17, BEFORE any overlap-gated run was
executed.** This amendment was written in full — definition, decision rule,
and anti-shopping clauses below — before a single overlap number existed.

### 12.1 Lineage (disclosed, not hidden)

§6's H1 already named 12:00–16:00 UTC as an exploratory session hypothesis
with an uplift gate, usable only to qualify an already-passing mode. No
mode has ever passed, so H1 was never evaluated. The playbook (2026-09-16,
prior to this amendment) measured gold's volume peak at 13:00–15:00 UTC on
our own data. Amendment 4 deliberately **escalates the same hour bounds to
a one-shot, full promotion-path test**: all 8 modes, all 4 frozen windows,
frozen gates. This is the only session escalation that will be run against
the frozen OOS window.

### 12.2 Hypothesis H3 (frozen wording)

**Restricting entries to the London/NY overlap (signal-bar open hour in
[12:00, 16:00) UTC) improves risk-adjusted performance enough to pass the
frozen gate matrix for at least one mode.** Mechanism (prior reasoning,
not evidence): overlap hours concentrate London + New York liquidity in
gold — deeper books, tighter effective spreads, more institutional flow —
so the family's mean-reversion triggers should fill cheaper and resolve
cleaner. The overlap window is a strict subset of the frozen 06–20
session, so no policy conflict arises.

### 12.3 Exact test configuration (frozen)

- **Session definition of record:** hour-of-open of the signal bar in
  [12, 16) UTC — the same classification basis as the frozen 06–20 gate
  (§4's pending-fill semantics unchanged: fill at next M15 open).
- **Engine:** `scripts/midas_sweep.py` `run_mode` with a session parameter;
  every other byte of behavior identical (data, indicators, cost model,
  sizing, windows).
- **Scope:** ALL 8 modes × ALL 4 frozen windows (IS1, IS2, WF, OOS), run
  symmetrically — no mode pre-selection.
- **Scoring:** the frozen `gates()` function of §5, unmodified, on the
  overlap re-simulation's OOS metrics and window nets. G2 is adjudicated
  under BOTH R measures: the frozen function's ratio measure plus the
  money-implied check (OOS net_pnl > 0) appended by the runner — strictly
  stricter than the frozen scorer alone.
- **Integrity precondition:** before any overlap number is read, the engine
  re-run at the default session (06–20) must reproduce the artifact of
  record (`artifacts/midas_sweep_20260917.json`) per-window metrics
  exactly (n, net_r, pf, net_pnl, expectancy, dd). Any mismatch voids the
  test until explained.

### 12.4 Decision rule (frozen before the run)

- A mode PASSES the §12 regime test iff the frozen gate matrix (G1–G7,
  with the dual-measure G2) passes on its overlap re-simulation. Per §8, a
  passing mode proceeds to EA-build parity certification — the v1.06
  certification harness exists for exactly this.
- If NO mode passes, **H3 is recorded falsified-for-promotion** with the
  full matrix published, and the 06–20 session stands as the policy of
  record. The falsifiable pre-prediction: if the overlap edge is real,
  at least one mode's G6 window-consistency should improve (fewer
  negative windows) versus its full-session run. If no mode's G6 status
  changes, the session hypothesis gains no support **regardless of how
  good any single OOS number looks** — a beautiful OOS alone will not be
  narrated into a pass.
- **No variations:** no alternative hour bounds, no per-mode session
  splits, no window re-definitions, no gate adjustments, no re-rolls. One
  shot. A failed H3 can only be revisited with NEW forward evidence from
  the paper arm, never by replaying the frozen OOS again.

### 12.5 OOS-touch accounting

§4 grants the frozen OOS window (2026-04-01 → 2026-09-16) exactly one
look. The §11 regime test did not evaluate session variants, so this
amendment's run is the granted look **for the session-hypothesis family**.
After this run the family is exhausted against historical OOS; any future
session claim must stand on forward paper evidence.

### 12.6 Non-decisive cross-check (descriptive only)

The frozen full-session trade rows (regenerated deterministically via
`--window-trades`, integrity-checked against the artifact) will be split
by entry hour: overlap vs rest, per mode per window. This is reported as
descriptive support in the results section and **cannot flip the §12.4
verdict** — the re-simulation is the verdict basis because a session-gated
engine changes which signals exist at all (position-holding interactions),
not merely which rows are counted.

### 12.7 Results (2026-09-17, appended after the one-shot run)

**Integrity precondition: PASS** — the engine at the default 06–20 session
reproduced `artifacts/midas_sweep_20260917.json` exactly on every mode ×
window metric (n, net_r, pf, net_pnl, expectancy, dd). The run proceeded.

**Gate matrix (frozen scorer + dual money measure), overlap 12–16 UTC:**

| mode | OOS n | OOS netR | OOS PF | OOS exp | OOS ddR | G6 | verdict |
|---|---|---|---|---|---|---|---|
| REVERSE_TRIGGER | 129 | +29.44 | 1.679 | +0.228 | 5.48 | 4/4 | **EDGE** |
| MACRO_ONLY | 133 | +30.90 | 1.684 | +0.232 | 5.95 | 3/4 | **EDGE** |
| SHORT_ONLY | 31 | +4.54 | 1.331 | +0.146 | 4.21 | 3/4 | NO-SHIP (PF 1.331 < 1.30? no — G3 pass; exp 0.146 < 0.15 → G4 fail) |
| ORIGINAL | 58 | +1.87 | 1.053 | +0.032 | 5.80 | 4/4 | NO-SHIP (G3, G4) |
| REVERSE_DIRECTION | 60 | +3.14 | 1.108 | +0.052 | 6.50 | 4/4 | NO-SHIP (G3, G4) |
| LONG_ONLY | 27 | −2.67 | 0.764 | −0.099 | 4.93 | 3/4 | NO-SHIP (G1, G2, G3, G4) |
| REVERSE_BOTH | 161 | −23.84 | 0.712 | −0.148 | 31.73 | 0/4 | NO-SHIP (G2–G6) |
| TRIGGER_ONLY | 127 | −3.22 | 0.927 | −0.025 | 15.89 | 1/4 | NO-SHIP (G2–G5) |

Artifact of record: `artifacts/midas_sweep_session_20260917.json`
(contains full overlap trade rows, verdicts, G6 shift table, cross-check).

**Mechanism status per §12.4's pre-prediction: NOT confirmed for the
passing modes.** The G6 shift table (overlap vs full session):
REVERSE_TRIGGER 4/4 → 4/4 (no change), MACRO_ONLY 4/4 → **3/4
(deteriorated; lost IS1 by −0.87R)**, SHORT_ONLY 2/4 → 3/4 (improved, but
still NO-SHIP), TRIGGER_ONLY 3/4 → 1/4 (deteriorated), others unchanged.
The pre-registered mechanism — overlap restriction should improve
window-consistency — is therefore unsupported for the modes that passed:
their OOS improvement (+29R / +31R vs +7R / +2R full-session) came through
path-selection in the re-simulation, not from more consistent windows.

**Cross-check (§12.6, descriptive, cannot flip the verdict):** in the
frozen full-session runs, OOS trades *entered during overlap hours*
performed no better than the rest — REVERSE_TRIGGER overlap subset
n=44, +0.11R (exp +0.002) vs rest n=174, +7.32R (exp +0.042);
MACRO_ONLY overlap subset n=45, **−1.58R** vs rest +3.14R. The re-sim's
edge therefore does **not** come from overlap-hour trades being inherently
better; it comes from which trades the constrained path takes (a
flat-selective engine during 12–16h holds a different trade population
than the 06–20 engine, whose overlap-hour entries are conditional on
surviving earlier trades). Both views are recorded; neither is narrated
away.

**Disposition (mechanical, per §12.4 and §8):**
- REVERSE_TRIGGER and MACRO_ONLY pass the frozen matrix on this OOS look
  and earn the §8 path: **EA-build parity certification on the overlap
  configuration**. REVERSE_TRIGGER is already EA-implemented (mode 2;
  session inputs exist — certification sets 12/16). MACRO_ONLY is not
  implemented in the EA; certifying it requires a build extension first.
- The pass is a **matrix pass, not an edge confirmation**: the mechanism
  prediction failed for both passing modes and the descriptive hour-split
  contradicts the H3 story. Both facts ride with the pass into the next
  protocol stage, where certification parity (§11 harness) is the next
  gate — mechanical, no further historical OOS looks.
- Per §12.5 the session-hypothesis family is now **exhausted against the
  frozen OOS window**. No further historical session test may be run.
  Forward paper evidence is the only remaining path for session claims.
- All other modes: NO-SHIP recorded with numbers, as always.

## 13. Amendment 5 — execution layer certified, integrity hardened,
### REVERSE_TRIGGER §8 path COMPLETE (2026-09-17, appended after the work)

### 13.1 What was built (v1.08 → v1.09)

**v1.08 — the live order path** (all live-only features gate on
`InpLiveExecution`; parity runs set it false, so the certified BAR contract
is untouched by construction):
- CTrade market orders, server-side SL/TP, retries with 300 ms backoff,
  vol sizing on real equity with min-lot floor (+`_FLOORED` ledger marker).
- Guards, all fail-closed and vetoing BEFORE any order: session gate,
  Friday cutoff (entries) + Friday force-flat (exits, weekend gap guard),
  spread cap (1.5% of stop), stops-level veto, 30-min staleness gate,
  daily equity circuit breaker (UTC-day re-arm, default 3%).
- External-close reconciliation: if SL/TP fires while the EA is down,
  re-init adopts the real position state and the exit is journaled from
  deal history (`LCLOSE,...,EXTERNAL`). Timeout close mirrored live.
- Parity bug found in audit and fixed: PERTICK paper buys filled at
  `ask + sprd/2` (a full spread worse than research) — corrected to the
  research fill (bid-mid ± half-spread both sides).

**v1.09 — integrity hardening after the 2026-09-17 sandbox-pollution
incident** (a stale full-year PERTICK ledger from a mis-windowed tester
pass was consumed by a compare and produced a garbage verdict):
1. **EA-enforced research window**: BAR parity now REQUIRES
   `InpWindowStart/End` = python t0/t1 (init fails closed otherwise) and
   `BarEvaluateSignal` enforces `t0 < sig+900 <= t1` EA-side. Tester dates
   or preloaded history can no longer leak out-of-window signals.
2. **Honest ERA provenance**: the ERA era_name field now reflects the real
   execution model (`bar-model-parity` in BAR passes, `pertick-fills` on
   the live ledger). A BAR ledger can no longer self-describe as pertick.
3. **Driver hygiene**: `--run` deletes any stale sandbox ledger before the
   pass; `--compare` verifies the ledger's ERA provenance (abort on any
   non-`bar-model-parity` note) before scoring.

### 13.2 Certification status (§8 parity stage — COMPLETE for RT @ 12–16)

| config | python | EA | verdict | artifact |
|---|---|---|---|---|
| REVERSE_DIRECTION @ 06–20 (v1.09) | 151, +1.474R | 151, +1.478R | **PASS**, 0 rows, max\|dR\| 0.0005 | `midas_parity_result_midas_wf_reverse_direction_ses620_20260917.json` |
| REVERSE_TRIGGER @ 12–16 (v1.09) | 159, +18.017R | 159, +18.020R | **PASS**, 0 rows, max\|dR\| 0.0005 | `midas_parity_result_midas_wf_reverse_trigger_ses1216_20260917.json` |

Both on the 1-minute-OHLC BAR model with the shared recorded-spread series;
the REVERSE_TRIGGER baseline equals Amendment 4's wf re-sim (+18.017R —
internal consistency). The MACRO_ONLY EDGE verdict remains uncertifiable
(mode not EA-implemented); building it would add a 9th mode to a program
whose matrix already has two shippable configs — declined as scope creep
unless REVERSE_TRIGGER forward evidence fails.

### 13.3 Simulated-live proof (real ticks, live order path ON)

169 real-tick market orders over the wf window (REVERSE_TRIGGER @ 12–16):
LOPEN 169 / LCLOSE 168 (one position legitimately open at window end),
zero paper-mirror rows (no contamination). Exit families exercised:
EXTERNAL 86 (server-side SL/TP reconciled from deal history), TIMEOUT 69,
FRIDAY-FLAT 13 (the weekend gap guard fired for real). The sim measures
PERTICK's execution gap vs the BAR research number (fewer signals on
quiet bars) — the known, disclosed BAR/PERTICK distinction; BAR parity
is the certification instrument, PERTICK is what live runs.

### 13.4 Arm-policy decision (EA-owner call, mechanical rationale)

The live paper arm switches to **REVERSE_TRIGGER @ 12–16** — the certified
ship candidate. Rationale: the 30-fill gate clock has not started (0 fills),
so switching costs zero evidence; forward paper evidence must be collected
on the mode we intend to ship, not on a superseded policy. Watchdog, ledger
continuity, and virtual equity are unchanged. Forward evidence on
ORIGINAL @ 06–20 would have required a second 30-trade campaign later.

### 13.5 What stands between here and live deployment

Unchanged pre-registered gates, now all evidenced on the ship candidate:
1. ≥ 30 closed paper trades, positive expectancy (clock starts at first
   fill of the new era).
2. Tick reconciliation PASS at 7 days of ledger.
3. Watchdog certification (relaunch + verify loop already proven live;
   30-day incident-free record accrues).
No gate was altered by this amendment; the execution layer only had to
reach the bar the research contract already set.
