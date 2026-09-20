# Reading the gold arm's health yourself

Three surfaces, in the order you should check them. All paths absolute;
`49E0…` below is always
`C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal\49E0383CD680D7AAEC56888AFA08F49E`
(the one live terminal — the other hashes on disk are dead V75 installs).

---

## 0. The 30-second check (start here every morning)

```
cd C:\Users\USER\Desktop\Projects\Synthetic Indices Bot
.venv\Scripts\python.exe scripts\morning_status.py
```

A **healthy** `[3b]` section looks like this (real output, 2026-09-17):

```
[3b] MIDASTOUCH GOLD ARM (MidastouchAI, paper)
  chart: XAUUSD M15 | tag M1 | terminal 49E0383C
  preset: OK (30 inputs byte-identical to repo .set)
  ledger: MIDASTOUCH_paper_XAUUSD_M1.csv | age 0.1h | veq 50.00 (start 50.00)
  live: flat
  closed: 0/30 - gate clock starts at first fill
  watchdog: 0 consecutive restup(s), 1 lifetime, last restup 2026-09-17T10:42:48+00:00
```

Read it line by line:

| line | healthy | what bad looks like |
|---|---|---|
| `chart:` | chart found, gold symbol, M15 | `no MIDASTOUCH chart attached - gold arm not running` |
| `preset:` | `OK (30 inputs byte-identical to repo .set)` | `preset DRIFT: InpMode=2 (repo pin 0)` — someone touched the chart; **do not hand-fix**, run the splice chain or ask |
| `ledger: … age` | under ~1h (heartbeats every 15 min) | age climbing past 35 min = watchdog territory |
| `veq` | starts at 50.00, moves only on closed trades | veq ≠ (start ± known closed P/L) means someone restarted over a polluted book |
| `live:` | `flat` almost always; a position between entry and exit is fine | `flat` while the chart HUD shows a position = two sources disagree, escalate |
| `live cluster:` | appears only when ≥2 arms hold same-direction positions opened within 15 min (one M15 signal bar) — e.g. day one: `2 arms LONG within 15 min (M1m, M1t)`. Information, not a problem: aggregate exposure is the cluster's SUM (≈2× one arm's risk); the section footer repeats every cluster | — |
| `clock offset: …` | section footer. Reads today's journal for `offset (server-GMT)` lines (MidasOffsetProbe runs) and `CLOCK:` lines (v1.12+ EA banner, refreshed on every attach), persists the latest whole-hour value to `artifacts/midas_clock_offset_state.json`, and compares against the last known offset: a ~1 h move prints a `DST SHIFT` alert (UTC+2 winter / UTC+3 summer is normal for gold brokers), any other move prints `OFFSET CHANGE`. **Re-baseline is automated**: run `python scripts/morning_status.py --verified-offset <N>` to re-set the baseline through the audit chain (two-run confirm); it records `last_offset_verified` with the corroborating method — the state file is never edited by hand. No reading today → last known value with age. Informational: the UTC-based gates are correct by construction; the offset changes how server-stamped provenance must be READ | — |
| `closed:` | `n/30` counting up from the first fill | the clock only starts at the first paper fill — 0/30 for months is *expected*, not broken |
| `watchdog:` | `0 consecutive restup(s)` | ≥1 consecutive restup = the auto-recovery loop is fighting something; read `artifacts\midas_watchdog.log` |

Anything in [3b] that says `PROBLEM` flips the whole report unhealthy —
morning status exits non-zero, so you can also just glance at whether the
run "went red".

**The watchdog's own view** (if you want the machine-readable version):

```
.venv\Scripts\python.exe scripts\midas_watchdog.py --status
```

Healthy = an event line ending `"action": "NONE"` with
`"flat": true` and `"consecutive_restups": 0`.

---

## 1. The Experts log (the EA's voice)

Two ways in — same bytes:

- **In MT5:** Toolbox → **Experts** tab (filter the box with `MIDAS`).
- **On disk (survives terminal restarts):**
  `49E0…\MQL5\Logs\`**`20260917.log`** — one file per day, named `YYYYMMDD.log`.
  It is UTF-16; open it in Notepad. From a terminal:
  `python -c "print(open(r'<path>', encoding='utf-16').read())"`

Every line the gold EA writes is tagged **`[MIDAS1.10]`** (the version —
after today; older lines may say 1.03/1.09, which is history, not drift).

**A healthy boot sequence** (real lines, 14:31 today):

```
[MIDAS1.10]MIDASTOUCH started | mode=0 | symbol=XAUUSD (GOLD-OK) | macro=H4+H1 EMA20
  | trigger=M15 BB(20,2.0)/RSI(14) | SL=2.0xATR(H1) TP=2.0R timeout=720min
  | session=06-20 UTC | spreadcap=1.5%stop | risk=1.00% | execution=PAPER | exec-model=PERTICK
[MIDAS1.10]PAPER ledger flat — nothing to restore
[MIDAS1.10]FLOOR TABLE XAUUSD: stop=44.79 ($44.79) minlot=0.10 risk@minlot=$4.48 equity@1%=$448
[MIDAS1.10]H1 debug dump written (30 bars)
```

The four pins to eyeball on any boot: **mode=0**, **session=06-20**,
**execution=PAPER**, **exec-model=PERTICK**. Anything else on those four =
drift (the watchdog catches this automatically and re-splices; you will see
its remediation lines in the same log).

**What you'll see during the day (all healthy):**

| line | meaning |
|---|---|
| `PAPER ledger flat — nothing to restore` | boot from flat, clean |
| `PAPER restored dangling ticket=…` | reboot mid-trade; the virtual position was adopted — expected after restarts, gone after the next close |
| `PAPER FILL BUY vol=0.10 @… risk=$… (…% vEq)` | a paper trade opened (min-lot risk ≈ $4.48–5.87 on the $50 book is the disclosed geometry) |
| `CLOSE SL/TP/TIME ticket=… R=…` | the trade closed; R lands in the ledger |
| `Trade R: +0.42` | one line per closed trade — THE parity evidence line |
| `STALE feed — bar skipped, no evaluation` | feed hiccup; the arm stood down by design, self-heals |
| nothing for hours | **normal** — a few signals a day is the design rate; silence ≠ death (that's what the ledger mtime proves) |

**Unhealthy signatures:** `INIT FAILED`, `execution=LIVE` in a banner,
`ORDER REJECT`/`LIVE FILL` (live layer must be OFF in paper), or a boot
banner whose four pins disagree with the list above.

---

## 2. The ledger (the evidence stream — ground truth)

`49E0…\MQL5\Files\MIDASTOUCH_paper_XAUUSD_M1.csv` — plain CSV, open
in Notepad/Excel. Current healthy content (a fresh §13 book, mid-heartbeat):

```
ERA,MIDAS1.10,1789651864,pertick-fills
EQ,50.00
EQ,50.00
```

Row grammar — one line per event, append-only:

| row | fields | healthy pattern |
|---|---|---|
| `ERA` | version, epoch, model | one per boot; `pertick-fills` on the live arm |
| `EQ` | equity | every boot + every 15 min heartbeat + every close |
| `OPEN` | time,ticket,dir,entry,sl,tp,lots,risk,stop,timeout,tag (+`_FLOORED`) | followed eventually by a CLOSE with the same ticket |
| `CLOSE` | time,ticket,reason,exit,R,pnl,equity | `reason` ∈ SL/TP/TIME (paper) |

**The two health questions the ledger answers:**

1. **Is it alive?** File's "last modified" moves at least every ~15 minutes
   (heartbeats). Windows: right-click → Properties → "Modified". That mtime
   is the *same signal the watchdog automates* — watching it by hand for a
   day is the fastest way to trust the machine.
2. **Is it honest?** Every `OPEN` has a matching `CLOSE` (same ticket in
   column 3) — except at most one trailing `OPEN`, which must match the
   position the chart HUD shows. Equity (`EQ`) changes only on `CLOSE`
   rows. Any open ticket that never closed *and* isn't on the HUD = a
   dangling book — do not delete rows; call it in.

**Do-not-touch:** never edit, rename, or "clean up" the ledger. Backups on
structural events are made by tooling into
`Desktop\Projects\Synthetic Indices Bot\artifacts\paper_ledgers\` (e.g.
`…pre-v110_20260917_142946.csv` from today's §13 reset). Empty file +
`ERA`/`EQ` rows = a deliberate fresh book, not data loss.

---

## 3. The watchdog (the machine that watches while you sleep)

It starts **itself**: the scheduled task **`MIDAS Watchdog Autostart`**
(registered 2026-09-17) launches `start_midas_watchdog.bat` at your logon —
per-user, interactive, no elevation — so the 10-min loop survives reboots
without anyone remembering it. Before that task existed, a machine restart
left the arms unguarded until you noticed (2026-09-17: ~70 min unguarded
after a restart). Verify it is registered:

```
powershell -NoProfile -Command "Get-ScheduledTask -TaskName 'MIDAS Watchdog Autostart'"
```

Manual start (also fine, e.g. after ending the task): double-click
**`start_midas_watchdog.bat`** in the project root. Only one loop can ever
supervise: the watchdog holds `artifacts\midas_watchdog.lock` for its whole
life (released automatically on exit or crash), and a second launcher —
logon task, double-click, anything — prints "another loop already
supervises" and exits. Registering the task (idempotent re-run) or removing
it (`-Unregister`):

```
powershell -ExecutionPolicy Bypass -File scripts\register_midas_watchdog_task.ps1
powershell -ExecutionPolicy Bypass -File scripts\register_midas_watchdog_task.ps1 -Unregister
```

| artifact | path | healthy |
|---|---|---|
| log | `artifacts\midas_watchdog.log` | periodic `"action": "NONE"` events; `PAUSED` lines only during deliberate parity/tester sessions |
| state | `artifacts\midas_watchdog_state.json` | `consecutive_restups: 0` (lifetime restups may be > 0 — that's history) |

If it ever recovers the arm you'll see the full loop in the log:
`RESTART → RECOVERED` with the restup counted; 3 unrecovered restups in a
row = stop and investigate. The pause discipline for
compile/parity sessions (`--pause` / `--resume`) lives in protocol §12 —
in practice the certified tools set and clear it themselves.

---

## 4. The clock: verifying the broker-vs-UTC offset (do this before the live gate, and after every DST change)

The EA runs **two deliberate clocks** (v1.12). Neither is an accident, and
swapping either for the other breaks something certified:

| clock | used by | why |
|---|---|---|
| **bar epochs** (`iTime` labels) | the session 06–20 and Friday-cutoff gates, both BAR and PERTICK | the python engine classifies these same epochs — this is the parity-frozen frame; converting it to "true UTC" would silently move every researched session statistic |
| **real UTC** (`TimeGMT()` via `UTCNow()`) | daily-loss-breaker day key, Friday force-flat, the live position's 12h timeout | operator guarantees that must mean what they say regardless of the broker's timezone or its DST shifts |

The staleness guard stays on `TimeCurrent()` on purpose (it measures gaps
in the server tick stream, which is exactly the frame it must measure),
and ledger row stamps stay on it as frame-consistent provenance.

**The 3-minute verification** (do it once before the live gate, then after
every DST transition — most gold brokers shift UTC+2↔UTC+3):

1. In MetaTrader: **File → Open Data Folder → MQL5 → Scripts**, copy
   `MidasOffsetProbe.ex5` there if it is not already (it ships in the repo
   under `mql5/MIDASTOUCH/`; drag the `.mq5` into the **Scripts** tree in
   MetaEditor and compile if needed).
2. Drag `MidasOffsetProbe` onto any chart. It prints to the **Experts**
   tab: the server clock (`TimeCurrent`), the MQL5 GMT clock (`TimeGMT`),
   and the derived offset, plus the three operator checks.
3. **CHECK 1 — trust TimeGMT**: open `time.is/UTC`. The probe's `mqlGMT`
   line must match real UTC within ~1 minute. If it does not, **do not
   attach the live preset** — the EA's UTC-based gates would be wrong at
   the machine level; investigate the terminal build first.
4. **CHECK 2 — note the offset**: it is informational (the EA's gates are
   correct whatever it is), but you need it to read server-stamped ledger
   rows next to UTC-scheduled ops (morning status, watchdog clocks).
5. **CHECK 3 — calendar it**: re-run the probe after every DST change.
   A +2→+3 shift is expected; anything else, stop and look.

The EA's own init banner also prints a `CLOCK:` line on every attach —
server, GMT and offset — so a wrong offset is visible in the journal from
day one.

**Automated baseline (2026-09-18).** The offset of record now persists to
`artifacts/midas_clock_offset_state.json` WITH its raw evidence — every
absorbed reading keeps `{offset_min, source, epoch, dir}` in the state's
`readings` chain (capped at 50), and any DST/OFFSET-CHANGE flag writes a
`last_change` record with BOTH legs. A flag is therefore auditable forever
against the exact journal line that produced the baseline, even after MT5
rewrites the day's log. [3b] also carries a **journal-retention guard**: if
today's terminal log is missing while ledgers exist, or the newest ledger
heartbeat is >90 min newer than the log's mtime, it prints
`journal retention:` alerts — that log's offset/banner evidence must be
treated as partial.

**Manual-automation split (learned 2026-09-18).** Launching the terminal
with `MidasOffsetProbe.ex5` as a command-line argument does NOT execute the
script on current MT5 builds (verified: arms boot, zero probe journal
lines). The probe run stays a manual step — step 2 above (drag onto a
chart) is the certified way. The offset baseline itself does not require
it: the v1.12+ banner refreshes the reading on every EA attach, so any
planned terminal restart keeps the baseline fresh once v1.12+ is deployed;
the offset of record is kept fresh by
the audit chain: every attach refreshes the reading (banner on v1.12+ arms),
and a **verified re-baseline** (`--verified-offset N` two-run confirm) is the
permanent resolution path whenever external evidence (live broker tick epochs
vs NTP-checked machine UTC) contradicts a stale baseline — see the resolved
go-live note below.

**VPS hosting era (2026-09-18).** While `artifacts/midas_vps_hosting.json`
exists (operator-set around an MT5 VPS migration — MT5 locks local algo off
by design in that mode), [3b] prints the era banner and exempts the local LV
ledger's staleness, and the watchdog is observe-only (`VPS-HOSTING`): the
LV surface lives on the VPS after the operator's sync, the paper arms keep
collecting locally, and no local restart/remediation makes sense. Delete the
marker when the surface returns to the local terminal — supervision resumes
at full strength on the next cycle.

**LV broker view during the VPS era.**
`scripts/midas_lv_broker_monitor.py` polls the account on a 60 s loop and
[3b] renders its snapshot as the `[LV broker view]` block: equity/balance,
LV positions and deals (magic 7801601), and balance operations flagged as
non-trading money movement (withdrawals/deposits appear there — money that
moves with no LV deal attached is a cash operation, not a trade).A snapshot labeled STALE (>5 min old) means the monitor loop died — restart it with
`python scripts/midas_lv_broker_monitor.py --loop 60`.

**First live fill — where to look.** The moment the LV ledger gains an
`LOPEN` row, [3b] shows `LIVE POSITION: LONG/SHORT …` on the LV block and the
watchdog's flat gate refuses restarts over it; the full pre-registered review
ritual (what gets checked and recorded at each phase, and what will NOT
happen) is `docs/MIDASTOUCH_FIRST_LIVE_TRADE.md`. The row grammar is pinned
to the EA writer by test — if [3b] is ever blind to a row that exists, treat
it as an incident, not a display quirk.

**Live-arm offset note (2026-09-18 go-live) — RESOLVED, externally verified.** The
LIVE arm (LV, v1.16) boot banner read broker offset **+0 h 00 min**, against the
+2 h probe baseline — the audit chain flagged it and [3b] displayed it. Verified
the same morning: live broker **tick epochs vs NTP-checked machine UTC** (machine
−0.32 s from the atomic reference) put the broker server at **UTC+0, real-time** —
the banner was true and the +2 h baseline was the stale side of a genuine
broker-side server change. The baseline was then re-set through the audit chain
(`morning_status.py --verified-offset 0`, two-run confirm) and the state file now
records `last_offset_verified` with the method. **The re-baseline mechanism is
the permanent rule**: an offset jump is always flagged first; it is only resolved
by external evidence, never by editing the state file by hand.

---

## See a drift incident happen — the tabletop drill

You can watch both defense legs work end to end without touching the live
arm:

```
.venv\Scripts\python.exe scripts\midas_drift_drill.py
```

It simulates the 09:57-style incident on a throwaway chart fixture (sandbox
only — stop/relaunch stubbed, real chart byte-verified untouched): phase A
tampered chart vs still-pinned running EA (the two legs disagree — that is
the layering working), phase B the EA reboots drifted (watchdog DRIFT →
stop → re-splice → relaunch, backup kept), phase C recovery (RECOVERED,
counter reset, [3b] back to `preset: OK`).

## The one-minute routine

1. Nothing new after a reboot — the watchdog autostarts at logon. Glance at
   `morning_status.py`'s [3b] watchdog line (or the lock file being held) if
   you want proof it came up.
2. `morning_status.py` → [3b] all green (preset OK, age <1h, flat).
3. Optional glance: chart HUD top-left shows `MIDAS1.10`, vEq 50.00,
   `trades: n/30`, `last:` … and the Experts tab shows today's boot banner
   with the four pins.

That's the whole job. Everything else — drift auto-remediation, stale-ledger
restarts, pause discipline during parity sessions — is the tooling's job,
and §13 turns the ledger into a verdict on the first reading of each month.
