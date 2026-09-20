# Reading MIDASTOUCH's health yourself

One account, one terminal, three surfaces — in the order you should check them.

```
account     1428765   @ Upcomers-Server (Upcomers Ltd.)
book        $25,000 Thunderbolt Classic evaluation
instrument  XAUUSD, M15 trigger / H1 regime
arm         MidastouchAI, magic 7825001, InpArmTag=U25
repo        C:\Users\USER\Desktop\Projects\MIDASTOUCH
python      `python` (3.14.6 on this machine) — **this checkout has no `.venv`**;
            the predecessor checkout has one, and borrowing it puts *that*
            project's `src/` on the import path (see `tests/test_local_imports.py`).
            If a repo-local `.venv` is ever created, every command below may
            switch to its interpreter, and `tests/test_operator_docs.py` will
            start requiring that path to exist — the pin follows reality, so the
            documents cannot drift ahead of it.
```

**The standing truth, read this before anything below.** Nothing is armed:
`InpLiveExecution=false` in every preset, and no gold signal has passed the
walk-forward gate. Arming is an **arming-record event** — a file the tooling
writes when a validated configuration exists — never an input edit. If you ever
see `LIVE` on a chart while `artifacts\live\armed.json` is absent, that is an
incident, not a milestone.

The retired programs (the Deriv synthetic-indices arms, the V75/XAUUSDmicro gold
era, the VPS live arm) are history. Their terminals, ledgers and presets are
gone on purpose. Do not look for them, and do not let anything point at the old
`Synthetic Indices Bot` project folder — that is a different repository.

---

## 0. The one-command check (start here)

```
cd C:\Users\USER\Desktop\Projects\MIDASTOUCH
python scripts\live_readiness.py
```

This is the go/no-go. Every line is **measured against the running terminal**,
not read from a document, and the exit code is non-zero unless every
precondition holds. A healthy run on a trading day:

```
[PASS] terminal connection                    build 6204 @ C:\Program Files\MetaTrader 5
[PASS] AutoTrading enabled                    allowed
[PASS] terminal connected                     connected
[PASS] account logged in                      1428765 @ Upcomers-Server (Upcomers Ltd.)
[PASS] account matches the registry           terminal 1428765 vs registry 1428765
[PASS] expert trading allowed on the account  allowed
[PASS] XAUUSD available                       Gold vs US Dollar spread 60 pts, min lot 0.01
[PASS] market open (live tick)                <a recent tick>
[OFF ] arming switch                          operator arming file absent — the switch defaults to OFF
```

Read the two legs that are *supposed* to look "off" as the design, not as faults:

| line | what it means | healthy | what bad looks like |
|---|---|---|---|
| `market open (live tick)` | gold trades ~24/5 with a daily break and a weekend close | a tick within the last few minutes | `last tick was N min ago` on a weekday = feed or session problem; on a weekend it is simply closed |
| `arming switch` | the operator arming file `artifacts\live\armed.json` | `OFF` / absent | `ON` while no validation record exists is the failure this leg exists to catch |
| `validation record present` | proof a configuration passed the walk-forward gate | `absent` today | — |
| `scheduled task MitemshubPaperSupervisor` | the paper supervisor must point **inside this repo** | `PASS` | `STALE: the task points at ...\Synthetic Indices Bot\...` = the task survived the project rename and must be re-pointed |

`VERDICT: NOT READY.` with `blocking: market open` on a Sunday is correct
behaviour, not a defect. **Authorisation is a separate leg from machine
readiness**, and the tool says so: readiness can be fixed by configuring
something, authorisation cannot be manufactured.

---

## 1. The status report (what happened, not just what is possible)

```
python scripts\morning_status.py
```

`[3b] MIDASTOUCH` is the section that matters: the gold ledger's age, its
virtual equity, whether the arm is flat, and the closed-trade gate clock. Today
it correctly says `no MIDASTOUCH chart attached - gold arm not running`,
because nothing is attached and nothing is armed. Sections `[1]`-`[3]` are the
**retained inventory of the retired V75 paper A/B** — their magics cannot see
this account's arm, so on a gold-only machine they read empty, and that is
expected rather than a fault — the tool says so itself, and names
`scripts/live_readiness.py` as the gold check.

Gate clock reminder, pre-registered and unchanged:

```
>= 30 closed trades with POSITIVE expectancy
+ tick reconciliation PASS (self-arms at 7 days of ledger)
+ watchdog CERTIFIED
   ->  live authorised at the pre-registered size
```

`0/30` for weeks is *expected*, not broken: the clock only starts at the first
fill, and no fill can happen until a chart is attached to a validated build.

---

## 2. The Experts log (the EA's own voice)

- **In MT5:** Toolbox → **Experts** tab.
- **On disk (survives restarts):** `<terminal data folder>\MQL5\Logs\<YYYYMMDD>.log`,
  UTF-16, one file per day. Read it with
  `python -c "print(open(r'<path>', encoding='utf-16').read())"`.

Every line the gold EA writes is tagged with its version. **The four pins to
eyeball on any boot banner:**

| pin | value it must read | why |
|---|---|---|
| symbol | `XAUUSD (GOLD-OK)` | the account trades the real metal, not a micro or a synthetic |
| mode | `mode=0` | ORIGINAL — the registry's frozen order |
| session | `06-20` | the UTC activity band in the protocol |
| execution | `PAPER` | a live banner here while nothing is armed is an incident |

A healthy boot also prints `FLOOR TABLE XAUUSD:` (the min-lot floor and the
equity it implies) and, on v1.12+, a `CLOCK:` line giving the broker/GMT offset.
**Unhealthy signatures:** `INIT FAILED`, `execution=LIVE` with no arming record,
`ORDER REJECT` / `LIVE FILL`, or a banner whose pins disagree with the table.

Silence for hours is normal — a few signals a day is the design rate. The ledger
mtime is what proves the process is alive, not the journal's chattiness.

---

## 3. The ledger (the evidence stream — ground truth)

`<terminal data folder>\MQL5\Files\MIDASTOUCH_paper_XAUUSD_M1.csv` — plain CSV,
append-only, one line per event:

| row | fields | healthy pattern |
|---|---|---|
| `ERA` | version, epoch, model | once per boot |
| `EQ` | equity | every boot, every heartbeat (~15 min), every close |
| `OPEN` | time,ticket,dir,entry,sl,tp,lots,risk,stop,timeout,tag | followed eventually by a `CLOSE` with the same ticket |
| `CLOSE` | time,ticket,reason,exit,R,pnl,equity | `reason` ∈ SL/TP/TIME |

Two questions it answers:

1. **Is it alive?** The file's *last modified* moves at least every ~15 minutes.
2. **Is it honest?** Every `OPEN` has a matching `CLOSE` (same ticket), except at
   most one trailing `OPEN` which must match the chart HUD. `EQ` changes only on
   `CLOSE` rows.

**Do not touch the ledger.** Never edit, rename or "clean up" it. An empty file
with only `ERA`/`EQ` rows is a deliberate fresh book, not data loss.

---

## 4. The watchdog (the machine that watches while you sleep)

Registered and verified with:

```
powershell -NoProfile -Command "Get-ScheduledTask -TaskName 'MIDAS Watchdog Autostart'"
python scripts\midas_watchdog.py --status
```

Healthy = an event line ending `"action": "NONE"` with `"flat": true` and
`"consecutive_restups": 0`. Its log is `artifacts\midas_watchdog.log`, its state
`artifacts\midas_watchdog_state.json`. Only one loop can ever supervise — it
holds `artifacts\midas_watchdog.lock` for its whole life, and a second launcher
prints "another loop already supervises" and exits.

```
# start it by hand (double-clicking also works):
start_midas_watchdog.bat
# register / remove the logon task (idempotent):
powershell -ExecutionPolicy Bypass -File scripts\register_midas_watchdog_task.ps1
powershell -ExecutionPolicy Bypass -File scripts\register_midas_watchdog_task.ps1 -Unregister
```

Recovery shows as `RESTART → RECOVERED` with the restup counted. **Three
unrecovered restups in a row = stop and investigate.** A stale
`.midas_watchdog_paused` marker is a live trap — it makes the loop skip its
checks, so it is created only for a deliberate tester session and removed by the
same tooling.

---

## 5. The paper supervisor

The scheduled task `MitemshubPaperSupervisor` runs one supervision pass every 20
minutes: `scripts\paper_supervisor.cmd` → `scripts\paper_supervisor.py` →
`scripts\midas_watchdog.py`. Three rules:

- It must point at a path **inside this repo**. `scripts\live_readiness.py`'s
  `scheduled task` leg is the check; if it says `STALE`, re-run
  `powershell -NoProfile -File scripts\install_paper_task.ps1 -Apply` — the
  installer refuses rather than register a task whose wrapper is missing.
  **Measured 2026-09-20:** the wrapper did not exist in this repo, so the
  installer refused and the task kept running the *predecessor* checkout's
  supervisor; the leg read `STALE` on every run and an unattended machine had no
  supervision at all. The wrapper and its module now exist, and
  `tests/test_paper_supervisor.py` fails if they disappear.
- It is **paper-only**: neither the supervisor nor the watchdog contains an
  order-sending path. The wrapper logs to `artifacts\live\supervisor.log` and
  resolves `python` from its own location — never from the predecessor checkout's
  `.venv`, which would put that project's `src/` on the import path.
- One pass per firing, and the **exit code means something**: `0` when the pass
  completed (including `action=NONE`, "no chart attached" — nothing is armed, and a
  task that goes red every 20 minutes is noise), non-zero only when the watchdog's
  own escalation says a human must act (`>= 3` unrecovered restups).

### If this machine is ever replaced by hosting / a VPS

MT5's virtual hosting **locks local algo trading off by design** (a local EA and a
hosted EA would both trade the same hedging account), and the ledger then stops
advancing on this machine while it keeps advancing on the hosting side. The watchdog
models this with an operator-managed marker:

```
artifacts\midas_vps_hosting.json      create it when the migration starts,
                                      delete it when the surface comes back
```

While that marker exists the watchdog reports `action=VPS-HOSTING` and does **no**
local remediation, because "the terminal looks dead" is then the correct reading of a
healthy system. Nothing else here should try to fix a moved surface either — the local
ledgers and `live_readiness.py` describe *this* machine, and their silence about the
hosted one is not evidence that it is down.

**And the standing truth does not change with the machine.** Moving to a VPS does not
arm anything: `InpLiveExecution=false` in every preset, and `armed.json` is absent. A
hosted terminal will run the same **paper** mirror, which is the design until a
walk-forward PASS record exists.

---

## 6. The instrument screen (why XAUUSD, re-measured any time)

```
python scripts\venue_probe.py --out artifacts\upcomers_inventory.json
python scripts\upcomers_cost_rank.py --days 180 --tick-days 3 --stop-mult 1.0 ^
                                     --out artifacts\upcomers_cost_rank.json
```

This is read-only (it reads bars, ticks and specs; it closes nothing). It
re-derives the measured cost-per-R ranking. The decision and the number it
produced are in `docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` — **gold at
0.02473R is the cheapest sizeable instrument on this venue**, and that number
*"is still 92% of the entire edge we can demonstrate"*. Re-run it whenever the
venue, the symbol set or the account size changes.

---

## The one-minute routine

1. `scripts\live_readiness.py` → no `[FAIL]` except `market open` when the
   market is genuinely shut.
2. `scripts\morning_status.py` → `[3b]` shows no gold arm running *and that is
   expected*, because nothing is armed.
3. Nothing else. There is no live arm to babysit and no position to manage.

Everything the program knows how to justify it does; everything else it
refuses. When `live_readiness.py` prints `VERDICT: READY` **and**
`artifacts\live\armed.json` exists, the situation has changed and
`docs\MIDASTOUCH_PROTOCOL.md` takes over.
