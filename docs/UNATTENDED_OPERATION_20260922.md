# UNATTENDED OPERATION — the arm's home, measured 2026-09-22

**The complaint, stated as a measurement:** *"The arm only exists ~5 hours a day because
this machine sleeps and the only scheduled supervisor is interactive-logon-only and
paper-scoped."* Every part of that is confirmed below from this machine's own records, and
so is the part that decides what to do about it: **this laptop cannot be certified as the
arm's unattended home**, and the reason is not fixable in software.

Nothing here is a claim about a night that has not happened yet. The pre-registered rule,
the measured BASELINE, and the host verdict are separate sections on purpose.

---

## 1. What was measured (before anything was changed)

### 1a. The supervisor was Ready, and absent for most of a night

`artifacts/live/supervisor.log`, over 2026-09-21 11:32Z → 2026-09-22 13:00Z (26.0 h):

| number | value |
|---|---|
| supervision passes recorded | **55** (78 due at a 20-minute cadence) |
| coverage | **69.7 %** (473.1 minutes unattended beyond one cadence) |
| passes in the 01:00–06:00 UTC hours | **0** |
| gaps over the 40-minute alarm threshold | **4**, longest **282.8 min** |
| passes that began and never completed | **2** (one spanning 05:23:13Z → 07:27:46Z: the host slept *inside* the check) |

The night window alone (22:00Z → 08:00Z), which is what the arm's market needs:

```
passes      : 10 recorded / 30 due at a 20-min cadence
coverage    : 30.8% (415.4 min unattended beyond one cadence)
longest gap : 282.8 min
GAP  68.1 min  2026-09-21T23:32:20Z -> 2026-09-22T00:40:24Z
GAP 282.8 min  2026-09-22T00:40:24Z -> 2026-09-22T05:23:13Z
GAP 124.5 min  2026-09-22T05:23:13Z -> 2026-09-22T07:27:46Z
VERDICT: GAPPED
```

Reproduce it exactly:

```bash
python scripts/live_coverage.py                       # the most recent complete night
python scripts/live_coverage.py --hours 24 --json
```

### 1b. Why: the task's principal, not the wrapper

```
$ python scripts/unattended.py "MitemshubPaperSupervisor"
FAIL MitemshubPaperSupervisor: logon=InteractiveToken runlevel=? triggers=time
     repeats=20.0min wake-to-run=off time-limit=?
  why not: logon type is 'InteractiveToken': an Interactive-principal task runs only
           while a user is signed in, and the arm's market hours are exactly the hours
           nobody is
  why not: no BootTrigger: nothing starts supervision at power-on with nobody signed in
  why not: WakeToRun is off: a sleeping host runs no task, and a task that cannot start
           writes no log line either, so the night reads like a quiet market
```

The wrapper resolved a working interpreter (that leg was fixed on 2026-09-20). The **task
definition** was the defect, and a task's definition is readable without running anything —
which is why it is now a readiness leg rather than a sentence in an installer.

### 1c. And why the host: Modern Standby with wake timers off

```
$ python scripts/host_power.py
  sleep states     : Standby (S0 Low Power Idle) Network Connected | Hibernate | Fast Startup
  sleep after (AC) : 0 s (never)
  hibernate (AC)   : 0 s (never)
  wake timers (AC) : Disable
  lid action (AC)  : not exposed by powercfg
  FAIL: this host CANNOT be certified for unattended supervision:
    - Allow wake timers = Disable on AC: a WakeToRun task cannot wake this host, so a
      scheduled pass during sleep simply does not happen
    - S0 Low Power Idle is the only standby state (no S3): the host suspends on lid close /
      idle independently of the 'Sleep after' timer, and the lid-close action is not exposed
      by powercfg on this build so it cannot even be read here
```

**"Sleep after = never" was already true and did not prevent a 282.8-minute hole.** That is
the finding worth carrying forward: on a Modern-Standby machine the idle timer is not the
thing that puts it to sleep, so checking it (or fixing it) proves nothing. There is also no
S3 for a wake timer to interrupt, and the lid policy cannot even be read on this build.

**Fixed the same hour, and re-measured.** The commands in §3 were applied (no elevation was
actually needed for `powercfg` — measured, all four returned 0), and the posture now reads:

```
  wake timers (AC) : Enable              (was: Disable)
  lid action (AC)  : not exposed by powercfg   (set blind to 0; cannot be read back)
  UNVERIFIED: ... whether a wake timer actually wakes an S0 host - and whether the lid
              policy suspends it at all - is NOT observable from powercfg.
              Promote this to PASS with one measured night, not with a setting
```

So the host verdict moved from **FAIL** (a measured defect with a measured fix) to
**WARN / unverified** (nothing measured is wrong, and the rest is not measurable from
here). It did **not** move to PASS, because nothing in `powercfg` can certify that a wake
timer wakes an S0 host — that is what one measured night is for. Writing PASS here would be
the "looks quiet, so it must be healthy" reading this program keeps paying for.

---

## 2. PRE-REGISTRATION — the rule, frozen before the first post-fix night

Frozen 2026-09-22, **before** any post-fix night exists. A rule written after seeing the
numbers describes the past; this one is meant to be able to fail.

```
A window PASSES iff
  (a) no interval between recorded supervision passes exceeds 40 min, and
  (b) no observed ledger heartbeat age exceeds 35 min.
```

* **40 min = 2 × the registered cadence (20 min).** One late firing is scheduler jitter and
  must never be an incident; two consecutive misses are the machine being absent.
* **35 min = `midas_watchdog.STALE_MIN`**, the watchdog's own staleness tier, so "the arm
  stopped beating" has exactly one definition in this program (`tests/test_live_coverage.py`
  pins the two equal).

`python scripts/live_coverage.py --prereg` prints the rule as data, including what it
**cannot** see:

> a host that is asleep runs nothing, so the gap is only ever *raised* by the first pass
> after the host wakes. The alarm is an after-the-fact record of a night that was not
> covered — the durable channels are `artifacts/live/heartbeat_gap_alarm.json`,
> `alerts.log` and `morning_status [3b]`, not a push notification this program cannot send.

Section 1 is a **BASELINE**, not a test of this rule: it was measured from records written
while the rule did not exist.

### What would retire the rule

A **measured night** — `python scripts/live_coverage.py` returning `PASS` (exit 0) over a
22:00Z → 08:00Z window, with the alarm record empty. That has **not** been observed, and no
coverage claim is written here until it is.

---

## 3. What was built

| file | what it answers |
|---|---|
| `scripts/unattended.py` | *would the task still run at 03:00 with nobody signed in?* Reads the task's own exported XML: LogonType (S4U/Password), a BootTrigger, WakeToRun. Three outcomes — a posture, "not registered", "could not ask" — never collapsed. |
| `scripts/host_power.py` | *can this HOST hold it?* Read-only `powercfg` probes: available sleep states, sleep/hibernate timers, wake timers, lid action. Prints the exact elevated commands that would change it; **never runs them.** |
| `scripts/live_coverage.py` | the heartbeat-gap alarm and the coverage measurement. One append-only pass record (`artifacts/live/supervision_heartbeat.jsonl`), two alarm kinds, and the window rule above. |
| `scripts/paper_supervisor.py` | records one heartbeat per pass (`record_pass`) and exits non-zero on a **new** alarm. A standing alarm does not re-red every pass — a task that goes red every 20 minutes is noise that hides the real alerts. |
| `scripts/install_paper_task.ps1` | registers `MIDASTOUCH Arm Supervisor`: **S4U** principal, **at-startup** trigger, repetition every 20 min, **WakeToRun**, no execution time limit, `IgnoreNew`. Removes the legacy interactive task *after* the replacement is registered. |

Two alarm kinds, because their remedies differ:

* `supervision-gap` — no pass for over 40 min. The machine slept, the task failed, or the
  task was never unattended. Restarting the EA cannot fix it; the schedule can.
* `ledger-heartbeat-gap` — a pass **did** run and the ledger's heartbeat age was over
  35 min. That is the arm, not the supervisor, and the remedy is the watchdog's.

The alarm fires on the real hole, not a synthetic one — feeding `record_pass` the actual
last pass before it (00:40:24Z) and the actual first pass after it (07:27:46Z):

```json
{"episode": "supervision-gap:1790037624", "kind": "supervision-gap",
 "raised_utc": "2026-09-22T07:27:46Z", "gap_min": 407.4,
 "from_utc": "2026-09-22T00:40:24Z", "to_utc": "2026-09-22T07:27:46Z",
 "threshold_min": 40, "cadence_min": 20,
 "detail": "no supervision pass for 407.4 min (…) — nothing was watching the arm for 407.4 min"}
```

and `artifacts/live/alerts.log` gains one line, deduped per episode.

### The four readiness legs (`python scripts/live_readiness.py`)

```
[FAIL] scheduled task target                MIDASTOUCH Arm Supervisor is not registered
[FAIL] supervisor runs unattended           … is not registered: nothing supervises the arm
[FAIL] host can hold supervision overnight  wake timers Disable; S0 Low Power Idle only
[PASS] no unacknowledged heartbeat gap      none outstanding
```

Before 2026-09-22 only the first existed, and it passed while the arm was unguarded for 407
minutes. The second and third **block**: a schedule that only runs when someone is signed in
is not a machine that can trade this strategy, and neither is a host that sleeps through its
own market.

---

### 3a. Two defects the installer itself shipped, and how they were found

Both were caught by *running* it rather than by reading it, and both are worth keeping
because the next person will write the same code:

1. **The cmdlets cannot express `WakeToRun` at all on this build.**
   `New-ScheduledTaskTrigger -Once` has no `-WakeToRun` parameter, and the trigger objects
the ScheduledTasks module returns expose exactly
   `{Enabled, EndBoundary, ExecutionTimeLimit, Id, Repetition, StartBoundary, RandomDelay}`.
   `$trigger.WakeToRun = $true` throws — non-terminatingly — and the first version of the
   installer swallowed that, went on, and printed **"Registered. Current state:"** over a
   task it had never created, followed by `No MSFT_ScheduledTask objects found`. A report
   that lies about the one thing it was run to do is the exact class this change exists to
   remove, so the installer now reads the task back and **refuses to report success** if it
   is not there.
2. **The trigger-level `<WakeToRun>` element is rejected by this scheduler.**
   `The task XML contains an unexpected node. (15,9):WakeToRun`. A real "wake the computer to
   run this task" task carries it in `<Settings>`, which is where it now lives; the section
   order and element shapes mirror what `Export-ScheduledTask` returns on this machine.
   If a scheduler ever refuses it anyway, the installer **falls back to the cmdlet
   registration and says the wake leg is missing** rather than quietly registering a task
   that cannot run at 03:00.

Measured scope of the registration attempt: S4U task registration **does** need an elevated
shell (`Access is denied`, `0x80070005`, unelevated, nothing changed).

**The arm's unattended home is a host with no lid, no S0 idle, and no user session to
lose — a VPS.** That is a statement of requirement, not a claim that a VPS has been
provisioned: this session has no way to buy, create or reach one, and nothing in this
document should be read as saying otherwise.

On this host, applying the new task is a **trade of one known-partial supervision for one
unverified supervision**:

* **Known:** an Interactive-principal task runs in the signed-in desktop session, where
  `midas_watchdog`'s stop-and-relaunch of the MT5 GUI demonstrably works (it did, six times
  on 2026-09-22 by the state file's own count).
* **Unverified:** whether an **S4U** task — non-interactive, per Microsoft's own
  documentation, *even when the user is logged on* — can drive `terminal64.exe`'s relaunch.
  It can certainly read the ledger, the chart and the account; the relaunch is the open
  question, and it is the recovery path for a live-armed arm.

So the honest sequence, on a host that will be used unattended, is:

1. register the task (`-Apply`), then **verify a pass actually happened** with the new
   principal: `Start-ScheduledTask -TaskName "MIDASTOUCH Arm Supervisor"`, then check
   `artifacts/live/supervision_heartbeat.jsonl` for a line with a fresh timestamp;
2. fix the power posture or move to a host that does not need fixing:
   ```
   powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
   powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
   powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE 0
   powercfg -setactive SCHEME_CURRENT
   ```
   (elevated; the operator's act — `host_power.py --fix-commands` prints them);
3. leave the machine awake for one night and read the result:
   `python scripts/live_coverage.py` — `PASS` is the claim, `GAPPED` names the hole.

### What a VPS must satisfy before it is the arm's home

* the terminal runs **without an interactive sign-in** (start it from the same
  at-startup task path, or MT5's own hosting);
* `python scripts/unattended.py` **PASS** on the host's task;
* `python scripts/host_power.py` **PASS** (no lid class, wake timers irrelevant because
  nothing sleeps);
* one measured night of `python scripts/live_coverage.py` **PASS** with an empty alarm;
* `python scripts/live_readiness.py` **READY**, with the arm's authorisation unchanged —
  moving the machine **arms nothing**: `armed.json` is the arming event and it says the same
  thing on any host.

---

## 5. Standing state after this document

* **The arm is armed on the operator's override** and supervised by the legacy
  `MitemshubPaperSupervisor`, still **interactive-logon-only** — the replacement task was
  NOT registered: the elevation prompt was declined, so nothing on the machine changed.
  What changed is that the machine now *measures* its own absence.
* **The coverage record is live.** `artifacts/live/supervision_heartbeat.jsonl` is written
  by the supervisor already running (first line 13:12:20Z: `action=NONE`, `ledger_age_min
  9.8`, `armed=true`), and over an awake window the harness reports
  **9 passes / 9 due, 100.0 % coverage, longest gap 20.0 min, VERDICT PASS**. That is a
  measurement of the cadence, **not** of unattended survival — no night has been measured.
* **This host is not certified for unattended operation**: the wake-timer leg is fixed
  (Enable, measured) and the remaining leg is unfalsifiable from `powercfg` alone (S0 Low
  Power Idle; lid policy unreadable). `live_readiness` reports **NOT READY** with two
  blocking legs — `scheduled task target` and `supervisor runs unattended` — plus the host
  as WARN.
* **The strategy remains unproven, and the arm is not failing for lack of permission to
trade.** Its own census for the UTC day (ledger `NOFILLSUM`) reads **23 bars evaluated, 19
  with no trigger at all, 4 with a trigger the mode refused** — so the binding constraint is
  the trigger's own frequency, not a safety gate, and not the machine during the hours the
  machine is awake. The machine's contribution is the *other* half: the 00:40Z → 07:27Z hole
  covers **04:00Z → 07:27Z of the arm's own 04:00–18:00 UTC session**, i.e. about a quarter
  of every trading day in which the strategy cannot be asked anything at all. Fixing that is
  a machine change (or a VPS); raising the fill rate beyond it is a strategy change, which
  is a pre-registered research question (`quant-validation`) and not a configuration edit.
* The gap alarm is a *record*, not a pager. Nothing in this program can notify anyone while
  the host is asleep; the alarm's job is to make the night legible when someone looks.
