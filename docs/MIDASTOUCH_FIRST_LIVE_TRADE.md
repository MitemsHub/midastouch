# FIRST LIVE TRADE — review ritual (pre-registered 2026-09-18)

**Status: REGISTERED BEFORE THE FIRST FILL.** The LV ledger carries zero
`LOPEN` rows as of this writing (verified 12:5x UTC). This document pins what
gets checked and recorded when the first one appears, so nothing is
improvised at the moment. Authority: the register's GO-LIVE EXECUTION BLOCK
(operator-authorized live attach, account 140778269, magic 7801601) and the
protocol's §4 pre-registration discipline.

## The row grammar (pinned to the EA writer, not to prose)

The EA v1.16 writer (`MidastouchAI.mq5`, PaperLog calls) owns the shape, and
the python consumers are structurally pinned to the MQ5 format strings by
`tests/test_midas_golive_grammar.py`:

- `LOPEN,epoch,posid,order,deal,dir,entry,sl,tp,lots,risk$,stop,timeout,tag`
  — **14 fields**; `posid` at [2] (the POSITION_IDENTIFIER — the only id the
  live path ever tracks), `dir` at [5] (+1 LONG / −1 SHORT), `tag` is `LV`
  (or `LV_FLOORED` when the R5 min-lot floor engaged).
- `LCLOSE,epoch,posid,reason,exit,R` — **6 fields**; `reason` ∈
  SL/TP/TIMEOUT/FRIDAY/EXTERNAL; carries **R, not $** (realized $ lives on
  the account, R on the rows).

The 2026-09-18 incident this pin exists for: the first python consumers were
written against an imagined 15-field row and would have rendered the first
real fill invisible to [3b] **and** to the watchdog's open-position gate.
All three consumers (morning_status, watchdog, parity harness) were aligned
to the writer-exact shape BEFORE any fill, and the fixtures now parse the MQ5
format strings themselves — a parser/writer divergence fails the suite
instead of a real position.

## Phase A — verification, within minutes of the LOPEN (read-only)

**VPS-hosting-era adaptation (2026-09-18):** while the operator marker
(`artifacts/midas_vps_hosting.json`) exists, the EA runs on the MetaTrader
VPS and the LOPEN row lands in the VPS's ledger copy — the LOCAL ledger is
frozen. Phase A then runs on BROKER evidence only (step 2 — the python API
sees the account's positions wherever the EA executes); steps 1/3/4 run
against the local ledger at era end or on the next sync-back, with the
note "row verified late (VPS era)". [3b] flags the era automatically.

1. **Row integrity**: exactly 14 comma fields, tag `LV`/`LV_FLOORED`, epoch
   plausibly recent, entry/SL/TP mutually consistent (SL below entry for
   LONG, above for SHORT, TP on the 2R side).
2. **Broker cross-check (the R2/R3 invariant on real money)**: via the MT5
   python API — position with magic 7801601 exists on 140778269; `type`
   matches `dir`; `volume` matches `lots`; the position's `sl`/`tp` match the
   row's fields to the point; `price_open` matches `entry` (record any
   slippage at entry in the notes). Save the position JSON.
3. **[3b] sees it**: `LIVE POSITION: LONG/SHORT …` line present (the parser
   is writer-pinned — if [3b] is blind while the ledger row exists, that is
   an INCIDENT, record before anything else).
4. **Watchdog sees it**: `ledger_health` on the LV ledger reports
   `flat: false` with the posid in `open_positions` (a terminal restart over
   this position must be impossible — SKIP-OPEN-POSITION).
5. **Record**: the full LOPEN row verbatim, the broker position JSON, UTC
   timestamp of each check, into the closeout addendum.

## Phase B — while open (monitoring only, zero interference)

- **R5 floor verdict**: row `risk$` (field 10) vs 15% of account equity at
  open — record the percentage. (Expected: ~5–9% at min-lot on the $50 book.)
- **Breaker context**: day key is UTC (`TimeUTCNow`); record remaining
  headroom under the 15% live-arm daily cap.
- **Scheduled exit arithmetic**: `open epoch + timeout field` = the TIME
  exit instant (state it explicitly; 12h by default).
- **Session/Friday context**: fill was inside 06–20 UTC; if a Friday, note
  the 20:00 UTC force-flat precedence.
- **The no-interference rule**: no manual close, no SL/TP edit, no terminal
  restart, no EA parameter change — exits are server-side and engine-owned.
  The watchdog's flat gate enforces the restart part mechanically.

## Phase C — reconciliation at the LCLOSE

1. Parse the LCLOSE: reason, exit price, R. Pair it to the LOPEN by posid.
2. **Broker deal cross-check**: history for `position=posid` — record the
   real exit fill(s), price(s), and realized $; compute entry and exit
   slippage vs the ledger's prices.
3. **Verdict, one of**:
   - `EXPECTED` — reason consistent with price action, |slippage| < 20% of
     the stop distance;
   - `DEGRADED` — slippage ≥ 20% of stop distance (record; watch for a
     second occurrence before drawing conclusions);
   - `MISMATCH` — SL/TP not honored as set, or the position vanished with
     no broker deal to match: INCIDENT, full evidence capture, no trading
     analysis until explained.
4. Record the complete pair + verdict in the closeout addendum; one line in
   the register's GO-LIVE block.

## Phase D — registration

- Closeout addendum (2026-09-18): Phases A–C records verbatim.
- Register GO-LIVE block: one line (first fill epoch, verdict of Phase C).
- Changelog: the first-fill entry.
- **Cert-scheduler interaction (pre-declared)**: if LV holds a position at a
  parity-cert flat window, the harness's gate refuses and the scheduler
  retries later — that is correct behavior, not a failure. The first trade
  may legitimately delay the v1.16 cert; nothing overrides it.

## Pre-commitments (what will NOT happen)

- No EA recompile, redeploy, or parameter change is triggered by the first
  trade — one fill is evidence, not a signal to act.
- No verdict about the strategy is drawn from one trade (§13 needs n).
- Subsequent fills get the automatic monitoring ([3b], watchdog, gates) and
  the same Phase-C reconciliation; only the FIRST fill gets the full
  Phase-A ritual.
- Every deviation from this document gets recorded as a deviation — the
  ritual is pre-registered precisely so honesty is cheap.

## VPS-era adaptation (2026-09-18, registered with the broker monitor)

While the VPS-hosting era lasts (`artifacts/midas_vps_hosting.json` exists),
the LV **ledger** is frozen on the VPS — Phase A's ledger steps (row
integrity, [3b] ledger visibility, watchdog flat gate) are performed on
**broker evidence only**, via the account-evidence monitor:

- `scripts/midas_lv_broker_monitor.py` polls the MT5 API and records
  `artifacts/midas_lv_broker_state.json`: positions and deals filtered to
  magic 7801601, plus account-level balance operations (money movement is
  account evidence, not arm evidence). The monitor NEVER writes the LV
  ledger.
- [3b] renders the snapshot automatically as the `[LV broker view]` block —
  a live position appears there as `LIVE POSITION (broker)`; that line is
  this ritual's Phase-A trigger during the era.
- Phase C reconciliation pairs the broker entry/exit deals by position_id —
  the same EXPECTED/DEGRADED/MISMATCH thresholds apply, with deal-side
  slippage computed from broker fills.
- When the era ends (marker deleted), the ledger-side steps resume as
  written above; the first LOCAL LOPEN after the era still gets Phase A in
  full only if no broker-evidence fill was already reconciled.
