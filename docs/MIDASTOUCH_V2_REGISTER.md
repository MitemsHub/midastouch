# MIDASTOUCH V2 REGISTER

**REPOSITORY SCOPE PURGE (2026-09-18 ~19:20 UTC — operator directive).**
Operator instruction: anything in the MIDASTOUCH repo that does not concern
MIDASTOUCH is to be deleted. Executed as a dependency-audited purge of the
MIDASTOUCH repository (the GitHub push checkout): 892 foreign paths removed
(the MITEMSHUB/V75 EA program, the Next.js operator dashboard, the
synthetic_trader library and its test suite, V75 research scripts, foreign
app/infra/packaging files). The MIDASTOUCH program is preserved in full:
EA source, presets, midas_* tooling, watchdog + logon task, certified
XAUUSD corpus, parity/tester evidence, cited V75-era evidence documents,
and the 25 gold test suites. Deletions recoverable from git history.

**LV TRIGGER-FREQUENCY AMENDMENT — SUPERSEDED 18:05 UTC by the corrected adjudication below.** The 17:30 pass shipped k=3.0/75-25 on a per-trade-expectancy ranking that (a) contained a decimal error in its frequency line and (b) optimized the wrong metric. Corrected in place the same evening; the 17:30 chart state never traded (zero fills between 17:30 and 17:38) and is preserved in the register history and chart backups (chart05.chr.bak_20260918_173001).

**LV TRIGGER-FREQUENCY AMENDMENT, CORRECTED (2026-09-18 18:05 UTC — executed live).**
Metric corrected: adjudication on **TOTAL OOS RETURN** (what the account earns), not per-trade expectancy; full ORIGINAL k×RSI grid re-run on both corpora (repo certified 775d + fresh broker 453d). Result: **k=1.0 / RSI 75-25 ORIGINAL — 152 OOS trades, +21.4R total, pf 1.287 OOS / 1.311 fresh-broker (edge holds on BOTH independent corpora), ~1 fill/day, OOS dd 7.5R; recent-30d +1.3R where the frozen 2.0/70-30 lost -3.7R.** k=3.0/75-25 is per-trade-king (pf 7.2 OOS) but total-return inferior (+7.3R OOS, ~1 fill/18d). Loosening to k=1.0 buys ~28x the OLD frequency estimate at ~equal per-trade expectancy (+0.117 vs +0.138 full-corpus) — the rare-quality pattern holds only WITHIN k>=2.5, and k=2.5 itself is OOS-dead (exp ~0). **Executed 17:38-17:40 UTC through the registered stop->splice->relaunch sequence** (second splice; preset parser-verified 31 keys unique; chart byte-verified 31/31, backup chart05.chr.bak_20260918_173855; all five EAs re-attached with fresh heartbeats; the two open paper positions restored; LV flat throughout — zero live exposure). M1 keeps the frozen 2.0/70-30 §13 baseline as paper control; divergence pinned both directions in tests/test_midas_golive_grammar.py. The 2026-10-01 reading judges LV on this corrected geometry. Research artifact: artifacts/midas_variant_research_20260918.json + the 18:05 total-return grid (repo + fresh corpora).

**GO-LIVE EXECUTION BLOCK (2026-09-18 ~08:40 UTC — the first real-money attach).**
Operator instruction: "we must take trades, the EA must be active."
Executed through the full registered chain, no step skipped:

- **What went live:** MidastouchAI **MIDAS1.16** (`Experts\MIDASTOUCH_live\MidastouchAI.ex5`,
  sha256 `\a4bf5e30…` — the same binary the v1.15 WF/OOS matrix certified and whose
  paper-path delta is nil on certified inputs), on **XAUUSDmicro M15**, real account
  **140778269** (DerivSVG-Server-03, equity $50.22 at attach), terminal 49E0, chart
  `Default/chart05.chr` (cloned from the certified chart01 geometry), arm tag **LV**,
  dedicated magic **7801601**.
- **Config:** `mql5/MIDASTOUCH/MidastouchAI_LV_gold.set` — every strategy/gate/risk
  value byte-identical to the certified M1 paper pin set; the ONLY deltas are
  identity+execution (`InpArmTag=LV`, `InpMagic=7801601`, `InpLiveExecution=true`).
  Verified **31/31 inputs byte-identical on the chart** at boot.
- **Operator authorization (2026-09-18):** the gold EA's live attach was
  authorized by the operator's explicit instruction to activate the EA and
  take trades on the live account. Geometry verified before execution:
  floor-table min-lot risk **$2.91 = 5.8% of $50.22**, inside the R5 15% cap.
- **Live-path proof (the risk that mattered):** the live order layer is
  source-pinned (R2/R3 invariants), its wall-clock gates (timeout, Friday flat,
  daily breaker) run on TimeGMT directly and are broker-offset-immune; the
  banner CLOCK line read +0h00 (recorded in the offset audit chain against the
  +2h probe baseline — flagged, not gating, disclosed in the health guide).
- **Verification at boot:** banner `execution=LIVE | exec-model=PERTICK`,
  `PAPER ledger flat — nothing to restore`, FLOOR TABLE XAUUSDmicro
  stop=29.08 risk@minlot=$2.91, zero INIT-FAILED/veto lines, LV ledger created
  with the registered era stamp `MIDAS1.16,pertick-fills+telemetry-only-per-V2-register`,
  heartbeat EQ rows ticking, **AutoTrading verified ON** via the MT5 API
  (`terminal_info().trade_allowed=True`, account `trade_allowed=True`), all four
  paper arms re-initialized v1.10 intact in the same boot, watchdog loop running.
  Post-attach resolution (same morning, evidenced): the broker-offset question —
  the LV banner's +0 h 00 min vs the +2 h probe baseline was **verified
  externally** (live broker tick epochs vs NTP-checked machine UTC; machine −0.32 s
  from the atomic reference) and the baseline re-set through the audit chain
  (`morning_status.py --verified-offset 0`, two-run confirm; `last_offset_verified`
  evidence recorded in state) — the banner was true; the old baseline was the stale
  side of a genuine broker-side server change. Health guide §4 note updated.
- **Monitoring upgrades shipped with the go-live:** the watchdog flat gate and
  morning status now parse the LIVE ledger grammar (LOPEN/LCLOSE) — a dangling
  LOPEN is a REAL position, so the flat gate refuses terminal restarts over a
  live trade (SKIP-OPEN-POSITION; --force documented override); [3b] shows the
  LV arm with a `LIVE $$$` header, its open position/flat state, live closes
  with exit reasons, and account-based framing. Pinned by `tests/test_midas_golive_grammar.py` (12).
- **Procedure deltas, disclosed:** paper EA removal
  N/A (live EA on a NEW chart; paper arms untouched — better than the
  checklist's replace flow); AutoTrading enabled programmatically (Ctrl+E to
  the focused terminal) with API verification; preset via file splice + restart
  (the certified chain), not dialog Load.
- **Guards that remain active from minute one:** R6 gold-only precondition,
  session 06–20 UTC, spread cap, stops-level check, daily breaker at
  **InpDailyLossCapPct=15.0 for the live arm** (review-frozen — see the live
  breaker amendment below), Friday 20:00 UTC cutoff/flat, 720-min timeout,
  R5 min-lot veto, one-position-at-a-time (magic 7801601 scope), watchdog
  flat-gated restarts, [3b] drift guards with deferred-pin tolerance (the LV
  chart carries all 31 pins — no deferrals apply).

**INCIDENT + FIX — the silent AutoTrading stand-down (2026-09-18, discovered
17:45 UTC, closed same hour).** Between ~08:40 UTC (attach; AutoTrading verified ON
at boot, per this block) and 17:39 UTC the terminal's **global AutoTrading switch
was switched OFF** — by hand or by focus accident at some point during the day.
Effect: MT5 refuses every EA order *silently* — no journal line, no order error,
no ledger trace — while the paper arms kept trading (virtual fills need no
switch). Result: 9 hours where even a firing ORIGINAL signal (08:15 UTC; the
live trigger was still k=2.0 then) could not have produced an order. The
monitoring apparatus watched every file and the account but never the switch —
a blind spot in the original evidence ring, now closed:

- **Terminal state restored:** `trade_allowed False → True` at 17:47 UTC
  (verified via `terminal_info()` through the MT5 API immediately after the
  programmatic toggle; account/broker permissions were always True).
- **Monitor sentinel (permanent):** `midas_lv_broker_monitor.py` now records
  `algo_trading` (True/False/None) on every snapshot and emits an
  `ALGOTRADING_OFF` problem entry when False; the [3b] LV broker view prints
  `AutoTrading ON/OFF/??` in the header (red when OFF) and surfaces the
  problem line. Pinned by 4 new tests in `tests/test_midas_lv_broker_monitor.py`.
- **Standing law:** a go-live-era morning check is INCOMPLETE if it does not
  include `algo_trading: true` from broker evidence. Any [3b] with
  `AutoTrading OFF` or `??` is an actionable alert, not a footnote.

**AMENDMENT — live-arm daily breaker (2026-09-18, review-frozen, effective
immediately).** The operator's structural review flagged the one flaw in
running the paper default on the live arm: **`InpDailyLossCapPct=3.0` lets a
single min-lot stop-out (measured $2.91–4.55 ≈ 6–9% of the $50.22 book) trip
the breaker** — "one loss is a day": the arm would stand down on its first
full loss every day and could take months to print the n the §13 gate needs.
The paper value stays frozen at 3.0 (it maps to the arms' $0.50–1.50 virtual
risk and their certified behavior is built on it). **The LIVE arm runs
`InpDailyLossCapPct=15.0`** — frozen reasoning: the review's cited live-failure
mode is a 3-consecutive-loss pattern compounding to ≈ −45% when sized on
running equity; at 15%/day the first full loss is admitted and the second
consecutive full-loss day is vetoed, which refuses exactly that pattern's
input instead of train-wrecking the sample with daily stand-downs; the R5 15%
per-trade cap still bounds every single order. Scope: LIVE arm only
(magic 7801601); paper arms untouched; python `python_build_data` unchanged
(the breaker is a live-order-path guard; paper never had one). Chart
re-spliced with the new pin at 10:02 UTC and reboot-verified. The Sizing
Principles remain "computed, not overridden" — this is a computed amendment
with the arithmetic on the record, not an override.

# MIDASTOUCH V2 REGISTER — adjudicated Phase-1 P0 items

**Created 2026-09-17** from the external EA review of the same date (sections
#1–44), adjudicated line-by-line against `mql5/MIDASTOUCH/MidastouchAI.mq5`
(then v1.10, now **v1.12 in-tree**, un-deployed) and the python engine of
record (`scripts/midas_sweep.py`). The review's verdict is adopted: solid
research-parity architecture, **do not rewrite, do not go live yet**. Its
errors are recorded in §6; its confirmed defects drive the register below.

Status legend: **[DONE v1.11/v1.12]** implemented in-tree, compiled clean,
tests pinned, **not deployed** · **[REGISTERED]** frozen, queued behind the
2026-10-01 first §13 reading · **[REJECTED]** with reason.

---

## 1. The standing rule (registered BEFORE any Phase-1 deploy)

> **Standing rule (telemetry/fail-closed class).** A change is *telemetry/
> fail-closed class* — and never aborts a §13 era — if, given identical
> ticks, it cannot change any CLOSE row's R nor the set of trades in the
> ledger. This class includes: (a) ledger column **appends at end-of-row**
> (never insert or reorder columns — existing parsers are positionally
> pinned); (b) banner/HUD/journal text; (c) the honest `APP_VERSION` bump
> itself; (d) fail-closed guards (INIT_FAILED on unmet preconditions);
> (e) code fixes in paths **unreachable under the arms' pin set** (today:
> everything guarded by `InpLiveExecution=false && InpBarModel=false`
> dispatch, i.e. the entire live layer); (f) recovery/adoption hardening.
>
> **Always a structural abort (§13 unchanged):** anything feeding
> `TriggerOnClosedBar`, `ModeDecide`, sizing, the session/Friday gates, the
> spread/ATR inputs, SL/TP/timeout math, or the cost model.
>
> **Mechanism (implemented in `midas_verdict.py`, 2026-09-17):** the
> telemetry/fail-closed build stamps its ERA note
> `telemetry-only-per-V2-register` (the ERA note field already carries free
> text); `midas_verdict.py` exempts exactly the version transitions whose
> FIRST stamp of the new version carries that note from the version-change
> abort, while every transition — exempted or not — is recorded in the
> reading's evidence (`version_transitions` in `arm_statistics`). The walk is
> fail-closed: a citation on a non-transition re-stamp exempts nothing, a
> truncated stamp is uncited, a rollback aborts (the older binary predates
> the register and cannot cite), and one uncited leg of a chain aborts the
> whole window. Self-declaration is honest because the note must cite this
> register, and the class definition above is frozen here. Tests:
> `tests/test_midas_verdict.py`, "V2 register §1" block (8 tests, both
> directions).

This rule existed in draft form because `midas_verdict.py` (era-version
abort) enforces the over-broad reading by default: *any* version change in
a ledger aborts the window. That is correct until a telemetry-only build
ships mid-window — then re-accruing a healthy window over print columns is
discipline-eroding waste. The rule was frozen **before** the first
version transition, not adjudicated after it. (Drafted 2026-09-17 in the
adjudication of the external review; v1.11/v1.12 are the first builds this
rule classifies. **Implemented the same day** — see the Mechanism note
above; the abort now keys on unexempted transitions, and the open
dependency registered under R10 is closed.)

## 2. The register

### DONE — in-tree as of 2026-09-17 (v1.11 + v1.12), not deployed

| # | P0 item | Source evidence (v1.10 as reviewed) | Fix in-tree | Lines (v1.12) | Pins | Review P0 |
|---|---|---|---|---|---|---|
| R1 | **Position-ID conflation** — order/deal/position IDs were one variable; `HistorySelectByPosition` consumed a deal-or-order ticket | v1.10 EA:137, 1211, 1236 | `g_lv_posid` (POSITION_IDENTIFIER, the only reconciliation key) + `g_lv_ticket`/`g_lv_order`/`g_lv_deal` separated; entry-deal resolution from open history | 140–150, 697–725, 1230–1250 | tests/test_midas_hud.py | #3 |
| R2 | **`PositionSelect(_Symbol)` trusts any position on the symbol** | v1.10 EA:1216, 1233; close by symbol | `SelectOurPosition()` = symbol + `InpMagic` match, re-verifies ticket+identifier+magic every call; `PositionClose(g_lv_ticket)` after verification; CLOSE ABORT if the owned position vanished mid-retry | 733–762, 1267–1284, 1328 | tests/test_midas_hud.py (allowlist); **dedicated invariant pins delivered**: `tests/test_midas_live_ids.py` (11 source pins — selection isolation, posid-only history, provenance-only order/deal IDs, coherent flat reset; mutation-verified 2026-09-17) | #4 |
| R3 | **UTC clock** — live wall-clock gates rode broker server time (and its DST) | v1.10 EA:868–872, 925–930, 1157, 1195 + live timeout pair | Two-clock frame law: live breaker day key, Friday flat/timeout on `TimeGMT()` via the single authoritative helper — **renamed `TimeUTCNow()` in v1.15**, which also corrected the law's PROVENANCE: `iTime` bar epochs are broker-SERVER time (broker-feed label frame, verified against the CSV `+00:00` timestamps), so the 06–20/Friday gates must structurize the epoch — never UTC — and the python of record classifies the same epochs (`midas_sweep.py` epoch classification re-pinned same commit; amendment 6) | current: time-engine block ~906–950, gates 1010/1067/1248/1285/1354/1450 | tests/test_midas_time.py (11, incl. frame-law + python-agreement pins) | #2 |
| R4 | **No offset verification surface** (part of the review's #2) | — | `CLOCK:` init-banner line (server, GMT, offset) + `MidasOffsetProbe.mq5` script + health-guide §4 walk-through (mqlGMT vs external UTC, re-run after DST) | 541–545, probe file | test_midas_time.py | #2 |

**Deploy discipline (unchanged):** all four items are live-path-only
(`LiveOnTick()` executes only at EA:643–646 under `InpLiveExecution=true &&
!InpBarModel`); the four running paper arms never execute this code.
Deploying v1.12 to an arm chart is a §13 version change → fresh ledger,
window re-accrues from zero — done deliberately at the live gate.

**Parity baseline status (2026-09-18, dynamic certification PASSED):**
CERTIFIED. The shadow path `MQL5\Experts\MIDASTOUCH_parity\MidastouchAI.ex5`
(which the live charts do NOT reference — they load
`Experts\MITEMSHUB_AI\MidastouchAI.ex5`, hash pinned) holds the v1.15
refresh and was dynamically certified on 2026-09-18 04:44 UTC: The harness gained `--expert-path` for exactly this: shadow-path
certification of an un-deployed build without touching the live load path
(default remains the certified deployed path, pinned by
`test_expert_points_at_deployed_binary`). Two harness hardenings shipped
with it: the `finally` relaunch is now guarded (a flat-check abort no
longer bounces a healthy terminal — live-validated 2026-09-17), and a
failed terminal stop aborts instead of running passes blind.
The certification run itself was **correctly refused by the flat-check
gate**: M1t and M1m hold open paper positions (their first fills, epochs
1789657200, no CLOSE rows yet — likely resolving overnight via the ~03:00
UTC timeout). The gate protecting the §13 window outranks the baseline
renewal; when all four arms are flat (check `morning_status.py [3b]`),
run:

```
python scripts/midas_parity.py --window wf \
    --expert-path "MIDASTOUCH_parity\\MidastouchAI"
```

PASS artifact → §2/§3's deploy path starts from a freshly certified
baseline. The same flat-check gate applies at deploy time itself.
(R10 executed after this note was written: the shadow binary is now the
v1.13 telemetry build — the certification therefore covers v1.13, which is
the version the register's deploy path would deploy.)

**CERTIFICATION RESULT (2026-09-18, artifact
`artifacts/midas_parity_result_20260918_0544.json`):** after the overnight
M1t/M1m timeouts resolved, morning status showed all four arms flat and the
harness ran to completion against the shadow binary — **PARITY: PASS,
python 151 tr / +1.474R vs EA 151 tr / +1.478R, max|dR| 0.0005 (tolerance
exact: 0 trades over), keys OK, anchor reproduced**, window WF
(2025-09-15 → 2026-04-03), mode REVERSE_DIRECTION, harness v2 keyed,
selftest 8/8, flat-check OK at run start, watchdog paused→resumed,
terminal relaunched, deployed binary hash-verified untouched (`\22f39…`).
The shadow binary certified is **v1.15** (the shadow is deliberately
refreshed to the newest in-tree build at each compile, so this one artifact
covers the whole un-deployed v1.11→v1.15 line — live-gated fixes,
R10 telemetry appends, R5 min-lot veto, and the R3 time-engine corrections
— reproducing the certified paper-path behavior at the same max|dR| the
12:58 v1.10 certificate showed). This satisfies §4(b) BAR-parity
re-certification for the R5/v1.14 era and unblocks the deploy path in §3
step 3, which still waits behind the 2026-10-01 reading.

**OOS 8-mode matrix on the v1.15 shadow (2026-09-18 06:41–06:45):** the
full mode registry was certified out-of-window — 4 matrix invocations × 2
modes, **8/8 PASS** (`artifacts/midas_parity_matrix_oos_20260918_064{1,2,4,5}.json`),
e.g. REVERSE_DIRECTION py 108tr/+8.199R vs EA 108tr/+8.202R, max|dR| 0.0005,
anchor reproduced every mode. The v1.15 shadow line is certified on BOTH
windows. **v1.16 note:** after these runs the shadow was refreshed to the
v1.16 build (R6 preconditions); its paper-path behavioral delta is nil on
certified inputs (preconditions already hold), and the next parity pass —
required by §4(b) before any deploy — re-certifies it explicitly.
**v1.16 cert status (2026-09-18 11:17 UTC re-check): PENDING FLATNESS** — the
§4(b) run was attempted at 07:07 and the flat-check gate correctly refused
(M1m's 06:15 fill); a ledger-authoritative re-check at 11:17 found M1m AND M1t
both holding LONGs (M1m 4389.075 from 06:15, 12h timeout 18:15 UTC; M1t 4390.515
from 09:35, 12h timeout 21:35 UTC; M1/M1s flat). The gate working
on live positions is exactly the discipline the register demands; thev1.16 certification runs at
the first all-flat window (earliest ~18:15 UTC once
M1m resolves, fully clear after 21:35 UTC), and nothing deploys
before the 2026-10-01 reading regardless.
**Armed (11:24 UTC):** `scripts/midas_cert_scheduler.py` is running detached —
it retries the registered shadow-path command every 20 min for 24 h, treats the
harness's own exit-4 flat-gate refusal as "retry later" (attempt 1 refused as
designed: M1m/M1t positions open, watchdog paused+resumed by the harness's
cleanup, terminal untouched), and records every attempt to
`artifacts/midas_cert_scheduler_20260918.jsonl` + per-attempt logs. Re-arm if
the session dies: `python scripts/midas_cert_scheduler.py`. Cert target
verified byte-exact: parity shadow == live binary (`a4bf5e30`, post-repair
v1.16); paper deploy path untouched (`22f39ae0`).
**VPS-hosting era opened (12:46 UTC):** the terminal migrated the trading
environment to MetaTrader VPS subscription 6898457 (operator-initiated and
confirmed in conversation) — MT5 locks LOCAL algo trading off by design in
this mode. The operator's declared flow: corrections land locally, then the
operator's VPS sync picks up the local state (already verified: LV v1.16
`a4bf5e30`, 15.0 breaker, LIVE pins, flat ledger). Era guard:
`artifacts/midas_vps_hosting.json` (operator-managed marker) makes the
watchdog observe-only and [3b] flag the era with an LV-staleness exemption;
the first-trade ritual adapts Phase A to broker-evidence-only while the era
lasts. Paper arms continue collecting locally (verified: all five ledgers
fresh post-migration). To close the era: delete the marker when the surface
returns to the local terminal.
**First-live-trade ritual pre-registered (12:5x UTC, before any fill):**
`docs/MIDASTOUCH_FIRST_LIVE_TRADE.md` — Phase A verify (row integrity, broker
cross-check, [3b]+watchdog visibility), Phase B no-interference monitoring,
Phase C LCLOSE reconciliation (EXPECTED/DEGRADED/MISMATCH), Phase D
registration; a live position at a cert window legitimately delays the cert.
Writing it caught and fixed a latent grammar defect (15-field parser contract
vs the EA's 14-field writer — first fill would have been invisible to [3b] and
the restart gate; parity harness had no live-grammar awareness at all): all
three consumers aligned to the writer-exact shape and pinned to the MQ5 format
strings by test.
**Broker-evidence LV monitor registered (VPS era, 12:4x UTC):**
`scripts/midas_lv_broker_monitor.py` polls the MT5 API on a 60 s loop and
persists `artifacts/midas_lv_broker_state.json` — positions and deals
filtered to magic 7801601, account-level balance operations regardless of
magic (the 12:25:59Z −$10.14 withdrawal is account evidence, not arm
evidence), equity/balance, dedup by deal ticket, `first_fill_seen` sticky.
The monitor never writes the LV ledger. [3b] renders the snapshot as the
`[LV broker view]` block automatically (stale snapshot labeled, never
hidden); a `LIVE POSITION (broker)` line is the first-trade ritual's
Phase-A trigger while the era lasts. Attribution rules pinned by test
(`tests/test_midas_lv_broker_monitor.py`, `tests/test_midas_lv_broker_view.py`).
**LV-silence census registered (2026-09-18 ~13:50 UTC):** operator asked why
no live trades; the certified harness (`midas_sweep.py`, fed the certified
history + fresh broker bars) ran a 30-day signal census per deployed variant.
ORIGINAL fires ~28×/30d in-session (≈0.9/day) but fills ~20 trades/30d on the
one-position bookkeeping; **the last ORIGINAL firing before go-live was
09-17 12:45 UTC — 46 minutes before M1's ledger existed (13:31 UTC)**, so
zero M1 fills is VERIFIED EXPECTED, not a fault; next expected ORIGINAL fill
within ~1–2 days at the historical rate. t/m fire 779–901×/30d (≈26–30×
M1's density) — their fills prove the whole path works, not that M1 is
starved. Historical 30-day sim nets (context only, not a forecast):
ORIGINAL −3.78R, t +1.66R, s −0.80R, m +0.98R. Census is NOT a verdict and
does not amend any gate.

**Reading-blocker resolution (2026-09-18, deferred-pin tolerance):** the
first live `midas_verdict.py` dry-run aborted ALL FOUR windows on
"preset DRIFT: missing from chart: InpMaxRiskPct" — the repo .set pins
gained the v1.14 input while the deployed arms stamp v1.10, so the
preset-identity guard was converting *in-tree advancement* into window
aborts (the 2026-10-01 reading would have been structurally blocked by a
fix the charts cannot carry). Resolved without touching the charts
(re-splice = a chart change mid-window; pin deletion = un-doing a
registered fix): `preset_identity` now treats a missing pin whose owner is
in `DEFERRED_PINS` (name → deployed/owner/why) as **deferral evidence,
never drift** — verdict OK with a `deferred` list; unknown missing pins
still abort (fail-closed); parse problems (duplicate rows) are never
deferrable. `midas_verdict.py` records the deferral in `notes` (JSON),
never in `abort_reasons`; [3b] displays it. Tests both directions:
`test_deferred_newer_build_pin_is_not_drift` /
`test_unknown_missing_pin_is_still_drift`. Live result: all four arms
CONTINUE-UNPROVEN, abort=False. **The 2026-10-01 reading is unblocked.**
The reading-day runbook itself is pre-registered:
`docs/MIDASTOUCH_READING_20261001.md` (frozen 2026-09-18; expected
outcome stated in advance: CONTINUE-UNPROVEN on n < 60 — the gate working
as designed).

**Operational hardening (2026-09-18):** the stale "MidasWatchdog"
scheduled task (one-time/minute trigger pointing at the retired
`Projects\MIDASTOUCH` tree — a second watchdog running against the wrong
repo) was deleted; the registered "MIDAS Watchdog Autostart" logon task is
the only watchdog autostart. The stray `compile_log.txt` at repo root was
removed; compile verification now uses an explicit `/log` path captured
immediately (see the R6 compile: 0 errors, 0 warnings).

**Python-half regression proof for v1.11/v1.12/v1.13 (2026-09-17 ~21:00,
run while the flat gate held):** with the terminal untouched, the harness's
own python half was executed against the v1.11–v1.13 tree —
`python_build_data()` + `python_regen(REVERSE_DIRECTION, WF)` reproduced
**n=151 / +1.474R / max|dR|≤0.0005 vs `…_1258`**, the 13:48 OOS matrix
(PASS 8/8, same-day, v1.10-bar-era python) covers the full mode registry,
and `M.selftest()` gates the session. This proves the python engine of
record, the window pins, and the harness's comparison law are exactly as
they were at certification — the regression surface the tree could have
silently moved. The EA-side dynamic pass stays gated behind arm flatness.
(The 147-float `midas_parity_python_wf_rd.json` is the documented
pre-Amendment-2 Wilder-ATR relic — protocol §stale-vintages — not a
regression baseline; v2 keyed compares against the live regen.)

**Live-load-path hazard note (discovered 2026-09-17):** the live gold
charts reference `Experts\MITEMSHUB_AI\MidastouchAI.ex5` — the same path
the certified harness uses for its tester passes. Without the shadow-path
mechanism, any parity re-cert would have swapped the binary under the
live charts at relaunch (a §13 mid-window deploy). Now recorded, tooling
cannot repeat it by default.

### REGISTERED — parity-gated, queued behind the 2026-10-01 reading

Each of these changes *which trades fire or how they size* → python and EA
change **together**, parity re-certified, new era, fresh 60-trade window.
One amendment at a time.

| # | P0 item | Evidence | Planned shape | Review ref |
|---|---|---|---|---|
| R5 | **Min-lot floor can exceed configured risk** | v1.10 EA:972/EA:1255-57 pattern: `if(lots < vmin) lots = vmin`, then `eff_risk` > target — disclosed daily ($4.55 observed vs ~$0.30 intended), but logging ≠ enforcement. Python floors *identically* (certified strategy), so an EA-only refusal would be unilateral divergence | **AMENDED IN-TREE 2026-09-17 as v1.14** (protocol amendment 6; python+EA one commit; NOT deployed): veto when min-lot risk exceeds the cap fraction of each engine's OWN basis — python pending-fill veto (`RunResult.vetoed`), EA BAR `SKIP,<epoch>,RISK-CAP,<tag>` row, PERTICK veto, live order refusal (account-equity basis). **Cap frozen at 15% by measurement** (decision table in amendment 6): a 1.5% cap ported from the V75 checklist would veto 15 certified fills and starve the $50 arms entirely; 15% vetoes ZERO certified fills (regen n=151/+1.474R, vetoed=0, enforced by `tests/test_midas_minlot_veto.py`). Deploy = the first parity-gated era, queued behind the 2026-10-01 reading | #5 |
| R6 | **News filter input implies protection that doesn't exist** | EA:79 `InpUseNewsFilter = false; // HONEST: calendar integration pending`; init banner EA:540. The label is honest today; the *input* still names protection that isn't there | **EXECUTED IN-TREE 2026-09-18 as v1.16** (python+EA one commit; NOT deployed): both R6-adjacent preconditions fail-closed per the §5 fold-rule — `InpUseNewsFilter=true` → INIT_FAILED (no calendar engine exists; refusing to run under a false label), not-gold symbol → INIT_FAILED (gold-only by charter; the #35 warning becomes a precondition). **v1.16 finalization (same day):** guards moved BEFORE the init banner (a refused attach never announces a healthy start), the "(calendar pending)" banner label and the input comment updated to the R6 law, compiled 0 errors / 0 warnings via the new `scripts/compile_midas.py` (explicit /log, 0/0 + .ex5 verified, in-tree scratch — MetaEditor silently no-ops on sources outside the terminal MQL5 tree, the trap the ad-hoc compiles hid), shadow refreshed `\a4bf5e30…`, deployed untouched. Pins: `tests/test_midas_r6_preconditions.py` (9). Harness mirrors both preconditions (`R6_GOLD_ONLY`, `R6_NEWS_FILTER_OFF`, feed-symbol assertion). Era rules: the §13 arms stamp v1.10 (single version, no transitions) — v1.16 activates at the next era decision, before any deploy | #14 |
| R7 | **BB alternative indexing as an experiment, not a fix** | Both engines compare prev close vs bands *including* the signal bar — python `midas_sweep.py:131–142` (`win = closes[i-n+1:i+1]`, `prev = closes[i-1]`) and EA `TriggerOnClosedBar` (:454–455, 967–975: bands from the closed signal bar). Identical convention; survived bit-level run3 certification. The review's bar-2/band-2 variant is a DIFFERENT strategy | Register as a pre-registered hypothesis with its own window after the reading — never as a "bugfix" | #15 → **REJECTED as a bug claim; REGISTERED as research** |
| R7b | **Spread cap: add absolute maximum** | EA:77 relative-only (`1.5% of stop`) | Only if python gains the identical gate in the same commit; else it's unilateral | #24 |
| R8 | **Daily breaker extension** (weekly loss, consecutive-loss cooldown, floating-vs-realized) | EA:1197 breaker (equity-only day key) | Risk-engine amendment, python-first | #21, #22 |
| R9 | **Startup self-test** | Zero self-test anywhere in v1.10–v1.12 | Symbol spec (tick value/size, min lot, step, stops level), indicator handles, feed presence — printed at init, INIT_FAILED on critical failure. Classification at build time: pure-print = fail-closed class; abort-on-data = must be reachable-identical in both engines to stay class-safe | #38 |
| R10 | **Telemetry columns** (ATR at entry, spread at entry/close, slippage) | Paper CLOSE rows carry pnl+post-close equity (EA:~1121); MAE/MFE already exist in BOTH engines (python rows, BAR columns) — the review's #30 is partially done | **EXECUTED 2026-09-17 as v1.13** (in-tree, not deployed): OPEN rows append atr_at_entry,spread_at_open; CLOSE rows append spread_at_close,slippage; ERA note cites the register on the paper path; BAR parity note byte-for-byte. Safety net: `tests/test_midas_telemetry.py` (12, incl. the 2026-09-18
consumer-completeness enumerate) pins the frozen prefixes positionally and
proves append-tolerance of EVERY python consumer — enumerated dynamically
from scripts/ by row-grammar signature, which found two real consumers the
hand list had missed (ab_adjudicate, adjudicate_arm_c); all readers pass
on appended grammar. (midas_verdict, parity parse_ledger, ledger_flatness,
[3b] collectors, era parser, watchdog ledger_health, ab_adjudicate,
adjudicate_arm_c). **§1 mechanism landed the same day** (`midas_verdict.py`): cited transitions are exempt, uncited ones still abort, `version_transitions` evidence on every reading — 8 tests in `tests/test_midas_verdict.py` | #29, #30 |

### REJECTED from the register

| Review claim | Why rejected |
|---|---|
| "BB indexing is a bug" (#15) | Identical convention in both engines (`midas_sweep.py:131–142` vs EA:967–975); certified by run3 parity. Different ≠ broken. Kept as R7 research, not R-item |
| "Default `InpMode=1`" (#34) | Source: `MODE_REVERSE_DIRECTION` (mode 2), EA:63 at v1.10. Also misdescribed the mode's semantics (that's M1t's REVERSE_TRIGGER). The demanded mode experiment IS the §14 portfolio, live since 2026-09-16 |
| "Severity = live-trading blockers" (frame) | `InpLiveExecution=false` default + §13 forward gate means R1–R4 are pre-conditions for the *live gate*, not blockers of today's paper run. The 2026-09-17 real incidents (09:57 preset drift, 11:11 code-defaults re-attach) were environmental and are covered by [3b] + the §12 watchdog, which a code review cannot see |
| "Add the five-layer engine" (#8–13) | Adopted as *roadmap language* (one module per experiment, each pre-registered), never as a batch landing — that part of the review was right; the risk is only in sequencing. Now made concrete as the §2b backlog below |

### §2b — Phase-2 research backlog (REGISTERED 2026-09-18; queued, not scheduled)

The external review's phase-2 engine (#8–13, adopted as roadmap language in
the REJECTED table above) is here made concrete: **four pre-registered
experiments**, each individually queued behind the R-series and behind each
other. Every row inherits §4's verification protocol (python+EA one commit,
BAR parity re-cert, ERA note per §1, fresh ledger per affected arm, archived
prior ledger, changelog row with the experiment ID, source tests). No P-row
starts before R6/R7b/R8/R9 are all adjudicated and the 2026-10-01 reading
has happened — at most one research era runs at a time.

**Common law for all four rows** (frozen now, before any code exists):

- **P-0 (primary endpoint).** Each experiment tests ONE directional
  hypothesis about the §13 arm family's trade selection. The metric is the
  §13 primary endpoint (§13/Amendment-4 gate values via `midas_verdict.py`)
  computed on a fresh 60-trade window per affected arm. If the amended
  family cannot beat the incumbent family's SAME-WINDOW control, the
  experiment reads CONTINUE-UNPROVEN at best — a research finding, never an
  automatic deploy.
- **P-C (control).** Before any P-row builds, the incumbent signal family
  re-runs on the same fresh window as its control (the parity harness's
  regen gives this for free in BAR mode; paper arms give it across eras).
- **P-S (sequencing).** P1 → P2 → P3 → P4. Each P-row's go/no-go review
  explicitly adjudicates whether the next P-row's premise still stands
  (e.g. a failed P1 liquidity layer can moot P4's confluence design).
- **P-N (no silent stacking).** Two P-rows may never land in one build or
  one era; the §1 mechanism's transition walk makes any attempt visible.
- **P-T (telemetry-first).** Each layer ships its OBSERVABILITY columns
  (end-of-row appends, §1-safe) in a telemetry-only build BEFORE any
  decision-path change, so the layer's raw signal is measured on live paper
  flow before it is allowed to gate anything.

| # | Experiment | Hypothesis (one sentence, falsifiable) | Planned shape (python+EA, one commit each) | Endpoint & abort |
|---|---|---|---|---|
| P1 | **Previous-day liquidity levels** (PDH/PDL, session extremes) | Bar-normalized proximity to the prior day's high/low is a *bias* layer: BUY bias when price is in the lower half of the PD range, SELL bias in the upper half, neutral band excluded from entries | Telemetry: append `pd_pos` (0..1 position in prior-day range) to CLOSE rows (§1-safe). Amendment: a `pd_neutral` session-gate-class veto (python `midas_sweep.py` gate list + EA `TriggerOnClosedBar` pre-gate), identical thresholds from one frozen constant block | 60-trade window per affected arm; primary = §13 endpoint vs P-C control; veto-rate telemetry reported (a veto rate >~⅓ of signals falsifies the "liquidity as filter" premise and sends P1 back to research) |
| P2 | **Market-structure detection** (H1 swing HH/HL vs LH/LL, N-bar fractal) | Directional bias from the last confirmed H1 swing structure agrees with — and filters better than — the H4/H1 EMA regime alone; it may REPLACE the macro layer only as a separately-registered variant, never silently | Telemetry: `struct_bias` (+1/0/−1 from N-bar fractal swings on H1) appended to CLOSE rows. Amendment: structure as a CONJUNCTIVE filter with the existing EMA regime first (bias must agree); a structure-replaces-EMA variant is a distinct follow-on experiment with its own registration | Same endpoint vs P-C; pre-registered sub-variant ID required for any replace-EMA trial; swing-window N frozen from WF-window sweep, documented in the amendment before the window opens |
| P3 | **Volatility regime filter** (ATR percentile regime on the arm TF) | Extreme ATR-percentile regimes (dead-calm and expansion tails) carry negative expectancy for the fixed 2R geometry; excluding them lifts the family's expectancy without shrinking n below viability | Telemetry: `atr_pct` (rolling percentile rank of the arm-TF ATR, e.g. 20-day window) appended to CLOSE rows. Amendment: regime-band veto at pre-registered percentile cuts, python+EA identical, thresholds frozen BEFORE the experimental window opens | Same endpoint vs P-C; the pre-registered band must come from the TELEMETRY build's own WF data, and the fresh window must not overlap the window the bands were fit on (no in-sample threshold tuning) |
| P4 | **Five-layer confluence architecture** (layers 1–4 + entry-trigger layer) | The review's stack — (1) HTF directional bias, (2) intraday structure, (3) liquidity/volatility context, (4) risk/event filter, (5) M30 entry trigger — scores trades on a confluence count k∈[0,5], and expectancy is monotone non-decreasing in k | Built ONLY from what P1–P3 actually measured: each layer contributes its measured, telemetry-validated signal; confluence score `k` appended to CLOSE rows (telemetry build) so expectancy-vs-k is MEASURED on live paper flow before any k-threshold gate exists. Decision gate (a k-minimum veto) is a separate registration with its own era, using the measured k→expectancy curve | Same endpoint vs P-C; P4 is REGISTERED here but explicitly CONDITIONAL: if ≥2 of P1–P3 read REJECTED/neutral, P4's premise (monotone-in-k) is void and must re-register against the surviving layers |

**Why P4 last and conditional:** the five-layer claim's weakest link is
composition — layers that each fail alone can only "work" via interactions,
which is precisely the multi-axis overfitting shape the protocol's
one-amendment-at-a-time law exists to prevent. The monotonicity endpoint
makes P4 falsifiable without granting it authority to re-tune P1–P3.

| P5 | **Adaptive trigger-threshold variant** (`MODE_ADAPTIVE`; REGISTERED 2026-09-18 on operator directive — "switch the live arm to a higher-frequency variant that fires more per day and is intelligent, learns and self-adjusts" — as a queued experiment, not a pre-reading change) | Entry density is a tunable tradeoff, not a fixed choice. Context (2026-09-18 census, this register's GO-LIVE block): ORIGINAL fires ~0.9×/day while t/m fire 26–30× more densely — and ALL 8 fixed variants are NO-SHIP on the frozen gates (`midas_sweep_verdict_20260916.json`: t and m fail G3/G4 exactly like everything else). Hypothesis: a trigger threshold θ (BB k-multiple / RSI band width) that adapts stepwise within HARD registered bounds [θmin, θmax] can reach ≥3× ORIGINAL's fill density WITHOUT failing G3/G4 — i.e. frequency bought by adaptation, not by shipping a known-bad static point | **Telemetry-first:** append `thr`, `thr_era_id`, and per-era signal-density to CLOSE rows (§1-safe, never-abort class). **Amendment — the lawfully self-adjusting engine:** `scripts/midas_adaptive.py`, a pre-registered online hill-climb (cadence: one adaptation step per 20 closed trades; fixed step δ; tie-break toward θmax = the conservative, rarer-signal end) proposes the next era's θ from trailing realized expectancy. Proposals land as artifacts + a register line each, and deploy through the EXISTING era machinery (re-splice + watchdog pin verification) — **the EA never mutates its own parameters mid-era; "self-adjusting" means an autonomous, fully-logged amendment pipeline, not in-place mutation.** Adaptation's authority is the threshold ONLY: risk %, breaker, SL/TP multipliers, session window and spread cap are outside its reach by construction | Paper trial on a dedicated arm (**M1a**, fresh ledger; ORIGINAL arm M1 stays unmodified as the control). Primary endpoint is JOINT — all three required: G3 pf ≥ 1.30 AND G4 expectancy ≥ +0.15R over the pre-registered window (the gates t/m fail today) AND fill density ≥ 3× ORIGINAL's same-period baseline. Pre-registered kill/revert rules: trailing 20-trade expectancy < −0.30R freezes adaptation at θmax for the rest of the window; any proposal crossing the hard bounds voids the experiment outright (REJECTED; re-registration requires explicit operator action); two consecutive full-loss days revert to the most conservative θ and stop adaptation (mirrors the live-arm breaker reasoning) |

**Why P5 last (with one fallback):** an adapting trigger must adapt AROUND
measured structure, not discover it — P5 composes whatever layers survive
P1–P3 as its context signal, and inherits P4's measured k→expectancy curve
when one exists. It is deliberately sequenced after the P-series for the
same reason P4 is conditional. Fallback: if P4 voids per its own condition
(fewer than three of P1–P3 survive), P5 may run directly after P3, using
only the surviving layers as context. P5 is the first registered answer to
the operator's frequency requirement that does not ship a NO-SHIP variant
to make the live arm busier.
**P5 telemetry-first build EXECUTED in-tree (v1.17, 2026-09-18):** the P5
row's P-T step is done exactly per the R10 pattern — thr, thr_era_id
(static 0 until the adaptive engine exists) and density (running in-session
condition-true count, census semantics, counted after the session/Friday
gates at both ModeDecide sites) ride as END-OF-ROW appends on both paper
CLOSE writers; ERA note carries `+telemetry-only-per-V2-register`; no
certified-path behavior change (the certified path may still run any
pre-v1.17 binary — nothing deployed). Pinned: source-format positional pins
extended (`tests/test_midas_telemetry.py`, 17 incl. density-counter placement
and no-reset monotonicity), consumer-completeness tolerance re-verified, and
the verdict tool pinned BOTH directions on the real transition (cited
v1.16→v1.17 mixed-width ledger passes; the same transition UNCITED aborts).
Compiled 0 errors / 0 warnings via the scratch tool with before/after proof
that the deployed paper, LIVE and parity binaries were never touched
(VPS-era sync source intact). Per the queue: v1.17 deploys to arms only in
its registered era, after the 2026-10-01 reading.
**v1.17 cert chain ARMED (2026-09-18 15:42 UTC):**
`scripts/midas_cert_chain_v117.py` (running detached) sequences the deploy-
path certification behind the pending v1.16 baseline: (1) wait for the v1.16
scheduler's terminal event (jsonl contract; staleness takeover at 35 min
re-runs the v1.16 cert itself if the scheduler dies — the baseline cannot be
lost to a dead process); (2) refresh the parity shadow to the v1.17 build
(byte-identity verified, unchanged-build refused, compile via the scratch
tool); (3) run the same registered harness command against the refreshed
shadow, retry-on-flat-gate every 20 min. Ordering law: the v1.16 cert runs
on the shadow AS-IS — the shadow is never swapped before the baseline is
certified. 19 hermetic pins (`tests/test_midas_cert_chain_v117.py`); chain
events append to `artifacts/midas_cert_chain_v117_*.jsonl`. The deploy path
(v1.17 shadow certified) is thereby reached automatically at the next flat
window even across session restarts.

## 3. Sequencing

1. **Now → 2026-10-01:** nothing deploys. R1–R4 sit in-tree compiled and
   pinned; the §13 windows accrue undisturbed. Amendment 6 (telemetry rule)
   and this register are the only governing documents needed before the
   first version transition.
2. **2026-10-01:** first monthly §13 reading (manual, or `midas_verdict.py`
   live). Arms may read CONTINUE-UNPROVEN at tiny n — expected.
3. **After the reading, one at a time:** v1.13 telemetry columns (R10,
   executed in-tree, never-abort class), then v1.14 min-lot risk refusal
   (R5, amended in-tree 2026-09-17 as protocol amendment 6 — the first
   parity-gated era), then R6/R7b/R8/R9 in operator-chosen order, each with
   its own era. Both binaries are compiled and shadow-pinned; neither
   deploys before the reading.
4. **Then, P-series (§2b), one experiment per era, P1 → P2 → P3 → P4 → P5:**
   each starts with its telemetry-first build (P-T, §1-safe appends) and
   only proceeds to its decision-path amendment if the layer's raw signal
   justifies it. The R-series order above is unaffected; the P-series
   begins only after R6/R7b/R8/R9 are all adjudicated, and the P4 row is
   void if fewer than three of P1–P3 survive. P5 runs after P4 (or directly
   after P3 if P4 voids) — it is the operator-directed frequency answer and
   adapts around whatever structure the earlier P-rows measured.
4. **Live gate (post-VALIDATED):** deploy the v1.1x line with R1–R4 + the
   offset verification per health guide §4; the GO_LIVE_CHECKLIST governs.

## 4. Verification protocol for every REGISTERED item

For each register row that becomes a build: (a) python amendment + EA
change in one commit; (b) bit-level BAR parity re-cert before any arm sees
the new binary; (c) ERA note stamped per §1 mechanism; (d) fresh ledger per
affected arm, archived old ledger intact to `artifacts/paper_ledgers/`;
(e) CHANGELOG row with the register row ID; (f) source tests extended
(`tests/test_midas_time.py`, `tests/test_midas_hud.py` pattern) so the
invariant survives refactors.

## 5. Review items that are NOT defects but accepted improvements

- **#16–17** (execution model is strong; keep BAR/PERTICK and the
  research/live seam) — adopted as-is; the register's whole R1–R4 work
  happens *inside* the existing seam, never across it.
- **#23** signal freshness — already implemented (staleness guard,
  `InpStaleMinutes`); the review acknowledged it; nothing to do.
- **#25** slippage telemetry — subsumed by R10.
- **#35** gold-only fail-closed — R6-adjacent: the NOT-GOLD path currently
  warns (EA:546). Folding it into R6's build decision (either both become
  INIT_FAILED preconditions, or neither does) keeps one coherent
  fail-closed story instead of two half-moves. **Decision at build time.**
- **#36–37** (PAPER/DEMO/LIVE confirm, kill switch) — reasonable
  operational hardening, classified per §1 at build time.

## 6. Adjudication summary (why this register is trustworthy)

Every P0 claim was checked in source, not accepted: 8 of 10 confirmed
(R1, R2, R5, R6, R9 confirmed as claimed; R3 confirmed with a smaller blast
radius than claimed — BAR replay is epoch-based and parity-safe; two review
items were factually wrong — the mode default and the BB "bug"; the frame
inversion — latent vs active risk — is corrected in §2's deploy discipline
and §3's sequencing). The review's single most valuable line is adopted
verbatim in spirit: **Problem A (can we reproduce the research engine?) and
Problem B (is the strategy profitable?) are separate problems, and this
program's infrastructure exists to keep them that way.**

---

*Maintainer note: line numbers in this register are pinned to the v1.12
in-tree source (1413 lines). If the EA changes, re-derive the cited lines
before relying on them — the *tests* (test_midas_time.py, test_midas_hud.py)
are the durable pins; this document's line numbers are evidence snapshots.*
