# VPS MIGRATION RUNBOOK — moving the arm without breaking its record

Written 2026-09-23, the day the local host measured its own failure: a **186-minute
supervision gap** (15:28→18:35Z) caused by the laptop entering Modern Standby and
hibernating ("Sleep Reason: Hibernate from Sleep — Standby Battery Budget Exceeded",
Kernel-Power event 42, 16:51:58Z) while a live position was open. A VPS has no lid, no
battery budget, no user session to lose — that is the whole reason to move. Source
analysis: `docs/UNATTENDED_OPERATION_20260922.md`.

**The one rule that outranks every step below: exactly one terminal may hold the
account at a time.** Two terminals logged into the same account both run the EA and
both send orders — that is double execution, not redundancy.

---

## 0. Preconditions (measure, don't assume)

| check | command | must show |
|---|---|---|
| repo state | `git log --oneline -1` | a commit at or after the one this runbook shipped with |
| suite green on the new host | `python -m pytest tests -q` | all pass (no `.venv` needed; system python) |
| arming record present | `python -c "import json;print(json.load(open('artifacts/live/armed.json'))['tag'])"` | `U25` |
| local terminal STOPPED before the VPS terminal starts | see step 4 | — |

## 0b. The MetaTrader built-in VPS path (the one already rented)

The operator subscribed to MetaQuotes' managed VPS on 2026-09-23 (subscription 6911490,
VPS Germany 01) and clicked Migrate the same day — and the VPS received **nothing**:
`6911490: 0 charts of 1 prepared to synchronize / nothing to synchronize, no any EA`.
Measured cause: the arm's EA chart exists only as a startup-INI attachment inside the
running process; no saved profile carries it (forced exits never save a profile), and
MT5 migrates the **saved profile's** charts only — the journal's `0 charts of 1` was
the Default profile's single bare chart, and a startup-INI chart is invisible to the
migration even while its EA is live (`charts without Expert Advisors are ignored`,
metatrader5.com). The VPS idled at `0 charts, 0 EAs` all day while the laptop traded
and, during the hibernation gap, while nothing covered it.

`scripts/midas_vps_migration.py` now gates and verifies this path (17 pinned tests):

```bash
python scripts/midas_vps_migration.py preflight --plan paper-rehearsal   # prove the environment, stay live locally
python scripts/midas_vps_migration.py preflight --plan full-cutover      # the real handover
# operator clicks Migrate in the VPS tab — only after a preflight PASS
python scripts/midas_vps_migration.py verify-after --plan <plan>         # reads the journal, fails closed
python scripts/midas_vps_migration.py mark-era --why "full cutover <date>"  # watchdog/morning-report era marker
python scripts/midas_vps_migration.py clear-era                          # when the surface comes home
```

* **paper-rehearsal** migrates a second chart running the dedicated rehearsal pin
  (`MidastouchAI_VPS_gold.set` — the paper preset with only `InpArmTag=VPS` changed),
  proving the carrier-chart fix end-to-end while the laptop EA stays the only live
  trader and the rehearsal cannot touch the book (paper execution, own tag, own ledger).
  Operator steps: drag the EA onto a new XAUUSD,H1 chart, load the VPS preset, then
  **File → Profiles → Save** (the migration reads saved profiles, not open windows).
* **full-cutover** migrates the LIVE EA chart itself. MT5 then disables local algo
  trading automatically — its own double-execution guard — and `verify-after` FAILS if
  that guard line did not appear (a missing guard means a live EA may exist on BOTH
  sides). The local LV ledger going stale is EXPECTED in this era (the 2026-09-18
  precedent); the local supervisor keeps supervising what it can see and stands down
  restart remediation (midas_watchdog.vps_hosting_active). Operator steps: close the
  bare charts, **File → Profiles → Save** so the profile carries the live EA chart,
  move `midas_attach.ini` aside in the same session, preflight, Migrate (All),
  verify-after, mark-era.
* The startup-INI conflict is a preflight blocker on full-cutover: once a profile
  carries the live EA, `midas_attach.ini` would boot a SECOND live EA next to it on
  every local restart — move the ini aside in the same session as the migration.
* What this VPS type can never do: run the python evidence layer. The census, parity,
  coverage and watchdog stay on the laptop (or a future Windows VPS) reading whatever
  ledgers remain visible to them; the EA on the MetaTrader VPS trades unmonitored by
  anything but MT5 itself. That trade-off is the operator's to accept knowingly.

## 1. Provision the VPS

* Windows Server 2019+ (the MT5 GUI and the watchdog's stop-and-relaunch need a desktop
  session stack), ≥2 vCPU, ≥4 GB RAM, ≥40 GB disk.
* Note the timezone — irrelevant: every measurement in this program is UTC-stamped.
* RDP access for the operator; **do not leave an RDP session's logon as a dependency**
  (that is the laptop's disease; the S4U task exists so nothing needs a signed-in user).

## 2. Install the software

```bash
git clone <repo-url> && cd MIDASTOUCH          # same repo, same tests, same contract
winget install Python.Python.3                 # or the installer; `python --version`
# MetaTrader 5 from the broker; do not log in yet.
```

## 3. Move the terminal's data folder (the record travels here)

The ledger, census, tally and first-fill packet live **inside the terminal's data
folder**, not the repo:

```
%APPDATA%\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\
```

On the LOCAL host (terminal stopped):

```bash
tasklist //FI "IMAGENAME eq terminal64.exe"     # must print: no tasks
robocopy "%APPDATA%\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" ^
  "<VPS path>%APPDATA%\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075" //E
```

Also copy the attach config (it names the repo's preset by absolute path — re-point it):

```
<D0E8209F...>\Config\midas_attach.ini           # edit StartUpPath to the VPS repo path
```

Continuity proof after the move: `morning_status.py` must show `veq 25012.80 (start
25000.00)`, `fills: 4 ledger fill(s) reconciled against 4 account identifier(s)`, and
the same census counters. A ledger that restarts from zero is a broken migration.

## 4. Cutover (the order is the safety mechanism)

```bash
# LOCAL:
python scripts/midas_watchdog.py --pause        # local supervisor stands down
taskkill //IM terminal64.exe //F                 # local terminal releases the account
# VPS:
terminal64.exe /config:<path>\midas_attach.ini   # first start, attach chart + preset
```

Verify before anything else — the EA's own init banner must read:

```
MIDASTOUCH v1.29 | mode=1 | REVERSE_DIRECTION | execution LIVE
spreadcap=2.5%stop ... census restored, tally N/30
```

`census restored` and the tally are the migration's acceptance line: the EA adopted the
travelled record. Then `python scripts/morning_status.py` — ledger age fresh, veq
continuous, no PROBLEM lines except the expected host-move notes.

## 5. Register the supervisor (the VPS's whole point)

```powershell
# elevated PowerShell on the VPS
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_paper_task.ps1 -Apply
Start-ScheduledTask -TaskName "MIDASTOUCH Arm Supervisor"    # force one pass NOW
```

Then check `artifacts/live/supervision_heartbeat.jsonl` for a fresh line **and** prove
the one unverified leg from the laptop: an S4U task driving the watchdog's
stop-and-relaunch of `terminal64.exe`. On the VPS, measure it deliberately — one
watchdog-initiated restart with the pass completing is the evidence.

## 6. The five gates (all must hold before decommissioning the laptop)

| # | gate | command | pass condition |
|---|---|---|---|
| 1 | task runs unattended | `python scripts/unattended.py "MIDASTOUCH Arm Supervisor"` | `PASS` (S4U, boot trigger, wake-to-run) |
| 2 | host never sleeps | `python scripts/host_power.py` | `PASS` — on a VPS expect no standby states at all |
| 3 | one measured night | `python scripts/live_coverage.py` | `PASS` over 22:00→08:00Z, alarm empty |
| 4 | readiness | `python scripts/live_readiness.py` | `READY` |
| 5 | engine identity | `python scripts/midas_parity.py` (or the tick reconciliation) | parity holds on the VPS host |

Gate 3 needs a real night on the VPS. Until it passes, the laptop remains the fallback —
which is why hibernation was disabled on the laptop too (2026-09-23, `powercfg /hibernate
off`, measured: Hibernate absent from `powercfg -a`).

## 7. Record the move

A host change is not a strategy change — `armed.json` still names the same preset and
arms nothing by itself. Append one dated amendment noting the host move and the gate
results; the record should be able to answer "which machine was the arm on, and when".

## 8. Decommission (only after all five gates hold)

```bash
# LOCAL:
python scripts/midas_watchdog.py --resume
powershell -NoProfile -File scripts\install_paper_task.ps1 -Unregister   # local tasks off
# leave terminal64.exe stopped locally; the repo stays as the development checkout
```

## Rollback

Any gate failing on the VPS: stop the VPS terminal, `--resume` the local watchdog,
start the local terminal, and the arm is home with its record intact (the ledger was
copied, not moved). Fix the VPS gate, repeat from step 4.
