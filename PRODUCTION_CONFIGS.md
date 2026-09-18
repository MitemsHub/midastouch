# Production Configurations — MITEMSHUB V75 Macro Engine v26.38

> Last updated: 2026-09-15
> Active EA source: `mql5/MITEMSHUB_AI/MitemshubAI.mq5` (multi-strategy engine hosting the paper A/B arms)
> Scope: **Volatility indices only (V75 deployed)**, Crash/Boom refused and removed (v26.34).

## v26.38 operating contract

The v27.00 narrow-engine restructure was registered but never shipped; the deployed line is the multi-strategy v26.x engine. Its current contract:

- `OnTick()` feeds per-tick subsystems first (tick recorder, fit router, VB-BURST, and — since v26.38 — the paper book's hard-exit monitor), then runs bar-granular evaluation behind the entry-timeframe new-bar guard.
- **v26.38 fill-model parity:** in paper mode, hard SL/TP fill per tick at the resting level (STOP checked before TP), mirroring the broker-side resting orders the live engine sends with its entry orders. Management exits (PLOCK/ECUT/TIME, breakeven, trail) remain bar-granular — they are decisions, not orders.
- Entries flow through the governor (spread gate, conviction throttle, win-rearm), the fleet account guard (paper-aware since v26.37: the instance's own virtual position counts toward the fleet sum), and the min-lot fit router.
- Sizing is risk-based with the broker min-lot floor; the 20% per-instance equity cap refuses or clamps entries that exceed it (the strangulation floor arithmetic of the VSG study lives here).
- Broker tick value is calibrated against `tick_size × contract_size` geometry on every order path.
- `InpLiveExecution=false` is a real paper simulator: virtual equity, virtual fills at live spread ×1.5, verified-append ledger/telemetry writers, no broker orders. `LIVE` presets submit real orders and must not be used before the pre-registered gate adjudicates.

The default `FINAL` preset has `InpLiveExecution=false`. `LIVE` is an explicit opt-in and must not be used before paper validation and binary/chart verification.

## Presets

| File | Execution | Purpose |
|---|---|---|
| `MitemshubAI_VOL75_FINAL.set` | PAPER/OFF | Safe default validation profile |
| `MitemshubAI_VOL75_PAPER.set` | PAPER/OFF | Explicit paper template |
| `MitemshubAI_VOL75_LIVE.set` | LIVE | Explicit opt-in only; same geometry, order submission enabled |

## Verification boundary

`python scripts/verify_go_live_artifacts.py` checks both engines' source contracts (versions must match the `deploy_manifest.txt` pins, which is also what the deploy gate enforces), the v26.38 fill-parity invariant (per-tick hard exits BEFORE the bar guard), the paper-order-safety audit, and the preset intent. It does not prove that MetaTrader has loaded the newest `.ex5` or that a chart's attached inputs match the file. Compile the source, inspect the Experts banner, and verify the chart input `InpLiveExecution` before any live use.

## Historical record

The earlier v26 research notes and the unshipped v27.00 narrow-engine design remain in git history. They are not the implementation contract for the deployed v26.38 line.
