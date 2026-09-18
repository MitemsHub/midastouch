# MIDASTOUCH CLOSEOUT — 2026-09-17 (drift caught and guarded, parity certified, verdict rule frozen)

**Summary:** The gold paper arm survived two unregistered input-drift incidents
in one morning — both caught, both restored through the certified chain, zero
trades lost — and the day produced the program's permanent defenses (watchdog
auto-remediation, byte-exact preset-identity check, registered pause
discipline), the **150-vs-147 parity root-cause** with three certified parity
certificates (WF, OOS, full 8-mode registry — 1,165 keyed trades, worst
|dR| = 0.0005R), and the **forward verdict rule frozen before the first fill**.
The ledger ends the day exactly as it must: flat, veq $50.00, 0 closed trades,
gate clock still waiting for its first fill. Nothing was promoted; the
ALL-8-MODES NO-SHIP verdict stands.

## Timeline (UTC)

| time | event |
|---|---|
| (morning) | Incident 1 found: the 09:57 attach ran **mode=2 REVERSE_TRIGGER, session 12–16** — an unregistered variant left by the interrupted parity session, which had used the live chart as its test bench (v1.04→v1.09 re-inits, ~19 that morning) |
| 10:56 | Incident 1 restored: `MidastouchAI_M1_gold.set` rewritten as the complete 30-key pin set (mode=0 ORIGINAL, session 06–20, $50 virtual, PERTICK, `InpLiveExecution=false` hard), spliced via `set_chart_preset.py` (chart backup kept), terminal recycled |
| 10:57:15 | Boot banner verified pin-for-pin; morning status [3b] green |
| ~11:00 | `scripts/midas_watchdog.py` shipped (liveness + flat-check-gated restart, 21 offline tests) |
| 11:11:45 | Incident 2: EA re-attached with **code defaults** (mode=1, $1000 virtual basis) — 25 minutes after the pinned restore. The new watchdog caught it during its own shakedown |
| 11:42:52 | Watchdog remediation completed on camera: drift detected → terminal stopped → pins re-spliced (backup kept) → relaunched → pinned banner verified → next poll `RECOVERED`, counter reset |
| 12:52 | Parity run `…_1252`: FAIL 149/151 — the last 2 trades missing → **ToDate 00:00 truncation** identified as the third root-cause leg |
| 12:58 | **Certificate 1 (WF): PASS** — 151 vs 151 keyed trades, max \|dR\| = 0.0005R (`…_1258`) |
| 13:36 | **Certificate 2 (OOS): PASS first run** — 108 vs 108, max \|dR\| = 0.0005R, sweep anchor reproduced exactly (`…_1336`) |
| 13:48 | **Certificate 3 (full registry matrix, OOS): 8/8 PASS** — 1,165 vs 1,165 keyed trades, all 8 sweep anchors reproduced (`midas_parity_matrix_oos_20260917_1348`) |
| (evening) | Protocol §12 (watchdog infrastructure + pause discipline), §13 (verdict rule, frozen with zero fills), [3b] preset-identity check all registered and tested |
| ~21:00 | **Shadow-path parity attempt for v1.13 (requested re-cert): gate held again** — M1t/M1m still hold their 15:00 positions; harness refused, terminal untouched. Python-half regression proof executed instead (see register §3): WF regen n=151 / +1.474R identical to certificate 1's python leg; OOS matrix (8/8 PASS, same day) covers the full registry. v1.11/v1.12/v1.13 EA-side certification remains one flat-window run away (exact command in register §3) |

## The two drift incidents — what they proved

Both incidents were the same failure class the protocol's "no hand-tuning
while collecting" rule exists to prevent, arriving by two different doors:

1. **The experiment leak (09:57).** A tester experiment's inputs ended up on
   the live chart because parity iterations compiled and re-attached through
   the chart instead of the tester sandbox. The chart sat on an unregistered
   config for the whole morning.
2. **The bare re-attach (11:11).** A hand-drag attach without loading the
   preset ran the EA's *code defaults* — mode=1, $1000 virtual — which would
   have silently changed the arm's sizing basis had a trade fired.

**Facts that kept the program honest:** zero fills fell in either drift
window (verified in the ledger both times — flat, equity unmoved), so the
evidence stream was never polluted. Both restorations went through the
certified chain: repo preset → `set_chart_preset.py` (byte-verified splice,
backup first) → boot-banner verification. Neither incident was caught by
luck after the first one — the watchdog found the second autonomously.

**The permanent guards this day bought (protocol §12, closeout addenda 1–3):**

- **Watchdog** (`scripts/midas_watchdog.py` + `start_midas_watchdog.bat`):
  ledger-mtime liveness (35+10 min tiers, flat-check-gated PID-exact restart,
  escalate at 3, weekend guard) plus the config-drift leg (journal banner vs
  repo pins, re-splice before relaunch, `execution=LIVE` is drift by
  definition, broken pins observe-only).
- **Preset-identity check** (morning status [3b] `preset_identity`): all 30
  chart inputs byte-exact against the repo .set; any difference — even pure
  reformatting — prints `preset DRIFT` and marks the arm unhealthy;
  unreadable pins report UNVERIFIABLE (fail-closed, never a silent skip).
  Two independent layers (watchdog remediation, [3b] observation) so a bug
  in either cannot hide drift behind the other.
- **Pause discipline** for parity/tester sessions: `--pause`/`--resume`
  around any deliberate terminal stop; the certified harness holds the
  marker itself and never lifts a manual pause; pausing never sanctions
  hand edits on the live chart.

## Parity: 150-vs-147 root-caused, then certified three times

**Root cause (protocol §11, Amendment 3).** The recorded run3 divergence
(EA 150 vs python 147) was **three stale vintages compared positionally** —
no live EA defect existed:

1. The frozen python artifact (147 trades) reproduces *exactly* only under
   pre-amendment-2 Wilder ATR; the SMA-ATR engine of record yields 151
   trades / +1.47R on WF.
2. The run3 harness predated the v1.04+ BAR-parity engine: no `InpBarModel`,
   no `InpWindowStart/End` pins — and it zipped trades **positionally**, so
   after the first misalignment every reported |dR| was quantization noise
   against the wrong partner trade.
3. A pass ending `ToDate=2026.03.31` truncates the tester clock at 03-31
   00:00 and silently drops trades that legitimately exit after t1 — found
   live as the 149/151 FAIL of run `…_1252`, fixed by extending the calendar
   past the research window (signals stay window-pinned EA-side).

Honest provenance note: the interrupted session had already achieved
substantive parity (its sandbox ledger matched the current engine on all
151 pairs); today's work made the *harness* trustworthy — keyed alignment,
regen-from-source, rotation, pinned contract — and the result reproducible.

**The harness** (`scripts/midas_parity.py` v2, 18 pinned tests): python R
regenerated from the engine of record at run time (selftest-gated); the full
BAR contract pinned; trades aligned **by key** (open/close ct + direction —
positional zip is fail-closed illegal evidence); EA evidence from the agent
sandbox ledger via ticket-join (journal fallback is keyless and can never
PASS); sandbox-ledger rotation per pass; gold-ledger flat-check (the V75
inventory is blind to gold charts — found live); watchdog pause handled
in-session; `--window wf|oos` and `--mode …` (repeatable, all 8 registry
modes).

**Certificates (all real ticks, EA v1.09 BAR, tolerance 0.01R):**

| # | window / scope | python | EA | max \|dR\| | anchors | artifact |
|---|---|---|---|---|---|---|
| 1 | WF, REVERSE_DIRECTION | 151 / +1.474R | 151 / +1.478R | 0.0005 | — | `…_20260917_1258.json` |
| 2 | OOS, REVERSE_DIRECTION | 108 / +8.199R | 108 / +8.202R | 0.0005 | reproduced | `…_20260917_1336.json` |
| 3 | OOS, **all 8 modes** | 1,165 | 1,165 | 0.0005 (worst) | 8/8 reproduced | `…_matrix_oos_20260917_1348.json` |

Parity on the losers (REVERSE_BOTH −19.307R, LONG_ONLY −1.950R) is certified
with the same rigor as on the winners. Every regen reproduced the frozen
sweep's OOS anchors exactly, so the certificates also re-prove the sweep
engine against itself. **Scope: engine parity only** — ALL-8-MODES NO-SHIP
stands, no gate moved, no parameter touched.

## Pre-registrations completed today

- **§12** — watchdog registered as standing infrastructure with the
  parity-session pause discipline (operative rule, operator contract).
- **§13 / Amendment 4** — M1 forward verdict rule **frozen with zero fills
  verified at write time**: VALIDATED n≥60 ∧ totalR>0 ∧ DD≤25% ∧ meanR≥0.05;
  CONTINUE-UNPROVEN below n=60 or in the gray zones; REJECTED n≥60 ∧
  (totalR<0 ∨ DD>30% ∨ meanR≤0). Monthly readings from **2026-10-01**;
  structural aborts restart the clock on a fresh ledger; the window is
  closed forever as a fitting target on REJECTED.
- **[3b] preset-identity** — the silent-preset-loss guard (11 tests; fixtures
  self-maintained against the real .set).

## Standing record

- One terminal (49E0), one chart (XAUUSDmicro M15), EA v1.09 paper mirror —
  the complete pin set in `mql5/MIDASTOUCH/MidastouchAI_M1_gold.set`.
- Real account 140778269 untouched at $50.22; no real order has ever been
  sent by this program. `InpLiveExecution=false` is a hard pin.
- Watchdog runs **from the user's session** via `start_midas_watchdog.bat`
  (agent-spawned processes are reaped); log
  `artifacts/midas_watchdog.log`, state `artifacts/midas_watchdog_state.json`.
- The index-EA and V75 arm stop of 2026-09-16 is unchanged; indices stay off.

## End-of-day state (verified)

- [3b]: `preset: OK (30 inputs byte-identical to repo .set)` — veq 50.00
  (start 50.00), live flat, `closed: 0/30 - gate clock starts at first fill`.
- Watchdog: 0 consecutive restups, 1 lifetime (the 11:42 remediation);
  pause marker clean.
- Test suites (harness, watchdog, [3b], preset-identity): 66 passing.

## Artifacts index (new today)

| artifact | path |
|---|---|
| Watchdog + launcher | `scripts/midas_watchdog.py`, `start_midas_watchdog.bat` |
| Watchdog log/state | `artifacts/midas_watchdog.log`, `artifacts/midas_watchdog_state.json` |
| Parity harness v2 + tests | `scripts/midas_parity.py`, `tests/test_midas_parity.py` |
| Certificate 1 (WF) | `artifacts/midas_parity_result_20260917_1258.json` (FAIL run `…_1252` kept as the ToDate-discovery record) |
| Certificate 2 (OOS) | `artifacts/midas_parity_result_20260917_1336.json` |
| Certificate 3 (registry matrix) | `artifacts/midas_parity_matrix_oos_20260917_1348.json` |
| Preset-identity guard + tests | `scripts/morning_status.py` (`preset_identity`), `tests/test_morning_status_preset.py` |
| Protocol amendments | `docs/MIDASTOUCH_PROTOCOL.md` §11 (certs), §12 (infrastructure), §13 (verdict rule) |

## Addendum (2) — GO-LIVE 2026-09-18 (~08:40 UTC)

The gold EA went live: MidastouchAI v1.16 on XAUUSDmicro, real account
140778269 ($50.22), terminal 49E0 chart05, arm tag LV, magic 7801601,
`InpLiveExecution=true` — the M1 certified pin set with only
identity+execution deltas, verified 31/31 byte-identical at boot; banner
`execution=LIVE | exec-model=PERTICK`, floor table min-lot risk $2.91
(5.8% of equity — inside the 15% R5 cap), AutoTrading verified ON via the
MT5 API, LV ledger era-stamped, heartbeat ticking, watchdog resumed and
supervising. Watchdog flat gate + morning status learned the live ledger
grammar (LOPEN/LCLOSE): a dangling LOPEN is a REAL position and blocks
terminal restarts (SKIP-OPEN-POSITION). Live-arm [3b] block shows the
position, closes and exit reasons. Pins: `tests/test_midas_golive_grammar.py`
(15). Full block: V2 register GO-LIVE EXECUTION BLOCK (operator-authorized
attach).

## Addendum (2026-09-18, afternoon)

**First-live-trade ritual pre-registered BEFORE any fill**
(`docs/MIDASTOUCH_FIRST_LIVE_TRADE.md`): Phase A verify (row integrity,
broker cross-check, [3b]+watchdog visibility), Phase B no-interference
monitoring, Phase C LCLOSE reconciliation (EXPECTED/DEGRADED/MISMATCH),
Phase D registration, plus the pre-declared cert-scheduler interaction.
Writing it caught a critical latent defect: the LOPEN parser contract
required 15 fields while the EA v1.16 writer emits 14 — the first real fill
would have been invisible to [3b] AND to the watchdog's open-position gate
(a terminal restart would have been permitted over real money), and the
parity harness's flat gate had no live-grammar awareness at all (a cert
session could have stopped the terminal over an open live trade). All three
consumers aligned to the writer-exact shape and the test fixtures now parse
the MQ5 format strings themselves. As of registration, the LV ledger
carries zero LOPEN rows.

## Addendum (2026-09-18, morning after)

| item | state |
|---|---|
| WF shadow certification (v1.15) | PASS 06:44 UTC local — python 151/+1.474R vs EA 151/+1.478R, max\|dR\| 0.0005 (`midas_parity_result_20260918_0544.json`); register §2 baseline = CERTIFIED |
| OOS 8-mode matrix (v1.15 shadow) | 8/8 PASS 06:41–06:45 UTC, four artifacts (`midas_parity_matrix_oos_20260918_064{1,2,4,5}.json`) |
| R6 executed in-tree | v1.16: INIT_FAILED on InpUseNewsFilter=true + non-gold symbol; harness preconditions mirrored; compile 0/0; shadow refreshed (`\7132193d…`); deployed untouched (`\22f39ae0…`) |
| Offset state audit chain | raw reading (value/source/epoch/dir) persisted per absorbed baseline; `last_change` both-legs record; journal-retention guard in [3b] (>90 min ledger-leads-log ⇒ REWRITTEN alert; missing log ⇒ MISSING alert) |
| §1 version-awareness | watchdog banner_drift + parity keyed compare pinned version-blind (behavioral + AST no-consumer pins, mutation-verified) |
| Operational | stale `MidasWatchdog` scheduled task deleted (foreign repo path, minute trigger); `compile_log.txt` scratch removed; telemetry consumer enumerate found ab_adjudicate + adjudicate_arm_c (all readers pass appended grammar) |
| v1.16 finalization | R6 guards moved BEFORE the init banner; "(calendar pending)" label dropped; compile contract toolized as `scripts/compile_midas.py` (explicit /log, 0/0 + .ex5 verified; encodes the discovered MetaEditor rule: sources outside the terminal MQL5 tree silently no-op); recompiled clean, shadow refreshed (`\a4bf5e30…`), deployed untouched; R6 pins 9 (`tests/test_midas_r6_preconditions.py`); one line-merge corruption introduced during editing was caught by the occurrence pins pre-compile and repaired |
| Reading blocker resolved | first live `midas_verdict.py` dry-run aborted all four windows on "missing from chart: InpMaxRiskPct" (repo pins v1.14 vs arms v1.10) — `preset_identity` deferral tolerance shipped (deferred newer-build pins = evidence, never drift; unknown pins still abort; parse problems never deferrable; tests both directions). All four arms read CONTINUE-UNPROVEN, abort=False. **2026-10-01 reading unblocked**; runbook pre-registered at `docs/MIDASTOUCH_READING_20261001.md` |
| v1.16 certification | pending flatness — M1m took the portfolio's first live M30 paper fill 06:15 UTC (720-min timeout ~18:15 UTC); the WF cert runs the moment the gate opens; until then the certified-pending status is recorded in register §2, and NOTHING deploys before the 2026-10-01 reading regardless |
| Watchdog suite root-cause fix | the 8 cross-suite test failures were NOT watchdog code: `test_midas_watchdog` stamped fixture mtimes with `time.time()` at test runtime but fed `decide()` a NOW captured at import — in a 131-suite session the ~60 s of garch calibration ahead of it slid a 45-min fixture into the 44-min grace band (RESTUP → phantom WAIT). Fixture stamps now anchor to the same module NOW that `decide()` receives; bisected via 5 halvings to the exact polluter; full tree re-run **1703 passed, 15 skipped** (was 8 failed / 1695) |

## Addendum (3) — v1.10 HUD, same day (display-only, certified chain, engine re-certified)

After the closeout was written, the EA gained the at-a-glance HUD the old
V75 chart had — through the full certified chain: compile (0 errors/0
warnings) → watchdog pause → flat-check → PID-exact stop → v1.10 binary
deployed to both Experts paths → §13 fresh-ledger abort (pre-v1.10 ledger
archived) → byte-exact re-splice (30 inputs, backup kept) → relaunch →
boot banner `[MIDAS1.10]` verified pin-for-pin → engine re-certified
(`midas_parity_result_20260917_1435.json`: WF, 151/151 keyed trades, max
|dR| = 0.0005R, first-run PASS — the HUD is behavior-neutral by
measurement). The HUD shows mode/name, session, virtual equity, trades
n/30 gate clock, wins, cumR, and the last engine action; it draws nothing
in the tester and reads only ledger-backed state, pinned by 11 offline
source tests (`tests/test_midas_hud.py`; the version-consistency test also
fixes the stale `#property version`, which had said 1.05 since v1.06).
Discipline notes: per §13 this binary change is a pre-fill structural
abort — the gate clock restarted on the fresh ledger (at 0 closed trades,
cost: none); the compile tooling builds in place so no v1.09 copy
survives, and v1.09's rollback verifier remains the parity harness.
Standing count after the addendum: 77 tests green, watchdog healthy,
arm flat at veq 50.00.

## What comes next

1. **Operator routine**: after any reboot, launch `start_midas_watchdog.bat`;
   run `python scripts/morning_status.py` each morning — [3b] is the health
   line (preset OK / veq / flat / closed count / watchdog state).
2. **First fill watch**: verify the first paper fills land on the ledger and
   read sane (floor-table risk ≈$5.87/trade at the $50 book is expected and
   disclosed).
3. **2026-10-01**: first monthly §13 reading (CONTINUE-UNPROVEN is the
   certain verdict at n≈0 — that is the rule working, not failing).
4. The verdict computation is currently manual; automating it
   (`midas_verdict.py`) is registered as the next small tool — thresholds
   already frozen, so the tool can never redefine them.
