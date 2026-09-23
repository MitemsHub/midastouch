# Changelog

## 2026-09-23 22:15Z - VPS-ERA TALLY FOLD WIRED; INGEST CORRECTED AGAINST REAL DATA; LIVE R's READ AGAINST THE CORPUS

- **`morning_status [3b]` folds `vps_fills.json` into the tally** (`_vps_fills_line`,
5 new tests): in the era the live closed-line gains `N VPS-era closed position(s)
(W/L, sumR) — tally X/30 includes them`. A FAILING or >26 h stale artifact is a
PROBLEM (the ingest is the tally's only heartbeat then); a missing one is a yellow
note (the marker precedes the migration). Fixture world: live-pin chart, both-sides-
seen fill, synthetic deal reader — the 2026-09-22 lesson applied twice.
- **Two ingest defects fixed by running it against the real account** (both now
pinned): the venue's deals carry NO SL on either side, so R joins the LEDGER's LOPEN
`stop_d` — the EA's order-time risk, which is the certified denominator (|fill−SL|
is 21.35 where the EA's stop_d is 21.71714); and the tally diff keys on CLOSES, not
opens — the ledger held all four LOPEN rows but one LCLOSE (the re-entry moved the
EA's tracker), so opens-keyed diffing reported 1/30 while the venue shows 3 closed
positions. An early draft also divided by the stop DISTANCE as if it were a price
(R 2.0168 read as 0.0102) — caught by deriving the test.
- **Measured**: true tally 3/30, +0.486R (0.1046/0.1934/0.1883 — 54.6–56.9th
centiles of the corpus forward). Parity: the ingest reproduces the EA's own LCLOSE R
(0.104) for the one position both sides hold.
- **Live vs corpus forward (engine of record, oos 130 fills)**: live mean +0.162R
sits at the 43.5th bootstrap percentile of 3-draw corpus means — the live behavior is
indistinguishable from expectation in both directions. n=3 validates nothing; it
fails to contradict.

## 2026-09-23 21:30Z - VPS-ERA LEDGER INGEST BUILT; PROFILE SAVE STILL DID NOT LAND

- **`scripts/midas_vps_ingest.py`** exists now (14 pinned tests,
`tests/test_midas_vps_ingest.py`): era-gated (NO-OP without the operator marker,
FAIL-closed with it when the venue is dark), attribution through the engine's own
`mt5_ops.attribute_deal` rule, positions paired from venue deal history, diffed
against the ledger's known fills, tally (closed/wins/sum_R) into
`artifacts/live/vps_fills.json`. Identity resolves from the arming record's `magic`
(era-marker override); both silent refuses to run rather than attribute with magic 0.
- **The short sign flip**, caught while deriving the tests, before the tool touched
live data: dividing R by `entry − SL` divides by a NEGATIVE on shorts and reads every
winning short as a loser. The denominator is the absolute stop distance now; the R
sign matrix (short win/loss, long win/loss) is the test suite's first pins.
- **Runbook §0d updated from "to build" to built**, with the one remaining wiring
stated: the `morning_status [3b]` era line is not yet automatic; until it lands the
operator reads `vps_fills.json` directly.
- **Measured blocker unchanged**: no saved profile on any of the three MT5 installs
carries the EA (newest .chr predates the save attempt). The paper-rehearsal preflight
refuses, correctly. The menu path that works is File → Profiles → **Save As...**
(there is no plain "Save"); the preset `MidastouchAI_VPS_gold.set` is staged in the
arm terminal's Presets folder for the dialog.

## 2026-09-23 22:00Z - THE HOST EVENTS ARE ON THE ARMING RECORD; THE LAPTOP ENTERS ITS CERTIFICATION NIGHT

- **Amendment 11 (artifacts/live/armed.json)** records the day's host events: the
hibernation gap (cause, fix, and the measured evidence), the empty MT5-VPS migration
(journal-quoted mechanism), and which host actually traded (this laptop; all 3 fills,
VPS executed nothing). The record can now answer "which machine was the arm on, and
what did each host do, on 2026-09-23".
- **Runbook §0c** compares the MetaTrader built-in VPS against a real Windows VPS:
execution-site vs arm-home, the blind-EA problem (the 30-trade tally and the
certification gates cannot read a VPS-side ledger), the one-terminal rule (mechanical
on MT5-VPS via the migration-time algo lock; procedural on a Windows host), and the
decision it leaves the operator, stated rather than implied.
- **Pre-night posture measured**: Hibernate absent from powercfg -a; both supervisor
tasks (S4U + legacy interactive) at LastTaskResult 0 / 0 missed with runs current;
ledger beating; readiness verdict unchanged (operator override — trading, not
validated). Tonight 22:00Z -> 08:00Z is the first measured night under the fixed
posture; per the pre-registration in docs/UNATTENDED_OPERATION_20260922.md, the
certifier is `python scripts/live_coverage.py` returning PASS over the night window
with an empty alarm — nothing else promotes the host.

## 2026-09-23 20:15Z - THE HOST HIBERNATED UNDER THE LIVE ARM; HIBERNATION DISABLED, S4U SUPERVISOR CONFIRMED, VPS RUNBOOK WRITTEN

- **Measured failure**: 2026-09-23 15:28→18:35Z (186.3 min) no supervision pass ran AND the EA's
ledger itself stopped beating (worst observed age 46.5 min) — Kernel-Power event 42 at 16:51:58Z,
"Sleep Reason: Hibernate from Sleep — Standby Battery Budget Exceeded". The laptop entered Modern
Standby and then hibernated with a live position open. A host that is in hibernation runs nothing:
not the EA, not either supervisor task. This is the laptop's second measured overnight gap
(407.4 min on 2026-09-22; see docs/UNATTENDED_OPERATION_20260922.md §1a).
- **`powercfg /hibernate off`** applied (elevated, operator-approved, reversible with
`/hibernate on`). Measured after: `powercfg -a` lists Hibernate under NOT available —
"Hibernation has not been enabled". The sleep-into-hibernation path that produced the gap no
longer exists on this host. Both supervisor tasks verified running (`MIDASTOUCH Arm Supervisor`
S4U + boot trigger + 20-min repetition, wake-to-run on; legacy `MitemshubPaperSupervisor` kept as
the interactive fallback; LastTaskResult 0 / 0 missed runs on both). The S0-idle leg remains
UNVERIFIED by design — one measured night of `live_coverage.py` PASS is the certifier, not a
setting.
- **`docs/VPS_MIGRATION_RUNBOOK_20260923.md`** added: the host-move procedure keyed to the five
readiness gates (unattended task PASS, host-power PASS, one measured night PASS, live_readiness
READY, parity holds), with the account-exclusivity rule (exactly one terminal on the account —
two is double execution), the data-folder copy that carries the ledger/census/tally, the cutover
order (pause local watchdog → stop local terminal → start VPS terminal → verify the init banner
reads `census restored`), and a rollback path. Moving hosts arms nothing: the arming record is
the record.

## 2026-09-23 11:15Z - THE SPREAD CAP WAS TIGHTER THAN THE CERTIFIED STRATEGY; FIXED AND DEPLOYED (amendment 10)

- **Measured before anything changed**: the certified engine of record's own entry costs on the
130 held-out fills (oos, venue corpus, UTC 04-18) are mean 0.0080R, p90 0.0141R, p99 0.0184R,
max 0.0193R — so the old `InpSpreadCapPctStop=1.5` (0.015R of stop) sat INSIDE the certified
trade set's own cost distribution and would have refused 7 of the 130 certified fills,
discarding +1.133R of the certified set's own expectancy. The live arm hit that floor on
2026-09-23: venue spread $0.49–0.50 against a ~$25 stop put the cap at ~$0.37 and 4 of the 5
accepted signals since arming were vetoed at the gate.
- **`InpSpreadCapPctStop 1.5 -> 2.5`** on the whole Upcomers family (paper, LIVE, M1 control),
on the engine-of-record input builder (`midas_parity.build_inputs`), and in the go-live
grammar pin — one contract, all surfaces together. The acceptance rule was pre-registered
before the presets were regenerated: 0/130 certified fills refused (measured TRUE), live
regime covered (0.0188–0.0200R < 0.025R), and the cap stays a quarter of the engine's own G7
0.10R ceiling. No trigger, stop, target, session, mode or sizing key moved. Recorded as
amendment 10 in `artifacts/live/armed.json`.
- **Deployed through the sanctioned restart path** (`mt5_ops.stop_terminal` +
`relaunch_terminal` with the attach config, book flat, backup + verify): the 12:13 init banner
reads `spreadcap=2.5%stop | execution=LIVE | mode=1`, census and tally restored, and
`midas_spread_watch` now reports the gate **OPEN** — spread $0.47 vs cap $0.54, $0.07
headroom. The next accepted signal executes.

## 2026-09-23 08:15Z - SHADOW COUNTER IN THE MORNING REPORT; THE "MISSING JOURNAL" DECODED

- **`morning_status` [3b.1] now carries the sweep-shadow forward record** as a standing
line: verdict word, N of 60, EA rows/in-window/coverage/disagreements/unmatched, artifact
age. Design constraint honored: it quotes `artifacts/sweep_shadow_forward.json` and
**imports nothing from the research layer** (`midas_sweep_shadow` stays residue; surface
audit DANGLING = none). Missing/corrupt artifact reads as "no forward record published
yet" — normal before rows exist, never an arm-health verdict. Pinned in
`tests/test_morning_status_preset.py::TestShadowRecordSection` (3 tests).
- **The "today's terminal journal is missing" caveat was a misnomer — both log files
exist.** The real event, measured: both the terminal journal and the EA log froze at
**22:12Z Sep 22** (last write mid-line), stayed frozen ~4.6h while the ledger kept its
cadence all night, and logging **resumed 02:50Z** with a venue reconnect scan. The
v1.29 deploy's two EA inits (00:06:24Z, 00:11:11Z) left ERA rows but their journal lines
fell inside the frozen window — hence `journal_retention_guard`'s "ERA today, no journal
line" alert. Its wording ("rewritten/rotated **or logging stopped**; treat as partial")
proved exactly right; no code change. 6 venue reconnects today (03:50–08:14 local), each
re-authorized in ~1s with 0 positions/0 orders; ledger cadence never broke. The EA log's
only content is the 04:11Z news-calendar refresh (332 events, 46 HIGH, 0 unresolvable).
- **Shadow state at 08:09Z:** 4 EA rows (07:00–07:45Z), all matched, coverage 1.0,
disagreements 0. The engine's 07:00Z sweep-short is still OPEN (fills at 07:15Z; 48-bar
timeout resolves it by ~19:00Z at latest) — N=0 is correct, not a stall. The mirrored
FADE book resolved −1.8022R: the direction check reads negative, where the pre-reg wants
it. Verdict: ACCUMULATING — N=0 of 60.

## 2026-09-23 07:50Z - FIRST SHADOW ROWS: TWO FRAME DEFECTS FOUND AND FIXED AT THE ROOT

- **The first EA-vs-engine pairing ran on live blind data and immediately earned its
existence.** Two defects, both in `scripts/midas_sweep_shadow.py`, both in the server-wall
vs true-UTC frame class:
  * *Lookup keyed on the raw stamp.* `check_rows_against_engine` converted the EA's
  server-stamped `sig_open` for the UTC-hour eligibility check but keyed the series lookup
  on the raw stamp — the series is UTC-keyed (corpus via `venue_bars_utc`, terminal via
  `live_bars`), so every live row would have read `unmatched` forever and no agreement
  would ever have been computed. Fixed: convert once with the row's own `off_min`, use for
  both lookup and hour check. Pins updated to the full contract (UTC-keyed series, row
  carries the server stamp); a wrong frame now reads as `unmatched`, the live failure mode.
  * *Forming bar in the resolve input.* `live_bars` pulled `copy_rates_from_pos(..., 0, n)`
  with no close test, so the still-forming M15/H1 bar entered the series and a resolve run
  mid-bar produced an outcome (SWEEP_CONT −1.92R) that no longer existed 8 minutes later —
  n flipped 1→0 between runs. Fixed: closed bars only, close time in UTC (`utc_open +
  tf_sec <= now`). The first cut of that filter compared the raw server-wall epoch against
  true-UTC now and silently dropped the newest two hours of closed bars; that was measured
  and fixed in the same hour.
- **Post-fix state (07:45Z):** 3 EA rows, all matched, coverage 1.0, disagreements 0,
unmatched 0; both corpus laws reproduce exactly (wfv 56/+15.9352R; oos sweep 152/+0.1955R,
t +2.208). N=0 resolved outcomes is correct — the engine's 07:00Z fill is still open. All
15 sweep-shadow pins pass. Read-only: EA, preset, arming record untouched.

## 2026-09-23 (morning) - CORPUS REFRESH AND THE TAIL-CREEP REPAIRS IT FORCED

- **Why the corpus looked stale.** `data/forex/xauusd/*_upcomers.csv` is fetched, not
self-updating: last fetch Sun 09-20 20:35 (market closed → tail Fri 09-18). Re-ran
`scripts/midas_fetch_history.py --suffix _upcomers` through the live terminal: all V1–V4
checks PASS, M15 16,429 bars and H1 4,115 through **2026-09-23 05:00Z**
(`artifacts/midas_history_20260923-upcomers.json`). The data of record now covers the week
the arm just traded.
- **The suite went 2→0→2→0 while the tail moved, and every failure was one defect class:**
a pin or fixture frozen to a corpus *vintage*, breaking when the tail grew. Repaired at the
root, each measured first:
  * `test_forward_cell_prereg` (the long-standing "environmental" failure — never
  environmental, just three days stale): the pin now counts the study's cell **inside the
  study's own declared window** (`window[1]` = 09-21 16:15Z, read from
  `gold_persistence_state.json`), splits at the artifact's own published midpoint, and
  judges calendar freshness **as-of the judged window** (`news_axis(..., as_of=)` — a
  frozen snapshot always ages past a moving tail; the question is whether it was current
  for the window, with coverage still refusing honestly). 662 == 658 + 4 future-dated
  entries (09-22, all stopped, −1.05R each — the persistence cell went 0-for on them).
  * `test_first_fills_audit`: the compliant-ledger fixture DERIVES its stops from the
  corpus through the audit's own `expected_stop` (the old literal stop 10.0 now reads as a
  70% geometry violation against crash-week ATR); PnL = r×risk keeps the +20/−10 shape.
  * `gold_reversal_into_close --forward`: the DECLARED forward run (protocol §Declared
  forward primary) — and it exposed a harness defect: the forward append bypassed the
  declared shape filter, admitting 09-22 (final stamp 22:45 > 22:30) into the primary rows
  against the run's own selector. Fixed to one selector; 09-23 stays primary, 09-22 sits
  auxiliary. Forward primary: n=22, net −0.0224R/day, t −0.58 — **UNDECIDED AT THIS N**,
  recorded as such.
- **Frozen corpus touched and returned:** restored from pinned commit 248db66 for the
SESSION24 `oos` leg (all three SHA-256s verified OK), bytes removed again after the run —
per `docs/FROZEN_CORPUS_20260921.md` §5.
- **Gates:** suite **1637 passed, 10 skipped, 0 failed** (first fully green run since the
corpus-tail pins appeared); surface closure 32 / residue 66 / **0 dangling**. Live EA,
preset, and arming record untouched.

## 2026-09-23 (early) - SESSION24: THE 24-HOUR REQUEST, PRE-REGISTERED, MEASURED, AND REFUSED

- **What was asked.** "Can the EA actually be intelligent enough to trade the full 24 hours
session — if yes, implement now." It can mechanically (the window is two preset inputs);
whether it can *intelligently* is an empirical question, so the full protocol was run:
pre-registration first (`docs/SESSION24_PREREG_20260923.md`, pass rule fixed before any
number), then `scripts/midas_second_session.py` (corpus-law self-check: wfv n=56
+15.9352R exactly), then the measurement (`artifacts/midas_session24_20260923.json`).
- **The verdict is FAIL, 3 of 5 pre-registered checks.** Held out (`oos`, frozen corpus
restored from pinned commit 248db66 for this leg): incumbent 04–18Z **+10.26R** (n=129,
mean +0.0796R, dd 5.24R) vs 24H **+5.56R** (n=178, mean +0.0312R, dd 9.49R) — the 24-hour
book gives up −4.71R to gain 49 fills, at +4.25R more drawdown, with per-trade edge that
clears nothing. The evening complement (18–04Z alone) made +4.46R/74 fills but at t = 0.52,
far under the family bar (t ≥ 1.96) fixed in advance — on the selection span it showed
+14.18R (t 2.42), the exact in-sample-attraction shape this repository exists to refuse.
The incumbent window stays; the request is retired until the evidence base changes (forward
shadow verdict or a new corpus era). No re-run with a different threshold — that is the
pre-registration's own wording.
- **A structural finding the engine forced:** it holds ONE position, so widening the window
is not additive — on `oos` the 24H book LOST 53 certified fills to slot displacement, GAINED
28 new day fills, shared 76. Any future evening design must be measured as a full-path
candidate against the incumbent (as this study measured it), never as an overlay. The
partition definition, verdict arithmetic (FAIL re-derivable from the artifact; a genuinely
better book IS a PASS), and the corpus-law refusal gate are pinned in
`tests/test_second_session.py` (8 tests).
- The same night, the operator's session-gate question got its measured answer on the data
of record: the gate's skipped hours earn **−0.001R/trade** held out (dead nothing) while
buying **−2.9R of drawdown** (5.24R vs 9.49R is the 24H book; the gate's own share per the
session-compat frame). Activity was never the missing ingredient; edge was.

## 2026-09-22 (night) - MIM: THE WITH-TREND BASKET, PRE-REGISTERED, MEASURED, AND REFUSED

- **What was asked for, and what was measured instead.** The operator's complaint (the arm
"declining" a visible recovery) was taken as an engineering requirement, not argued away:
a second basket, with-trend, that can join a sustained move. The census
(`scripts/midas_evening_census.py`) first corrected the premise with counts: the day was
net **−4.68 pts** (high 4375.88 @00:00Z, crash to 4291.39 @08:30Z); the afternoon recovery
began **in-gate** (15:00–18:00Z: +22.87 pts inside the 04–18Z window) and the armed trigger
never fired on it; the evening's +16.46-pt run off the 18:00Z low is entirely outside the
gate, where the arm is structurally blind. The ledger shows **zero safety refusals today** —
nothing was vetoed; the triggers were not there.
- **The pre-registration came before the numbers.** `docs/MIM_PREREG_20260922.md` fixes the
mechanism (market intraday momentum — the same asset's first half of session predicting its
second half; Gao/Han/Li/Zhou JFE 2018, replicated on commodity ETFs and Chinese futures —
a with-trend family with published OOS evidence, and a *different hypothesis* from the
cross-sectional momentum the Mahadzva series measured to be uniformly negative), the spans
(the repository's pinned `wf`/`oos` split, venue corpus), the family (6 cells: 3 ATR
thresholds × {MOM, REV}), the primary cell (`MOM_0`), the pass rule (t ≥ 2.4, n ≥ 30,
≥ 0.30 fills/day, mean > 0, same sign on `wf`, no REV twin beating its MOM twin), and the
verdict wording — with three dated clarifications made before running. The engine is
unchanged: signals ride `run_mode` as `m15_bb`, TRIGGER_ONLY, certified geometry, and the
signal is nonzero only on each day's 10:45Z bar (one decision per day, filled at the
11:00Z bar's open; `thr` reads the last H1 bar CLOSED before the decision — the lookahead
pin holds that line).
- **The verdict is FAIL, and the failure is the answer.** `scripts/midas_mim.py` reproduced
the pinned corpus law before anything else was computed. Held-out (`oos`): `MOM_0` took
**182 trades at 1.08 fills/day** — nearly the exact activity the operator asked for — and
earned **+0.0136R per trade, t = 0.17** (bar: 2.4). **0/3** MOM cells clear the t-bar
anywhere. The descriptive regression shows the decay: `beta` 0.464 (t 2.30) on the
selection span → **0.103 (t 0.76) held out**. Every `REV_*` direction twin lost held out
(−0.059…−0.092R), so the *sign* is right and the *magnitude* is a null — a real effect,
one order of magnitude too small for this clock and cost structure. The activity was
measured, and the activity is not where the money is. Artifact:
`artifacts/midas_mim_20260922.json`; verdict doc: `docs/MIM_VERDICT_20260922.md`.
- **Nothing armed, disarmed, or re-risked.** The EA, preset, and arming record are
untouched. The sweep-continuation family remains the strongest frequency upgrade on the
table (held-out 152 trades, +0.1955R, t +2.21) and its forward shadow recorder is running
(v1.28 `SWEEPSHADOW`; first rows due with the next 07:00Z window). Re-testing this family
with a different threshold is the multiple-testing drift this program refuses.
- **One defect found on first live use, fixed:** `midas_sweep_shadow.live_bars` called
`.get()` on numpy structured scalars — the shadow resolver's first real morning would have
crashed; the evening census caught it and the fix is exercised live.

## 2026-09-22 - MIDAS1.29: THE EXIT REASON WORD, AND A FLAT GATE THAT CAN NO LONGER PASS VACUOUSLY

- **The gap, prescribed by the same evening's exit audit.** The arm's first live fill was
closed by a MOBILE order and the ledger's word for it was `EXTERNAL` — the same word a
server-side stop-out gets — because the external-adoption path in `LiveCheckExits()` read
the OUT deal's PRICE only and never `DEAL_REASON` or `DEAL_MAGIC`. v1.29 (`+exit-reason`
in the ERA note) makes the adoption scan name the close: `SL`/`TP`/`SO` from the platform's
reason family (a server-side exit even though the EA did not place the closing order);
`EXPERT` when the closing deal bears our magic (the EA's own path — WHO answers before
WHAT); `MANUAL-CLIENT`/`MANUAL-WEB`/`MANUAL-MOBILE` for the platform's manual family; and
`EXTERNAL-UNKNOWN` only when nothing is known — a row must never render a guessed word as
known. Measured toolchain limit: this `ENUM_DEAL_REASON` has no OTHER member (error 256 on
`DEAL_REASON_OTHER`), so unnamed reasons stay `EXTERNAL-UNKNOWN` by design. Record-only:
no decision function reads the vocabulary (pinned), the LCLOSE reason slot merely widens
its vocabulary, and parity on the tick-covered window is PASS on the same nine trades
(`artifacts/midas_parity_result_20260922_2311.json`, max|dR| 0.0004, 0 over tolerance).
- **The flat gate the exit audit found vacuous is closed on both witnesses.** Measured
this afternoon: `midas_parity`'s pre-stop gate discovered arms from chart PROFILES only,
and the live arm is start-up-attached — so on the one machine that matters the inventory
came up empty, `verify_all_flat([])` returned vacuous truth, and two certification runs
stopped the live terminal while the venue held the arm's OPEN position. The gate now
discovers books the way the watchdog does (profiles PLUS the attach config, deduped by
ledger), refuses when an arming record names an arm but zero books are discovered ("no
books" is not "flat"), and asks the VENUE as the second witness:
`mt5_ops.venue_open_position_count()` counts open positions attributed by the same
rule the EA was corrected to (a position is ours iff its position id has an IN deal
bearing our magic — this venue stamps closing deals magic 0). Ledger-flat-but-venue-open
refuses; an unanswerable venue refuses (fail-closed — silence is exactly what the old
gate passed on); an agreeing venue is said out loud. The gate block itself is exercised
as written by `tests/test_parity_flat_gate_startup.py` (12 pins) so structure drift, not
just copy drift, fails.
- **The spread-flatness premise now has its falsification harness.**
`scripts/midas_spread_flatness.py` compares the corpus's per-hour spread (hours from the
file's own `iso` declaration — no era-pin inheritance) against the arm's live SPREADHOUR
rows, judged in the SESSION hours the gate trades (04–18Z), never the rollover hours.
Measured on the corpus side tonight: in-session 23.94–28.01 pts, **ratio 1.17 — flat, as
the premise assumes** (all-hours ratio 8.69, driven by 21–23Z rollover, which is the
reason a session gate exists). Live verdict **PENDING** until SPREADHOUR rows accumulate
(they roll at each UTC day boundary; first evaluation after ≥ 6 hours carry ≥ 10 samples).
Verdicts, stated before the numbers exist: FLATNESS HOLDS (live ratio ≤ 3.0 and level
within 2× the corpus), FLATNESS VIOLATED (the premise is false live), PREMISE MISALIGNED
(flat but at a different level — corpus cost models understate the venue).
- **Deployed and running.** Compiled 0/0 (`source=3ea31314 ex5=b1956658`, both copies
hash-checked), the terminal stopped (flat, venue 0 positions — the new cross-check ran
first), relaunched with the attach config, and the ledger's own
`ERA,MIDAS1.29,1790121984,…+sweep-shadow+exit-reason` row proves the chart runs it; both
`live_readiness` build legs PASS. Suite **1623 passed, 10 skipped, 1 failed** (the
pre-existing environmental `test_forward_cell_prereg`); 13 new pins in
`tests/test_midas_v129_record.py`, 12 in `tests/test_parity_flat_gate_startup.py`, 10 in
`tests/test_spread_flatness.py`. Surface: closure 32 (23 entry points), residue 63 (the
new harness), 0 dangling. Nothing armed, disarmed, or re-risked; preset untouched.

## 2026-09-22 - MIDAS1.28: THE SWEEP SHADOW - THE STRONGEST MEASURED NUMBER IS RECORDED FORWARD WITH NO ORDER PATH

- **What the day demanded and what the day got.** The operator asked for activity; the day
  answered with counts (`docs/ENTRY_STRUCTURE_AUDIT_20260922.md`): 84 evaluated bars, **82.1 %
  of in-session bars carried no trigger**, the armed mode fired eight shorts into a rally, and
  the engine-of-record counterfactual says the armed rule would have lost **-3.258R** taking
  both of its signals while the real book sits at +0.104R. On today's data, activity was what
  cost money. The honest response to "be more active" is therefore not a loosened gate - the
  census again read `session=0 friday=0 spread=0 riskcap=0 breaker=0 news=0` all day - but to
  put the strongest measured *active* candidate on the record so evidence, not impatience,
  decides whether it ever trades.
- **The candidate.** `docs/ASIA_SWEEP_PREREG_20260922.md` REFUSED to port the Asian-range
  sweep family (its pre-registered primary window failed on all three variants) and the same
  run reported the strongest number in this program on its SECONDARY window: oos UTC 07-18,
  **152 held-out trades, +0.1955R, pf 1.499, t +2.21**, mirror -0.1584R, textbook reversal
  read -0.1425R. Its prescribed next step was a forward shadow recorder, not a trader. That
  recorder is build **MIDAS1.28** (`+sweep-shadow` in the ERA note): one `SWEEPSHADOW` row per
  evaluated bar inside UTC 07:00-18:00 carrying the setup (the day's Asian range, sweep side,
  first-of-side flag, reclaim flag, the certified stop distance) and **never an outcome** - the
  EA cannot know the future and a row claiming an R its writer could not have measured is not
  evidence. `scripts/midas_sweep_shadow.py` resolves the rows through the engine of record's
  own `run_mode`, so the arithmetic is not re-implemented on either side. The block reads no
  order state, consults no governor, increments no census counter, and is called from exactly
  one place - all pinned by 18 tests in `tests/test_midas_v128_record.py` plus
  `tests/test_sweep_shadow.py`.
- **The rule it will be judged by was written BEFORE any row existed**
  (`docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md`): ACCUMULATING below 60 resolved outcomes and
  no interim number is quotable; then evaluate once - PASS requires t >= 2.4, n >= 60,
  >= 0.30 fills/day, mean forward R > 0, AND both direction checks still negative; FAIL names
  which test failed; VOID invalidates the RECORDER (EA rows vs independently rebuilt signals
  disagree on a bar, or a direction check turned positive forward). The arming record carries
  the block (`artifacts/live/armed.json` `sweep_shadow_forward`), `morning_status` reads the
  tail ("no rows yet - the shadow starts on the next evaluated bar inside UTC 07-18"), and the
  first rows arrive with tomorrow's window.
- **The gates, after the build.** Compiled **0 errors / 0 warnings**, deployed
  (`source=8bf3ab7c ex5=7de8d002`, both copies hash-checked) and the terminal relaunched onto
  it: the ledger's own `ERA,MIDAS1.28,1790116945,…,+sweep-shadow` row at 20:42:25Z is the
  proof the chart runs it (both `live_readiness` build legs PASS - the second leg exists
  because of yesterday's file-vs-chart lesson). Parity on the tick-covered window:
  `artifacts/midas_parity_result_20260922_2134.json` **PASS** - **the same nine trades**
  (python 9 / +0.2699R vs EA 9 / +0.271R, `max|dR| 0.0004`, 0 over tolerance), which is how a
  record-only change proves it changed nothing that decides. Suite: **1588 passed, 10
  skipped, 1 failed** - the pre-existing environmental `test_forward_cell_prereg` (662 vs 658
  corpus entries, on no changed path). Surface audit: closure **32 (23 entry points)**,
  residue 62 (the new resolver), **0 dangling**. The preset stayed byte-identical to the
  repo `.set` (44 inputs); nothing was armed, disarmed, or re-risked.
- **One day-counter restart to expect, by design.** The 13-field census floor
  (`DiagRestoreFromLedger`) deliberately does not read the v1.26-format snapshot, so the
  running day's counters restarted at the 20:42Z init (`signal=6, no_trigger=5, mismatch=1`
  so far) - refuse rather than restore a confident zero; the day's full counts live in the
  `NOFILL` rows already on the ledger. And `SWEEPSHADOW`/`SPREADHOUR` rows accumulate only
  inside their windows (UTC 07-18 and the daily roll respectively).
- **Also recorded today** (unchanged here, documented in their own entries): the exit audit
  (`docs/LIVE_EXIT_AUDIT_20260922.md` - the mobile close, the vacuous flat gate), the entry
  structure audit (`docs/ENTRY_STRUCTURE_AUDIT_20260922.md`), and the two-engine education
  (`docs/WHY_TWO_ENGINES.md`).

## 2026-09-22 - WHAT CLOSED THE FIRST LIVE FILL: A MOBILE ORDER, AND TWO GATES THAT COULD NOT SEE THE ARM

- **The venue's own record answered it, and the answer is not the EA.** Entry deal ticket 18137411:
  sell 0.01 @ 4333.07, `magic 7825001`, `reason 3 = EXPERT`, comment `MIDAS` — that is what this
  EA's orders look like. Exit deal ticket 18138688: buy 0.01 @ 4328.76, **`magic 0`, `reason 1 =
  DEAL_REASON_MOBILE`, empty comment** — an order placed from the MetaTrader **mobile** application,
  six minutes and thirty-seven seconds later, for **+$4.31 / +0.104R**. The EA's own stop and target
  **were** on the venue (`sl=4374.38 tp=4250.77` on the position's order) and **neither was touched**:
  the close at 4328.76 is inside both by 45.62 and 77.99 points, i.e. the SL was 0.95 % of price away
  and the TP 1.90 %.
- **Why no EA exit was ever in the running.** The arm owns exactly three exits — the server-side
  SL/TP placed at entry, the `InpTimeoutMinutes = 720` close on real UTC (expiry **02:00Z the next
  morning**), and `LiveFridayFlatCheck()` (a Tuesday) — and the governor is **not** one of them:
  `PropGovernorBlock()` is consulted on the ENTRY path only, so the daily cap and the shield refuse the
  *next* trade and have no path that closes an open one. Meeting the EA required a 0.95 % adverse or
  1.90 % favourable move, or twelve hours; the position lived 6 min 37 s.
- **What it would take, stated so it can be watched for:** (1) nothing external closes it first — the
  venue accepts a mobile/web/desktop order on this account and **the EA has no veto**, it can only
  reconcile (which it did, within the same second); (2) the position reaches one of the three exits;
  (3) for the two the EA executes, the chart must be up with AutoTrading and `InpLiveExecution` — the
  SL/TP exits need none of that, which is the entire point of placing them at the venue; and (4) the
  record can say *which* of them happened, which today it cannot (next bullet). Nothing here is
  measured yet for an EA-initiated or SL/TP close: no such exit has happened on this arm, and what
  would measure it is the first one — the `--live-stance` tester pass exercises the code path but
  produces no venue attribution.
- **A record gap, named: `EXTERNAL` is two different events.** `LiveCheckExits()` reads the OUT deal's
  **price** and writes a fixed word — it never reads `DEAL_REASON` or `DEAL_MAGIC`. So "my stop was
  hit" and "a human tapped Close on their phone" produce the **same row**, and the distinction lives
  only in the venue's history, outside the artifact this program keeps as evidence. The additive fix
  (next build): write the reason word — `SL`/`TP`/`SO`/`EXPERT`/`MANUAL-mobile|web|desktop` — and
  whether the magic was ours.
- **And the safety finding that came out of asking: a certification run stopped the live terminal with
  the position OPEN.** `artifacts/midas_parity_result_20260922_1502.json` (`ts 14:02:45Z`, **PASS**)
  was produced by a session that started at 14:01:40Z — **1 min 40 s after the fill** — from
  `config\v75_regress_midas_tickcov_rd_rd.ini` (`Expert=MIDASTOUCH_parity\MidastouchAI`,
  `ShutdownTerminal=1`), with the account reporting **1 position**; the same thing happened again at
  14:25:29Z (artifact `…_1526`). The position survived because the SL/TP are server-side and the EA
  **re-adopts** the venue's state on re-init (measured: `LIVE RECOVERED ticket=18874164 … SL=4374.38
  TP=4250.77` after the first one). What the arm did **not** have for those ~67 seconds is the only
  thing it executes itself: the timeout and the Friday-flat flatten. The gate that exists to prevent
  exactly this is vacuous here — `midas_parity.py` inventories **chart profiles**, this arm is
  **start-up-attached**, so the inventory is empty, `verify_all_flat([])` returns `(True, [])` and the
  run prints `flat-check OK (0 gold arm book(s) on the terminal)`: an honest count of the books it
  could see and a false statement about the books that exist. `verify_all_flat`'s own docstring names
  the trap — *"an EMPTY arm list returns (True, []) … callers must treat 'no arms inventoried' as its
  own finding"*; the watchdog does, this caller does not. **Nothing was changed to close it** — it
  moves a certification gate, so it is recorded with its one-line direction (discover arms the way
  every other tool does, and refuse on an empty inventory) and left for a deliberate decision.
- **Recorded in `docs/LIVE_EXIT_AUDIT_20260922.md`**, with §7 stating what is **not** claimed: not
  whose hands placed the mobile order (the account's authorization log shows one client address for the
  whole morning and a second only from ~15:37Z, so the close came from the same public address the
  desktop terminal used — exactly what a phone on the same network looks like), not that the close was
  a mistake, not that the tester touched the live account (it cannot, and it ran
  `InpLiveExecution=false` with its own magic), and **not** that any of it is a strategy result: one
  fill closed by hand says nothing about expectancy, which stays **NOT VALIDATED**. Docs and a README
  correction only — no code, no build, no arming change. Suite **1556 passed, 10 skipped, 1 failed**
  (the pre-existing environmental `test_forward_cell_prereg`).

## 2026-09-22 - A GREEN BUILD LEG IS NOT A CHART: READINESS NOW READS WHAT THE EXPERT IS RUNNING

- **The hole this closes was measured, not imagined.** `live_readiness`'s `deployed EA build
  matches its source` leg asks whether the binary a chart *would* load is the one the source
  produces — and on 2026-09-22 it went **PASS** (`0 errors / 0 warnings`, `source 6a2c9455`, both
  copies hash-checked) while the arm's own ledger still said **`ERA,MIDAS1.26,…`**. Replacing the
  `.ex5` did **not** re-initialise a start-up-attached expert: no re-init line in the terminal
  journal, no new `ERA` row, fifteen minutes, market open. So the go/no-go command could be green
  while the chart traded a binary nobody certified. The reload needed a terminal relaunch, after
  which the ledger wrote `ERA,MIDAS1.27,1790112181,…` — and *that* row is the thing no leg was
  reading.
- **The new leg reads the chart's own statement and BLOCKS on disagreement:**
  `the CHART runs the deployed build` compares the `ERA` row the EA appends at every init against
  the `APP_VERSION` the source defines (`tests/test_midas_hud.py` already pins
  `#property version == APP_VERSION`, so both ends are one word written by one program). The
  ledger it reads is **derived from the arming record's tag**
  (`MIDASTOUCH_paper_<symbol>_<tag>.csv`), never globbed: a retired arm's leftover book, or the
  parity harness's own tagged file, sits in `MQL5\Files` for the rest of the program's life and a
  glob would fail this leg forever over a chart nobody started. On this machine it reads
  `MIDASTOUCH_paper_XAUUSD_U25` and passes: `is running MIDAS1.27 (last init 09-22 19:23Z, 6 min
  ago (server +120min))`.
- **Three states, and the third one is the point.** `ok` (a chart names the source's build),
  `stale` (**blocking FAIL**, naming both builds, the init time and the remedy — re-initialise the
  expert by relaunching the terminal *with its attach config*), and `unconfirmed` (**WARN**, never
  a pass, never a block) for every way the question cannot be answered: no running terminal, no arm
  named anywhere, a ledger with no `ERA` row yet, or a source that states no version at all. A
  stopped terminal must not block on a leg about a chart, and an unasked question must not read as
  green — the same rule this report applies to a scheduled task it could not query.
- **Two smaller disciplines carried into the reader.** The LAST complete `ERA` row decides, and a
  short row is skipped rather than parsed generously (a bare `ERA` line parsed as `""` would compare
  two empty strings and pass); and the row's epoch is rendered **in UTC with the venue offset
  applied**, printed beside `server +120min`, because ledger epochs are *server*-stamped and reading
  one as UTC is a plausible two-hour lie this repo has already paid for once.
- **AND THE OTHER DIRECTION, which the version comparison cannot see: the file replaced AFTER the
  init.** A chart can be initialised into the right version and still not be the file on disk,
  because the `.ex5` was written afterwards — and the case that hides here is real: *source edited
  and redeployed **without a version bump***, which the pins cannot enforce. The arm's `ERA` row
  covers the binary that existed at its init and nothing later, so when the file a chart loads was
  written after that init, the version leg is reading a fact about a file nobody is running. That is
  now a **blocking FAIL** (`the chart is not running the binary that exists: … initialised into
  MIDAS1.27 at 19:23Z, but the binary a chart loads was written at 19:33Z — after that init`), and it
  says what is *proven* rather than what is not: **the ordering**, not that behaviour differs.
- **The frame is the ARM's, not today's.** Ledger epochs are server-stamped, so the comparison needs
  an offset — and using TODAY'S chosen offset is an hour wrong across a DST step, which is exactly
  the width of the case being caught. So the offset is read off the arm's own `STATE` row, which has
  carried `off_min` (its own `TimeTradeServer() - TimeGMT()`) since v1.27, with the measured one as
  the fallback for a ledger that predates the tail, and `STATE_OFF_UNKNOWN` (-9999) treated as the
  assertion of *not knowing* that it is — never as a number, which would put a 166-hour error into
  every conversion. The margin is **60 s**, not an hour: the measured finding was a deploy ~4 minutes
  after the init, and a tolerance wide enough to swallow that would swallow the finding.
- **Two stamps, and the later of them, because each is blind to a different case.** `--deploy` copies
  with `shutil.copy2`, so the deployed file carries the **scratch build's** mtime: a compile that
  finished before a chart's init but was copied after it would read as *older* than the init — as in
  step — while the file was really replaced underneath a running expert. The build record's `utc`,
  written after the copies, sees that case; a **hand** copy that never touches the script is seen
  only by the mtime. So the ordering uses the LATER of the two, and neither is treated as identity —
  that stays the hash leg's job.
- **Suite 1556 passed, 10 skipped, 1 failed** (the same pre-existing environmental
  `test_forward_cell_prereg`, 662 vs 658 entries, on no changed file's path) — **15 new pins** in
  `tests/test_build_provenance.py`, the file that already owns this leg's contract, including the
  two traps: a same-minute deploy-then-relaunch must NOT fire (the measured gap was 4 minutes, so a
  loose tolerance defeats the leg), and a DST-shifted frame must not refuse a chart that is in step.
  Live surface
  audit unchanged: closure **32 (23 entry points)**, residue 61, **0 dangling**. `live_readiness`
  now reports **no FAIL leg** on this machine, and the verdict is unmoved:
  **AUTHORISED BY OPERATOR OVERRIDE — TRADING, NOT VALIDATED**.

## 2026-09-22 - THE BUILD THAT NAMES ITS REFUSALS, SHIPPED (v1.27): A GREEN BUILD LEG IS NOT A CHART

- **Four refusals in the live evaluation path said nothing, and now they name themselves.** Measured
  2026-09-22 by reading this arm's own ledger against its own `TrackFreshM15Bar`: the session gate
  and the Friday cutoff incremented the census and returned **without** setting `g_last_action`, so
  the chart's `last:` line still showed the *previous* bar's action - the HUD said "SIGNAL BUY
  evaluated" for a bar that had been refused - and the two pricing guards (`atr <= 0`, `stop <= 0`)
  returned before the census at all, so a bar the engine could not price was neither counted nor
  named. All four are now on the record.
- **The pricing guards get their OWN counter, and that is the point of the change.** `nodata` is
  appended to the census; it is never folded into `signal`/`spread`/`riskcap`/… because nothing about
  the arm refused those bars - the engine could not price them - and inflating the refusal census
  with them would be a false statement about the venue. The pin reads the two branches themselves
  (`tests/test_midas_v127_record.py`) and asserts no refusal counter inside them, and the HUD's `V:`
  line carries `nodata` next to the vetoes so the chart answers the question without a second reader.
- **The `STATE` row now carries the same bar context the `OPEN` row has carried since v1.19e.** The
  row that is written for **every** evaluated bar had no `StateAppend()` tail while the row written
  for a *fill* had one, so the bars this arm refuses - the large majority of them - were exactly the
  ones with no `sig_ct`/`hour_utc`/`vol_ratio`/`news`/`off_min` on the record. One `StateAppend()`,
  one parser, two row types; the keyed `cfg=` token stays LAST so every positional reader is
  untouched, and `na`/`-1` sentinels render as *unasserted*, never as midnight or "no news".
- **And the arm now measures its own spread by UTC hour** (`SPREADHOUR`): sampled on the live tick
  path, gated out of the tester AND out of BAR mode, rolled **before** the daily counter zeroing, and
  read by **nothing** in the EA - it exists because the session finding this arm's research rests on
  assumes the venue's spread is flat across hours, and that assumption had only ever been read off
  the data of record, never off the live feed.
- **The load-bearing property is pinned, not asserted: none of it can move a trade.** Every v1.27
  write sits on a path gated out of `MQL_TESTER` and out of `InpBarModel` (the certified parity
  replay), so the certified ledgers cannot move, and no entry, exit, size, veto or protective rule
  reads a spread hour or a bar-context field.
- **Compiled, deployed, certified.** Compile **0 errors / 0 warnings**,
  `source=6a2c9455 ex5=ce733866`, hash-verified copies to the repo and to the terminal's
  `Experts/MIDASTOUCH` - which flipped `live_readiness`'s build leg from **FAIL** (*"the deployed
  build belongs to a DIFFERENT source"*) to **PASS** (*source == the source the deployed binary was
  built from*). `artifacts/midas_parity_result_20260922_2007.json`: **PARITY PASS** on real ticks -
  python 9tr / +0.2699R vs EA 9tr / +0.271R, `max|dR| 0.0004`, 0 trades over tolerance - the same
  nine trades as v1.24/v1.25/v1.26, which is how a record-only build is measured; plus **SIZING
  PASS** (7 closed fills, every one sized as declared at the equity it had, 5 floored to the venue's
  min lot) and **GOVERNED-PASS** at the arm's own 3 % cap on a `--breaker-stress` leg whose derived
  6.18 %/trade risk forces the refusal path to bind (the mirror predicted 1 refusal on 2026-09-11
  from 07:15Z; the governed EA took none of them and all 6 it said would survive).
- **THE PART WORTH KEEPING: the copy went green while the chart stayed a build behind.** After the
  certified `.ex5` was written to both destinations, `live_readiness`'s
  `deployed build matches its source` leg PASSed - and the arm's own ledger still said
  `ERA,MIDAS1.26,…`. Replacing the binary was **not observed** to re-initialise a
  **start-up-attached** expert (no re-init line in the terminal journal, no new `ERA` row, ~15 min,
  market open), because that leg reads the **files** and not the chart: a green leg and a chart one
  build behind are two different facts, and only the second one is a chart trading the wrong binary.
  The reload needed a terminal relaunch (`mt5_ops.relaunch_terminal()`, run **with** the attach
  config - which is also the thing that means the arm survives a relaunch at all), taken while the
  arm was **flat** and **outside session** (the gate is 06-20 *server*, so nothing was expected to
  be evaluated inside the window). It came back on the new build, and the ledger's own row proves it:
  `ERA,MIDAS1.27,1790112181,pertick-fills+…+acct-eq+census10+state-ctx+spread-hour`. Nothing was
  armed, disarmed or re-configured: the arm is still ARMED BY OPERATOR OVERRIDE, flat, 44 preset
  inputs byte-identical to the repo `.set`, and `live_readiness` now reports **no FAIL leg** - only
  the two WARNs that are WARNs on purpose (an overnight-wake claim that no `powercfg` reading can
  settle, and the absent validation record).
- **One consequence of the census change, named before it is mistaken for a fault.** `nodata` is
  counter **10** and the row is append-only, so `DiagRestoreFromLedger` now requires **13 fields** and
  a **v1.26** `NOFILLSUM` snapshot is deliberately *not* read as one - restoring a missing 10th counter
  as a confident zero is the exact class of sign this program keeps paying for. So the arm's first init
  on v1.27 logs exactly what it did (`NOFILL census: no snapshot row yet, counting from zero`) and the
  **in-progress** day's refusal census starts again from zero on the new build. The earlier counts are
  not lost: they are the `NOFILLSUM` rows already in the ledger, which the readers total over their own
  window (`morning_status`: `no-fill (24h): signal=17, no_trigger=17`). The LIVE fill census restored
  normally (`closed=1 wins=1 cumR=+0.104`), and the init journal carries **no error or failure line**.
- **Where the arm stands:** alive and evaluating (H4 up / H1 up -> BULLISH, `trigger none`,
  **outside session** - the gate classifies *server* bar epochs, 06-20 server - so no entry is due
  until 06:00 server), flat, day +$4.31 of the $250 cap, floor $23,504, min-lot risk $42.02 of the
  $62.50 configured and quantised down, 1 closed fill reconciled against the account.
- **Suite 1541 passed, 10 skipped, 1 failed** - the pre-existing environmental
  `test_forward_cell_prereg` (the venue corpus has grown to 662 entries against the study's pinned
  658), on no changed file's path. Surface audit: live closure **32 (23 entry points)**, residue 61,
  **0 dangling**.

## 2026-09-22 - THE ONE EXTERNAL LEAD, TESTED AND CLOSED: gold-vs-AUD structural divergence FAILS here

- **The outside research's single surviving result was tested on the venue's own bars at the first
  opportunity, and it does not transfer.** Pre-registered in
  `docs/CROSS_ASSET_DIVERGENCE_PREREG_20260922.md` before the run; harness
  `scripts/midas_cross_asset.py`; artifact `artifacts/midas_cross_asset_20260922.json`; pins
  `tests/test_cross_asset.py`. Verdict against the rule fixed in advance (t >= 2.4 for a 3-variant
  family, n >= 30, >= 0.30 fills/day) on the held-out window:
  `DIVERGE FAIL t=-0.347 | FADE FAIL t=-0.140 | ALIGN FAIL t=-0.385` - **all three fail on the t
  test and only that test**, with 164-203 fills at ~1.0/day. This is not an underpower problem: the
  sign is wrong on more than enough trades, and every variant is negative in BOTH spans (`wf`
  `DIVERGE` -0.1598, n=77, t -1.41). The signal fires on ~10 % of bars, so rarity was never the
  issue - it is simply the wrong signal here.
- **New data of record, fetched for it and recorded:** `AUDUSD H1 4,316 bars / M15 17,250 bars,
  2026-01-12 -> 2026-09-22` from the SAME terminal and account as gold
  (`C:\Program Files\MetaTrader 5` build 6204, account 1428765 @ Upcomers-Server), all validation
  checks PASS, provenance in `artifacts/midas_history_20260922-upcomers.json`. `--symbols` was ADDED
  to `midas_fetch_history.py`; **`SYMBOLS` still contains only `XAUUSD`**, so no existing artifact's
  provenance becomes ambiguous (`symbols_default_unchanged=false` is recorded in the new artifact).
- **A real defect found during verification, before anything was reported.** The first run expressed
  the CONTEXT series in bar **open** times while the gold leg used close times, giving the AUD leg's
  swings **one H1 bar of lookahead**. Caught by reading the code against its own claim, fixed, and
  now pinned by a direct **repaint test**: perturbing a future bar's high must not move a single
  earlier signal. The verdict is negative either way, and the window-scoped signal counts were
  corrected in the same pass (they had printed the whole corpus twice).
- **The signal is non-repainting by construction and that is asserted, not assumed:** a swing needs
  `high[i] > high[i+-1]` and `> high[i+-2]`, so it is confirmed only at the CLOSE of `i+2`; the
  structure direction uses only swings confirmed at or before the moment being priced; and only H1
  bars whose close is `<= ct` are visible - the same rule `run_mode` uses for its own macro state.
- **Nothing was ported to MQL5 and no EA build was touched** - the pre-registration said a port
  happens only on a pass, and there was none. Suite **1529 passed, 10 skipped, 1 failed** (the
  pre-existing environmental `test_forward_cell_prereg`, on no changed file's path).

## 2026-09-22 - THE OUTSIDE WORLD, RECONCILED: A 10-PAPER 2026 SERIES AGAINST THIS ARM'S NUMBERS

- **A "Deflated Alpha Series" (S. Mahadzva, 2026, SSRN working papers 1-10) was read against our own
  measurements**, and the reading is on the record in
  `docs/EXTERNAL_LITERATURE_RECONCILIATION_20260922.md`. Provenance and limits, stated first: the
  series is **preprints, single author, not peer-reviewed**; the full texts are **unreachable from
  this machine** (SSRN 403s automated fetch, a reader proxy returns the bot challenge, and a real
  browser tab did not clear Cloudflare), so **the whole reconciliation is abstract-level**, obtained
  through Crossref metadata (`api.crossref.org/works?filter=orcid:0009-0001-1754-4472`, 9 items).
  Nothing in it may be cited as evidence in a gate; it is a reason to pre-register tests.
- **The one result that matters most is a corroboration at a scale we will never reach.** Their
  matched free-direction **Bollinger** rule: **+0.022R over 2,231 OOS trades** and -0.044R on
  holdout, DSR ~0.00. Ours: **+0.0355R over 127**. Different instruments, different programs, same
  conclusion - this rule family is a null at intraday resolution - and our small sample is
  consistent with their large one, which is the strongest external support available for this arm's
  "insufficient evidence" verdict.
- **Four of the 30-phase request's directions are contradicted by measurement, not by taste.**
  Confluence/evidence-combination and rare-condition filters **degraded** the signal they were added
  to (+0.041R -> -0.054R, p 0.754; rare conditions winning folds on lucky trades) - Phases 9/10.
  Opening-range breakouts lost on every combination; VWAP/EMA pullback near-misses reversed on
  holdout; cross-sectional momentum was uniformly negative and worse at faster timeframes - Phase 11
  paths A and C. ICT/SMC as taught: no evidence, with three sweep mechanisms agreeing 65 of 66
  folds that a swept level predicts **continuation**, not reversal - Phases 6/8. And their calendar
  paper names the exact trap of adding a free walk-forward dimension (a weekday filter made an
  optimiser "discover" Monday, the worst weekday in the honest sample) - which is why our own two
  moved dimensions (session window, trigger k) were pre-registered and split before measurement.
- **Two things they add that we have never tested, both worth a pre-registration and neither run:**
  (1) their program's **only surviving result** is **gold-vs-AUD structural divergence** (clears
  permutation, max post-correction DSR, survives a 100x cost increase, fails their
  walk-forward-efficiency gate, short-history fragile) - one signal that adds INFORMATION rather than
  parameters; (2) a **cost-based minimum stop-distance floor**, their repair for an R edge smaller
  than the per-lot commission a tight stop forces, which sits directly beside our own min-lot
  arithmetic ($41.31 = 0.165 % of equity, not the declared 0.25 %) and our tight-stop study's
  `POSITIVE, UNDERPOWERED | does not clear the program-wide hurdle`.
- **One methodological import and one operational one.** Their **walk-forward-efficiency band**
  (~1.0-1.6 acceptable, 2.08 fragile, >2.5 rejected) is a check this repo lacks and it caught results
  their p-values passed, including their own flagship - cheap to add beside V1-V7, and it would have
  flagged our `LONG_ONLY` `wf`/`oos` flip before a human did. And their implementation bug **invisible
  to every statistical gate, caught by a human looking at a chart** is external support for treating
  the HUD and `STATE` rows as validation artifacts - the method that found our v1.21-v1.26 defects.
- **No EA build was touched, nothing was armed or disarmed, and every certificate stands.** Suite
  **1525 passed, 10 skipped, 1 failed** (the pre-existing environmental `test_forward_cell_prereg`, on
  no changed file's path). Docs and a review packet only: `docs/EA_REVIEW_PACKET_20260922.md` is the
  paste-ready brief for any external reviewer.

## 2026-09-22 - DECISION ENGINE AUDIT: WHICH LEG OF THE ENTRY CONJUNCTION EARNS ITS KEEP

- **The question was "is the trading logic structurally too rigid", and it is now answered with
  counts instead of adjectives.** The armed mode is ONE setup family: a BB(20, k) touch-back / RSI
  extreme on M15, entered only where the H1+H4 EMA20 regime is ANTI-aligned with that trigger, and
  only inside the session window. New harness `scripts/midas_decision_attribution.py` (pre-registered
  in `docs/DECISION_ATTRIBUTION_PREREG_20260922.md`) walks every evaluable bar and classifies it by
  the pair the engine itself branches on, then ablates the legs through the engine's own 8 modes on
  the repo's pre-registered split. Both self-checks are binding and both passed: the pinned
  venue-corpus law `wfv = 56 / +15.9352R` reproduced, and the census agreed with the engine on
  **every trade of all 8 modes on both spans** (0 disagreements).
- **The trigger is the rarity, by design: 82.66 % of in-session evaluable bars produce NO trigger**
  (5,516 of 6,673 on the held-out window). The armed class occurred 503 times and filled 127. The
  per-hour table is flat (380-420 of every 480 bars per hour) and the ATR(H1) terciles differ by
  little. The live arm's own ledger says the same thing from its `STATE` rows: of 50 distinct signal
  bars evaluated, 35 (70 %) had no trigger, 5 (10 %) were the armed class, 10 (20 %) were outside
  the window. Nothing protective is refusing anything: `session/friday/spread/riskcap/brk/news = 0`.
- **The macro-alignment leg COSTS WITHOUT MEASURABLY PAYING - and buys drawdown.** Removing it takes
  fills from 0.75 to **1.28/day** and zero-entry days from 41.4 % to **29.0 %**, for **-0.0243R** of
  held-out expectancy at **Welch t = +0.21** (unmeasurable), while max drawdown goes **6.3R ->
  13.3R**. Against the pre-registered 0.05R bar it fails; against a drawdown criterion it is the
  most valuable rule in the file. The reversal premise itself is **not established**: the armed mode
  beats its mirror image (`ORIGINAL`, macro agreeing) by **+0.0249R, t = +0.19**, and its support
  comes from `wf` - the span the configuration family was searched on. `REVERSE_BOTH` is measured
  HARMFUL (-0.0941R, 28.6R DD, negative in both spans) and must never be enabled.
- **The finding that governs everything else: the constraint is DATA, not design.** The venue corpus
  is 2026-01-12 -> 2026-09-18, 16,224 M15 bars, 8 months, two clock eras. At the armed
  configuration's own frequency, deciding its expectancy at t >= 1.5 needs **1,931 trades = ~7.0
  years of this market**; `TRIGGER_ONLY` needs ~43, `MACRO_ONLY` ~79; the most decidable cell
  (`SHORT_ONLY`) needs ~1.7. A six-family / seven-regime / confidence-scored engine would multiply
  the hypotheses searched against those same eight months, so it is **not** proposed - the report
  says which items on that list are blocked and what would unblock them.
- **`docs/DECISION_ENGINE_AUDIT_20260922.md`** is the resulting Phase-30 report: the architecture map
  with line numbers, the complete veto inventory (9 counted classes, plus 4 `return` sites that
  refuse SILENTLY and are named), per-component verdicts, the ranked list of what the evidence
  supports, the proposed one-seam architecture (a setup LIST + an evidence gate that can say
  "insufficient evidence"), the testing plan, the measured frequency change, the risks, and the
  exact files/functions that would change. **No EA build was touched: the deployed v1.26 binary is
  unchanged** and no signal, size, protective rule or ledger writer moved.
- **Counts:** suite **1525 passed, 10 skipped, 1 failed** (the pre-existing environmental
  `test_forward_cell_prereg`, on no changed file's path); surface audit **0 dangling**. The parity
  certificate, the arming record and the live arm are untouched by this work.

## 2026-09-22 - THE SHIPPING 3% DAILY CAP IS CERTIFIED AT A DERIVED RISK, ON THE PASS'S OWN CLOCK

- **The gap this closes, in one sentence.** The governor had a certificate at a threshold *derived
  to bind* (0.11 %) and none at the number the arm actually runs (3 %), so the shipping leg could
  only ever say **VACUOUS** — honest, and not a certificate. The lever is now the **risk per trade**
  instead of the cap, because a daily-loss cap is a percentage of the day's opening equity and a
  3 % day is only reachable on this window if one trade is worth more of it.
- **Why a construction, measured.** On the tick-covered window (the only span the venue serves real
  ticks for) the live path makes **7** closed fills, no day holds more than two, and the largest day
  drawdown still followed by an entry is **0.583R** — **0.14 %** of the day's opening equity at the
  arm's own realised risk, so a 3 % day would take **~19 consecutive full stops inside one UTC day**.
  The window cannot be widened (everything outside the real-tick span is demoted to REFUSED), and
  **R is risk-invariant**, so raising the risk moves *when* the rule binds and the order of nothing:
  the certified path took **exactly** the shipping stance's entries.
- **The certificate: `--live-stance --breaker-stress`, GOVERNED-PASS at the arm's own 3 %.** Derived
  risk **6.18 %/trade** (3 % over the 0.583R day, carried at a declared 1.2 margin for the venue's
  lot step). Two passes on the same window and tick model — `BSU` with the governor OFF (the path
  the prediction is read from) and `BSG` with it ON at the **shipping 3 %** — and the verification is
  the four-way disagreement test: `refused_as_predicted 1 / refused_but_taken 0 /
  survived_as_predicted 6 / lost_without_prediction 0 / unexpected_entries 0`. The refusal is
  attributed by the pass's own record: the governed ledger has **6** closed fills against the
  ungoverned **7** (shas `0098144c` vs `737cf121`), the missing row is exactly the predicted
  `LOPEN,1789142400,...` (2026-09-11 14:00Z), and the EA's journal vetoes it with
  `PROP VETO: daily-loss cap (3%)`. Artifact `artifacts/midas_parity_result_20260922_1843.json`;
  `armed.json` amendment 9; protocol amendment 12.
- **Two modelling defects, both found by failing first and both fixed.** (1) **The derivation was
  read off the wrong path.** Derived from the python engine of record it came back **NO-BIND**
  (`..._1822.json`): the bar model takes **9** trades where the live path takes **7**, and its worst
  usable day (2026-09-15) is a day the live path never trades — a threshold derived from a market
  the pass does not walk is not a stress of that pass. The derivation now reads the **live stance's
  own fills**. (2) **The day anchor is not a close-walk's anchor, and the day is not UTC.**
  `PropDayAnchorCheck()` includes the **floating P&L** of any position carried across the boundary,
  and `TimeUTCNow()` returns `TimeGMT()` — which **inside the strategy tester is the venue's clock**,
  so the pass rolls its day at **server** midnight (UTC 22:00 here) while the live arm rolls at true
  UTC. Both were measured off the pass's own journal: `STALE feed` prints at 00:00:00 **server** every
  day, and solving the pass's `DAILY BREAKER TRIPPED: equity down 7.46%` line puts the boundary price
  at **4321.05** — inside the boundary bar, and **$3.85** from the previous bar's close that an
  "ending at the boundary" rule would have used. $3.85 is $108 of floating, **0.43 % of equity
  against a 3 % cap**: it decides a 2.98 %-vs-3.00 % comparison. `breaker_walk` now rolls on the
  **pass's** day (named in the artifact's `day_clock`) and marks the boundary floating at the bar's
  **adverse extreme**, the direction in which a predicted breach stays predicted. The pass that ran
  under the old model (artifact `..._1833`) reported **GOVERNED-FAIL** — it is in the record, not
  adjusted away.
- **Limits, stated rather than implied:** this certifies the rule under the **tester's** clock (the
  live arm's UTC-midnight instant is not certified here); the risk per trade in the pass is a
  **stress input** (6.18 %, not the shipping 0.25 %) while the cap, strategy, window, tick model and
  entry sequence are the arm's own; the shield is **measured** on the path (never within $1,500.00 of
  its floor, and that floor is pinned at the declared size) rather than modelled; and the profit
  ceiling is **off by declaration**, with its 2 would-be refusals reported beside the result.
- **Counts:** suite **1520 passed, 10 skipped, 1 failed** (the pre-existing environmental
  `test_forward_cell_prereg`, on no changed file's path; `tests/test_parity_live_stance.py` is now
  45 tests). Surface audit **0 dangling**. The strategy certificate is unchanged — same nine trades,
  `max|dR|` 0.0004 on real ticks — which is the measurement that this work moved no rule.

## 2026-09-22 - THE MAGIC-0 CLOSE: ONE ATTRIBUTION RULE, AND NOW ONLY ONE COPY OF IT

- **The defect, in one line: `if deal.magic != ours: continue`.** MEASURED on the arm's first real fill,
  the venue stamped the ENTRY deal with magic 7825001 and the **CLOSING** deal with **magic 0** (the
  platform executed it; its reason read MOBILE). Every reader that filtered the venue's deal history on
  the deal's own magic threw that close away — and a filter that drops a row reports a **smaller world**,
  not an error. On the EA side this was a **risk** number (the day's realised P&L, and the Best Day cap
  and reconstructed opening equity measured from it) and was fixed in v1.25 by attributing **by
  position**. The python side had the same defect in **three** readers, and a rule copied into three
  files is three rules, so the rule now lives once:
  `mt5_ops.our_positions_from_deals` / `attribute_deal` / `attributed_deals` — ownership is a property of
  the POSITION (an OUT deal is ours iff its position has an IN deal bearing our magic), and the
  attribution is recorded **per deal** rather than flattened, because the whole defect was that this
  could not be told from the output.
- **The three readers, all converted:** `midas_watchdog.live_fill_reconciliation` (the completeness alarm
  `morning_status` reports), `midas_first_fill_packet.venue_deals` (the ledger-vs-venue packet — the
  reference implementation, which had already got it right and now shares the rule), and
  `midas_lv_broker_monitor.build_state` (the broker-evidence surface: a monitor that cannot see a close
  is evidence of a position that never ended). **Audited after the change:** those are the only three
  python files in the repository that touch the venue's deal history, and the only magic comparison left
  anywhere is on OPEN **positions**, which is correct — an open position's magic is set by whoever opened
  it.
- **Fail closed, and the direction is the point.** An OUT deal is adopted only when its position has an
  IN deal bearing our magic **among the deals that were read**. A close whose opening cannot be seen is
  **not** ours and is never assumed to be: the two mistakes are not symmetric — dropping one of our
  closes under-reports our P&L, while adopting a **stranger's** close would put someone else's loss inside
  this arm's day cap, invisible, inside a risk rule. Unattributable deals are now **named**
  (`unattributed_deals`) instead of silently dropped, and a `SILENT` verdict with unattributable deals
  present says so — "saw things it could not name" and "nothing traded yet" must not read the same.
- **Measured on the live account, not in a fixture:** the watchdog reconciliation now reports
  `matched / healthy`, `1 close(s) adopted BY POSITION (the venue did not stamp them with our magic)`,
  naming position 18874164 / ticket 18138688 / magic 0 / price 4328.76; and the packet's two deals now
  attribute as `entry → magic`, `close → position`, with its verdict still **AGREE**. The EA's own
  `LENTRY` heal and the packet agree with the venue for the same fill.
- **Pinned** (`tests/test_deal_attribution.py`, plus cases in the three readers' own files): the rule's
  behaviour in both input shapes (MT5 namedtuples and the packet's dicts), the fail-closed directions
  (a stray close, an IN deal without our magic, a `0` position id), the L4 monitor adopting our close and
  rejecting a stranger's, and a **source pin that no reader re-introduces the magic-only filter** and that
  `our_positions_from_deals` is defined in exactly one module. Suite: **1508 passed, 10 skipped, 1 failed**
  (the pre-existing environmental `test_forward_cell_prereg`).

## 2026-09-22 - THE ARM NOW SURVIVES UNATTENDED, AND THE BARS THE CERTIFICATION RUNS WERE EATING

- **Registered: `MIDASTOUCH Arm Supervisor`** — S4U principal ("run whether or not the user is signed
  on"), a boot trigger, the pinned 20-minute cadence, no execution time limit, and **wake-to-run".**
  Verified against the scheduler's own XML: `logon=S4U triggers=boot,time repeats=20.0min
  wake-to-run=on time-limit=PT0S`, and `live_readiness` moves the two previously-blocking legs to
  **PASS** — its verdict is now `AUTHORISED BY OPERATOR OVERRIDE — TRADING, NOT VALIDATED` instead of
  NOT READY. Proved it runs, not just that it exists: forced a pass, `Last Result: 0`, and the
  heartbeat it wrote at 17:03:12Z reads `verdict OK, action NONE, terminal_running true, armed true`.
  The legacy interactive task is **kept** (`-KeepLegacy`) for the trial night, because whether an S4U
  task can stop and relaunch the MT5 GUI is still unverified; it is removed once a pass from the new
  one is on the record.
- **AND THE INSTALLER HAD TO BE FIXED TO GET THERE.** The first `-Apply` printed *"Registered"* over a
  task whose XML the scheduler had **refused** and which had silently fallen back to the cmdlet path —
  the one form that **cannot express wake-to-run**. The task existed and ran on its cadence, so on a
  sleeping host it would have written no line at all: the night would have read like a quiet market,
  and the single leg this installer exists for was the one lost. The scheduler named the offending
  node (`(32,7):UseUnifiedSchedulingEngine`); reordering the whole `<Settings>` block to the published
  schema moved the line number and nothing else. So the installer now tries the definition in
  **progressively smaller forms** — dropping `UseUnifiedSchedulingEngine`, then `IdleSettings`, then
  `Hidden`/`Enabled`, one at a time — and **never** drops `WakeToRun`, the S4U principal, the boot
  trigger or the repetition. This machine accepts `without UseUnifiedSchedulingEngine`, and the
  accepted form is printed. Two rules come out of it: a registration that cannot express the wake
  flag must **not** be reported as success (the installer already refused to, which is how this was
  caught), and a `<Settings>` element list must be pinned **in order**, not by presence — every name
  was already present in the broken version. `tests/test_unattended.py` now pins the order.
- **Windows still owes the last leg, and it is named rather than assumed:** whether a wake timer
  actually wakes an *S0 Low Power Idle* host — and whether closing the lid suspends it — is not
  observable from `powercfg` on this build. Promote it with `scripts/live_coverage.py` after one real
  night, not with a setting.

### Why the arm has not taken another trade (measured, and part of it was us)

- **The EA is not slow; it is bar-driven.** Since the 14:06Z fill, 11 in-session M15 bars closed and
  **8 were evaluated** — every one with `trig=0` (no trigger fired: RSI between 46.7 and 54.4, price
  inside the bands), so the macro rule was never even asked. The four bars today that *did* fire a
  trigger were declined by it (`mismatch=4`). Nothing protective refused anything: `session=0
  friday=0 spread=0 riskcap=0 breaker=0 news=0`, governor `CLEAR`, spread $0.40 against a $0.62 cap.
- **3 of those 11 bars were never evaluated at all — 14:30Z, 16:15Z and 16:45Z — and each one is a
  bar that closed while this session's certification runs had the terminal stopped.** The EA
  discovers a new bar on a tick, and on its first tick after a reload it sets its bar pointer and
  returns *without evaluating*; a bar that closes while the terminal is down is therefore gone, with
  no row anywhere saying so. That is a real, self-inflicted cost of running parity passes against a
  live arm, and it is why the answer to "why no trade" cannot be read off the chart.
- **Named, not patched:** the fix is a bounded catch-up (on init, evaluate the single bar the ledger
  says was missed, if it is recent and unrecorded) and a ledger row that makes a miss *visible*. The
  catch-up changes **when** an entry happens — a trade would be taken one bar late, at the market
  price of the catch-up instant rather than the missed close — so it is a strategy-relevant change
  and belongs in a pre-registered decision, not in a drive-by edit. The visibility half has no such
  question and is the smaller job.

## 2026-09-22 - `vEq` WAS THE PAPER BOOK'S FROZEN COUNTER: the arm's own equity on the chart and on the record (v1.26)

- **The report, and it was correct.** The operator's screenshot: with the account at
  **25,004.26** the chart printed `vEq: $25,000.00 (start $25,000.00)`, and the ledger's heartbeat
  printed `EQ,25000.00`. Both numbers were `g_paper_eq` — and **on an armed arm the paper book never
  trades**, because `LiveSendOrder` is the only entry path that runs, so that value is a **frozen
  constant standing where the arm's equity belongs**. Same defect class as v1.24's `trades: 0/30`,
  and worse in consequence: equity is the figure the governor's shield and day caps are read from,
  so the chart disagreed with the number the **risk rules** use.
- **The fix, and it is one meaning with two books.** The HUD's equity line and every **live**
  heartbeat `EQ` row now carry the ARM's equity — the venue's `ACCOUNT_EQUITY` on the live path,
  the paper book on the paper path — through a single write site (`LogEquityRow()`), so the record's
  basis cannot drift from the display's again. The live label names the record it is reading:
  `vEq: $25,004.26 acct (bal $25,004.26, +4.26 vs the $25,000 basis)`. The paper form is v1.10's,
  **verbatim**, and every write is gated out of tester/BAR runs, so certified parity ledgers and the
  paper arm stay byte-identical. The `EQ` row's BASIS changes on a live ledger, so the ERA note
  gains **`+acct-eq`** — a reader must be able to tell that from the ledger alone.
- **Why it could not be caught by the suite.** Nothing in the repository read the HUD's own line
  back, and the number it printed was *internally consistent* with the paper book — the defect lived
  in the meeting point of two records, which is exactly where the arm's other three defects lived.
  The new pin (`test_the_equity_line_names_the_record_it_is_reading`) asserts the live line reads the
  venue and never `g_paper_eq`, that the label names the basis, and that the heartbeat row is
  written through the same helper the display uses.
- **Recompiled, deployed, re-certified — in that order.** `compile_midas.py` **0 errors /
  0 warnings** (`source=9bf97612 ex5=049f31e4`), deployed, and re-certified on the new binary with
  `--window tickcov --corpus venue --live-stance --governor-stress`: **PARITY PASS** (the same nine
  trades, `max|dR|` 0.0004) and **ACCOUNT LAYER PASS**. The unchanged trade set is again the
  measurement that this build is display/record only. Certificate of record:
  `artifacts/midas_parity_result_20260922_1743.json` (amendments 6, 7 and 8 in `armed.json`).
- **AND THE GOVERNOR IS NO LONGER ONLY "UNEXERCISED" — it is certified at a threshold DERIVED to
  bind (`--governor-stress`, amendment 7).** The shipping leg can only ever say VACUOUS here (the
  largest day drawdown is 0.318% of a 3% cap), and a leg that says *"never asked"* is honest but is
  not a certificate. Changing the strategy so a window binds it would be selecting data, so the
  threshold was derived instead — **and the derivation was fixed by measurement**: the first rule
  tried (*half the largest day drawdown*, 0.15%) breached on the day's **last** fill and refused
  nothing, which the run reported as `NO-BIND` (artifact `..._1718.json`) rather than dressing it up
  as a pass. The rule is now *truncate 2dp the largest day drawdown still followed by another entry
  on that day* — **0.11%** from the 2026-09-11 07:15Z close — with the unusable closes named as
  skipped. Two passes on distinct ledgers (LSU `34474511` / 7 fills, governor **OFF**; LSG
  `04201b95` / 6, governor **ON**), and the check is falsifiable: the mirror reads its prediction
  off the **ungoverned** path — reading it off the governed one would leave `must_be_present` empty
  by construction and make an over-refusal undetectable — and the EA must then refuse exactly those
  entries and keep every other one. **GOVERNED-PASS**: `refused_as_predicted 1` (the 2026-09-11
  14:00Z entry), `refused_but_taken 0`, `survived_as_predicted 6`, `lost_without_prediction 0`,
  `unexpected_entries 0`. The ungoverned pass took the same entries as the shipping stance, which is
  the VACUOUS verdict stated from the other side. Verifying that leg then caught a **second, quieter
defect in the model itself, found by arithmetic rather than by a failure**: the stance read the
  best-day cap as `account x InpPropBestDayPct` = **$5,000/day** when the EA's own
  `PropDayProfitCapUsd()` is `size x target% x best-day%` = **$250/day** — twenty times smaller, and
  the number the chart prints. A model that under-states a cap by 20× cannot see it bind, so its
  VACUOUS verdict (and the `$5,000` in the artifact's day table) was a **false negative presented as
  evidence**. Corrected, the verdict is unchanged and now means something: the window's best day is
  **+$78.23 = 31.3% of the $250 cap**, where the old number made it read as 1.6% of a cap twenty
  times too large. A best-day share with no target is now **refused rather than guessed**, and a test
  pins the python mirror against the EA's own function body so the two can never state different
  rules. Three more integrity rules came out of this work: each
  pass's ledger is recorded with its sha256 and mtime, and **a ledger older than the pass that
  should have written it is REFUSED, never graded** — the tester agent writes ONE file per arm tag,
  so a silent pass would otherwise be graded against the previous pass's fills and reported as a
  certificate. **The shipping 3% cap is still unexercised at this risk and stays reported VACUOUS**
  — superseded the same day by the `--breaker-stress` certificate above, which exercises the refusal
  path at the shipping 3% by deriving the risk per trade instead of the cap; the live-stance
  governor audit still reports VACUOUS, because at 0.25%/trade this window cannot reach 3% and that
  distance is now printed as arithmetic. The trailing
  shield floor and intrabar excursions remain unmodelled, named in the artifact as always.
- **And what the operator actually asked for, stated plainly:** the arm is **armed, flat and
  evaluating**; nothing of ours refuses its signals — today's refusal census is `signal=33
  no-trigger=29 mismatch=4` with `session=0 friday=0 spread=0 riskcap=0 breaker=0 news=0`. The fill
  rate is decided by the entry rule (`REVERSE_DIRECTION` requires the macro to CONTRADICT the
  trigger), and no change in this session moved it — a trade cannot be ordered into existence, only
  the rule's own signal can, and the arm takes what the rule accepts.
- **Pins moved with the build:** the version register (`test_ea_version_is_the_r6_build` += v1.26 with
  its reason), the deployer's accepted ERA stamps (`ERA,MIDAS1.26,`), and the two HUD pins that name
  the equity line and the heartbeat's write order (extended, with the reason in place). Suite:
  **1473 passed, 10 skipped, 1 failed** (the pre-existing environmental `test_forward_cell_prereg`).

## 2026-09-22 - THE ARM'S OWN FILL TOLD THREE LIES, AND NO CERTIFICATE COVERED THE ARM: the fill-row-integrity build (v1.25) + the account layer certified for the first time

- **The instruction was to fix the three defects the arm's first fill exposed, and all three
  were measured from the ledger and the venue's own history rather than inferred.** (1) *The
  entry price was a zero.* The row the arm wrote reads
  `LOPEN,1790092800,0,18874164,0,-1,0.00000,...,cfg=62.50@0.25(missed string parameter)` - the
  price came from `ResultPrice()` at the instant of acknowledgement, when on this venue that
  field is 0, while the true 4333.07 was in the position **and** in the entry deal within the
  same second; the packet reported `entry price: ledger 0.0 vs venue 4333.07` for the rest of
  the fill's life. (2) *`(missed string parameter)` on every fill row*: the LOPEN format
  carried **four `%s` for three arguments**, so MQL5 appended its own missing-argument text into
  a data row. (3) *A closing deal is not always ours to stamp*: the venue's **closing** deal
  carried **magic 0** (the platform executed it - the reason field reads MOBILE) while the entry
  deal carried 7825001, and the day's realised P&L filtered OUT deals on `DEAL_MAGIC == InpMagic`
  - i.e. it ignored every externally-closed trade, and that number is what the **Best Day cap and
  the day's reconstructed opening equity** are measured from. A risk-path number.
- **The fixes.** The ack resolves the price from the position or the entry deal before the row is
  written; if neither answers inside a bounded wait the row says `entry=pending` (**a 0 in a price
  column is read as a price by every reader** - a keyed token is not); and
  `LENTRY,<epoch>,<identity>,<price>,<source>` amends it the moment the venue reports one, at init
  (which heals a row written by an earlier build) and again the moment a pending fill resolves.
  The specifier counts now match their arguments, with the tail **ordered by contract**: the
  configured-risk token is read off the END of the row, so v1.25's `,entry=pending` sits before
  it. Day-P&L attribution is now **by POSITION** (an OUT deal is ours iff its position has an IN
  deal bearing our magic), with the unmatched case LOGGED rather than dropped.
- **The heal is confirmed operating on the live arm, not just present in source.** The running
  build's own ERA row is followed by
  `LENTRY,1790099656,18874164,4333.07000,entry deal` - the identity taken from the row's ORDER
  field, because on a netting account that IS the position id and `posid` is 0 at write time. And
  the readers consume it: `midas_first_fill_packet.read_live_ledger` now pairs
  `LENTRY,<identity>,<price>,<source>` rows (the packet is the tool that reported the
  disagreement), grades the **amended** figure and prints where it came from; a row still pending
  is reported **PENDING**, not as an agreement and not as a disagreement.
- **The same defect on the read side, fixed with it.** `venue_deals` filtered the venue's history
  on `magic == ours`, so the packet could not see a close the platform had stamped with magic 0
  and reported *"the ledger recorded a close the account does not hold"* about a close it did.
  Attribution is now by position, and the deals it needed that for are NAMED in the packet
  (`venue_attributed_by_position`) - a widening that keeps its fail-closed direction: a stranger's
  OUT deal is still refused, pinned by a test.
- **The new pin is the general one the defect class deserved**
  (`test_midas_telemetry.test_every_fill_row_format_matches_its_arguments`): every ledger row
  writer's specifier count is compared against its top-level argument count on the source, and
  MQL5's missing-argument text is asserted absent from the code. The grammar pins counted
  specifiers and none of them counted the arguments beside them - a row is written by a format
  **and** an argument list, and only both together are a row.
- **Recompiled, deployed, re-certified - in that order.** `compile_midas.py` **0 errors /
  0 warnings** (`source=011e0ab9 ex5=6748e8bd`), deployed to the live terminal, and the chart
  reloaded onto it: the ledger's own `ERA,MIDAS1.25,...,+fill-price-heal` row proves it.
  `python scripts/midas_parity.py --window tickcov --corpus venue --live-stance` -> **PARITY
  PASS** on **real** ticks: `py 9tr +0.2699R | EA 9tr +0.271R | max|dR| 0.0004`, artifact
  `artifacts/midas_parity_result_20260922_1654.json`. **The trade set is identical to the v1.24
  certificate's**, which is the measurement that v1.25 is fill-row integrity and nothing else -
  a build that could move a trade would have moved one.
- **AND THE OTHER HALF OF THE REQUEST: the account layer is now certified instead of pinned off.**
  Every pass of record pins `InpPropGuard=false`, `InpRiskPercent=1.0`, `InpArmTag=M1` because the
  python engine of record is a BAR model and the governor is an account-level layer it does not
  model - so **nothing** in this harness had ever said anything about the configuration the arm
  runs. `--live-stance` adds a SECOND pass over the same window and tick model whose account layer
  is read from the arm's own preset (one declaration, not a copy: anything it does not declare
  refuses), whose EA runs its LIVE path in the tester (which the EA's own comment says it is
  "deliberately testable" that way - in there the orders hit the simulated account), and whose
  standard is the pinned python mirror `size_like_ea`. Result: **ACCOUNT LAYER PASS** -
  **7 closed fills, every one sized the way the declared rule sizes it at the equity it actually
  had** (lots and the row's own `risk_usd`, which is equity-independent), **5 of 7 floored to the
  venue's min lot** (the quantisation the live arm shows, now on a record), and the configured-risk
  token on each row matching the preset's own percent. One entry of that pass was still open at the
  window's end and is reported **ungraded** rather than dropped.
- **The governor leg is VACUOUS, and it says so in that word.** No modelled rule bound on this
  window: the largest day drawdown was **0.318 % of the 3 % cap**, so the arm was never asked.
  "The governor behaved" and "the governor was never asked" are different claims and only one of
  them is evidence; a window that exercises the cap is what would validate it. NOT modelled, and
  named in the artifact rather than left to inference: the trailing shield floor (needs the
  venue's peak/DD bookkeeping) and intrabar equity excursions. This pass does **not** compare
  trades against the python engine - the live path's fill mechanics are the arm's own, which is
  the divergence the BAR pass documents.
- **The live record's own packet now reads AGREE, and it took all three fixes to get there.**
  `artifacts/live/first_fill_packet.json` on the arm's real fill: `--- position 18874164: AGREE ---`,
  with the venue's deals **attributed by position** (18874164 — the close the magic filter could not
  see), `entry price 4333.07 vs 4333.070000000001 AGREE` carrying the note *"the row itself carries
  0.0: the price was UNRESOLVED at write time and this figure is the LENTRY amendment, line 1,
  source 'entry deal'"*, and `exit price 4328.76 AGREE`. Before this session the same packet read
  `DISAGREE` with a phantom `MISSING_LEDGER_ROW`.
- **And the record was being written by the TEST SUITE, which is its own defect.** Found while
  chasing the above: `record_first_fill` wrote the packet to a **hardcoded**
  `artifacts/live/first_fill_packet.json`, so every test that redirected the capture to a tmp dir
  still dumped its **synthetic** packet into the arm's live record — the file on disk described
  `fill 308417`, a position that never existed, beside the real fill in `first_fill.json`. The
  packet path is now derived from the capture's own location (one location, not two), pinned by a
  test that asserts it follows the redirect.
- **What this still does not change, stated plainly:** the venue's own validation criteria remain
  **FAILED** (pf >= 1.30, expectancy >= +0.15R), the account is still an operator override, and
  `live_readiness` is still **NOT READY** on the two unattended-supervision legs. The parity pass
  certifies engine equivalence; the live-stance pass certifies the account layer; neither is a
  validation.
- **Pins moved with the build, each extended rather than replaced:** the version register
  (`test_ea_version_is_the_r6_build` += v1.25 with its reason), the deployer's accepted ERA stamps
  (`ERA,MIDAS1.25,`), the LOPEN/OPEN specifier and tail-shaped pins (with the measured reason for
  the count in place of the old one), the sanctioned-selector list (the fill-price resolver proves
  magic+symbol before it reads anything), and the history-selection invariant, which was restated
  as **ownership** - an argument is either state we hold or a parameter of a function that proves
  the identity is ours - because two honest callers arrived that the literal `g_lv_posid` pin could
  not describe. Suite: **1472 passed, 10 skipped, 1 failed** (the pre-existing environmental
  `test_forward_cell_prereg`, 661 vs its literal 658, on no changed file's path).

## 2026-09-22 - THE ARM WAS FLAT AND EVERY SAFETY MEASURE WAS FREE: the trigger threshold moves to its measured value (2.0 -> 1.5)

- **The complaint, answered by the arm's own census, not by an opinion.** `NOFILLSUM` for UTC
  day 20718 read `25,4,0,0,0,0,0,21,0`: 25 bars evaluated with no trade, **21 with no trigger at
  all**, 4 with a trigger the mode refused, and **every protective counter at zero** - session,
  Friday, spread, risk-cap, breaker, news. So there was nothing to remove: no measure that
  protects the account had refused anything, and the fill rate was decided by **how often a
  trigger fires**. That is a threshold, not a gate, and it is what moved.
- **The machine's half, already on the record but now measured to the end.** The 04:00-07:15 UTC
  hole cost today **13 of 38 in-session M15 bars** (evaluation stops at server 01:15 and resumes
  mid-session at server 09:15), because the host enters **Modern Standby** on lid close: the
  event log records `Kernel-Power 506 The system is entering Modern Standby` repeatedly, the
  chassis is a convertible (type 31) on a battery, and `powercfg` refuses to even show the lid
  policy without an administrator token - display-off and sleep-after were already `never`, so no
  idle timer was the cause. Nothing was changed here; the honest statement is that this needs a
  VPS or the elevation that was declined.
- **A frame finding, disclosed rather than quietly fixed.** The EA's `InSessionBar()` compares
  `InpSessionStartHour/EndHour` (declared `// UTC`) against `TimeToStruct(iTime(...))`, and every
  MQL5 datetime is **server** time - this venue is +2 (measured from the ledger: a bar opening
  10:00 UTC is stamped 12:00). So the live arm trades UTC **04:00-18:00** while the certified
  window is 06:00-20:00, and `midas_parity.build_inputs` normalises the inputs by the offset so the
  *tester* frame agrees with python. Swept on the venue's own bars the live window is **better in
  both spans**, so it was left alone and written down instead.
- **The measurement** (`scripts/midas_frequency_axes.py`, pre-registered in
  `docs/FREQUENCY_AXES_PREREG_20260922.md` BEFORE it ran, artifact
  `artifacts/midas_frequency_axes_20260922.json`). Certified `midas_sweep.run_mode`, unchanged;
  corpus = the venue's own bars; harness self-check binding: it reproduced the pinned
  `wfv` law n=53 / +14.2563R before printing anything. Held out (`oos` 2026-04-01 -> 09-16, 168 d):
  **k=2.0** 111 fills, 0.66/day, **50.3 % of days flat**, `-0.003R`, pf 0.981, dd 7.6R ->
  **k=1.5** 130 fills, 0.77/day, **40.8 % flat**, `+0.087R`, pf 1.201, dd 6.5R -> k=1.0 140 fills,
  0.83/day, 37.3 % flat, `-0.009R`, pf 0.966, dd 8.9R. The selection span (`wf`) ranks them the same
  way. Min-lot `vetoed` = 0 in every cell.
- **The prior this falsified, recorded because the artifact still says it.** The Sep-18 sweep (the
  **retired** series, a different market) pointed at k=1.0, monotonically, at every RSI band; on
  the venue's own bars **k=1.0 is the worst of the three**. The mechanism is in the source: the
  trigger is `bb_touch` **else** the RSI branch, so narrowing the band *displaces* the RSI trigger
  instead of adding to it.
- **The change.** `gold_preset_upcomers.BB_DEV = 1.5` (with the table beside it),
  `midas_parity.BB_DEV = 1.5` - the EA input and the python leg's trigger array are one contract
  and moved in the same commit - and all three presets regenerated, the M1 control included so the
  family runs one strategy. The watchdog's own drift action spliced it onto the running chart at
  **2026-09-22T13:49:11Z** (`action=DRIFT`, `relaunched=True`); the EA's journal shows
  `trigger=M15 BB(20,2.0` at 13:32 giving way to `trigger=M15 BB(20,1.5` at 14:49/14:52, and the
  identity check that reported `DRIFT` now reports **OK**.
- **What moved because the contract moved** (all re-measured, each with its reason in place):
  `tests/test_midas_minlot_veto.py` wfv **53 -> 56 trades**, +14.2563R -> **+15.9352R**, the
  amendment-6 invariant (the veto never fires there) unchanged; the parity **`veto` window
  re-chosen** 2026-05-11..16 -> **2026-03-15..20**, because at 1.5 the old one refused nothing at
  all and a window that no longer exercises the stand-down is not a veto path - found by sweeping
  every 5-day window of the venue span at its **era's own clock**, with exactly one week surviving;
  and a preset fixture that compared against the literal `"2.0"` now reads the pin's own value.
- **The certificate, at the new threshold.** `python scripts/midas_parity.py --window tickcov`
  (the only window with real ticks, and the only one whose PASS is recordable) returned **PASS**:
  artifact `artifacts/midas_parity_result_20260922_1547.json` (14:47:00Z — the pass of record
  at that moment, because it was the one that ran the build the arm ran, v1.24; SUPERSEDED the
  same day by `..._1654.json` on v1.25, see the entry above), python leg 9 trades /
  **+0.2699R** against the EA's 9 / **+0.271R**, count, open time, close time and side all
  agreeing, `max|dR|` **0.0004**, `tick_model used: real`. The artifact carries the input block the
  pass used, so the threshold it describes is readable from it (`InpBBDev: "1.5"`) rather than
  inferred, and the trade set **moved** (two 2.0-era entries gone, two new ones in) — a changed
  configuration, not a no-op. Recorded in `artifacts/live/armed.json` under `parity_certification`,
  together with the one thing a parity pass structurally cannot say (see the account-layer bullet
  below). Two identical PASSes at **14:02:45Z** (`..._1502.json`) and **14:26:14Z**
  (`..._1526.json`) certify the same contract on v1.23 and are kept, neither counted twice.
- **WHY THREE IDENTICAL PASSES ACROSS TWO BUILDS EXIST, and it is not busywork.** (1) The first pass's
  provenance was broken by this session's own hand: `scripts/midas_parity.py` and
  `scripts/gold_preset_upcomers.py` were edited at **14:14Z**, *after* the 14:02Z pass, so that
  certificate described a tree that no longer existed. I measured the edits inert — the python leg
  re-derived from the current tree reproduces the artifact to the digit (**n=9, +0.2699R**) — but a
  certificate whose validity needs an argument is worth re-earning for four minutes of a flat
  market. (2) **The arm's own first fill had made a fresh pass impossible.** Measured:
  `mt5_ops.ledger_flatness` returned **`flat=False`, `open_positions=[{'ticket': '0', ...}]`** on a
  book whose only live trade was **closed**, and `midas_parity` refuses to stop the terminal over a
  non-flat book — so the certification run was **blocked**, not merely un-run. (3) **The build then
  changed underneath the certificate** (the HUD fix below), so a third pass was run against v1.24 —
  a certificate that does not name the build it ran invites exactly the question it exists to
  answer.
- **The chart was lying about the arm's own trade, and the fix is in the EA (v1.24).** The
  operator's own screenshot after the fill showed `MIDASTOUCH MIDAS1.23 | trades: 0/30 (gate reads
  at n=60) | wins 0 | cumR +0.00` while the ledger held a CLOSED live fill at **+0.104R**. Root
  cause, found by reading the code rather than the symptom: **no live close path incremented a
  counter.** The two *paper* close paths do (`g_cum_r += r; g_trades++`); the live managed-close and
  the live external-close write their `LCLOSE` row and touch nothing else, and the paper counters an
  armed arm can see start at zero on every reload — so on this account the tally could only ever
  read **0/30**. Fixed as a **ledger-backed live census**: one helper counts the ledger's own
  `LCLOSE` rows (the same rows every other reader uses), restored at init and incremented by both
  live close paths, with the tally line naming which record it counts. Two pins added, and the HUD's
  read-only boundary (no file access) kept intact. The governor line likewise stops printing
  `floor $0 | today +0.00 of cap $0` for a state it has not measured and says so instead.
- **v1.24 compiled, deployed and certified, in that order.** `compile_midas.py` **0 errors /
  0 warnings** (source sha `014b980a`, ex5 sha `39b41510`), deployed to the live terminal, and the
  live journal confirms the reload at **14:48:12Z** with `[MIDAS1.24]LIVE CENSUS restored: closed=1
  wins=1 cumR=+0.104 (from 1 LCLOSE row(s) in MIDASTOUCH_paper_XAUUSD_U25.csv)` — the one closed
  fill the ledger holds, restored across a restart instead of reset to zero. The third parity pass
  (`..._1547.json`, PASS, the same nine trades, `max|dR|` 0.0004) then re-earned the certificate on
  that binary; the **unchanged trade set is also the measurable statement that v1.24 is
  telemetry-only** — a HUD that could move a trade would have moved one. `armed.json` now carries a
  `certified_build` naming both hashes.
- **The arming record named the previous build too, and now says so.** `armed.json`'s `config_id` read
  `MIDASTOUCH_v1.23_...` while the chart ran v1.24 — the same defect class as the tally, caught because the
  operator went looking for what else did not match. Renamed to v1.24 with a `config_id_history` giving the
  moment and the reason, and **amendment 4** added to the record (the same place the previous config_id move
  was recorded) carrying the fix, the measurement and what it does not do. Nothing parses that string as a
  version except the `ArmingGate`, which compares it to a validation record an override does not create —
  measured before the rename, so it is a naming fix and not a behaviour change.
- **The documents that described the previous arm, corrected rather than left to age.** `README.md` still
  said **0 opened, 0 closed** and named `MIDAS1.23`; its status table now carries the fill, the parity
  certificate of record and the real refusal census. The health guide's HUD sample was pre-v1.22 in shape
  (no `cfg` on the sizing line, the paper tally, a governor that reads zeros) — updated to what this
  build prints, with the values marked as the arm's own and their source named.
- **Two version-history pins extended for v1.24** — `test_ea_version_is_the_r6_build`'s registered
  list and the deployer verifier's `accepted_era` tuple — each at the point its own comment marks as
  an extension point ("A NEW RELEASE EXTENDS THIS LIST, it does not replace it"). The verifier
  needed it: it would otherwise have refused the very ERA stamp the live ledger now carries
  (`ERA,MIDAS1.24,...`).
- **What is between the arm and its next fill, measured after the reload.** The live census restored
  at 14:48:12Z reads `signal=28 no-trigger=24 mismatch=4` with `session=0 friday=0 spread=0
  riskcap=0 breaker=0 news=0`. **Every safety counter is still zero** — nothing protective has
  refused anything in the arm's whole live record — and the only refusals that exist are the
  confluence rule's, 4 of the 4 signals that fired. The arm is armed, flat, in-session and
  evaluating, so the next qualifying signal fills. What is NOT done is relaxing that rule, which
  would be a strategy change needing a pre-registered study rather than a gate to switch off.
- **THE ARM TRADED.** 2026-09-22 **14:00:00Z**: a live SHORT, 0.01 XAUUSD @ 4333.07, signal bar
  13:45 (the first entry after the threshold went live at 13:49), closed by the venue at
  **14:06:37** for **+$4.31 / +0.104R** — account 1428765 went 25,000 -> **25,004.26**. The ledger
  recorded it (`LOPEN` at 1790092800, `LCLOSE ... EXTERNAL 4328.76000 +0.104`).
- **And the fill immediately exposed FOUR false statements in the record-keeping path, all
  fixed because a record that lies is worse than no record. One rule produced three of them:**
  an `LOPEN` row carries the position id in field 2 — *except at the moment the EA writes it*,
  when on a netting account field 2 is `0` and the **order ticket** (which on netting IS the
  position id) is the only identity the row holds. Field 2 was what every pairing reader read.
  - **`mt5_ops.ledger_flatness`, `midas_watchdog.ledger_health`, `morning_status.parse_ledger`
    and `morning_status.live_grammar_view`** all paired a fill with its close on field 2 alone,
    so the arm's one **closed** fill stayed "open": the operator's own report printed
    `LIVE POSITION: SHORT 0.01 lots @ 0.00 ... open -1.7h` (negative age — the row's epoch is
    SERVER-stamped and the age was taken against UTC) and `1 OPEN rows without CLOSE` sat on the
    problem list, while the venue held **0 positions**. That is also the line that reads
    `ledger_flatness`, i.e. the gate that blocks a certification run. Fixed with ONE rule in one
    place — `mt5_ops.live_fill_key`, keying on the identity the row actually carries, never on
    `0` (which would buy a false MATCH, a live position read as closed — the worse failure), and
    treating a row with no identity at all as unpairable so the verdict stays fail-closed. The
    frame is fixed too: the age is now taken with the persisted broker offset (`server_offset_min`)
    or says `frame unproven`. Pinned by three tests built from the arm's **verbatim** row
    (`LOPEN,1790092800,0,18874164,0,-1,...` + `LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104`)
    including the two directions that matter more than the fix: the same row **without** its close
    must still read as a live position, and a row carrying **no** identifier must not pair with a
    close that also carries none. The suite's old fixtures all used a realistic `posid`, which is
    exactly why four readers could pass while the live book read not-flat.
  - `midas_watchdog.live_fill_reconciliation` keyed a `LOPEN` row on its `posid`/`deal` fields
    only. MEASURED on this fill: both are **0** at write time on a netting account (the EA writes
    the row as the fill is acknowledged; its own journal says the IDs reconcile on the next tick)
    while the venue's `position_id` 18874164 sits in the row's **order** field, which was not
    read. The alarm therefore fired as `ledger-short` — "every R derived from this ledger is
    unverified" — on a fill the ledger had recorded in full, and would have fired on every
    netting fill. Fixed to key on `posid`/`order`/`deal` (and never on `0`, which would buy a
    false MATCH), and the account side now keys on the **position's** identity because the deal
    ticket is a field the row cannot contain at write time.
  - `midas_first_fill_packet.read_live_ledger` had the same defect: reading `posid` alone keyed
    the `LOPEN` under "0" and its **own `LCLOSE`** under "18874164", so the packet reported the
    ledger's close as "the venue holds a fill this ledger never recorded" — a phantom
    `MISSING_LEDGER_ROW` manufactured from the ledger's own two rows.
  - `build_packet` also called the reconciliation **without** the injected reader, so its own
    promise ("Nothing here touches a terminal") was false and `test_no_fills_is_reported_as_nothing_yet`
    passed only while the account happened to hold no deals. It failed the moment the arm traded.
    Both readers now take the injected account, and two regression tests pin the real row's shape.
  - **`morning_status.print_midas_section` had the same hole, one step earlier:** it reconciled the
    ledger against the account with no injectable source, so `test_armed_world_marks_the_live_arm_live_
    and_the_paper_arm_paper` — a test describing a **synthetic** world — depended on whether this
    machine's arm had traded, and went unhealthy the moment it had. Fixed with a seam
    (`LIVE_FILL_DEAL_READER`) and pinned in that test's own world helpers, on the same principle the
    file's `preset_for_tag(armed=...)` already applies to the arming state.
  - The write-once `artifacts/live/first_fill.json` had been written at 14:09:36Z **by the buggy
    keying**, so it said `ledger-short` and lost `first_ledger_row`/`first_account_deal`. The false
    capture is preserved as `first_fill.superseded_20260922T140936Z.json` and the corrected record
    (state `matched`, with the row and the deal) is written beside it, with the supersession
    stated inside the new artifact.
- **Two real gaps the packet now names, NOT fixed here** (both need the EA, and the second is
  about the venue rather than the EA): the `LOPEN` row carries `entry = 0.00000` because it is
  written before the fill price is known, so the ledger cannot say what price the arm actually got
  — the packet reports `entry price: ledger 0.0 vs venue 4333.07`; and this venue's **closing**
  deal carries **magic 0**, so a deal history filtered by our magic holds the entry and not the
  close, which is why the ledger's `+0.104R` cannot be graded against the venue by that filter.
  A third, cosmetic: the row's `cfg=` token ends with a literal `(missed string parameter)` — an
  MQL5 format specifier in `RiskAppend()` with no argument.
- **What this is not.** Not a validation: at `+0.087R` over 130 trades t is about 0.9, the venue's
  own criteria (pf >= 1.30, expectancy >= +0.15R) are still **FAILED**, and the account remains an
  operator override on an unvalidated strategy. It is an ordering between three thresholds that
  held on two spans and one market under a rule written before the numbers existed.
- **The layer a parity pass cannot cover, measured separately.** The harness compares the two
  STRATEGY engines and pins `InpPropGuard=false`, `InpRiskPercent=1.0`, `InpMagic=7801001`,
  `InpArmTag=M1` (readable in the artifact's own input block), because the python engine of record
  does not model the account layer — so no parity pass can ever certify the live arm's 0.25%
  sizing or its governor, and a certificate silent about that reads as if it covered it. Measured
  read-only with `scripts/verify_sizing_live.py` against the live preset and the venue: **legality
  ALLOW** at **0.01 lots risking $39.01 of a $62.51 budget** (0.25% of $25,004.26 equity) —
  **QUANTISED DOWN** by the venue's minimum lot, $23.50 of the budget unexpressible — a measured
  basis of $100.00 per price unit per lot against spec fields implying $10.00 (the venue's 10x
  self-inconsistency, reported not averaged). Exit **4 = LEGAL_BUT_NOT_ARMED**: the *rules* allow
  the trade and the *python-side* gate is OFF because `artifacts/live/validation_record.json` does
  not exist, which is what the override block says it does not create. Both records now sit
  together in `artifacts/live/armed.json`.
- **A fix that only exists is not a fix: the live watchdog was still running the old module.**
  MEASURED: PID 3284 (started 2026-09-21) kept logging `ledgers: [{... "flat": false}]` and
  `live_fills: ledger-short ... account 2 / ledger 1` — the pre-fix verdicts — because python does
  not reload a module under a running process, and `flat=false` is not cosmetic there: it is the
  verdict that makes the watchdog **SKIP** a restart, so a genuinely hung arm would have been left
  hung on a closed trade read as open. It was restarted through its own registered task
  (`MIDAS Watchdog Autostart` -> `start_midas_watchdog.bat`, the documented entry point, seconds of
  gap, instance lock held) and its first pass, **2026-09-22T14:34:26Z**, reads
  `flat: True` and `live_fills: matched / healthy, 1 ledger fill reconciled against 1 account
  identifier`. The same open-position lie is gone from `scripts/morning_status.py`'s own output:
  `[3b]` now prints `live: flat` where it printed `LIVE POSITION: SHORT ... open -1.7h`.
- Suite after the pass and these fixes: **1451 passed, 10 skipped, 1 failed** - the failure is the
  pre-existing environmental `test_forward_cell_prereg` (661 against its literal 658), on no
  changed file's path. The two version-history pins above failed until they were extended for
  v1.24, which is what those pins are for.

## 2026-09-22 - THE SUPERVISOR NEVER RAN AT NIGHT: it is now unattended, host-checked, and every night is measured

- **The complaint, measured from the supervisor's own log** (`artifacts/live/supervisor.log`,
  2026-09-21 11:32Z -> 2026-09-22 13:00Z, 26.0 h): **55 passes recorded where a 20-minute
  cadence owes 78**, coverage **69.7 %** (473.1 min unattended beyond one cadence), **zero
  passes in the 01:00-06:00 UTC hours**, 4 gaps over threshold with the longest **282.8 min**,
  and 2 passes that began and never completed. The night window alone (22:00Z -> 08:00Z):
  **10 passes / 30 due, 30.8 % coverage, 415.4 min unattended, longest gap 282.8 min**.
  Reproduce: `python scripts/live_coverage.py` (last night) or `--hours 24 --json`.
- **Root cause 1, the task's principal.** `python scripts/unattended.py` read the task's own
  exported XML: `logon=InteractiveToken`, no BootTrigger, `wake-to-run=off` - so it ran
  **only while a user was signed in**, and the arm's market hours are exactly the hours
  nobody is. The task was `Ready` the whole time, with a recent LastRunTime. A registered
  task with the wrong principal is not supervision.
- **Root cause 2, the host.** `python scripts/host_power.py`: the only standby state is
  `S0 Low Power Idle Network Connected` (no S3), `Allow wake timers = Disable` on AC, and
  the lid-close action is **not exposed by powercfg** on this build. `Sleep after = never`
  was already true and did not prevent the hole - that is the finding worth keeping, because
  checking the idle timer proves nothing on a Modern-Standby machine.
- **What was built.** `scripts/unattended.py` (LogonType + BootTrigger + WakeToRun from the
  scheduler's own XML; "not registered" and "could not ask" kept distinct),
  `scripts/host_power.py` (read-only powercfg audit, prints the elevated fixes, runs none),
  `scripts/live_coverage.py` (one heartbeat line per pass, two alarm kinds, the window rule),
  and `scripts/install_paper_task.ps1` now registers **`MIDASTOUCH Arm Supervisor`** -
  S4U principal, at-startup trigger, 20-min repetition, **WakeToRun**, no execution time
  limit, `IgnoreNew` - and removes the legacy interactive `MitemshubPaperSupervisor` only
  AFTER the replacement is registered. The name is deliberate: the supervisor is scoped to
  the ARM (`preset_for_tag(tag, armed=True)`), not to a paper run.
- **A bug in the measurement harness itself, found and fixed the same hour.** The first
  `live_coverage._epoch` fed the log's naive `2026-09-22T07:27:46` into
  `datetime.astimezone()`, which reads a naive stamp as LOCAL time - on this host (UTC+1)
  every summary line moved an hour earlier and the night reported **14 passes / 42 %** where
  it was **10 / 30.8 %**. A harness that flatters the thing it measures is worse than none;
  `tests/test_live_coverage.py` now pins a naive `...Z` stamp to UTC regardless of the host's
  zone.
- **The alarm fires on the real hole, not a synthetic one.** Feeding `record_pass` the actual
  last pass before the gap (00:40:24Z) and the actual first pass after it (07:27:46Z) raises
  `supervision-gap` at **407.4 min** (episode-keyed, one `alerts.log` line, deduped), with a
  `why` that names `unattended.py` and `host_power.py`. A stale ledger AT a pass that ran is
  the other kind (`ledger-heartbeat-gap`) because its remedy is the watchdog's, not the
  schedule's.
- **Four readiness legs replace one.** `scheduled task target`, `supervisor runs unattended`,
  `host can hold supervision overnight` and `no unacknowledged heartbeat gap`; the middle two
  **block**, and this machine now reads **VERDICT: NOT READY** with exactly those two - the
  honest reading of "the arm exists ~5 hours a day". Before 2026-09-22 only the first existed
  and it passed while the arm was unguarded for 407 minutes.
- **PRE-REGISTERED, before any post-fix night exists** (`docs/UNATTENDED_OPERATION_20260922.md`
  §2, printed as data by `live_coverage.py --prereg`): a window PASSES iff no interval between
  recorded passes exceeds **40 min** (2 x cadence) and no observed ledger heartbeat age
  exceeds **35 min** (`midas_watchdog.STALE_MIN`, pinned equal by test). The numbers above are
  labelled a **BASELINE**, not a test of that rule.
- **THE HOST WAS FIXED, AND RE-MEASURED.** Wake timers were `Disable` on AC and are now
  **`Enable`** (measured: `RTCWAKE` AC `0x0` -> `0x1`), plus `STANDBYIDLE 0`, `HIBERNATEIDLE 0`
  and `LIDACTION 0` (the last set BLIND: it cannot be read back through `powercfg -query` on
  this build, and that is stated rather than presented as a verified fix). No elevation turned
  out to be needed for `powercfg`. The host verdict moved **FAIL -> WARN/unverified**: nothing
  measured is wrong any more, and nothing in `powercfg` can certify that a wake timer actually
  wakes an S0 host. Only a measured night can, which is why it is WARN and not PASS.
- **Two defects the installer itself shipped, both found by running it.** (1) On this build the
  ScheduledTasks cmdlets **cannot express `WakeToRun` at all** - the trigger objects expose
  only {Enabled, EndBoundary, ExecutionTimeLimit, Id, Repetition, StartBoundary, RandomDelay}
  - so the first version's `$trigger.WakeToRun = $true` threw non-terminatingly, was swallowed,
  and the script printed **"Registered. Current state:"** over a task it had never created. The
  registration is now written as the Task Scheduler's own **XML** (the artifact
  `unattended.py` reads back), the task is **read back and success is refused** if it is not
  there, and a scheduler that refuses the wake flag falls back to the cmdlet path while
  **saying the leg is missing**. (2) A `<WakeToRun>` child of `<TimeTrigger>` is rejected
  outright ("The task XML contains an unexpected node"); it belongs in `<Settings>`, where a
  real wake-to-run task carries it. S4U registration **does** need elevation (measured:
  `Access is denied`, `0x80070005`).
- **NOT DONE, NOT CLAIMED.** No VPS has been provisioned, and **no post-fix night has been
  measured** - `live_coverage.py` returning PASS over 22:00Z -> 08:00Z is the claim and it has
  not been observed. The replacement task is **NOT registered**: the elevation prompt was
  declined, so nothing on the machine changed and the legacy interactive supervisor is still
  the only one. The coverage record is nonetheless **live** - the running supervisor wrote its
  first heartbeat at 13:12:20Z, and over an awake window the harness reports **9 passes / 9
  due, 100.0 % coverage, longest gap 20.0 min, PASS** (a measurement of the cadence, not of
  unattended survival). An Interactive task can demonstrably stop and relaunch the MT5 GUI;
  whether an S4U task can is **unverified**, so switching this live-armed arm's only recovery
  path stays the operator's call: `install_paper_task.ps1 -Apply -KeepLegacy` (elevated), then
  `Start-ScheduledTask` + a fresh line in `supervision_heartbeat.jsonl` to confirm.
- **The arm is not short of permission to trade.** Its own `NOFILLSUM` census for the UTC day
  reads **23 bars evaluated, 19 with NO trigger at all, 4 with a trigger the mode refused** -
  the binding constraint is the trigger's own frequency, not a safety gate. The machine's
  contribution is the other half: the 00:40Z -> 07:27Z hole covers **04:00Z -> 07:27Z of the
  arm's own 04:00-18:00 UTC session**, roughly a quarter of every trading day in which the
  strategy cannot be asked anything. No gate was relaxed to manufacture a fill.
- **Counts.** Suite **1444 passed, 10 skipped, 1 failed** - the failure is the pre-existing
  environmental `test_forward_cell_prereg.py::test_the_forward_mask_reproduces_the_studys_own_cell`
  (661 vs the study's literal 658); no file in this change is on that path. Live import
  closure **31 (23 entry points)**, **0 dangling**. **42 new tests**: `test_live_coverage.py`
  (20), `test_host_power.py` (8), `test_unattended.py` (8), `test_paper_supervisor.py` (+6),
  against the 1402 the suite held before this change.

## 2026-09-22 — the arm is aligned to the mode the gate certifies, and the census refuted the request to remove safety gates

- **The request.** "I don't like the fact that you are not trading yet … either you reduce
  them or remove some and use the best." So the first thing measured was not a gate but the
  refusal census, because "which measure is blocking you" has a countable answer.
- **The census, from the arm's own record.** Across the whole live record (2026-09-21 20:00
  UTC onward) the restart-persistent counters read `session=0 friday=0 spread=0 riskcap=0
  breaker=0 news=0`. Every refusal that existed came from ONE measure: ORIGINAL's requirement
  that the H1/H4 regime agree with the M15 trigger. Read from the ledger's own `STATE` rows,
  **all 3 of the 31 evaluated bars that carried a trigger at all** (each `mac=-1, trig=+1`)
  died there. Widening the session window, cutting the spread cap or switching the prop
  governor off would have produced **exactly zero** extra trades. None of them was touched.
- **What changed: `InpMode` 0 → 1** (ORIGINAL → REVERSE_DIRECTION) in both Upcomers presets,
  pinned as `MODE` in `scripts/gold_preset_upcomers.py`. This is *configuration integrity*,
  not a claim that mode 1 is the better mode: every parity window and the walk-forward gate
  describe mode 1 (the 2026-09-21 12:18 parity PASS is a REVERSE_DIRECTION pass), so mode 0
  meant no parity run and no gate verdict spoke about the live configuration *in either
  direction*. The sweep says both are NO-SHIP, ORIGINAL is ahead in is1/is2/wf, and mode 1 is
  ahead only in the out-of-sample window (n=108 +0.0759R pf 1.158 maxDD 5.41R against n=94
  +0.0697R pf 1.141 maxDD 6.87R, +8.199R against +6.555R total, 15% more fills). The whole
  table is in the preset header and in the arming-record amendment.
- **It went live through the mechanism that exists for it.** The repo pin moved, and the
  watchdog's own drift action respliced the staged `MQL5\Presets\…_LIVE.set` and relaunched
  the terminal at 12:28:47Z; the EA's journal confirms `MIDASTOUCH started | mode=1` at
  12:28:57Z, and `morning_status` now reports `preset: OK (44 inputs byte-identical to repo
  .set)` where it had reported `PROBLEM: preset DRIFT: InpMode=0 (repo pin 1)`.
- **The arming record was amended, not edited** (`artifacts/live/armed.json`, gitignored):
  `config_id` → `MIDASTOUCH_v1.23_XAUUSD_M15_MODE_REVERSE_DIRECTION_U25`, a dated amendment
  stating what it does NOT do (the gate FAILED mode 1 itself — V2 12/30, V3, V5 −0.7173R,
  V6 +0.5243 — so this is still an override on a FAILED gate), and the old
  `armed_configuration_was_never_the_gated_one` block replaced by
  `armed_configuration_and_the_gate`, which keeps the prior text under
  `prior_state_2026_09_21` rather than deleting it. The record now also discloses
  `gate_family_mismatch` (the cited artifact measures `ema_stack_trigger`; the EA implements
  `bb_rsi_trigger`; they agree on 3.4% of signals), which is what `live_readiness` asks for:
  its verdict moved from **NOT READY / blocking: evidence describes this strategy** to
  **AUTHORISED BY OPERATOR OVERRIDE — TRADING, NOT VALIDATED**, by disclosure rather than by
  relaxing the check.
- **A false label on the session window, fixed.** The HUD and `morning_status` both called
  the window "06-20 UTC" while the gate classifies *bar epochs*, i.e. broker-server hours —
  on this venue (UTC+2) that is 04:00-18:00 UTC, two hours of the operator's day at each end.
  `morning_status` now reads the hours from the preset and says `SERVER … NOT UTC`; the HUD's
  own string still says UTC and needs an EA-side change to carry a version bump, so it is
  queued with the next EA edit rather than forced into a live restart.
- **Measured, not assumed: the real blocker is uptime.** The arm evaluated 31 bars where an
  awake terminal would have evaluated ~66: the machine slept from ~01:40 to ~06:22 UTC
  (`Sleep after=never` on AC, so this is session/lid-class, not the idle timer), the terminal
  then spent ~2h failing to reconnect, and 10 of the 31 evaluated bars were outside the
  session window entirely. No gate change can trade bars that were never evaluated.
- **INCIDENT, on the record, with the EA's own banner as the evidence.** `execution=` in the
  INIT banner reads LIVE at 12:20:20Z, **PAPER at 12:28:57Z**, LIVE again at 12:32:32Z. So
  for 3m35s the arm was running with the real-order switch OFF while the ledger, the
  heartbeats and `STATE` rows all looked perfectly alive — the exact "looks like a quiet
  market" failure mode this program keeps paying for. The 12:28:47Z watchdog pass is what
  put it there: its drift remedy (triggered by the mode pin moving) wrote a preset with
  `InpLiveExecution=false` into the staged `..._LIVE.set`, and the next pass found
  `chart InpLiveExecution=false (repo pin true)` and repaired it. The same class is already
  documented inside `resplice_pins` from 2026-09-21 17:52 ("resolved by writing the paper
  preset into `..._LIVE.set` (4564 bytes, paper header)"). I could NOT attribute the 12:28Z
  write to anything I ran — my staging wrote the LIVE pin, and `preset_for_tag(tag,
  armed=True)` resolves to the LIVE pin — and another process is editing this checkout
  concurrently, so the mechanism is NOT yet established. What matters until it is:
  `execution=` is the only signal that distinguishes "armed" from "alive".

## 2026-09-22 (v1.23) — the venue's self-inconsistency printed once, recorded always

- **The complaint, measured in the journal.** `TICK VALUE MISMATCH broker tv/ts=10.00 vs
  settled 100.00 …` appeared at 09:45, 10:01, 10:16, 10:31, 10:46, 11:01, 11:16, 11:30 and
  11:31 on 2026-09-22 — the same two static numbers. Root cause, read from the call graph:
  `DollarPerUnitPerLot()` printed on every call, and the 15-minute heartbeat calls it twice
  (`StateRowWrite` + `HudUpdate`), every evaluated bar calls it again, and the sizing sites
  add one per attempt. A fact that never changes was the loudest line in the journal, and
  the `VETO`/`NOFILL` refusals it protects were underneath it.
- **Print once per session, or on change.** `SpecMoved()` now gates the line: the first
  observation of the EA session returns true; afterwards either number must move past a
  0.5% relative band. A re-print names what it was (`TICK VALUE MISMATCH CHANGED: …
  was tv/ts=… vs settled …`), because "it changed" is itself evidence. The first line of a
  session is byte-identical to the v1.22 text, so nothing that greps the journal breaks.
- **The record replaces the repetition.** The same two moments append a `SPEC` row with
  KEYED fields — `SPEC,<utc epoch>,tv=…,ts=…,cs=…,broker=…,settled=…,used=…,ratio=…` —
  written through `PaperLog`, gated out of the tester and the BAR replay exactly like
  `STATE`, and carrying `+spec-record` in the ERA note. Keyed rather than positional for
  the NOFILL reason (2026-09-21): a reader whose column order disagrees with the writer
  mislabels every field after the divergence, invisibly. `morning_status.spec_last` /
  `spec_text` read it back and render it under the arm view, and the new row is invisible
  to every existing parser (`parse_ledger` and friends ignore unknown prefixes — pinned).
- **Deployed and proved on the live arm.** EA compiles 0 errors / 0 warnings (134,382B),
  `source=a6ce588b ex5=fb7f8db5`, copied to both attachable paths, and reloaded while FLAT
  at 12:20:20 local through the registered stop→relaunch. The journal now shows exactly
  ONE mismatch line for the session; the ERA row is
  `ERA,MIDAS1.23,1790083220,pertick-fills+telemetry-only-per-V2-register+diag-nofill+p6-entrytf+diag-census+state-view+cfg-risk+spec-record`;
  the row landed as
  `SPEC,1790076020,tv=0.10000,ts=0.01000,cs=100.00,broker=10.00,settled=100.0000,used=100.0000,ratio=0.1000`;
  and `morning_status` renders `venue spec (ledger SPEC, written 09-22 11:20 UTC): broker
  tv/ts=10.00 vs order_calc_profit 100.00 per price unit (ratio 0.10) — venue spec
  self-inconsistent; sized on the settled value`.
- **One caveat on the ledger, stated rather than hidden.** The ledger also carries
  `ERA,MIDAS1.23,…,+spec-tv-mismatch` from an earlier v1.23 build that ran 11:43–12:20
  local before this one; the deployer's accepted-stamp list is extended, never replaced,
  and this entry describes `+spec-record` — the build now deployed. Two builds, two tags,
  told apart by the ERA row exactly as the v1.20 lesson requires.
- **Pins, proved both ways.** `tests/test_spec_warn_dedupe.py` (9 tests): the gate sits
  between caller and print, the record lands at the print (not on a clock — `OnTimer`
  carries no writer), the row stays keyed with only the epoch positional, the reader
  round-trips and ignores partial rows, and the ERA note cites the change. Restoring the
  defect (a bare print, no `SpecRecord`) fails 2 of them; restored, 9 pass. Suite **1402
  passed, 10 skipped, 1 failed** — the failure is
  `test_forward_cell_prereg.py::test_the_forward_mask_reproduces_the_studys_own_cell`,
  environmental as before: the venue's history has advanced and the recomputed frozen cell
  is 660 against the study's literal 658. No file in this change is on that path.
- Registered never-abort history extended to v1.23 (`test_midas_r6_preconditions`), and the
  deployer's `accepted_era` admits `ERA,MIDAS1.23,`. `README` names MIDAS1.23.

## 2026-09-22 — the fill row now says what the arm was *told* to risk, not just what it got

- **The gap existed only outside the journal.** A fill row carried one risk number: the
  dollars actually put at stake, derived from the lot size the venue allowed. The arm's
  *configured* risk (`InpRiskPercent` of the very equity base the sizing divided) is a
  different number whenever the venue's lot step cannot express it — and the previous
  turn's own `verify_sizing_live` work found that state is the standing one on this
  account. Reading the journal alone, a min-lot fill and a correctly-sized fill looked
  identical; the gap was recoverable only by running a verification tool against a preset
  the ledger does not name.
- **`cfg=<usd>@<pct>`, appended last on every fill row and on the STATE row (v1.22).** One
  KEYED field rather than two positional ones, and that is a correctness choice, not style:
  the v1.19e state stamp is 0 fields (label off, or a tester row) or exactly 5, so "the next
  two fields" cannot be told apart from a half-written stamp. `cfg=` can never be mistaken
  for one. It rides all three fill writers the same way the state stamp does — BAR `OPEN`,
  PERTICK `OPEN` and the LIVE `LOPEN` — and, again like it, **no tester row carries it**, so
  the certified parity ledgers stay byte-identical by construction.
- **It is on the STATE row too, which is what makes it visible before the first fill.** The
  panel's view already carries the prospective size (`lots`, `risk`); appending the token
  there means the configured-vs-allowed gap is answerable from the journal on the next
  evaluated bar, not only once a fill happens. `ConfiguredRiskUsd()` is the single definition
  behind the HUD line, the STATE row and the fill rows, so the three cannot disagree about
  what was asked for; the HUD's SIZING line now reads
  `0.02 lots, risk $62.24 of $62.50 configured (0.25%) QUANTISED DOWN on 2.0xATR(H1)=$31.12`.
- **The stamp describes the row's own risk basis.** `PaperEquity()` on the two paper paths,
  account equity on the live one — the same quantity each path's sizing already divided — so
  `cfg` and the row's `risk` field are always two numbers off one basis, never two bases.
  No new arithmetic: the value passed is the `risk_d` those paths already computed.
- **Readers, because a number nobody parses is not visible.** `midas_first_fills_audit.py`
  (the wire-contract owner) gained `read_risk_tail` / `RISK_PREFIX` and now prints a `risk:`
  disclosure per closed trade plus a `risk basis:` summary naming how many fills were
  quantised down or oversized; `morning_status.live_grammar_view` renders it under a live
  `LOPEN`. Both take the token off the END, so neither has to know whether the state stamp
  is on. A pre-v1.22 row is unstamped, not malformed.
- **Disclosure, never a rule.** Whether the venue's granularity can express the arm's budget
  is a property of the venue, not something the arm can breach, so the audit reports the
  numbers and grades nothing on them. The bound that refuses a trade is unchanged:
  `InpMaxRiskPct` (amendment 6), veto on all three sizing sites.
- **Pins, strengthened rather than relaxed.** `tests/test_state_label_contract.py` now counts
  on the concatenation `StateAppend() + RiskAppend(` (the old `, StateAppend()` pin read 0
  the moment the append moved onto its own line — a pin that a whitespace change could
  disarm) and pins `RiskAppend` itself: tester-gated, carrying `InpRiskPercent`, and NOT
  gated on `InpRecordStateLabel`. `test_midas_golive_grammar` pins the LOPEN writer at 16
  specifiers with the tail `state,cfg`.
- **Measured, on the live arm.** EA compiles 0 errors / 0 warnings (133870B), the deployed
  binary matches its source, the arm was reloaded while FLAT and its ERA row is now
  `ERA,MIDAS1.22,...,+state-view+cfg-risk`. The very next evaluated bar wrote the token to
  the live ledger:
  `STATE,1790064000,1790070300,-1,-1,-1,1,2377,1,2,6224,0.00,250.00,23500.00,cfg=62.50@0.25`,
  and `morning_status` renders it as `0.02 lots risk $62.24 of $62.50 configured (0.25%)
  QUANTISED DOWN`. **No FILL row carries it yet** — the arm has still never filled, so for
  the fill writers the proof remains the compile plus the pinned grammar; the readers were
  also exercised on a crafted `OPEN` row (state tail parses unchanged beside the token, and
  `risk note: configured $62.50 (0.25% of the row's own risk basis) | took $10.00 |
  QUANTISED DOWN (-52.50)`).
- **Suite: 1393 passed, 10 skipped, 1 failed.** The failure is
  `test_forward_cell_prereg.py::test_the_forward_mask_reproduces_the_studys_own_cell` and it
  is environmental, not this change: the venue history's window end has advanced to
  2026-09-22 09:30 while the research calendar copy is 25.8h old, and the engine's own
  freshness rule is 24h — measured directly as `the calendar is unusable at the window end:
  calendar stale (25.8h old > 24h)`. No file in this change is on that code path. The LIVE
  calendar is separate and fresh (the EA refreshed it at 08:27). Surface audit unchanged:
  closure 27 (22 entry points), residue 56, **dangling none**.

## 2026-09-21 — the tool printed one size where the account has two

- **The number that will be sent was missing.** `verify_sizing_live.py` sized to the
  venue's daily loss limit and printed that single figure. On the U25 arm that is **0.11
  lots / $350.24**; the EA sizes `InpRiskPercent` of equity, which is **0.01 lots /
  $31.84**. One unlabelled number, read as the other.
- **Both sizes now print, labelled.** `size (this tool)` and `size (the ARM)`, the latter
  read from the preset the **arming record names** (`artifacts/live/armed.json` →
  `MidastouchAI_upcomers_gold_LIVE.set`; `--preset` overrides) and computed by
  `EaSizing` / `size_like_ea`, a step-for-step mirror of the EA's own `LiveSendOrder`.
  With no arming record the line reads `UNAVAILABLE` and names what would be needed —
  the paper preset is deliberately *not* a fallback, since it answers a question about a
  different configuration.
- **The mirror is pinned against the MQL5, not trusted.** `tests/test_ea_sizing_mirror.py`
  extracts the bodies of `LiveSendOrder`, `OpenPaperPosition` and `BarFillAndManage` from
  `MidastouchAI.mq5` and asserts every arithmetic step is still there, that all three
  sites still carry the amendment-6 veto, and that no fourth sizing site has appeared.
- **A state the EA's own log cannot express turned up while pinning it.** The EA's
  `FLOORED` flag marks only the min-lot branch, so it is silent on the case that is
  actually happening on this account: the 0.25% budget is **$62.50**, the venue's 0.01
  step yields **$31.84**, and the arm trades **half its configured risk** with nothing in
  the journal saying so. `EaSizing.quantised_down` derives that from the numbers and now
  prints `$30.66 of it unspent`. Its mirror image, `over_budget`, covers the small arm
  where the venue minimum forces *more* than `InpRiskPercent` (a $3,000 arm risks 4.25x
  its configured budget at this stop width).
- **Measured live:** `size (the ARM) 0.01 lots risk $31.84 budget $62.50 (preset
  MidastouchAI_upcomers_gold_LIVE.set, named by artifacts\live\armed.json)`, beside
  `size (this tool) 0.11 lots risk $350.24`. Suite **1392 passed, 10 skipped**
  (24 + 14 tests across the two files); surface audit unchanged at closure 27
  (22 entry points), residue 56, **dangling none**.

## 2026-09-21 — `BLOCK` was two different facts wearing one word

- **The complaint, reproduced.** `scripts/verify_sizing_live.py` printed `BLOCK` beside
  `$0.00 allowance` on a funded account whose only conditions were *no profit yet* and *an
  arming switch that is off*. Nothing had blocked anything, and both readings were this
  repository's own reporting rather than the venue's or the EA's behaviour.
- **`$0.00` meant two opposite things, and now it says which.** The Best Day allowance is
  zero when today's ceiling is REACHED (a refusal) and zero when no profit is banked yet
  (the share is undefined at zero, and the rule binds on the first profitable *close*, never
  on an entry). `TradeDecision` now carries `best_day_basis` (`BEST_DAY_NO_PROFIT_YET` /
  `BEST_DAY_CAP_REACHED` / `BEST_DAY_HEADROOM`) and `best_day_note`, so no renderer infers a
  refusal from a number, and the tool's line reads
  `remaining allowance $0.00 — NOT a refusal: no profit is banked yet, …`.
- **Legality and arming are two labelled verdicts, never one word.** The arming switch was
  being passed into `evaluate_trade`, so an unarmed-but-legal configuration reported
  `BLOCKED`. The rules now answer `legality`; the arming record answers `arming switch`; and
  the exit codes keep them apart — **1** = the rules refuse, **4** = legal but not armed, so a
  pipeline can no longer read "the switch is off" as "the venue would refuse".
- **`explain()` names its block codes** (`BLOCK (not_armed)`) instead of the bare word, which
  is what let the Best Day line three lines above it be read as the cause.
- **Pinned.** `tests/test_verify_sizing_live_reporting.py` (12 tests, pure — no terminal, no
  network) asserts a legal unarmed verdict contains no `BLOCK` at all, that a zero allowance
  never renders unqualified, that a reached cap *is* labelled a refusal, and — by `ast`, not
  text — that `evaluate_trade` is never handed an arming decision in this tool.
- **Measured live:** `VERDICT: LEGAL_BUT_NOT_ARMED (4) — NOTHING refuses this trade; the
  arming switch is what is off`, with `legality ALLOW` and `arming switch OFF` on their own
  lines. Suite **1366 passed, 10 skipped**.

## 2026-09-21 — the order path is a gate now, not a paragraph in a changelog

- **The hand proof from earlier today became routine.** The arm's ability to place an order was
  established once, by hand: a min-lot XAUUSD request the venue priced and accepted (retcode 0,
  $241.76 of margin), and a filling-mode question settled by reading the installed `Trade.mqh`
  (`FillingCheck` rewrites CTrade's FOK default to whatever the symbol lists — here IOC only).
  True, and checked by nothing that runs on a schedule, so "does it work" depended on someone
  remembering how it was done. `live_readiness` now carries two legs:
  `symbol filling mode is usable` and `order path accept-check (min lot, nothing sent)`.
- **Three answers, not two, because two of them get conflated.** A venue that ACCEPTS the
  request passes; one that REFUSES its shape (wrong filling mode, bad volume, bad stops) blocks
  and names the retcode; one that cannot be asked (market closed, trading disabled) reports
  **UNCONFIRMED**, which renders WARN and does not block. An unasked question is not an answer,
  and the leg says so in those words rather than rounding to green.
- **Read-only by construction, and pinned that way.** `order_check` prices and margins the
  request on the server and sends nothing; a source pin parses the module with `ast` and asserts
  there is no `order_send` anywhere in it. That pin immediately caught its own first version
  tripping over the word inside the docstring explaining the rule — prose must not be able to
  satisfy or violate a code pin, so the pin strips docstrings rather than matching text.
- **Measured live:** `[PASS] symbol filling mode is usable — IOC only; CTrade resolves to IOC`
  and `[PASS] order path accept-check (min lot, nothing sent) — venue ACCEPTED a 0.01-lot buy,
  stop $31.17 (2xATR) — nothing was sent`. (The margin the check returns moves with the
  price, so it is printed but not asserted; the retcode is the claim.) The verdict is unchanged
  (`NOT READY`, blocking: the cited evidence describes a different strategy), and the surface
  audit is unchanged: closure 27 (22 entry points), residue 56, **dangling none**.
  Suite **1354 passed, 10 skipped**.

## 2026-09-21 (v1.21) — the chart now says what the engine sees, and the record keeps it

- **The complaint, confirmed against the source.** The HUD said the arm was alive and nothing
  about its view: no regime, no trigger state, no sizing, no governor reading. Worse, the only
  place the macro direction appeared was inside a veto label (`last: VETO NO-TRIGGER(mac=-1)`) —
  a bare integer, read as such.
- **Six display lines, built from the decision's own values.** `REGIME` names the direction
  rather than numbering it (`H4 down / H1 down -> BEARISH (macro -1)`) using the **same two
  booleans that decide entries**, stashed inside `MacroState()` so the chart cannot say BULLISH
  while the engine refuses a long. `TRIGGER` shows the closed bar's trigger plus the RSI that
  answers "how close was it". `GATES` shows the session verdict and the live spread against the
  1.5%-of-stop cap. `SIZING` shows the lots and the dollar risk it would take now, flagging
  `[MIN-LOT EXCEEDS BUDGET -> risk-cap veto]` when the venue's floor is bigger than the budget.
  `GOVERNOR` shows the shield floor, today's P&L against the Best Day cap, and the block reason.
  `NEWS` reports the stand-down switch.
- **A `Comment()` is not a record, so the same numbers are a ledger row.** `STATE` is appended
  per evaluated bar and on the heartbeat, and `morning_status` renders it from the file — "why
  didn't it trade at 14:15" is answerable tomorrow without the chart. Gated out of the tester
  and the BAR replay, so certified parity ledgers stay byte-identical; the ERA note carries
  `+state-view` (v1.21 accepted by the deployer, list extended as always).
- **The row has two clocks and they are labelled, not blended.** Its own timestamp is UTC; the
  bar epoch it carries is server-stamped like every bar epoch here. The first live row exposed
  exactly that trap in the reader I had just written (`20:00` UTC written for a bar stamped
  `21:45` server), which is why the report prints both, labelled, instead of converting.
- **The session rule is now defined once**, in `InSessionBar()`, used by the live gate and the
  HUD alike; the BAR-replay gate keeps its own frozen comparison and a test asserts *that*
  difference explicitly, so adopting the shared rule in BAR mode is a deliberate parity
  decision rather than a silent refactor. Display helpers are pinned read-only: no view function
  may assign to engine state.
- **Live, verified.** `MIDAS1.21` deployed to both copies (0 errors / 0 warnings), arm reloaded
  at a flat, out-of-session moment, census restored across it (`signal=7 no-trigger=7`), ERA row
  `+state-view`, and the first `STATE` row landed as written:
  `STATE,1790020800,1790027100,-1,-1,-1,0,4644,0,1,3252,0.00,250.00,23500.00`
  — BEARISH (H4 and H1 both down), no trigger, RSI 46.4, inside session, 0.01 lots risking
  $32.52. Suite **1339 passed, 10 skipped**.

## 2026-09-21 (later) — the reversal hint, tested where it had not already been seen

- **A hypothesis generated by consumed data cannot be tested on it.** The momentum study's
  +120 era read net −0.0210R/day (t −2.00), which invites "trade the other way". Pre-registered
  in `docs/GOLD_REVERSAL_INTO_CLOSE_PROTOCOL.md` before measuring, with two things said up
  front: the 147 consumed days are **refused as evidence** (a second look with the sign flipped),
  and **cost is paid in both directions** — reversing flips gross (−0.0128 → +0.0128) and leaves
  the 0.0082R toll, so the hint is **+0.0046R/day**, not +0.021R/day. Required sample declared
  first: ≈4,800 days for that effect, ≈650 for 0.02R/day, ≈22 for what the available slice can
  see (0.1088R/day).
- **The unconsumed slice is 32 days, and the study reports what it really is.** Measured: 22
  primary (day-anchor present, venue's close earlier), 9 auxiliary (descriptive, anchors move),
  1 dropped (2026-01-12, 39 bars). Of the 22, **15 are the US-DST-only window** (Mar 9–27, when
  US and EU DST do not cancel and the venue's close is stamped an hour earlier) and 7 are
  genuine holiday early closes — the protocol called them all "early closes" and that is
  corrected in the verdict.
- **Result: UNDECIDED AT THIS N, leaning against the hypothesis.** Primary n=22: gross
  −0.0157R, cost 0.0067R, net **−0.0224R/day** (t −0.58), MDE 0.1088; the declared regression
  wants b < 0 and gave **b = +0.0107 (t +0.34)**. Auxiliary n=9: −0.0125R (t −0.33). Disclosed:
  the mirror (momentum) direction on the same 22 days nets +0.0090R (t +0.23), descriptive only;
  and the pooled mean's sign flips to +0.0045R without the single day 2026-01-27 (−0.5856R), so
  the estimate is one day's story. At 12,300 days for the cost-inclusive hint, no extension of
  this history can decide it — the forward sample (`--forward`, from 2026-09-21) is the only
  un-consumed direction, and it decides nothing early.
- **Pins:** `tests/test_gold_reversal_into_close.py` (18) — including the structural guard that
  the primary and auxiliary samples are **disjoint from the consumed days**, the declared
  selector recomputed from the bars, and the artifact's verdict recomputed from its own rows.
  Suite: **1330 passed, 10 skipped**. Nothing here touches a preset, an input or the arm.

## 2026-09-21 (night) — a reader that refuses, and the first literature candidate measured

- **SSRN refuses automated clients by policy, so the tool records it and stops.**
  `papers.ssrn.com/robots.txt` answers HTTP 403 with "We have detected that you may be using an
  automated script or search engine our site does not support" — a stated policy, not a puzzle.
  `scripts/research_fetch.py` reads robots.txt with longest-match/Allow-wins precedence, refuses
  any page carrying a block-page or login-wall marker, sleeps between requests, caps a run at
  eight URLs, and never retries a block differently. Playwright is behind the live transport,
  imported lazily, so the suite needs no browser. The same literature was reached over routes
  that permit fetching (author-hosted PDFs, NBER).
- **`docs/GOLD_LITERATURE_REVIEW_20260921.md`** records what each paper claims, what it implies
  here, and which claims this venue's data can settle. The gold-specific finding (Iwatsubo,
  Watkins & Xu) is that New York is as liquid or more liquid than Tokyo in gold and the NY day
  session is informed-trading dominated; Ito & Hashimoto give the cost side (spreads widen as
  activity and volatility fall).
- **The one candidate the literature most directly supports was pre-registered and measured**
  (`docs/GOLD_INTRADAY_MOMENTUM_PROTOCOL.md`, then `..._VERDICT_20260921.md`): the paper's
  "last 30 minutes before the close" maps onto this venue as stamps 22:15–22:30, i.e.
  **21:15–21:45 UTC** in the +60 era and **20:15–20:45 UTC** in the +120 era — a window the
  arm's 06–20 UTC session and 22:00 UTC flat rule never trade. Measured on 147 of 179 stamped
  days: gross **−0.0037R/day** (t −0.37), cost 0.0071R, net **−0.0109R/day** (t −1.09), MDE
  0.0278R/day → **UNDECIDED AT THIS N**, with the effect absent before costs rather than eaten
  by them. The arm's absence from that window is therefore measured, not assumed, and no
  session change is justified by it.
- **Pins:** `tests/test_research_fetch.py` (19 tests — robots precedence, block/login refusal,
  the per-run cap, the lazy browser import) and `tests/test_gold_intraday_momentum.py`
  (14 tests — the declaration, and the artifact's recorded verdict recomputed from its own
  rows). Suite: **1312 passed, 10 skipped**. Surface audit: closure 27 (22 entry points), residue 55 (both new scripts are research
  harnesses by design), **dangling none**.

## 2026-09-21 (late) — the build that carries the census stops calling itself 1.19

- **`MIDAS1.19` described two different builds.** The restart-persistent census (NOFILLSUM
  rows, the UTC-day roll, the init restore) shipped in the source while `#property version`
  and `APP_VERSION` still read `1.19`, so a build *with* the census and a build *without* it
  were indistinguishable in the journal banner and in the ledger's `ERA` row — the one field a
  replay uses to know which behaviour produced a row. Measured: the previous build wrote
  `ERA,MIDAS1.19,1790021732,...,+diag-census`.
- **Both tags are now `1.20`**, and the source comments that had already moved to "v1.20" for
  this change now agree with the tag. The compiled binary is deployed to both copies:
  `source 921c7c88 == the source the deployed binary was built from`.
- **The pins were literals and are now invariants**, because a literal is what let the tag go
  stale: `tests/test_midas_telemetry.py` asserts the label *rides* the P6 build block
  (`>= 1.19`) and that `APP_VERSION` equals whatever `#property version` declares;
  `tests/test_midas_p6_build.py` asserts the deployer admits the released version's ERA stamp
  (and a v1.20 ledger verifies); `tests/test_midas_r6_preconditions.py` extends the registered
  version history to include 1.20. The deployer's accepted-stamp list is *extended*, never
  replaced — an un-migrated ledger still has to verify.

## 2026-09-21 (evening) — the refusal census survives a restart, and stops mislabeling itself

- **The census is now in the ledger, not in the process.** The v1.18 rule was "write a NOFILL
  row once per 24h since the first refusal", anchored in an in-memory `datetime`. MEASURED:
  on 2026-09-21 the arm logged **22 inits** and the ledger held **zero** NOFILL rows for a
  live day on which every evaluated bar was refused — each reload reset the anchor and all
  nine counters, so the rule could never fire. The one record built to answer "why didn't it
  trade" was unreachable exactly when the arm was being reloaded most.
- **New row `NOFILLSUM,<epoch>,<utc day>,<9 counters>`** — the RUNNING census, appended
  whenever a counter changes (at most one per evaluated M15 bar) and on `OnDeinit`, so a crash
  or a recompile loses nothing measurable. The census `NOFILL` row is now written by the
  **UTC day roll** (`UtcDayNo`, epoch/86400 — a property of the clock, not of the process),
  and after the roll the zeroed state is forced onto the record so a reload cannot resurrect
  counts the roll already accounted for.
- **The EA reads it back at init**: `DiagRestoreFromLedger()` runs after the ERA row and
  before any veto can be counted, and prints `NOFILL census restored: day=… signal=… (from
  NOFILLSUM @…)`. `morning_status` gained `nofill_open_day()` and prints the day in progress
  (`no-fill (day N, running): …`) beside the rolled 24h line, so the question answers during
  the day. Proven on the live arm, not just pinned: two real reloads at 19:04:55 and 19:15:32
  restored `day=20717 signal=1 no-trigger=1` instead of counting from zero, and the restored
  counter then continued to 2 on the next bar. Era note carries `+diag-census`.
- **A read-side defect found while wiring it up**: `morning_status.NOFILL_KEYS` named the
  row's fields in a different order than the EA writes them — `no_trigger` third where the
  third field is `session` — so every column from three onward was reported under the wrong
  name (session vetoes attributed to the trigger, spread vetoes to the risk cap). Nothing
  caught it because the only fixture used a row whose trailing fields were all zero, and a
  permutation of zeros is invisible. The tuple now carries the writer's order and the pin
  uses nine distinct values, which is the test that would have caught it.
- Also fixed: the **commonest** veto path (`NO-TRIGGER` mode refusals, the dominant class in a
  quiet market) returned without calling the accounting entry point at all, leaning on the
  15-minute heartbeat to notice it — true only while the EA is still running.
- `docs/MIDASTOUCH_HEALTH_GUIDE.md` §3a documents the two rows, the counter order, how to read
  them, and why a ledger with no snapshot row reports nothing rather than zeros.
- Tests: `tests/test_nofill_census_restart.py` (11) plus the rewritten cadence pins in
  `tests/test_midas_telemetry.py` — **1257 passed, 10 skipped**; surface audit 0 dangling.

## 2026-09-21 (after the push) — "I copied nothing" is not "the build is stale"

- **`scripts/compile_midas.py`** no longer prints `NOT deployed — a chart still loads whatever
  is at <dest>` on every verify-only run. MEASURED DEFECT: that sentence reports what the
  PROCESS did (it copied nothing) in the words of a report about the ARTIFACT (the deployed
  build is wrong). Those are different facts with different remedies, and the second is the one
  `live_readiness` treats as a failure — so the alarm stood on a healthy state, and the same
  run that printed it also had a deployed binary in step with its source (`source 71886ca3 ==
  the source the deployed binary was built from`). A line that cries wolf on the normal case
  teaches its reader to skip the line that matters.
- **Two facts, three words, one alarm.** A verify-only run now says what it skipped, then
  reports the deployed build's state: `CURRENT` (a chart already loads this source), `STALE`
  (older, replaced, or absent — the only alarm), `UNKNOWN` (no record: newer-than-source is not
  proof, because MetaEditor is not bit-reproducible). The verdict is **not re-derived** — it is
  `live_readiness.deployed_build_state`'s own, over the same two destinations and the same
  build record, so the compiler and the readiness gate can never disagree about what "stale"
  means. Advisory, not enforcing: a successful compile still exits 0.
- Also separated: the deploy record line. `build record: NOT written (nothing was deployed)`
  never meant that — on `--deploy` every verified target is deployed — so it now says the
  record was LEFT ALONE because nothing was copied, and cannot read as a deploy.
- **Pinned in `tests/test_build_provenance.py` (13 -> 21)**, and both directions proved by
  restoring the defect: the alarm word on a healthy state fails 3 pins; the retired one-
  sentence-for-both-facts form fails 5. Writing the pins caught my own first guard being
  evadable — it scanned lines containing `print(`, and a mutation that reassigned the whole
  list (`lines = [f"      NOT deployed …"]`) printed the retired sentence straight through it.
  The guard is now structural (`ast` string constants, docstrings excluded), so it cannot be
  walked around by changing which expression holds the string — and the comment recording WHY
  the sentence was wrong is still allowed to quote it.

## 2026-09-21 (later still) — the size the arm really takes, and the first-fill packet

- **`scripts/gold_minlot_sizing.py`**: the deployability leg re-run at the size this account
  actually trades. At 0.25% the $62.50 budget sits ABOVE the venue's min-lot floor, so the EA
  trades 0.01 lot — and at the minimum lot the dollars a trade risks is its OWN stop distance
  in dollars, varying trade to trade (mean $11.99, range $5.96-$63.47 on the venue's bars).
  Measured: **worst simulated day -$158.33, 0 of 30 days beyond the $750 line, $591.67 of
  headroom** (0.633% of the account vs the venue's 3%) — against the flat-0.25% row's
  -$466.60/$283.40, which charged every trade the same dollars. The script re-derives the
  frozen artifact's four flat rows and asserts they reproduce EXACTLY, so the two tables are
  provably the same machinery and the only difference is the sizing model. Enabled by a new
  backward-compatible `risk_usd_for(trade)` hook on `gold_governed_wfo.govern` (a constant
  hook reproduces the flat path bit-for-bit, pinned).
- **The decidability answer, in the same artifact**: lot size does NOT enter it. `t =
  mean_r / (sd_r / sqrt(n))` — both in R, and R is size-free, so the dollars cancel. Size moves
  the dollars at stake and the governor's vetoes; it cannot move the required sample by one
  trade. At the measured effect (+0.4230R, sd 3.3110) that is 236 trades for t>=1.96 and 481
  for 80% power at the measured 2.61 entries/calendar-day (0.50 years) — **and those are
  post-hoc numbers that would UPGRADE the verdict**: the binding requirement is the
  declaration's 766 (fixed before the run from the DISCOVERY set's +0.3221R), which is what
  returns `POSITIVE, UNDERPOWERED`. The artifact says so in those words, and a test fails if
  the post-hoc note ever disappears.
- **`scripts/midas_first_fill_packet.py`**: the arm's first real fill, three ways at once —
  the venue's deal history, the EA's ledger row and the EA's state stamp — field by field with
  a verdict per field and every disagreement NAMED with both values. Fires from
  `midas_watchdog.record_first_fill` (lazy import, no cycle) and writes
  `artifacts/live/first_fill_packet.json`. The server-vs-UTC frame case is DISCLOSED ("agree
  only after conversion") rather than silently converted on one side. Defect found while
  writing it: a CLOSE row the venue cannot confirm fell through as AGREEMENT, i.e. the one
  case where the ledger claims an exit the account does not hold was the one case that passed
  silently; now a named DISAGREE, pinned both ways. Suite **1237 passed / 10 skipped**;
  surface audit 0 dangling.

## 2026-09-21 (later) — the supervisor stops reverting the arming record; replays get a frozen calendar

- **Watchdog: the DRIFT remedy re-spliced the WRONG pin.** `resplice_pins` resolved its
  source with `preset_for_tag(tag)` — arming defaulted OFF — while `check()` detects drift
  against `preset_for_tag(tag, armed=arming["armed"])`. Measured on this machine: 16:52:20Z
  the watchdog reported `[U25] chart InpLiveExecution=false (repo pin true)`, rewrote the
  armed arm's staged preset from the PAPER pin (4564 bytes, paper header), restarted the
  terminal, the EA booted `execution=PAPER`, and twenty minutes later the same drift fired
  again — 4 lifetime restups, 20 EA inits today, every operator authorisation reverted
  within one watchdog cycle. The remedy now resolves the armed pin by the record
  (`_armed()`, unreadable -> paper, the only one of the two mistakes that cannot place an
  order) and `check()` hands it the very pin the drift was detected against. Pinned both
  ways in `tests/test_midas_watchdog.py` (2 new; both fail against the old code).
- **Two calendars, two clocks.** `MidastouchAI.mq5` refreshes the rolling
  `MIDASTOUCH_news_calendar.csv` live from `CalendarValueHistory(now-N, now+M)`, so its
  coverage moves with the clock. Measured 17:52Z: that refresh cut it to a
  2026-09-09..2026-10-09 window and the coverage the day's measurements stood on
  (2026-01-02..2026-09-24, 2719 events / 369 HIGH) was gone — every replay of the certified
  window then ran a stand-down with no event in it at all, and `test_parity_corpus`'s veto
  pin went red against a rule that had not changed. The snapshot is now tracked
  (`configs/calendars/`, sha256-pinned, with its provenance in a README), staged by
  `midas_parity.stage_frozen_calendar()` under `MIDASTOUCH_news_calendar_frozen.csv`, named
  by the pass inputs and declared `#property tester_file` in the EA beside the rolling one.
  With no snapshot a pass REFUSES; it never falls back to the rolling file. Pins:
  `tests/test_frozen_calendar.py` (6), `test_news_engine_mirror`/`test_news_calendar` input
  pins, `test_parity_corpus` veto window re-pointed at the frozen file.
- **Deployed and verified live.** `compile_midas.py --deploy` (0 errors / 0 warnings,
  source 89d8a5cf == deployed binary), staged preset re-spliced from the LIVE pin, terminal
  relaunched through the attach config: the journal shows `execution=LIVE`, `STATE LABEL ON`,
  and `morning_status [3b]` re-verifies the preset byte-identical to the repo (44 inputs).
  Suite **1210 passed / 10 skipped**; surface audit 0 dangling.
- **Risk re-sized to the measured survivable size: `InpRiskPercent` 1.00 -> 0.25** on both
  Upcomers presets. `scripts/gold_preset_upcomers.py` now pins it as `RISK_PERCENT` with the
  measurement beside it: `artifacts/gold_prereg_no_target.json: sizing_scan_post_hoc` (the
  governor inside, the venue's own bars, the 3% UTC-day line at $750) is the only scanned
  size that breaches the daily rule on NO day — worst day -$466.60, **$283.40 of headroom**,
  0 of 30 days beyond. 1.00% breached on 13 of 30 (-$804.84), 0.75% on 7, 0.50% on 10.
  Recorded as an AMENDMENT in `artifacts/live/armed.json` (scope, `risk_statement`, and what
  it does NOT do — it changes no gate result). At 0.25% ($62.50/R) the venue min-lot floor
  (~$33 at this stop width) binds, so the arm's actual per-trade risk is 0.13%.
- **Two diagnostics that named the wrong quantity**, both found while verifying the above:
  the HUD's TF field read `tf=PERIOD_M15` and was read as contradicting the H1 chart when it
  renders `InpEntryTF` (the entry/trigger TF; the EA never calls `Period()`/`_Period`, and
  every series call names its timeframe) — now `entryTF=`, with the no-chart-period-read
  invariant pinned; and the journal's `FLOOR TABLE ... equity@1%=$N` printed a percentage
  computed at `InpRiskPercent`, correct only while that was 1.00 — it printed
  `equity@1%=$13234` at 0.25%, i.e. a right number under a wrong label, now
  `equity@%.2f%%` from the input. Pins: `test_midas_hud` (2), `test_midas_golive_grammar`
  (1, plus the preset risk value), and `test_midas_p6_build`'s PERIOD_M15 scan now runs over
  comment-stripped source (a comment naming PERIOD_M15 to explain why it is not read there
  is not a site). Suite **1213 passed / 10 skipped**; deployed source 71886ca3 == binary.

## 2026-09-21 — the entry's state is stamped into the ledger (v1.19e, InpRecordStateLabel)

- EA: `InpRecordStateLabel` (default false, so the frozen baseline and every parity
  run stay byte-identical) makes both paper OPEN writers append the SIGNAL bar's own
  state as five end-of-row fields: `sig_ct, hour_utc, vol_ratio, news, off_min`.
  Nothing reads them back as a gate — the stand-down is still `InpUseNewsFilter`,
  untouched — and the stamp is deliberately OFF in strategy-tester runs so certified
  parity ledgers cannot move.
- Why: the pre-registered forward cell
  (`docs/GOLD_PREREG_FORWARD_CELL_20260921.md`) labelled the arm's rows by looking each
  signal bar up in the venue's data of record, which fails for any row newer than the
  last history refresh (`UNLABELLABLE`) and for a ledger that outlives the terminal's
  data folder. The recording arm now states its own axes; the rebuild is kept as the
  control and the two are reconciled row by row, with disagreements listed.
- The axes are single-sourced: the EA writes the RAW ratio/hour/proximity, and python
  bins them with `gold_persistence_state.label_of_values` — the function that found the
  cell. The EA's constants are pinned to the python values by
  `tests/test_state_label_contract.py`, and the reader's offset into the row is pinned
  against the writers' own format strings.
- Measured, on the venue's bars: the stamped ratio reproduces
  `wilder_atr`+`trailing_percentile` to a worst relative deviation of **2.1e-08** over 34
  sampled bars spanning all three volatility bins (16,299 bars available), and the
  volatility bin agrees 34/34. The 200-bar recursion warm-up is what buys that bound and
  a test pins that removing it loses the agreement.
- Also: `NewsRefreshIfDue` now keeps the calendar alive for a recording-only arm (gate
  OFF + stamp ON), because a stale source would stamp `na` forever and `na` is not
  `out`; both Upcomers presets (paper + the armed LIVE variant) pin the new input.
- Pins: `tests/test_state_label_contract.py` (20), `tests/test_forward_cell_prereg.py`
  (+1 end-to-end on a stamped record); updated `test_midas_telemetry` OPEN-format pins,
  `test_midas_hud` input registry and `test_news_calendar` refresh-condition pin.
  Suite 1201 passed / 10 skipped; EA compiles 0 errors / 0 warnings.

## 2026-09-18 — P6 build block executed: v1.19 InpEntryTF + staged TP-1.5R presets

- EA v1.19: InpEntryTF input (default M15 = certified; M5 = P6 winner);
  live/PERTICK path fully TF-parameterized; BAR parity hardwired M15 with
  fail-closed M5+BAR init guard; HUD shows the TF; ERA note +p6-entrytf.
- Staged LV presets (DO NOT SPLICE until the 2026-10-01 reading passes):
  MidastouchAI_LV_TP15_M15_gold.set (interim TP 1.5R) and
  MidastouchAI_LV_TP15_M5_gold.set (P6 winner: M5 + TP 1.5R, kill rules
  in-file). Paper presets carry the inert InpEntryTF=15 identity line only.
- Deployer verify contract extended to admit the v1.19 ERA stamp (the armed
  chain would otherwise verify-fail when the tree advances).
- Pins: tests/test_midas_p6_build.py (10), telemetry chain pins updated to
  the three-tag era, HUD/R6 pins follow the tree; affected suites 106/106.

## 2026-09-18 — P6 consistent-daily-income study executed (register §2b)

- Pre-registered daily-consistency study (M5/M15 × TP {1,1.5,1.8,2} × k
  {1,1.5,2}) across the certified M15 corpora and a fresh 50,000-bar broker
  M5 fetch (provenance artifact). 36 configs; ranking fixed before results;
  OOS law added before any OOS number was seen (Jan–Mar in-sample,
  Apr–Sep OOS, same gates).
- Winner: M5 k=2.0 TP=1.5R — 57.2% positive days, median $6.41/day on the
  $5k study book, pf 1.368; OOS survivor (pf 1.150, 52.9% positive days).
  10 of 12 M5 configs failed OOS — the law did its job.
- M15 cross-check: on the current config the median day declines
  monotonically with TP length (1.0R +$4.29, 1.5R +$2.91, 1.8R −$2.48,
  2.0R live −$2.50) — every shortened TP beats the live shape; the
  amendment targets 1.5R because it alone of {1.5, 1.8} survived the M5
  OOS gate and 1.0R missed it (pf 1.138 < 1.15).
- Amendment queued behind the 2026-10-01 reading: M5-entry LV variant (new
  code, full §1 parity) + interim TP 2.0→1.5 SIA item. No live/paper arm
  changed tonight from this result.
- New: scripts/midas_p6_income_study.py (+ its test pins), scripts/midas_fetch_m5.py,
  artifacts/midas_p6_income_study_20260918.json, artifacts/midas_p6_m5_fetch.json,
  data/forex/xauusd/XAUUSDmicro_M5.csv.

## 2026-09-18 — VPS migration law + chain-gated v1.18 paper deploy

- First live trade: BUY 0.10 @ 4381.09 (18:45:01Z) executed on the VPS
  (surface migrated 12:46Z); broker monitor caught it (first_fill_seen,
  equity $40.36). Local 10027 rejects were the migration-disabled local
  instance refusing a double-entry race on the netting account.
- Era law: local AutoTrading OFF during VPS hosting (ON = double-entry
  hazard); sentinel era-aware both directions; monitor loop restarted on
  the era-aware build.
- v1.18 paper deploy: scripts/midas_deploy_v118.py armed detached — waits
  for v17-cert-complete, then gates → stop → compile → md5-verified copies
  (never parity shadow / live path) → relaunch → ERA18+diag-nofill verify.
  LV deploy DEFERRED to the VPS re-sync. 8 hermetic pins + 3 era pins.

## 2026-09-18 — v1.18 NOFILL diagnostics + external-review adjudication

- Every veto in the PERTICK signal path now logs its reason (honest HUD
  `VETO <reason>` lines) and a daily NOFILL ledger row records the veto
  census (8 counters) — "why didn't it trade" is now evidence, not memory.
- Live-order terminal failure records retcode+description (g_lv_last_error).
- Review items adjudicated with measured evidence: Mode 7 refuted (sweep:
  half the R, worse pf), spread cap 5.0% refuted (p99 spread $0.51 vs $0.38
  cap — the cap only bites in the news tail), hardcoded ATR band refuted by
  its own study (no band improves return; artifact registered).
- v1.18 compiled 0/0 via the scratch tool; deployed binaries untouched;
  era note carries +telemetry-only-per-V2-register+diag-nofill (never-abort
  both directions, pinned); 23 telemetry pins green.

## 2026-09-18 — AutoTrading silent stand-down found and closed (LV live)

- Found: terminal global AutoTrading OFF 08:40→17:39 UTC — MT5 silently refuses
  every EA order in this state; paper arms unaffected, so nothing else alarmed.
- Fixed: switch restored ON (API-verified); `midas_lv_broker_monitor.py` now
  records `algo_trading` every poll and raises `ALGOTRADING_OFF` as a problem;
  morning status [3b] prints AutoTrading ON/OFF in the LV broker view header.
- Tests: 4 new sentinel pins (off/on/missing-API/attribution-uncorrupted);
  monitor+view suites 24/24, morning-status suite 16/16.

## [LV trigger amendment CORRECTED in-place the same evening: k=1.0/RSI 75-25 by TOTAL OOS RETURN (+21.4R, pf 1.29/1.31 dual-corpus), superseding the 17:30 k=3.0 pass] - 2026-09-18

Self-audit before the report caught two defects in my own 17:30 adjudication: a decimal error ("~1/1.6 days" — real answer ~1/18 days) and the wrong objective (per-trade expectancy instead of total OOS return). Re-ranked the full ORIGINAL k×RSI grid on total OOS return across both independent corpora: k=1.0/75-25 wins decisively — 152 OOS trades, +21.4R, pf 1.287 (repo) / 1.311 (fresh broker), ~1 fill/day, dd 7.5R, recent-30d positive where the frozen baseline was -3.7R. k=3.0 keeps the best per-trade quality (pf 7.2 OOS) but totals only +7.3R OOS at ~1 fill/18d — total-return inferior; k=2.5 OOS-dead; LONG_ONLY OOS-fragile. Deployed 17:38-17:40 UTC via the registered stop->splice->relaunch (chart byte-verified 31/31, backup kept, paper positions restored, LV flat throughout). The 17:30 chart state never traded. Test pin, register, and preset notes all corrected to the same numbers; M1 control unchanged.

## [LV trigger-frequency amendment EXECUTED LIVE: ORIGINAL trigger 2.0/70-30 -> 3.0/75-25, stop->splice->relaunch through the registered sequence] - 2026-09-18

The "LV fires only ~0.9/day" census claim was wrong — a fresh-pull sweep (15.5 months of live broker bars, 160 configs, certified primitives, artifacts/midas_variant_research_20260918.json) showed the frozen baseline actually runs ~17/mo; density was never the constraint. But zero in-session firings since attach was real, and the OOS cross-validation on the independent certified corpus drew the honest map: loosening k is refuted (k<=2.5 edges collapse), the high-frequency t/m modes churn OOS-breakeven (pf 0.98-1.06), and the frontier runs the OTHER way — k=3.0/75-25 ORIGINAL: +0.355R exp full-corpus, +0.338R / pf 2.15 OOS-confirmed, ~1 fill per 1.6 days at live sizing. Executed live at 17:30 UTC through the registered stop->splice->relaunch choreography (the watchdog's own operation): repo preset amended with the full evidence note, chart05 byte-verified 31/31 with backup, all five EAs re-attached, open paper positions restored from their pertick-fills ledgers, LV flat during the window (zero live exposure). M1 keeps the frozen baseline as paper control; divergence pinned both directions in test_midas_golive_grammar.py; registered in the V2 register before the first amended fill. The frequency research engine (scripts/midas_variant_research.py) stays as the parameterized research artifact behind P5's adaptive axis.

## [v1.17 cert chain armed — v1.16 baseline cert first, then shadow refresh, then v1.17 certification, all automatic] - 2026-09-18

The deploy path now certifies itself at the next flat window without operator memory: scripts/midas_cert_chain_v117.py (detached) enforces the ordering law — the armed v1.16 scheduler completes its cert on the parity shadow AS-IS (waiting on its jsonl event contract; a scheduler dead >35 min is taken over by re-running the v1.16 cert directly, and the chain refuses to advance unless that baseline passes); only then is the shadow refreshed to the v1.17 build (byte-identity of the copy verified, an unchanged build refused as a no-op masquerading as a baseline) and the identical registered harness command certifies the new tree with the flat-gate retry contract. Never touches the terminal or watchdog directly — every terminal operation belongs to the harness's registered choreography. 19 hermetic pins (tests/test_midas_cert_chain_v117.py), mypy clean, first live cycle verified reading `waiting` with arms mid-position. Events: artifacts/midas_cert_chain_v117_*.jsonl; registered in the V2 register P5 block.

## [P5 telemetry-first EA build executed in-tree (v1.17): thr/thr_era_id/density CLOSE appends, R10 pattern, never deployed] - 2026-09-18

The P5 row's P-T step, executed exactly per the R10 precedent: v1.17 appends thr (BB k-multiple), thr_era_id (static 0 until the adaptive engine exists) and density (running in-session condition-true count, census semantics — incremented after the session/Friday gates at BOTH ModeDecide call sites, BAR + PERTICK) as end-of-row appends on both paper CLOSE writers; ERA note carries +telemetry-only-per-V2-register (never-abort class); no certified-path behavior change. Pins: positional format pins moved consciously to the 12-field shape (tests/test_midas_telemetry.py, 17 green) with counter-placement and no-reset monotonicity pins; consumer-completeness enumeration re-verified every CLOSE reader tolerates the appended grammar; the verdict tool pinned BOTH directions on the real deployment path (a cited v1.16→v1.17 mixed-width ledger passes with r/veq positional across both widths; the same transition UNCITED aborts). Compiled 0/0 via scripts/compile_midas.py with before/after md5 proof the deployed paper, LIVE and parity binaries were never touched (VPS-era sync source intact). Nothing deploys: v1.17 reaches arms only in its registered era, after the 2026-10-01 reading.

## [P5 registered — adaptive trigger-threshold variant (MODE_ADAPTIVE) as the operator's frequency answer; spec engine + pins in-tree, queued behind 2026-10-01] - 2026-09-18

Operator directive ("switch the live arm to a higher-frequency variant that fires more per day and is intelligent, learns and self-adjusts") registered as §2b row P5, deliberately queued behind the reading and the P-series, because the frozen sweep verdict already refutes the literal request: ALL 8 fixed variants are NO-SHIP on gates G3/G4 (`midas_sweep_verdict_20260916.json`) — switching LV to t or m would ship a known-bad static point to make the live arm busier. P5 instead pre-registers a NEW adaptive variant: trigger threshold θ (BB k-multiple / RSI band width) adapting stepwise within hard bounds [1.0, 4.0], one step per 20 closed trades, δ=0.25, tie toward the conservative end; kill rules (trailing-20 expectancy < −0.30R → FREEZE at θmax; two consecutive full-loss days → REVERT; envelope-violating state → VOID + operator re-registration); joint endpoint = G3 pf ≥ 1.30 AND G4 expectancy ≥ +0.15R AND fill density ≥ 3× ORIGINAL's same-period baseline, trialed on a dedicated M1a paper arm with M1 as control. "Learns and self-adjusts" is implemented lawfully: the EA never mutates its own parameters mid-era — `scripts/midas_adaptive.py` (pure, no MT5, no ledger writes) proposes from trailing realized expectancy, and every proposal deploys through the existing era machinery (re-splice + watchdog pin verification) as a registered amendment. Engine + 21 test pins in-tree (constants, cadence, bound law — the envelope is the cap and a bound-reach is a HOLD, never a crossing proposal —, kill rules, VOID semantics, purity); mypy clean; selftest OK. Adaptation's authority is the threshold ONLY — risk %, breaker, SL/TP multipliers, session window and spread cap are outside its reach by construction.

## [VPS-era broker-evidence LV monitor — positions/deals/equity by magic 7801601 surfaced in [3b] automatically] - 2026-09-18

While hosting lasts, the VPS LV ledger is invisible locally, so the account became the evidence surface: `scripts/midas_lv_broker_monitor.py` polls the MT5 API (60 s loop, detached) and persists `artifacts/midas_lv_broker_state.json` — positions and trade deals filtered to magic 7801601, account-level balance operations captured REGARDLESS of magic (the 12:25:59Z −$10.14 withdrawal shape: money movement is account evidence, not arm evidence), equity/balance/margin, deals deduped by ticket across polls, `first_fill_seen` set on the first ENTRY deal and never unset. The monitor never writes the LV ledger (EA-owned file; pinned by test). [3b] renders any existing snapshot as the `[LV broker view]` block — account header with snapshot age, `LIVE POSITION (broker)` lines (direction/volume/entry/SL/TP/open-age), entry/exit deals with P/L, balance ops flagged as non-trading; a >5-min-old snapshot is labeled STALE and never hidden, staleness being itself the signal that the poller died. Hermeticity: the snapshot path is a module constant plus an autouse conftest fixture — the operator's real snapshot can never leak into a test run (caught by the correlation suite's flat-portfolio test during the full-tree run). Attribution rules pinned in tests/test_midas_lv_broker_monitor.py (10), rendering in tests/test_midas_lv_broker_view.py (10, including collision-freedom with arm-level `live: flat` lines). First-trade ritual Phase A adapts to broker evidence during the era (registered in the ritual doc). Full tree: 1744 passed / 15 skipped.

## [VPS-hosting era: MT5 locked local algo off by design; operator chose the VPS surface; era guards shipped for watchdog + [3b] + first-trade ritual] - 2026-09-18

The "remove the barricades" request surfaced the real blocker: at 12:46 the terminal's journal recorded `6898457: automated trading disabled after migration and enabled on virtual hosting` — an MT5 VPS migration had locked LOCAL algo trading off BY DESIGN (local EA + VPS EA would both trade the same hedging account; three programmatic Ctrl+E attempts correctly refused). Operator confirmed they started the migration and chose the surface: corrections land locally, then the operator's VPS sync picks up the already-verified local state (LV v1.16 `a4bf5e30`, 15.0 breaker, LIVE pins — verified byte-exact earlier). Era guards shipped: `artifacts/midas_vps_hosting.json` (operator-managed marker, the only honest source — MT5 exposes no hosting API) makes the watchdog observe-only (`VPS-HOSTING`, never remediates — a frozen local LV ledger is the era's signature, not a fault) and [3b] print the era banner with the LV-staleness exemption; the first-trade ritual gained its Phase-A broker-evidence adaptation (the python API sees account positions wherever the EA executes). All five local ledgers still fresh post-migration (paper arms collect locally; AutoTrading gates orders, not heartbeats). Cert scheduler unchanged — its flat gates handle every case. To end the era: delete the marker when the surface returns.

## [first-live-trade ritual pre-registered; LOPEN grammar aligned to the EA writer (14 fields) across all three consumers] - 2026-09-18

Pre-registered docs/MIDASTOUCH_FIRST_LIVE_TRADE.md before any fill: Phase A verification (row integrity, broker position cross-check, [3b]+watchdog visibility), Phase B no-interference monitoring (R5 floor %, breaker headroom, exit arithmetic), Phase C LCLOSE reconciliation with a 3-way verdict (EXPECTED/DEGRADED/MISMATCH at 20%-of-stop slippage), Phase D registration — plus the pre-declared cert-scheduler interaction (a live position legitimately delays the v1.16 cert). Writing it caught a critical latent defect: the python consumers' LOPEN contract required 15 fields while the EA v1.16 writer emits 14 — the first real fill would have been invisible to [3b] AND to the watchdog's open-position gate (a terminal restart would have been permitted over real money), and the parity harness had NO live-grammar awareness at all (a cert session could have stopped the terminal over an open live trade). All three consumers (morning_status live_grammar_view, midas_watchdog ledger_health, v28_sweep_runner ledger_flatness) aligned to the writer-exact shape (posid [2], dir [5], LCLOSE pairing by posid, 6-field LCLOSE), and the test fixtures now parse the MQ5 format strings directly — a parser/writer divergence fails the suite instead of a real position. mypy: v28_sweep_runner now fully clean.

## [go-live hardening: §14 chart-identity drift checks, refused-restart counters, verified offset re-baseline, live-arm breaker amendment] - 2026-09-18

Three issues found in the first hours of live operation, root-caused and fixed. (1) **Phantom escalation storm killed at the mechanism**: the 09:05–09:25 ESCALATE was banner-attribution failure — five charts print identical `mode=… | session=…` banner text with no arm tag, so the LV check matched a paper arm's PAPER banner and screamed drift. The banner drift matchers (`banners_for_pins`/`banner_drift`) were REMOVED outright — banner text cannot be attributed across identically-labelled charts — and the watchdog's drift path now keys on the CHART FILE identity (the same byte-verified `<inputs>` source [3b] uses, which caught the real 09:57 incident); the banner stays observation; a refused restart (SKIP-OPEN-POSITION) no longer increments the escalation counters (the 09:05 skip had driven a phantom ESCALATE state; counters rolled back and reset after the healthy-arm verification). (2) **Broker-offset resolution locked in**: the +0h00-vs-+2h flag was resolved by external evidence (live broker tick epochs vs NTP-checked machine UTC: broker genuinely at UTC+0; machine −0.32 s from the atomic reference) and re-baselined through the audit chain (`--verified-offset 0` two-run confirm; `last_offset_verified` evidence recorded) — an offset jump is always flagged, resolved only by evidence. (3) **Live-arm daily breaker amended review-frozen**: `InpDailyLossCapPct=3.0` (the paper default) would make one min-lot stop-out (6–9% of the $50.22 book) a daily stand-down; the LIVE arm runs **15.0** (first full loss admitted, second consecutive full-loss day vetoed — refuses the review's −45% pattern instead of starving the sample), paper arms untouched at 3.0, live chart re-spliced and verified 31/31 with the new pin. **Operational footnote:** the old-banner-code loop processes launched 2026-09-17 18:16 kept the phantom alive from memory after the fix landed — killed and replaced with a single fresh loop on the fixed code (first cycle: NONE, zero drift, zero problems); the instance lock is loop-lifetime, so the Task Scheduler's logon instance now coexists safely (a second loop exits loudly instead of double-supervising). During the phantom's entire lifetime every attempted restart hit the §14 flat gate (M1t/M1m held positions) and was refused — no terminal restart, no chart re-splice, no live-arm impact ever occurred; only counters stacked, and they were reset after verification.

## [GO-LIVE — MidastouchAI v1.16 LIVE on account 140778269; live-grammar monitoring shipped] - 2026-09-18

The first real-money attach of the gold EA, executed through the full registered chain: dedicated live binary (v1.16 \a4bf5e30… under Experts\\MIDASTOUCH_live — the certified shadow build; paper paths untouched), new chart05 cloned from certified chart01 geometry, preset MidastouchAI_LV_gold.set = the M1 pin set with only identity+execution deltas (tag LV, magic 7801601, InpLiveExecution=true), verified 31/31 byte-identical at boot; banner execution=LIVE confirmed, floor table min-lot risk $2.91 = 5.8% of $50.22 (inside the R5 15% cap), AutoTrading verified ON via API, watchdog flat gate + morning status upgraded to parse the LIVE LOPEN/LCLOSE grammar (a dangling LOPEN is a real position — restarts refuse over it; SKIP-OPEN-POSITION, --force override documented), [3b] shows the LIVE $$$ arm with open position, live closes and exit reasons; 12 go-live grammar pins in tests/test_midas_golive_grammar.py. Registered in the V2 register's GO-LIVE EXECUTION BLOCK; live attach authorized by the operator's explicit instruction (geometry verified before execution).
## [v1.16 finalization + reading-blocker fix — guards before banner, compile tool, deferred-pin tolerance, reading runbook] - 2026-09-18

R6 hardening finished: both INIT_FAILED preconditions moved BEFORE the init banner (a refused attach never announces a healthy start) and the stale "(calendar pending)" label removed; one line-merge corruption introduced by an edit was caught by the R6 occurrence pins before it could compile and repaired (behavioral delta: a comment). New `scripts/compile_midas.py` encodes the real MetaEditor contract (silently no-ops on sources outside the terminal MQL5 tree; scratch lives under the data folder, explicit /log, 0 errors / 0 warnings + .ex5 verified) — v1.16 recompiled clean, shadow refreshed (\a4bf5e30…), deployed binary untouched. Reading blocker resolved: the first live midas_verdict dry-run aborted all four windows on "missing from chart: InpMaxRiskPct" (repo pins advanced to v1.14 while arms run v1.10) — preset_identity now treats deferred newer-build pins as recorded evidence, never drift (unknown pins still abort; parse problems never deferrable; verdict records deferral in notes, tests both directions). All four arms read CONTINUE-UNPROVEN, abort=False — the 2026-10-01 reading is unblocked, with the reading-day runbook pre-registered at docs/MIDASTOUCH_READING_20261001.md (expected outcome stated in advance). v1.16 WF parity certification pending flatness (M1m opened the portfolio's first live M30 fill 06:15 UTC, 720-min timeout ~18:15). Also root-caused and fixed the 8 cross-suite watchdog test failures: fixture mtimes were stamped with time.time() at test runtime while decide() received an import-time NOW, so long sessions slid the 45-min fixture into the 44-min grace band — stamps now anchor to the same module NOW; full tree 1703 passed / 15 skipped.

## [v1.16 — R6 executed: fail-closed preconditions (news-filter input, gold-only charter); OOS 8-mode matrix certified; operational hardening] - 2026-09-18

R6 closed as a python+EA pair (never-deployed, era-gated): the EA INIT_FAILEDs on InpUseNewsFilter=true (no calendar engine exists) and on a non-gold symbol (charter), folding #35 per the register's rule; the harness mirrors both preconditions. EA compiled 0 errors / 0 warnings (verified via explicit /log capture — the stray repo-root compile_log.txt removed); shadow refreshed to v1.16 (\7132193d…); deployed binary untouched (\22f39ae0…). Before the refresh, the v1.15 shadow certified the OOS 8-mode matrix 8/8 PASS (four artifacts). Also: stale 'MidasWatchdog' scheduled task deleted (foreign repo path, minute-repeating — a second watchdog); telemetry consumer-completeness now enumerates consumers dynamically and found two the hand list missed (ab_adjudicate, adjudicate_arm_c) — all readers verified on appended grammar; version-law pin moved to 1.16.

## [morning_status + harness — §1 version-awareness, offset audit chain, journal-retention guard; probe launch finding] - 2026-09-18

Version transitions are now pinned to midas_verdict.py's §1 walk as the ONLY version consumer: banner_drift stays version-blind (behavioral + AST no-consumer pins, mutation-verified) and the parity harness's keyed compare stays version-agnostic — a cited v1.13 telemetry build trips nothing else. Offset state carries the raw reading chain (value/source/epoch/dir, cap 50) + last_change both-legs record, so DST flags are auditable against the journal line that produced the baseline; unstable readings never create state. New journal-retention guard alerts when today's log is missing or >90 min older than the newest ledger heartbeat (the 2026-09-17 log-rewrite incident class). Probe walk-through executed with full watchdog-pause choreography: MT5 silently ignores MidasOffsetProbe.ex5 as a launch argument (instrument finding, health guide updated — manual drag remains the certified way); machine UTC verified vs time.is; persisted +2 h baseline externally corroborated 2026-09-17 and standing. 93 tests green; no new mypy errors.

## [register — phase-2 backlog drafted as §2b: P1 liquidity, P2 structure, P3 regime, P4 confluence, telemetry-first law] - 2026-09-18

The review's five-layer roadmap is now four individually pre-registered experiments in the V2 register §2b, each with a falsifiable one-sentence hypothesis, python+EA planned shape, §13 endpoint vs same-window control, and a common law frozen before any code exists (P-0 endpoint, P-C control, P-S sequencing, P-N no-stacking, P-T telemetry-first). P4 (five-layer confluence) is explicitly conditional on ≥3 of P1–P3 surviving. Sequencing §3 gains the P-series queue line. Also: SHADOW_EXPERT constant + tests/test_midas_parity_paths.py (8 pins, mutation-verified) locking the live-vs-shadow load-path separation; R2 register row updated with the path-pin suite.

## [parity — v1.15 shadow certification PASSED: dynamic BAR parity re-cert for the un-deployed line] - 2026-09-18

## [parity — v1.15 shadow certification PASSED: dynamic BAR parity re-cert for the un-deployed line] - 2026-09-18

With morning status showing all four gold arms flat (overnight M1t/M1m timeouts resolved), the flat-gated dynamic certification ran to completion against the shadow binary (v1.15, `MIDASTOUCH_parity` path): python 151 tr/+1.474R vs EA 151 tr/+1.478R, max|dR| 0.0005, keys OK, anchor reproduced — artifact `artifacts/midas_parity_result_20260918_0544.json`. Covers the whole v1.11→v1.15 un-deployed line at once; satisfies §4(b) for the R5/v1.14 era; deployed binary hash-verified untouched; register §2 baseline updated. Deploy path still waits behind the 2026-10-01 reading.

## [parity — v1.13 shadow re-cert attempt: flat gate held; python-half regression proof registered] - 2026-09-17 (evening)

Requested BAR-mode parity regression for the v1.11–v1.13 tree, run by the
book (shadow path, watchdog pause, flat gate): the gate REFUSED the dynamic
pass — M1t/M1m still hold their 15:00 fills (12h timeout ⇒ ~03:00 UTC). No
state was touched; the pause marker was released and the terminal never
stopped.

What WAS proven while the gate held (registered in V2-register §3):
- the python engine of record + window pins + comparison law are unchanged
  since certification: WF REVERSE_DIRECTION regen = n=151 / +1.474R, exactly
  certificate 1's python leg (`…_1258` PASS, max|dR| 0.0005 vs EA);
- the full mode registry is covered same-day by the OOS 8-mode matrix
  (`…_1348`, 8/8 PASS, 1,165 keyed trades, all anchors reproduced);
- the 147-float `midas_parity_python_wf_rd.json` is the documented
  pre-Amendment-2 Wilder-ATR relic (protocol stale-vintages finding), not a
  regression baseline.

Remaining for the freshly certified v1.13 baseline: one dynamic shadow-path
WF pass once all arms are flat (command in register §3), then the deploy
gate itself.

## [tests — source-level invariant pins for the v1.11 live-path ID architecture (register R2/R3)] - 2026-09-17

`tests/test_midas_live_ids.py` (11 tests) pins the R1/R2 position-handling
remediation at the source level, so a regression fails the suite before it
can compile into a binary:

- **Selection isolation**: `SelectOurPosition()` must verify magic+symbol;
  no bare `PositionSelect(_Symbol)` / `PositionClose(_Symbol)` anywhere in
  comment-stripped source; every position-API touch must sit inside the
  five sanctioned functions (selector, ID resolution, verified close,
  exit reconciliation, restart adoption).
- **posid-only history**: every `HistorySelectByPosition(...)` argument is
  pinned to the literal `g_lv_posid`; external-close reconciliation must
  key on `DEAL_POSITION_ID == g_lv_posid`.
- **Provenance stays provenance**: `ResultDeal`/`ResultOrder` may only feed
  `g_lv_deal`/`g_lv_order`; regex sweeps forbid any `Result*` or
  history-deal-space assignment into `g_lv_posid`/`g_lv_ticket`.
- **Coherent state**: the flat reset must clear all four ID fields
together; close must operate on the held ticket.

Mutation-verified: reintroducing `PositionClose(_Symbol)`, feeding a ticket
to `HistorySelectByPosition`, or assigning `ResultOrder()` into
`g_lv_posid` are each caught by the corresponding pin.

## [MIDASTOUCH v1.15 — review P0 #2 completed: authoritative TimeUTCNow + frame-law provenance correction; NOT deployed] - 2026-09-17

The R3 UTC-clock remediation is completed and made honest:

- **One authoritative helper**: `UTCNow()` renamed `TimeUTCNow()` (and the
  probe's references updated) — the single TimeGMT-backed clock for every
  human-intent gate: daily-breaker day key, Friday force-flat, live
  timeout (both ends), and — since v1.15 — the documented frame for the
  session/Friday ENTRY gates' counterpart hour semantics.
- **Provenance finding (the important correction)**: v1.12's frame law
  claimed the bar-epoch gates classify "python-identical UTC epochs". They
  are not UTC — `iTime` returns broker-SERVER-stamped epochs (the broker
  feed's label frame; the CSV of record carries `+00:00` timestamps, but
  the tester/paper bars carry the server's own stamps). Classifying those
  epochs through a UTC structurization would shift the 06–20 window with
  the broker's timezone — the exact review P0, hiding inside the gates the
  v1.12 law told us not to touch. v1.15 corrects the LAW: hour gates that
  read bar epochs use the epoch's own (server) frame; hour gates that read
  the wall clock use `TimeUTCNow()`. The python of record classifies the
  same broker-feed epochs (same frame) — no python code change was needed,
  only the re-pin; both sides documented at the site.
- Source pins updated/added in `tests/test_midas_time.py` (11): the single
  helper (now with a stale-name sweep), end-to-end UTC for breaker/flat/
  timeout, the frame-law pins for both epoch gates, and a cross-engine pin
  tying the EA's epoch classification to `midas_sweep.py`'s — if either
  side ever changes frame, the suite forces a joint re-adjudication.
- Compiled 0/0 (EA 1225 ms, probe 513 ms); deployed binary hash-verified
  untouched; shadow certification binary refreshed to v1.15. Era discipline
  unchanged: nothing deploys before the 2026-10-01 reading.

## [MIDASTOUCH v1.14 — protocol amendment 6 (register R5): min-lot risk refusal, python+EA one commit; NOT deployed] - 2026-09-17

The first parity-gated amendment of the register, amended in-tree and
queued behind the 2026-10-01 reading. The rule: when computed lots fall
below the broker minimum, the trade fills only if the min-lot risk
(stop_d × $100 × 0.01) does not EXCEED 15% of the sizing basis; otherwise
the trade is vetoed, never silently oversized.

- **python** (`scripts/midas_sweep.py`): `MAX_RISK_FRACTION=0.15`, pure
  `minlot_risk_exceeds_cap(stop_d, basis)`, pending-fill veto (`res.vetoed`,
  no position constructed, vetoed bar runs no signal detection — mirrors
  the EA BAR caller's `if(!may_signal) continue`).
- **EA** (`MidastouchAI.mq5`, v1.14, compiled 0/0, 1186 ms):
  `InpMaxRiskPct=15.0`; BAR model vetoes the fill with ledger row
  `SKIP,<epoch>,RISK-CAP,<tag>`; PERTICK `OpenPaperPosition` vetoes before
  fill; live `LiveSendOrder` refuses the order against ACCOUNT equity —
  each engine vetoes against the basis it sizes with.
- **The cap is 15% by measurement, not by port**: the certified WF corpus
  floors 42/151 fills at up to $277.30 = 5.5% of book, and the $50 §13
  arms' day-one min-lot risk ($4.55 = 9.1% of basis) sits above every cap
  below ~10%. A 1.5% cap (the V75 checklist's number) would veto 15
  certified fills and starve the forward arms; 15% vetoes ZERO certified
  fills (regen n=151 / +1.474R, vetoed=0) and still closes the pathology
  the review demanded. Decision table frozen in protocol amendment 6.
- `tests/test_midas_minlot_veto.py` (9): boundary law (strict inequality),
  purity, counter, corpus+arm compatibility facts, and the permanent
  regression law (certified regen unchanged, vetoed=0).
- Deploy discipline: era-stamped fresh ledgers + shadow-path parity re-cert
  for v1.14 BEFORE any deploy; nothing deploys before the 2026-10-01
  reading. Deployed binary hash-verified untouched; shadow certification
  binary refreshed to v1.14.

## [morning_status — broker-vs-UTC offset tracking in [3b]: probe/banner parsing, persisted baseline, automatic DST-shift flag] - 2026-09-17

- `scripts/morning_status.py` ([3b] footer, display-only): reads TODAY's
  terminal journals for both offset writers — MidasOffsetProbe lines
  (`offset (server-GMT) = +N h MM min`) and v1.12+ EA init banners
  (`CLOCK: … offset=+N h MM min`, self-recording on every attach) — and
  persists the latest stable whole-hour value to
  `artifacts/midas_clock_offset_state.json`. A new reading ~1 h off the
  baseline prints a `DST SHIFT` alert (UTC+2 winter / UTC+3 summer is
  expected for NY-close-anchored gold brokers); any other move prints
  `OFFSET CHANGE`. Fail-closed details: ±1 min sampling-artifact band
  (TimeCurrent/TimeGMT are separate statements); non-whole-hour readings are
  reported but never become the baseline; source classification by the
  parenthesized `offset (server-GMT)` fingerprint (the probe's offset line
  itself carries no "OFFSET PROBE" marker); no-reading days show the last
  known value with age and never mutate state.
- `tests/test_midas_clock.py`: 19 tests — grammar for both writers,
  negative offsets, `_fmt_off` mirrors MQL5 truncation-toward-zero, the
  artifact band, DST vs non-DST change, baseline persistence, corruption and
  partial-state degradation, section wiring (monkeypatched state path),
  unchanged arm health.
- Zero new mypy errors (the line-258 find — a partial state file crashing
  the age line — was fixed, not suppressed). Live-verified: two consecutive
  runs on the real tree leave the state byte-identical while reporting the
  morning probe's +2 h baseline.

## [MIDASTOUCH v1.13a — V2 register §1 mechanism implemented in midas_verdict.py (cited transitions exempt, evidence recorded)] - 2026-09-17

Closes the open dependency registered under R10: the ERA-note citation now
has an enforcement-side reader.

- `scripts/midas_verdict.py`: the §13 version-change abort keys on
  **unexempted transitions** from a new `_unexempted_version_changes` walk —
  a version change whose first ERA stamp of the new version carries
  `telemetry-only-per-V2-register` (the v1.13 writer's note) continues the
  window; every transition, exempted or not, is recorded in the reading's
  evidence as `version_transitions` (from/to/line/telemetry_exempt/note).
- **Fail-closed by construction**: citation on a non-transition re-stamp
  exempts nothing; a truncated stamp is uncited; rollback aborts (the older
  binary predates the register and cannot cite); one uncited leg of a chain
  aborts the whole window. The abort message now names the unexempted legs.
- `tests/test_midas_verdict.py`: 8 new "V2 register §1" tests pin both
  directions — exempted transition continues (with evidence), uncited
  transition aborts, non-transition citation ignored, chain exemption,
  longer-note tolerance, rollback abort, fresh telemetry-only window reads
  as a single version, malformed stamp fails closed.

## [MIDASTOUCH v1.13 — register item R10 executed: telemetry ledger columns (never-abort class, NOT deployed)] - 2026-09-17

First build produced under the register's standing rule (§1), exercising the
never-abort classification end to end:

- **End-of-row appends only**: paper OPEN rows (BAR + PERTICK writers) append
  `atr_at_entry,spread_at_open`; both paper CLOSE writers append
  `spread_at_close,slippage` (model exits: 0 by construction — recorded
  explicitly so live slippage has a matching column). Live rows (LOPEN/LCLOSE)
  deliberately keep their v1.11 grammar; extending them is a live-gate
  decision. The frozen grammar heads are pinned positionally by
  tests/test_midas_telemetry.py — insertion/reordering now fails the suite.
- **ERA note cites the register** on the paper path
  (`pertick-fills+telemetry-only-per-V2-register`); BAR tester ledgers keep
  the exact parity-era note byte-for-byte. midas_verdict.py can classify this
  version change without aborting the window once the §1 exemption lands.
- **Consumer safety net proven, not assumed**: all five python consumers of
  the ledger grammar are min-length + index-based (parse_ledger 12/7,
  collect_midas_positions 12, ledger_flatness 12/8, midas_verdict 8,
  era.parse_era_rows extras-ignored) — 10 tests feed every one of them
  appended rows and pin identical reads.
- Honest path: one corrupted test-file write was caught mid-turn and
  rewritten before any run; compile clean 0/0; deployed binary untouched
  (hash pinned); shadow certification binary refreshed to v1.13.

## [Parity harness v2.1: shadow-path certification + relaunch guard; v1.12 baseline PREPARED (gate-refused)] - 2026-09-17

Baseline re-certification attempt for the v1.12 tree, executed and recorded:

- **Shadow-path mechanism** (`--expert-path`, default = the certified
  deployed path): parity passes can now certify an un-deployed build at
  `MQL5\Experts\MIDASTOUCH_parity\` without touching the live charts' load
  path. This closes a real hazard discovered en route: the live gold charts
  load `Experts\MITEMSHUB_AI\MidastouchAI.ex5` — the SAME path the certified
  harness used, so any pre-v1.12 re-cert would have silently swapped the
  binary under the live arms at relaunch (a §13 mid-window deploy).
- **Relaunch guard + stop verification**: the `finally` relaunch now fires
  only if this session stopped the terminal or ran passes (a flat-check
  abort no longer bounces a healthy terminal — live-validated in this
  session), and a failed terminal stop aborts instead of running blind.
- **The gate outranked the run**: the certification was correctly REFUSED by
  the flat-check gate — M1t and M1m hold their first open paper positions
  (epochs 1789657200, no CLOSE yet). Exactly the §13 protection working;
  the v1.12 shadow binary is compiled (0/0), installed, and the run is one
  command away once all four arms are flat (morning status [3b] shows the
  state). Register §2 updated with the status and the ready command.
- tests/test_midas_parity.py: 18 passed (defaults unchanged and pinned).

## [MIDASTOUCH_V2_REGISTER.md — adjudicated Phase-1 P0 register + standing telemetry/fail-closed rule] - 2026-09-17

Freezes the external EA review's adjudication into a governing document:
R1–R4 (position-ID architecture, magic isolation, UTC time engine, offset
verification) recorded as DONE-in-tree-not-deployed with v1.12 source-line
evidence; R5–R10 (min-lot refusal, news-filter honesty, BB experiment,
absolute spread cap, breaker extension, startup self-test, telemetry
columns) registered as parity-gated work queued behind the 2026-10-01
reading; the review's factual errors (mode default, BB "bug", severity
frame) recorded with evidence. §1 of the register states the standing
telemetry/fail-closed rule — identical-ticks test, never-aborts/always-
aborts lists, and the ERA-note mechanism (`telemetry-only-per-V2-register`)
that midas_verdict.py will follow once implemented — frozen BEFORE the
first version transition it must classify.

## [MIDASTOUCH v1.12 — UTC time engine for live-path wall-clock gates + broker-offset verification (NOT deployed)] - 2026-09-17

Implements the review's P0 #2 ("your UTC clock isn't actually UTC") with a deliberate
two-clock frame law instead of a blanket conversion — because two of the four affected
gates are parity-frozen on the label frame and MUST NOT move:

- **The frame law**: signal-bar EPOCH classification (session 06–20, Friday cutoff — both
  BAR and PERTICK) stays on `iTime` labels, because python classifies those same epochs
  (Amendment 2; converting them would silently re-shape every researched session statistic
  and break bit-level BAR parity). Live-path wall-clock decisions move to `TimeGMT()` via
  a single `UTCNow()` helper: the daily-breaker day key, the Friday force-flat, and the
  live position's 12h timeout (both ends of the comparison). The staleness guard stays on
  `TimeCurrent()` deliberately (it measures gaps in the server tick stream — its own
  frame), as do ledger row stamps (provenance consistency).
- **Verification surface**: the init banner prints a `CLOCK:` line (server, GMT, derived
  offset) on every attach; new `MidasOffsetProbe.mq5` script walks the operator through
  the pre-live-gate offset check (mqlGMT vs an external UTC clock; note the offset; re-run
  after DST). Documented as health guide §4.
- **Pinned by source tests** (`tests/test_midas_time.py`, 9): UTCNow is single and
  TimeGMT-backed; both parity gates classify epochs and never touch the wall clock; the
  breaker/Friday-flat/timeout sites use UTCNow end-to-end and never structurize
  `TimeCurrent()`; staleness keeps the server frame; the probe exists.
- **Verification**: both files compile clean (0 errors / 0 warnings) via MetaEditor CLI in
  a scratch folder — deployed 1.10 binary byte-identical before/after (sha256 pinned),
  scratch removed. One real compile catch: MQL5's `%` is integer-only (probe fix).
- Same deploy discipline as v1.11: zero effect on the running paper portfolio (live-path
  only); deploying = new §13 era, do it deliberately at the live gate.

## [MIDASTOUCH v1.11 — live-path position-ID isolation + magic-number position select (NOT deployed)] - 2026-09-17

Implements the two confirmed P0 items from the external EA review (order/deal/position-ID
conflation; `PositionSelect(_Symbol)` trusting any position on the symbol). Zero effect on
the running portfolio: `LiveOnTick()` executes only when `InpLiveExecution=true &&
!InpBarModel` (EA:626) — all four gold arms are paper mirrors and never touch this code.

- **Three DISTINCT ID spaces, no conflation**: `g_lv_posid` (POSITION_IDENTIFIER — the ONLY
  history-reconciliation key for `HistorySelectByPosition`), `g_lv_ticket` (selected
  position ticket, positioning context), `g_lv_order`/`g_lv_deal` (entry provenance).
  The old `ResultDeal() ?: ResultOrder()` assignment into one variable is gone.
- **`SelectOurPosition()` is the only way live code touches a position**: adoption scans
  `PositionsTotal()` matching symbol AND `InpMagic`; once IDs are held it re-verifies the
  exact ticket+identifier+magic every call (O(1), and makes the external-close check
  correct — the old early-exit would have masked a server-side SL/TP close). All
  `PositionSelect(_Symbol)` call sites replaced; `PositionClose(_Symbol)` replaced by
  `PositionClose(g_lv_ticket)` after verification, with a CLOSE ABORT if the position
  vanished mid-retry (external close reconciles via `LiveCheckExits` instead).
- **Recovery hardening**: `LiveRecoverState` and post-fill adoption now resolve the entry
  deal from open history (`DEAL_ENTRY_IN`) and refuse to adopt foreign positions.
- **Ledger grammar (live rows only)**: `LOPEN` now carries posid, order, deal tickets
  explicitly; `LCLOSE` carries the position identifier. No python tooling parses
  LOPEN/LCLOSE yet (verified) — no consumer breaks.
- **Version honestly bumped** `MIDAS1.10 → MIDAS1.11` (`#property version` kept equal to
  `APP_VERSION` per the HUD law test). Deploying this binary to an arm chart is a §13
  version change: fresh ledger, window re-accrues from zero — deploy deliberately at the
  live gate, not silently.
- **Verification**: compiled clean (0 errors / 0 warnings) via MetaEditor CLI in a scratch
  folder — the deployed 1.10 binary is byte-identical before/after (sha256 pinned), scratch
  removed. Python suite green (123 tests incl. the HUD law).

## [[3b] correlation view: same-direction, same-bar opens across the §14 portfolio] - 2026-09-17

Day one proved the need (M1t + M1m opened the same LONG on the same signal
bar): the portfolio's exposure is sometimes the cluster's SUM, not one arm's
risk, and nothing displayed that.

- `scripts/morning_status.py` — [3b] now collects open positions across all
  gold arms (dangling OPEN rows = live positions, EA row grammar:
  dir 1=BUY/-1=SELL) and clusters them: same direction, opened within
  900 s = one M15 bar (the shared signal bar by construction). Each exposed
  arm's block prints `live cluster: N arms LONG/SHORT within 15 min (tags)`
  and the section ends with a footer listing every cluster. **Display-only
  by design** — correlation never marks the section unhealthy: the §14 modes
  are certified individually and a shared signal is expected portfolio
  behavior, not drift.
- `tests/test_midas_correlation.py` (11): cluster boundary (inclusive at
  900 s, refused at 901 s), opposite directions never cluster, distant opens
  don't merge through the anchor, LONG+SHORT clusters coexist, collector
  grammar (closed pairs excluded, corrupt rows skipped, missing ledgers
  skipped), and section integration — including that the fixture must build
  each arm's chart from ITS OWN repo .set (building M1t from M1's pins is
  fixture drift, and [3b] correctly flagged it as preset DRIFT).

## [Watchdog reboot-survival: logon-task autostart + single-instance lock] - 2026-09-17

The restart that morning reaped the watchdog loop and the arms ran ~70 min
unguarded; the closeout's "launch the .bat after every reboot" step is now
the machine's job, not the operator's memory:

- `scripts/register_midas_watchdog_task.ps1` — registers the per-user
  scheduled task **MIDAS Watchdog Autostart** (interactive logon trigger,
  RunLevel Limited, no elevation — the user session per §12, never a service
  context) launching the certified `start_midas_watchdog.bat` from the repo
  root. Idempotent re-run replaces the task; `-Unregister` is the off
  switch. Pure ASCII so Windows PowerShell 5.1 parses it without a BOM.
  Registered on the machine 2026-09-17 (State Ready; verified principal/
  trigger/action) and end-to-end: a detached .bat launch booted the loop,
  polled all four arms (action NONE, last_ok refreshed), and survived the
  spawning console.
- `scripts/midas_watchdog.py` — **single-instance lock**: the `--loop` path
  holds `artifacts/midas_watchdog.lock` on an OS handle for its whole life
  (byte-range lock; a crash releases it implicitly — no stale lock exists),
  writes its PID, and a second loop of any origin (logon task + manual
  double-click) exits loudly instead of doubling restart decisions. One-shot
  commands (`--status`, `--pause/--resume`, single checks) never take the
  lock. Live-verified: second `--loop` refused while held, lock free after
  release.
- `tests/test_midas_watchdog.py` (+4, 31 total): acquire/PID write, second
  acquire refused, crash-release semantics, main-loop take/release on
  Ctrl+C, refusal path, and the registration script's contract (per-user
  interactive principal, .bat entry point, no elevation, -Unregister
  present).
- Docs: health guide §3 (what the task is, how to verify/register/remove,
  the lock) and the one-minute routine (reboot step is now "nothing"),
  protocol §12 operator contract (autostart + lock registered).

## [§13 monthly verdict automated: scripts/midas_verdict.py — thresholds frozen, tool read-only] - 2026-09-17

The closeout registered the verdict tool as the next small one; shipped with
the gates as read-only constants so the tool can never redefine them:

- `scripts/midas_verdict.py` — per-arm §13 adjudication from the ledger of
  record: n/totalR/meanR/DD from post-era CLOSE rows (CLOSE-veq path,
  peak-to-trough, like armd_accrual), tag-driven discovery across the whole
  §14 portfolio, and the frozen mapping verbatim (VALIDATED n≥60 ∧ totalR>0 ∧
  DD≤25% ∧ meanR≥0.05; REJECTED n≥60 ∧ (totalR<0 ∨ DD>30% ∨ meanR≤0);
  CONTINUE-UNPROVEN otherwise). **The verdict is computed, never stored** —
  no artifact to drift; `--json` prints the full evidence record for
  citations; `--tag` judges one arm.
- **Structural aborts are evidence-backed, not decorative** (§13's abort rows,
  both directions suppressed): [3b] `preset_identity` DRIFT/UNVERIFIABLE vs
  the arm's own repo .set; §12 watchdog escalation (state ≥3 consecutive
  restups, or DRIFT/ESCALATE last action) or missing §12 artifacts; EA version
  change inside one ledger (distinct ERA-stamp versions = abort); corrupt
  CLOSE rows or a nonpositive-veq row (DD denominator) abort the read. An
  aborted window always shows CONTINUE-UNPROVEN + reasons — a polluted window
  is never judged, so drift can neither launder a VALIDATED nor hide a
  REJECTED (retirement stays data-backed; the family always gets its clean
  window after the certified chain re-accrues).
- `scripts/era.py` — family rule registered: `midastouchai` is per-tick in
  all eras (same shape as V75MacroEngine); MIDASTOUCH ERA stamps carry the EA
  VERSION, consumed for §13 aborts, never as an era divider.
- `scripts/paper_weekly.py` — section [7] runs the monthly verdict every
  Sunday (read-only; no-ledgers is a disclosed skip, never a crash).
- `tests/test_midas_verdict.py` — 27 offline tests: gate values pinned
  verbatim, every verdict boundary (n=59/60, DD=25.0/25.1/30.0/30.1,
  meanR=0/0.049/0.05), DD math, both suppression directions, abort evidence
  chain, discovery gaps, era-registry extension, weekly wiring, CLI JSON.
- First live read (2026-09-17): M1/M1t/M1s/M1m all n=0/60,
  CONTINUE-UNPROVEN, zero aborts — exactly the §13 day-zero expectation.

## [§14 portfolio LIVE: four certified gold arms; tooling upgraded to N-arm] - 2026-09-17

Operator direction: 3–4+ trades/day (the single arm's measured ~0.6/day was
rejected as too passive). Response — widen the frozen forward test to a
**portfolio of four certified strategies** (legal only pre-first-fill;
protocol **Amendment 5 / §14** frozen with the ledger provably at 0 fills,
verbatim gates and constants, modes per the OOS-anchored sweep: ORIGINAL
+ REVERSE_TRIGGER + SHORT_ONLY + MACRO_ONLY ≈ 3.5 trades/day aggregate,
≈+2.0R/2wk; the only busier variant, REVERSE_BOTH, stays excluded for its
measured −19.3R). Shipped:

- `mql5/MIDASTOUCH/MidastouchAI_{M1o,M1t,M1s,M1m}_gold.set` — four certified
  presets (only InpArmTag/InpMode differ; magic identical), copied to
  `MQL5\Presets`.
- `scripts/deploy_portfolio.py` — the certified deploy: flat-check →
  watchdog pause → PID-exact stop → clone chart01 into chart02/03/04 with
  unique ids + per-arm tag/mode → per-arm preset-identity verification
  BEFORE relaunch (all three OK, 30 inputs byte-identical) → relaunch.
  The live M1 arm untouched.
- **Multi-arm watchdog (§14 obligation)**: `midas_arms()` discovers the
  whole portfolio tag-driven; drift attribution matches each arm's pins to
  its own journal banner (mode+session) so an arm is never blamed for a
  neighbor's drift; liveness rides the WORST ledger; ANY remediation is a
  portfolio-wide stop gated on EVERY ledger flat; per-arm re-splice from
  the arm's own preset (`preset_for_tag`). One shared escalation counter.
- **[3b] portfolio**: one health block per arm, each verified against its
  own preset; header numbered when multiple.
- **Flat-check gates**: `v28_sweep_runner.inventory_arms` now inventories
  gold arms beside V75 arms (every paper book gates every stop); parity
  harness prints the portfolio composition.
- **Live state**: 4 arms running — M1 (mode=0), M1t (mode=2), M1s (mode=5),
  M1m (mode=6), all PAPER, all flat, four ledgers born
  (`ERA,MIDAS1.10` + EQ,50.00); watchdog poll NONE across all four; [3b]
  4× green; 82 tests passing. §13 adjudication now per-arm at n≥60 —
  first readings expected in weeks, not months.

## [Tabletop drift drill: both defense legs exercised on a throwaway fixture] - 2026-09-17

- `scripts/midas_drift_drill.py` — a self-contained sandbox drill replaying
  the 09:57-style preset-drift incident against the REAL watchdog and [3b]
  code: chart tamper vs still-pinned running EA (leg asymmetry), drifted
  reboot (watchdog DRIFT → PID stop → certified re-splice w/ backup →
  relaunch), and recovery (RECOVERED + counter reset + [3b] OK).
  All external effects redirected (stop/relaunch stubbed, state/journal/
  chart in `artifacts/_tt_sandbox`, removed after); the driver asserts the
  real chart is byte-identical at exit. Full capture in the thread.

## [Operator health guide for the gold arm] - 2026-09-17

- `docs/MIDASTOUCH_HEALTH_GUIDE.md` — self-service walkthrough of the three
  health surfaces (morning status [3b], the Experts log, the ledger) with
  real captured output, healthy/unhealthy line-by-line tables, the
  two-ledger health questions (alive via mtime, honest via OPEN/CLOSE
  pairing), watchdog artifacts, and the one-minute daily routine.

## [MidastouchAI v1.10: display-only HUD via the certified chain; engine re-certified on the new binary] - 2026-09-17

- `mql5/MIDASTOUCH/MidastouchAI.mq5` — v1.09 → **v1.10**: display-only HUD
  (`Comment`, zero `Comment()` calls before): mode + registry name, session,
  virtual equity / start, position state, trades n/30 gate clock (§13 reads
  at n≥60, shown on the HUD), wins, cumR, and last engine action (open /
  close w/ R, stashed SIGNAL, spread-cap veto, stale-feed skip, live
  LOPEN/LCLOSE). STRICTLY display-only: HUD state is a strict subset of the
  ledger (OPEN/CLOSE/EQ/ERA + pinned inputs); refresh hooks only on
  live-path events (init, 15-min heartbeat, PERTICK OnTick); `HudUpdate()`
  returns immediately in the strategy tester so parity ledgers stay
  byte-identical. Also fixes the stale `#property version` (had said 1.05
  since v1.06; now 1.10, pinned equal to APP_VERSION by test).
- `tests/test_midas_hud.py` — 11 offline source tests pinning the HUD law:
  tester-gating, ledger-backed-state-only allowlist, single `Comment(`,
  BAR-mode functions pristine except BarManage's documented post-close
  epilogue, watchdog-stable banner tokens, no HUD inputs/file access, and
  EA-inputs ≡ preset-keys (30 ≡ 30, splice-chain coupling).
- `scripts/midas_parity.py` — cosmetic: harness prints no longer hardcode
  the EA version.
- **Certified chain executed in order**: compile 0 errors/0 warnings →
  watchdog `--pause` → flat-check (gold ledger flat) → PID-exact terminal
  stop → v1.10 .ex5 deployed to BOTH Experts paths (`MITEMSHUB_AI\` for the
  tester layout, `MIDASTOUCH\` for symmetry) → §13 fresh-ledger abort (prior
  ledger archived `artifacts/paper_ledgers/…pre-v110_20260917_142946.csv`)
  → `set_chart_preset.py` byte-exact re-splice (30 inputs, backup kept) →
  relaunch → boot banner `[MIDAS1.10]` verified pin-for-pin (mode=0,
  session=06-20, execution=PAPER, exec-model=PERTICK), watchdog drift `[]`.
- **Engine re-certified on v1.10** (`artifacts/midas_parity_result_20260917_1435.json`):
  WF REVERSE_DIRECTION — python 151 / +1.474R vs EA v1.10-BAR 151 / +1.478R,
  all keys agreeing, max |dR| = 0.0005R, **first-run PASS** → the HUD is
  behavior-neutral by measurement, not by argument.
- Honesty note: the compile tooling builds in place, so no v1.09 binary or
  source copy survives (the `--Source` is overwritten before the build);
  v1.09's rollback verifier remains the parity harness itself. The v1.10
  delta is enumerated display-only code, pinned by `tests/test_midas_hud.py`.
- End state: arm flat, veq 50.00, `closed: 0/30` — gate clock restarted
  cleanly per §13; watchdog healthy, 0 consecutive restups; suites 77 green.

## [2026-09-17 closeout: drift incidents, watchdog shakedown, parity certification] - 2026-09-17

- `docs/MIDASTOUCH_CLOSEOUT_20260917.md` — full-day closeout in the house
  format: both drift incidents (09:57 unregistered mode-flip, 11:11
  code-defaults reattach) with zero-fills verification in both windows, the
  watchdog shakedown including the on-camera 11:42 auto-remediation
  (detect → stop → re-splice → relaunch → RECOVERED), the 150-vs-147 parity
  root-cause (three stale vintages compared positionally — no live EA defect)
  with the three certificates (WF / OOS / full 8-mode registry — 1,165 keyed
  trades, worst |dR| = 0.0005R), the §13 verdict-rule freeze, and the [3b]
  preset-identity guard. End-of-day state: arm flat at veq 50.00, 0 closed
  trades, watchdog clean, no promotion — ALL-8-MODES NO-SHIP stands.

## [Full-registry parity matrix: 8/8 modes PASS on OOS (protocol §11, Certificate 3)] - 2026-09-17

- `scripts/midas_parity.py` — full-registry matrix (`--mode` repeatable,
  EA mode-enum map, per-mode tester tags + sandbox-ledger rotation,
  one watchdog-paused session; `matrix_verdict()` requires every mode PASS
  and every frozen sweep anchor reproduced). Pinned by 6 new tests
  (mode-code/tag maps, aggregation, anchor reader) — 18 harness tests total.
- **Certificate 3** (`artifacts/midas_parity_matrix_oos_20260917_1348.json`):
  8/8 registry modes PASS over OOS in real ticks — 1,165 vs 1,165 keyed
  trades, worst per-mode max |dR| = 0.0005R, all 8 sweep anchors
  reproduced exactly (losers included: REVERSE_BOTH −19.307R,
  LONG_ONLY −1.950R). Engine parity now covers the whole registry;
  ALL-8-MODES NO-SHIP stands, no promotion.

## [Second parity certificate: OOS window PASS first-run (protocol §11, Certificate 2)] - 2026-09-17

- `scripts/midas_parity.py` — window-parametrized (`--window wf|oos`,
  per-window tester tag/calendar, EA mode-enum map; WF certificate defaults
  untouched, 12 pinned harness tests still green).
- **OOS certificate PASS on the first run**
  (`artifacts/midas_parity_result_20260917_1336.json`): python 108 / +8.199R
  vs EA v1.09-BAR 108 / +8.202R — count equal, all 108 pairs keyed identical
  (open/close times, direction), max |dR| = 0.0005R ≤ 0.01R. Cross-check:
  the python regen reproduces the sweep's OOS anchor (n=108, +8.199R)
  exactly. Engine parity now certified on both sides of the window split —
  the harness is not overfit to WF. Scope unchanged: engine parity only,
  ALL-8-MODES NO-SHIP stands.

## [M1 forward verdict rule frozen BEFORE first fill (protocol §13, Amendment 4)] - 2026-09-17

- `docs/MIDASTOUCH_PROTOCOL.md` §13 — arm-D rulebook ported verbatim:
  VALIDATED n≥60 AND totalR>0 AND DD≤25% AND meanR≥0.05; CONTINUE-UNPROVEN
  for n<60 / gray zones; REJECTED n≥60 AND (totalR<0 OR DD>30% OR meanR≤0).
  Frozen with the ledger holding zero fills (verified at write time).
  Monthly readings from 2026-10-01; weekly [3b] glances are ops, never
  judgment. Structural aborts (fresh-ledger restart): [3b] ledger problems,
  preset DRIFT, escalated watchdog, loaded-but-dead engine, EA version
  change. Scope honesty: the arm tests the FAMILY (unselected ORIGINAL),
  not a promotable mode — the ALL-8-MODES NO-SHIP verdict stands either
  way; VALIDATED advances to the pre-registered live-sizing path only.
- Basis disclosure carried from arm D: min-lot stop-risk ≈$5.87 on the $50
  book (≈11.7%/trade, tolerated); R statistics are basis-invariant.
- Closeout next-session snapshot updated: (c) is now "adjudication
  pre-registered, §13", first reading 2026-10-01.

## [Morning status [3b] preset-identity check: chart inputs verified byte-exact vs repo .set] - 2026-09-17

- `scripts/morning_status.py` — new `preset_identity()` in [3b]: all 30 EA
  inputs on the chart .chr compared byte-exact against
  `mql5/MIDASTOUCH/MidastouchAI_M1_gold.set` (missing/extra keys, value
  differences incl. reformatting, conflicting duplicate rows). Drift prints
  `preset DRIFT ...` and marks the arm unhealthy; unreadable repo preset
  reports UNVERIFIABLE (fail-closed — a lost pins file is the failure class
  this guard exists to catch). Complements the watchdog's banner leg (4
  pins, auto-remediation) as the independent full-inputs observation layer
  (protocol §12, closeout addendum 3).
- `tests/test_morning_status_preset.py` — 11 cases: pure semantics (OK on
  byte-identical, drift on pinned change / reformatting / missing / extra /
  duplicate, UNVERIFIABLE on unreadable pins, group headers ignored) plus
  two end-to-end [3b] tests; chart fixtures self-maintained against the
  real .set so a pin edit cannot silently invalidate them.

## [MIDAS watchdog registered as standing infrastructure (protocol §12) with parity-session pause discipline] - 2026-09-17

- `docs/MIDASTOUCH_PROTOCOL.md` §12 — registers `scripts/midas_watchdog.py`
  as permanent paper-arm infrastructure: liveness leg (ledger-mtime
  heartbeat, 35+10 min tiers, flat-check-gated PID-exact restart, escalate
  at 3, weekend guard), config-drift leg (journal banner vs repo preset
  pins, re-splice before relaunch, LIVE-is-drift, broken-pins observe-only),
  and the **operative pause discipline**: `--pause`/`--resume` around every
  parity/tester session or deliberate terminal stop; the certified parity
  harness holds the marker itself and never lifts a manual pause; pausing
  does not sanction hand edits on the live chart (certified chain only).
- Operator contract documented: user-launched `start_midas_watchdog.bat`
  (`--loop 600`), log/state artifacts; `--status`/`--dry-run`/`--force`/
  `--reset-state` for inspection and emergencies.
- Closeout addendum (2) appended: watchdog shakedown history (caught the
  11:11 drift live, full remediation loop on camera), snapshot of what
  runs now, artifacts index refreshed (EA v1.09, parity v2 + certificate,
  watchdog paths).

## [MIDAS parity certified: 150-vs-147 root-caused to stale vintages + positional zip; keyed harness v2 ships PASS] - 2026-09-17

- **Root cause of the recorded 150-vs-147 parity failure** (run3): three
  stale vintages, not an EA defect. The frozen python artifact reproduces
  only under pre-amendment-2 Wilder ATR (verified exact 147-match); the
  SMA-ATR engine of record yields 151 trades / +1.47R on WF. The run3
  harness predated the v1.04+ BAR-parity engine (no InpBarModel, no
  InpWindowStart/End pins) and zipped trades positionally, quantizing
  SL/TP/timeout outcomes against the wrong partner after trade 0.
- `scripts/midas_parity.py` v2 — regenerates python R from the engine of
  record (selftest-gated), pins the full BAR contract (InpBarModel=true,
  InpWindowStart/End = python t0/t1), aligns trades **by key**
  (open/close ct + direction; positional zip is fail-closed illegal
  evidence), reads EA evidence from the agent sandbox ledger (ticket join)
  with journal fallback, rotates stale sandbox ledgers before each pass,
  extends tester ToDate past the research window (03.31 truncation dropped
  the WF tail trade; certified passes use 04.03), flat-checks the gold
  ledger explicitly (inventory_arms only sees V75 charts), and pauses the
  paper arm's watchdog for the session.
- **CERTIFIED PASS** (`artifacts/midas_parity_result_20260917_1258.json`):
  python 151 / +1.474R vs EA v1.09-BAR 151 / +1.478R — all 151 pairs keyed
  identical on open/close times and direction, max |dR| = 0.0005R ≤ 0.01R.
  Scope: ENGINE parity — the ALL-8-MODES NO-SHIP verdict stands; no
  promotion (docs/MIDASTOUCH_PROTOCOL.md §11, Amendment 3, append-only).
- `tests/test_midas_parity.py` — 12 offline tests pinning the keyed
  alignment law (key agreement required even when R matches; keyless
  journal sources can never PASS), and the v2 input contract.

## [MIDASTOUCH gold-arm watchdog shipped: heartbeat auto-recovery + banner-vs-pins drift remediation] - 2026-09-17

- `scripts/midas_watchdog.py` — the EA's 15-min ledger heartbeat (OnTimer EQ
  touch, every terminal state) is the liveness signal. Staleness beyond
  ~45 min triggers a flat-check-gated, PID-exact terminal restart (the
  v28_sweep_runner discipline: a dangling OPEN or an unreadable/rowless
  ledger fails closed — never restart a book we cannot prove is flat),
  escalating after 3 consecutive restups without observed recovery.
- **Config-drift leg:** the terminal journal's latest `MIDASTOUCH started`
  banner is compared against the repo preset pins (mode / session /
  execution / exec-model). Any mismatch — e.g. the 11:11 code-defaults
  reattach (mode=1, $1000 basis, 25 min after the pinned restore) — is
  remediated by the same restart **with the pins re-spliced into the chart
  before relaunch** (a defaults-running instance would clobber the chart on
  graceful exit). `execution=LIVE` is drift by definition. Caught and fixed
  live during the shakedown: drift detected → stop → resplice → relaunch →
  pinned banner 11:42:52 → `RECOVERED` counter reset on the next poll.
- Guards: weekend no-restart (flat book, closed market), pause marker for
  parity sessions (`--pause`/`--resume`), `--dry-run`/`--force`, escalation
  state + last-action artifacts (`artifacts/midas_watchdog_state.json`,
  `midas_watchdog_last_action.json`).
- `morning_status` [3b] gains the watchdog line (escalation = arm
  unhealthy); `start_midas_watchdog.bat` runs the 10-min loop from the
  user's session (agent-spawned processes get reaped — start it yourself).
- Tests: 21 offline tests pinning the tiers, the flat gate, weekend and
  escalation guards, fail-closed parsing, banner drift parsing, the
  resplice (with restore-on-verify-fail), and observe-only pin errors;
  37/37 with the morning-status suite.

## [MIDASTOUCH M1 arm: config drift caught and restored to pins; parity build v1.09 synced into the repo] - 2026-09-17

- **Drift caught:** the gold paper arm's last attach (09:57) ran `mode=2
  REVERSE_TRIGGER, session 12-16` — an unregistered variant left by the
  interrupted parity session (v1.04→v1.09 iterations re-used the live chart
  as a test bench). Zero fills in the drift window; ledger integrity intact.
- **Restored via the certified chain:** `MidastouchAI_M1_gold.set` rewritten
  as the complete 30-key pin set (mode=0 ORIGINAL, session 06-20, $50
  virtual, PERTICK, `InpLiveExecution=false` hard), spliced with
  `set_chart_preset.py` (chart backup kept), terminal recycled (flat-checked
  first). Boot banner 10:57:15 verified pin-for-pin; morning status [3b]
  green (veq 50.00, flat, 0/30 clock not started).
- **Repo synced:** deployed v1.09 source (BAR-mode parity model + live-order
  path behind `InpLiveExecution`, window-enforced BAR replay, watchdog
  heartbeat) copied from the terminal tree to `mql5/MIDASTOUCH/
  MidastouchAI.mq5` — the repo had been stale at v1.03.
- **Standing rule restated:** parity passes run in the tester only; the live
  chart changes exclusively through the preset + splice tool + banner check.
- Live-trading answer unchanged and grounded: **not yet** — zero closed
  forward trades exist under the frozen gates; the clock starts at the first
  fill on the now-clean arm.

## [MIDASTOUCH: gold pivot complete — indices program stopped & archived, gold engine v1.03 paper-live on XAUUSDmicro] - 2026-09-16

- **Program pivot per operator directive**: synthetic indices (V75/V28) work
  stopped — scheduled tasks disabled, all four paper arms flat-checked and
  their charts disarmed across all three terminal installs (backups kept),
  five ledgers archived with checksums (`archive/v75_ledgers_20260916/`,
  closeout `docs/V75_CLOSEOUT_20260916.md`). Nothing deleted.
- **Ground-truth probe** (`scripts/deriv_symbol_probe.py`): XAUUSD confirmed
  on the real account; **cost toll 0.69% of a typical H1 stop** (vs 5.6%
  that killed V75-1s). Floor math: XAUUSD min-lot risks ~$49.6/trade, but
  **XAUUSDmicro risks ~$5.0/trade → tradeable at the real $50.22 account**.
  Feed: H1 continuous 2024-04-10→2026-09-16 (one disclosed 112-day broker
  hole before that); validated history in `data/forex/xauusd/`.
- **Playbook** (`docs/MIDASTOUCH_GOLD_PLAYBOOK.md`) measured from our own
  14,414 H1 bars: vol peak 13:00–15:00 UTC, spread ~$0.10 steady ($0.17
  rollover worst).
- **Frozen protocol + honest sweep** (`docs/MIDASTOUCH_PROTOCOL.md`,
  `scripts/midas_sweep.py`): gates frozen pre-run, 8 modes × 4 windows on
  50k M15 bars — **all 8 NO-SHIP** (best SHORT_ONLY PF 1.343 refused by G6
  era-alternation). Two append-only amendments (pending-fill fidelity;
  bounded SMA-ATR parity fix forcing a full symmetric re-sweep — no gate
  shopping).
- **`MidastouchAI.mq5` v1.03** (`mql5/MIDASTOUCH/`): gold-pinned by charter,
  paper-default, compiles 0/0. Parity campaign vs the python engine:
  +1-bar fill skew fixed (same-bar evaluate-and-fill); Wilder-ATR
  history-depth divergence root-caused → bounded SMA-ATR(14) on both sides,
  after which **entries align exactly**; outcome-level drift remains (150
  vs 147) — certification parity NOT yet claimed, next session's task.
- **Gold paper arm LIVE**: chart01 = XAUUSDmicro M15, MidastouchAI v1.03,
  paper, $50 virtual equity mirroring the real account floor. Banner
  `[MIDAS1.03] … symbol=XAUUSDmicro (GOLD-OK) … execution=PAPER`, ledger
  `MIDASTOUCH_paper_XAUUSDmicro_M1.csv` initialized.
- `morning_status.py` section **[3b] MIDASTOUCH GOLD ARM** added (chart
  health, gold-charter check, ledger age/integrity/live/R); 16/16 existing
  tests pass. Full record: `docs/MIDASTOUCH_CLOSEOUT_20260916.md`.

## [A2 ATTACHED AND TRADING — the forward clock is running; §11 regime hypothesis pre-registered, run, and REFUSED] - 2026-09-16

- **Arm A2 is live** (21:15:32 terminal-local): the attach that was queued as
  "an operator step" turned out to be automatable — stopped the 49E0 terminal,
  spliced the A2 expert block (built from the verifier-pinned preset, all 28
  keys, magic/tag/tp2 asserted) into `chart01.chr` ahead of the window
  section, relaunched. Banner: `[v28.10] MITEMSHUB V75 MACRO started |
  mode=3 | experiment=ARM_A2_REVERSE_BOTH_TP20 | … | risk=1.00%`, PAPER
  resume $1000.00, FILTER TABLE consult-only. Gate 4 recorded — all four
  start-day gates DONE. Pre-edit chart backup:
  `<data folder>/…chart01.chr.pre_A2_20260916.bak`.
- Arm D resumed cleanly through the attach and two subsequent research
  stop/start cycles; the sweep runner's ledger-flat verification passed on
  every cycle (A2 flat, D flat, zero dangling OPENs).
- Labels: `morning_status.MAGICS` and `v28_sweep_runner.KNOWN_MAGICS` now map
  7788075 -> A2_fwd (arm A retired, archived). 30/30 on those suites.
- **§11 regime test** (the REVERSE_TRIGGER gem): pre-registered BEFORE any
  conditional data existed (two frozen candidates: R1 macro-direction state,
  R2 ATR-percentile HIGH/LOW; frozen gate: uplift >= +0.10R, CI excluding
  zero, both split halves, n>=40). Built `v28_regime_rerun.py` (tagged
  single-sided passes + terminal restore, flat-check fail-closed) and
  `v28_regime_test.py` (EA-faithful macro oracle from M15 bars — the
  ReadMacroDirection close[1]-vs-EMA20 rule — with fail-closed coverage
  after the fresh90 bars file silently answered 2025 trades with 2026 bars).
  Deterministic re-runs matched the registry exactly (267/232/521 fills).
  **VERDICT: REFUSED** — R1 negative in every window; R2 sign-stable in wf
  but CI-spanning and significantly negative in is180. The is-window losses
  DO classify (HIGH-vol), but that regime carried the wf gains: the
  conditional edge itself flips across eras. No threshold-shopping; the
  ALIGNED_DOWN observation is a seed for a new registration only.
- Artifacts: `regime_rerun_*_*.json`, `regime_test_verdict.json`,
  protocol §11 + §11.1.

## [ML signal filter rides on A2 from day one: bucket table built and shipped PASSIVE; EA consult leg live; veto authority gate-frozen] - 2026-09-16

- The §10 recon rewrote the design before anything shipped: the 15-feature
  GBC's P(win) does not rank out-of-window (calibration flips between folds;
  mean wf AUC 0.476) — shipping it as the floor-mode bar would have put
  demonstrated non-skill in charge of vetoes. But a large SIMPLE structure
  exists (side x 6h-block buckets span P(win) 0.32-0.90 vs 0.56 baseline),
  and the sweep contains only M30_REVERSED_EXTREME signals, so conviction
  class stays rule-based.
- `scripts/signal_filter_table.py` (protocol §10.7, frozen on the recon):
  bucket table with Laplace shrinkage (alpha=5), min-n=15 with GLOBAL
  fallback, muted buckets ship exactly 0.50 ("no opinion"), and a five-leg
  activation gate (n>=500, coverage>=50%, wf AUC>0.55 in >=5/6 folds, mean
  >0.55, worst fold >= -0.05R). First build: gate FAIL (4/5 legs fail) ->
  shipped **PASSIVE** (8 buckets + GLOBAL fallback) to
  mql5/MITEMSHUB_AI/MitemshubAI_filter_table_A2.csv and the 49E0 Files dir.
- EA: `LoadFilterTable` (banner-proven: FILTER TABLE line names buckets,
  global rate, ACTIVATION, and consult-only status), `FilterConsultAllows`
  in the floor-mode policy — prints FILTER CONSULT and writes FCONSULT
  ledger rows on every floor-mode evaluation; in PASSIVE it can NEVER veto
  (mirrored and pinned by test, including p=0.0 and the muted 0.50 case).
  Veto authority activates only on an ACTIVATION=ACTIVE file, which only
  `--certify` on gate-passing fresh re-run data can produce.
- Forward build compiled clean; parity re-run PASS (n=27, max |dR|=0.0063) —
  the tester path is untouched by the paper-only consult code. 13 new tests;
  131/131 across the seven touched suites. Protocol §10.7, ARM_A2_RESTART
  §2 note, and the silent-OSError hardening note for v28_signal_filter
  (observed: two external pipeline runs read n=0 mid-parity when the agent
  log was locked — read_log must distinguish empty from unreadable before
  the builder can trust a zero).

## [Floor-zone boundaries computed live and wired into morning status section [4]] - 2026-09-16

- New `scripts/floor_zone.py`: the exact boundary chain per engine x symbol —
  min-lot dollar risk from the EA's own formula ((stop / tick_size) x
  calibrated tick value x volume_min), floor onset = risk / risk_fraction,
  STRANGULATION crossover = risk / budget (15%), per-arm halt floor =
  window-start x (1 - 30%). Tick value mirrors CalibratedTickValue() with the
  5% identity rule — verified load-bearing live: the raw broker value (0.0001)
  understates V75 risk 100x vs the geometric value (0.01). ATR is Wilder-
  smoothed at the last CLOSED bar of each engine's anchor TF (v28/v75macro =
  2.0x H1(14); pullback = 1.7x M15(14) with the swing-widening disclosure —
  a floor estimate, never hidden). MT5 python access is injected and
  fail-closed: no terminal -> disclosed UNKNOWN, never a guessed boundary.
- Morning status gains section [4] FLOOR ZONES: per-engine boundary rows and
  a per-arm verdict (TRADING / FLOOR_MODE / STRANGULATED / HALTED / UNKNOWN)
  from the ledger veq; STRANGULATED/HALTED flag unhealthy for --strict.
- Live first read (2026-09-16): pullback min-lot $5.07 -> strangulation
  $33.82, B_tp24 veq $40.20 = FLOOR_MODE; v28 min-lot $12.75 -> onset
  $1,274.84, strangulation $84.99; D_fwd/C_v75 UNKNOWN pre-first-fill.
  Numbers reconcile with the observed guard firings ($4.64-$6.10 at Sep-15
  ATR -> $30.93 crossover, the arm-A anchor, pinned as a test).
- Two findings the tests now pin: (1) for a $50-start pullback arm the halt
  floor ($35) sits ABOVE the strangulation crossover ($30.93-$33.82) — the
  structural-abort halt fires BEFORE the slow strangle completes, which is
  the policy intent (restart, don't die locked out); (2) at current ATR the
  v28 floor-onset ($1,274.84) is ABOVE A2's $1,000 basis — A2 will run in
  floor mode from day one, i.e. min-lot trades at ~1.28% risk under the
  conviction bar and budget guard (functioning, not strangled; the guard
  cap is $150 vs ~$12.75 min-lot risk). 13 new tests; 118/118 across the
  six touched suites; go-live verifier PASS.

## [Floor-mode policy implemented in the engine guard: hard drawdown stop + raised entry bar replace the silent veto; parity re-verified] - 2026-09-16

- The promised strangulation-zone fix is now engine code. Floor mode = the
  broker minimum lot risking more than the strategy fraction of virtual
  equity (paper path only; the tester path keeps the research contract
  byte-faithful). In floor mode the paper engine takes the minimum lot ONLY
  if two new gates pass, both printing their operands loudly:
  (1) FLOOR MODE HALT — virtual equity at or below 30% below window-start
  equity (g_paper_start, preserved across ledger resume: no drawdown
  laundering) halts entries; restart is a structural abort on a fresh ledger;
  (2) FLOOR MODE conviction bar — only strong BB+RSI springboards
  (M30_REVERSED_BB_UPPER/LOWER+RSI class) pay the floor's ~10x risk premium;
  plain *_EXTREME signals stand down. The account-budget guard then applies
  exactly as before, print shape untouched for funnel_diff.
- Order enforced and pinned: identity evidence (g_entry_trigger set before
  sizing on the paper path) -> halt -> conviction -> budget -> take min lot.
  A2's $1,000 basis never enters floor mode; the policy exists so the
  account can trade at ANY balance — the user's principle, in code.
- Pinned: A2 preset carries InpMaxTotalRiskPct=15.0 (now explicit, was an
  implicit default), InpFloorModeMaxDDPct=30.0, InpFloorModeConviction=true;
  verifier pins extended and PASS; two new tests pin the preset values and
  the engine contract (policy order, g_paper_start baseline, tester-path
  separation). Compile 0 errors/0 warnings; parity re-run PASS (n=27, max
  |dR|=0.0063) proving the tester path untouched; 112/112 across the six
  touched suites.

## [Arm A stopped and its slot freed for A2: EA disarmed from FB9A profile, final ledger verified in artifacts] - 2026-09-16

- Ground-truth first: arm A runs on FB9A (Program Files MT5, co-hosting arm
  C) — and that terminal was ALREADY stopped (no process; last EA journal
  write 17:47 today, paper CSV frozen since 09-15 21:44). The live-stop
  requirement was therefore already satisfied; the remaining risk was the
  saved profile: FB9A's Default `chart01.chr` still carried arm A's expert
  block (MitemshubAI.ex5, InpMagic=7788075) and would have auto-resumed the
  strangled arm on next launch.
- Disarmed with a byte-precise splice of the `<expert>…</expert>` block
  (magic-asserted before cutting; BOM and chart body verified after:
  58,540 -> 52,442 bytes). Arm C's expert on chart03 verified untouched.
  Pre-edit chart backup: `artifacts/paper_ledgers/armA_FB9A_chart01_chr_backup_20260916.chr`
  (sha256 4ced7443…). Final ledger archive re-verified byte-identical to the
  FB9A source (sha256 393c0830…, 43 rows, last row the v26.39 ERA marker).
- Fleet map corrected on the record: 49E0 = MitemshubMT5_B install hosting
  arm D (running, flat: 0 outstanding OPENs), 71BF = MitemshubMT5_C (stopped,
  arm B), FB9A = Program Files MT5 (stopped; arm C armed, arm A now disarmed).
  The A2 chart slot is 49E0's spare Vol75 chart (EA-less) — attaching A2
  needs no FB9A action. `morning_status.py` inventory is discovery-based, so
  arm A drops out automatically; its stale co-hosting comment updated.
  `verify_go_live_artifacts.py` PASS re-confirmed after the change.

## [ML signal-filter track started: protocol §10 pre-registered, pipeline built, first walk-forward gate run = FAIL (no ship)] - 2026-09-16

- **§10 pre-registered BEFORE any training** (V28_RESEARCH_PROTOCOL.md):
  decision-time features only (last CLOSED M15 bar; peak_r/hold/exit reason
  are outcomes and forbidden), walk-forward expanding folds with a 1-month
  embargo, a 30-trades-per-(month × geometry-cell) group cap against the
  sweep's re-run duplication, frozen sklearn config, and a mechanical ship
  gate (≥5/6 folds improved, aggregate uplift ≥ +0.10R, keep-rate ≥ 0.35).
  Deployment order frozen: wf gate → fresh re-run check → shadow on arm A2 →
  only then a preset amendment shipping a frozen P(win)-bucket table.
- **Dataset honestly counted: 799/8,426 trades (9.5%) carry decision-time
  journal evidence.** The registry's 8,426 trades carry money-PnL arrays only;
  per-trade telemetry (OPEN/CLOSE lines: side, trigger, entry/SL/TP, R,
  peak_r, hold, exit reason) exists only where agent journals survive — today
  that is 937 paired trades, of which 817 join REVERSE_BOTH rows (12 OOS-role
  excluded by rule, 108 no-registry-row) and 799 featurize inside bar
  coverage. Coverage grows ONLY by deterministic §2 re-runs; every report
  prints the ratio.
- **First walk-forward run: gate FAIL — ships nothing.** 2/6 folds improved;
  aggregate uplift −0.025R vs the take-everything baseline; keep-rate 0.73
  passed. The remaining folds' expR is dominated by a few fat wins the model
  cannot see coming from decision-time features at this coverage. Per §10.4
  there is no re-tuning against these folds; the pipeline is deterministic
  (seeded) and reproduces the verdict exactly on re-run.
- New `scripts/v28_signal_filter.py` (journal parsing against the real agent
  log shapes — reason-word CLOSE lines, mid-line sim timestamps — registry
  join with full coverage accounting, ATR/RSI/range/vol-regime decision-time
  features, purged folds, gate) + 17 offline tests (real-shape parsing pins,
  leakage pin: perturbing the entry bar must not move the features, embargo
  and cap discipline, frozen gate constants, synthetic end-to-end).
  173/173 across the eight touched suites.

## [Forward build MitemshubAI_v28_fwd assembled, compiled, and PASSED parity] - 2026-09-16

- **The A2 blocker is cleared.** `mql5/MITEMSHUB_AI/MitemshubAI_v28_fwd.mq5`
  (APP_VERSION 28.10): v28 strategy core verbatim + the v26.40 paper module
  ported (virtual equity, per-tick hard SL/TP mirror with STOP-before-TP,
  tagged ledger, fleet-mirror account guard, floor-mode sizing so the account
  is tradeable at any balance) + the per-close `Trade R:` parity line. Compiled
  clean: 0 errors, 0 warnings.
- **Parity: PASS** (`artifacts/v28_research/armE_parity_20260916_181219Z.json`):
  research `[v28.00]` vs forward `[v28.10]` on the held wf window with identical
  inputs — 27/27 trades aligned in order, max |dR|=0.0063 ≤ 0.02, totalR +3.0280
  vs +3.0293 (|d|=0.0013 ≤ 0.05), input pins verified from both reports. §2's
  byte-faithful claim is now measured, not asserted. A2 start-gate 1 SATISFIED.
- **The harness's fail-closed design earned its keep twice**: the first live
  run came back INCONCLUSIVE because (a) no EA ever emitted the `Trade R:`
  line parity requires — the forward build now emits it, and (b) the agent's
  flush lag truncated the journal read (13 of 27 lines) and the identity parser
  didn't know the MITEMSHUB banner. Evidence layer rebuilt: tag-addressed
  journal segments (init banner `experiment=<tag>` bounds the pass),
  sign-tolerant regexes (`%+.4f` prints a leading `+` — the original `-?`
  class parsed zero forward lines), CLOSE-line R fallback for the research
  build (which has no Trade R line), and a flush-lag stability loop that
  stops once the R count is stable across two reads. 6 new tests pin the
  contracts the live run earned; 156/156 across the seven touched suites.

## [ARM A2 RESTART authorized: REVERSE_BOTH tp2.0 at a $1,000 basis; arm E superseded; strangulation diagnosis closed the loop] - 2026-09-16

- **User decision (2026-09-16)**, following the full program audit: arm A
  (pullback, TPx1.8, $50 basis) is structurally dead — 14 forward trades,
  -4.16R, DD 55%, and BELOW the strangulation crossover ($30.93 needed vs
  $30.73 held): it can never trade again at its config. Arms A+B are the
  pullback family's forward record: -6.2R over 24 trades. The restart
  repurposes arm A's window and fleet slot for the program's only supported
  positive finding: **V28 REVERSE_BOTH sl2.0/tp2.0/h180/r1%**.
- **docs/ARM_A2_RESTART.md** frozen BEFORE any A2 data: basis change
  rationale ($50 virtual makes min-lot ~10% risk; $1,000 makes it ~0.5% —
  an accounting unit, not capital; stats stay R-denominated), arm identity
  (magic 7788075 = arm A's ORIGINAL slot, tag A2, fresh ledger + clock),
  arm-D verdict gates verbatim, plus a NEW standing structural abort: the
  budget guard's effective cap below observed min-lot risk for 14
  consecutive days = restart, not pause. Expected duration 7-15 months,
  but the clock starts when the build lands — not after arm D adjudicates.
- **Arm E superseded (append-only note in its proposal)**: same candidate,
  amended start gate; its build contract + parity harness + verifier design
  carry over to A2 unchanged in content. Arm E never opened a window.
- **`MitemshubAI_VOL75_ARM_A2.set`** pre-drafted (build contract): tp2.0
  surface, magic 7788075, tag A2, $1,000 paper equity, fleet CSV without
  the retired arm-E magic. Two near-miss errors caught before they
  propagated: the first draft assigned arm B's magic (7788100) to A2 —
  collision with the live arm B; and the retired 7788175 initially lingered
  in the fleet CSV.
- **Accrual registry**: E retired, A2 registered pre-start (start=None,
  _A2.csv glob, fails closed); verifier `verify_arm_a2_preset` +
  `verify_arm_a2_consistency` (parity-pin equality, registry pre-start);
  weekly leg iterates the registry so A2 joins automatically on start day.
- Tests retargeted and green: 46/46 in the two touched suites; go-live
  verifier PASS with A2 pins live.

## [Arm-E preset pre-drafted + verifier pins: every start-day artifact now exists except the init banner] - 2026-09-16

- **`mql5/MITEMSHUB_AI/MitemshubAI_VOL75_ARM_E.set`** pre-drafted as a BUILD
  CONTRACT (the forward EA does not exist yet): the frozen tp2.0 v28 strategy
  surface (mode 3, sl 2.0 / tp 2.0 / hold 180 / risk 1%), paper-only, magic
  **7788175** (+25 offset; collision-free beside A/B/C/D), tag E (suffixes
  all Files output so the accrual registry's `_E.csv` glob can only match
  arm E), fleet CSV extended with E's magic, tick recorder off (arm B owns
  the shared file), 24/7 session. The verifier itself caught the first
  draft's inline `;` comments — MT5 .set values must be bare; commentary now
  lives on its own lines.
- **`verify_arm_e_preset`** added to `scripts/verify_go_live_artifacts.py`
  (fail-closed pin set mirroring arm-D's verifier) plus
  **`verify_arm_e_consistency`**: the preset's strategy surface must equal
  `build_parity.INPUT_PINS` exactly (parity run and forward preset test the
  SAME candidate or the precondition is meaningless), and the accrual
  registry must hold arm E PRE-START (start=None, `_E.csv` glob) — starting
  the clock without the parity pass + banner now fails verification.
- Pinned by two new tests (paper-safe + frozen pins + bare values +
  fleet membership; cross-artifact consistency incl. parity-pin equality).
  Go-live verifier: PASS with the new checks live; doc §8 .set line filled;
  136/136 across the six suites.

## [Build-parity shadow-window harness built for arm-E's §3 hard start precondition] - 2026-09-16

- **`scripts/build_parity.py`** (built pre-start, designed and frozen before
  first use): runs the research build (`MitemshubAI_v28`) and the forward
  build on IDENTICAL inputs — the exact §3 pinned tp2.0 surface via
  `candidate_inputs()` — over the same held shadow window (default `wf`),
  then diffs the two trade sets per trade: (side, entry_time) must align in
  order and per-trade R must match within frozen tolerances (0.02R per trade,
  0.05R cumulative, n≥10 — tolerance cannot be laundered across many trades).
- **Verdict classes, mechanical and fail-closed**: PASS / FAIL_TRADE_SET /
  FAIL_R_SEQUENCE / INCONCLUSIVE_{ZERO_TRADES,LOW_TRADES,EVIDENCE} — missing
  identity lines, report/journal R disagreement, or unparseable evidence are
  INCONCLUSIVE, never "passing"; inconclusive never opens the window.
- **Guards**: the `oos` block is refused outright (spent one-shot window);
  research==forward is refused (two runs of one ex5 certify nothing); both
  .ex5 files must exist BEFORE the terminal is stopped (never stop a live
  arm for a run that cannot happen); both passes' REPORT input dumps must
  carry the §3 pins (numeric-normalized — what actually ran, not the INI).
- **Terminal discipline**: reuses the sweep runner's own — terminal identity,
  arm inventory, every ledger flat (override recorded), stop, both passes,
  relaunch — and the registry is NOT touched (parity is a precondition
  artifact, not a §5 experiment). Receipt: `artifacts/v28_research/armE_parity_*`.
- **Test-pinned** (17 offline tests): normalization alignment + disagreement
  refusal, every verdict class, cumulative-drift laundering case, input pins
  (exact + numeric-equivalent + drift + missing), all three pre-terminal
  refuses, frozen exit codes (0/10/11), artifact naming. 134/134 across the
  six suites; arm-E §3/§8 updated with the start-day command.

## [armd_accrual generalized to an ARMS registry: arm E supported pre-start, Sunday leg iterates every registered arm] - 2026-09-16

- **`scripts/armd_accrual.py` is now the all-arms forward-test accrual tracker**
  (per the arm-E pre-draft §6 note, landed pre-start rather than at start):
  `ARMS` declares each arm's doc citation, pre-registered gates, window start,
  ledger glob, and accrual artifact. `accrue(append, force, arm="D")` keeps
  the old arm-D contract byte-compatible; the CLI gains `--arm` (default D).
- **Arm E registered pre-start, failing closed**: gates frozen verbatim from
  arm D (`ARME_TP20_FORWARD_PROPOSAL` §4), `start: None`, ledger glob
  `SET-ON-START-DAY*` — `accrue(arm="E")` raises SystemExit until start day,
  so no zero row and no clock can start by accident. First successful accrual
  records `window_start=<date>` in-row and derives the clock from it (§8's
  only registry actions on start day: real terminal id + confirmed init date).
- **Rows carry the arm tag; artifacts are per-arm** (ARMD_ACCRUAL.jsonl /
  ARME_ACCRUAL.jsonl) — independent windows never blend. Today's D row
  force-stamped once to complete its tag.
- **Weekly leg §[6] generalized**: iterates `sorted(ARMS)` with per-arm
  SystemExit isolation (pre-start E degrades to a recorded `unavailable`
  note), section key renamed `armd_accrual` -> `accrual` with `by_arm`, and
  NEXT ACTIONS now name the arm each VALIDATED/REJECTED verdict belongs to.
  Live run proven: D accrues, E refused loudly, leg completed.
- Tests: registry freeze (verbatim citations, gate identity), E pre-start
  fail-closed, E first-accrual window-start stamping, per-arm artifact
  isolation, weekly-leg structural pins. 117/117 across the five suites.

## [Account-guard post-v26.37 firings reclassified: designed vetoes, not defects — funnel-diff classifier replaced with operand+ledger taxonomy] - 2026-09-16

- **Investigation verdict: classification bug, not guard defect.** The drill-era
  rule ("any post-v26.37 firing = DEFECTIVE") mis-flagged correct vetoes:
  - 2026-09-15 19:30:00 (v26.37, new $6.10 > cap $4.61) and 20:15:00 (v26.38,
    new $4.64 > cap $4.61) — both on the FIXED builds, `fleet $0.00` truthful
    (ledger: no position open), cap $4.61 = $30.73 × 15% exactly (arm A virtual
    equity after that day's −1.271R close; `InpMaxTotalRiskPct=15` from the
    chart surface). The candidates were min-lot entries at 19.9% of equity —
    correctly refused by the **account-budget guard** (the documented
    small-account/strangulation regime), not the fleet-mirror guard.
  - Two further firings today (15:15/15:30, v26.39) classify identically.
- **Classifier rewritten** (`scripts/funnel_diff.py`): per-firing classification
  from the firing line's own operands (build, fleet/new/cap) + the host arm's
  ledger state at the firing instant (OPEN/CLOSE sequence pairing, single-
  position book). Taxonomy: position-open ∧ fleet≈$0 → DEFECT (mirror blind);
  no-position ∧ fleet>$0 → DEFECT (phantom fleet); otherwise WORKING (designed
  veto). Unparseable time fails to UNCLASSIFIED; pre-deploy firings keep the
  closed $0-basis class; anything unprovable never silently reads WORKING.
- Artifact of record rewritten: `funnel_diff_20260916.json` — account-guard row
  now "CLASSIFIED: designed vetoes ... not defects"; summary flags only
  `paused` (pre-existing LOW-COUNT row, unchanged).
- Pinned by `tests/test_funnel_diff_guard.py` (8 tests: the four live WORKING
  firings, both DEFECT mechanical cases, fail-closed paths, frozen deploy
  boundary, ledger pairing). Suite green: 113/113 across the five project
  suites.

## [Dead scheduled tasks deregistered: MQL5Verify, SyntheticIndicesLiveAutoScorer, SyntheticIndicesLiveTickCollector — all OS-Disabled since Aug, action scripts already deleted in 7f25ce0; definitions exported for the record] - 2026-09-16

- **Forensics before deletion:** all three tasks were already **Disabled** by
  the OS, last ran 2026-08-21 (before the Aug 24 cleanup), and their action
  wrappers (`run-mql5-verify-task.ps1`, `run-live-score-loop-task.ps1`,
  `run-live-tick-collector-task.ps1`) were deliberately removed in commit
  `7f25ce0` ("Remove obsolete tick collection scripts and old artifacts") —
  the tick-collection/autonomous-live era they served is superseded by
  EA-side tick recording, the manifest-pinned deploy gate, and the current
  operating rhythm (morning_status daily + Sunday paper pipeline).
- **Action:** each task's XML definition exported to
  `artifacts/v75_replay/dead_task_definitions_20260916/` for the record,
  then unregistered. Task Scheduler now contains exactly one project task:
  **SyntheticIndicesPaperPipeline** (Ready, Sundays 06:30). Historical
  references in `docs/PHASE5_SUMMARY.md` left untouched (phase record).
- **None recreated:** nothing in the current frozen pipeline cites these
  functions; recreating a task whose action script no longer exists would
  only manufacture a new silent-failure surface.

## [Go-live rehearsal executed read-only: 5/6 PASS — and it caught the LIVE preset stub booting TP 2.4 instead of the certified tp18 geometry, plus the v26.40 build missing from terminal A] - 2026-09-16

- **New tool `scripts/go_live_rehearsal.py`** — a repeatable, read-only dry run
  of every GO_LIVE_CHECKLIST verification step: terminal-A process identity,
  journal account authorization, repo LIVE preset values, deployed Common
  copy byte-identity, verify_go_live_artifacts, and a banner-marker rehearsal
  against the SAME terminal + EA build the live attach will use. Artifact:
  `artifacts/v75_replay/go_live_rehearsal_YYYYMMDD.json`, exit 0 iff all pass.
- **LANDMINE #1 (preset stub, FIXED):** the shipped LIVE preset was a 7-line
  stub — a fresh attach + Load would have booted `InpTpMult` at the **2.4
  default** instead of the adjudicated tp18 geometry the truth table and
  certified chain are built on. Both presets are now completed from arm A's
  executed chart surface (79 keys each; only InpLiveExecution + the tick
  recorder differ); the deployed Common copy is re-synced byte-identical; and
  `verify_go_live_artifacts` now REQUIRES the certified pins (TpMult 1.8,
  risk 0.005, 20% cap, fleet CSV with A+B) so a stub can never pass again.
- **LANDMINE #2 (stale build, OPEN):** terminal A's newest banner is v26.39 —
  the manifest-certified v26.40 build was never deployed to FB9A. This is the
  rehearsal's remaining FAIL, by design: run the deploy sync (sync-mt5.ps1,
  manifest-pinned v26.40), then re-run the rehearsal for a fresh v26.40
  banner. The banner marker surface itself is proven (all 10 checklist
  strings found live, including the evolved FIT ROUTER wording and the
  phantom "State ->" line the checklist prose carried — now corrected).
- **Rehearsal robustness, learned from the live logs:** inits can be
  truncated mid-sequence (terminal stop), so markers aggregate across ALL of
  the day's banner blocks; the version check reads the NEWEST banner (the
  build an operator would see) against repo APP_VERSION; the PAPER MODE:
  discriminator is validated in the paper banner so the live absence-check
  is a real detector, not a no-op.
- **Tests:** 8 new offline tests (synthetic UTF-16 journals, truncated-init
  aggregation, newest-banner version semantics, stub refusal, discriminator
  validation, subprocess whitelist pinning the read-only contract); suites
  119/119 green.


## [Arm-E tp2.0 forward-test proposal PRE-DRAFTED: verdict gates frozen before any forward data, thin-sample disclosure built in, start gated on arm D's adjudication + a hard build-parity pass] - 2026-09-16

- **`docs/ARM_E_TP20_FORWARD_PROPOSAL.md`** — the arm-D discipline applied to
  the tp2.0 cell (the one-shot's chosen candidate) BEFORE it earns a window:
  frozen gates (n ≥ 60, totalR > 0, DD ≤ 25%, meanR ≥ 0.05; abort at 30%),
  monthly reads, structural-abort restart rule, and an expected-duration
  statement (7–15 months at the family's observed rates) written now so it
  cannot disappoint later.
- **Thin-sample disclosure built in (quote-verbatim rule):** tp2.0's only
  independent evidence is the 12-trade OOS sample (+0.225R, PF 1.07 — CI
  includes zero); "proven/validated/profitable" are banned phrasings until
  arm E's own window resolves; strongest permitted phrasing is "directionally
  positive, thin, forward test pending".
- **Selection provenance recorded as the disclosure's backbone:** every held
  number (is180/wf/family) participated in choosing the cell — the forward
  window is the only evidence tp2.0 will ever earn that it did not help
  select itself.
- **Two structural pre-declarations:** the program holds exactly two forward
  tests (arm D's candidate, arm E's tp2.0) and at most one open verdict at a
  time (arm E starts only after arm D's adjudication or structural restart);
  and a hard build-parity precondition — the research build's trade set must
  be reproduced by the forward EA on a held shadow window before the window
  opens, else the test would verify nothing.
- **Nothing runs yet:** STATUS is PRE-DRAFT; fill-in checklist at §8.

## [Arm-D accrual wired into the Sunday pipeline end-to-end: weekly §[6] verified live, SyntheticIndicesPaperPipeline task registered — the documented schedule had NO task behind it] - 2026-09-16

- **Verified the wiring live:** `paper_weekly.py` §[6] runs `armd_accrual.accrue`
  (idempotent per day), embeds the row + pre-registered verdict in the report
  artifact, and propagates VALIDATED/REJECTED into NEXT ACTIONS; a missing
  ledger degrades to `unavailable`, never kills the leg. Structural test pins
  all of it (`test_paper_weekly_has_the_armd_leg_and_survival_catch`).
- **Root cause found:** the ops doc's "Sunday 06:30 pipeline" and
  `paper_pipeline_weekly.cmd` had **no registered scheduled task** behind
  them — and all three existing tasks (MQL5Verify, LiveAutoScorer,
  LiveTickCollector) point at `run-*-task.ps1` wrappers **deleted from the
  repo**; the scheduler layer has been silently dead since ~Sep 4 (sched log
  last write Sep 4, pipeline_state stale).
- **Fix:** registered **SyntheticIndicesPaperPipeline** (Sundays 06:30 local,
  StartWhenAvailable, 2 h cap, user-level) → `run-paper-pipeline-task.ps1` →
  `.venv` `paper_pipeline.py`, appended to
  `artifacts/v75_replay/paper_pipeline_sched.log`. Wrapper proven with a live
  run: rc=0, log grown, pipeline_state refreshed.
- **Surfaced, not fixed (owner decisions):** the three dead task wrappers
  (recreate or deregister), and the funnel-diff leg's **account-guard
  DEFECTIVE** signal (post-v26.37 firings on 2026-09-15) — an open ops item
  that now resurfaces every Sunday via this task.

## [Go-live engineering audit: live order path confirmed broker-side resting SL/TP, artifacts PASS on v26.40, checklist version pins fixed] - 2026-09-16

- **Audit origin:** the 2026-09-16 access-point-hopping investigation showed a
  ~5-minute server-side feed stop while holding a position would blind EA-side
  exit management; the mitigation is broker-side resting SL/TP attached at
  entry.
- **Verified, no code change needed:** both live order paths
  (`MitemshubAI.mq5` standard 3059-60, VOL75 3239-40) submit SL/TP inside the
  market order itself — resting broker-side protection exists from the fill;
  `ValidStopForModify` guards every subsequent `PositionModify`.
- **`verify_go_live_artifacts.py`: PASS** — v26.40 compiled and synced, LIVE
  preset byte-identical to repo, deploy-manifest pins match.
- **Operator trap fixed:** the checklist's banner expectations still said
  v26.39 while the verified build is v26.40 — build pin, banner strings, and
  build-history note updated so go-live day's own string check cannot fail
  spuriously.

## [OOS one-shot SPENT on tp2.0 (user-authorized): +$20.55 / +0.225R over 12 trades — frozen verdict CONTINUE_THIN, positive OOS sign, interior NOT retired] - 2026-09-16

- **The spend:** `REVERSE_BOTH_sl2_tp2_h180_r0.01`, executed through the sweep
  runner (arm D flat-verified pre-stop, banner-verified post-relaunch, canary
  armed). Reason recorded in the spend token: best wf cell, solo permutation
  p = 0.051, survives every leave-one-out drop.
- **Registry row V28-0061:** n = 12, pnl **+$20.55**, R **+0.225**, PF 1.07 —
  the only positive REVERSE_BOTH-family OOS row in the registry.
- **Frozen decision: CONTINUE_THIN** — the sign survived out-of-sample but
  n = 12 < 30 cannot carry a proposal (pre-scoped when the rule was frozen).
  OOS for this interior is now closed forever; the token and the registry row
  are the permanent receipts. Nothing was tuned against the window.
- **Post-spend standing:** is180 family p = 0.0000 (SUPPORTED); wf family
  p = 0.066 borderline (hangs on the sl1.0 cell alone, per the leave-one-out
  diagnostic); single OOS sample positive. The path to live remains arm D's
  frozen forward window (n ≥ 60, R > 0, DD ≤ 25%); the go-live engineering
  track (fill model, server-side SL/TP, kill-switch, sizing caps) proceeds in
  parallel per user authorization.

## [Family test extended to held windows + leave-one-cell-out sensitivity: is180 SUPPORTED at p≈0, wf negative verdict shown to hang on the sl1.0 cell alone (OOS refused in code)] - 2026-09-16

- **Held-window extension (protocol §9 amendment 4a):** `wf-family` now takes
  `--window wf|is90|is180` and **refuses OOS in code, unconditionally** —
  amendment 3's one-shot rule owns that window. is180 result: 10 distinct
  trade sets, 306 pooled trades, family +$18.51/trade (p05 +$5242, profitable
  share 1.000) vs ORIGINAL −$27.03 (profitable share 0.000), mean diff
  +$45.55/trade, permutation p = 0.0000 → **FAMILY_EDGE_SUPPORTED**.
- **Leave-one-cell-out diagnostic (test-pinned):** on wf, dropping sl1.0 flips
  the verdict (p 0.066 → **0.029**, SUPPORTED); all other drops stay
  0.051–0.065; sl1.0 alone is a wf loser (−$2.37/trade, p = 0.32) — the same
  cell the IS adjudication flagged as §6 one-window-wins noise. No distinct
  cell passes solo (best tp2.0 p = 0.051). Recorded as an honest borderline
  input to the amendment 3 spend decision; the bar is NOT re-tuned.
- **Tooling:** 7 new offline tests (OOS refusal ×2, is180 aggregation, window-
  suffixed artifact names, LOO carrier identification, solo diagnostics);
  suites 99/99 green across v28 research, sweep runner, and go-live artifacts.

## [Family-level wf significance test for the REVERSE_BOTH interior: dedupe-to-distinct-trade-sets, pooled bootstrap, permutation vs ORIGINAL — verdict FAMILY_EDGE_NOT_SUPPORTED at p=0.066 against a +$18/trade level gap] - 2026-09-16

- **The test (frozen and test-pinned BEFORE the first live run; protocol §9
  amendment 4 + `v28_research.py wf-family`):** the mode's wf rows are deduped
  to distinct trade sets (identical (n, pnl) signatures verified
  trade-by-trade, collapsed to the baseline-geometry representative, collision
  fails closed), pooled into one per-trade family sample, bootstrapped against
  zero and against the ORIGINAL wf pool, and compared by a one-sided
  permutation test of the mean-per-trade difference. Verdict bar (all
  required): >= 100 pooled distinct trades, family p05 > 0, profitable share
  >= 0.80, mean above ORIGINAL's, permutation p <= 0.05. Descriptive, not a
  gate: it consumes no OOS resource and can never promote.
- **Result (15 wf rows -> 12 distinct trade sets, 335 pooled distinct
  trades):** family +$5.02/trade (p05 -$17.04, profitable 0.948) vs ORIGINAL
  -$13.08/trade (p05 -$808.47, profitable 0.106); mean diff +$18.10/trade,
  permutation p = 0.066 -> **FAMILY_EDGE_NOT_SUPPORTED** (family p05 <= 0;
  p > 0.05).
- **Reading, recorded with the result:** the level separation is large and
  one-sided (consistent with the mode-level wf finding), but the refusal is
  the honest one — the interior deliberately contains wf-losing cells (sl1.0,
  h30 sign-flip; h60/h90/h360 bootstrap unprofitable) and its distinct
  information is thinner than 335 trades suggest (exit inertness). A tight
  interior would pass; this one carries its dead cells. Nothing retired: the
  §9 amendment 3 one-shot OOS rule remains the family's only OOS path,
  unspent.
- **Tooling:** `wf-family` subcommand with --mode/--baseline (defaults
  V28_REVERSE_BOTH vs V28_ORIGINAL); byte-deterministic artifact
  (`wf_family_significance.json`, timestamp-free); docstring states both
  directions of the unpaired test's honesty (conservative across pools,
  approximate within the family pool). 8 new offline tests pin the collapse,
  the collision refusal, determinism/directionality of the permutation
  statistic, the verdict mapping, the sample floor, and artifact
  byte-stability; suites 66/66 green.

## [OOS one-shot rule pre-registered for the REVERSE_BOTH interior: mechanical eligibility from held windows, single-use spend token, frozen decision mapping — the only positive outcome is a forward-test proposal, never a ship] - 2026-09-16

- **The rule (frozen BEFORE any interior OOS row exists; protocol §9
  amendment 3 + `v28_research.py oos-oneshot`, code-checked):** a cell earns
  the interior's single OOS run iff it holds is180+wf evidence with is R ≥
  +2.0, wf R ≥ +1.5, wf sign matching is, and wf DD ≤ 20% — computed
  mechanically from the registry, with two structural exclusions: the
  baseline (its stage-1 OOS row already exists) and trade-identical
  duplicate-exit rows (tp3/5/6: one strategy under three labels must not
  multiply the shot's choices). Six cells eligible today: sl1.5, sl2.5,
  tp2.0, h120, h240, sl3.0.
- **Single-use, whole-interior:** spending requires an explicit --cell plus a
  recorded --reason (auditable against the frozen bar); the spend token AND
  any interior OOS registry row both block a second run, so deleting the
  token cannot re-arm it. One run spends the shot whatever the outcome.
- **Frozen decision mapping:** OOS DD > $3 000 (30% of the frozen deposit) →
  FAMILY_RETIRED; pnl > 0 ∧ R > 0 ∧ n ≥ 30 → EARNED_FORWARD_TEST_PROPOSAL
  (authorizes *drafting* an arm-D-style fresh-window proposal — not live
  orders, not preset changes); positive but n < 30 → CONTINUE_THIN (recorded,
  no action — a 90-day window yields ~12 family trades, so the promotion
  sample gate can never be met by this block; that is why the shot is a
  final historical verdict, not a promotion input); pnl ≤ 0 → FAMILY_RETIRED.
  A retirement closes the interior's OOS consideration forever; no rows are
  deleted and no history is rewritten.
- **Self-review caught a label-gaming hole before any run:** the duplicate-
  exclusion (3) was added after seeing the first dry-run list tp3/5/6 as
  separate choices — they are the baseline's trade set relabeled, and the
  frozen rule now says so explicitly. Dry-run verified against the live
  registry (6 eligible, exclusions firing); 9 new offline tests pin the
  eligibility bar, exclusions, decision mapping, spend requirements, and the
  spent-shot refusal (v28 suite 44/44). Nothing ran against OOS; the token is
  unspent and the block stays reserved.

## [V28 stage-2 evidence completed: TP/hold walk-forward rows close the §5 matrix — the frozen default geometry (sl2/tp4/h180) is the wf optimum on every axis, TP inertness above 3 ATR transfers exactly, and both IS extremes (h360, h30) die out-of-regime] - 2026-09-16

- **Executed:** the ten remaining sweep cells (tp2/3/5/6, h30/60/90/120/240/360)
  ran on `wf` through the permanent runner
  (`v28_sweep_runner.py exit-sweep --window wf`, registry V28-0051 → V28-0060,
  arm D flat pre-stop, banner + $50.00 veq verified post-relaunch, OOS
  untouched). All 15 sweep cells now hold is + wf evidence; registry at 60
  records, re-exported.
- **TP axis:** inertness above 3 ATR transfers exactly — tp3/4/5/6 identical on
  wf as on is (+2.516R), a structural property of the exits. tp2.0 is the best
  wf cell of the whole sweep (+3.03R) and the only live TP cell on either
  window.
- **Hold axis:** the IS h120 dip is absent on wf — confirmed noise per §6. The
  wf surface rises monotonically to the h180/h240 plateau (+2.52/+2.48R); both
  IS extremes die out-of-regime (h30 sign-flips to −0.57R; h360 degrades to
  6.7% of its IS edge) — the same lesson the SL axis taught (IS champions are
  regime artifacts; the interior is what holds).
- **Synthesis:** the frozen default geometry (sl2/tp4/h180) sits at or beside
  the wf peak on all three axes. No re-selection is authorized or suggested;
  the stage-2 conclusion is that the mode carries the edge and the baseline is
  already inside the flat region. Gate verdicts unchanged (all cells REFUSED:
  missing oos evidence, thin samples); the OOS block stays reserved.
- **Tooling note:** the runner's first real command surfaced a CLI defect — a
  plain `nargs='*'` made the top parser reject the subcommand's `--survivors`;
  fixed with `argparse.REMAINDER`, parser extracted as `build_parser()`, and
  pinned by two new pass-through tests (runner suite 14/14, v28 suite 35/35).
  Protocol §9 amendment 2 records the full matrix.

## [V28 sweep discipline graduated into a permanent protocol tool: scripts/v28_sweep_runner.py pins exact terminal identity, discovers arms from chart profiles, and refuses to stop the terminal unless every hosted paper ledger is provably flat] - 2026-09-16

- **The tool:** `scripts/v28_sweep_runner.py` (registered in
  V28_RESEARCH_PROTOCOL.md §2) wraps any v28_research command in the full
  stop → flat-check → sweep → always-relaunch discipline. Verified live:
  `status` discovers D_fwd from the 49E0 chart profile (magic 7788150, tag D,
  21 ERA rows) and reports FLAT with exit 0. Two live-caught defects fixed in
  the same session: origin.txt is UTF-16 with BOM (a utf-8 read garbles the
  path and silently finds no data folder), and a ledger file with zero
  recognizable rows is not evidence of flatness — the gate fails closed on it.
- **The flat gate mirrors the EA's own restore rule** (MitemshubAI
  `PaperInit` adopts a dangling OPEN row as a live virtual position): flat =
  zero OPEN rows without a matching CLOSE, by ticket. An unreadable, corrupt,
  or row-less ledger refuses the sweep; `--i-have-verified-flat` exists for
  verified emergencies and records itself in the artifact.
- **Terminal identity is exact-path, not name-shaped:** PIDs match on the
  full executable path (case-insensitive), so FB9A and MitemshubMT5_C can
  never be caught in the sweep window (the 10:22 retry was an exact-path
  launch against the wrong host's twin — identity, not shape, is the pin).
- **Always-relaunch is structural:** the `finally` block relaunches whatever
  the sweep does — including a crash of the sweep subprocess (rc=4 with the
  error recorded). Every run writes
  `artifacts/v28_research/sweep_runner_last_run.json`: terminal identity,
  arm inventory, per-arm flatness evidence, override flag, command, rc,
  relaunch — the sweep window on a paper-arm host is now auditable.
- **The `_tmp` orchestrator is retired** to
  `scripts/_deprecated_v28_sweep_orchestrator.py` with a deprecation header;
  12 offline tests (`tests/test_v28_sweep_runner.py`) pin the gate: dangling
  OPEN refusal, ticket pairing, fail-closed, chart discovery, override
  recording, stop/sweep/relaunch ordering, relaunch-on-crash.

## [V28 SL axis walk-forward completed: the IS champion dies out-of-regime (sl1.0 +11.12R IS → −0.52R wf, sign flip) while the whole SL interior holds (+1.7 to +2.8R) — edge confirmed at the mode level, not the geometry level] - 2026-09-16

- **Executed per V28 §5 step 2** (wf, same geometry, no edits; OOS untouched):
  the four unregistered SL-axis cells ran on the wf window via
  `scripts/_tmp_v28_wf_sl_cells.py` under the full stop/flat/relaunch
  discipline — arm D's ledger read and confirmed flat before the terminal stop
  (16 rows, all ERA stamps, zero OPEN/CLOSE), all four passes registered
  (V28-0047 → V28-0050), banner + $50.00 veq verified after relaunch.
- **The finding:** the sweep's tighter-is-better IS gradient does not survive
  its own extreme — sl1.0 (+11.12R IS, the sweep headline) is **negative on wf
  (−0.52R, P&L sign flip vs IS)**, the §6 one-window-wins noise signature,
  with a −679.86 max drawdown to boot. The interior is flat, not peaked:
  sl1.5/2.0/2.5/3.0 wf R spans 1.69–2.84R with no monotone structure (IS
  ordering nearly inverts — sl1.5, mid-pack in IS, is the best wf cell). No
  geometry re-selection authorized; the durable fact is that the REVERSE_BOTH
  signal family carries a positive wf edge across the whole SL interior while
  ORIGINAL loses on the same window.
- **Gate status unchanged:** every cell still REFUSED (missing oos evidence,
  samples below 30). The wf rows close the §5 evidence gap so no future
  decision can cite a missing-wf refusal as the blocker; they do not argue a
  ship. Registry: 50 records; protocol §9 amended with the full is→wf table.

## [V28 stage-2 exit-sweep adjudicated: SL axis monotonic (tighter = better), TP inert past 3 ATR, hold non-monotonic — every cell REFUSED by the frozen gate; sweep-host mixup corrected (the tester terminal hosts arm D, not arm B)] - 2026-09-16

- **Sweep executed and reconciled:** the detached orchestrator recovered cleanly
  after the session died mid-flight — its 10:48 run stopped the sweep host, ran
  all 14 remaining is180 cells (~17 s/pass, rc=0) and relaunched the terminal;
  arm D re-initialized at 10:52:25 (banner verified, $50.00 virtual equity
  restored, flat, 0 positions). The 10:22 direct-launch retry had hit the
  known single-instance no-op and burned one 900 s timeout — that trap has now
  recurred twice, so per the protocol's own escalation note the guard is IN the
  runner: `run_pass` fast-fails with the fix in the message when the tester
  terminal is already running, and waits out per-pass self-exit teardown so
  passes 2..n are never condemned for it. 4 new offline tests; suite 35/35.
- **Registry corrected on arm identity:** the sweep host (`MitemshubMT5_B`,
  data folder 49E0…) carries ONLY `_D`-tagged arm files (magic 7788150) — it
  is **arm D's** host; arm B ($40.20, 10 closed) lives on `MitemshubMT5_C`,
  which the sweep never touched. The protocol §2 note and the orchestrator's
  banner-verification instruction both named arm B/wrong equity — corrected in
  the protocol, and the stop/flat/relaunch discipline is unchanged (it was
  arm D that was flat and correctly restored). Arm A/B telemetry silence since
  the 10:00 bar is the known quiet-bars pattern (tick archives 7 s fresh);
  morning-status health otherwise green.
- **Verdict (mechanical, frozen gate): the sweep found NO promotable config.**
  SL axis (tp4/h180): strictly monotonic — sl1.0 +11.12R → sl3.0 +4.40R, same
  n=29 trade sets, tighter stops realize more of the same signal. TP axis:
  inert above 3 ATR (tp3–tp6 byte-identical rows — a determinism check passing,
  not an edge); tp2.0 +7.12R is the only live cell. Hold axis: non-monotonic
  (h120 dips below h90) — the §6 noise signature, not a candidate. All 15
  cells REFUSED: the 14 new is-only cells lack wf/oos evidence by design, and
  the baseline (the only candidate with all three roles) fails OOS outright
  (−20.17 net, −0.185R ratio-sum, −0.2021 money-implied, n 29/27/12 below the
  30-trade gate). REVERSE_BOTH remains the direction-level finding (the only
  mode positive across is90/is180/wf; ORIGINAL −8.13R on the same is180
  window), not a promotable config; the OOS block was not consumed.
- Recorded in `V28_RESEARCH_PROTOCOL.md` §9 with the full matrix; registry
  exported (46 records → registry.csv/json); `promote` refusal on
  `REVERSE_BOTH_sl2_tp4_h180_r0.01` captured verbatim.

## [Ancient-window validation adjudicated: ALL configs FAIL on untouched 2025-04→07 history — the family's edge is epoch-specific to the trained era; arm D's forward accrual is the only path to live] - 2026-09-16

- The last truly independent historical test executed under a protocol frozen
  before data collection (docs/ANCIENT_WINDOW_VALIDATION_20260916.md):
  broker-native V75(1s) M15 2025-04-20→2025-07-26 (9312/9312 bars, D1/D2
  provenance PASS) with 8 months of native H1 warm-up — a window that predates
  the entire optimization program and was never loaded by any study.
- Frozen configs, no search: shipped n=32 −10.09R (totalR/meanR FAIL);
  rebuilt and gated each n=1 −0.67R (starved — the 0.60–0.70 ATR PB band and
  MOM-leg combos almost never form in that era; funnel anatomy recorded).
  Frozen mapping outcome: ALL FAIL → epoch-specific edge. No
  re-parameterization authorized; arm D (docs/ARM_D_FORWARD_TEST.md) remains
  the only path to live.
- POST-HOC (labeled, no runs): the ancient window is itself a historic one-way
  squeeze (+121% in-window, lower absolute vol than Jun–Sep 2026) — the same
  R90 signature as the hostile window. Two independent eras, one mechanism,
  sharpening participation-gate v2's target to an R90-magnitude filter.
- New tooling: scripts/ancient_window_run.py (frozen-config batch runner with
  the lab's cross-instrument spec guard), scripts/armd_accrual.py (daily
  arm-D tracker emitting the pre-registered VALIDATED/REJECTED/CONTINUE
  verdict into artifacts/ARMD_ACCRUAL.jsonl, idempotent per day).

## [Hostile-regime vs overfit adjudicated: Jun-Sep 2026 is a historic one-way squeeze (R90 p95.7) but the failure is CONFIG-SPECIFIC FRAGILITY — gradient −0.714, random control fine, same thesis positive on V100 in the same window] - 2026-09-16

- The program's open question (hostile window or overfit?) settled with four
  pre-registered discriminators (docs/HOSTILE_VS_OVERFIT_20260916.md):
  feature extremity on price alone (1 of 4 EXTREME — R90; volatility NORMAL,
  pullback thesis still functioning), loser anatomy (one mechanism: BUYs
  into the squeeze, −47.4R shipped; shipped|legacy24 monthly corr 0.985),
  IS→OOS gradient across today's configs (Spearman **−0.714**, n=8 — the
  +20R tuning finalists died hardest), random-entry control (ratio 1.086 —
  a directionless participant fine in BOTH windows), and cross-symbol
  simultaneity (**V100 rebuilt entry OOS +1.46R, n=39, DD 10%, in the SAME
  calendar window**). Verdict per the frozen bar: MIXED, weighted toward
  overfit; the regime supplied the traps, the overfit supplied the exposure.
- All 8 fresh-batch runs reproduce the recorded rows exactly (provenance
  proven); V100 OOS cell run once per frozen protocol (no fitting use).
- Consequences: gate v2 pre-registers on R90-type squeeze magnitude; tuning
  budget stays cut; arm D forward window remains the only clean judge.

## [Arm D forward-test arm live: v26.40 ports the autopsy gates as inert inputs + arm-tagged files; gated candidate collects an independent OOS window under pre-registered adjudication] - 2026-09-16

- **v26.40 engine port (compile 0/0, deploy-manifest re-pin `6459f3ad…`):**
  the two OOS-autopsy participation gates are now inputs — `InpNoMomGate`
  (vetoes direction-matching MOM combos) and `InpHtfSlopeGate` (vetoes PB
  entries against the 24h slope of the H1 EMA100, completed bars only,
  fail-open on data gaps) — applied post-decision exactly like the lab, with
  vetoed band-fade plans disarmed. Both default FALSE: off = exact v26.39
  behaviour (verified by contract test + byte-identical default path).
  `InpArmTag` suffixes ALL Files output (ledger/telemetry/state/review/slip)
  so arms can share a terminal+symbol; empty tag = legacy names, zero
  migration.
- **Arm D deployed:** magic 7788150, `InpArmTag=D`, paper-only $50, 24/7,
  dedicated terminal 49E0 chart03 (V75, M15) — the frozen gated candidate
  (`MitemshubAI_VOL75_ARM_D_FWD.set`, pins contract-tested): PB 0.60–0.70,
  TP 1.6, EMA-side ON, BOTH gates ON, MR/BF/BO OFF, self-correct OFF,
  recorder OFF (arm B owns the shared tick file). Banner verified (v26.40,
  tagged `_D` files, era stamp 26.40), fit telemetry: min-lot stop-risk
  $5.03 ≈ 10.1%/trade TOLERATED (R stats basis-independent).
- **Adjudication pre-registered BEFORE the first trade**
  (`docs/ARM_D_FORWARD_TEST.md`): monthly reads from 2026-10-01;
  VALIDATED = n≥60 ∧ totalR>0 ∧ DD≤25% ∧ meanR≥0.05; REJECTED = n≥60 ∧
  (totalR<0 ∨ DD>30% ∨ meanR≤0); structural aborts restart on a fresh
  ledger, never a polluted window. Arm D is NOT a TJ1 gate input.
- **Tooling:** morning_status discovers `D_fwd` via magic+tag (unregistered
  tags fail closed) and skips the recorder canary for tagged arms; the
  tick-archive canary now judges by latest-file mtime instead of today's
  date tag (midnight false alarm). `verify_go_live_artifacts` pins the arm-D
  preset fail-closed. Attach tool fixed to INSERT the expert block when the
  template chart has none (previously a silent EA-less chart).
- **Ops:** arm B found PAUSED (consec-loss breaker, loop alive) — resumes
  next session day per v23 policy; arm A healthy (quiet-bar silence only).
- Suites: 80 passed (go-live/era/armC/morning-status incl. 4 new arm-D
  tests); GO-LIVE ARTIFACTS: PASS.

## [V75(1s)@H1 tuning: NO-SHIP — the tuned config is WORSE out-of-sample (−6.87R) than the config it tuned (−3.97R); fresh gates with multiplicity levy did their job] - 2026-09-15

### Executed — docs/V75LOW_H1_TUNING_20260915.md (frozen before any run; spec-before-import discipline)
- **Search:** 108-run stage-1 grid (7 eligible) + 18-run stage-2 band variants (11 eligible) on the IS window (2023-12→2026-06, 2.5y). Frozen selection picked two near-twin finalists: tp 2.4 / pz 0.6 / shipped PB band (IS +20.44R, n=429, DD 24.6% — double the shipped config's IS edge).
- **Fresh OOS gates (pre-registered with a 2.0R multiplicity levy, stricter DD 25%, 60% degradation bound, split-OOS halves):** the finalist FAILED five of six gates — OOS −6.87R, DD 37.4%, degradation breach, halves +2.74/−5.63. The tuned config is worse OOS than the untuned shipped config (−3.97R): the +10R IS gain was curve-fit.
- **Attribution of the overfit:** TP 1.8→2.4 re-imports the legacy multiple whose V75 history IS the walkforward inversion; PLOCK 0.5→0.6 harvests gains the OOS bull regime would have extended. The split halves localize the bleed to the late window — the same Jul–Sep failure every candidate shows on every symbol.
- **Process note:** this is what the levy is for. Without the +2.0R bar and split-halves requirement, a −6.87R candidate with one decent half could have been argued forward. Verdict NO-SHIP, shipped-at-scale config stands, forward test remains the only clean judge.
- Artifacts: V75LOW_H1_TUNING_S1.json, V75LOW_H1_TUNING_S2.json, V75LOW_H1_TUNING_OOS.json; results in the protocol doc §5.

## [Amendment C scan: home-symbol OOS fixes do NOT transfer — HTF-SLOPE worsens V75(1s)@H1 OOS (−9.30R) and destroys V100's signal cell; NO-EDGE everywhere but home] - 2026-09-15

### Extension to docs/CROSS_SYMBOL_SCAN_20260915.md (frozen before runs; fresh-process, spec-before-import discipline)
- **v75low_H1 × shipped:** ungated +10.51R IS / −3.97R OOS (fail, as before). HTF_SLOPE doubles IS (+22.16R) but its first-ever OOS is WORSE than ungated (−9.30R, DD 34.5%) — the +22.16R replication row was in-sample gate optimization, not transferable improvement. NO_MOM flips the symbol negative (−7.95R): the home symbol's OOS fix is poison here.
- **v100 × rebuilt entry:** ungated +9.40R (DD 49.5%, 1.0-lot inflation) re-confirmed as gross signal; HTF_SLOPE −3.08R and NO_MOM −10.94R both destroy it; BOTH +4.55R halves it. No certifiable geometry at fundable scale.
- **The meta-finding:** each symbol's edge, where one exists, has a different composition — participation gates tuned on one symbol's OOS do not transfer, and the gate matrix now provides direct evidence AGAINST the simplest overfit story (a gate that were pure IS noise could not systematically help one symbol and hurt two others). Edge remains specific to 1-tick V75 at M15; the gated candidate there stays the sole forward-test qualifier. All alternative symbol/timeframe cells: NO-EDGE under frozen gates.
- Artifacts: AMENDMENT_C_V75LOW_H1.json, AMENDMENT_C_V100.json; results in the scan doc §7.

## [MR-leg rebuild: every trend-aware variant still subtracts value (best Δ −3.1R vs bar of +2.0R) — MR stays OFF, no OOS consumed] - 2026-09-15

### Amendment B to docs/SPRINT_ENTRY_REDESIGN_20260915.md (frozen before runs) + mr_mode lab knob (inert, anchors re-proven EXACT)
- **Question:** the sprint's largest lever was disabling MR (~19 trades ≈ −10R). Can a trend-aware MR instead CONTRIBUTE? Variants frozen: flat M15 stack context (|eF−eM| ≤ 0.35·ATR), H1-EMA100 24h-slope alignment, both; × 2 PB bands × 2 TP, plus MR-off reference rows for a direct contribution metric (existence bar Δ ≥ +2.0R).
- **Answer: no.** As-is MR: Δ −3.7 to −17.6R. Trend-filtered: Δ −3.1 to −4.2R (trend-awareness halves the bleed but cannot flip the sign — on this corpus trend_filter ≡ both, the flat-stack condition subsumes the slope condition). htf_slope alone: worse (up to −20.5R, and it destabilizes trade count via false BULL/BEAR classifications during the IS bear grind). Verdict: MR REBUILD NO-ADOPT — mean-reversion on V75 M15 does not pay even when confined to flat, trend-aligned contexts; MR stays OFF in all standing configs. Per the frozen rule, no finalist advanced and the OOS window was not consumed.
- **Runner bug declared:** the first grid pass wrongly mapped mode=None to MR-off (duplicating references); the four true 'MR as-is' rows were added afterwards — frozen design otherwise unchanged.
- Standing configurations unchanged: sprint winner (IS +11.89R) and autopsy-gated candidate (IS +12.74R / OOS +1.53R, forward-test qualified). Artifacts: artifacts/train/MR_REBUILD_GRID.json; Amendment B results in the sprint doc.

## [OOS autopsy + participation gate: MOM-leg veto flips OOS to +1.53R; HTF-SLOPE gate doubles the H1 candidate's edge — gated candidate qualifies for forward testing] - 2026-09-15

### Executed — docs/OOS_AUTOPSY_20260915.md (autopsy → frozen gate design → one-pass runs) + lab knobs (inert by default, anchors re-proven EXACT)
- **Autopsy verdict:** the rebuilt entry's OOS loss is entirely short-side — BEARISH-classified SELLs went 1-for-10 (−6.11R, WR 10%) while BUYs broke even; the IS year's +16.46R short edge was a grinding bear market (49k→29.5k), and the OOS bull recovery (29.5k→47k) baited the family into selling every H1-classified downswing. MOM+PB was the only strategy bucket negative in BOTH windows. Hour-of-day and ATR-percentile axes inspected and rejected as overfit traps (recorded).
- **Gates (frozen before any gated run):** HTF-SLOPE (PB entries must align with the 24h slope of H1 EMA100) and NO_MOM (veto MOM legs); BOTH pre-declared primary. Evaluation: IS preservation ≥ +8R/n ≥ 60, OOS ship gates, cross-symbol replication bar ≥ +5R.
- **Results:** BOTH = IS +12.74R (n=116, DD 11.3%) / OOS **+1.53R (n=25, DD 3.8%)** — every gate passes, degradation ratio 0.56. Attribution: the OOS fix is entirely NO_MOM (22 OOS MOM-leg trades vetoed = exactly the −5.40R MOM+PB bleed); HTF-SLOPE alone is near-inert on the home symbol (0–2 vetoes — the H1 regime classifier already enforces most of it). Its value shows on V75(1s)@H1: 20 counter-slope trades worth −11.65R removed → **+10.51R → +22.16R IS** — the gate generalizes across symbols. Circularity caveat on record: the OOS pass is a diagnosis-then-verify loop on one window, not independent evidence — the gated candidate (rebuilt + BOTH) is qualified for FORWARD testing, not validated.
- **Tooling traps caught before they fossilized:** (1) in-process env switching after lab import caches instrument constants — one replication attempt was invalid and redone spec-before-import; (2) the harness default `TP_MULT_CERT=2.4` is the legacy geometry, not the deployed preset's 1.8 — a default-argument call silently tests TP 2.4. All recorded rows are the corrected ones.
- Artifacts: artifacts/train/AUTOPSY_TRADES.json, AUTOPSY_GATE_RESULTS.json, docs/OOS_AUTOPSY_20260915.md. Engine code and presets untouched.

## [H1 timeframe test on V75 (1s): cost stops binding, signal appears (+10.5R IS) — OOS persistence still fails; frozen verdict NO-EDGE] - 2026-09-15

### Amendment A to docs/CROSS_SYMBOL_SCAN_20260915.md, pre-registered before any H1 run
- **Setup:** H1-primary replay (H1 series in the harness's primary slot, H4 context aggregated from the same source — no synthetic bars), same four frozen configs, same gates, one pass; V75(1t)@H1 as the control. Spread constants are per-trade and timeframe-independent.
- **Control first:** V75(1t)@H1 is miserable everywhere (shipped −16.64R, DD 67%; trained_best −20.31R) — the H1 horizon is not a general fix.
- **The finding:** V75(1s)@H1 shipped config = the ONLY SCAN pass on any alternative symbol or timeframe: +10.51R over 406 trades, DD 25.7%, streak 6, WR 48.0%. Spread toll drops to 1.24% of stop distance (M15 1s: 5.6%; M15 1t: 2.2%) — the lowest cost burden of any combination tested. At H1, cost is no longer what kills this family.
- **What fails:** OOS persistence — −3.97R (n=53, DD 33.8% > 30 gate) over the shared Jun–Sep 2026 window. This is the same failure mode as the home symbol's rebuilt entry (+11.9R IS → −5.7R OOS). Honest caveat now on record: every OOS test this cycle shares one 3-month window — one regime draw, not independent confirmations. Distinguishing a hostile regime from pervasive overfit is THE open question of the program; an independent later window is the only clean separator.
- Artifacts: CROSS_SYMBOL_SCAN_v75low_H1.json, CROSS_SYMBOL_SCAN_v75t_H1.json; H1-primary datasets under artifacts/train/v75low_h1/ and v75t_h1/.

## [Cross-symbol edge scan: NO-EDGE on V100 and V75 (1s); new 2.9-year V75(1s) corpus collected live] - 2026-09-15

### Executed — docs/CROSS_SYMBOL_SCAN_20260915.md (frozen before runs) + scripts/cross_symbol_scan.py
- **Scope honesty first:** the repo held no V75-low data; V100 was already adjudicated for the OLD configs (`docs/V100_NET_EDGE_STUDY.md`: gross dies net, Q1/Q2 NO, 1.0-lot floor). The scan's open question was whether the REBUILT entry (EMA-side kernel, MR-off) has an edge where the old configs did not.
- **V100 (2y, true spec — spread 0.26, $1.0/unit/lot, 1.0-lot floor): NO-EDGE.** The rebuilt entry shows gross signal even here (+9.40R, n=79, WR 51.9%) — the kernel's directional effect transfers across symbols — but the 1.0-lot floor at a $300 basis risks 3–5%/trade and DD hits 49.5% inside a winning run. Independently re-confirms Q5: V100 is untradeable at small scale regardless of signal quality.
- **V75 (1s) Index: NO-EDGE, decisively — and the symbol had no data in the repo, so it was collected live.** `symbol_select` woke the dormant subscription; spec measured live (spread 1.90 units, $1.0/unit/lot, min lot 0.05, step 0.001); 96,055 M15 bars (2023-11-06 → 2026-09-15, ~2.9 years, the largest corpus we hold) pulled chunked and saved to artifacts/train/v75low/. All four configs deeply negative (shipped −58.19R/377t; rebuilt −18.10/−26.47R). Mechanism priced: M15 TR is ~7× smaller (30.8 vs 220.3) while spread is ~10× smaller (1.90 vs 18.5) → spread is 5.6% of the 1.7·ATR stop vs 2.2% on the 1-tick V75 — a 2.6× relative cost toll, structural at this timeframe.
- Verdict recorded in OPERATING_SUMMARY question table (row 7b): the strategy family's edge, where it exists at all, is specific to the 1-tick V75 index; no second instrument is certifiable from held data. Artifacts: CROSS_SYMBOL_SCAN_v100.json, CROSS_SYMBOL_SCAN_v75low.json. Engine code and presets untouched.

## [Entry redesign sprint: EMA-side kernel + MR-off rebuilds the family (+11.9R IS, −5.7R OOS) — still NO-SHIP on the frozen gates] - 2026-09-15

### Executed — docs/SPRINT_ENTRY_REDESIGN_20260915.md (frozen before runs) + scripts/entry_lab.py + scripts/sprint_entry_redesign.py
- **Lab fidelity proven first:** scripts/entry_lab.py is a byte-copy of the certified harness with five inert-by-default knobs (use_bandfade, m15_full_stack, h1_sep, disable_mr, mom_confirm); anchors ema-side off AND on reproduce the harness EXACTLY (same n, totalR, DD) before any candidate counted. Certified files untouched.
- **The rebuilt entry:** trend-side pullback core (ema_side ON), PB band narrowed to 0.6–0.7·ATR, TP 1.6R, mean-revert legs disabled. IS: +11.89R over 137 trades (DD 14.6%, streak ≤8) vs the shipped config's −4.3R on the identical window. OOS: −5.73R (n=40, DD 13.8%) vs the shipped baseline's −15.10R (n=119, DD 29.7%) on the identical window — beats the gate-5 margin by ~9.4R and halves the drawdown.
- **Still NO-SHIP, and the gates are right:** OOS totalR is negative (g2) and meanR degraded below half of IS (g4). A config that loses less than baseline is not a config that makes money. All three finalists (incl. the full-M15-stack variant, +10.56R IS) failed identically: the Jun–Sep 2026 out-of-sample regime is hostile to the entire family.
- **Two auxiliary findings priced:** (1) BandFade legs never fire on this corpus (strategy mix PB 163 / MOM+PB 104 / MR 16 / MOM+MR 3), so the preset-vs-harness BF fidelity question is moot here — gap exactly 0.0R. (2) The MR leg is the family's biggest bleed source: ~19 IS trades costing ≈−10R; disabling it is the single largest improvement lever found (recorded as the lead design fact for the next iteration, not shipped).
- **Two driver bugs caught and fixed before conclusions:** a duplicate-kwarg crash in family C, and a wrong OOS baseline row (pinned CLI defaults instead of the module constants PB 0.30/2.2 — corrected to the true shipped baseline, n=119/−15.10R, matching the training protocol's row exactly).
- Artifacts: artifacts/train/SPRINT_REPORT.json (equivalence proof, 72 IS runs, finalists, OOS rows, gate matrix), docs/SPRINT_ENTRY_REDESIGN_20260915.md. Engine code and presets untouched; the rebuilt entry is a candidate, not a deployment.

## [V75 parameter training: NO-SHIP — no trainable edge over the shipped config on 417 days of data] - 2026-09-15

### Executed — docs/TRAINING_PROTOCOL_20260915.md (frozen before the runs) + scripts/train_v75_grid.py
- **The question:** user directive to train the EA on the data we hold, today. The protocol froze the split (IS 2025-08-01→2026-06-01, OOS 2026-06-01→2026-09-02 from the 40k-bar/417-day broker corpus, converted to harness format in artifacts/train/), the fill model (touch = broker-side resting-order approximation), the search space, the selection rule, and six ship gates BEFORE any run.
- **Stage 1 (108 runs): 0 eligible.** Best ≈ −4.3R over 10 months; nearly all of the 108-configuration space is deeply negative (tp 2.4 rows: −14 to −28R, DD 40–75%). Parameters cannot rescue the entries.
- **Amendment A (declared after stage 1, before OOS):** structural levers on IS only. `ema_side_filter` is the one real finding — it flips the family from ≈−15R to +1.5R (n=194) and its best geometry reaches +0.71R with DD 24.3% — but still fails the frozen eligibility bar on the loss-streak bound (9 vs ≤8), and OOS turns it negative (−7.8R; baseline itself −15.1R over the same 93 days). `legacy_sl` re-confirms the walkforward inversion mechanism: −39R, 95% DD. min-score and family-throttle variants destroy the trade count without fixing expectancy.
- **Verdict (frozen rule, applied mechanically): NO-SHIP.** The shipped parameters remain the certified ones. The certified fresh-60 +4.37R is now honestly recontextualized: 93 of its 94 days overlap the OOS segment where the same config scores −15.1R — favorable-regime luck, not a stable edge. The EMA-side filter is the only lever with a measured directional effect; it is recorded as the lead candidate for a strategy redesign (entry side must be trend-aware), not as a preset change.
- Artifacts: artifacts/train/TRAINING_REPORT.json (consolidated, 108+14 runs + OOS diagnostics), TRAIN_LOG.txt, AMENDMENT_A_*.json, OOS_DIAGNOSTICS.json; protocol with Amendment A: docs/TRAINING_PROTOCOL_20260915.md. Engine code and presets untouched.

## [Ledger ERA provenance — pre/post-v26.38 fill regimes are now separated in every statistic, automatically] - 2026-09-15

### Added — scripts/era.py + era stamps in both engines (v26.39 / v2.24) + era-aware consumers + tests (18 new)
- **The rule being enforced:** the fill-cost stress protocol priced the pre-v26.38 bar-open fill cadence at −8.3R/window vs per-tick fills, so the two regimes are different distributions and must never share an expectancy statistic (OPERATING_SUMMARY 2026-09-15 era-boundary amendment). Until now the separation was a manual convention; it is now data-native.
- **The writers:** each engine stamps an idempotent provenance row `ERA,<version>,<boundary_epoch>,pertick-fills` into its own paper ledger at init. MitemshubAI v26.39 stamps in `PaperInit()` before any early return, `PaperActive()`-guarded (LIVE book untouched); V75MacroEngine v2.24 stamps in `OnInit` under `InpPaperMode`. Strategy and fill model are unchanged — the stamp is provenance only. Restarts append another stamp; readers keep the FIRST (append-only files, so the first is the oldest claim) — pinned by test.
- **The boundary (frozen, pre-registered):** `ERA_EPOCH = 1789494700` = 2026-09-15 17:51:40 UTC, the midpoint of the verified EA-down window (last pre-deploy ledger activity 17:50:48 UTC, terminals stopped 17:52:18, first v26.38 init 17:52:35 UTC) — no real trade can straddle it by construction. An earlier draft froze the boundary outside the silence window; caught in self-review and corrected before any consumer shipped. A stamp whose boundary mismatches the frozen one is marked not-ok and ignored (consumers fall back to the epoch rule).
- **The readers:** `era.parse_era_rows` (integrity-marked), `era_of_trade` (positional: rows ABOVE the first stamp are classified by the frozen epoch rule, rows BELOW carry the stamp era — necessary because append-only stamps sit at the file's current end), `era_filter` (default `pertick-fills` = the pre-registered gate statistic), `era_split` (display). Wired into: `ab_adjudicate.py` (TJ1 pairs/t/count are post-era only, era block in the artifact), `adjudicate_arm_c.py` (arm-A reference filtered post-era, G1 count post-era, era block), `morning_status.py` (X/30 clock is post-era with a pre-excluded count shown, rate projection suppressed below 3 trades in <12h — a single close can no longer claim "24/day"), `reconcile_paper_ticks.py` (only post-era trades are eligible; pre-era trades would reconcile against the wrong regime by construction). All parsers skip ERA rows and carry CLOSE line numbers.
- **Smoke on real ledgers caught a real pre-existing bug:** with arm A's 14 trades all pre-era, the filtered list is empty — and the TJ1 KEEP-COLLECTING branch crashed on `arm_stats({})['trades_per_day']` (KeyError) while also passing arm A's equity curve for arm B's rate projection. Fixed (`.get()` + per-arm curve); the smoke verdict now reads correctly: `KEEP COLLECTING — A_tp18 has 0/30 post-era trades; B_tp24 has 1/30 post-era trades`.
- **Deployed and verified live:** compile 0/0 both engines (49E0 + sync build gate); manifest re-pinned (`26.39|568f4930…`, `2.24|91e78c87…`); arms restarted from a verified-zero process state (tasklist, not WMI — a bash-quoting trap made a first `Get-CimInstance` kill attempt silently misfire, caught by re-checking with tasklist before launch); banners show `[v26.39]` / `v2.24` + `PAPER ledger era stamp` on both hosts (21:44:17/19); ledger stamps verified ok on all three ledgers; splits: A 14 pre-era / 0 post, B 9 pre / 1 post (a post-v26.38 fill landed before this deploy), C no trades yet. Suite: era 18/18, go-live 25/25, adjudicator 18/18, morning_status 15/15.
- **Note for tomorrow's status read:** arm B is currently PAUSED by the consecutive-loss breaker (3 losses today, dailyPnL −15.00) — pre-existing engine behavior, resumes next session day; not related to this change.

## [Go-live artifact contract re-pinned to the deployed two-engine line — the stale v27.00 test debt is closed with teeth] - 2026-09-15

### Fixed — scripts/verify_go_live_artifacts.py + tests/test_go_live_artifacts.py: the suite pins reality, and can never go stale silently again
- **The debt:** both files pinned the unshipped v27.00 narrow-engine design (`EXPECTED_VERSION = "27.00"`, `ProcessM30Gate`/`MAX_HOLD_SECONDS`-era markers) and had been failing 7 tests on the untouched worktree since the v26.36 re-pin — a green-suite lie waiting at the exact moment a go-live check mattered.
- **The design change:** certified BYTES are no longer duplicated in a second constant. The verifier now reads `scripts/deploy_manifest.txt` (the deploy gate's own single source of truth), asserts the worktree matches the pins, and asserts the pinned versions are the expected ones (MitemshubAI `26.38`, V75MacroEngine `2.23`). An engine edit without a deliberate re-pin now fails here AND at the deploy gate — the two can no longer drift apart.
- **The contract is two engines now:** MitemshubAI (arms A/B host, v26.38 markers incl. `PaperCheckHardExits`, `PaperClose(reason, exit_price=0)`, paper-aware `FleetOpenRisk`, volatility-only refusal, TickRecorder include) and V75MacroEngine (arm C, v2.23 markers incl. per-tick `PaperCheckExits` before the M30 gate, the arms-exact 12-field OPEN schema, self-containment/no-custom-includes, long-only stand-down, calibrated tick value with the 5% identity rule). Preset checks extended: shared magic 7788075, LIVE submits / FINAL does not, and drift between them is confined to declared keys (`InpLiveExecution`, `InpTickRecordEnabled`) — anything else is intent drift.
- **The fill-parity invariant is positional and mutation-tested:** the suite fails unless the per-tick hard-exit call sits inside `OnTick` BEFORE the bar guard (moving it after the guard — the bar-open regression class that priced −8.3R/window — was simulated and caught), unless hard exits fill AT the resting level with STOP checked before TP, and unless management exits (PLOCK/ECUT/TIME) stayed bar-granular. `PaperOpen`'s body is audited to contain no order-send calls.
- **Suite result: 24/24 green;** the mutation check on the parity invariant caught the planted regression; the CLI (`python scripts/verify_go_live_artifacts.py`, exit 0, `--deployed-live` byte-compare preserved) still satisfies the GO_LIVE_CHECKLIST/PRODUCTION_CONFIGS contract. Full local suite after the change: 1316 passed, 15 skipped, 0 failed.
- **Docs de-staled with it:** PRODUCTION_CONFIGS.md rewritten from the unshipped v27.00 contract to the deployed v26.38 line (per-tick subsystems, fill-model parity, governor/fleet-guard/fit-router entry flow, verified-append writers); GO_LIVE_CHECKLIST's banner-expectation rows now expect `v26.38` with a note that the live book's fills are unchanged by the parity fix. #property version on V75MacroEngine ("2.22") still lags its ENGINE_VERSION banner macro ("2.23") — surfaced informationally in the verifier output rather than asserted, since MQL5 cannot take a macro there.

## [v26.38 PAPER FILL-MODEL PARITY — hard SL/TP now fill per tick at the resting level, ending the machinery-vs-strategy confound in the gate] - 2026-09-15

### Fixed — mql5/MITEMSHUB_AI/MitemshubAI.mq5: the paper book's exit cadence no longer differs from the live book's
- **The defect and its price:** `OnTick` returned early unless `new_bar`, so `PaperManage()` (arms A/B) evaluated the virtual ladder once per M15 bar, while the live engine sends resting SL/TP with the entry order and the broker fills them intrabar. The fill-cost stress protocol (`docs/FILL_COST_STRESS_PROTOCOL.md`, artifacts `fill_cost_stress_decision.json`) priced this exactly: on the certified 60-day window, touch-fill control +4.12R vs engine-mirror −4.18R — **−8.3R/window of pure machinery**, attributed to the TP-cadence term (18 rides-back −3.65R; 7 intrabar TPs that a bar-open model books as SL −6.66R; stops nearly identical). A gate adjudicating this data would rule on machinery, not strategy. Arm C (V75MacroEngine v2.23) already filled per tick (`PaperCheckExits()` before its M30 gatekeeper) — the defect was arms A/B only.
- **The fix (strategy untouched, entry path untouched):** new `PaperCheckHardExits()` runs on EVERY tick before the bar guard, mirrors resting-order semantics (long: bid<=SL → fill AT SL, bid>=TP → fill AT TP; shorts on ask; STOP checked before TP when one tick spans both). `PaperClose(reason, exit_price=0)` takes an explicit fill price for resting-order exits; management exits (PLOCK/ECUT/TIME, BE, trail) deliberately remain bar-granular — they are decisions, not orders. Fill-at-level is the no-slippage mirror of a broker's resting fill; slippage remains a separately measurable stress overlay.
- **Pre-registered agreement, not a new baseline:** TJ2's `--mode baropen` (adjudicated MATCHED, +0.022R, CI95 covers 0, reason-agreement 0.846, zero exit-price violations) models exactly these semantics — management at bar opens, SL/TP boundary hits per tick. The engine now implements the baseline that already reconciled; no TJ2 amendment needed.
- **Era boundary (append-only, docs/OPERATING_SUMMARY.md §4):** trades closed before this deploy carry bar-open fills; trades after carry per-tick fills. Mixing regimes in one expectancy statistic would measure the change, not the strategy — the 30-trade gate clock restarts at the boundary. Arms keep their virtual equity (continuity preserved), and the −8.3R handicap is now understood as machinery cost, not strategy evidence — the 23 collected trades remain honest data about the OLD sim.
- **Live verification (timestamped):** FB9A `[v26.38]` init 19:58:03 — state restored ($30.73, dailyPnL −6.36, cooldown 3→2→1 across bars), tick recorder ON, FIT ROUTER TOLERATED, arm C v2.23 $50.00; 71BF `[v26.38]` init 19:52:35 — $42.72 restored, recorder ON. Compile 0 errors/0 warnings (49E0 staging + all trees via sync build gate); manifest re-pinned deliberately (`mql5/MITEMSHUB_AI/MitemshubAI.mq5|26.38|4c9e5bd9…`); morning_status all green post-restart.
- **Deploy incident, honestly logged:** the first relaunch used `/portable` on the default-install terminal, silently redirecting its data path away from FB9A (no journal, no logs for ~6 min; 71BF, a local install, was unaffected). Killed, relaunched without the flag, verified via the terminal's own log (`data folder` line) before re-checking banners. Also noted pre-restart: arm A's 19:30/19:45 signals were REFUSED by the 20% cap (min-lot risk $6.57 > cap $6.15) — the paper arm at $30.73 is already partially strangulated, matching the VSG floor prediction live.
- Pre-existing test debt flagged, not introduced here: `tests/test_go_live_artifacts.py` pins the obsolete v27.00 V75 shape and fails on the untouched worktree (7 failures predate this change).

## [VSG study executed: NO at $150 — V1's 10% risk breaches the DD line (52.1% > 45%) and V2's stop grid confirms the intra-bar-noise prediction; the adjudicator ships tested] - 2026-09-15

### scripts/study_frozen_certify_v75.py --risk-frac + docs/VIABLE_SCALE_GEOMETRY_STUDY.md §6 results + scripts/adjudicate_arm_c.py + tests (18/18)
- G0 control PASS — exact reproduction on the pinned harness (n=114, +4.37R, funnel identical: 2727/10/0/1002/45, streak 6, loss rate 54.4%); the new --risk-frac lever (added to the harness because V1 had no risk parameter; default 0.005 keeps the certified path byte-identical, proven by G0 itself).
- **V1 (risk 10%, E=$150): FAIL G1** — 0 refusals and materiality trivially clean (identical trade sequence), but max DD 52.1% breaches the frozen 45% line. The §1 frontier projection (31.0%) was wrong and the pre-registered rule right: the engine's 0.75^consec volume scaling compounds multiplicatively (0.9^6 ~= 0.53 through the certified 6-loss streak), so the percentage regime's binding constraint is multiplicative DD, not strangulation. Survivability != admission.
- **V2 (stop-mult 1/3 | 0.5 | 2/3 at 0.5%): ALL FAIL, noise prediction CONFIRMED** — meanR -0.13/-0.10/-0.10 vs the +0.038 control (materiality bar 0.02 kills all three); sm=0.5 passes the G2 hit-rate bound (+2.9pp) yet still loses 0.14R/t; sm=2/3 also breaches G1 DD (50.2%). Tighter stops convert intra-bar noise into stop-outs exactly as pre-declared (median intra-bar range 0.541R).
- **Verdict: the §4 NO-at-$150 branch fires.** Live-authorization floor for the current geometry stands at ~$226 (10%-risk) / ~$1,446 (1%-risk), with the sharper warning that 10%-risk must expect a ~50% DD through its own certified streak — any future scale study must freeze BOTH an admission floor and a DD-survivability bound. Arm C stays collection-only.
- scripts/adjudicate_arm_c.py written and tested BEFORE any candidate data exists (18/18 synthetic-ledger tests): unified OPEN/CLOSE/EQ parser (both engines), G1-G5 incl. the G5 window-min-equity floor with sub-case (a)/(b) classification, G4 banner-diff contamination gate (UNVERIFIED -> INVALID when journals cannot verify it), G1 <30 as a schedule gate (KEEP COLLECTING, never a statistics verdict), daily-paired t with the 13/14 tie-breaker, full frozen decision mapping.

## [Arm-C adjudication gains G5 — the strangulation floor is now checked at verdict time, not just at activation; a strangled window is INVALID, never adjudicated] - 2026-09-15

### docs/ARM_C_TEMPLATE.md amendment (append-only) + cross-links (GO_LIVE_CHECKLIST floor amendment, OPERATING_SUMMARY arm-C branch)
- The hole closed: the ~$226 floor was an activation precondition (§4) only — nothing re-verified it at adjudication, so a candidate could start compliant, eat its own certified worst streak mid-window, and pass G1-G4 on a sample whose tail trades were collected strangled (the L1 death mode laundering itself into a statistics result).
- **G5 mechanics, frozen:** arm C's window-minimum equity (ledger EQ rows) must be >= the ATR monitor's `floor_certified` at every point of the window — the minimum, not the end value, because equity can dip below the floor mid-window and recover. Single source of truth: `strangulation_floor` block in `atr_drift_monitor.json`; k and s are never re-derived by the adjudicator; a stale block (>8 days) fails G5 as a data gate, same class as a dead ledger. Implemented in `scripts/adjudicate_arm_c.py` (code-checked, not prose-checked) when that tool is written.
- Two failure sub-cases, different paths: (a) floor rose above equity (ATR drift) -> append-only floor amendment, fresh window at the amended floor; (b) equity fell below a stable floor (the streak death mode) -> window INVALIDATION, not a candidate verdict — no REJECTED recorded, the no-re-adjudication ban is not triggered, re-collection allowed at compliant equity under the same template. Strangulation biases the daily-paired series itself (cap-bound days admit a thinned, adversarially-selected subsample), so no statistic on it is interpretable — same INVALID-only logic as the G4 contamination gate.
- Consequential edit to §3's mapping: CONFIRMED now requires G1-G5 all clean; REJECTED/INCONCLUSIVE unchanged (a verdict on a G5-failing window is not a verdict at all).

## [Viable-scale geometry study pre-registered — the ~$226 floor question answered by frontier, not judgment; 10%-risk or nothing at $150] - 2026-09-15

### docs/VIABLE_SCALE_GEOMETRY_STUDY.md — new frozen protocol + cross-links (GO_LIVE_CHECKLIST, OPERATING_SUMMARY arm-C branch)
- The strangulation-floor amendment left one question open: can ANY risk input + stop sizing make arm C viable at $150? The study re-prices from the certified replay's own 114-trade sequence (per-trade stop distances, R sequence, frozen k band) — percentage-regime bisection for min-lot refusals: 1% needs $1,446 (the known static result), 5% needs $268, 7.5% is admitted but every entry is refused, **10% needs $138 with 0 refusals and max window DD 31.0%**; 12.5%/15% breach the DD freeze line. Cross-check: percentage regime needs E >= s/r = $205 + the after-streak buffer = $225.54 — the strangulation floor reproduced by an independent derivation.
- Answer space frozen to exactly two candidates: **V1 risk-input only** (InpRiskPercent 1.0 -> 10.0, unchanged 2.0 x H1 ATR(14) geometry; each stop -10%, worst -18.9%) and **V2 stop-scaling only** (s* in {1/3, 0.5, 2/3} at 1% risk), with V2's trap pre-declared: median intra-bar M15 range 0.541R >= the scaled stop, so the stop-hit rate must rise mechanically — gate G2 bounds it at +5pp over the control's 54.4% or V2 is falsified. Nothing else is a candidate (wider stops raise s and the floor; hybrid cadence already killed by its own gates; TP is arm B's duel).
- Gates G0–G3 frozen before any run: G0 harness re-pin (the NO-GO drill's amendment), G1 survivability (0 refusals, DD <= 45%, n >= 100), G2 the V2 noise bound, G3 winner -> hypothesis doc -> fresh window -> arm-C paper under the frozen adjudication rule — plus a materiality bar (mean R/t regression > 0.02 kills any variant: re-pricing scale cannot manufacture edge). Pre-declared outcome mapping includes the honest NO-at-$150 branch (checklist floor becomes ~$226 at 10% / ~$1,446 at 1%; arm C stays collection-only). Not yet executed; results append to the study.

## [Strangulation floor computed — the sizing truth table's static admission misses the L1 death mode; honest minimum is ~$226, not $100] - 2026-09-15

### GO_LIVE_CHECKLIST amendment (append-only) + atr_drift_monitor strangulation_floor block + ARM_C_TEMPLATE precondition update
- The hybrid study's L1 book died by a mechanism the frozen table never modeled: min-lot risk is PINNED in dollars (broker volume floor) while the 20% cap shrinks with equity, so a loss streak strangles admission below a computable floor. Mechanics validated against observation — L1 died at equity ~= risk$/0.20 with 589 risk-cap vetoes. Formula, frozen: eq_floor = s x (k+5) — 5s static admission + k*s absorb the worst certified streak + s trade again after it.
- Inputs cited, not remembered: k = 6 (cert_report_fresh60_tp18_net.json worst_loss_streak field, n=114; arms observed 5/3 at n=14/9, consistent), s = $20.50 (p95 worst min-lot stop, ATR reading #6). **Certified floor $225.54; tail k=7 $246.05; engineering s=$28 $308.00 — all above every frozen row ($50-$150).** The $100 MINIMUM-VIABLE and $150 RECOMMENDED-BUFFER rows stand for static admission but do NOT survive a certified-replay streak unstrangled (at $150 the streak's tail ends below the $30 cap, which then refuses everything).
- Consequence recorded: the arm-C branch's precondition now reads $100 minimum to trade at all, ~$226 minimum to survive the config's own worst certified streak; between them is a strangulation-prone regime (the L1 death mode). The weekly ATR monitor re-derives the floor every reading (strangulation_floor block); a floor above actual account equity is an amendment-grade finding. Truth-table re-derivation unchanged this reading (WATCH on the $100 static row).

## [TickRecorder live on both MitemshubAI hosts — every future arm exit is forensically exact; a .chr text-edit corruption caught and repaired in the process] - 2026-09-15

### mql5/MITEMSHUB_AI/{VOL75_FINAL,VOL75_TP24}.set + chart inputs + morning_status canary — playbook finding F3 closed
- Design established from the module source before enabling: the recorder writes a per-TERMINAL, per-SYMBOL file (MITEMSHUB_ticks_Volatility_75_Index_<day>.csv, ts/bid/ask/mid), so ONE recorder per terminal is correct — arm A on FB9A also covers arm C (same feed, same symbol; V75MacroEngine has no recorder module and the artifact test pins it include-free). Arm A + arm B recorders cover all three arms' forensics. Enabled in the repo presets AND byte-surgically in the arm charts (InpTickRecordEnabled=true, flush 100 ticks / 10s).
- A restart for the chart surgery silently dropped both arm EAs (charts loaded EA-less for ~21 minutes, 12:44-13:05): my first .chr edit used text-mode UTF-16 writes that doubled the file's newline structure and MT5 refused to restore the EA (chart03, unedited, loaded fine — the discriminating evidence). Restored from the pre-surgery backups, re-applied via byte-exact insertion with a round-trip assertion (new == backup + insertion only, proven), relaunched from a verified-zero-process state (the prior "relaunch" had hit already-running terminals — Start-Process is a no-op then, and a sloppy grep presented stale 12:19 banners as fresh). Missed M15 evaluations: 12:45 and 13:00, identically on both hosts (one shared stream; no differential effect on A/B, no positions open during the gap).
- Verified end-to-end: [TickRecorder] ON in both journals, CSVs live and growing (377/376 rows, 3s fresh, identical last-tick = shared feed), morning_status gained a TickRecorder canary (missing/stale >15min archive on a MitemshubAI host = unhealthy; V75MacroEngine charts correctly skipped), presets synced to Common so the weekly preset-drift check stays consistent. All three arms healthy: A 14/30 ($30.73), B 9/30 ($42.72), C 0/30 ($50.00) — gate clock unchanged.

## [Funnel diff automated — the playbook's Step-4 output contract is now one command, with journal-expiry counts archived forever] - 2026-09-15

### scripts/funnel_diff.py — new tool + paper_weekly §5 + playbook §4 registration
- The NO-GO drill ran Step 4 by hand; finding F4 (journal retention ~6d vs the 60d replay window) meant those counts rot. The new tool emits the playbook's exact output contract on demand and as the weekly pipeline's §5 leg: per-counter rates (replay per 1000 of funnel.score, live per 1000 of the arms' combined sig events — the shared-stream denominator from the 09-15 measurement), frozen verdict words, and a cumulative funnel_diff_history.json so expiry can never silently destroy counts again.
- Honesty guards frozen: counts < 5 -> LOW-COUNT (window-limited, never drift evidence); meta-label/time-block/family-throttle nonzero either side -> CONFIG DRIFT; account-guard classified PER FIRING against the v26.37 deploy — all-pre-deploy = CLASSIFIED closed class (informational), any post-deploy firing = DEFECTIVE (new defect, never blended into strategy causes). First automated run: 0 flagged — funnel clean; the 07:47:04 firing correctly classifies pre-v26.37.
- Two tool defects caught on its own first run and fixed before registration: day-slice [:10] kept the log extension (breaking timestamp parse and silently dropping the firing classification) and the account-guard verdict word mislabeled a fully pre-deploy history as DEFECTIVE. The buggy first run's history row was removed (my own artifact from this session); the live numerator cannot be attributed per-instance (same EA/symbol both hosts) so denominator = A+B sig events combined, recorded in the artifact.
- Playbook §4 now names the tool as the standard Step-4 producer with the real-execution usage (--replay pointing at the rebaseline run's cert report, so the funnel comes from the same run R1 validated). Weekly pipeline re-run: [5] leg green.

## [ACCOUNT GUARD fleet-basis defect fixed in v26.37 — the funnel diff is clean of the class before the gate adjudicates] - 2026-09-15

### mql5/MITEMSHUB_AI/MitemshubAI.mq5 — FleetOpenRisk mirrors the virtual book in paper mode
- The drill's Step 4 counted the known defect live (account-guard 1x on FB9A). Root cause pinned: the cap side was paper-aware since v26.35, but the fleet-sum operand iterated real account positions only — structurally $0.00 in paper mode, blind to the instance's own virtual position. Fix: when PaperActive() and a virtual position is open, FleetOpenRisk adds its risk at the ORIGINAL stop (g_pp_orig_risk) with the calibrated tick value — exactly how the live loop values a real position (a trailed/breakeven stop would flatter the number identically live). Live path byte-identical (PaperActive() false). Both call sites (guard veto + Comment panel) covered by fixing inside FleetOpenRisk.
- Diagnosis honesty: the 07:45 refusal was the total-risk guardrail firing CORRECTLY on paper numbers (min-lot $6.01 > 15% x $37.09 = $5.56, arm A flat) — the fleet blindness produced a $0.00 panel operand and misattributable veto classes, not that refusal. The fix makes the guard truthful; it would not have admitted the signal.
- Deploy discipline: v26.37 bumped, manifest re-pinned deliberately with the drill-proven rationale recorded in the manifest itself, 0-error/0-warning compile (FB9A tree) then 640 files synced to 5 instances with the build gate passing, both arm hosts restarted by PID, banners verified (v26.37, PAPER MODE, Session=00-00, FIT ROUTER evaluating), virtual equity restored exactly (A $30.73, B $42.72), both arms flat at restart so no force-close, telemetry fresh on both hosts. V75MacroEngine untouched at v2.23. Morning status green: A 14/30, B 9/30, C 0/30 — gate clock unchanged.
- Playbook defect register amended (4 mentions): account-guard paper basis moved to fixed, with the rule that a nonzero paper account-guard count after v26.37 is a NEW defect; rehearsal log gains the closure entry. Test note: the 7 test_go_live_artifacts failures are pre-existing (expect the v27 go-live-artifact line's markers; fail identically with the edit stashed) — not caused by, and not blocking, this fix.

## [NO-GO playbook rehearsed end-to-end on live data (DRILL) — R1/R2/R3 all pass, five findings folded back into the playbook] - 2026-09-15

### docs/NO_GO_BRANCH_PLAYBOOK.md §8 + artifacts/v75_replay/nogo_playbook_drill_20260915.json — the first real execution will not be the first execution
- Step 2 R1 **PASS — exact reproduction** of the baseline of record (n=114, +4.37R, +0.0383R/t, t=0.35, funnel shape identical) from the pinned harness (study_frozen_certify_v75.py), proving the playbook's harness-pinning amendment works under drill conditions. The §2 command sketch itself FAILED verbatim — the spec-integrity guard requires all four spec vars alongside CERT_DATA_DIR, and the CERT_DATA_DIR placeholder was unresolved; the working invocation is now recorded in §7 (findings F1/F2).
- Step 2 R2 **PASS** — baropen-mode reconciler over arm A (14 closed trades; playbook says final 30 — F5): ΔR +0.002, CI [−0.229, +0.341] covers zero, reason-agreement 0.857 ≥ 0.75, zero exit violations → MATCHED. R3 **PASS** — live spread ~7.7% TIGHTER than the 18.5 model (spot 17.08; fill-shift median 8.32 = half-spread at entry): no cost regression.
- Step 3: ΔR/t = +0.0031 (slope +0.0022 × 1.42-unit gap) — immaterial by the frozen ±0.02 band; no spread-regime shift. Drill finding F3: the Step-3 "spread telemetry cross-check" is impossible — the arms' telemetry carries no spread field; fill-vs-mid + the reconciler's fill-shift carry Step 3 alone, and TickRecorder enablement would fix this permanently.
- Step 4: rate-normalized funnel diff, no comparable counter diverges >2× (spread-gate, risk-cap, auto-disable, meta-label, time-block, family-throttle all match-direction; replay's 1002 pauses not comparable — its loss-streak stretch predates the ~6-day journal retention, F4). Account-guard fired 1× on FB9A — the known $0 paper-basis defect, counted separately per the playbook. Drill finding F4 also fixed procedurally: Step-4 diffs at real execution must use the overlapping window, or journals get copied into artifacts weekly.
- Frozen outcome mapping: the drill would map to Outcome A mechanics — deliberately NO edge statement; edge adjudication stays TJ1's job. Playbook §8 (rehearsal log, append-only) opened; changelog carries the R1/R2/R3 table per the playbook's own output contract.

## [Weekly ATR-drift monitor registered — the frozen $28 sizing bound is now revalidated from live data every paper_weekly run] - 2026-09-15

### scripts/atr_drift_monitor.py — new tool + paper_weekly §4 + protocol registration
- The arm-C sizing truth table froze min-lot stop-risk at $10.00–$17.85 from 8 tester fills — a function of H1 ATR(14) (SL = 2.0 × H1 ATR, V75MacroEngine.mq5), which drifts with the volatility regime. A drifting ATR silently invalidates the $100 MINIMUM-VIABLE floor (a formal arm-C-branch precondition). The monitor re-derives the whole table weekly from live H1 bars (1000-bar lookback, Wilder iATR replication) via the per-fill calibration chain k = risk$/volume/stop-dist read back from the surviving tester ledger (all 8 fills re-derived, band reproduced exactly).
- Frozen verdict tiers on the **p95 ATR geometry**: HOLD (≤ $20 worst stop) / WATCH ($20–24, $100 row stale → review) / AMEND (> $24, formal append-only amendment required before any live decision cites the table), symmetric SHRINK-WATCH at the low tail (≤ $5), CALIBRATION-DRIFT caps at WATCH, SKIPPED-STALE on a feed older than 3h (never HOLD on old data).
- **First reading fired WATCH on day one**: p95 ATR 688.8 → worst min-lot stop $20.50 vs the $100 row's $20 budget; $100 re-derives as PARTIAL at the tail, $120/$150 hold; today's band [10.86–18.12] still brackets the frozen [10.00–17.85]. The table is sound at the median and marginal at the volatility tail — exactly what WATCH means. History: artifacts/v75_replay/atr_drift_monitor.json.
- Registered in GO_LIVE_CHECKLIST (validity-monitor section, verdict tiers, first reading) and ARM_C_TEMPLATE §4 (AMEND suspends the template's preconditions until the amendment lands); wired into paper_weekly as section [4] with NEXT-ACTIONS propagation and a monitor crash can never take the weekly leg down. Unit checks: Wilder ATR vs synthetic ramp, band math, verdict boundaries, row re-derivation, calibration reproduction — all pass; full pipeline re-run green (weekly leg CERTIFIED).

## [Arm-C adjudication rule pre-registered — the arm-C branch is now executable, not aspirational] - 2026-09-15

### docs/ARM_C_TEMPLATE.md — frozen before any candidate config exists, per OPERATING_SUMMARY §3
- The tree's arm-C branch required "a NEW pre-registered adjudication rule (candidate vs arm A reference) BEFORE the candidate's 30th trade" — now written, frozen, and fill-in-the-blank only at activation. Key design facts, all measured not assumed: the two engines do NOT share a signal stream (arm_b_rate_decomposition_20260915.json), so the A/B nearest-epoch pairing cannot transfer — the rule is a **daily-paired concurrent-window design** (d_i = meanR_C(day) − meanR_A(day), Welch t vs 0) with arm A as the reference stream.
- Gates G1–G4 frozen: ≥30 closed trades; ≥21 days coverage with A alive; ledger integrity (WLOST quarantine, unmatched CLOSE, canary alarms); input-contamination check vs the activation snapshot. The hybrid-study lesson is built in — C's veto/skip funnel is diffed against A's and reported, so the $50-scale risk-cap strangle confound can never masquerade as an edge result.
- Verdict mapping frozen: CONFIRMED (n_d ≥ 15, T ≥ +1.0, mean(d_i) > 0, totalR_C ≥ totalR_A, all gates clean → LIVE preset changes only through the certified chain); REJECTED (T ≤ −1.0 → teardown, no re-tuning); INCONCLUSIVE (collect to n_d = 30 paired days max, then REJECTED-with-honor — INCONCLUSIVE is never read as encouraging, same discipline as TJ1). Scarcity tie-breaker points at INCONCLUSIVE, never at a verdict.
- Preconditions wired to the standing rules: TJ1 adjudicated uncontaminated first; candidate entered through the study chain; the sizing truth table's $100 minimum-viable floor is a formal precondition (below it G1 is unreachable — the geometry is INERT). Teardown unchanged. Cross-linked from OPERATING_SUMMARY §3 and the GO_LIVE_CHECKLIST sizing section.

## [Spike-continuation study: the cascade-correlation claim is a market-level fact — 516 spike crossings continue, controls revert] - 2026-09-15

### docs/SPIKE_CONTINUATION_STUDY.md — position-free design frozen before the run; single run adjudicates the claim
- The stop-gap decomposition's "spike fills land into cascades" rested on 2 paper trades. This study tests it on the whole tick corpus (3.88M ticks, 8,640 M15 bars, 07-07→09-02) with **no positions involved**: 2,421 events where price crossed a 1R-away level, split by the frozen signature — spike (crossing within 10min + range > trailing-p90), fast-control, slow-control.
- **Primary (frozen): Δ2min = +0.1785R (spike minus slow), permutation p < 0.0001, CI [+0.153, +0.204]; sign consistent at 30s and 8min → CLAIM TRUE.** Spike crossings continue a median **+0.334R further within 8 minutes** with **78.5%** probability; fast-but-ordinary crossings *revert* (−0.15R) — it is the spike signature, not speed alone. The paper-measured 0.251R overshoot sits inside this distribution.
- One implementation bug caught before any result was read (list-index-vs-epoch base in the speed test forced all events "slow"); the fix touched only that base, not the frozen definitions.
- Consequences recorded: the hybrid study's L1 book (ladder + measured overshoot) rests on validated mechanics — its risk-cap strangle finding stands; the "structural, not luck" verdict gains a market mechanism with ~260× the original evidence. Caveat kept: position-free proxy level (prior close ± 1 median-TR); exact engine per-fill overshoot still best measured via paper stream or an enabled TickRecorder.
- Tool: `scripts/spike_continuation_study.py`; artifact `artifacts/v75_replay/spike_continuation_20260915.json`.

## [Hybrid exit study: pre-registered, run, and FAILED — the frozen gates kill the candidate before paper] - 2026-09-15

### docs/HYBRID_EXIT_STUDY.md — hypothesis frozen before implementation; result appended same-day (§7)
- **G0 (control) first caught real harness drift:** the worktree `certify_v75.py` no longer reproduces the certified baseline (n=84, −14.57R vs n=114, +4.37R — it gained micro-fit 1.5% and the sd ≥ 107.7 min-stop floor since the 09-05 commit `841bf97`). Study rebuilt on a frozen snapshot `scripts/study_frozen_certify_v75.py` (HEAD + only the registered exit-mode patch); H then reproduces the baseline **exactly**. The NO-GO playbook's R1 amended to pin harness versions.
- **Three books, one shared signal stream, identical management:** H (first-touch stops + bar-open management = the hybrid) +4.37R/n=114; L0 (engine bar-open ladder mirrored, ideal spike fills) −2.36R/n=117; L1 (ladder + the paper-measured −0.251R spike overshoot) −4.61R/**n=6**.
- **G1 FAIL:** H−L0 mean ΔR **+0.0391R/t** vs the frozen +0.08 bar (t=+1.33, CI [−0.015, +0.099] straddles 0, 3/6 positive folds vs 4/6 required). The hybrid's edge is half the materiality bar and not significant — **the candidate is dead and does not go to paper.**
- **Mechanism finding (promoted, not buried):** L1's book strangled at $50 — the −0.251R/stop drag triggers **589 risk-cap vetoes** until the 20% cap silences entries. At tiny scale the overshoot pathology is an **account-scale problem first**, an exit-model problem second; any future exit work must be sized-aware.
- **Honest bookkeeping:** the frozen books ignore the engine's intrabar TP spike-exit (conservative against the hybrid — G1's failure is not a modeling bias artifact); worktree `certify_v75.py` restored byte-equivalent in behavior to its pre-study state after the study ran (safety run reproduces n=84/−14.57).

## [STOP-gap decomposition amended for the 10th STOP — verdict unchanged and stronger: structural, not luck, not bar-open gaps] - 2026-09-15

- Arm A's 10th STOP (09-15 10:45, SC9, −1.271R) postdates every offline tick corpus (TickRecorder is default-OFF), so the structural test was extended with live-terminal M15 bars via the MT5 API: **1000 bar-opens** (2× the morning's 575). Max boundary jump 0.067R; P(jump>0.1R) still 0%.
- The new exit is a bar-open ladder stop with **0.271R overshoot** — but its boundary jump was only 0.023R: ~0.25R of the cost is **intra-bar drift past the stop**, invisible to the 15-min ladder. Arm B took the identical signal and printed the identical exit price and R — paper-internal reproducibility, not arm-specific luck.
- Aggregates on n=7 gap events: total **−1.760R**, mean **−0.251R**, bootstrap CI [−0.411, −0.114]; **drop-worst robustness (n=6): CI [−0.304, −0.082] — still excludes 0**. Drag −0.185R/day over the 9.50-day span (−0.126R per closed trade). Sign test 7/7 adverse (p=0.016) noted as construction-biased; the magnitude tests carry the argument.
- New conditional test closes the last regime excuse: E[bar-open jump | prior-bar range quartile] is **flat** (0.0134→0.0153R) — big bars do not produce dangerous boundaries, and the two big ladder overshoots occurred after a p91-range and a p8-range bar respectively.
- Counterfactuals updated for 14 trades: ledger −4.160R, every-tick ladder −5.818R, hybrid −2.400R; net cadence package **+1.658R** to the ledger. The hybrid (per-tick first-touch stop + bar-open management) remains the one falsifiable candidate via the certified path only.
- Amendment block appended to `artifacts/v75_replay/stop_gap_decomposition_20260915.json` (append-only, dated).

## [NO-GO branch playbook pre-registered — the day the gate fires becomes procedure, not improvisation] - 2026-09-15

### docs/NO_GO_BRANCH_PLAYBOOK.md — frozen before adjudication
- Fires on exactly one condition: `ab_adjudicate.py` output arm-A negative (or INCONCLUSIVE-negative → read-only diagnostics, collection continues per the standing rule). Excludes the arm-B-wins branch, P3 leg failures, arm C.
- **Step 1 freeze:** byte-copy ledgers, record adjudicator's own numbers, arms keep running, zero knob-touching.
- **Step 2 re-baseline drill:** reproduce `cert_report_fresh60_tp18_net.json` (+0.038R/t, t=0.35, n=114 — the tree's cited baseline, never distinguishable from zero) on the fresh-60-day window with acceptance checks R1 reproducibility / R2 stream-vs-replay (baropen-mode TJ2 bars) / R3 cost regression (>10% live-vs-model spread gap).
- **Step 3 spread pricing:** the frozen +0.0022R/t-per-unit slope from the tier study (−25-unit bar to clear +0.08R/t; zero-spread ceiling already failed materiality) — live mean spread measured from fills+telemetry, priced ±0.02R/t materiality, venue hunting explicitly closed.
- **Step 4 funnel diffs:** replay funnel (`certify_v75.py`: score/spread-gate/risk-cap/paused/time-block/auto-disable/family-throttle/pb-failure-classifier) vs live journal greps of the v26.36 SKIP/SUPPRESS print strings, **rate-normalized per 1000 signals**; account-guard's known $0 paper-basis defect counted separately so a machinery cause can't masquerade as an edge result.
- **Frozen outcomes only:** A (stream healthy, edge absent → config retired from live consideration, collection continues as research), B (machinery cause → certified-chain fix + one pre-declared re-adjudication), C (cost regression → re-price at live spread; collapses into A). Hand-tuning illegal under every outcome; re-entry to live consideration requires hypothesis doc → VALIDATED-CANDIDATE on fresh window → new arm ≥30 trades under new pre-registered rule → go-live gate, in that order.
- Cross-linked from the decision tree (`OPERATING_SUMMARY.md` §3 branch) and `GO_LIVE_CHECKLIST.md`'s verdict item.

## [Arm B rate decomposition — 8-vs-13 is uptime, not TP geometry and not the 24/7 switch] - 2026-09-15

### Question: is B's slow trade rate (8 closed vs A's 13) the TP 2.4 geometry or the session change?
- **Neither.** OPEN rows prove one **shared signal stream** (identical entry epochs/tags across arms on shared bars — 16 distinct entry events). The arms diverge only by availability: B missed the 5-entry 09-10..11 block while its host was offline (71BF added 09-14, ~14h less live clock than A), and B missed one signal to restart-repair cooldown. TP 2.4's blocking cost is measurable and tiny: median holds differ by ~0 bars (2.75h vs 2.6h), TJ1-era in-trade overlap 4.4% → **~0.1 expected lost entries** of the 5-entry gap. Rate while both were live and on-session: 1.18/day (A) vs 1.06/day (B) — near-identical.
- The 24/7 switch has **zero negative effect** — it strictly widens the shared signal window; the residual `SESSION-OFF` prints come from pre-restart loads still carrying the contaminated 06-21 window (FB9A showed 3× `Session=06-21` loads before its 08:16 `Session=00-00` load — the 09-14 16:31 reload is the suspected regression vector; repaired by the morning's preset rewrite).
- Side-findings for follow-up: (1) B's 06:47 entry was force-closed by the 08:16 upgrade restart via the historical-restore path; (2) A's 07:45-bar signal was refused by the fleet **ACCOUNT GUARD** reading fleet equity as $0.00 in paper mode — fleet-equity basis under paper needs a look; (3) one pre-restart B fill (07:47 v26.35) never reached the ledger (restart-closed) — verified writers intact.
- Recorded in `artifacts/v75_replay/arm_b_rate_decomposition_20260915.json`.

## [Arm C minimum viable size pre-registered — $100 floor, $150 buffer, own truth table in the go-live checklist] - 2026-09-15

### Pre-registration — frozen before any arm-C sizing decision exists to bias it
- Grounding frozen from the v2.23 tester measurements (8 real fills, stops 1121–1466 pts): **min-lot (0.01) stop-risk $10.00–$17.85, typical $14–17.85**, engineering bound ≈ $28 at the 2× median-ATR stop. Production 1%-risk input can never fit this geometry below ~$1,800 — a live attach would require a pre-registered risk-input change through the certified chain, never a silent edit.
- Truth table ($50–$150, per the global 20% cap): **$50 INERT (measured — every entry refused)**; $75 NOT VIABLE (unpredictable partial admission); $85 MARGINAL; **$100 MINIMUM VIABLE** (all 8 measured geometries admitted); $120 headroom; **$150 RECOMMENDED BUFFER** (covers the ≈$28 bound). The knife, stated in the doc: at $100 one stop = −17.9%, and the arms' observed 3-loss streak compounds to ≈ −45% on running equity.
- Governance: the truth table is a **precondition, never an authorization** — live arm C additionally requires the arm-C branch (VALIDATED-CANDIDATE + pre-registered adjudication, `OPERATING_SUMMARY.md` §3); until then its FB9A run stays a collection-only regime exercise. Amending the frozen numbers requires a protocol amendment.
- Recorded in `docs/GO_LIVE_CHECKLIST.md` (new "Arm C sizing truth table" section beside the arms' $50 table).

## [STOP-exit gap decomposition — the cost is real but NOT bar-open gaps; the bar-open cadence package is net +1.9R on the sample] - 2026-09-15

### Question — how much did bar-open gap slippage cost arm A's 9 STOP exits vs the tick ladder, and is it structural or luck?
- **The cost is real and located:** 6 of the 9 STOPs were original-stop hits; total gap-through **−1.489R** (mean −0.248R/stop, bootstrap CI [−0.433, −0.089] — excludes 0), i.e. −0.29R/day over the 5.09d window vs the certified replay edge of ~+0.10R/day. Split: 4 bar-open-ladder exits −0.457R, 2 per-tick spike-path exits −1.033R.
- **But the hypothesis is dead:** measured over all 575 bar-opens in the window, V75 **does not gap at bar-opens** — max jump 0.048R, P(jump>0.1R) = 0%, E[jump | jump>0] = 0.014R, and 3 of the 4 ladder-exit overshoots sit right at that expectation. The two big overshoots are spike-path fills into intra-bar cascades, at the 15th and 69th percentile of the ordinary intra-bar range distribution (median 0.539R) — correlated with their own trigger, not freak luck.
- **The offsetting side of the same cadence:** the bar-open ladder lets winners ride past where an every-tick ladder would cut them — +1.833R (TP 2.521 vs ladder SL 0.688), +1.320R (TP vs PLOCK), +0.265R — total **+3.418R**. Net cadence effect on the sample: **+1.929R in the ledger's favor** (ledger −2.889R vs every-tick-ladder −4.818R).
- **Counterfactual table (diagnostic):** every-tick ladder −4.818R; ledger as-run −2.889R; hybrid (per-tick first-touch stops + bar-open management) −1.399R. The hybrid is a falsifiable candidate, nothing more — it changes engine behavior and must go through the certified path (study → fresh window → paper arm); n=13 makes all of this fragile.
- Verdict: stop gap-through is **structural (intra-bar path continuation vs 1R stops), not bar-open gaps and not luck**; the engine's bar-open cadence was net-positive on this sample and must not be "fixed" by hand. Evidence: `artifacts/v75_replay/stop_gap_decomposition_20260915.json`; the reconciliation artifact re-finalized in baropen mode (MATCHED).

## [Sunday pipeline dry-run — all four legs verdicted; two leg crashes fixed; recon leg moved to the bar-open baseline] - 2026-09-15

### Fixes — pipeline legs that silently died on today's run
- `paper_weekly.py` crashed with `UnicodeEncodeError` under the pipeline (child stdout through pipes used the cp1252 console codec; the report's `→` is unencodable). Fixed: the tool reconfigures its stdout to UTF-8-replace; the pipeline decodes children as UTF-8 (and emits UTF-8 itself), with `PYTHONIOENCODING=utf-8` exported to every child. Leg verdict restored: **CERTIFIED**.
- `regime_gate_study_v3.py` crashed with IndexError: its v2 clean-OOS context block slices `build_folds()[16:]` — defined on the retired 210-day window's 26 folds, but the current certified dataset is the fresh 60-day window with 7 folds. The block now skips honestly with an explanatory note when F17-F26 don't exist (the paper branch and its pre-registered verdict are unaffected); the 0-closed-trades path also prints its `Verdict:` line so the pipeline can parse it. Leg verdict restored: **KEEP COLLECTING (no closed paper trades)**.
- `paper_pipeline.py` recon leg now runs the reconciler with `--mode baropen` (amendment 2026-09-15 — the engine evaluates its ladder per M15 bar-open; the every-tick walk remains available as `--mode tick`).
- Note: `ab`'s ETA arithmetic uses each arm's own observed rate — B's 8th trade was a loss collected slowly, so its ETA reads ~25d vs A's ~7d; the duel adjudicates when BOTH arms reach 30.

## [Paper-ledger writers hardened — verified append with retry + WLOST quarantine; v26.36 + v2.23 deployed to all three arms] - 2026-09-15

### Why — close the silent-row-drop defect class for good (audit found one lost CLOSE row)
- **The class:** every writer in both engines appended with unchecked `FileWriteString`/`FileWrite` results and printed success unconditionally — a failed open/append stayed invisible while the journal claimed the row was written. That is how arm A's ledger lost trade #5's CLOSE row (2026-09-08 00:30) without a trace.
- **The fix (`AppendVerified` in MitemshubAI v26.36, `AppendVerifiedV75` in V75MacroEngine v2.23):** a row only counts as written when the bytes are **verified on disk by re-reading** (file size must have grown by the row length after close — deliberately not trusting `FileFlush` return values, which this MQL5 compiler build returns as void); one retry with a 50 ms backoff; a row failing twice is **quarantined to the journal with the `WLOST` tag** including the full row content, so it is loud, greppable, and hand-restorable. Wired into every hot writer: paper ledger (OPEN/CLOSE/EQ), telemetry JSONL, and the trade-history CSV (header handling preserved).
- **Watchdog counterpart:** `morning_status` now scans each arm's today-journal for `WLOST` and alerts unhealthy (the quarantined row never entered the ledger file, so ledger parsers alone can never see it); 2 new unit tests pin the scan. The canary gained telemetry-after-banner as liveness evidence earlier the same day (24/7 quiet bars journal nothing; pinned by 2 tests) and was refactored onto a shared `journal_lines_today` helper.
- **Deploy discipline:** v27 WIP backed up to `MitemshubAI_v27_research_backup.mq5`, v26.35 restored from HEAD as the patch base, hardening applied, bumped to v26.36 (VTAG single-source; no strategy/config change — the arms' equity continuity $37.09/$55.20 and both presets' signatures verified in the boot banners, `Session=00-00` intact). Manifest re-pinned twice after compile-gate iterations corrected my own code (the gate refused my edited bytes both times — working exactly as designed); final shas `48a4d866…` (v26.36) and `2e164ff8…` (v2.23); sync 640 files, build gate green ×5 trees; both terminals restarted and banner-verified on the new builds (all three arms flat during the restart).
- **Validation:** V28 research suite + canary (13) + liveness + collector + V75 surface: **90 passed**. The arm-C tester drill re-run end-to-end on v2.23: production config still correctly refuses every entry at the $50 floor (min-lot guard), config-variant pass produces **8 OPEN / 8 CLOSE / 8 EQ with zero problems, watchdog parse 8 closed / veq 44.61 / no problems, telemetry fill:8 close:8** — the hardened append path produces byte-valid ledgers under real tester fills.
- MQL5 note recorded for future patches: `FileWrite` and `FileFlush` are void-typed in this compiler build (error 151 on return-value use) — byte-count + on-disk re-read verification is the portable pattern.

## [24/7 collection live; three config/integrity defects found and fixed; TJ2 bar-open baseline amendment proves the paper engine MATCHED] - 2026-09-15

### Why — the operator directive: stop gating collection on a session, keep the terminals open, fix every defect found
- **No session gate existed in the engines — it was config.** Both arm charts carried `InpSessionStartHour=6 / InpSessionEndHour=21` (the v26.35 code defaults; the certified presets say 0/0 but were never the source of the chart inputs). Both arms now boot with the certified preset applied byte-exact and the banner proves it: **`Session=00-00`** (FB9A 06:41:10, 71BF 06:41:12). Collection runs 24/7 from the terminals staying open; V75 arm C never had a gate and collected through the nights all along (03:00 telemetry writes).
- **Defect 1 — arm A's chart had silently lost its preset** (most likely in the 09-13 WIP re-attach churn): the chart carried TP 2.4 + Breakout/BandFade ON (v27-style code defaults) instead of the certified FINAL preset (TP 1.8, Breakout/BandFade OFF). The duel was protected by luck, not design: the ledger's own OPEN rows prove **all 13 closed trades ran TP 1.8** (TP/SL distance ratio exactly 1.8 ×13) — the drift happened after the last close. Any fill from the drifted chart would have been off-strategy and polluted the A/B. New tool `scripts/set_chart_preset.py` writes a preset byte-exact into a chart's `<inputs>` block (removes keys not in the preset so code defaults can't masquerade as config), with backup + re-parse verification; both arm charts repaired from the certified presets.
- **Defect 2 — one ledger CLOSE row silently failed to write.** State says 14 trades / −2.3886R; the ledger has 13 CLOSE rows / −2.8886R. Reconciled exactly: 13 rows − 0.50R (trade #5, the STOP +0.456R winner whose close fired on 09-08 00:30) = 14-trade state total. The surviving journal coverage (files for 09-05..07 are gone, MT5 rotation) cannot pinpoint the mechanism, so it stays classed as an unattributed silent write drop; the ledger is the adjudication source and the loss of a winner is conservative. The writer-hardening fix (verified append with retry + loud failure tag) ships in v26.36 rather than an out-of-band change to the certified build.
- **Defect 3 — the collector test asserted a foreign broker's symbol table.** `tests/test_mt5_collector.py` expected `R_75 → SYN75`; live probe via the MT5 API on the operative account (DerivSVG-Server-03) shows **SYN75/SYN100 do not exist** and `Volatility 75 Index` does (bid 45987). Code was right, test was wrong (written against a different Deriv server); test corrected to the operative reality, 5/5 pass.
- **TJ2 closed with evidence (amendment 2026-09-15, pre-registered before bar-open data was scored):** `reconcile_paper_ticks.py --mode baropen` evaluates the ladder on the first tick at/after each M15 boundary (the engine's `new_bar` gate semantics) while keeping SL/TP boundary hits per-tick (the engine's spike-exit path is per-tick). Same 13 trades: **bar-open baseline → ladder delta +0.022R, CI95 [−0.230, +0.382] covers 0, reason-agreement 0.846 ≥ 0.75, zero exit-price violations → MATCHED**; every-tick baseline unchanged (+0.188R / 0.692 → REASON-DRIFT), so the 09-14 result is reproduced, not overwritten. The "drift" was evaluation cadence, not mechanics. Artifact final state: `MATCHED | mode: baropen`. TJ2's arming question is resolved: when arm A reaches 7 days of ledger, the baseline tests the engine's actual hypothesis.
- **Canary amended for 24/7 reality (caught live, false-positive → fixed within the hour):** with sessions off, a quiet bar journals nothing, and the init-silence canary fired on both healthy arms at 06:41+20m. Telemetry is admissible liveness evidence (heartbeats write every bar even when the journal is quiet): the corpse signature remains exactly *banner, then no journal line AND no telemetry write ever*. Live: both arms `canary ok (telemetry written after init)`; 11 canary tests pass including two new pins (telemetry-after-banner ok; telemetry-only-before-banner still alerts).
- Ponytail review (over-engineering hunt) over the new tooling: one dead `import random` removed from the reconciler; everything else lean.
- Full battery: pytest suite green (collector fixed; the rest of the 1,275-test run unaffected by today's changes), sync steady-state 630 files / 0 pruned / build gate green, deploy gate held throughout.

## [Arm C paper-ledger tester validation — CLOSE row proven end-to-end; two v2.21 ledger defects found and fixed (v2.22); arm C config inert at the $50 floor] - 2026-09-15

### Result — the watchdog reads a filled V75 paper trade end-to-end (verdict PASS, with one pre-registered operational finding)
- Drill (`scripts/validate_armc_paper_ledger_tester.py`, new): drives V75MacroEngine v2.22 in **paper mode** through the Strategy Tester headlessly on 49E0 (tester-only terminal; the arms' terminals were never closed — preflight checks the tester *install* is not running, per-install not global), over the cached 71-day real-tick window with arm C's exact chart inputs. Validates every row against the v2.21/2.22 writer schema, replays equity from the ledger's own columns ($50 start), then hands the file to the **real watchdog parser** (`morning_status.parse_ledger`) — the same object the A/B machinery consumes.
- **Variant pass (risk=40%): 8 OPEN / 8 CLOSE / 8 EQ rows, equity replay exact (44.60 == ledger 44.61), R accounting exact per trade, watchdog parse: 8 closed, zero problems, telemetry `fill:8 / close:8` alongside 3407 heartbeats and 1353 signals.** All exits ECUT (2h timeout) — matching the regression gate's established all-timeout pattern on this window for the wide-stop geometry (0 SL/TP hits; the stop is disaster-only by design).
- **Primary finding (pre-declared as a possible outcome, now measured): the production config (1% risk at the $50 virtual floor) is INERT — every entry refused** (`PAPER TRADE REFUSED: computed volume < broker minimum`, max computed volume 0.008 vs the 0.01 min lot). Arm C's 2×H1-ATR stop implies min-lot stop-risk **≈ $14–17 = 28–34% of $50** — the arms' "$50 tolerated at 9–13%/trade" story does **not** transfer to this geometry (their stop is ~$4.6–6.5). The engine's guard behaved exactly as designed (never violating the risk contract); recorded in `docs/GO_LIVE_CHECKLIST.md`: **arm C needs its own pre-registered minimum viable size (~$85–120 at ≤20%/trade) before it can trade anywhere** — until then its FB9A paper run is a collection-only regime exercise.
- **Two v2.21 ledger defects caught by the drill, fixed in v2.22:** (1) the OPEN writer emitted **13 fields** (an extra ATR column shifted every field after col8 off the arms' schema — the A/B adjudicator would misread volume as risk); (2) the `%.5f` SL/TP slots were fed `DoubleToString` *strings*, which MQL prints as `0.00000` — OPEN rows carried zeroed stop/target geometry (the virtual book itself was correct; ECUT-only closes never touched the broken columns, which is why live telemetry looked healthy). v2.22 writes the arms' exact 12-field schema (`OPEN,ts,ticket,dir,entry,sl,tp,vol,eff_risk$,stop_dist,max_hold,tag`), numbers as numbers; CLOSE rows switched from string-arg to numeric formatting in the same pass.
- **Identity discipline:** the first v2.22 deploy still printed "v2.21" in its init banner — a hardcoded string behind on the version bump, caught on the FB9A reload before any restart-dependent validation ran. The banner now derives from a single `ENGINE_VERSION` macro (the canary greps this line as run identity); re-pinned (sha `ad53c09…`), redeployed (0 errors ×5 trees), and FB9A arm C verified live on `v2.22 initialized (…PAPER)` at 01:32. Arms A/B untouched throughout (deploy gate held; B's "stale" telemetry in the same window is the session-off boundary, not a fault).
- Evidence: `artifacts/v75_macro_engine_tester/armc_paper_ledger_20260915.json` (both passes, identities v2.22, verdict PASS, findings block with the refusal measurements); sandbox-clear before each pass documented in the drill (append-only writers would otherwise splice runs).

## [sync-mt5 -AllowWip liveness gate — a WIP must prove it is alive before it may deploy over the arms] - 2026-09-15

### Added — telemetry-liveness evidence requirement on the explicit bypass path
- Closes the last sanctioned-accident path from the 2026-09-13 incident class: `-AllowWip` previously deployed any mismatching worktree source on a bare human assertion — the exact action that froze both paper arms for ~2 days when it happened *without* intent. The bypass is now machine-checked: `sync-mt5.ps1 -AllowWip` runs `scripts/check_wip_liveness.py` (verify mode) against the worktree bytes **before** deploying, and refuses fail-closed when the recorded evidence does not validate them (exit 1, deployed builds untouched, exact staging remedy in the message).
- What counts as proof (pre-registered 2026-09-15, seven conditions C1–C7, all required on at least one terminal): the source declares its own version (bindable banner); evidence comes from a **non-arm terminal only** — any chart carrying 7788075/7788100/7788125 excludes the terminal, since a WIP already sitting on an arm is the incident, not evidence; the staging terminal's deployed source sha256-matches the worktree source and its `.ex5` is fresh (the running build IS these bytes); a version-bound init banner on the EA's own journal channel (today/yesterday, real 4th-field channel format); the banner ≥ one bar-grace old (16m MitemshubAI / 31m V75MacroEngine — at least one bar interval to live); ≥1 post-init journal line (the inverse of the banner-then-silence signature the morning_status canary alerts); and telemetry written **after** the banner.
- Modes: `--collect` probes the running terminals and records `artifacts/deploy_wip_liveness.json` — FAIL attempts are recorded too, the audit trail matters; verify (default, called by sync) re-checks that artifact against the **current** worktree bytes, so any edit after validation re-locks the deploy, and rejects evidence older than 48h (`--max-age-hours`).
- Staging flow (recorded in the `scripts/deploy_manifest.txt` header): copy the WIP into the staging terminal's Experts tree manually (a sync refuses it), compile in place, attach to a chart, wait one bar interval, `python scripts/check_wip_liveness.py --collect --src <src>`, then sync with `-AllowWip`. **49E0** — tester/reserve-only, no arm magics by construction — is the staging terminal (role noted in `docs/OPERATING_SUMMARY.md`).
- Verified: live `--collect` on today's terminals returns FAIL with the correct per-terminal reasons (FB9A/71BF excluded as arm hosts; 49E0/Common/Community fail sha binding against their deployed v26.35 copies) and the artifact records it; `-AllowWip` dry-run now exits 1 with refusal + remedy (previously it deployed); steady-state sync without `-AllowWip` unchanged (630 files, 0 pruned, build gate green, exit 0). 12 new unit tests (`tests/test_wip_liveness.py`) pin every condition with synthetic terminals in the real journal/chart formats — including the 09-13 banner-then-silence signature, the arm-terminal exclusion, byte-drift refusal, wrong-version banners, and the V75 family path (31m grace, own file names). Full suites: 52 passed.

## [TJ2 tick reconciliation on arm A (13 trades) — R agrees, exit reasons drift: the paper ladder runs per bar-open, the baseline per tick] - 2026-09-14

### Finding — pre-registered verdict REASON-DRIFT; mechanism identified as evaluation cadence, not bookkeeping drift
- Run: `reconcile_paper_ticks.py` on arm A's 13 closed trades (2026-09-05 21:45 → 09-11 12:00; **5.09 days close-to-close — formally below the 7-day arming gate**, run as an early look at `--min-days 5`, coverage recorded in the artifact so nothing is overstated). Window ticks auto-pulled read-only from the broker via the MT5 API; ladder constants imported from `study_fastfail_ticks`, so the baseline cannot silently diverge from the study.
- Pre-registered verdict: **REASON-DRIFT** (F3 reason-agreement **0.692 < 0.75**), even though every R-leg passed: mean ladder delta **+0.188R**, bootstrap CI95 **[−0.157, +0.593] covers 0** (not OPTIMISTIC-DRIFT), **zero** exit-price violations (F4), integrity ok, 13/13 simulated, fill-shift **+8.32** ≈ the designed entry-shift conservatism (spread multiplier). Mean abs delta 0.472R.
- Structure of the drift (per-trade table): all four reason mismatches are **ledger-better** — TP-vs-trail divergences (+1.833, +1.320, +0.872, +0.265R) where the ledger rode to target while the tick ladder PLOCKed earlier — while pure-STOP trades show the ledger *worse* than the ladder (−1.63, −1.40, −1.31 vs clean −1.00 exits: gap-through slippage a bar-open ladder cannot see). Ledger mean −0.222R vs tick-ladder mean −0.410R.
- **Mechanism, evidence not theory:** v26.35 evaluates its virtual ladder **once per M15 bar open** — `OnTick` returns early unless `new_bar` (HEAD `MitemshubAI.mq5` ~L1056) and `PaperManage()` sits inside that gate (~L1083) — while the study baseline walks **every tick**. Ledger timestamps confirm it: **11 of 13 closes sit exactly on M15 boundaries** (`epoch % 900 == 0`); the two mid-bar exceptions (the +2.521R TARGET at :724s and a STOP at :898s, with the mid-bar OPEN chained to that TP close in the same second) match the secondary per-tick spike-exit path. Config equality checked first (arm A chart inputs == study ladder: PLOCK 0.5 / BE 1.0 / trail 1.0/0.7), and the engine's ladder code is textually identical to the study's — cadence is the only remaining difference.
- Standing consequence: **TJ2 remains unarmed and unchanged** — the artifact records 5.09d < 7d, and a ≥7d arming would hit the same bar-open-vs-tick gap by construction. The real reconciliation question for the gate is "does the paper engine match a bar-open ladder baseline"; closing it needs either a bar-open replay mode in the baseline or a pre-registered allowance for cadence-driven reason drift. Neither is decided here — the frozen 2026-09-04 rules stay frozen until amended pre-registered.
- Evidence: `artifacts/v75_replay/paper_tick_reconciliation.json` (verdict REASON-DRIFT; arms.A: 13/13 simmed, integrity ok, mean +0.188R, CI [−0.157, +0.593], F3 0.692, F4 0, fill-shift 8.32, days 5.09).

## [morning_status init-silence canary — the loaded-but-dead EA signature now alerts within one bar] - 2026-09-14

### Added — canary anchored on the EA's init banner in its own journal channel
- Closes the detection gap that let the 09-13/14 v27 WIP freeze both arms for ~2 days: the WIP printed its init banner and then emitted **nothing** — no bar processing, no telemetry — across three loads on one terminal, while the existing watchdog only fires on telemetry age > 2h. The canary (`init_silence_canary`) anchors on the arm EA's newest init banner in **today's** `MQL5/Logs` journal (`initialized` / `vX.YZ started`), filtered to the EA's own 4th journal field (`MitemshubAI (…)` / `V75MacroEngine (…)` — sibling EAs' lines and name-prefix collisions like `MitemshubAI_v28` cannot satisfy it), and alerts when the banner is ≥ its grace window old **and** no journal line follows it at all.
- Grace windows are per-EA and must exceed one bar interval, because a healthy EA's first post-init journal line can be its first bar event: 16m for the M15 MitemshubAI arms, 31m for the M30 V75MacroEngine arm. Three non-alert states keep it honest: `armed` (inside grace — no false alarm right after a restart), `ok` with in-window lines (normal), and `ok` for a quiet period (banner at night before the session, resumed later — *later* processing proves life; ongoing cadence after that remains the telemetry-staleness check's job). An `alert` marks the arm unhealthy (strict exit 1) with the banner time and elapsed age in the message.
- Verified live against all three arms (`[OK] canary ok` ×3 — B: 2 journal lines within 16m of its 23:30 init; A: 2 within 16m of the 22:12 restart; C: 1 within 31m) and pinned by 9 unit tests in `tests/test_morning_status.py` using synthetic journals in the exact real line format — including the two traps that would matter in the field: channel isolation (another EA's banner/lines on a shared terminal must neither arm nor satisfy the canary) and the 09-13 scenario itself (banner + silence → alert).

## [Dedicated ARMS terminal — arm B migrated off the tester terminal; paper collection is now isolation-safe] - 2026-09-14

### Changed — the arms own a terminal that research never closes
- Motivation: arm B lived on `MitemshubMT5_B` (49E0) — the same terminal the V75MacroEngine tester requires closed for every regression run, and the 09-13/09-14 tester sessions froze B's gate clock for ~4 days in total. The arms now have a dedicated terminal research tooling must not touch: the idle **`MitemshubMT5_C`** install (data folder **71BF**), which was already credentialed for account 140778269 (journal-proven) and had been sitting powered-off since 09-05.
- Migration performed with the terminal off, mirrors of the arm-C chart activation discipline: B's six `MitemshubAI_*` ledger/telemetry/state files copied byte-for-byte with mtimes preserved; the parked 7788126 rehearsal chart archived (`chart01.chr.bak_parked7788126`, rehearsal Files archived under `_armC_rehearsal_archive_20260914/`) and replaced by B's exact expert block (magic 7788100, `InpLiveExecution=false`), re-parse verified before boot. First boot: authorized in seconds, full v26.35 startup, **`Loaded intelligence: Trades=7 WR=57.1% R=+0.64`** — the accrued history restored from the transplanted state, and a fresh `fit` telemetry event at the next M15 boundary. Zero errors in the journal.
- 49E0 retired as an arm host: EA detached from its chart with backup (`chart01.chr.bak_armB_20260914_233330`), its six arm-B artifacts archived (`_armB_migrated_20260914/`) so no duplicate `B_tp24` magic can ever run from there. 49E0 is now tester/reserve-only — the tester's close-and-relaunch cycle can no longer cost the gate any collection time.
- Verified by the watchdog: `morning_status` reports **2 processes hosting all 3 arms** (B_tp24 + C_v75 fresh; A_tp18 + C_v75 on FB9A), B with **no connection gaps** in its journal window, and ledger continuity intact ($55.20 / 7 closed unchanged). Topology recorded in `docs/OPERATING_SUMMARY.md` and `docs/GO_LIVE_CHECKLIST.md`: **71BF is paper-collection-reserved — tester runs and research sessions must never close it; the tester flow uses the default install (49E0).**
- Standing risk unchanged: FB9A hosts arm A + arm C and the future live chart, so a 49E0-style close never touches them — but if FB9A itself is ever closed for research, both its arms freeze; the strict watchdog (TJ3) is the tripwire either way.

## [sync-mt5 deploy gate — WIP can no longer reach the terminals by accident] - 2026-09-14

### Added — fail-closed sha256 manifest gate on the deploy script
- The 2026-09-13 incident (a routine sync deployed the uncommitted, non-functional v27 WIP over the certified paper arms and froze them for ~2 days) is now structurally closed: `sync-mt5.ps1` evaluates `scripts/deploy_manifest.txt` before touching any terminal, and refuses to copy/compile any EA whose worktree source does not match its pinned sha256 — pinned today: `V75MacroEngine.mq5` = v2.21 (live-validated on arm C), `MitemshubAI.mq5` = v26.35 (the certified arms build, HEAD's copy). The deployed copy is left untouched and protected from the prune pass. Repo-as-source-of-truth is preserved — the manifest lives in the repo and any new pin is a deliberate, diff-reviewable edit (validate → sha256sum → pin → changelog), never an accident of worktree state.
- Overrides: `-AllowWip` deploys a mismatching worktree copy **explicitly** (loud per-terminal bypass notice — the sanctioned path for shipping a validated candidate), and `-DryRun` previews the gate decision, per-file mirror plan, and compile plan without touching anything. Missing manifest ⇒ refuse everything (fail-closed).
- Gate-consistent plumbing: the mirror skips a gated source **and its binary artifacts**; prune (orphan + stale) skips gated files; the LIVE-EA build gate waives staleness for a gated source/binary pair but still fails loudly if a gated EA's binary is **missing** (a terminal restart would not reload it), with the exact remedy in the message; the stale-source check is scoped to the live build's actual inputs (`MitemshubAI.mq5` + includes), so sibling research EAs (`MitemshubAI_v28.mq5`) no longer false-trip it.
- Verified: dry-run on both paths (default denies 1 pin / mirrors 112 files; `-AllowWip` mirrors 113); steady-state sync PASS (630 files to 5 trees, 0 pruned, build gate passed, exit 0); all five deployed trees uniform on v26.35 (source sha `c13b5eb…`, fresh `.ex5`); V75 v2.21 deploys and compiles 0 errors throughout; arms' telemetry uninterrupted.
- **Incident during this change, recorded honestly:** the first gated sync deleted the arms' deployed `MitemshubAI.ex5` binaries from all trees. Two stacked causes, both fixed: (1) a gate check inside `ForEach-Object` used `return`, which skips only one script-block invocation, not the pipeline — the stale-prune then deleted the gated binary; the check moved into `Where-Object` (comment left in the script). (2) A zombie worktree binary `mql5/MITEMSHUB_AI/MitemshubAI.ex5` — the 09-09 **v27 build, gitignored and invisible to `git status`** — was mirrored over the restored binary with `Copy-Item`'s preserved old mtime, which prune 2b then correctly deleted as stale. Running EAs were never affected (loaded in memory); binaries were restored by compiling the deployed certified source in place (0 errors ×5 trees, `.ex5` fresh vs source), the zombie was removed from the worktree (recompilable from the v27 source any time), and two forgotten trees (Common, Community) that still held 09-09 v27 **source** were aligned to v26.35. A gated sync that finds a missing gated binary now names the failure and the fix instead of failing silently.

## [V75MacroEngine v2.21 — PAPER MODE: the engine becomes arm C on its own virtual book] - 2026-09-14

### Added — InpPaperMode: virtual fills, zero broker orders, watchdog-format bookkeeping
- Arm-C machinery applied to the macro engine: with `InpPaperMode=true` the EA runs its full pipeline (H4/H1 alignment, M30 springboard, 1% risk, 2h timeout, 1:2 ATR geometry) against **virtual equity starting at $50** (the same floor the paper arms started on), fills at ask/bid (the exit pays the spread), and **never touches `CTrade`** — no broker order can exist on the paper path, by construction. With `InpPaperMode=false` (default) the binary is behaviorally v2.20: same guards, same constants, same output lines.
- Bookkeeping lands in `MQL5\Files\` in the exact formats the A/B machinery already parses: `V75MacroEngine_paper_<symbol>.csv` (`OPEN,<12 cols>` / `CLOSE,<8>` / `EQ` — the MitemshubAI ledger schema, including the `PAPER` tag where arms store their session id) and `V75MacroEngine_paper_telemetry_<symbol>.jsonl` (per-bar `hb` heartbeat at **every** M30 open *before* any stand-down return — watchdog freshness must not depend on regime — plus `sig` with the trigger outcome, `fill` and `close` events). Virtual equity continuity is enforced through the EQ rows; geometry (entry/SL/TP prices, volume, slDistance, riskAmount) rides the OPEN row like the arms'.
- `morning_status.py` now discovers arm C (`C_v75`, magic 7788125 — the number pre-declared for the first VALIDATED-CANDIDATE in the operating summary's arm-C branch) via the V75 spelling `InpMagicNumber` as well as `InpMagic`, resolves **per-EA** ledger/telemetry names, counts distinct terminals hosting arms for the running-terminals check, and labels arm C as telemetry-only (NOT a gate input — the paper gate remains arms A/B).
- **Activation (2026-09-14 21:02, FB9A chart03):** the magic 7500 **live-capable** chart was re-inputted to paper mode + 7788125 while the terminal was closed (`.chr` backup kept: `chart03.chr.bak_live7500`). The 7788125 reservation on the parked 71BF chart01 (the arm-C template's MitemshubAI chart) was moved to 7788126 (`chart01.chr.bak_7788125`) so exactly one arm C exists. Init banner verified: `v2.21 initialized (LONG-ONLY, 2h timeout, PAPER)` + `virtual fills only`. First heartbeats landed at the 21:30/22:00 M30 opens. Aligned-DOWNTREND means entries wait for an uptrend regime — the arm warms up meanwhile.
- **Account ground truth (same sweep):** FB9A's account 140778269 is **REAL** (`trade_mode: REAL`, $50.22 — the go-live funding precondition is now MET), and all three terminals log into that one real account; paper safety is EA-level throughout. Recorded with the Algo-switch rule in `docs/GO_LIVE_CHECKLIST.md`; arm-C template amended (`docs/ARM_C_TEMPLATE.md`).
- Three defects found and fixed during activation, in order: (1) the first build logged the heartbeat *after* the macro stand-down returns, so a DOWNTREND regime (today's) would never write telemetry and the watchdog would false-alarm a healthy arm — heartbeat moved to the top of the per-bar block (the single-position gate lost in that edit was restored immediately); (2) the writers used `FILE_CSV`, which field-quotes verbatim comma rows and mangles the JSON line — switched to the arms' proven `FILE_TXT|FILE_ANSI|FILE_SHARE_READ` pattern, with loud errors instead of silent no-ops; (3) the file names embedded the symbol with spaces while the machinery convention (and `morning_status.py`) expects underscores — fixed via `PaperSymbolTag()`, existing telemetry renamed in place.
- Evidence: FB9A journal 20:43/21:02/21:35 init blocks; compile gates 0 errors ×3 terminals ×4 builds (final `.ex5` 22:12:00–05); telemetry file with `hb` records at eq 50.00 / magic 7788125; `scripts/morning_status.py` extended in the same pass.
## [V75 regime analysis — no entry-regime filter qualifies; stand-aside rejected, walkforward warning stands] - 2026-09-14

### Finding — the 2026 deficit cannot be filtered away with the standard regime states
- The open question after v2.20 was whether the losing 2026 segment could be dodged by a stand-aside filter: measure regime state at each of the 75 real long-only entries (H1 ATR(14) z-score, H1 ADX(14), 6h EMA slope, month realized vol from M30) and correlate against PnL at both granularities, with the repo's walkforward convention (fit on 2024.01–2025.08, evaluate 2025.09–2026.09 out-of-sample).
- **Nothing correlates.** Per-trade — the granularity at which an EA filter actually fires — the best is |ρ| = 0.05 (adx), atr_z +0.03, slope −0.02; permutation p ≥ 0.67, i.e. pure noise. Month-level (n=29) tops out at atr_z ρ +0.22 (p≈0.25) across eight scanned feature-direction cells — unremarkable after the scan.
- **The train-fit filters fail their own out-of-sample.** The best full-window month rule (atr_z ≥ 0.84, kept +786.61) works only by dropping the train segment's single losing month and never fires OOS (test kept −236.04 = the unfiltered baseline). The per-trade rules are worse than useless OOS: atr_z ≤ 1.19 keeps −333.84 while dropping +97.80; adx ≤ 36.99 keeps −330.58 while dropping +94.54. The nominal "best OOS separation" (slope ≤ 0.53) drops zero trades — the baseline restated, not a filter.
- **The granularities disagree in sign** on the one feature with any signal (month-level keeps high atr_z; the per-trade train fit drops high atr_z). A real effect does not flip sign under re-aggregation; noise does.
- Decision: **no stand-aside input is added to the engine; v2.20 geometry stands unchanged.** The 2026 deficit is the already-recorded walkforward inversion (every config flips negative on the test window) showing up feature-wise — edge decay, not a filterable regime state. Limits recorded: 75 entries / 22 test trades = low power; the verdict closes these four features, not the space — reopening requires a new pre-registered feature + fresh window per the ledger discipline.
- Evidence: `artifacts/v75_macro_engine_tester/regime_analysis_20260914.txt` (reproduced bit-identically on re-run); generator `scripts/v75_regime_analysis.py`; ledger row #11 in `docs/OPERATING_SUMMARY.md`.

## [V75MacroEngine v2.20 — timeout re-derived: 3h → 2h on buy-side MFE/MAE evidence] - 2026-09-14

### Changed — the hard timeout is now 2 hours; SL/TP geometry untouched
- The 71-day path-forensics claim was re-measured on the full window with deep terminal history (M30 44,353 bars + H1 22,177 bars, 2024.03–2026.09): the published p75=0.64R MFE was **sell-dragged** — the 75 real long-only entries measure **p50 0.71R / p75 1.14R / max 3.31R**, with 32% reaching 1R. But MAE is the binding side: 29% of buys touch −1R eventually, and every extra hold-hour converts timeouts into SL hits. The what-if grid over TP×hold shows **2h beats 3h at every TP level** (at spec TP: offline +7.84 → +10.14R, PF 1.51 → 1.99), while 4–8h holds collapse. TP is a plateau across 0.8–2.0R at 2h — the liquidation time is the lever, not the target — so the TP stays at spec 4× ATR and only `TIMEOUT_SECONDS` changes.
- **Validation (real ticks):** 71-day gate reproduces the 8-buy entry stream exactly (zero sells, all bar-open entries, 8/8 reconciliations — exit paths differ by design). 31-month pass: **76 fills, +867.90 (PF 1.794, R-sum +8.38, final balance 10,866.84)** vs v2.10's +730.66/PF 1.529 — SL hits 4→1, negative months 10→7, 2026 −236→−120, one extra fill from the freed slot. 2026 remains net negative: regime risk stands.
- The validation driver is now build-generic (`v210_longonly_validate.py [prefix]`, e.g. `v220`): entry-stream invariants stay hard for every build, PnL pins apply only where the exit paths are pinned. The runner's identity hook now also parses the v2.x init line (`V75 Macro Engine vN.NN initialized`), so every pass records what actually ran.
- Evidence: `artifacts/v75_macro_engine_tester/v220_exit_rederivation_evidence_20260914.txt` + `exit_rederivation_20260914.txt`; script `scripts/v75_exit_rederivation.py`; reports `V75_regress_v220_71d.htm` / `V75_regress_v220_31m.htm`.

## [V75MacroEngine v2.10 — LONG-ONLY: the sell leg is cut on 31-month evidence] - 2026-09-14

### Changed — aligned-DOWN regimes now stand down; the SELL springboard is removed
- Five independent 31-month real-tick runs (spec exits + four TP/trail variants) all show the same side split: **buys +748/+704/+693/+252/+478, sells −1,081/−810/−1,024/−913/−551** — the sell arm loses under every exit geometry, worsening by year (+69 / −481 / −669). Entry-drift stats corroborate: the buy signal lifts the 1-bar directional hit rate 50.7%→62.7%; the sell signal is indistinguishable from base (54.3% vs 51.9%, negative mean; between-arm difference p≈0.016). The aligned_down MFE data adds the mechanism: mean peak 0.39R, max 1.81R vs the 2.0R target — the sell arm's 1:2 never materializes (0 TP hits in 167 spec trades).
- v2.10 makes the **minimal surgical change**: aligned-DOWN regimes stand down in `OnTick` before the springboard; the sell branch, `bbUpper` read, `ENTRY_SELL` enum member and `InpRSISellLevel` input are deleted. Constants, 3h timeout, 1% sizing, single-position cap and HUD are untouched. Init print is now `V75 Macro Engine v2.10 initialized (LONG-ONLY)`.
- **Validation (real ticks, same rig):** PASS 1, the 71-day regression window, reproduces the v2.00 buy arm **exactly** — 8 fills, zero sells, R sequence [−0.58, 0.32, 0.21, 0.27, −0.39, −0.06, 0.13, −0.38] identical, PnL −45.77 vs −45.92 (one 15-cent tick-fill difference at a timeout close) — proving the removed sell arm was path-isolated. PASS 2, the full 31-month window 2024.03.01–2026.09.10: **75 fills, +730.66 (final balance 10,728.71), PF 1.529, R-sum +7.15**, 4 SL / 0 TP / 71 timeouts — within 2.3% of the tpA2 buy-arm reference (+747.55 / PF 1.56), the gap being buy flow the sells had been blocking while holding the single-position slot. Per-year: 2024 +639 / 2025 +328 / 2026 −236; 10 of 29 months negative.
- Recorded honestly: 2026 remains net negative even long-only — the walkforward warning (train 2024.01–2025.08 → test 2025.09–2026.09 flips every config negative) stands, so the long-only fix removes the structural bleed but the current regime is hostile to the pullback-buy style. The exit geometry is deliberately left untouched (spec 2×/4× ATR + 3h timeout); the MFE evidence says the 4×ATR TP is unreachable and a re-derived exit (~0.8R targets) is the next strategy decision, but it is a change with its own validation burden, not part of this fix.
- Rig note: the live terminal (`MitemshubMT5_B`) silently absorbs a `/config:` tester launch (single-instance MT5) — a v210_71d pass then times out with no agent activity. All tester runs in this repo require the terminal closed; the two v2.10 passes were run with it closed and it was relaunched afterwards (0 open positions at close).
- Evidence: `artifacts/v75_macro_engine_tester/v210_longonly_evidence_20260914.txt`; reports `V75_regress_v210_71d.htm` / `V75_regress_v210_31m.htm`; forensics `scripts/v75_exit_geometry_study.py`; driver `scripts/v210_longonly_validate.py`.

## [V28 scorecard/gate state dollars and R as a matched pair, and the 32-record matrix is re-reported] - 2026-09-13

### Change — both R measures travel with every record, and a verdict quotes the pair
- The scorecard and promotion gate now report `cumulative_r` (sum of per-trade ratios — what `OnTester()` scores) beside `money_implied_r` (net P&L / mean risk — the figure that multiplies back to dollars), with `mean_risk`, `risk_source` and `expectancy_r_money`. A refusal reason now names the money and the R that correspond to each other, e.g. `out-of-sample money-implied R is not positive (-0.2021 = -20.17 USD / mean risk 99.79)`. A record with no denominator is refused outright and the reason names the fix (`backfill`) rather than silently substituting the ratio-sum figure.
- The 32 matrix records predate the EA's `R_RECONCILE` line, so `cmd_backfill` now resolves each one's mean denominator from **its own journal segment** (never another pass's): the pass's `R_RECONCILE` line when present, else reconstructed from its OPEN geometry via the EA's own formula — `(stop_distance / tick_size) * CalibratedTickValue() * volume`, which on V75 reduces to `|entry - SL| * volume` because the calibrated value is the geometric `tick_size*contract_size`.
- **Reconstruction validated against a pass carrying both sources** (262 closes): reconstructed mean 96.48, min 89.24, max 103.59 vs the EA's own 96.86 / 89.24 / 104.04 — 0.4% on the mean, identical minimum; the residual is that the EA's POSITION source uses the actual fill while the OPEN print shows the requested price. Backfill result: **32/32 records carry `mean_risk`** (all `open_lines`), range 80.10–106.14, **0 identity violations** (`test_pnl == money_implied_r * mean_risk`) and **0 sign disagreements** between money-implied R and P&L.
- Re-reported matrix: **all eight hypotheses remain REFUSED, and no verdict changes** — the numbers that decide them (P&L, PF, trade counts, exit splits) were already verified. What is new is that every refusal now also states a consistent dollar/R pair, so the ratio-sum R cannot be mistaken for something that converts back to money. `REVERSE_DIRECTION` is where the measures diverge most (ratio −1.192 vs money −1.501); `REVERSE_BOTH` stays positive in is/wf and negative in the untouched oos (−0.185 / −0.202), exactly as the 33-month run showed.
- One harness detail fixed while doing this: storing `mean_risk` rounded to 2dp but computing the implied R from the unrounded value left `V28-0016` violating the identity by 0.0012; the implied R is now derived from the stored denominator.
- Evidence: `artifacts/v28_research/r_measures_surfaced_20260913.txt`; refreshed exports `registry.csv` / `registry.json`; pre-backfill registry archived as `registry_pre_reconcile.jsonl`. 31 tests pass in `tests/test_v28_research.py` (5 new pins), 70 passed / 1 skipped across the V28/V75 suites. Still open and unchanged: the 16 defect-era registry records in `registry_backfilled_contaminated_20260913.jsonl` carry invalid cumulative R and must not be read for R.

## [V28 MFE study — why every exit is a timeout, and what a different exit would have captured] - 2026-09-13

### Finding — the take-profit is not being beaten by the timeout, it is unreachable
- The question could not be answered from the existing logs: a trade that times out reports where it finished, never how far in front it ever was. Added tick-true excursion tracking to the EA — `TrackPeakExcursion()` samples `POSITION_PROFIT / g_risk_money` **every tick ahead of the guardian**, `g_peak_r` is folded with realised R at the close and printed as `peak_r` on every CLOSE line, and `MFE_SUMMARY` prints how many trades cleared each level of {0.25…2.00}R. All eight modes re-run on M30 2024.01.01–2026.09.10 (100% real ticks, 42.4M ticks), **16,449 trades**; every mode's captured close count matches its report's Total Trades (8/8).
- **2 of 16,449 trades (0.012%) ever reached 2.00R; the largest favourable excursion anywhere was 2.005R.** The spec's TP is 4×ATR against a 2×ATR stop, i.e. 2.0R. The 92% timeout share is not the timeout winning a race — the target is at a price the instrument simply does not visit. The median trade peaks at 0.35R: 70% of the way to the stop, 18% of the way to the target.
- **The MFE distribution is nearly identical in every mode**: mean 0.391–0.465R, p90 0.785–1.035R, in all eight, across entry rules that disagree on direction, trigger and filter. In R units the favourable excursion over a 3-hour hold is a property of the instrument's volatility over that window, not of the signal — if the entries carried directional information these distributions would have to differ.
- **Exit geometry is not the lever.** Pricing a TP at kR (exact here: a trade whose MFE reached k must have reached it while open, so the TP fires first) leaves six of eight modes negative at their best level; `ORIGINAL` is best left alone at 2.0R; the two positive modes gain at most +34% (REVERSE_BOTH +87.94 → +117.58, PF 1.02 → 1.03) — inside noise and far below the PF 1.30 gate. The tight targets that help the losing modes (0.25–0.50R) are exactly the ones that destroy the modest winners.
- Limits recorded: the counterfactual holds the entry sequence and sizing fixed (a tighter TP frees the one-position slot earlier, which needs a re-run to price); fills are assumed at the level with no slippage; MAE is not tracked, so tighter *stops* cannot be priced from this corpus.
- Evidence: `artifacts/v28_research/mfe_exit_geometry_20260913.txt`. 75 offline tests pass across the V28/V75 suites (two new pins: peak tracked before the guardian and reported per close, and the excursion state reset per pass).

## [V28 REVERSE_BOTH on 33 months — the last open thread closes negative] - 2026-09-13

### Result — the 3-of-4-window profitability does not survive a bigger sample
- `REVERSE_BOTH` was the only matrix configuration profitable in 3 of 4 windows with trustworthy R (+1.895 / +6.604 / +2.516 / −0.185) but under the 30-trade gate in all of them (18 / 29 / 27 / 12). Re-testing it on those same windows would be circular, so it was run on the **full cached range**: M30 2024.01.01–2026.09.10, **100% real ticks**, 47,184 bars, 42,442,757 ticks, 181 trades (6× the gate).
- **181 trades, net +87.94, PF 1.02, expectancy +0.0065R, cumulative R +1.1711, balance drawdown 1,364.04 (13.09% ≈ 14.1R), win rate 49.2%, 0 TP / 15 SL exits (91.7% timeout).** That is +0.88% total return over 33 months against a 13% drawdown — and it fails profit factor, expectancy and drawdown while passing the sample gate. First V28 candidate to clear the sample gate and still be refused.
- The four-window impression was a property of the window. Sliced at the selection boundary: **selection era (2025.09.15+, the 12 months that picked it) 68 trades, +858.62, PF 1.985; virgin era (<2025.09.15, 20.5 months) 113 trades, −760.99, PF 0.754.** The two eras cancel (matching the +97.63 aggregate). Contiguous 90-day blocks are 6/11 positive, and the break is a regime property rather than an artefact of the split: the last four blocks are all positive (2025.09.28→2026.09.03) while the seven before are 2/7 — the same signature as the V75MacroEngine walk-forward inversion.
- Caveat recorded: the virgin era is virgin only with respect to *this mode's* selection; other V28 modes and the V75MacroEngine research have used 2024–2025 data.
- Accounting cross-check on the new log, over 181 trades and 33 months: `ratio_sum_r=+1.1711` equals the report's own `OnTester` field, `mean_risk=96.45` sits in the same 89–104 band as every other V28 run, `gap=+0.2593` inside `dispersion_bound=6.2201` → `consistent=true`.
- `tests/v75_tester_runner.py`'s `parse_report` now also returns the deal table with simulated timestamps (the journal is wall-clock only), so any sub-period can be sliced without re-running the tester. Evidence: `artifacts/v28_research/reverseboth_long_sample_20260913.txt` + `reverseboth_long.json`.

## [MitemshubAI v28 — R denominator reconciled: the gap was arithmetic, not a defect] - 2026-09-13

### Finding — the per-trade denominator is correct; "implied risk" was the wrong statistic
- The open question was that is90 `REVERSE_DIRECTION` showed net −144.81 against cumulative R −1.192, implying ~$122 of risk per trade where the close audit showed $89–104 (mean $96.86). Auditing **all 262 closes**: the per-row identity holds on **0/262 violations**, `sum(pnl_i/risk_i)` recomputes to **−1.1922** against the EA's own `cum_R` −1.1920 and the report's `OnTester` −1.1920, and the denominators are tight (min 89.24, median 97.44, max 104.04; all `ENTRY`/`POSITION`, zero fallbacks).
- **The gap is the arithmetic of summing ratios.** `sum(pnl_i/risk_i) == sum(pnl)/mean_risk` only when every denominator is identical. Measured: ratio-sum **−1.1922** vs money-implied **−1.4951**, difference **+0.3029**, `corr(1/risk, pnl) = +0.053` — a ±8% risk spread from equity drift and lot rounding accounts for it. Nothing in `CommitTradeRisk` or `CaptureManagedPosition` needed changing.
- Added `LogRAccounting()`, called from `OnTester()`: it accumulates `sum(risk)`, `sum(|pnl|)`, `min/max(risk)` per close (all reset in `ResetTestMetrics`, so nothing leaks between passes) and emits `R_RECONCILE … ratio_sum_r money_implied_r gap dispersion_bound consistent`. `consistent` compares the gap against the exact bound `sum|pnl_i| · max_dev(1/risk)`, so a genuinely wrong denominator is reported as a WARNING rather than hiding behind the benign effect. `ratio_sum_r` is for comparing candidates; `money_implied_r` is for converting R back to dollars.
- Measured line: `trades=262 mean_risk=96.86 risk_min=89.24 risk_max=104.04 ratio_sum_r=-1.1920 money_implied_r=-1.4951 gap=+0.3030 dispersion_bound=9.7843 consistent=true net_pnl=-144.81 implied_risk_by_ratiosum=121.48`.

### Fixed — the research driver recorded the wrong P&L
- `run_experiment` set `test_pnl` to the report's **deal-table sum**, not the run's net profit — one-directionally optimistic by ~$0.05/trade (up to $60 on a 1,200-trade run), wrong on 23 of 32 records (e.g. −129.24 recorded against −144.81 actual). That bias fed the promotion gate's out-of-sample P&L.
- New `choose_whole_run_pnl()` takes the EA's own counter → the report's `Total Net Profit` → the deals sum, and records the choice in a new `pnl_source` field. Verified end-to-end on a fresh pass: `test_pnl −144.81`, `pnl_source ea_journal`, `cumulative_r −1.192`.
- Evidence: `artifacts/v28_research/r_denominator_reconciliation_20260913.txt`. 24 offline tests pass (three new pins: reconciliation log + dispersion bound, accumulator reset, P&L source order).

## [V28 matrix re-run on the fixed binary — which findings survive trustworthy R] - 2026-09-13

### Result — the corrupted R made the program look ~2.2x worse than it is, and killed one false positive
- Re-ran all 32 cells (4 windows × 8 modes, unchanged windows, 100% real ticks) on the fixed `MitemshubAI_v28` build. Sign agreement between cumulative R and net P&L goes **10/32 → 1/32**, and the one residual is a flat run (is180 `REVERSE_DIRECTION`: net −25.73, R +0.246), not a defect.
- The era's R was not merely noisy, it was **magnitude-inflated and sometimes sign-flipped**: is180 `REVERSE_DIRECTION` +63.484 → **+0.246** (258x), oos `MACRO_ONLY` −81.669 → −6.514 (12.5x), and 6 records flipped sign outright (e.g. is180 `TRIGGER_ONLY` net −2140.63, era R +51.387 → −24.061). Aggregate R across the 32 records: **−401.5 → −184.4**.
- Trading is unchanged: P&L, PF and trade counts are identical on all 32, and the 22 records whose era R already agreed are unchanged to 3 decimals. Only the accounting moved.
- **`REVERSE_DIRECTION` is a false positive that the corrupted R was carrying.** Its era R was positive in all four windows (+29.5/+63.5/+20.8/+18.4) while its money was negative (−144.81/−25.73/−1667.12/−916.28) — that discrepancy *was* the defect. Real R: −1.19/+0.25/−17.97/−9.35.
- Survivors: `ORIGINAL` is negative in all four windows (PF 0.40/0.17/0.53/0.86); only 8 of 32 runs are profitable; the 4×ATR target is unreachable at matrix scale — **7,597 trades → 4 TP, 602 SL, 6,991 timeout exits (92%)**; the sell-side asymmetry holds (`SHORT_ONLY` worse than `LONG_ONLY` in every window, bootstrap profitable share 0.00). All eight promotion verdicts remain **REFUSED**, now for legitimate reasons (oos P&L/R not positive, walk-forward sign flips, bootstrap p05 far below zero) instead of corrupted R.
- The one open thread: `REVERSE_BOTH` is the only configuration positive in 3 of 4 windows with trustworthy R (+1.895/+6.604/+2.516/−0.185) — but it is below the 30-trade gate in every window (18/29/27/12 trades) and negative out-of-sample. A hypothesis for a much larger sample, not a result.

### Fixed — two harness defects that corrupted the re-run itself
- **Reused run tags broke every research-line capture.** The tag was `v28_<window>_<hypothesis>` — deterministic, so a re-run reuses an earlier pass's tag, and `journal_has_tag()` searched the whole journal, matched the older line and returned immediately; the delta parse then found nothing and all 32 passes silently fell back to the report field. Tags now carry pid + timestamp (one tag = one pass) and the wait is offset-scoped.
- **`cmd_backfill` imported superseded numbers.** It used `re.search` and took the *oldest* matching line, replacing post-fix whole-run R with defect-era values on **24 of 32 records**; its docstring claimed the tag was unique per pass. It now takes the newest match. Both rules are pinned by tests, the 32 records were rebuilt from their own reports (OnTester R, Total Net Profit, deal-reason exit split), and the contaminated intermediate is archived for audit.
- Evidence: `artifacts/v28_research/matrix_rerun_postfix_20260913.txt`, `registry.jsonl` (post-fix) vs `registry_defect_era_full_20260913.jsonl` (defect era) vs `registry_backfilled_contaminated_20260913.jsonl`.

## [MitemshubAI v28 — research framework, and a fatal v27 execution defect] - 2026-09-13

### Fixed — v27 (and therefore every prior backtest) never actually held a position
- `ConfigureFilledPosition()` treated a rejected `PositionModify` as fatal and market-closed the position. On Deriv V75 the entry order **already carries the exact ATR stops**, so the corrective modify asks for values identical to the held ones and the server answers `10016 invalid stops`. The EA then destroyed a perfectly protected trade.
- Evidence: **6,390** `EXACT ATR PROTECTION FAILED: retcode=10016 invalid stops; closing` journal lines, and the instrumented trace proving the values are identical — `want_sl=35540.25 want_tp=38239.32 held_sl=35540.25 held_tp=38239.32 stops_level=10770`, i.e. 89,969 points of stop distance against a 10,770-point broker minimum (so it was never a distance problem).
- Effect on results: every v27 backtest measured *open → close at the opposite side of the spread*. Mode 0 on 2026.06.12–2026.09.10: **27 fills, 100% losers, PF 0.00, `OnTester` R −0.344**, each trade exiting in the same second it opened. After the fix the same config holds its trades: fill count falls (the one-position gate is now genuinely occupied), exits become real lifecycle events, and P&L is finally a measurement of the strategy.
- Fix: a rejected modify now verifies what the broker actually holds and keeps an already-protected position; only a genuinely **unprotected** position is closed, so v27's safety intent is preserved. The full geometry (want/held/levels/point/bid/ask) is logged on any rejection — a 10016 is no longer unattributable.
- New input `InpLegacyV27ModifyClose` (default `false`) reproduces v27 here byte-for-byte, so the original behaviour stays auditable; `v28_research.py equivalence` proves `v27 ≡ v28 mode 0` with that switch on.

### Added — V28 as a research framework (no self-modifying logic)
- Eight deterministic strategy modes (original / reverse-direction / reverse-trigger / reverse-both / long-only / short-only / macro-only / trigger-only), each a hypothesis rather than a mutation. The EA never rewrites its own logic during live trading; `InpLiveExecution=false` remains the default safety setting.
- Tunable geometry (`InpRiskFraction`, `InpStopATRMultiplier`, `InpTargetATRMultiplier`, `InpMaxHoldMinutes`) with **bounded validation** — out-of-range values fail `OnInit` loudly instead of letting an optimizer trade absurd stop geometry, and the recommended (narrower) search ranges are documented.
- **Whole-run tester metrics** (`g_test_*`) reset once per pass in `OnInit` and never at midnight; `OnTester()` returns whole-run cumulative R. The tester now also skips terminal global variables, so one pass cannot inherit another's session accounting.
- `RESEARCH_RESULT` is a single machine-readable journal line carrying the candidate identity and the exit-reason split (`sl_exits`/`tp_exits`/`timeout_exits`) alongside trades, wins, losses, win rate, P&L and R.
- `scripts/v28_research.py`: append-only experiment registry with unique ids, scorecard (net P&L, cumulative R, PF, drawdown, expectancy, win rate, avg win/loss, longest losing streak, trade count, recovery factor, OOS P&L, walk-forward consistency), robustness probes (fixed-seed trade bootstrap, drop-best-1/3, order-shuffle drawdown) and a **promotion gate that refuses any candidate without is+wf+oos evidence, ≥30 trades per role and a robustness pass**. Windows are reserved up front; the OOS block is never used for selection.
- `mql5/MITEMSHUB_AI/V28_RESEARCH_PROTOCOL.md` — tester setup, mode/matrix definition, walk-forward protocol, optimization ranges and the interpretation rules.
- `tests/v28_research.py` + `tests/test_v28_research.py` (25 offline tests pin identity, input completeness, window roles, bootstrap determinism and every promotion refusal).
- v27 (`mql5/MITEMSHUB_AI/MitemshubAI.mq5`) is untouched and still the live EA; v28 ships beside it as `MitemshubAI_v28.mq5`. Both compile **0 errors, 0 warnings** in all five terminal trees.

### Fixed — whole-run R accounting: 77 of 262 closes were silently dropped, flipping the sign of cumulative R
- The timeout guardian and an M30 entry can fire on the **same tick** (an entry opens on a bar open and the 180-minute hold is exactly six M30 bars, so a timeout expiry *always* lands on a bar open). `CaptureManagedPosition()` then overwrote the tracked trade's identity with the new position, so the closed trade was never booked — no `CLOSE` line, and no `POSITION GONE` line either.
- Measured in `REVERSE_DIRECTION` on M30 2026.06.12–2026.09.10 (100% real ticks): **262 opens, 185 booked closes**, 242 distinct tickets liquidated, **77 liquidated but never booked**, and exactly 77 opens sharing a journal second with a liquidation request. The report's net was **−144.81** while the EA's counters held **+2826.52 / +29.4700 R** — opposite signs, and `OnTester()` returned that corrupted `+29.47`. This is the mechanism behind the "10 of 32 records with R and P&L of opposite sign" finding.
- Fix: adoption now has one owner. `CaptureManagedPosition()` books a superseded trade (`RecoverClosedPosition()`) *before* adopting the new position, and clears the stale identity rather than carrying a stale denominator forward; `PollManagedPosition()`'s changed-identifier branch routes through the same path. The R denominator likewise has one writer (`CommitTradeRisk`), bound to the position id and plausibility-bounded, and **every close now logs `risk=` and `risk_src=` plus running `cum_pnl`/`cum_R`**.
- Verified on the same window with the same 262 trades: **262 opens / 262 booked closes, 0 unbooked liquidations, 0 silent clears**, exits TIMEOUT 242 / SL 20 / TP 0, EA `test_pnl` **−144.81 (== the report's net profit)** and `test_R` **−1.1920 (== the report's own `OnTester result` −1.192019807083707)** — signs agree. `ORIGINAL` on the same window is unchanged (18 trades, −229.41, R −2.3075), so the change is accounting-only.
- Denominator audit: `risk_src` 203/203 `ENTRY`, risk **$89.79–$104.04** (was $4.39–$79.46), and **0/203** per-trade `sign(pnl) != sign(R)`. Three source-level regression pins added to `tests/test_v28_research.py` (19 tests pass).
- Caveat: records produced by pre-fix builds still have unreliable cumulative R — only their P&L / PF / exit counts remain valid, and the registry should be re-run before any promotion decision reads R. Evidence: `artifacts/v28_research/r_accounting_fix_20260913.txt`.

## [V75 research — tick cache 31→35 months; two-sample walk-forward protocol] - 2026-09-13

### Added — the two-sample (walk-forward) protocol, so selection can be separated from validation
- `tests/v75_walkforward.py`: splits the cached months into TRAIN (selection) and TEST (untouched validation), runs every config on both sides, and reports the transfer — per-config train/test expectancy + PF, the train-winner's rank on each side, Spearman(train E, test E), and the 30-trade gate per segment. Selection is train expectancy only (PF breaks ties). Presets: `legacy` (2024.03-05 / 2024.06-08) and `powered` (2024.01-2025.08 / 2025.09-2026.09). Cells are banked to `walkforward_<name>.json` as they land and a relaunch **resumes**.
- `tests/v75_tester_runner.py` gains `report_inputs()`, so the "what did this pass actually run with" check (the input-cache gotcha) has one owner. `tests/test_v75_walkforward_protocol.py` (10 offline tests) pins the preset geometry, the selection rule, the sample gate, the uneven-side/resume fix, and explicit-input completeness.
- Fixed during the run: `persist()` summarised as soon as *either* segment had any cell, raising `KeyError` on segment-specific name sets; the summary now ranks only configs present in both, and the crash path is a regression test.

### Changed — tick cache 31 → 35 months, and the earlier "floor = 2024.03" was wrong
- Three real-tick probes: **2024.01-2024.02 runs complete** (2,832 M30 bars, 2,547,536 ticks, 12 fills) → `202401`/`202402` added; **2023 Q4 is partial** (384 bars over 3 months, 60% history quality, 1 fill) → `202311`/`202312` added but flagged unusable for research. Pre-Oct-2023 still resolves to no symbol. The usable floor is therefore **2024.01**, not 2024.03.

### Result — an adequately powered split shows selection *anti*-transfers
- **Powered** (train 111 fills / test 70 fills, gate met): train is positive for every config (E +0.030…+0.054R, PF 1.17…1.27); test is negative for every config (E −0.091…−0.173R, PF 0.42…0.60). The train-selected winner (`tp090`) is **test rank 5/5**, Spearman **−0.9**.
- **Legacy** (18/14 fills, gate NOT met): same inversion, `tp090` again 5/5, Spearman −0.7.
- Tripling the sample strengthened the inversion rather than dissolving it, so the P&L sign is a property of the time segment, not of the exit geometry. Bounds every earlier single-window "best cell" claim in this repo, and matches the entry-attribution finding (the loss lives in the regime and on the sell side). Caveat recorded: the powered TEST block overlaps windows used in earlier A/Bs, so a virgin holdout should be reserved before the next selection round.
- Evidence: `artifacts/v75_macro_engine_tester/cache_extension_and_walkforward_20260913.txt`, `walkforward_legacy.json`, `walkforward_powered.json`, both probe reports.

## [V75MacroEngine v1.29 — Pass-C springboard grid: no cell is robust] - 2026-09-12

### Changed — v1.29: the springboard thresholds are now inputs
- `InpRSIBuyLevel` (35.0) and `InpRSISellLevel` (65.0) replace the hardcoded `35.0`/`65.0` literals, with an init-time `Springboard:` identity print. Compiled defaults are the spec values, so out-of-the-box behavior is unchanged; a rig test pins both defaults and asserts the triggers consume the inputs. This is what made the springboard griddable at all.

### Pass-C grid — RSI {30,35,40} × BB {2.0,2.3,2.6}, 6-month real-tick window
- All 9 cells net negative; **TP hits = 0 everywhere**. Expectancy spans only **−0.207R to −0.292R** — the per-trade loss rate is essentially threshold-invariant.
- **The RSI axis is degenerate at 30 and 35**: those rows are byte-identical in every BB column (same PnL to the cent), the empirical confirmation of the inert-RSI-leg finding. Only RSI 40 activates the leg — so the grid is effectively 2-valued on that axis, not 3.
- Wider BB bands do not help: at RSI 30/35, 2.0 → 2.6 cuts fills 29 → 5 and PF 0.17 → 0.00 (zero winners).
- **The 6-month "best" cell (rsi40_bb2.6, PF 0.36, n=15) fails out-of-sample**: on the full window it is PF 0.80 / E −0.054R, *worse* than the spec default's PF 0.92 / E −0.019R. Its edge was small-sample noise. The non-monotonic RSI-40 PF sequence (0.23/0.17/0.36) is the same noise.
- Structural power limit: BB 2.6 yields only 5–15 fills per 6 months against the 30-trade gate. Pre-computed from the audit corpus (band = MA ± k·σ), predicted fill counts matched observed closely (predicted 29/16/5 vs actual 29/19/5 at RSI 30; 34/22/13 vs 34/25/15 at RSI 40), so future grids can be pre-screened rather than burned on the tester.
- The spec reference cell reproduced the independent isolated baseline exactly (167/−333.31/PF 0.92/152 timeouts/0 TP), validating the grid driver. Evidence: `artifacts/v75_macro_engine_tester/passc_springboard_grid_20260912.txt` + per-cell JSON.

## [V75MacroEngine v1.28 — entry attribution: the RSI leg never fires, the sell side bleeds] - 2026-09-12

### Added — v1.28: springboard branch + entry context reach the audit CSV
- The branch was computed (`bbTrigger`/`rsiTrigger`) then **discarded**, so "which leg fired" was unrecoverable; `trade_closed` rows carried no entry context. v1.28 encodes the branch in the existing `signal` token (`buy_bb` / `buy_rsi` / `buy_bb_rsi` / `sell_*`) and writes the entry regime + branch onto `trade_closed` rows — **no new columns**. Trading unchanged: the isolated run reproduces the baseline exactly (167 fills, −333.31, PF 0.920, R-sum −3.16) and the tier-3 gate is 10/10 green. Two rig invariants added.

### Finding — half the spec's entry logic has never operated
- Over **32,553 aligned bars**, entries came from: `bb_only` 166, `both` 1, **`rsi_only` 0**. RSI contributed exactly one entry in 19 months (the 6-month pooled corpus agrees: 0 of 6,621).
- It is structural, not rare: the alignment filter mechanically bounds M30 RSI away from the thresholds — `aligned_up` min RSI **34.06** vs the required ≤35 (1 bar in 15,166); `aligned_down` max RSI **64.51** vs ≥65 (0 bars in 17,387). Thresholds sit ~1.0–1.5 points outside the achievable range. The engine is in practice a **single-rule** system (EMA alignment + Bollinger pierce).

### Finding — all the negative expectancy is on the sell side
- Full window, isolated run: `aligned_up` n=75 **sumR +7.18** (mean +0.096R, win 60.0%, meanPeak 0.50R) vs `aligned_down` n=92 **sumR −10.34** (mean −0.112R, win 43.5%, meanPeak 0.39R). Neither arm alone is significant (t=+1.52 / −1.93), but the **difference** is marginally significant (mean diff +0.208R, t≈+2.4, ~p=0.016).
- Post-signal drift (close-to-close, aligned M30 bars, points): the **buy** signal lifts the one-bar directional hit rate from 50.7% (base) to **62.7%** with median favorable move +6 → **+449 points** (mean +627); the **sell** signal is indistinguishable from base (54.3% vs 51.9%) with a negative mean. The buy edge is real at entry but **given back by the exit** (~0.57R one-bar drift → +0.096R realized), consistent with the TP study's p75 = 0.64R MFE.
- Hit rate ≈ **0.5% of aligned bars** (74/15,166 up, 92/17,387 down) — roughly one entry per 200 aligned bars, which is why the 30-trade gate needs months to clear.
- The 6-month window is specifically a **short-side disaster**: its subset shows `aligned_down` n=13, meanR −0.532, **win rate 7.7%** — explaining why its headline (−389.05, PF 0.35) is far worse than the full window (−73.43, PF 0.97).
- Evidence: `artifacts/v75_macro_engine_tester/entry_attribution_20260912.txt`.

## [V75MacroEngine — tick-cache floor found; 6h+trail revalidated on v1.27] - 2026-09-12

### Finding — the V75 tick cache cannot be extended: 2024.03 is the broker's floor
- Probes at 2023.09, 2022.09 and 2021.09 each produced a report with **no symbol resolved (`Period M0 1970.01.01–1970.01.01`, Bars 0, Ticks 0)** and downloaded **zero** tick months, while Mar 2024 (5 fills) and Sep 2024 (9 fills) probes have real data. The local cache (`202403.tkc` → `202609.tkc`, 31 months) already covers **everything the broker serves** — the window cannot be grown by adding months.

### Revalidated — canonical 6h+trail on v1.27, full 31-month window
- Config: `InpExitManager=TRAIL`, 0.2R trigger, 1.0× H1 ATR trail, spec 4×ATR TP, 6h timeout; complete explicit `[TesterInputs]`; $10k; real ticks. Identity print: `Breakeven @ 0.20R + ATR trail 1.00x`.
- Window `2024.03.01–2026.09.10`, **100% real ticks, 44,304 bars, 39,852,025 ticks**: **173 fills, −73.43, PF 0.974, R-sum −0.53 (E −0.003R/trade)**, 142 SL / 2 TP / 29 timeout exits, 4,321 SL ratchets with **0 modify failures**, all entries on M30 bar opens, final balance 9,915.29, balance DD 1,172.09 (10.68% ≈ 11.7R), equity DD 1,259.54 (11.42% ≈ 12.6R).
- **Byte-identical to the archived v1.25/v1.26 canonical on the same window** — an independent confirmation that the v1.27 always-on peak tracking is trading-inert on the shipping config.
- Gate table: sample (173 vs ≥30) ✓ · TIME-exit share (16.8% vs ≤40%) ✓ · max DD (11.7R balance vs ≤12R) ✓ marginal · **PF (0.974 vs ≥1.30) ✗ · expectancy (−0.003R vs ≥+0.15R) ✗** → back to research, do not promote. Note the DD gate is the one metric that flips on balance-vs-equity basis (11.7R vs 12.6R).
- Evidence: `artifacts/v75_macro_engine_tester/cache_floor_and_6h_trail_reval_20260912.txt` + `V75_regress_reval6htrail.htm`.

## [V75MacroEngine v1.27 — data-driven TP derivation, contamination corrected] - 2026-09-12

### Fixed — the `peak_r` audit column was dead in the spec-default config
- `g_exitPeakR` was only updated inside `ManageOpenProfit()`, which returns immediately in the default `EXIT_MANAGER_NONE` mode — so every spec-default trade wrote `peak_r = 0.00` to the CSV. The documented pipeline column carried no information exactly when the shipping default was running.
- v1.27 gives it **one owner**: `TrackPeakExcursion()`, called from `OnTick` on every tick ahead of the exit manager and independent of the exit-manager mode. Trading behavior is provably unchanged — the pre-fix and post-fix 4×ATR baseline passes match on every metric (167 fills, −333.31, PF 0.920, 15 SL, 0 TP, 152 timeouts, R-sum −3.16) and the tier-3 regression gate is 10/10 green on v1.27. New rig invariant `test_peak_tracking_is_mode_independent` fails CI if the peak write moves back behind the mode gate.

### Finding — the earlier TP derivation was built on a contaminated sample
- The 2026-09-11 take-profit derivation used 60 rows labelled "uncensored 6m-OFF MFE" that in fact **pooled several runs sharing one `run_id`**, including runs whose TP already capped the peak (mixed row schemas, out-of-order timestamps), and was dominated by the dead column above. Its 0.03R median — and the 0.30R target derived from it — were artifacts.
- Clean uncensored distribution (n=167, 31 months, 3h hold, no early exit): **p25 0.16R · p50 0.38R · p75 0.64R · p90 0.88R · p95 1.06R · max 1.81R**. Max observed excursion (1.81R) is below the spec's 4×ATR target (2.0R) — that target is literally unreachable on this data, which explains 0 TP hits across every previous run.

### A/B — identical 31-month window and exits; only the TP changed
| TP target | Fills | Net PnL | PF | TP hits | Timeouts | R-sum |
|---|---|---|---|---|---|---|
| 4×ATR (spec = 2.0R) | 167 | −333.31 | 0.920 | 0 | 152 | −3.16 |
| 0.90R (p90) | 167 | −330.81 | 0.921 | 16 | 136 | −3.20 |
| **0.60R (p75) — derived** | 168 | **−105.88** | **0.974** | 53 | 100 | **−0.98** |
| 0.30R (previous contaminated pick) | 171 | −661.27 | 0.820 | 98 | 57 | −6.80 |
- The data-derived p75 target beats the fixed 4×ATR spec target on every axis (−68% net loss, PF 0.920 → 0.974, R-sum −3.16 → −0.98); p90 is a wash (only 16 trades reach it); the old 0.30R pick is the **worst** cell tested. Still below the PF ≥ 1.30 promotion gate — best geometry found, not an edge. Evidence: `artifacts/v75_macro_engine_tester/data_tp_derivation_20260912.txt` + `mfe_sample_31m_off_clean.csv` + four `.htm` reports.

## [V75MacroEngine cache extended to 32 months; 173-trade sample verdict] - 2026-09-11

### Changed — real-tick cache 13 → 32 months via on-demand broker download
- Probes at Mar 2025 and Sep 2024 proved the broker serves years of V75 tick history (the 13-month limit was an artifact of what had been downloaded, not a server cap); each probe month pulled a full half-year block (~10MB/month). Terminal B's cache is now **2024.03 → 2026.09 (32 months)**, fully local — any future range back to Mar 2024 runs with zero download time.

### Added — v1.26: data-derived R-multiple TP mode
- `ENUM_TP_MODE` (`TP_MODE_ATR_MULTIPLE` spec default / `TP_MODE_R_MULTIPLE`) + `InpTPRMultiple`, wired into `DeriveProtectivePrices`, with an init-time `TP mode:` identity print and a HUD field. Compiled default = spec 4×ATR, so out-of-the-box behavior is unchanged (tier-3 regression gate re-run on v1.26: **10/10 pass**, pinned 71-day invariants hold).

### Findings — long-window sample study (canonical 6h+trail, 0.2R/1.0×, spec 4×ATR TP, $10k, real ticks)
- Sample ladder: 71d = 15 fills / +11.67 / PF 1.07 · 6m = 31 / −389.05 / 0.35 · 12m = 72 / −684.32 / 0.50 · **31m (2024.03.01→2026.09.10) = 173 fills / −73.43 / PF 0.97 / R-sum −0.53** — sample gate cleared by ~6×.
- The 173-trade verdict: the strategy is **≈break-even, not an edge** (PF 0.97 vs the ≥1.30 gate; expectancy −0.003R/trade vs the ≥+0.15R gate). Positive tail months exist (Sep 2024 probe +298.33, Mar 2025 +58.62) but are cancelled by negative regimes; drawdown stays bounded (final balance 9,915.29 after a −684 valley). Exit machinery exonerated: 4,321 trail ratchets / 0 modify failures, all entries on M30 bar opens.
- Data-TP stack (0.3R) generalizes worse: 173 fills / −356.73 / PF 0.87 / R-sum −3.53 — the 0.3R cap helps short-window draws but bleeds R on 31 months of runners. Reports + summary archived in `artifacts/v75_macro_engine_tester/` (`long_window_sample_20260911.txt`, both `.htm` reports).

## [V75MacroEngine tester regression gate] - 2026-09-11

### Added — tier 3: the Strategy Tester validation is now a repeatable gate
- `tests/v75_tester_runner.py` + `tests/test_v75_tester_gate.py`: an opt-in tier (`V75_TESTER_TESTS=1`) that runs two headless real-tick tester passes on the fully-cached 71-day window (exit OFF, trail opt-in) and asserts the verified invariants — fill counts (13/15), entries only on M30 bar opens, OFF-mode exits all timeout-backstop (0 SL/TP hits), trail ratchet count (25) with 0 modify failures, exactly-one `POSITION CLOSED` reconciliation per trade, and PnL/PF/R-ledger values (−176.50/−16.65, PF 0.35/0.81, R −1.79/−0.17). 10 tests, ~75s end-to-end.
- Encodes the session's hard-won gotchas so future runs can't re-trip them: explicit `[TesterInputs]` mandatory (agent input-cache reuse), the EA's init-time identity print as the run discriminator, append-only journal parsing via pre-launch byte-offset snapshots, and the `[Tester]` section header requirement for generated INIs.

## [V75MacroEngine 6-month protocol validation fails promotion gates] - 2026-09-11

### Changed — tick cache extended 3→13 months; full protocol range run
- The Strategy Tester auto-downloaded Sep 2025–Sep 2026 real ticks on the first 6-month run; terminal B's V75 tick cache now covers 13 months.
- 6-month real-tick range (2026.03.11 → 2026.09.10, M30, $10k): spec config (exit OFF, 3h timeout) = 29 fills, −783.90, PF 0.17, 0 TP hits, 24 timeouts; best-known config (6h timeout + 0.2R/1.0× trail) = **31 fills (sample gate cleared)**, −389.05, PF 0.35, 0 TP hits, 6 timeouts, max balance DD ≈ 5.1R.
- Protocol verdict: sample-size gate passes for the trail config, but PF (0.35 vs ≥1.30) and expectancy (≈−0.13R vs ≥+0.15R) fail decisively → **back to research, no promotion**. The 71-day +11.67 (PF 1.07) result did not generalize — out-of-sample refutation, not confirmation.
- Structural conclusion unchanged and now 6-month-proven: the 4×ATR take-profit was never reached in 60 trades across both configs; negative expectancy (~−0.13R/trade) persists under every exit machinery tested, isolating the deficit in the entry layer (H4/H1 EMA alignment + M30 BB/RSI springboard). Reports archived in `artifacts/v75_macro_engine_tester/`.

## [V75MacroEngine exit manager defaults to OFF] - 2026-09-11

### Changed — opt-in profit protection, spec-pure default contract
- `InpExitManager` compiled default flipped from `TRAIL` to `NONE` (v1.25): out of the box the EA is the spec-pure SL/TP + 3h-timeout contract, and the ATR-trail/breakeven protection is an explicit opt-in. Opt-in values unchanged (0.2R trigger / 1.0× ATR trail, evidence-set; 6h+trail remains the only net-positive cell at +11.67, PF 1.07).
- Tester-verified both directions on the same real-tick window: pure default reproduces the timeout-only baseline exactly (13 fills, −176.50, PF 0.35, 0 SL modifications), and the opt-in trail run still matches the known trail result (15 fills, −16.65, 25+ ratchets).
- Test rig now pins the OFF default (`test_default_exit_manager_is_evidence_based`), so a silent default flip fails CI.
- Headless-tester gotcha discovered during verification: an INI with no `[TesterInputs]` section reuses the agent's last cached input set rather than the compiled defaults — verification runs must pass inputs explicitly, and the EA's init-time identity print is the discriminator.

## [V75MacroEngine open-profit protection (ratchet exits)] - 2026-09-11

### Added — ATR trail / breakeven so open profit survives the 3h timeout
- New `ManageOpenProfit()` runs on every tick behind the (unchanged) 3h timeout backstop. It is ratchet-only: the SL can move in the trade's favor and never wider, gated by a one-point improvement check and the broker's minimum stop distance, with modifies reported/failed loudly in the journal.
- Three modes via `InpExitManager`: `NONE` (original SL/TP + timeout behavior, byte-identical regression verified), `BE` (one ratchet to entry+offset at the trigger), `TRAIL` (BE step, then trail at `InpTrailATRMult` × H1 ATR — the new default).
- Defaults (`0.2R` trigger, `1.0×` ATR trail) are evidence-set, not aesthetic: in the Jul–Sep 2026 real-tick validation the 3h window never produced a +1.0R favorable excursion (max peak 0.44R), so a 1.0R trigger could never arm; at 0.2R/1.0× the same 71-day run cut net loss from −176.50 to −16.65 (−90.6%), PF 0.35 → 0.81. Trade-off is real and documented: winners are surrendered at the trail instead of running to timeout.
- The peak favorable excursion of every closed trade is now printed at reconciliation ("below trigger — protection never armed" when applicable), making arming behavior auditable from the journal alone.
- Managed/adopted-context invariant preserved: external positions have no R-yardstick (`g_initialSL = 0`) and are never SL-managed; R accounting still happens exactly once through the single cleanup path.
- Strategy Tester evidence in `artifacts/v75_macro_engine_tester/`; repeatable run configs in `config_tester/` and terminal-B `config/v75_*.ini` (`[TesterInputs]` section is the reliable way to pass inputs — named `.set` presets were silently ignored by the tester in this setup).

## [V75MacroEngine verification rig and truthful HUD status] - 2026-09-11

### Added — permanent regression gate for the V75 macro engine
- `tests/test_v75_macro_engine_surface.py` re-verifies the engine after every edit: static spec-invariant assertions on the `.mq5` source, the sizing/refusal math mirrored against real V75 symbol constants (the min-lot clamp-up regression stays proven fixed), and a deployed-binary freshness gate that fails when any terminal copy of the EA diverges from the repo or its `.ex5` is older than its source.
- Live tier (`V75_LIVE_TESTS=1`) attaches read-only to a running terminal and re-checks the tick-value overwrite and sizing verdicts against real broker data; no orders are sent.
- `scripts/sync-mt5.ps1` now deploys, compiles, and build-gates `V75MacroEngine.mq5` in every terminal instance using the same MetaEditor CLI pattern as the live EA, closing the repo↔terminal dual-copy trap for this EA.

### Fixed — HUD no longer contradicts the decision path
- The engine now owns a status string (`g_entryStatus`) set at each decision branch (diverged stand-down, aligned-waiting, entry blocked, order sent, and the undercapitalization refusal); the flat-state HUD renders it verbatim instead of always claiming "Waiting for Macro Alignment", which was misleading on a $50 account where every entry is refused for minimum-lot infeasibility.

## [V75 M30/H1/H4 macro engine] - 2026-09-09

### Changed — replaced the legacy multi-strategy entry surface with a disciplined, self-contained V75 engine
- Entry analysis is now behind a new-M30-candle gate; every tick only services the three-hour guardian, managed-position polling, session accounting, and HUD.
- Direction requires previous H4/H1 closes aligned around their own EMA(20); the M30 springboard uses BB(20,2) or RSI(14) thresholds 35/65.
- The active trade contract is one position, 1% equity sizing, 2× H1 ATR(14) SL, 4× H1 ATR(14) TP, calibrated tick value with a 5% identity tolerance, and forced liquidation at exactly three hours.
- The EA is now self-contained with only the native `<Trade\\Trade.mqh>` include, and its V75 presets explicitly separate paper/off from live execution.
- Added source/preset regression checks for the new gate, macro alignment, risk geometry, timeout, polling, and no-live-order default.
- No order was sent and no terminal state was changed during this pass.

All notable changes to Synthetic AI Trader are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Execution idempotency and horizon fail-closed hardening] - 2026-09-08

### Fixed — duplicate closes and malformed research configuration cannot corrupt state
- Close bookkeeping now returns immediately after the tracked position has already been cleared, preventing an `OnTradeTransaction` event plus fallback/local close from double-counting P/L, learning, or paper results.
- Persisted `ENGINE` rows are accepted only when all five fields are present, so truncated state files cannot read beyond their schema.
- Optional horizon mode now rejects invalid geometry, confidence, agreement, and lookback parameters at initialization; its configured lookback is used for momentum and path efficiency instead of being silently fixed at 32 bars.
- Deployed V75 presets remain unchanged: horizon mode is off and no live order was sent.

## [Fresh-install governor initialization] - 2026-09-08

### Fixed — new charts no longer start in probe-only mode
- Strategy-enable flags are now initialized to enabled before persisted review state is loaded.
- Existing state files still override those defaults, while a brand-new chart can evaluate the configured V75 strategies normally instead of silently allowing only every 10th signal.
- No signal thresholds, exit geometry, risk sizing, presets, or live execution behavior changed.

## [Blind 90-day A/B replay and standard-path micro-balance fix] - 2026-09-05

### Fixed — normal Volatility entries bypassed `InpMicroFitPct`
- The two-terminal blind replay used identical Deriv MT5 M15/H1 history from 2026-06-07 18:00 UTC through 2026-09-05 18:00 UTC, with exact OHLC agreement across terminals A and B.
- Before the fix, accepted $50-account trades risked 6–20% because the standard `OpenTrade` path clamped to the 0.01 minimum lot and enforced only the 20% cap; the alternate opener already had micro-balance fitting.
- v26.36 applies the 1.5% micro-fit to the standard path, preserves broker/spread stop floors, recomputes effective risk, and pins `InpMicroFitPct=1.5` in both V75 paper presets.
- Baseline result: Arm A TP 1.8 ended $18.96 (-62.08%, 36 trades, -6.88R); Arm B TP 2.4 ended $21.00 (-58.00%, 48 trades, -5.60R). These are diagnostic results, not a live authorization.
- Source and replay fix are pending compile/deployment; no terminal `.ex5` was replaced and no live order was sent.

## [Go-live checklist rehearsed: every artifact verified in place, abort criteria pre-written] - 2026-09-05

### Added — docs/GO_LIVE_CHECKLIST.md, the exact $50 execution procedure (do NOT run until the gate passes)
- **Everything verified in place on terminal A** (data folder `FB9A56D617EDDDFE29EE54EBEFFE96C1`): `MitemshubAI.ex5`/`.mq5` v26.35 present, `MitemshubAI_VOL75_LIVE.set` present and **byte-identical to repo** with `InpLiveExecution=true`, `InpMagic=7788075`, `InpTpMult=1.8`, fleet CSV covering A+B.
- **Expected banner lines extracted from source**: LIVE attach shows `MITEMSHUB AI v26.35 ... Standard Mode` with **NO `PAPER MODE:` line** (the discriminator), `FIT ROUTER: instruments vs a $50.00 account` + `TOLERATED ... each trade risks ~9-13% of equity`, `RiskCap=20%` + tiny-account warning (expected at $50), `[SELFTEST] OK`. Live orders print `Executing BUY/SELL vol=.. SL=.. TP=..`; failures print `ORDER FAILED retcode=..`.
- **$50 truth table**: ~$4.6-6.5 min-lot stop-risk ≈ 9-13%/trade (TOLERATED); $31 floor ≈ 20% (at cap); below $31 → `CANNOT FIT` vetoes everything; $100+ ≈ 5-7% (sane compounding size).
- **Abort criteria pre-written**: PAPER MODE in banner / CANNOT FIT at funded balance / wrong magic or TP / dashboard MODE not LIVE / any ORDER FAILED / first fill wrong symbol or magic.
- Also flagged: 2026-09-04 record said real account at $0.57 — funding to ≥$50 must be confirmed broker-side at attach (the FIT ROUTER banner prints the true balance).

## [Operating summary: every question closed by protocol, the gate tree pre-declared] - 2026-09-05

### Added — docs/OPERATING_SUMMARY.md, the single reference for what is and isn't open
- **10 closed questions** with verdicts (engine honesty, generator memorylessness, regime axis, MOM duel, V100, cost-dilution, spread tiers, EA audit, data path, arm C) — each with its frozen protocol + artifact + commit, and the rule that nothing reopens by vibes.
- **The one open gate**: TJ1 paper A/B (≥30 arm-A trades, positive expectancy, paired |t|≥1.0) + TJ2 tick reconciliation (self-arms 7d) + TJ3 watchdog — with the current status (clock not yet started, 0/30) and the pre-registered accelerated path (20 trades + 5d reconciliation).
- **Decision tree for every gate outcome**, pre-declared: GO LIVE (all three green) · NO GO if any leg fails with the fix-first order · INCONCLUSIVE → keep collecting with 50/75-trade boarding · arm-A negative → re-baseline + protocol-ordered investigation, collection continues · TP-2.4-wins branch (re-certify on the 210-day window before any preset change, then arm-C paper test) · and the full arm-C candidate branch (new pre-registered rule, activation ≈1 min, teardown on loss).
- Non-negotiables restated (live = A/chart01/7788075 only; no hand-tuning; funding floors; spec-stamped artifacts; data is the only judge) + the daily cadence.

## [V75 spread-tier study: the broker-side lever is dead on Deriv synthetics] - 2026-09-05

### Executed — frozen protocol (docs/V75_SPREAD_TIER_STUDY.md, committed `ded5e3a` before any measurement)
- **Measurement, 2,460,772 ticks (Jul 7–Sep 2, both lake files)**: V75 effective spread is a step grid (levels ~16.0/17.0/17.9/18.5) **flat at 16.96 median for every hour of day** — no hour-gate exists to exploit. The live 18.5 calibration sits at the lake's p99: the standard account's spread IS the raw model spread (16.96 = −8.3% vs 18.5, under the 25% materiality threshold). Deriv's Zero Spread MT5 account cannot price below the generator's raw spread on synthetics.
- **Net edge per tier (fresh60, deployed tp 1.8; integrity gate: t185 ledger bit-identical to stored)**: raw 16.96 → +0.048R/t, 14 → +0.054R/t, 9.25/4.6 → +0.031/+0.028R/t (non-monotonic — governor re-routing noise at 120 trades), spread 0 → +0.162R/t BUT that ceiling is a different strategy (band-fade reopens, 9 trades +11.1R) and structurally unpurchasable.
- **Robustness (70d, 9 folds)**: near-linear cost response, **+0.0023R/t per unit of spread** (matches mean(1/sd) exactly) — the deliverable pricing slope for any future venue quote. Even the zero-spread ceiling fails fold consistency (3/9).
- **Verdict**: NO tier clears the frozen +0.08R/t bar on either window; P1 and P2 both held. Hour-gate idea dead by measurement; broker-side lever dead on this platform; no EA change, no arm-C candidate. Cost structure remains the binding constraint — growth depends on the paper gate's verdict, not on hunting a cheaper toll.

## [Arm C activation rehearsal: minutes-scale promise PROVEN] - 2026-09-05

### Executed — supervised 10-minute run of docs/ARM_C_TEMPLATE.md, verbatim
- **T0 12:22:46** → `authorized '140778269' on DerivSVG-Server-03` at **T+6s** → full v26.35 banner (SELFTEST OK, GARCH ready, 200-bar cold-start catch-up, `PAPER MODE: virtual equity $50.00`, tick value calibrated, `FIT ROUTER ... TOLERATED` $4.59 at live spread) at **T+8s**. Pre-flight had verified the `common.ini` login pointer (UTF-16 — plain grep reads nothing), chart magic 7788125, paper mode, and the fleet (2 running: A, B; C off).
- **Steady state**: EA evaluated real bars (first `sig`/SKIP telemetry event), state CSV fresh; telemetry quiet-window behavior matched healthy arm B exactly (event-driven cadence — recorded in the template so nobody misreads quiet as dead).
- **Parked** at T+23min — about 1 minute of procedure, the rest deliberate observation — via PID-from-ExecutablePath kill; A/B untouched, both wrote telemetry at the next M15 close. Time-to-operational ≈ **1 minute**; the doc's "minutes, not hours" promise is now measured, not assumed.

## [Spec-integrity guard: cross-instrument cert runs must STATE their specs] - 2026-09-05

### Added — the V100 0.01-lot lesson, made mechanical
- `certify_v75.py`: `assert_spec_integrity()` runs inside `certify()` — if `CERT_DATA_DIR` is set, all four spec variables (`CERT_SPREAD`, `CERT_USD_PER_UNIT_PER_LOT`, `CERT_MIN_LOT`, `CERT_LOT_STEP`) must be explicit or the run **exits 1 before any data pull**, with the correct V75 truth printed in the error. Default V75 runs (no `CERT_DATA_DIR`) are exempt: the defaults ARE the V75 truth. Every caller (walkforward, study scripts) is covered transitively.
- **Spec stamp in every artifact**: `spec_block()` — data_dir, spread, usd/unit/lot, min_lot, lot_step, cost model, geometry (`tp_mult`/`stop_mult`/`min_score_bonus`), which env vars were explicit, guard version — is written into every `cert_report_*.json` and every walk-forward artifact (which also stamps its full config registry). An artifact whose sizing implies a lot grid the instrument cannot trade is now self-identifying as invalid.
- `z_gate_phaseA.py` declares its specs explicitly (its data IS V75, pulled via `pull_v75_week`) — custom-dir runs state them like anyone else.

### Verified — four-point battery, all green
- **T2 loud-fail**: non-V75 dir without specs → `SPEC-INTEGRITY FAIL`, exit 1, no artifact written. **T2b**: z_gate's import satisfies the guard via module-level setdefaults. **T3**: explicit specs run clean and the stamp reflects them.
- **T1 bit-identity**: legacy fresh60 re-run at `--tp-mult 1.8` equals the stored 09:01 artifact on all 135 trades and every metric. Two footguns surfaced and were resolved honestly: (1) the CLI's default is `TP_MULT_CERT = 2.4` — omitting `--tp-mult 1.8` silently certifies the wrong geometry (now visible in the spec stamp's `geometry` block); (2) the stored artifact's `funnel.paused` is 947 vs 948 in every re-run — **including from a pristine worktree of the committing SHA**. A gap-aware reconstruction from the trade ledger independently computes 948, so the ledger-relevant contract reproduces exactly and the stored 947 is attributed to the transient pre-commit working tree (runs 08:58–09:01, commit 09:03). No engine issue.

## [Arm C paper-terminal template: built, validated, PARKED] - 2026-09-05

### Added — docs/ARM_C_TEMPLATE.md: a third paper arm that can start collecting within minutes of an adoption decision
- Clone of B's install at `%LOCALAPPDATA%\MitemshubMT5_C`, data folder `71BF6B2AB5548CFBA970FA2F38007C31`, magic **7788125** (verified unused), chart = arm A's validated paper chart (TP 1.8 placeholder), auto-login verified (`authorized '140778269' on DerivSVG-Server-03`), sync gate PASS, v26.35 banner + FIT ROUTER TOLERATED ($4.65 min-lot risk, 9.3%/trade at $50 virtual) + paper equity $50 initialized.
- **Login gotcha recorded**: `accounts.dat` alone does not enable auto-login — the pointer lives in `config\common.ini` (`Login=`/`Server=`). Also: launch MT5 clones via PowerShell `Start-Process` (Bash `&` hangs on the child's handles), and never kill by image name (the 2026-09-04 terminal-A mishap) — kill by PID from the ExecutablePath.
- **Parked by protocol**: the cost-dilution verdict was NO-ADOPT 5/5 and no study has ever returned VALIDATED-CANDIDATE, so C stays OFF until (a) a candidate exists and (b) the primary A/B adjudicates uncontaminated. A running C before adoption would trade an un-adopted config and mint unread data. Activation is a one-input edit + one Start-Process + a morning-status line.

## [V75 cost-dilution study: NO-ADOPT 5/5 — geometry cannot outrun the spread] - 2026-09-05

### Executed — frozen protocol (docs/V75_COST_DILUTION_STUDY.md), one pass, priors held exactly
- **Amendment before the pull** (transparent, committed): the frozen "28 days yields 8 folds" was arithmetically wrong; the power requirement (≥8 fresh folds) dominates, window corrected to 70 days. One pull (Jun 27 → Sep 5, 6,719 bars), all six arms on the same file, cost-inclusive engine, 9×8-day folds.
- **Result**: ws13 −5.42R/141tr, ws17 −4.27R/128tr, ws25 +1.51R/111tr, lf13 −2.65R/143tr, bs17 −4.27R/128tr vs ref −1.21R/158tr — best variant expectancy +0.014R/trade vs the frozen W4 bar of +0.08R. **All five NO-ADOPT, matching all five frozen priors; the cost-dilution thesis is dead on V75.**
- **Reference-failure clause examined, NOT exercised**: ref printed 3/9 positive folds but worst −3.33R (inside its normal certified range) — choppy window, not a regime break; re-pulling after seeing the reference fail would be outcome-fishing.
- **Descriptive finding**: bs17's folds are identical to ws17's — the MinScore+1 frequency lever never bound at current volatility; MinScore is not a live frequency lever on V75.
- **Consequence**: no geometry lever exists on V75; the path forward is the paper A/B gate on the deployed config, and if a cost lever exists it is broker-side (spread tier), not geometry-side. EA and presets untouched.
- Artifact: `artifacts/v75_costdil/costdil_results.json` (+ `walkforward` env block in the doc).

## [V100 net-edge study: NO EDGE + 2y artifact retracted] - 2026-09-05

### Executed — pre-registered study (docs/V100_NET_EDGE_STUDY.md): does the gross edge survive V100's 15x-lower spread cost? NO.
- **Integrity gate caught a systemic confounder first**: the stored Sep-4 2y/210d "gross" V100 runs set spread+tick-value but left `CERT_MIN_LOT/CERT_LOT_STEP` at V75's 0.01 defaults — a broker-impossible lot grid for V100 (true floor 1.0). Every signal traded on negligible dollar size (`max_risk_pct: 0.5` gives it away). Old-code vs new-code on identical envs agree bit-exactly, so the cost refactor was not the cause.
- **Q1 (survival) — the edge DIES.** True-spec net walk-forward, 53×14d folds, ~1,700 trades/config: legacy +29.21→**−20.06R**, v2629 +13.86→**−20.07R**, tp18 +23.09→**−24.55R**. Per-trade cost ≈0.028R (2–3× the naive arithmetic — the −62% price grind shrinks stops while the spread stays fixed, so cost share *rises* over time). Full-period cert at $200: $200→$17.61, DD 94.9% — the true 1.0-lot floor plus early-era wide stops risks up to 20%/trade.
- **Q2 (gate) — nothing passes V1–V6**, matching the frozen prior. V100 stays uncertified; funding follows certification; EA unchanged.
- **Retraction**: the Sep-4 "V100 personality flip" (stack +15.1R on 210d) was an artifact of the same fictional lot grid — under true specs the stack scores **−33.76R (t=−3.00)** on the same window. "No universal geometry" stands for a blunter reason: no validated geometry exists on V100 at all.
- **Standing rule (fourth small-sample-lead-class death, now systemic)**: every cross-instrument cert run must set all five CERT_* spec variables explicitly; any artifact whose `max_risk_pct` implies sizing the instrument cannot trade is invalid on its face. V75 default-spec runs exempt (0.01 IS the V75 truth).
- Artifacts: `artifacts/v100_replay/walkforward_v100_2y_gross_repro.json` (true-spec gross baseline), `walkforward_v100_2y_net.json`, `walkforward_v100_210d_truespec_net.json`, `artifacts/v75_replay/cert_report_v100_2y_net200.json`.

## [Morning status tool + first-trade drill + 2 adjudicator fixes] - 2026-09-05

### Added — scripts/morning_status.py: the one-command morning check (read-only)
- Arm health per terminal (process count via tasklist, EA telemetry write age with a 2h staleness line, ledger veq + integrity), night-gap audit from the UTF-16 terminal journals ("connection lost → authorized" pairs, cross-midnight capable, sub-60s MT5 access-point flaps summarized instead of listed), and go-live gate progress X/30 per arm with days-to-30 at the observed rate. `--strict` exits 1 on unhealthy signals. Validated live: catches the 01:14→08:24 sleep exactly.

### Added — scripts/first_trade_drill.py: prove the paper-data path BEFORE the first real fill (10/10 green)
- Generates synthetic ledgers in the exact EA v26.35 wire format (OPEN/CLOSE/EQ, seconds epochs) in temp dirs and runs the real downstream tools: adjudicator verdicts for empty arms (KEEP COLLECTING), below-gate (ETA projection), clean A-win (P1/P2/P3 all hold), and symmetric-noise pairs (INCONCLUSIVE — the rule refuses to declare on noise); reconciler 7-day gate fires with no broker pull; morning-status ledger parser + cross-midnight journal pairing unit-checked. Ends by restoring truthful real-state artifacts (removes drill-written ones when no real ledger exists yet).
- **Bug found by the drill #1 (HIGH): `ab_adjudicate.py` paired on CLOSE epochs, not the frozen OPEN-epoch rule** — the arms hold different durations under different TP geometry, so in production their CLOSE times would almost never align and the adjudication would starve. Fixed to pair on `open_epoch` (falls back to close epoch only for OPEN-less rows).
- **Bug found by the drill #2 (MEDIUM): zero pairs crashed the adjudicator** (`None` mean formatted with `:+.3f` → TypeError, exit 1, no verdict line). Now prints an explicit zero-pair diagnostic.
- Drill-design lesson recorded in-code: giving the B arm a different `tp_mult` in the "no signal" scenario embeds a REAL winner-pay effect (2.4 vs 1.8) that the paired test correctly catches — the noise arm must share A's outcomes plus symmetric noise.

### Added — docs/MILESTONE_MEMO_v2635.md: one-page milestone memo
- What was claimed (cost-blind +130%), what the re-baseline says (+4.37R net, t=0.35, TP 2.4 negative), the critique replication outcome (cost flaw confirmed; structure claims rejected), the four v26.35 EA fixes, the pre-registered gate as sole authorizer, and the honest standing risks.

## [Verification re-run + CLI hotfix] - 2026-09-05 (morning)

### Fixed — certify_v75.py CLI crashed after writing every report (cosmetic, engine untouched)
- **Bug** — `certify()` pops `r_extra`/`tp_r` from trade records before returning, but `main()`'s trade-dump print loop still read `t['r_extra']` → `KeyError` after the report file was written. Every CLI invocation of the new engine crashed at the final print step; last night's verifications imported `certify()` directly and never hit it. Fix: `t.get('r_extra', 0.0)`.
- **Backward test re-run (legacy engine, CERT_COST_LEGACY=1)** — fresh60 window reproduces the stored `cert_report_legacy_repro_tp18.json` **bit-identically**: all metrics AND all 135 trade records equal (+13.23R / 48.1% / DD 42.2% / $114.76).
- **Forward test re-run (cost-inclusive engine)** — all three re-baselines reproduce exactly: TP 1.8 +4.37R/114/45.6%, TP 2.4 −4.07R/68/39.7%, TP 1.8 @$100 +4.37R/114. Four reports in `artifacts/v75_replay/*_check0905.json`.
- **EA-side deploy gate re-check** — `verify_set_inputs.py` 15/15 presets PASS on v26.35 source.
- **Morning ops check** — both paper arms healthy (v26.35, router TOLERATED at $50 virtual, clean reconnects); PC slept ~01:14→08:24 (accepted: broker archives make any data window pullable on demand; only the paper ledger accrues and sleep nights stretch, never lose, gate time). No closed paper trades yet — gate clock starts with the first fill.

## [Cost-inclusive certification engine + re-baseline] - 2026-09-05

### Fixed — certify_v75.py pays the spread in PnL (fills at bid/ask, not mid)
- **Why** — the critique replication (same day) proved the engine used the 18.5-unit spread only as a veto gate; PnL never paid it. Audit arithmetic said −4.34R on +13.23R; the full dynamic re-baseline says worse.
- **How** — entry fills at the adverse half-spread (BUY at ask, SELL at bid), exit pays the other half via `r_extra`; SL/TP/BE/trail anchor to the real fill like the EA. `CERT_COST_LEGACY=1` restores the cost-blind engine.
- **Integrity** — legacy mode reproduces the published fresh60 run **bit-identically** (+13.23R / 135 / 48.1%) before the new mode is trusted.
- **Re-baseline (fresh 60d, $100)** — TP 1.8: **+4.37R / 114 trades / DD 36.7% / net expectancy +0.038R per trade (t=0.35)** — statistically indistinguishable from zero on this window. TP 2.4: **−4.07R** (negative net of costs; the A/B now adjudicates marginal-positive vs negative). Governor trajectory shifts (MOM+PB auto-disabled at −2.08R; PB carries +6.22R alone). Funding Monte-Carlo re-priced on the net stream: $31 → 10% P(profit), $50 → 39%, $100 → 92% survival, median +$3.42/60d.
- **Consequence** — the pre-registered go-live gate (≥30 positive-expectancy arm-A paper trades + tick reconciliation PASS + watchdog) is the only authorizer; a non-positive gate outcome triggers investigation, not live deployment.
- Artifacts: `cert_report_fresh60_tp18_net.json`, `cert_report_fresh60_tp24_net.json`, `cert_report_fresh60_tp18_net100.json`, `cert_report_legacy_repro_tp18.json`, `funding_plan.json`.

## [Critique replication: Tests A/C, drift audit, cost correction] - 2026-09-05

### Added — docs/CRITIQUE_REPLICATION.md + scripts/critique_replication.py: external critique's demands executed under frozen protocol
- **Why** — an external critique challenged the project's claims (Band Fade contradiction, small-sample "certification", missing costs, EMA regime as noise). Response: verify its factual claims against artifacts, then run its Tests A–C on our own data under a pre-registered protocol (`frozen before execution`, one pass).
- **Test A (variance ratios, 8s→256h + supplementary 0.5h/1h/2h/4h)** — all inside surrogate null bands (2.46M ticks + 19 months of H1): no linear trend/mean-revert structure at any horizon. Generator confirmed memoryless at every tested scale.
- **Test C (regime-conditional forward drift, exact EA mirror)** — the EMA regime axis carries NO directional information; sign is weakly anti-continuation (BULLISH label → negative forward drift, consistent 8/8 across eras/horizons, strongest fresh-era episode t=−2.57). Vol terciles: nothing. The regime axis's remaining legitimate role is volatility-aware gating/sizing, never direction.
- **Cost flaw CONFIRMED and quantified** — the cert engine never subtracted the 18.5-unit spread from PnL (veto gate only). Corrected: +13.23R → **+8.89R net** (0.098R→0.066R/trade). Engine fix queued so all future certs are cost-inclusive.
- **Small-sample honesty applied to ourselves** — fresh60 Wilson 95% LB = 39.9% win rate, per-trade t=0.96: the honest claim is "consistent with zero-to-small positive expectancy", and the ≥30-trade live paper gate (not backtests) decides live value. Drift audit: 19-month −78% downtrend then a near-doubling Feb→Jul 2026 — long-run drift real but sign-unstable; hourly-grain drift unpredictable (t=−1.62); drift capture would be a position strategy, not M15.
- Artifacts: `artifacts/critique_replication/results.json`, `vr_long_horizon.json`.
- **Queued fix**: spread-cost-inclusive fills in certify_v75.py (all future certifications cost-inclusive, flagship numbers re-baselined once).

## [Drift-vs-Σ tracker: CLOSED (1/3) — no EA integration] - 2026-09-05

### Registered → executed in one pass (docs/DRIFT_SIGMA_TRACKER.md, artifacts/drift_sigma/)
- **Question**: can a causal tick-stream tracker (EWMA drift µ₂ / EWMA σ₂ over trailing 1800 steps) estimate the generator controller's state well enough to feed the EA a regime-confidence input?
- **Tick lake extended**: July gap filled (+1,165,557 quotes → 2.46M ticks, Jun 7 → Sep 2).
- **K1 predictiveness — FAIL, sign inverted**: quintiles flat, daily spread t = −1.90 (wrong sign), Spearman −0.056 → the EWMA drift estimate **mean-reverts** (hours that trended hard give it back). No positive predictive power.
- **K2 economic gating — FAIL per frozen bar**: gating kept +9.73R/72 vs blocked +3.50R/63 (D = +6.23R, better per-trade expectancy) but t = 0.57, worst fold −5.83R — two of three requirements missed. Base arm reproduced the published +13.23R/135 exactly (integrity check held).
- **K3 vol forecast — PASS decisively**: tick-EWMA σ beat M15 ATR(14) on all 716 hours (RMSE 7.7× lower, MAE 11.9× lower; caveat: shared-scale advantage vs a range-based proxy).
- **Verdict: CLOSED (1/3)** — no EA change. Only legitimate open thread: K1's inversion suggests a *fade-the-drift* mechanism, re-registrable only as a new protocol. The M15 regime layer remains the validated intelligence.

## [Generator fingerprint study: the V75 machine decoded] - 2026-09-04 (night)

### Added — `scripts/generator_fingerprint.py` + docs/GENERATOR_FINGERPRINT.md: how the tick generator actually works
- **Data**: 1,295,215 real ticks over 30 continuous days (broker archive), cadence cross-validated against broker-history probes (the feed itself is 0.5 Hz — one tick per 2.000 s, zero jitter: a deterministic step machine).
- **Findings (T1–T7)**: Gaussian steps (skew 0.00, kurtosis 0.01); up/down 0.4998; tick-return ACF max |ρ|=0.0025 over 100 lags (no direction memory); run lengths match a memoryless coin to 4 decimals; variance ratio ≈ 1.00 at 1s–1m and 0.97–0.98 at 15m–1h (pure random walk); no volatility clustering at tick scale; hour-of-day vol flat to 1.8% (per-step vol targeting confirmed).
- **Conclusions**: "working ahead of the generator" at tick level is mathematically impossible — each step carries zero information about the next, so tick-momentum, spike-runs, and tick-mean-reversion are coin-flip noise by construction (consistent with the earlier tick-fade rejection). The only evolving signal is slow drift-vs-vol — exactly what the M15/H1 regime layer and GARCH already estimate. **The M15 operating point is the correct one, not a compromise.** The 2s clock is an execution/simulation gift (event-exact fills, reconciler ground truth).
- No EA config changes; research direction settled: regime intelligence at bar scale, not tick-speed reflexes.

## [v26.35 — Full pre-live code audit: 4 bugs fixed] - 2026-09-04 (night)

### Fixed — findings from the line-by-line audit (docs/FULL_EA_AUDIT_v2635.md)
- **CRITICAL (paper)**: the ACCOUNT GUARD in `OpenTrade` compared fleet risk against **real account equity** while sizing used paper virtual equity — with $0.57 real vs $50 paper, every paper entry was vetoed (`fleet $0 + $6.25 > $0.086 cap`). Root cause of the weeks-long v26.28-era paper silence. Guard now uses the same equity basis as sizing (`PaperActive() ? PaperEquity() : AccountEquity()`). Consequence: paper A/B statistics genuinely start from tonight; pre-fix paper data is zero by construction.
- **HIGH (live)**: `StratEnabledOrProbe(i)` returned `true` on out-of-range index — a latent governor bypass on any future slot-index slip (the v26.34 VB-BURST `8` bug would have sailed through). Now fail-closed (OOB = deny).
- **MEDIUM (live)**: default `InpMagic` was `7788211` — an orphan not in the fleet CSV, invisible to the fleet guard and close filters on a default-input attach. Now `7788075`.
- **COSMETIC**: self-test banner had 9 format specifiers / 6 args (doubles consumed `%d` slots → garbage `regime 1250694476/5`); counters cast to int. Dashboard fleet-cap display got the same equity-basis fix.
- **Verified clean**: sizing chain = certified model; server-side SL/TP always attached; stops-level validity + entry-abort guards; exit ladder = certified ladder; close detection triple-redundant with dedupe; state files symbol-tagged and terminal-local; all 15 presets PASS; zero CB remnants in live paths.
- **Deployed**: MetaEditor 0 errors / 0 warnings, `.ex5` synced to 13 instances, both paper terminals auto-restored on v26.35 (banner, `TOLERATED` router at $6.31/12.6%, paper $50) — paper A/B continues on the fixed engine.

## [MOM-standalone duel: REJECT] - 2026-09-04 (night)

### Registered, executed, closed — lone-momentum trading is noise-chasing (docs/MOM_STANDALONE_DUEL.md)
- **Trigger**: the 2026-09-04 19:15–21:15 V75 waterfall (1,417 pts) that the EA skipped via the lone-momentum demotion — hindsight showed 2 would-be SELL winners. Treated as a hindsight teaser and pre-registered instead of acted on.
- **Engine**: `certify_v75.py` gained a surgical `mom_standalone` toggle (default off — verified to reproduce the published fresh60 run to the trade: +13.23R/135/48.1%).
- **Window (a), fresh 60 days, 8 paired folds**: demote **+13.23R/135** vs standalone **+10.01R/167** → D = −3.22R ✓, t = −1.70 ✓, worse in 6/8 folds (one −11.55R blowup fold) → **REJECT**. The standalone arm even triggered governor auto-disable (MOM, MOM+PB) and *still* finished worse while being rescued.
- **Window (b), 19 months (z-gate data), 28 paired folds**: full-window totals confounded by stateful-governor divergence (auto-disable killed PB in the demote arm: 69 vs 719 trades) — clean fold deltas: +2.17R/fold, t = +1.15, neither REJECT nor ADOPT → **NO-ADOPT** for that era (standalone still net-negative overall, −23R).
- **Methodology lesson recorded**: in long continuous sims the stateful governor (auto-disable, loss-scaling) diverges between arms — full-window totals stop being a pure signal-rule comparison; fold-based paired deltas with state reset are the honest statistic (all future duels).
- **Decision**: `InpMomentumStandalone` stays `false`; deployed preset and paper A/B untouched.

## [Funding-growth plan tool] - 2026-09-04 (evening)

### Added — `scripts/funding_plan.py`: balance simulation + withdrawal-schedule comparison
- Replays the certified 60-day TP 1.8 trade sequence (135 trades, `sd`/`r` pairs) through the exact EA money layer (`v75_money.py`: min-lot clamp, 0.75^loss scaling, 20% effective-risk cap, compounding) at $31/$50/$100/$200 starting equity.
- **Monte Carlo**: 1,000 shuffles of the trade order (geometry kept paired with its own outcome); measures P(profit), P(ever min-lot-stuck), terminal-equity percentiles.
- **Withdrawal policies simulated inside the walk** (later trades sized on post-withdrawal equity): compound / weekly bank-above-$100-buffer / weekly bank-half-of-profit.
- **Findings**: $31 viable in name only (93% stuck, 25% profitable, median $22); $50 coin-flip (59% stuck, p05 ≈ $19); **$100 = safe floor (97.6% profitable, path-independent +$64.76, veto rare and recovering)**; $200 adds only veto headroom. Recommended schedule: weekly withdrawal of everything above a $100 working buffer (banked $92 in 60 days at $100 start, min equity $72).
- Outputs: `artifacts/v75_replay/funding_plan.{json,md}` (md carries the frozen recommendation). `docs/LIVE_READINESS.md` funding section updated to cite it.

## [Paper A/B live + LIVE readiness package] - 2026-09-04 (evening)

### Added — both paper arms running (operator steps 2+3 completed autonomously)
- **Arm B terminal created without user action**: cloned the MT5 install to `%LOCALAPPDATA%\MitemshubMT5_B` (non-portable first launch generated data folder `49E0383C…`), copied login/`accounts.dat`/`servers.dat` from terminal A, seeded a UTF-16 `chart01.chr` cloned from A's validated profile with `InpTpMult=2.4` + `InpMagic=7788100`, ran `sync-mt5.ps1` (13 instances), launched — EA auto-attached with the v26.34 banner, paper mode, router TOLERATED, authorized on the same demo account.
- **chart04 landmine resolved** by MT5's own exit-flush: the Default profile now holds only chart01 (EA, validated config) + one plain chart; detacher verified nothing to strip.
- One controlled mishap during B's setup: the name-based process fallback killed terminal A alongside B; A was relaunched immediately and auto-restored the validated config (v26.34 banner, TOLERATED router). No state lost (paper mode).

### Added — live-trading readiness (`docs/LIVE_READINESS.md`)
- **`MitemshubAI_VOL75_LIVE.set`** — identical to `VOL75_FINAL` except `InpLiveExecution=true` (TP 1.8, magic 7788075); `verify_set_inputs.py` PASS.
- **Broker-exact funding math** (`order_calc_profit`-based, cross-checked against the EA's FIT ROUTER): V75 min-lot stop-risk $6.19 ⇒ **$31 equity floor** (20% cap); $10 accounts cannot trade V75 on this broker (lot floor, not strategy); $2,800 unlocks V100 (uncertified).
- **Fresh 60-day certification** (Jul 7 → Sep 4): TP 1.8 **+13.23R, $50 → $114.76** (135 trades, 48.1% WR, 42.2% max DD) vs TP 2.4 +4.60R — third consecutive fresh window with TP 1.8 ahead.
- **Pre-registered GO-LIVE GATE**: A/B expectancy positive at ≥30 trades + tick reconciliation PASS + watchdog CERTIFIED; documented accelerated option (20 trades + recon PASS) and the live-deploy procedure.

## [v26.34 — Crash/Boom engine physically removed] - 2026-09-04

### Removed — the dormant CB engine is gone from the source tree (user request)
- **Deleted**: `mql5/MITEMSHUB_AI/CrashBoom/` (CrashBoomEngine, CrashBoomStrategy, SpikeDetector, TickPatternAnalyzer, MultiTimeframeConfirm, TimeOfDayAwareness, SymbolCalibration, DynamicRiskSizing) — ~9 modules reachable only from the retired CB path. History preserved in git and `artifacts/v2633_source_backup/`.
- **Deleted from the EA**: every CB input (mode/is-crash/micro-fade/AUTO-param sources/quick-TP/tick-fade/burst-guard group), the learned CB spike gate (EWMA + `MitemshubAI_cblearn` persistence), the burst-guard policy self-check table, `CBRecordReject` reject-accounting (counters kept, no longer incremented), the CB signal branch and CB exits in both live and paper manage paths.
- **Survived, deliberately**: the Volatility-only init guard (now cites v26.34), the tick recorder (`TickRecorder.mqh` relocated to `Microstructure/` — the opt-in microstructure archive, default OFF), `OpenTradeLive` (the engine-plan opener, kept for the VB-BURST leg) now using the standard risk-planned sizing chain, and the v26.12 reject counters for state-file continuity.
- **Strategy table**: 9 → 6 slots (PB/BO/MOM/MR/BF + VB-BURST at slot 5); `STRAT_SLOTS=6`, names table, governor thresholds, and the state-file loader (old rows 5–8 dropped cleanly) all aligned. Fixed a latent bug in the same stroke: the VB-BURST governor gate called `StratEnabledOrProbe(8)`, which would have silently bypassed the governor on the 6-slot table.
- **Verified**: MetaEditor compile **0 errors / 0 warnings**, fresh `.ex5` synced to all 12 instances (108 orphans pruned on first sync), `verify_set_inputs.py` passes on the V75 presets (zero CB keys), weekly drift report parses v26.34 banners.


## [Paper pipeline: weekly scheduled run] - 2026-09-04

### Added — automated weekly verdict tracking (no manual runs to remember)
- **`scripts/paper_pipeline_weekly.cmd`** — scheduled-task entry point (repo's `%~dp0` wrapper convention, venv python); appends every run to `artifacts/v75_replay/paper_pipeline_sched.log` so unattended runs are permanently recorded.
- **Scheduled task `Mitemshub Paper Pipeline Weekly`** — Sundays 06:30, deliberately 30 min after the existing `Mitemshub Weekly Data Refresh` (Sundays 06:00) so reconciliation/regime tools see the week's fresh bars. Read-only by design.
- Verified end-to-end via `Start-ScheduledTask`: run completed with result 0, next fire 2026-09-06 06:30. From the first paper trade onward, the log's diff section is the automatic "which verdicts changed" report.

---

## [Regime-gate study round 2 (harness-only, no EA change)] - 2026-09-04

### Studied — adaptive regime gating re-tested on the 210-day sample: NOT VALIDATED, three independent ways
- **"What changed after Aug 9" — nothing anomalous.** Post-Aug9 legacy fold z-scores −0.08..−1.23 sit inside the pre-Aug distribution (9/22 pre-Aug folds were also negative); fold-to-fold R autocorrelation is **−0.12** (a momentum regime gate would have scored +23.7R vs buy-and-hold-the-strategy's +51.4R). A perfect ex-ante gate's oracle bound is +40R over legacy — the prize exists, so the question moved to trade level.
- **Trade level (scripts/regime_gate_study_v2.py, pre-registered calibration F01–F16 / validation F17–F26 split)**: on 283 calibration PB trades, mild separators finally appear at real sample size — mid-|z| bucket +0.203R vs tails −0.032R, hour-bucket B1 +0.270R, and the family-throttle's causal basis is real but weak (trades taken while the 10-trade window is below −3R: +0.013R vs +0.099R cold). The chosen `|z| ≤ 1.08` gate was directionally right out-of-sample (vetoed bucket worse OOS, kept-total higher) but **deleted 56% of trades to gain +0.3R** → G3 fail → GATE NOT VALIDATED.
- **Round-4 walk-forward (walkforward_210d_r4_gate.json, reference = tp18)**: the never-tested tp18+throttle combination scores **+45.88R vs tp18's +52.42R — the throttle costs 6.5R on the validated base config**. Every adaptive variant (throttle, gate+stack, tp18+thr) fails V2/V3/V4/V6; static **TP 1.8 remains the only walk-forward-consistent config**.
- Standing architecture: the harness keeps `--family-throttle` for re-testing as paper data grows, and trades now carry `atr_pct` in their records for future regime work — but no gate is deployed. The EA's existing outcome-adaptive machinery (per-strategy auto-disable, 3-loss pause, probe re-entry) remains the only adaptation with a validated basis.

## [TP-duel fresh-data test] - 2026-09-04

### Studied — the last uncontaminated V75 window adjudicates the TP duel: CONFIRMS-TP18-LEAD
- **Design** (docs/TP_DUEL_FRESH_TEST.md, frozen before execution): legacy TP 2.4 had never run on pre-Feb-2026 bars, so the paired difference on 2025-08 .. 2026-01 was uncontaminated; D = legacy − tp18 with registered thresholds (CONFIRMS ≤ −3.0R & t ≤ −1.0; tie-band between; UPSET ≥ +3.0R & t ≥ +1.0 relabels the favorite but never touches the preset); 3 registered ~2-month folds; one look, then closed.
- **Result**: legacy +10.86R vs tp18 +20.98R → **D = −10.12R, fold deltas [−7.71, +4.42, −13.70], t = −1.06 → CONFIRMS-TP18-LEAD**. TP 1.8 wins 2/3 folds; both arms positive on the window; deployed preset unchanged; paper A/B proceeds as the final judge (two-sided by design).
- **Standing duel record**: Feb–Sep 2026 (26 folds, ~500 tr): tie (+52.42 vs +51.44). Aug 2025–Jan 2026 (fresh one-shot): tp18 by +10.12R. Historical power for this question is now exhausted — paper data is the only remaining adjudicator, as it always was. Also notable: the tp18 family is now positive on **three** disjoint multi-month spans (Oct–Dec 2024 +17.4R probe, Aug 2025–Jan 2026 +20.98R, Feb–Sep 2026 +52.4R).

## [V100 two-year walk-forward] - 2026-09-04

### Studied — the stack-vs-legacy flip was fold-count noise: the veto+depth stack loses on BOTH instruments; question settled
- **Power**: 2 years of V100 bars (2024-08 .. 2026-09, 71,038 M15 bars; 210-day set snapshotted), 53×14-day folds, ~2,000 trades per config — ~5× the V75 round-3 power. Driver gained env knobs (`WF_FOLD_DAYS`, `WF_CONFIGS`) so per-symbol runs never touch V75 defaults.
- **Result**: legacy TP 2.4 +31.66R (26/53 folds, t=+0.67) | **v2629 stack −7.09R (t=−0.18)** | tp18 +25.01R (reference). The 210-day stack lead (+15.1R vs legacy −2.05R) **inverts completely under power** — the stack is now measured harmful on V75 (~33R drag) AND net-negative on V100. There is no instrument where it wins; the "V100's config" hypothesis is dead.
- **Second settled question**: no V100 geometry validates (best t=+0.67, worst fold −13.5R). V100 stays uncertified — the fit router may name it, but funding follows certification, and V75 remains the only certified instrument.
- **Meta-lesson (third occurrence)**: August filters → 33R drag at 26 folds; mid-z effect → sign flip on fresh data; V100 stack flip → inversion at 53 folds. Every small-sample lead this project has chased died under power. The pre-registered walk-forward discipline is the only reason none of them reached the EA.

## [Pipeline runner] - 2026-09-04

### Added — scripts/paper_pipeline.py: one command runs every study tool and reports which verdicts changed
- Dynamic tools re-executed (all self-gating, read-only): A/B adjudicator, paper↔tick reconciler, regime-gate replication v3, weekly report (ledger + watchdog + preset drift). Registered one-look contracts read from artifacts, never re-run: z-gate Phase A, V75/V100 walk-forwards, regime3 interim.
- Arm A/B discovery is automatic (chart-magic scan of terminal profiles, ledger-presence fallback). Verdict extraction handles VERDICT/Verdict lines and the watchdog's CERTIFIED/VIOLATIONS format.
- State: `artifacts/v75_replay/pipeline_state.json` — every run diffs verdicts against the previous run and prints NEW / CHANGED (was → now) / unchanged. This is the "re-run once a week of paper data exists and report what changed" deliverable: it is one command, and it reports nothing-but-the-truth today (arm dirs: none — still gated on the MT5 reload; zgate NOT VALIDATED; both walk-forwards NOT VALIDATED for adaptive configs; watchdog CERTIFIED 36/0/28).

## [Z-gate Phase A] - 2026-09-04

### Studied — the z-only gate gets its pre-registered fresh-data test and fails comprehensively: NOT VALIDATED, final for this generation
- **Protocol first** (docs/Z_GATE_PROTOCOL.md, frozen before any data point was examined): Phase A on strictly untouched history (2024-08 .. 2026-01 — zero overlap with the burned Feb–Sep 2026 window), gate forms committed in advance (PRIMARY tertile-keep, FALLBACK median-keep), calibration pre-bar C1–C3, one-shot validation W1–W5 with segment-consistency requirements, multiple-comparisons ban on further threshold archaeology. Pull tooling gained `--end` for historical windows; `z_gate_phaseA.py` executes the contract mechanically.
- **Outcome**: calibration passed decisively (720 PB trades, keep +0.125R vs veto −0.038R, gap +0.163 → edges frozen |z| ∈ (0.420, 1.240]) — then validation (one shot, 170 trades) **flipped sign**: kept +0.017R vs vetoed +0.159R (gap −0.14), kept only 25% of trades, and keeping mid-z trades cost −12.9R/−7.4R per segment against +20.98R for trading everything. W1–W5 all false → NOT VALIDATED, final.
- **Reading**: the mid-z effect was window-luck with a clean mechanism-shaped costume — it fit in Feb–Sep 2026, reversed in Aug 2025–Jan 2026. This is exactly what the protocol was designed to catch: one look, fresh data, sign-flip exposed. The |z| gate question is closed at this sample size.
- **Descriptive silver lining** (not a criterion): the tp18 base strategy scored +20.98R on the Aug 2025–Jan 2026 window — positive on two disjoint ~7-month spans now.

## [Cross-instrument certification: V100] - 2026-09-04

> **SUPERSEDED 2026-09-05**: the V100 numbers below (and the "personality flip") used the V75 0.01-lot default — a broker-impossible grid for V100. See the 2026-09-05 net-edge study entry and docs/V100_NET_EDGE_STUDY.md. Kept for the audit trail.

### Studied — the harness now certifies any Volatility symbol; V100 measured, NOT VALIDATED, and the lesson is structural
- **Capability (sharpening the Volatility mandate)**: `certify_v75.py` is now symbol-agnostic via env (`CERT_DATA_DIR/CERT_SPREAD/CERT_USD_PER_UNIT_PER_LOT/CERT_MIN_LOT/CERT_LOT_STEP/CERT_SPREAD_GATE_FRAC`), `pull_v75_week.py` takes `--symbol/--outdir`. V75 defaults byte-identical; all prior artifacts reproduce.
- **V100 fit (live specs)**: honest broker tick value (identity verified — unlike V75's 100× lie), spread 0.26 (3% of a 1.7×ATR stop, so the spread gate passes instead of strangling), min lot 1.0 → $8.76/min-lot trade = 4.4% at $200. Risk-wise the best Volatility instrument yet.
- **V100 verdict (210 days, 26 folds, ~500 trades, pre-registered V1–V6)**: every config NOT VALIDATED. The surprise is a **personality flip vs V75**: legacy TP 2.4 scores −2.05R (t=−0.09) while the v26.29 stack scores +15.1R (t=+0.69) — the veto+depth filters that were a 33R drag on V75 are a +17R swing on V100. There is **no universal geometry**: instrument personality differs, and every symbol needs its own walk-forward + paper evidence before funding. Per protocol nothing is deployed for V100; the stack-positive lead (t=0.69, 12/26 folds) is recorded for a future, properly powered study (2y of V100 bars or a paper arm) — not promoted on t=0.69.
- **Standing conclusion hardened**: V75 (TP 1.8) remains the only certified instrument. "Sharpening Volatility skills" = per-instrument certification discipline, now executable in one env-prefixed command for any symbol in the family.

## [MITEMSHUB AI EA v26.33] - 2026-09-04

### Changed — VOLATILITY-ONLY MANDATE (owner decision: nothing to do with Crash/Boom, ever)
- **`OnInit` refuses Crash/Boom symbols** — `INIT_FAILED` with a loud log naming the mandate; the EA can no longer be attached to a Boom/Crash chart by accident. Rationale on record: spike-gap mechanics fill stops at post-spike quotes (structurally incompatible with the BE/trail ladder), the tick-burst family measured net-negative across the full 70-cell calibration, and no CB walk-forward exists or is planned.
- **Fit-router universe trimmed** to Volatility 10/25/50/75/100 — the router can no longer recommend Crash 500 (or any CB) to a small account; its advice now always points inside the certifiable Volatility family.
- **CB presets deleted** (`MitemshubAI_BOOM1000_CB.set`, `MitemshubAI_CRASH1000_CB.set`) from the repo and all terminals; sync prunes them henceforth (24 orphans pruned on this deploy). CB *engine code* stays dormant for historical reference — nothing references it on Volatility charts.
- **Banner rebranded** ("Volatility-Only | Standard Mode"); `APP_VERSION` → 26.33. Deploy gate passed (preset validator PASS, 12 instances synced, fresh `.ex5` newer than source). The v26.32 strategy config on the paper presets is untouched.

## [Regime-gate study round 3 protocol] - 2026-09-04

### Added — scripts/regime_gate_study_v3.py: pre-registered replication protocol for the near-miss separators, triggered by paper data
- **Protocol** (fixed before any paper data exists): bucket edges FROZEN from the v2 calibration artifact (abort rather than re-fit if missing); sample gate ≥150 closed arm-A paper trades over ≥21 days; features attach to ledger trades by pairing OPENs to harness sig_t ≤120s (z/hour recomputed with identical definitions; unmatched counted as signal-drift indicator); criteria R1 mid-z paper gap ≥+0.10R, R2 hour-B1 gap ≥+0.10R, R3 AND-keep economics ≥+0.15R/trade over ≥40% of trades, R4 same-sign agreement on the harness companion sample over the paper window. Verdict: VALIDATED-CANDIDATE (→ EA-input design + dedicated walk-forward + paper A/B, never auto-deploy) or NO GATE. Interim mode reports the in-sample extension when run without paper data.
- **Interim result already informative**: on all 440 harness PB trades (Feb–Sep) both gaps persist (mid-z +0.129, hour +0.212) — but the clean-OOS context (v2 validation folds only, n=90) splits them: **mid-z +0.316 (replicates, stronger than calibration), hour-B1 −0.281 (sign flips — calibration-window luck)**. Expectation for the paper round: the v2 AND-gate likely fails via R2, and the surviving candidate is a z-only gate, which would need its own pre-registered protocol — the v3 artifact preserves the evidence trail for that decision.
- Still gated on the operator reload: no paper ledger exists yet.

## [Weekly report tooling] - 2026-09-04

### Added — scripts/paper_weekly.py: one command for ledger expectancy + watchdog verdict + preset drift
- **[1] Ledger expectancy** — per terminal: n, days, total/mean R (vs the walk-forward tp18 reference +0.105R/trade), WR, $pnl, virtual-equity drawdown, worst streak, exit-reason split; explicitly exploratory below 30 closed trades. Prompts the A/B adjudicator + tick reconciler once n ≥ 30.
- **[2] Watchdog** — reuses demo_watchdog's audit()/paper_audit() verbatim (same checks, same verdict).
- **[3] Preset drift, three layers** — (a) chart-attached inputs (parsed from each terminal's UTF-16 `.chr` profile: the ground truth for what the EA would run with after a reload) vs the magic-matched deployed preset — catches the "preset updated, EA never reloaded" failure mode; (b) repo preset vs deployed Common\Presets copy; (c) terminal .ex5 mtime vs repo source. Also flags banner-version staleness, duplicate magics across charts, and V75 charts with InpLiveExecution=true. Read-only; writes weekly_report_YYYYMMDD.json.
- **First live run caught two real findings**: chart01 runs v26.28-era inputs (InpTpMult 2.4 vs deployed 1.8 — the never-done reload, now machine-verified), and chart04 is a second V75 chart with **InpLiveExecution=true and the same magic 7788075** — on demo it contaminates the experiment (double signals, one magic); migrated to a funded terminal as-is it would trade real money on unvalidated settings. Both flagged with explicit NEXT ACTIONS.

### Added — scripts/reconcile_paper_ticks.py: verifies the live paper engine against the tick-study baseline the first week data exists
- **Purpose** — the fast-fail tick study validated the EA exit ladder offline against 1.5M real broker ticks; this tool checks the LIVE paper engine still matches that reality and catches drift early. Per closed ledger trade, re-simulates the identical ladder (constants imported from study_fastfail_ticks — single source of truth) through real broker ticks from the ledger's own fill, and measures: ladder delta (ledger R − tick R), fill shift vs the fair tick fill (quantifies the InpPaperSpreadMult conservatism), exit-reason agreement (STOP→SL / TARGET→TP), and exit-price sanity (≤3×median spread).
- **Pre-registered verdicts**: KEEP COLLECTING (<7d coverage) / MATCHED (|mean ΔR| ≤ 0.10R, CI covers 0, mechanics pass) / OPTIMISTIC-DRIFT (ledger better than reality — dangerous) / CONSERVATIVE-DRIFT (ledger worse — cert numbers understate live) / REASON- or PRICE-DRIFT (mechanics diverged). Auto-pulls missing tick windows from the broker (pull_v75_ticks.py).
- **Self-tested against the real 1.5M-tick file** with synthetic ledgers in the exact EA wire format: zero-bias → MATCHED (Δ −0.007R, CI[−0.057,+0.041]), +0.25R → OPTIMISTIC-DRIFT, −0.25R → CONSERVATIVE-DRIFT, short window and missing ledger → KEEP COLLECTING. All five verdicts correct; injected +4.0 fill shift recovered exactly.
- **Ledger-format correction found on the way**: ledger epochs are SECONDS (TimeCurrent), not ms. Fixed a latent units bug in scripts/ab_adjudicate.py (pairing tolerance was 25h instead of 90s; days/ETA 1000× off); re-verified pairing at 60s offsets and sane ETA.

## [A/B adjudicator tooling] - 2026-09-04

### Added — scripts/ab_adjudicate.py: pre-registered decision rule for the TP 1.8 vs TP 2.4 paper arms
- Fixes the verdict rule **before** any paper data exists: data gate (≥30 closed trades/arm, with ETA from observed rate), greedy pairing by OPEN epoch within 90s (arms share the signal engine and broker clock), then declare only if P1 |paired t| ≥ 1.0, P2 sign agreement between paired delta and total-R difference, P3 ledger integrity (dangling OPENs, veq discontinuity). Otherwise KEEP COLLECTING / INCONCLUSIVE. Scope note: adjudicates TP only — the veto/depth question was settled by the 210-day walk-forward and must not be resurrected on paper subsamples.
- Self-tested on synthetic ledgers in the exact EA wire format, 5 scenarios (A wins, B wins, tie → INCONCLUSIVE, <30 trades → KEEP COLLECTING with ETA, missing arm → KEEP COLLECTING): PASS. Key validity detail: paired tests need shared per-pair market noise to have power (independent draws are unpairable) — real arms share signals, so this holds live.
- One command the moment data flows: `python scripts/ab_adjudicate.py --a-dir "<terminalA>/MQL5/Files" --b-dir "<terminalB>/MQL5/Files"` → `artifacts/v75_replay/ab_adjudication.json`.

## [VOL75 preset v26.32] - 2026-09-04

### Changed — 210-day walk-forward (26 folds) overturns the August filter conclusions
- **Data** — pulled 210 days of broker M15/H1 (2026-02-06 → 2026-09-04, 20,160 bars; 40-day snapshots preserved as `m15/h1_40d_snapshot_20260904.csv`). Round 3 of scripts/walkforward_v75.py: 26×8-day folds, 5 configs, pre-registered criteria (V1–V6), ~508 trades per config.
- **Result** — the strategy family was never broken: legacy geometry scores **+51.4R (t=1.57)** over 7 months; August (the basis of rounds 1–2) was merely a drawdown stretch. **TP 1.8 alone is the best config: +52.4R, t=1.68, 15/26 folds positive** — the only candidate passing the edge criteria (V1 total>0, V4 beats legacy, V5 median>0, V6 t≥1.5). The v26.29 static stack (EMA-side veto + pb-min 0.60) measures **+18.3R — a ~33R drag** vs legacy on the long sample: curve-fit to August, now **OFF** (`InpPbEmaSideVeto=false`, `InpPullbackMin=0.30` in VOL75_FINAL.set; `InpTpMult=1.8` kept). The family throttle adds nothing over tp18 (+50.4R).
- **Still honest** — every candidate failed the strict 60%-positive-folds bar (58% best). Modest, choppy edge on one instrument/broker/regime-stretch; the paper run remains the final gate before any live capital.
- Note: 4-fold walk-forwards on 5 weeks of data are noise machines. Minimum viable validation from here on: 25+ folds or paper data, never both-datasets-from-August.

## [v26.31 strategy round (harness-only, no EA change)] - 2026-09-04

### Studied — adaptive regime gate: the honest answer is that no causal regime feature separates PB wins from losses
- **Diagnostic** — characterized every walk-forward fold (ATR level/percentile, EMA separation, trend age, |z|, path efficiency): F3 (Aug 17–25) was the *most* trending fold (net +7.2%, highest path efficiency) yet PB's *worst* (−9.07R) — runaway markets don't retrace; churn happens in all measured regimes. Every causal feature split tested put BOTH buckets negative; vetoing "bad-regime" trades would mostly just delete trades (some good).
- **Built anyway, as outcome-adaptation instead** — `certify_v75.py --family-throttle`: when the PB family's last 10 trades sum < −3R, PB-family signals need a probe (every 5th) until the window recovers. Zero fitted regime constants; the gate watches realized expectancy only. Full-period: −8.03R → −4.72R, DD 33.7% → 24.8% (on legacy entries, honest booking).
- **Pre-registered gate round (scripts/walkforward_v75.py round 2, artifact walkforward_v2631_gate.json): NOT VALIDATED.** Throttle-on-legacy: +0.92R total vs legacy +1.36R (G1 ✗ — the legacy book's interleaved strategies blunt it end-to-end), positive folds 1/4 (G2 ✗). gate+stack: +7.35R vs stack +7.06R (G4 ✓, tiny gain), positive folds 1/4 (G5 ✗), worst fold −4.0R (G6 ✗). Conclusion: the static **tp18-only** config remains the only walk-forward-consistent improvement (+5.49R, positive 3/4 folds); throttle helps the full-period metric but not fold-consistency; the deployed v26.29 stack (veto+depth) is carried by F1–F2 luck per round 1. Standing decision unchanged: paper data adjudicates, not these folds.

## [MITEMSHUB AI EA v26.30] - 2026-09-04

### Added — Min-lot risk router: tiny accounts get truth, not silent ruin
- **Why** — at $10 on V75 the broker minimum lot (0.01) risks the *full calibrated* $5.10 ≈ 51% of the account on one trade; the 20% cap then vetoes every signal, and before this version the EA did so **silently** — the operator had no way to know the instrument cannot fit the account.
- **`RunFitRouter()` (init) + OnTick gate** — measures the chart symbol's smallest achievable stop-risk (broker min lot × calibrated tick value at the EA's real stop geometry, `InpRouterScanATR`×ATR): fits the 0.5% plan → good fit; exceeds plan but inside `InpMaxEffectiveRiskPct` → tolerated with loud per-trade risk warning; exceeds the cap → entries refused (`g_fit_ok=false`) and `ScanFitAlternatives()` prints which monitored instruments *do* fit. Auto re-checks when equity grows 50% (a grown account may unlock the symbol). Emits a `fit` telemetry event; both money paths use the v26.25 `CalibTickValue()` identity — the router must not inherit the broker's 100× tick-value lie (raw-broker math falsely "fits" V75 at $0.05/trade).
- **Measured with live broker specs (calibrated)** — at $10 every monitored symbol is refused (cheapest honest fit: Crash 500 ≈ $2.23/min-lot trade → needs ≈ $12); V75 needs ≈ $26. At $50 all ten symbols fit (V75 = 10.2% per trade). Instrument choice cannot be defaulted any more: the EA states the minimum funding for each chart.
- Inputs default ON (`InpFitRouter=true`, `InpRouterScanATR=1.7`), pinned in VOL75_FINAL.set; paper mode untouched.

---

## [MITEMSHUB AI EA v26.29] - 2026-09-04

### Changed — VOL75 strategy: first positive certification (+0.85R, was −30.05R)
- **Why** — cert200 forensics showed PB/MOM+PB's −29R was three stacked causes: (1) the cert harness booked every SL as −1.00R even after break-even had moved the stop (~23.5R accounting artifact, fixed in scripts/certify_v75.py with `--legacy-sl` preserving the old numbers exactly); (2) an asymmetric exit ladder (TP 2.4R vs −1R losses with winners PLOCK-capped ≤0.5R); (3) genuine entry-churn (26/34 losers went ≥0.25R in favor first, then rolled over).
- **Fix (VOL75_FINAL preset)** — `InpTpMult` 2.4 → **1.8**; new input `InpPbEmaSideVeto=true` (veto the pullback leg when the close pierces EMA20 against the trend — the single biggest contributor, −30.05 → −3.17R); `InpPullbackMin` 0.30 → **0.60** (skip shallow chases). End-to-end through the full governor: **$200 → $213.24, +0.85R, WR 50%, max DD 20.2%** (n=56). At the paper scenario ($50): $50 → $52.09, −1.13R vs the old preset's $50 → $19.70.
- **Caveat carried, not buried** — the EMA-side veto showed no separation on the independent 103-trade baseline (−0.62 vs −0.59 R/trade) and TP 1.8 partially contradicts the v26.27 OOS-validated 2.4. This stack is the paper run's candidate, not proven edge; walk-forward validation is the gate before any funded deployment. EA defaults stay OFF (`InpPbEmaSideVeto=false`) so other instruments are unaffected.
- Also — fast-fail reflex (cut stalled trades early, re-enter) was tested and **rejected by the data** on M15 bars (−0.72R vs −0.13R on the filtered stack): BE already rescues the trades the reflex would convert into small losses. A tick-level version can be revisited once the paper ledger has data.
- **Tick-level fast-fail follow-up: still rejected** — scripts/study_fastfail_ticks.py replayed the certified trade sets through 1.5M real broker V75 ticks (data/v75_ticks_cert_window.csv, COPY_TICKS_INFO, real-spread fills; note data/R_75_ticks.csv is a mislabeled non-V75 series, return corr 0.011 — do not reuse). Eight FF arms (giveback G0.3–0.8, stall 45–90m) vs the EA ladder, paired with bootstrap CIs: no arm significantly positive on both sets (best v2629 arm +0.085R/trade CI[−0.12,+0.29]; the one "significant" baseline-arm result +0.088 fails to replicate on v2629 and is the expected 1-in-16 multiple-comparison fluke). Tick-true ladder for v2629 = −1.30R vs −0.18R bar-sim → spread+intra-bar friction ≈ 0.02R/trade, well inside the paper engine's ×1.5 spread conservatism. WR inflation from FF arms (77% vs 48%) is an illusion — expectancy unchanged. The BE+trail ladder already captures what FF would.
- **Walk-forward gate (same day): NOT VALIDATED** — scripts/walkforward_v75.py, 4 scored 8-day folds + tail, 7 pre-registered configs, criteria fixed before running. Totals F1–F4: v2629 +7.06R > legacy +1.36R (C1 ✓), TP-neighbor robustness ✓ (+11.7R combined), but consistency failed: positive in only 2/4 folds (C2 ✗), worst fold −4.29R (C3 ✗), and only the TP ablation beats legacy — the veto's contribution flips sign across folds (C5 ✗). Period effect dominates: every config printed its best numbers in F1 (Aug 1–9) and struggled after. The stack stays the PAPER candidate (zero-cost to test live-data), but funded promotion is now blocked on paper-first evidence, not on this backtest.

## [MITEMSHUB AI EA v26.28] - 2026-09-04

### Added — Real paper trading engine (the stub is gone)
- **Why** — `InpLiveExecution=false` was a stub: it faked a ticket with a timestamp, the ticket was then zeroed by the position-search fallback, and virtual positions were **never managed or closed**. No exits, no learning, no data — useless for validating the system without a demo account.
- **`PaperOpen/PaperManage/PaperClose`** — virtual fill at live bid/ask with a configurable conservatism multiplier (`InpPaperSpreadMult`); the position runs the **exact ManagePosition ladder** (STOP/TARGET/PLOCK/ECUT/TIME/BE/trailing + CB spike exits, same thresholds and reason strings); every close flows through `HandleTradeClose` so the governor, learning tables, cooldown, and pause logic all train on paper trades.
- **Virtual equity** — `InpPaperEquity` (default **50.0**) drives `g_eq` in paper mode, so sizing, the 20% real-risk cap, loss-streak scaling, and compounding all validate the *funded* scenario instead of the real account balance. Paper equity persists across restarts via `MitemshubAI_paper_*.csv` (EQ/OPEN/CLOSE ledger, dangling-position restore).
- **Instrumentation** — `paper_open`/`paper_close` telemetry events + a `PAPER:` dashboard row; the watchdog's [2]/[3] checks now work in paper mode via the `veq` field. Banner prints the paper-mode line at init.

## [MITEMSHUB AI EA v26.27] - 2026-09-04

### Fixed — VOL75_FINAL preset fidelity: TP 2.0 -> 2.4, BandFade disabled for the live-spread regime
- **Why** — the 5-week certification backtest (103 trades, 17.5% WR, -62.6R) exposed two preset/source inconsistencies. The source default `InpTpMult=2.4` is OOS-validated (63-cell scalp sweep, artifacts/scalp_sweep_volatility_75_index.json, all tighter cells OOS-negative) but the preset carried 2.0. BandFade's geometry (~22-unit stops) can never pass the v26.23 spread gate against V75's ~18.5-unit live spread (18% of stop): **100% of BF entries were vetoed live**, and the 8 BF trades in the 5-week replay (stop-capped at 1.5% of price) all lost.
- **Fix** — preset `InpTpMult=2.4`; preset `InpUseBandFade=false` on V75 (kept ON where spreads allow). Certification harness: scripts/certify_v75.py (full governor + v26.26 money layer on real bars). Watchdog for demo accounts: scripts/demo_watchdog.py.

## [MITEMSHUB AI EA v26.26] - 2026-09-03

### Added — Post-entry Risk Sentinel: the broker's fill is now audited, never trusted
- **Why** — the v26.25 incident proved that planned and real risk can diverge silently: every pre-send guard validated the *plan*, and nothing re-measured after the fill. Any broker-side volume normalization, stop adjustment, fill slippage, or spec change would have altered real risk invisibly.
- **`RunRiskSentinel()`** — runs after every confirmed entry (main opener, CB opener, and orphan recovery) and reads the position back as the **broker recorded it** (`POSITION_PRICE_OPEN`, `POSITION_SL`, `POSITION_VOLUME`). Computes real dollar-at-risk with **calibrated** tick values, prints a `RISK AUDIT` line (planned vs actual, with `[broker adjusted]` flag on any divergence), and **adopts the broker geometry** into `g_entry/g_sl/g_orig_risk/g_risk_money` so R-math, exit management, and the learning tables all operate on truth.
- **Breach = fatal, not advisory** — if real risk exceeds `InpMaxEffectiveRiskPct` of equity (the same policy the entry chain enforces), the EA pauses itself, logs a `SENTINEL BREACH`, writes a `sentinel` telemetry event, and force-closes the position. The 2026-09-03 failure mode (57% of equity at stake while every guard passed) is now structurally impossible to repeat silently.

## [MITEMSHUB AI EA v26.25] - 2026-09-03

### Fixed — CRITICAL: position sizing consumed a broker tick value 100x understated on Volatility 75 Index
- **Root cause (evidence, not theory)** — Deriv SVG reports `SYMBOL_TRADE_TICK_VALUE=0.0001` for V75 with `tick_size=0.01`, `contract_size=1.0`, account USD. The true value, measured from the 2026-09-03 closed trade (SELL 0.03, 251.55 pts, +$7.55 = $1.0009 per price-unit per 1.0 lot), is **$1.0009** — the broker number is **100.09x understated**. Sibling symbols (V100, Crash 1000, Boom 1000) are consistent with the identity `tick_value == tick_size * contract_size`; only V75 lies.
- **Impact** — the sizing chain believed the 500-point stop risked $5/lot and sized 0.03–0.04 lots; the *real* risk was **$15.03 (57% of equity)** on the morning trade and **$20.02 (61%)** on the 15:00 signal. Every guardrail (`InpMaxEffectiveRiskPct=20%`, fleet cap, v26.6 micro-fit) validated against the same poisoned number and passed silently. The dashboard's `Risk: 0.50%` was fiction. The user's manual save of the morning trade hid this from the account record.
- **Fix** — new `CalibTickValue(sym)`: when profit currency == account currency, the identity `tick_value == tick_size * contract_size` must hold; if the broker value deviates >5%, the geometry value is used and a loud `TICKVALUE CALIBRATED` line prints. Non-USD-quoted instruments keep the broker value (genuine conversion factor). Wired into **all** consumers: main trade opener, CB opener (which feeds the CB engine's dynamic sizing), detached-close recovery, and fleet-wide open-risk accounting.
- Post-fix behavior on this account: wanted vol for a 500pt stop ≈ 0.0003 lots → min-lot 0.01 clamps to **$5.00 true risk = 14.7% of equity**, and the v26.6 micro-fit then shrinks SL/TP to bring effective risk to ≈1.5% (spread-bound floor). Realistic worst case per trade falls from 57–61% to ~4%.

## [MITEMSHUB AI EA v26.24] - 2026-09-03

### Fixed — Governor bootstrap: fresh installs/migrations can no longer wake up benched
- **State-load hardening (`LoadReviewState`)** — a `STRAT,i` row with `enabled=0` but **zero recorded trades** is now loaded as enabled. The performance review needs ≥ `InpMinTradesToJudge` (15) trades to legitimately disable a strategy, so a zero-trade suppress can only come from a stale/zeroed state file — and under v26.20's `StratEnabledOrProbe` gate it benched the strategy at init (Sep-03 Volatility 75: banner said `Trades=0` yet PB/BO/MOM/MR all showed `(probe n/10)`; every candidate bar was vetoed, the classic legs could never fire, and no probe trade could ever accumulate to earn reinstatement — a permanent deadlock).
- Probe counters for zero-trade strategies are reset so probing restarts from a clean slate.

### Fixed — Cold-start blindness: regime/sigma/GARCH gates are warm on the first bar after a restart
- **`SeedHistoryState()` (new, called from `OnInit`)** — after a restart/migration the EA previously woke up blind: the ATR-percentile history was empty (percentile pinned at the 50 default → the regime classifier could not leave `RANGING` → Pullback/BO-sell sat out every trend), the sigma EMA was unseeded (`exp_ratio ≈ 1.0` → BandFade's `>1.25` expansion gate could not pass), and the GARCH module was cold (telemetry `z` stuck on the legacy-stddev scale for another 50 bars, tagged `[GARCH warmup]`).
- The replay walks the last `max(InpAtrLookback, InpGarchWarmupBars+2)` closed bars oldest→newest through the **same** per-bar feeds as live (`ClassifyRegime`'s ATR append, `GarchFeedBar`, `UpdateSigmaBaseline` EMA with `PerBarSigma`/`ActiveBarSigma` now accepting a shift so historical sigma is measured as-of each replay cursor). One-time init log: `Cold-start catch-up: N bars replayed | ATR hist N | GARCH obs N | sigma EMA X`.
- Short-history charts (< need+2 bars) keep the old gradual warmup. Defensive no-op when state is already warm (state files do not persist these series by design).
- Sep-03 evidence: dashboard showed `Telem: z=-4.02 … [GARCH warmup]`, `ATR%: 50` (pinned), `Regime: RANGING` through a 2,400-point trend day, `exp 1.00x` while price collapsed — all four classic strategies either benched (bug 1) or regime/sigma-starved (bug 2). Zero trades was the product of both, not signal selectivity.

## [MITEMSHUB AI EA v26.15] - 2026-09-01

### Added — Quick-TP tick-fade exit mode (v26.15)
- **`InpCBQuickTP` / `InpCBQuickTPTPMult` (default OFF / 2.5)** — opt-in Quick-TP exit for the tick-fade leg: banks a small fixed target (`N x ATR`) and disables trailing, profit locks, early cut and breakeven on tick-fade positions (exits at TP/SL/time only). The M5 fade path and Volatility-mode management are untouched.
- Backed by `scripts/cb_quick_tp_study.py` (new): EA-order tick-fade replay with a TP × minRR × trail-mode × cooldown × hold sweep over all recorded Boom/Crash 1000 tick sessions, plus an EA-faithful band-fade target/cooldown sweep on the 104-day M5 caches, plus the F1–F4 robustness gate (≥4 trades, no session < −1.5R, ATR ×0.8/×1.2 ≥ 0R, spread ×1.5 ≥ 0R).
- **Study verdict (why the mode ships OFF):** only TP ≥ 3.2×ATR geometries survive the gate; the deployed TP 4.0 trail-ON itself fails F2 (worst session −3.8R, ATR ×1.2 stress +0.8R). Quick-TP's best family (TP 2.5×ATR, trail off, +42.9R base) fails F2 at −2.1R — cutting the target truncates the +10R runners that pay for the stop-outs. Both deployed .set files carry the new keys at OFF; policy table logs `quick-tp`.

## [MITEMSHUB AI EA v25.1] - 2026-08-29

### Overview
Fade-only Crash/Boom mode with optimized parameters from 60-day real-broker sweeps, tick microstructure recorder, fleet risk guard, and removal of live parameter drift.

### Changed — Crash/Boom strategy reoptimized
- **Fade-only by default** — grind gated by `InpCBEnableGrind` (off); EA only trades post-spike fade on Boom/Crash
- Defaults re-optimized from 60-day sweep: spike threshold 3.0→2.8, cooldown 2→1 bars, entry retrace 30%→40%, SL 0.5x→0.4x ATR, TP 1.5x→3.5x ATR, max spike prob 0.65→0.70
- New minimum R:R filter (2.0), spike direction filter, ATR minimum filter, retrace quality window (max 50%)
- Duplicate-bar guard prevents double-processing cooldowns and spike ages
- Spike threshold read from detector instead of calibration profile
- **Removed live parameter drift** — SymbolCalibration no longer mutates fade_depth/tp/threshold from live samples; parameters stable until offline review

### Added — Tick microstructure recorder
- New `TickRecorder.mqh`: buffered CSV writes (every 500 ticks or 60s), daily rotation, degrades to no-op on errors
- Integrated into `OnTick()` (runs first, captures every tick), `OnInit()`, `OnDeinit()`, and dashboard

### Added — Fleet risk guard
- `OpenCBTrade()` now rejects trades if fleet-wide risk exceeds cap
- Safety net for ticket=0 on accepted orders

### New inputs
`InpCBEnableGrind`, `InpCBRequireSpikeDirection`, `InpCBMinATRPoints`, `InpTickRecordEnabled`, `InpTickFlushTicks`, `InpTickFlushSeconds`

### Updated `.set` files
- BOOM1000_CB: TP 1.8→3.2, fade-only, tick recorder on, fleet cap 12→13%, added magic 7788300
- CRASH1000_CB: TP 1.8→3.5, magic→7788300, fade-only, tick recorder on, fleet cap 12→13%

---

## [MITEMSHUB AI EA v22.0] - 2026-08-25

### Fixed — why the live bot was bleeding opportunities (Aug 17 journal: 1W/8L, −19.87, 287 signals blocked)

#### `mql5/MITEMSHUB_AI/MitemshubAI.mq5` (v21.1 → v22.0)
- **Permanent pause latch removed** — after `InpMaxConsecLoss` losses, `g_paused` latched forever (day rollover never reset it): the #1 opportunity killer. Now auto-resets with counters on each session-day rollover.
- **Dead daily-loss halt wired** — `InpMaxDailyLossPct` existed but was never referenced; now freezes new entries at −3% from the day-start equity baseline and resets next session day.
- **Effective-risk guardrail** — broker min-lot on a ~$30 account forced ~25–27% equity risk per trade. New `InpMaxEffectiveRiskPct` (default 30%) hard-caps REAL min-lot risk and skips the trade (with a loud log) instead of silently over-risking; target risk lowered to 0.5%.
- **Momentum demoted** — a lone big candle no longer triggers an entry (`InpMomentumStandalone=false`); this chase-top/chase-bottom behavior produced all eight Aug-17 losses (entries at bb_position 0.0).
- **HIGH_VOL regime no longer a global block** — only legs that self-gate skip it; the new band-fade leg *trades* expansion by design.
- **Band-geometry guard** — sigma-derived stops/targets only apply when the winning direction matches the direction band-fade fired; otherwise classic ATR geometry is used.
- **Regime-TF ladder completed** — M5→M30→H4 mapping fixed (was M5→H4); entry/regime timeframe overrides (`InpEntryTFOverride`, `InpRegimeTFOverride`) let you run M15 execution off an H1 chart.
- Order comments updated to `MITEM_v22.0`; startup banner/dashboard show the new controls.

#### Added
- **Band-fade strategy leg** (port of validated `band_geometry.py` semantics): fade |z_dev| ≥ 2σ extensions only when volatility just expanded (> 1.25× its EMA baseline), stop = 0.10×sigma_h, target = 0.80×sigma_h, per-trade hold horizon in seconds, min-RR and max-stop-% gates. This is the walk-forward-validated edge (PF≈3.02) that was previously trapped in Python-only backtests.

#### Configs (same filenames the controller deploys)
- `MitemshubAI_VOL100_FINAL.set` / `MitemshubAI_VOL75_FINAL.set` regenerated with **complete v22 key coverage** — the old files were written for v15 input names, so MT5 silently dropped them and traded code defaults.

#### Tooling & integrations
- **`scripts/verify_set_inputs.py`** — cross-checks every `.set` key against EA `input` declarations, flags missing critical inputs, and brace-checks the source. Run before any deploy: `python scripts/verify_set_inputs.py mql5/MITEMSHUB_AI/MitemshubAI.mq5 mql5/MITEMSHUB_AI/*.set`.
- **`src/dashboard.py`** — EA-log parser now understands `[v22]` lines (was hard-coded to `[v21.1]`, which would have blinded the dashboard to v22 trades).

#### Telemetry journal (v22.0, 2026-08-25)
- **Per-bar measured values**: `UpdateBandTelemetry()` computes `z_dev`, sigma-expansion ratio (`sigma/sigma_base`) and per-bar sigma once per closed entry-TF bar, BEFORE strategy evaluation — gates and dashboard consume the same numbers the journal records.
- **JSONL journal** `MQL5\Files\MitemshubAI_v22_telemetry.jsonl` with three event types:
  - `sig` — every evaluated bar with a fired leg: action TAKE/SKIP, skip reason (e.g. `mom-demoted-lone-candle`, `score B2/S0 < min 3`), fired legs (`"legs":"MOM-|MR-|BF-"`), buy/sell scores, regime, z, exp, sigma/base, band-geometry flag.
  - `open` — ticket, dir, entry/sl/tp, volume, effective $ risk, legs, regime, timeframe, z, exp.
  - `close` — exit reason/price, R multiple, money P&L, consec-loss count, pause/daily-halt state.
- **Dashboard row 11** shows live `z=… exp=…x sig=… base=…`; StratBandFade now reuses the measured globals instead of recomputing (identical semantics).

#### Strategy Tester validation kit (v22.0, 2026-08-25)
- **`STRATEGY_TESTER_VALIDATION.md`** — exact tester panel settings, 3-pass protocol (raw edge / $30 realism / robustness sweep) and quantitative pass criteria for validating the band-fade leg on Volatility 75 & 100 over 6 months of M15.
- **`MitemshubAI_TESTER_BFONLY_VOL100.set` / `_VOL75.set`** — isolation rigs (band-fade only, breakers neutralized, trailing/BE off) for clean raw-edge measurement; verified against EA inputs. Deploy configs unchanged.

#### Five-symbol parallel profiles (v22.1, 2026-08-25)
- **`MitemshubAI_VOL10_FINAL.set` / `_VOL25_` / `_VOL50_`** — vol-tier-scaled band-fade tunes for low-volatility synthetics: deeper z-entry (2.3/2.2/2.0), nearer targets (0.60/0.70/0.80 σ_h), tighter max-stop-% and risk caps where min-lot finally allows sane sizing. Marked UNVALIDATED — Strategy-Tester Pass-A gates required before sizing up.
- **Unique magic per chart** across all five FINAL sets (`7788010/025/050/075/100` = `77880`+vol tier) so parallel EA instances never cross-attribute positions; V75/V100 re-magicked from the old ad-hoc values — reattach fresh.
- **PRODUCTION_CONFIGS.md** gained the five-symbol matrix plus a venue-name warning: this Deriv terminal has no "Volatility XX Index" symbols — tradable names are SYN-series (SYN75/SYN100 verified in `mt5_collector.DERIV_SYMBOL_MAP`).

#### Pass-A real-data validation of VOL10/25/50 profiles (2026-08-25)
- `backtest_real_history.py` extended: per-profile tuned z/targets, exit-reason tracking, avg band-stop-width %, and explicit promotion-gate verdicts (≥30 tr, PF≥1.30, expR≥+0.15, maxDD≤12R, TIME≤40%).
- **208-day real M15 verdicts**: VOL10 ❌ REJECTED (PF 0.96, expR −0.04 — no edge; spread ≈26% of its 0.013% band stops); VOL25 ⏸ SHELVED (PF 1.44/+0.36R but 27R DD); VOL50 🟡 CONDITIONAL (PF 1.55/+0.46R, 0% TIME exits, DD 16R → risk ≤0.9%). Reference anchors V75/V100 pass all edge gates and trip only the fixed DD line.
- **Gate policy revision** documented: fixed R-drawdown gate replaced by sizing rule (`risk% ≤ tolerance / DD_R`), since every always-on leg exceeds 12R over 7 months.

#### Telemetry-native replay (2026-08-25)
- **`scripts/replay_v22_bandfade.py`** now auto-discovers `MitemshubAI_v22_telemetry.jsonl` (explicit `--telem` → MT5 terminal Files dirs → repo fallbacks). When found, a new **Part T** replaces proxy-based auditing with EXACT EA values: ticket-paired trades (R/$/z/exp/legs/risk), band-fade vs classic-ATR leg performance split, skip-reason histograms (`mom-demoted-lone-candle`, score blocks…), live gate hit-rates (|z|≥2 / expansion>1.25× / both), breaker-state counts, and still-open tickets. `--legacy` forces the old proxy Parts A+B; without telemetry the script behaves exactly as before.

#### Live-terminal ground truth & real-history validation (2026-08-25)
- **`scripts/mt5_probe.py`** — read-only Deriv terminal probe: enumerates all 730 symbols, verifies trade modes/min-lots/tick values, computes per-symbol min-lot risk floors at reference stop sizes, exports real candle history to `artifacts/real_*.csv`.
- **SYN-series claim REVERSED by ground truth**: the terminal DOES expose "Volatility XX Index" display names (FULL-tradeable) and has NO SYNxx symbols. `DERIV_SYMBOL_MAP` now maps R_10…R_100 (+V75/V100) to verified display names; controller aliases simplified to a safety net. Earlier stale comment removed.
- **Min-lot risk floors rewrite the fleet plan**: V75 min lot 0.01 → ~$0.08/trade risk floor (🟢 anchor); V100 $10.39 (42% eq); V25/V10 unviable ($23/$40 = 90%/162%). PRODUCTION_CONFIGS matrix updated — live fleet is V75-first, equity-gated.
- **`scripts/backtest_real_history.py`** — EA-faithful band-fade backtest over 208 days of real broker M5 candles (exported via probe). Result: deployed **z=2.0 wins on ALL tested symbols at M15** (V75 PF 1.57 +0.50R; V100 PF 1.63 +0.52R; V75(1s) PF 1.62); looser z gates from the synthetic sweep do NOT survive real microstructure; H1 loses → M15-only confirmed. Deployed configs validated as-is.
- **`scripts/daily_scoreboard.py --weekly`** — ISO-week rollups plus an explicit promotion verdict (≥20 demo trades, expectancy ≥ +0.15R, positive total, beats old-logic baseline when present) printing PROMOTE CANDIDATE / HOLD ON DEMO with unmet criteria.

#### Band-fade frequency sweep tooling (2026-08-25)
- **`scripts/sweep_bandfade_params.py`** — grid-sweeps `z_entry` × timeframe(M15/M30/H1) × `stop_sigma_mult`(0.10/0.20) through the repo's own EGARCH band-strategy runner (`run_vol_band_backtest`) with risk-halts relaxed to expose raw edge; synthesizes seeded 1-min calibrated series per vol tier (GBM + AR(1) clustering, post-hoc variance-normalized), optional `--ticks-csv` real-data sanity, automatic walk-forward half-split on frontier winners, JSON export.
- **Fixed import-blocking bug**: duplicate `DERIV = "deriv"` enum member in `backtest/synthetic_generator.py` crashed the entire `synthetic_trader.backtest` package under Python 3.14.
- 120-day findings (see artifacts/bandfade_sweep.json): M15 dominates the frequency-profit frontier; `z=1.0/stop=0.10` roughly doubles trade frequency vs the deployed `z=2.0` at modest expectancy cost and passes walk-forward halves on both symbols; stop=0.20 fails outright on R_100. Deployed configs unchanged pending real-broker tester confirmation.

#### Symbol alignment across the stack (2026-08-25 audit)
- **Root cause documented**: the Python engine trades INTERNAL names (`R_75`/`R_100`; every CLI default) and its forward-demo is an OFFLINE tick replay — it never touched MT5. Meanwhile this broker's terminal only exposes SYN-series symbols (`SYN75`/`SYN100` verified), so the controller keyed to "Volatility XX Index" could never find its symbols and silently skipped enablement.
- **`autonomous_controller.py`** now resolves configured symbols through `SYMBOL_ALIASES` (display name → SYN fallback, cached) at all `symbol_info`/`symbol_select` sites including order routing.
- **`mt5_collector.DERIV_SYMBOL_MAP` fixed**: `V75`/`V100` no longer map to Boom/Crash 1000 (different instruments!) but to SYN75/SYN100. `R_10/R_25/R_50` deliberately unmapped until venue names are Market-Watch-verified — unknowns fail loudly by design.
- **Docs de-staled**: attach instructions and Strategy-Tester symbol rows now name SYN-series; legacy `_LIVE.set` rows marked superseded.
- Known leftovers: old one-off forensics/backtest scripts (`backtest_v17_*`, `walk_forward.py`, `v100_forensic.py`) still probe display-name symbols — inert research artifacts, not part of the live loop.

#### Audit completion pass (2026-08-25, session 2)
- **Dead shadow map removed**: `mt5_collector.DERIV_SYMBOL_MAP` was defined twice — a stale SYN/SURGE/DROP/LEAP dict silently overridden by the corrected map below it. Dead dict deleted; single authoritative map remains.
- **PRODUCTION_CONFIGS.md de-staled** (three dangerous leftovers): safety rule #6 demanded ONE shared magic (7788123), contradicting the v22.1 unique-magic fleet design — now mandates per-chart fleet magics; attach instructions still claimed "SYN-series only" — replaced with the verified display-name truth; tiny-account advice recommended V10/V25 — backwards per verified min-lot floors ($40/$22 = 162%/90% of $30 equity) — now points at V75 ($0.08 floor).
- **Dashboard log parser accepts `[v22.x]` tags**: matched literal `[v22]`, which would have missed `[v22.1]`-tagged journal lines (same blindness class the v22 fix targeted).
- **Controller SYMBOLS params aligned to deployed tunes**: z_entry 1.8→2.0, targets →1.20 (V75) / 0.80 (V100), timeframe H1→M15, vol_ratio→1.25 (= InpBandVolExtRatio). Self-optimization suggestions are now comparable to what actually trades.
- **Exposure-guard inputs pinned in all seven sets**: `InpMaxTotalRiskPct=15` + full five-magic fleet CSV on the FINAL profiles; `=100` (neutralized like their other breakers) on the `_TESTER_BFONLY_` rigs. `verify_set_inputs.py` reports zero default-fallback notes.
- **Artifact-clobber footgun fixed**: a `--only` rerun of `backtest_real_history.py` rewrote `bandfade_real_M15.json` with just its own rows, silently erasing every other symbol's results (the recorded V75/V100 M15 cells were lost exactly this way). Output now MERGES by (symbol, tf, z, tgt) — partial reruns update their own cells and keep the rest.
- **Deal comments bumped to `MITEM_v22.1`** for order traceability. Telemetry filename deliberately stays `MitemshubAI_v22_telemetry.jsonl` — replay/scoreboard auto-discovery depends on it; renaming would blind the analytics pipeline. Verified: `daily_scoreboard.py` tag regexes already capture any `[vNN.N]` build tag.

#### Terminal source deployment + AGGRO profiles (2026-08-25)
- **Root cause of "MetaEditor still shows v21.1" found and fixed**: the terminals' `MQL5\Experts\MitemshubAI.mq5` copies were never updated — only the repo had v22.1, so every recompile rebuilt the OLD engine. Deployed the v22.1 source (old file preserved as `MitemshubAI_v21_1_backup_20260825.mq5`) to ALL THREE terminal data folders on this machine, plus all nine current `.set` files into each terminal's Presets and Experts locations.
- **AGGRO max-frequency profiles** `MitemshubAI_VOL100_AGGRO.set` / `_VOL75_AGGRO.set`: z=1.0 (deepest validated gate, ~3× frequency), consec-loss pause 6, cooldown 1 bar, account ceiling 50%. V100's effective-risk cap raised to 45% so its ~$10.39 min-lot floor can trade at $30 equity — documented with the explicit math that ~40%/trade means three losers ≈ −78% of the account.

#### Config de-stale pass: `MitemshubAI_V100_H1.set` (2026-08-25)
- The last `.set` still carrying a v21.1 header was also missing all four v22-critical inputs (`InpBandZEntry/StopSigma/TargetSigma`, `InpMaxEffectiveRiskPct`) and pinned the hazardous legacy `InpRiskPerTrade=0.25` (= 25% target risk under fraction semantics that date back to v16). Regenerated with full v22.1 coverage: band-fade V100 tune (z=2.0 / stop 0.10σ / target 0.80σ), momentum-standalone demoted, effective-risk cap 30%, account guard `InpMaxTotalRiskPct=15` with fleet CSV extended by this profile's own magic 7788211 for correct self-accounting. TF overrides intentionally left at CURRENT to preserve the file's H1 identity. `verify_set_inputs.py` now PASSES it. Remaining stale `.set` families (PAPER_TEST, SYN TIER/LIVE ×8, V6/V16–V20 archaeology) are superseded research artifacts per PRODUCTION_CONFIGS.md — do not load them on v22.x.

#### Daily scoreboard (v22.0, 2026-08-25)
- **`scripts/daily_scoreboard.py`** — accumulating daily comparison of v22 demo results vs old-logic baselines. Sources combine when present: v22 telemetry JSONL (trades, R/$, exit split, band share, avg entry-z; plus decision analytics — TAKE/SKIP counts and lone-momentum chase-entries avoided, reported as counts only, never invented P&L), MT5 Experts logs (true parallel-shadow per build tag `[v22]`/`[v21.1]`/`[v16.5]`), and Python-engine journals (`--engine-glob`) as historical baseline. `--selftest` verifies the pipeline on synthetic events; `--json` exports the summary.

### ⚠️ Deploy note
The terminal previously ran an unknown build printing "v10 starting" that matches nothing in this repo. **Recompile `MitemshubAI.mq5` v22.0 in MetaEditor, attach it fresh with the regenerated `.set` file, and verify the chart prints `[v22] ... started`.** Until then, what trades live is not what's in this repo.

---

## [0.1.0] - 2026-07-25

### Added

#### Infrastructure & Deployment
- **Terraform templates** for AWS EC2 deployment (Windows Server 2022)
- Application Load Balancer with HTTP listener
- Security groups: RDP restricted to admin IP, web traffic through ALB
- Auto-start on boot via PM2 + Windows Scheduled Task
- Chocolatey-based provisioning: Node.js 20, Python 3.10, Git, PM2

#### Operator Dashboard (Next.js 15)
- **Trade Plan Panel** — Real-time trade recommendations with entry/invalidation/target levels
- **AI Market Intelligence** — Regime analysis, bias scoring, market thesis
- **Multi-Timeframe Alignment** — Visual alignment matrix across 4H→1H→15M→5M
- **Bullish vs Bearish Evidence** — Ranked evidence with strength bars
- **Current Market Thesis** — AI-generated thesis with confidence and invalidation
- **Health Dashboard** — System health monitoring, MT5 diagnostics, bridge status
- **Trade History** — Complete trade journal with outcomes and performance metrics
- **Mobile-First Design** — Responsive layout with bottom navigation
- **Dark Mode** — Full dark theme support with proper contrast ratios
- **Haptic Feedback** — Tactile feedback for mobile interactions (`src/components/ui/haptic.ts`)
- **Pull-to-Refresh** — Swipe down to refresh market data on mobile
- **Loading Skeletons** — Shimmer states for MultiTimeframe, Evidence, and MarketThesis panels
- **Intel Accordion** — Collapsible intelligence panels with smooth animations

#### Python Trading Engine
- **Missing live-watch functions restored** — `run_live_watch`, `render_live_snapshot_text`, `render_live_watch_alert_text`, `build_live_watch_review_snapshot`, `render_live_watch_review_text`, `build_watch_alert_from_prepared_state`, `_append_journal`
- **Bucket-based cooldown** — `DEFAULT_CONTEXT_ALERT_COOLDOWN=2` for context update suppression
- **StopIteration handling** — Clean exit when snapshot source is exhausted
- **MT5 price sanity check** — Alerts when CSV tick prices deviate from expected ranges
- **build_watch_alert** — Added `why` field from briefing for better explainability

#### Documentation
- **Comprehensive README.md** — Architecture diagrams, quickstart guide, CLI commands, deployment docs
- **CHANGELOG.md** — This file
- **Architecture diagrams** — ASCII art showing full system flow

### Fixed
- **Missing Python functions** that caused import errors breaking the Python engine bridge
- **Cooldown mechanism** — Restored bucket-based countdown (was incorrectly using 120-second epoch-based)
- **Dark mode command-rail** — Fixed washed-out appearance with proper dark theme CSS overrides
- **StopIteration in run_live_watch** — Previously fell into reconnect handler, creating spurious journal entries
- **build_decision_summary** — Now falls back to `briefing` when `why` is not present

### Changed
- **Merged feature/mt5-rollout-enablement into main** — All development consolidated into production branch
- **Updated .env.example** — `SYNTHETIC_ENGINE_MAX_LIVE_TICKS=5` → `15`
- **README overhaul** — Complete rewrite with architecture, features, CLI, and deployment documentation

---

## Previous Phases

### Phase 4 — AI Evolution & Self-Improving Intelligence
See [docs/PHASE4_SUMMARY.md](docs/PHASE4_SUMMARY.md)
- FeatureSelector, ModelCalibrator, ConfidenceScorer
- EnsembleModel, ModelMonitor, FeatureImportanceReport
- 13 new tests, experiment tracking framework

### Phase 3 — Core Intelligence Engine
See [docs/PHASE3_SUMMARY.md](docs/PHASE3_SUMMARY.md)
- 4-timeframe hierarchy with confluence scoring
- Continuous background scanner
- Call lifecycle management (forming→actionable→confirmed→failing→cancelled)
- Hurst exponent, entropy, volatility clustering
- FVG detection, internal BOS, equal highs/lows, liquidity sweeps
- Regime detection with persistence
- 8-component decision fusion
- Confidence calibration (isotonic + Platt)
- Explainability engine

### Phase 1–2 — Foundation
- Market data ingestion and candle construction
- Online logistic regression model
- Paper execution and journaling
- Walk-forward validation
- Risk engine with position sizing and drawdown limits
