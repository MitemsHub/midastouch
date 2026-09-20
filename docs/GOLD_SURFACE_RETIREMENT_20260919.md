# GOLD SURFACE RETIREMENT — 2026-09-19

**Decision:** the MT5 Virtual-Hosting era marker is **retired**, and the gold VPS surface is
**closed**. Grounds, evidence, and the residual uncertainty are below. Nothing was deleted.

Resolves the open blocker in `docs/PROGRAM_STRUCTURE_DECISION_20260919.md` and completes the
outstanding operator action in `docs/MIDASTOUCH_CLOSEOUT_20260919.md`.

---

## 1. What changed

**Operator statement (2026-09-19):** *"I have uninstalled deriv terminal already, that account
is no longer funded."*

That matters more than the original instruction did, because it removes the thing the marker
existed to protect. The marker's purpose was to stop the local MIDAS watchdog from "repairing"
a surface that had been **deliberately moved** to a VPS — the era's signature being a frozen
local LV ledger, which is not a fault. With the account unfunded, there is nothing left to
protect and nothing left to trade.

**Action taken:** `artifacts/midas_vps_hosting.json` → moved to
`artifacts/archive/gold_surface_retirement_20260919/midas_vps_hosting.json`
(516 bytes, 9 lines, `sha256 d6c8775d38b4efa1…`, original mtime 2026-09-18T13:19Z) with a
`MANIFEST.json`. The live path was cleared.

## 2. Why the live path had to be cleared, not merely annotated

`scripts/midas_watchdog.py`:

```python
def vps_hosting_active() -> bool:
    return os.path.exists(VPS_HOSTING_MARKER)
```

**Existence-based, not content-based.** Writing `"active": false` into the file would have
changed nothing — five consumers (`midas_watchdog.check`, `midas_lv_broker_monitor`,
two `morning_status` sites, and two pinned tests) would still have seen the era as active.

Leaving a marker that asserts an era which no longer exists is the failure mode this
repository already documented once: the MIDASTOUCH closeout records that a stale
`.midas_watchdog_paused` marker *"turned 9 of that file's 31 tests red"* and concluded that
*"a stale marker would be a live trap for anyone who ever restarted the loop."* The same
reasoning applies verbatim here, so the marker was archived and its live path cleared.

**This intentionally flips the watchdog back to normal supervision.** That is now inert: the
watchdog process is not running, its autostart task is unregistered, both synthetic tasks are
`Disabled`, and there are no arms left to supervise. Verified:

* `vps_hosting_active()` → **False** (was True)
* `tests/test_midas_watchdog.py` → **31 passed**
* `scripts/morning_status.py` → `no MIDASTOUCH chart attached - gold arm not running`,
  `no terminal data folder with a V75 chart + arm magic found`, era banner absent

## 3. Evidence gathered this session

| check | result |
|---|---|
| Deriv terminal application | **uninstalled** — no `Program Files/Deriv*`; only `/c/Program Files/MetaTrader 5` (Upcomers) remains |
| Deriv terminal **data** dirs | **still present** — `49E0383C…` (last journal 2026-09-19 17:07) and `71BF6B2A…` (2026-09-16 17:49) |
| Active data dir | `D0E8209F…` (journal 21:01) = the **Upcomers** terminal, PID 15640 — the only one running |
| `midas_*` processes | none |
| MIDAS scheduled task | unregistered |
| Synthetic tasks | both `Disabled` (by design; re-armed by the revival plan, not here) |
| Gold arm artifacts on disk | **intact** — `MidastouchAI.ex5`, the LIVE/parity/compile folders, all 5 paper ledgers (`MIDASTOUCH_paper_XAUUSDmicro_M1/M1m/M1s/M1t/LV.csv`), `MIDASTOUCH_spread_M15.csv`, the gold presets |

**Nothing was lost.** The data directory holds the complete gold arm state, so the program
remains restorable exactly as `MIDASTOUCH_CLOSEOUT_20260919.md` intended.

## 4. Residual uncertainty (stated, not buried)

**We never obtained positive confirmation that the VPS instance was unloaded.** That
confirmation required a human in the VPS session and this machine has no reach into it. What
we have instead is stronger for the purpose that mattered:

* the account behind the surface is **unfunded**, so it cannot place a trade whether or not the
  EA is loaded;
* the local surface no longer exists;
* the watchdog that would act on the marker is retired.

The remaining possibility is a loaded-but-impotent EA on an unfunded account. That is recorded
here as an accepted residual, not as a resolved item.

**Reopen condition:** if account **140778269** is ever re-funded, or any Deriv/MIDASTOUCH
surface is revived, this item reopens and the VPS must be cleared by hand before anything is
armed. The historical evidence is preserved at the archive path above.

## 5. Standing state after this document

* **Gold program: closed**, both surfaces. No live arm, no paper arm, no watchdog, no scheduled
  task. The strategy itself remains **unproven** — `docs/GOLD_WFO_VERDICT_20260919.md`:
  NOT VALIDATED, t = +0.52.
* **Synthetic-indices program: parked**, no armed arms, two disabled tasks.
* **Upcomers program: live and funded** — $25,000 Thunderbolt Classic, terminal PID 15640,
  0 positions, 0 orders. Instrument decision: `XAUUSD` at 0.0247R
  (`docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` §7).
* The next substantive work is **strategy research on a fresh window**, not code restructuring
  — the boundary is set by `docs/PROGRAM_STRUCTURE_DECISION_20260919.md`.
