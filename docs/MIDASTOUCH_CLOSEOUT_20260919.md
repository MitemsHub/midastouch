# MIDASTOUCH CLOSEOUT — 2026-09-19 (parked, nothing deleted)

**Operator directive:** stop all processes used by MIDASTOUCH and come back to the
synthetic indices. Decision taken this session: **flatten and disable the live gold
arm on the VPS** (no real-money program keeps running unattended), and **park** the
gold program rather than delete it.

This document is the same shape as `docs/V75_CLOSEOUT_20260916.md` — the indices stop
that this closeout reverses. Nothing was deleted; everything is archived and
restorable.

## What was stopped (all verified this session)

| item | action | verification |
|---|---|---|
| `midas_watchdog.py --loop 600` PID **19396** | stopped (`Stop-Process -Force`) | re-query for `CommandLine -like '*midas*'` returns empty |
| `midas_watchdog.py --loop 600` PID **10264** | stopped | same |
| `cmd.exe` wrapper PID **10708** | stopped | same |
| Scheduled task **`MIDAS Watchdog Autostart`** (enabled, logon trigger) | `register_midas_watchdog_task.ps1 -Unregister` → `UNREGISTERED` | `Get-ScheduledTask` no longer lists it |
| Watchdog loop | paused first via `midas_watchdog.py --pause` | marker **removed again** later the same session — see the note below |
| Gold EA on terminal **49E0**, profile `Default`, charts **01–05** | expert blocks stripped via `scripts/detach_chart_ea.py --match MidastouchAI` | `--scan` now reports *no charts with a known EA attached* |

**Two watchdog loops, not one.** The 09-18 log showed duplicate loops against a single
lock file; both PIDs plus the wrapper were killed. Stopping one would have left the
other polling indefinitely.

**Note — the pause marker was created and then deliberately removed (2026-09-19).**
`--pause` was run as a courtesy before killing the loops, which wrote
`scripts/.midas_watchdog_paused`. That marker is read from its **real path** by every
`wd.check()` in `tests/test_midas_watchdog.py` (only the tests that specifically exercise
pausing monkeypatch it), so leaving it on disk turned **9 of that file's 31 tests red** —
they short-circuited to `action: PAUSED` instead of the `RESTUP` / drift-remediation
behaviour under test. The marker was removed; all 31 pass. With the watchdog retired and
its autostart task unregistered there is nothing left to pause, and a stale marker would be
a live trap for anyone who ever restarted the loop.

**Chart backups** (MT5 profile restored from any of these by a plain file copy):

```
Default/chart0{1..5}.chr.bak_20260919_154556..154559
  (under %APPDATA%\MetaQuotes\Terminal\49E0383CD680D7AAEC56888AFA08F49E\MQL5\Profiles\Charts\)
```

Chart01–04 carried the paper arms `M1 / M1t / M1s / M1m`
(`Experts\MITEMSHUB_AI\MidastouchAI.ex5`); chart05 carried the live arm `LV`
(`Experts\MIDASTOUCH_live\MidastouchAI.ex5`). No EA remains attached anywhere —
including the `MitemshubMT5_B` and `MitemshubMT5_C` installs, which were already clean.

## Ledger / artifact archive (checksummed)

`artifacts/archive/midastouch_closeout_20260919/` — **40 files**, `MANIFEST.json`
carries `bytes`, `lines`, `sha256_16` and the original source path per file:

| group | files | notes |
|---|---|---|
| `terminal_files__MIDASTOUCH_*.csv` | 7 | the 5 arm ledgers + `debug_h1` + `spread_M15` (50,001 rows) |
| `artifacts__midas_*.json/.jsonl/.log` | 33 | parity certificates, sweep results, cert chain, deploy chain, P6 income study, variant research, watchdog log/state, broker state |

Notable preserved evidence:
- `midas_parity_result_20260918_0544.json` — WF certificate PASS, 151/151 keyed, max |dR| 0.0005R
- 4× `midas_parity_matrix_oos_20260918_06{41,42,44,45}.json` — 8/8 registry matrix PASS
- `midas_lv_broker_state.json` — the last broker read: account 140778269, equity **$39.58**, `algo_trading: false`, `positions: []`, one closed trade (−$0.50), one balance op (−$10.14)
- `midas_variant_research_20260918.json` — the 160-config LV trigger-frequency sweep

## ⚠️ OUTSTANDING — operator action on the VPS (cannot be done from this machine)

The live gold surface **migrated to a VPS on 2026-09-18 12:19 UTC**
(`artifacts/midas_vps_hosting.json`, subscription 6898457). This machine has no reach
into it, so the local stop above does **not** stop the live arm.

**Required, in the operator's own session on the VPS:**

1. Open the gold chart and set **`InpLiveExecution=false`** on the LV instance — or
   remove the EA outright (the preferred, unambiguous option).
2. Close any open `XAUUSDmicro` position on account **140778269**.
3. Confirm AutoTrading for the account is **OFF** on the VPS.
4. Report back; only then does the next step apply.

`artifacts/midas_vps_hosting.json` is **deliberately left in place** — plan step 0.4 said
to delete it after the VPS is handled, and deleting the only local record that a remote
surface may still be live would be the exact opposite of failing safe. Delete it *after*
step 3 is confirmed, then re-run `python scripts/morning_status.py` to confirm `[3b]`
reports no gold arm.

Until steps 1–3 are confirmed, treat the gold program as **live and unattended**.

## Standing record (unchanged by this closeout)

- Gold was the program's only real-money exposure: 1 closed trade at **−$0.50**, plus a
  −$10.14 balance operation. Account equity $50.22 → $39.58. **The revival funding plan
  reuses this same ~$39.58** (operator decision, see `docs/SYNTHETIC_REVIVAL_20260919.md`).
- The gold program itself is **preserved in full** in `Desktop/Projects/MIDASTOUCH`
  (origin `MitemsHub/midastouch`): EA source, presets, `midas_*` tooling, certified
  XAUUSD corpus, parity/tester evidence, 25 gold test suites. Nothing in this repo's
  `mql5/MIDASTOUCH/` or `scripts/midas_*` was removed.
- The two synthetic scheduled tasks remain **Disabled** and were not touched by this
  closeout: `MitemshubA2FirstTradeWatch`, `SyntheticIndicesPaperPipeline`. They are
  re-armed by Phase 5 of the revival plan, not here.

## What is running right now

- **Zero** trading processes, local or scheduled. No `terminal64.exe`, no `midas_*`
  python loop, no enabled trading task.
- Two disabled synthetic tasks (by design, above).
- The revived synthetic program is built by `docs/SYNTHETIC_REVIVAL_20260919.md`.
