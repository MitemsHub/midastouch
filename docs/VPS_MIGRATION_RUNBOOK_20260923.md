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
