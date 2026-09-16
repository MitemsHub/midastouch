# Changelog

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
