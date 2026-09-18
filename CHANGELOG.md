# Changelog

## [MIDASTOUCH: first-fills audit armed — pre-registered rule compliance for every paper trade from fill #1] - 2026-09-17

- **`scripts/midas_first_fills_audit.py`**: mechanical acceptance audit of
  the live paper ledger, written BEFORE any evidence exists (trade #1 is
  graded exactly like trade #150). Per closed trade, against the frozen
  rules: session window (signal-bar open hour inside 12–16), Friday
  cutoff, stop geometry = 2.0 × bounded SMA-ATR(H1,14) **from the data of
  record** (reusing the engine's own `sma_atr`/`load_bars` so the auditor
  cannot drift from research; 2% feed tolerance; >24 h stale data →
  disclosed UNVERIFIABLE, never a false violation), R-vs-fields math and
  reason sanity (TP ≥ +1.9, SL ≤ −0.95, TIMEOUT in [−1,+2]), virtual-
  equity continuity, OPEN12/CLOSE8 format, and live-order contamination
  of the paper mirror. Exit codes machine-read; `--json` for tooling.
- **Wired into morning_status [3b]**: renders the current era + summary
  line, escalates violations into PROBLEMs (feeds `--strict`); audit
  failure degrades gracefully, never kills status.
- **10 new tests** (synthetic ledgers, one planted violation per check
  class): session, Friday cutoff, stop geometry, unverifiable stop, R
  math, reason sanity, veq continuity, contamination, armed 0-trade
  state, clean pass. Battery: pytest 58/58, sweep selftest PASS.
- Live state verified: v1.09 arm flat, ledger fresh, audit exits 0 in
  the armed state. Note: stop-geometry verification follows the data of
  record — refresh `data/forex/xauusd/` when the audit reports stale.

## [MIDASTOUCH: execution layer certified — EA v1.08/v1.09, REVERSE_TRIGGER §8 path complete, live arm switched to the ship candidate] - 2026-09-17

- **Sandbox-pollution incident root-caused**: a mis-windowed tester pass
  (window inputs zeroed by the pre-fix driver; replay ran over ALL loaded
  history, Aug 2024 → Apr 2026, 524 trades) left a stale PERTICK ledger in
  the agent sandbox; the next compare consumed it and produced a garbage
  verdict. Three permanent fixes:
  - **EA v1.09 EA-enforced window**: BAR parity now REQUIRES
    `InpWindowStart/End` (init fails closed otherwise) and enforces
    `t0 < sig+900 <= t1` in `BarEvaluateSignal` — tester dates/preloaded
    history can no longer leak out-of-window signals.
  - **Honest ERA provenance**: era_name is now the real exec model
    (`bar-model-parity` in BAR passes / `pertick-fills` live); a BAR ledger
    can no longer self-describe as pertick. `--compare` verifies the note
    and aborts on any mismatch; `--run` deletes stale sandbox ledgers.
  - **morning_status [4] removed** (V75 floor-zone scaffolding whose
    module no longer exists in the curated repo) — it printed an import
    error every run; the gold arm's risk reality lives in [3b] + the EA's
    own floor table.
- **REVERSE_TRIGGER @ 12–16 §8 certification COMPLETE (v1.09)**:
  python 159 trades +18.017R vs EA 159 +18.020R — **PARITY PASS, 0
  mismatching rows, max |dR| 0.0005**, regression fingerprint match
  (`artifacts/midas_parity_result_midas_wf_reverse_trigger_ses1216_20260917.json`).
  REVERSE_DIRECTION @ 06–20 re-certified on the same binary: 151/151,
  0 rows, max |dR| 0.0005. Both configs now certified on the shipping build.
- **Simulated-live on v1.09** (real ticks, `--sim`, live order path ON):
  169 market orders, zero paper contamination, exits EXTERNAL 86 /
  TIMEOUT 69 / **FRIDAY-FLAT 13** (weekend gap guard proven for real);
  one position legitimately open at window end.
- **Live order path (v1.08)** completed earlier today: CTrade market
  orders + server-side SL/TP + retries, min-lot floor, guards (session,
  Friday cutoff + force-flat, spread cap 1.5% of stop, stops-level,
  staleness, daily equity breaker), external-close reconciliation via deal
  history; PERTICK paper buy fill corrected to the research fill.
- **Arm-policy switch (§13.4)**: live paper arm now REVERSE_TRIGGER @
  12–16 UTC (the certified ship candidate) — the 30-fill gate clock had
  not started (0 fills), so the switch costs zero evidence; forward paper
  evidence must accrue on the mode we intend to ship. Verified live:
  v1.09 banner mode=2 session=12–16, PAPER, flat, ledger fresh.
- **Protocol Amendment 5** written (§13): execution layer, hardening,
  both certifications, sim proof, arm policy, and the (unchanged)
  pre-registered gates that stand between here and live deployment.
- **Battery**: sweep selftest PASS · pytest 48/48 (era-format test
  updated to assert the honest-provenance contract) · morning status
  green (ledger 0.0–0.2 h, watchdog verified, flat).

## [MIDASTOUCH: watchdog live — EA v1.07 ledger heartbeat + scheduled watchdog; battery-start gotcha root-caused] - 2026-09-17

- **EA v1.07 heartbeat**: paper arm writes an `EQ` row at init and every
  900 s via `OnTimer` — the ledger mtime is now a LIVE liveness signal
  (timer-driven, runs even with the market closed/weekends). Guarded off
  in the tester (`MQL_TESTER`), so parity ledgers stay byte-identical:
  **v1.07 re-certified PARITY PASS, 151/151, max |dR| 0.0005**.
- **`scripts/midas_watchdog.py`** (stdlib-only): detects dead terminal
  (path-exact PID scan) or stale ledger (>2 missed heartbeats) → records
  alert + detail in `scripts/.midas_watchdog_state.json`, relaunches via
  the proven sweep-runner helpers with verification (fresh ledger row
  within 120 s) and a 3/day cap; alert-only when the terminal is up but
  the ledger is stale (never kill a possibly-trading terminal from a
  script). `--status` / `--no-relaunch` modes; exit codes machine-read.
- **Parity-hold coordination**: `midas_parity.py --run` writes
  `scripts/.midas_terminal_hold` (with PID, self-healing if the driver
  dies); the watchdog takes no structural action during certification.
- **Scheduled every 15 min** (task `MidasWatchdog`, current user, no
  admin): first three attempts were silently queued by Windows' default
  **don't-start-on-battery policy** — this laptop runs on battery
  (`Win32_Battery` status 1), exit 0, no logs. Recreated with
  `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`; scheduled-run
  proof: task stamp 08:28:01 → state file written 08:28:04. End-to-end
  relaunch drill earlier: terminal killed → watchdog relaunched → ledger
  verified fresh (1/3 today), task Ready.
- **morning_status [3b] wired**: renders watchdog line (relaunches today,
  last verified relaunch) and surfaces `last_alert` as a PROBLEM that
  feeds `--strict`; ledger staleness tightened to >1 h (heartbeat is
  15 min on v1.07+). 48/48 tests pass. Watchdog runtime files
  gitignored (`scripts/.midas_*`).

## [MIDASTOUCH: Amendment 4 — pre-registered overlap session test run one-shot; first matrix passes (REVERSE_TRIGGER, MACRO_ONLY), mechanism unconfirmed] - 2026-09-17

- **H3 pre-registered then run once** (`docs/MIDASTOUCH_PROTOCOL.md` §12):
  entries restricted to London/NY overlap 12–16 UTC, all 8 modes × 4
  frozen windows, frozen `gates()` scorer untouched + dual money-measure
  G2, integrity precondition (engine@06–20 must reproduce the artifact of
  record) enforced BEFORE any overlap number was computed. OOS look for
  the session family now spent (§12.5) — no further historical session
  tests permitted.
- **Result: 2/8 modes pass the frozen matrix** — REVERSE_TRIGGER (OOS
  n=129, +29.44R, PF 1.679, exp +0.228R, dd 5.48R, G6 4/4) and MACRO_ONLY
  (n=133, +30.90R, PF 1.684, exp +0.232R, dd 5.95R, G6 3/4). SHORT_ONLY
  improved to 3/4 windows but still fails G4. All others NO-SHIP.
- **Honest two-sided record**: the pre-registered mechanism prediction
  (G6 consistency should improve) did NOT hold for the passing modes
  (REVERSE_TRIGGER unchanged 4/4→4/4, MACRO_ONLY deteriorated 4/4→3/4),
  and the §12.6 descriptive cross-check shows frozen full-session trades
  entered during overlap hours performed no better than the rest. The
  pass is a **matrix pass via path-selection in the re-simulation, not a
  confirmed edge** — both facts recorded with the pass.
- **Disposition**: REVERSE_TRIGGER proceeds to §8 EA-build parity
  certification on the overlap config (certification harness exists from
  §11); MACRO_ONLY needs an EA build extension first. Live paper arm
  unchanged (ORIGINAL, 06–20) — no policy change without certification.
- `scripts/midas_sweep.py`: `run_mode` gained default-valued session
  parameters (byte-identical defaults; selftest ALL PASS).
  `scripts/midas_session_test.py`: the one-shot runner (integrity gate,
  re-simulation, frozen scoring, G6 shift table, hour cross-check).
  Artifact: `artifacts/midas_sweep_session_20260917.json`.

## [MIDASTOUCH: outcome-level parity certified — EA v1.06 matches the python engine trade-for-trade] - 2026-09-17

- **Parity root-caused to exactness** (`docs/MIDASTOUCH_PROTOCOL.md`
  Amendment 3): the WF/REVERSE_DIRECTION comparison went from 150-vs-151
  with divergent outcomes to **151/151 identical trades — same entries,
  exits, reasons and prices; 0 mismatching rows; max |dR| 0.0005**
  (artifact `artifacts/midas_parity_result_20260917.json`, tag
  `midas_wf_rd_bar`). Three proven root causes:
  1. per-tick execution cannot mirror a bar-model backtest (mid-bar
     timeouts, live-tick spreads) → the EA gained a **BAR execution model**
     replaying completed bars in python's exact pass order, priced from the
     bar series + the shared recorded-spread series (staged via
     `#property tester_file`);
  2. shift-space **ATR chaining bug** (v1.05): TR chain walked
     newest→oldest but referenced each bar's *newer* neighbor's close —
     stops inflated ~18%, cascading into every divergent outcome incl. one
     lost fill; proven by dumping the EA's actual TR window (bars identical
     to the CSV, manual SMA = python's value exactly);
  3. loop-domain gaps (signals while in position, window gating, past-end
     management) brought to python's exact semantics.
- **`MidastouchAI.mq5` v1.06** (shipped build): BAR model + PERTICK live
  model share all signal math; debug instrumentation removed after use;
  compiles 0 errors / 0 warnings. Parity passes run on the tester's
  1-minute-OHLC model so quiet M15 bars still fire (the BAR model prices
  nothing from ticks).
- **`scripts/midas_parity.py`** rebuilt as the certification driver:
  `--prepare` (fresh python baseline + shared spread file + clean ledger),
  `--run` (stops terminal, tester pass, sandbox paths fixed), `--compare`
  (row-level verdict + optional `--fingerprint` regression guard). The
  v1.06 build is **certification-ready**: any future gate-passing mode
  ships without further EA work. Sweep verdict unchanged: all modes
  NO-SHIP; the live paper arm (M1) continues on v1.06.

## [MIDASTOUCH: gold pivot complete — indices program stopped & archived, gold engine v1.03 paper-live on XAUUSDmicro] - 2026-09-16

- **Program pivot per operator directive**: synthetic indices (V75/V28) work
  stopped — scheduled tasks disabled, all four paper arms flat-checked and
  their charts disarmed across all three terminal installs (backups kept),
  five ledgers archived with checksums. Nothing deleted; archived workspace
  preserved at `../Synthetic Indices Bot/`.
- **Ground-truth probe** (`scripts/deriv_symbol_probe.py`): XAUUSD confirmed
  on the real account (140778269, DerivSVG-Server-03, 1:1000); **cost toll
  0.69% of a typical H1 stop** (vs 5.6% that killed V75-1s). Floor math:
  XAUUSD min-lot risks ~$49.6/trade, but **XAUUSDmicro risks ~$5.0/trade →
  tradeable at the real $50.22 account**. Feed: H1 continuous
  2024-04-10→2026-09-16 (one disclosed 112-day broker hole before that);
  validated history in `data/forex/xauusd/`.
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
- **Gold paper arm LIVE**: XAUUSDmicro M15, MidastouchAI v1.03, paper, $50
  virtual equity mirroring the real account floor. Banner
  `[MIDAS1.03] … symbol=XAUUSDmicro (GOLD-OK) … execution=PAPER`, ledger
  `MIDASTOUCH_paper_XAUUSDmicro_M1.csv` initialized.
- `morning_status.py` section **[3b] MIDASTOUCH GOLD ARM** added (chart
  health, gold-charter check, ledger age/integrity/live/R); 16/16 tests
  pass. Full record: `docs/MIDASTOUCH_CLOSEOUT_20260916.md`.

## [v1.03 — bounded SMA-ATR(14) on both engines; entries at exact parity] - 2026-09-16

- EA ATR switched from Wilder (infinite-memory; diverges from any engine
  with a different history depth) to bounded SMA of True Range over the
  last 14 closed H1 bars — identical computation in python and MQL5.
- Full symmetric re-sweep of all 8 modes under the frozen gates (Amendment
  2): verdict unchanged — all NO-SHIP, gates untouched.
- Parity: entries now align exactly (timestamps + sides); OPEN rows carry
  the ATR + H1 stamp per trade; H1 debug dump at first trade.

## [v1.01/v1.02 — fill-timing + instrumentation] - 2026-09-16

- v1.01: same-bar evaluate-and-fill (signal bar index 1 closes exactly when
  the new bar opens) removes the +1-bar entry skew.
- v1.02: OPEN rows record ATR + H1 bar stamp; OnInit dumps the tester's H1
  series for direct bar-level comparison.
