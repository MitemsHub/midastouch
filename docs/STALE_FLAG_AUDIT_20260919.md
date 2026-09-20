# STALE FLAG AUDIT — 2026-09-19

**Trigger:** after the VPS-hosting marker (`artifacts/midas_vps_hosting.json`) was
retired earlier today (`docs/GOLD_SURFACE_RETIREMENT_20260919.md`), the operator
asked for a sweep: *"any other stale operator-managed markers or safety flags like
the VPS one — files whose mere presence changes behaviour and that may now assert
an era that has ended."*

This is that sweep. It found **one flag still consumed by live code** (retired
below), **one control that reported a false green** (rewritten below), and **one
residual hazard sitting outside the repository** (recorded, deliberately not
touched).

---

## 1. What qualifies

A file makes this list only if all three hold:

1. **Presence, not content, changes behaviour** — the consumer tests
   `os.path.exists()` / `FileIsExist()` / reads the file as state, so a stale copy
   is a live input. Writing `"retired": true` *inside* such a file changes
   nothing; only clearing the path does.
2. **It is operator- or run-managed state**, not derived output. A report that
   nobody reads cannot mislead; a marker that a tool branches on can.
3. **Its subject can have ended** — it can assert a venue, a broker, a mechanism
   or an era that no longer exists.

Deliberately **out of scope:** the ~60 ordinary data-presence checks in `src/`
(`if not csv_path.exists()`, `st_size > 0`, "pick the first non-empty candidate").
Those are correct shape-checks, not era flags: their absence means "no data",
which is the truth.

---

## 2. Findings

| # | flag | mechanism | consumers | on disk 2026-09-19 | asserts | verdict |
|---|---|---|---|---|---|---|
| 1 | `artifacts/midas_clock_offset_state.json` | read as the DST baseline | `morning_status.check_clock_offset` → `print_midas_section` → `midas_drift_drill.py`, `midas_verdict.py` | **was present** | broker offset **+0 h verified against the GOLD broker** (dir `49E0383C`) | **RETIRED this sweep** |
| 2 | `scripts/confirm-gate-open.ps1` | hardcoded terminal dir + `Select-String` | none (unreferenced) | present | "gate OPEN, no cblearn block" | **REWRITTEN fail-closed** |
| 3 | `scripts/.midas_watchdog_paused` | `os.path.exists` gate | `midas_watchdog` (check/`--pause`), `midas_parity`, `deploy_portfolio`, `midas_deploy_v118` | **absent** | "parity/tester session in progress" | keep; **gitignored** now |
| 4 | `artifacts/midas_vps_hosting.json` | `os.path.exists` gate | 5 sites | retired 2026-09-19 (earlier) | "algo lives on the VPS" | already retired |
| 5 | `MitemshubAI_cblearn_*.csv` | learned CB gate state | `confirm-gate-open.ps1`, `reset-cblearn.ps1` | **absent everywhere** | the learned CB spike gate | orphaned; controls annotated |
| 6 | terminal-hash pins in 7 scripts | hardcoded data dir | see §5 | dirs **gone** | which terminal to read | systemic; recorded |
| 7 | `MitemshubAI_state_<symbol>.csv` | `LoadState()` on attach | `MitemshubAI.mq5` | absent in live dir; present ×2 in Deriv-era dirs | per-symbol day counters, streak, equity anchor | keep as evidence; reopen condition §7 |
| 8 | `config/midas_parity.ini` | Strategy Tester launcher | only if terminal launched `/config:` | present (Deriv dir) | run `MidastouchAI` on XAUUSD M15 | keep as record |
| 9 | `artifacts/rollout_armed_r100.json` | **write-only** snapshot | none — the gate is the `--armed-live` CLI flag | present | "armed-live for R_100" | not a flag; filename reads like one |
| 10 | `Common\Files\synth_calls_R_75.json` | **presence = a trade instruction** | `SynthCallExecutor.mq5` | **present, 38 days stale** | a live R_75 buy call | **residual hazard — outside the repo, not touched** |

---

## 3. Retired in this sweep

### 3.1 `artifacts/midas_clock_offset_state.json` — the one with a live consumer

The file held a broker-vs-UTC baseline built entirely from the **gold** era:

```
last_offset_min      : 0        last_source: banner   runs: 9
readings[*].dir      : 49E0383C  (all six — the Deriv/gold terminal)
last_offset_verified : {offset_min: 0, method: "broker-tick-epochs+ntp"}
```

The live Upcomers terminal (`D0E8209F…`) reports **UTC+2**. Because
`check_clock_offset()` *reads* this file, the first Upcomers run would have:

- raised a **false alarm** — `OFFSET CHANGE: broker offset moved +0 h 00 min ->
  +2 h 00 min, not a 1-h DST step — verify before trusting server-stamped rows`
  (a 2 h move is outside the DST branch, so it lands in the "unexplained" one); and
- **silently overwritten** the baseline, while leaving `last_offset_verified`
  claiming *external* NTP/broker-tick verification for a **broker we no longer
  trade**. The hazard is not the number — it is the **label carried across a
  venue change.**

**Action:** archived byte-for-byte to
`artifacts/archive/gold_surface_retirement_20260919/midas_clock_offset_state.json`
(1351 B, `sha256 6413d2fc7332e028…`), live path cleared, MANIFEST updated.
Nothing deleted.

The health guide's rule is that this file is **never hand-edited** —
re-baselining goes through `morning_status.py --verified-offset <N>` (two-run
confirm). Clearing it is therefore not an edit of a baseline but the removal of
a *foreign venue's* baseline: with no state, the first real reading records
itself as the baseline **with its own terminal dir** and raises no alert. Pinned
by `tests/test_midas_clock.py::TestRetiredEraFlag` (3 tests).

### 3.2 `scripts/confirm-gate-open.ps1` — a false green

It hardcoded terminal dir `FB9A56D617EDDDFE29EE54EBEFFE96C1`, which **does not
exist on this machine** (live: `49E0383C`, `71BF6B2A` = Deriv-era; `D0E8209F` =
Upcomers). `Select-String` therefore returned nothing, and the script fell
through to its `else` branch:

```
cblearn: no state files yet (fresh gate, OPEN until first trades)
```

That is a **positive assertion of an OPEN gate**, on a terminal that does not
exist, about a mechanism that was **deleted from the EA** (CHANGELOG: *"Deleted
from the EA: … the learned CB spike gate (EWMA + `MitemshubAI_cblearn`
persistence) …"*). Exactly the VPS-marker failure mode: a safety control
reporting green because it cannot see anything.

**Action:** rewritten to fail closed — it resolves terminal dirs dynamically,
requires today's journal, exits non-zero unless it actually found EA init/gate
evidence, and reports the cblearn leg as **RETIRED**, not OPEN.
`scripts/reset-cblearn.ps1` (dynamic glob, so it failed silently rather than
falsely) keeps its behaviour and gains a retirement note in its header.

---

## 4. Left in place, deliberately

**`scripts/.midas_watchdog_paused` — absent, and now gitignored.** It is the
cleanest of the four markers: presence means *observe only*, i.e. it can only
make the watchdog do **less**, never more. It was not absent by luck — the
MIDASTOUCH closeout records that a stale one *"turned 9 of that file's 31 tests
red"* and would be *"a live trap for anyone who ever restarted the loop."*
Because it is created at runtime by four scripts and was **not** in `.gitignore`,
a broad `git add` could have committed a safety flag set; that line is now in
`.gitignore`.

**`artifacts/midas_watchdog.lock` — correct design, keep.** `os.open(O_CREAT)` +
`msvcrt.locking`/`fcntl.flock` on byte 0. The **existence** of the file is
irrelevant; the OS handle is the gate, and it dies with the process. This is the
design the other flag classes should have had.

**`artifacts/rollout_*_r100.json` — not a flag.** No code reads them; the arming
gate is the `--armed-live` CLI flag (`supervised_live.py` appends
`missing_armed_confirmation`). They are *written* snapshots. They are recorded
here only because a filename like `rollout_armed_r100.json` reads like a live
arming record, which is a documentation hazard rather than a behavioural one.

**The good pattern, worth copying:** `MitemshubAI_v28_fwd.mq5::LoadFilterTable()`
uses `FileIsExist()` — presence changes behaviour (it enables a learned consult)
— but the absence path is **explicitly logged and explicitly scoped**:
`"FILTER TABLE: %s absent — consult disabled (rule-based conviction bar stays
authoritative)"`. A reader can never mistake absence for a verdict. That is the
bar every entry above failed.

---

## 5. Systemic finding: the operator tooling is pinned to terminal dirs that are gone

### 5.1 The finding (as first recorded)

Seven scripts referenced MT5 data directories by hardcoded hash. **Not one of
them pointed at the live Upcomers terminal.**

| script | pinned dir | existed? | era |
|---|---|---|---|
| `scripts/confirm-gate-open.ps1` | `FB9A56D6…` | **no** | high-water-era synthetic |
| `scripts/go_live_rehearsal.py` | `FB9A56D6…` | **no** | same |
| `scripts/demo_watchdog.py` | `FB9A56D6…` | **no** | same |
| `scripts/funnel_diff.py` | `FB9A56D6…`, `71BF6B2A…` | no / yes | same / Deriv |
| `scripts/atr_drift_monitor.py` | `MetaQuotes\Tester\49E0383C…` | Tester dir | gold |
| `scripts/midas_drift_drill.py` | `49E0383C…` | yes | gold |
| `scripts/set_chart_preset.py` | `FB9A56D6…` (doc example) | **no** | same |

Each one either errored or reported an unearned verdict. `confirm-gate-open.ps1`
was the only one that produced a **false green**.

### 5.2 Remediated: all seven now resolve dynamically and refuse to guess

One source of truth, `scripts/mt5_terminals.py`, replaces every hardcoded hash.
It resolves from **evidence on disk** and raises `TerminalNotFound` (a non-zero
exit for every consumer) when there is none. It never returns a default.

| consumer | how it resolves | refusal point |
|---|---|---|
| `scripts/confirm-gate-open.ps1` | calls the resolver — **but only from 2026-09-19 late; see §5.4** | empty terminal root, no journal, or a journal with no EA evidence → `exit 1`, prints **UNKNOWN, not OPEN** |
| `scripts/go_live_rehearsal.py` | `resolve_terminal_holding("MitemshubAI*telemetry*.jsonl")` | cannot locate the arm's install → the rehearsal stops instead of scoring it |
| `scripts/demo_watchdog.py` | `telemetry_dirs()` — by filename, not by install | no telemetry anywhere → **UNKNOWN**, never "quiet account" |
| `scripts/funnel_diff.py` | the install that holds the V75 state file | none holds it → refuses before comparing |
| `scripts/atr_drift_monitor.py` | `resolve_tester_files(ledger name)` | no Tester ledger → **CALIBRATION-DRIFT**, never the frozen band |
| `scripts/midas_drift_drill.py` | `resolve_terminal()` | none → `SystemExit` at import, before seeding |
| `scripts/set_chart_preset.py` | `--hash` optional; default resolves live | chart not found → `exit 2` (fail-closed either way) |

### 5.3 Identity: recency was still not enough

The fix in §5.2 removed the hardcoded hashes but kept the **selection rule**: pick
the install whose journal was written most recently. That rule is wrong in a
specific, measurable way, and the same session produced the evidence.

On 2026-09-19 the dead Deriv install `49E0383C` wrote `logs/20260919.log` at
15:58 reading:

```
MetaTrader 5 Terminal x64 build 6182 started for Deriv.com Limited
```

A terminal that **merely booted** — no account, no EA, no relation to the live
venue — satisfies every recency test. Ranking it below a better candidate only
helps when a better candidate exists; when the live install has no journal for
today, recency hands the answer to a dead one. The Experts-journal rule narrows
this but does not close it.

**The fix is to identify installs by the ACCOUNT NUMBER in their journals.** MT5
writes unambiguous identity lines, and they are the only thing on disk that names
the account:

```
'1428765': authorized on Upcomers-Server
'1428765': terminal synchronized with Upcomers Ltd.: 0 positions, 0 orders
'140778269': authorized on DerivSVG-Server-03 through Access Server - South Africa 02
'140778269': terminal synchronized with Deriv (SVG) LLC: 0 positions, 0 orders
```

The registry `configs/mt5/accounts.json` declares one active account; every
install citing any *other* account is classified **foreign and excluded from
every fallback**, so it can never be selected however recently it was touched.
Measured on this machine:

```
49E0383C   foreign   acct 140778269  server DerivSVG-Server-03  company Deriv (SVG) LLC
71BF6B2A   foreign   acct 140778269  server DerivSVG-Server-03  company Deriv (SVG) LLC
D0E8209F   active    acct 1428765    server Upcomers-Server      company Upcomers Ltd.
Common/Community/MQL5   unknown   (no journals, no account)

resolve_terminal() -> D0E8209F, "journals cite the active account ..."
```

Three design points that are not incidental:

* **Exclusion comes from `active` alone.** Any install citing a non-active
  account is foreign, whether or not it appears in the `retired` list. The list
  gives the excluded install a *name* ("that is the closed MIDASTOUCH gold
  install"), which is what lets a refusal be specific. An early draft of the
  registry README claimed the retired list did the excluding; that was wrong and
  is corrected in the file.
* **Ambiguity is reported, not hidden.** An install citing *no* account (a fresh
  install that has never logged in) is eligible but the reason string says
  *"NOTE this install names no account, so it is not confirmed as ours"*. With no
  registry at all, nothing can be called foreign, and the reason says
  *"WARNING nothing was excluded by account because no account registry at ..."*.
  A missing registry cannot silently downgrade resolution back to recency.
* **A successful resolution also reports what it passed over.** The exclusion
  note is appended on the success path, not only in refusals — an operator who
  cannot see that the dead install was considered and rejected cannot tell a real
  resolution from a lucky one.

**Two parser bugs were found by testing against the real journals rather than a
convenient format.** The company regex captured *the account number* instead of
the company name (wrong capture group), and the server regex only matched the
`... through Access Server ...` shape, so journals that print the bare
`authorized on Upcomers-Server` form yielded no server at all — which the real
machine happened to hide, because it prints both shapes. Journals are UTF-16LE,
so the codec is chosen from the bytes: decoding UTF-8 as UTF-16 does not always
raise, it can succeed and yield interleaved NULs, and every identity regex would
then miss silently. A bare `\d{6,9}` scan finds timestamps and ticket numbers, so
the account pattern is anchored on MT5's quoting.

**`resolve_terminal_holding` deliberately does NOT exclude foreign installs.** Its
question is *"who holds this evidence"*, and the answer is legitimately a retired
install — `demo_watchdog` reads the closed V75 paper ledgers from `49E0383C`. It
prefers the active account's install when one also holds the file, and otherwise
returns the evidence with *"WARNING no install holding it cites the active
account, so this evidence may be from a closed program"*.

Where the `--terminal` guard still binds: an operator can pass `explicit=<path>`
and that overrides identity, because naming a directory is not guessing. Only
*defaults* are subject to the identity rule.

### 5.4 The sweep: making the class automatic, and three defects it found

§5.2 and §5.3 fixed the instances. This is the class-level check, so the same
fault cannot return unnoticed:

```
python scripts/refusal_sweep.py              # every diagnostic vs an unreadable root
python scripts/refusal_sweep.py --self-check # prove the sweep can fail
```

It points each tool at an empty terminal root and passes a case only when it
**(1)** exits non-zero, **(2)** names what it could not resolve, **(3)** does not
traceback, and **(4)** writes nothing that a later reader could mistake for a
result. It snapshots and restores the artifact paths, so it reports writes instead
of causing them. Full sweep: **8 cases, 6 seconds.**

**Running it for the first time found three real defects** — which is the point,
and none of them was visible in the earlier hand-written review:

| script | was | now |
|---|---|---|
| `funnel_diff.py` | escaping `TerminalNotFound` → a **traceback**, exit 1 | clean diagnosis, `exit 2` |
| `go_live_rehearsal.py` | same traceback | clean diagnosis, `exit 2` |
| `atr_drift_monitor.py` | **`exit 0`** while unable to read the market, **and appended a reading** to the append-only calibration history | `exit 2`, appends nothing |

The `atr_drift_monitor` one is the worst of the three and the reason criterion (1)
exists: it did not merely fail to notice a problem, it *reported success* and wrote
into the calibration record, so a later reader would have found a reading that was
never a measurement. That is a **false green in the record**, not just on screen.

The traceback criterion (3) is not pedantry. An escaping `TerminalNotFound` yields
the same exit code as a refusal, so an exit-code-only check passes both; the
difference is that a wrapper catching `Exception` files the refusal as a *bug* and
may retry or ignore it. "I refuse" and "I broke" must not look alike.

#### A fourth finding: the PowerShell tool was a second implementation

`confirm-gate-open.ps1` did **not** call the shared resolver — it re-implemented
resolution in PowerShell (`Get-ChildItem $termRoot -Directory`, read whichever
install held a journal for today). §5.2 of this document claimed it "calls the
resolver", and that claim was **wrong**; it is corrected in the table above.

The consequence was not cosmetic: a hand-rolled scan cannot know the §5.3 identity
rule, so this script would have read a **dead Deriv-era install's journal and
graded the gate from it** — the original false green, in a new form. It now
delegates to `python scripts/mt5_terminals.py --terminal`, which is what the
resolver module's docstring has said it is for since it was written. Verified both
ways: real `%APPDATA%` resolves `D0E8209F` and reports **UNKNOWN, not OPEN**
(`exit 1`); empty `%APPDATA%` refuses to resolve the active account (`exit 1`).

**A sweep that cannot fail is worthless**, so `--self-check` feeds the verdict
function a script that exits 0, one that tracebacks, one that is silent, one that
hangs, one that writes a reading, and one that refuses properly, and asserts each
is classified correctly. `tests/test_refusal_sweep.py` pins the same logic plus one
more property: **`test_every_resolver_consumer_is_swept` derives the list of
scripts that actually read a terminal directory and fails when one is missing from
the sweep.** That is what makes this a class check rather than a fixed list — and
it is the test that surfaced the PowerShell divergence, because the script could
not be derived as a consumer until it delegated.

**`verify_sizing_live.py` needs a different neutraliser, and that is worth
knowing.** An empty `%APPDATA%` does **not** stop it: the MT5 Python bridge finds a
running terminal independently of `%APPDATA%`, measured 2026-09-19. It has an
explicit `--offline` flag for this, and the sweep uses it. A sweep that assumed
"empty root ⇒ no terminal" would have silently tested nothing for that case.

It also legitimately writes a record of its own refusal (no `verdict`, no lot
size, `terminal.available: false`), so the write rule has a narrow, declared
exemption — and the exemption is itself checked, by requiring the written content
to say the terminal was unavailable.

**Two resolution modes, and the distinction is load-bearing.**
`resolve_terminal()` answers *"which install is live?"*;
`resolve_terminal_holding(pattern)` answers *"which install holds these
records?"*. They give **different answers** on this machine, and conflating them
is a measured failure, not a hypothetical: the live install held **zero**
telemetry files while `49E0383C` and `71BF6B2A` held them, so a consumer that
asked the first question and read for the second found nothing and printed a
verdict about an account it had never read. Consumers whose subject is a specific
account's records must ask the second question.

**One correctness fix beyond the pins.** `49E0383C/logs/20260919.log` is a
*terminal-startup* journal ("started for Deriv.com Limited"), while the Experts
journal lives in `MQL5/Logs/`. A naive "has a journal today" test therefore
passes for an install that merely booted — so the resolver layers its evidence
and prefers the Experts journal
(`test_experts_journal_outranks_a_bare_startup_journal`). That was a bug in my own
first version, caught by checking the claim against the disk instead of trusting it.

**Verified on this machine, not only in tests.**

```
confirm-gate-open.ps1    -> resolves D0E8209F (live), reports UNKNOWN, exit 1
demo_watchdog            -> resolves 49E0383C, grades REAL closed paper trades
go_live_rehearsal        -> resolves 49E0383C, banner source 20260916.log, exit 1
atr_drift_monitor        -> CALIBRATION-DRIFT flagged, no silent frozen band
resolve_terminal_holding -> 49E0383C (broad telemetry) / 71BF6B2A (v23 file)
```

Two of the three above changed their answer **after** the first fix, because the
first version asked "which install is live?" — that is the moment the distinction
became measurable rather than theoretical.

**An explicit `--hash` survives on `set_chart_preset.py`**, which is an operator
overriding a resolver, not the tool inventing a default — and the chart-existence
guard still fails closed. Both paths were exercised: the resolver path exits 2 at
"no `<inputs>` block in chart", the explicit dead hash exits 2 at "chart not
found".

**"Refuses correctly" had to be distinguished from "refuses always."**
`set_chart_preset.py` reads charts as UTF-16, and every live chart it can reach
fails at "no `<inputs>` block" — which would look identical to an encoding bug
that makes the tool useless. So I ran a positive control: **19 chart backups**
from the Deriv-era installs decode fine through the same `read_chr` and *do*
contain exactly one `<inputs>` block with an `<expert>` block present. The
refusal is therefore about the subject (no chart on this machine currently has an
EA attached), not about the reader.

**Grep-verified:** no live code path in `scripts/`, `src/` or `mql5/` contains a
terminal hash. Every remaining occurrence is a comment or docstring recording the
retired constant.

Scheduled tasks were checked too: `MitemshubA2FirstTradeWatch` and
`SyntheticIndicesPaperPipeline` are both **Disabled**, and no task references any
of the retired controls.

---

## 6. Deriv-era residue that is evidence, not a flag

Preserved, untouched — this is the closed gold/synthetic record, and the
closeout explicitly keeps it:

- `…/49E0383C…/MQL5/Files/` — `MIDASTOUCH_paper_XAUUSDmicro_{LV,M1,M1m,M1s,M1t}.csv`
  (five paper ledgers), `MIDASTOUCH_debug_h1.csv`, `MIDASTOUCH_spread_M15.csv`,
  `MidastouchAI_M1_gold.set`, and two `MitemshubAI_state_Volatility_75_Index*.csv`.
- `…/71BF6B2A…/MQL5/Files/` — `MitemshubAI_paper_Volatility_75_Index.csv`, its state file.
- `…/49E0383C…/config/midas_parity.ini` — a Strategy Tester launcher
  (`Expert=MidastouchAI`, `Symbol=XAUUSD`, `Period=M15`, `ShutdownTerminal=1`).
  It changes behaviour only if a terminal is launched with `/config:`.

**The one that is loaded rather than merely read:** `MitemshubAI.mq5` calls
`LoadState()` on attach, restoring counters from
`MitemshubAI_state_<symbol>.csv`. The **live Upcomers terminal's `MQL5/Files` is
empty**, so nothing can be restored there — but attaching the EA to a
Deriv-era dir would restore that era's counters. Reopen condition in §7.

`Common\Files` also holds ~300 MB of `V75MacroEngine_audit_20*.csv` (audit
corpus, read-only inputs, no behavioural role).

---

## 7. Residual hazard found but NOT touched: a stale trade instruction in the shared folder

`%APPDATA%\MetaQuotes\Terminal\Common\Files\` is **shared by every MT5 terminal
on this machine**, including the live Upcomers one. It contains:

```
synth_calls_R_75.json      421 B   Aug 10 23:35   <- a trade INSTRUCTION
synth_ea_state_R_75.json   171 B   Aug 11 00:10   status: "rejected"
```

`SynthCallExecutor.mq5` polls `InpCallFile` (default `synth_calls_R_75.json`) on
a timer and **executes the call it finds** — so here, unlike everything else in
this audit, presence is the trigger. The stale call is a `buy 0.01` R_75 with
`evidence_status: "proven"` (so it passes the proven-only gate).

**Why it cannot fire today — and how thin that margin is.** Two gates hold it:

1. **Expiry, which is the real protection.** `expiry_epoch 1786574143` =
   **2026-08-12**, and `ProcessCalls()` tests expiry *before* direction, levels
   and the venue check. It is 38 days stale, so the call is marked `expired` and
   returns. If the emitter had written `expiry_epoch: 0` — which the parser
   documents as **"no expiry"** — that gate disappears entirely.
2. The venue-symbol/chart mismatch (`venue_symbol "SYN75"`; `SYN75` exists on no
   Upcomers chart), which skips without marking processed.

The dedupe memory contributes **nothing** here: `OnInit()` restores
`g_lastCallId` from the state file *only* when status is `executed`/`closed`, and
this state says `rejected` — deliberately, so a restart cannot skip a still-valid
call. The call file is never consumed or removed, so it stays armed until it
expires.

**Not touched, and why:** that path is outside this repository, and my rule is to
treat anything outside the project directory as read-only. Neutralising it is a
one-line move the operator should own.

**Recommended fix (for whenever the synthetic program is re-armed):** make
consumption explicit — the EA should archive the call file (e.g. rename to
`.done`) after processing, and the emitter should delete on expiry, so that
**presence stops being an execution trigger** and the expiry field is a second
line of defence rather than the only one.

### Reopen conditions (any of these invalidates the "retired" verdict)

- **Gold/synthetic surface revived, or `140778269` re-funded** → clear the VPS
  instance by hand and re-audit every entry in §2.
- **`SynthCallExecutor` attached**, or any emitter writing `expiry_epoch: 0`
  into `Common\Files` → §7 stops being theoretical.
- **Any MT5 terminal launched with `/config:`** → `config/midas_parity.ini` (§6)
  becomes a live launcher.
- **The EA attached to a Deriv-era terminal dir** (`49E0383C` / `71BF6B2A`) →
  `LoadState()` restores that era's counters.
- **A new broker/venue** → the clock-offset baseline must be re-established by
  reading, not inherited (this is what §3.1 was).

---

## 8. Verification

- `artifacts/midas_clock_offset_state.json`: absent from the live path, present
  in the archive, hash-identical to the original.
- `scripts/.midas_watchdog_paused`: absent; `git check-ignore` now reports it.
- `confirm-gate-open.ps1`: `exit 1` when the active account's terminal cannot be
  resolved, and `exit 1` on a journal with no EA evidence; `exit 0` only with
  evidence. Since §5.4 it delegates to `scripts/mt5_terminals.py --terminal`, so
  it also inherits the §5.3 identity exclusion.
- `tests/test_midas_clock.py` — 3 new pins in `TestRetiredEraFlag`.
- `tests/test_mt5_terminals.py` — **48 pass**, including 4 pins for
  `resolve_terminal_holding` (evidence beats liveness; nothing holds it → refuse;
  searches the Experts journal location; no terminals → refuse without crashing)
  and 21 for identity (§5.3), the load-bearing one being
  `test_a_retired_install_that_merely_booted_today_is_never_selected`: a foreign
  install holding today's Experts journal *and* charts, against a live install
  whose newest journal is 9 days old — every recency test points at the dead
  install and identity must overrule all of them.
- `configs/mt5/accounts.json` — the identity registry; declares active
  `1428765` (Upcomers) and retired `140778269` (Deriv/MIDASTOUCH).
- `scripts/refusal_sweep.py` + `tests/test_refusal_sweep.py` — **8 cases, 15 pins**;
  full sweep passes in ~6s and `--self-check` passes. The sweep restores every
  artifact it touches, verified by
  `test_the_sweep_restores_what_it_touched`.
- All four Python consumers re-run on the real machine after the change:
  `demo_watchdog` still reads `49E0383C` (it is the only holder of the telemetry),
  `midas_drift_drill` resolves `D0E8209F` by identity and refuses, and
  `confirm-gate-open.ps1` prints **UNKNOWN, not OPEN**.
- No terminal hash remains in any live code path (§5.2).
- All six Python consumers executed on the real machine and behaved as the
table in §5.2 specifies; `set_chart_preset.py` exercised on both its resolver and
its explicit-hash path.
- `python -m compileall scripts/ src/` — clean (one pre-existing
`SyntaxWarning` in `src/backtest_v17_3_v100.py`, unrelated).
- Affected suites after §5.4: **194 pass**
  (`refusal_sweep`, `mt5_terminals`, `midas_clock`, `midas_watchdog`,
  `funnel_diff_guard`, `go_live_rehearsal`, `prop_execution`); **2,133 tests
  collect** cleanly.
- Full affected-suite run recorded in the session that produced
  `docs/GOLD_SURFACE_RETIREMENT_20260919.md` and this file.
