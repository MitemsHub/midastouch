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
[PASS] XAUUSD available                       Gold vs US Dollar spread 41 pts, min lot 0.01
[PASS] market open (live tick)                feed live (last tick 0 min ago, venue clock UTC+2)
[PASS] symbol filling mode is usable          IOC only; CTrade resolves to IOC
[PASS] order path accept-check (min lot)      venue ACCEPTED a 0.01-lot buy, stop $31.17
[FAIL] scheduled task target                  MIDASTOUCH Arm Supervisor is not registered
[FAIL] supervisor runs unattended             ... runs only while a user is signed in
[FAIL] host can hold supervision overnight    wake timers Disable; S0 Low Power Idle only
[PASS] no unacknowledged heartbeat gap        none outstanding
[PASS] deployed EA build matches its source   source 2988ab12 == the deployed binary's source
[PASS] the CHART runs the deployed build      MIDASTOUCH_paper_XAUUSD_U25 is running MIDAS1.27 (last init …)
[PASS] operator authorisation                 ARMED BY OPERATOR OVERRIDE — the gate FAILED
[OFF ] python execution gate                  no validation record — nothing has passed the gate
[PASS] operator arming file present           artifacts\live\armed.json
[WARN] validation record present              absent — nothing has passed the walk-forward gate
[FAIL] evidence describes this strategy       the cited artifact measured a different trigger
```

Read the legs that are *supposed* to look "off" as the design, not as faults:

| line | what it means | healthy | what bad looks like |
|---|---|---|---|
| `market open (live tick)` | gold trades ~24/5 with a daily break and a weekend close | a tick within the last few minutes | `last tick was N min ago` on a weekday = feed or session problem; on a weekend it is simply closed |
| `python execution gate` / `validation record present` | a configuration that passed the walk-forward gate | both say `nothing has passed` | a record appearing **without** a matching gate run |
| `operator authorisation` / `operator arming file present` | the operator's own arming decision (`artifacts\live\armed.json`) | `ARMED` with the reason it names | `ON` with **no** record at all = the failure those legs exist to catch |
| `evidence describes this strategy` | the cited verdict must measure the trigger the EA runs | `PASS` | today's state: the artifact measured `ema_stack_trigger`, the EA implements `bb_rsi_trigger` — a verdict about a different strategy, refused |
| `scheduled task target` | the supervisor must point **inside this repo** | `PASS` | `STALE: the task points at ...\Synthetic Indices Bot\...` = the task survived the project rename and must be re-pointed |
| `supervisor runs unattended` | the task must run **whether or not anyone is signed in** (S4U + a BootTrigger + WakeToRun, read from the task's own XML) | `PASS` | `logon type is 'InteractiveToken'` — the measured 2026-09-22 state, and the reason the arm had zero supervision passes in the 01:00–06:00 UTC hours |
| `host can hold supervision overnight` | the **host** must be able to hold the schedule: wake timers, no S0 idle, no standing sleep timer | `PASS` | `Allow wake timers = Disable …; S0 Low Power Idle is the only standby state` = a documented policy this laptop fails, and the reason its home is a VPS |
| `no unacknowledged heartbeat gap` | no recorded interval between supervision passes over the pre-registered threshold, or no stale-ledger pass, is outstanding | `PASS` | `PROBLEM: supervision-gap — no supervision pass for 407.4 min` — acknowledge only after reading the night: `python scripts\live_coverage.py --ack` |
| `the CHART runs the deployed build` | what the running expert **says it is** — the `ERA` row it writes at every init, against the `APP_VERSION` the source defines — **and whether that row still covers the file on disk**: a binary written *after* the init cannot be the one the chart is running, so a deploy with no relaunch is caught even when the version was not bumped | `PASS`, naming the build and when it last initialised (UTC, with the **arm's own recorded** server offset applied) | `the CHART is not running the deployed build: … is running MIDAS1.26 … against this source's MIDAS1.27` = the `.ex5` on disk was replaced and the expert was never re-initialised into it. Measured 2026-09-22: copying the certified binary was **not** enough on a start-up-attached expert — no journal line, no new `ERA` row, fifteen minutes, market open. The variant that shares the version reads `the chart is not running the binary that exists: … initialised into MIDAS1.27 at 19:23Z, but the binary a chart loads was written at 19:33Z — after that init`. Both mean: relaunch the terminal **with its attach config** (`mt5_ops.relaunch_terminal()`, or the registered stop→copy→verify→relaunch in `midas_deploy_v118.py`) |

### The two harder legs: filling mode and the order path

These were each proven **once, by hand**, on 2026-09-21 — a min-lot request the
venue priced and accepted, and a filling-mode question answered by reading the
installed `Trade.mqh`. A hand proof decays: a venue can change its filling mode,
an account can lose its trade permissions, and the next person to ask "can this
thing actually place an order" would have to remember how it was done. Both are
now routine legs, so both are re-asked on every run.

| leg | what it does | three outcomes |
|---|---|---|
| `symbol filling mode is usable` | mirrors `CTrade`'s own resolver: FOK if the symbol lists it, else IOC, and *neither* means no order can ever be sent | `PASS` / `FAIL` (neither mode listed) |
| `order path accept-check (min lot, nothing sent)` | asks the **venue** to price and margin a real 0.01-lot order with the arm's own stop geometry | `PASS` accepted · `FAIL` refused (blocks, and names the retcode) · `UNCONFIRMED` market closed or trading disabled — renders `WARN` and does **not** block; an unasked question is not a pass |

`order_check` is read-only by construction — MT5 prices the request server-side
and places nothing — and a source test asserts there is **no `order_send`
anywhere in `live_readiness.py`**, so the day it can send an order is the day it
would fail its own suite. A `FAIL` here means a signal would be rejected at the
venue even though every other leg is green, which is exactly the case no other
leg can see.

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
On v1.19d that line can also read **`CLOCK: UNVERIFIED OFFSET`**, naming two
readings that disagree — and that is correct, not a fault: the old line derived
the offset from `TimeCurrent()`, which is the time of the **last tick**, so for
minutes after a launch it announced `offset=-5 h 19 min` for a venue that is
UTC+2 (measured twice on 2026-09-21). Wait for a live tick, then read it again;
the trade-server clock in the same line (`+2 h 00 min`) is the trustworthy one.
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
| `OPEN` | time,ticket,dir,entry,sl,tp,lots,risk,stop,timeout,tag,atr,spread[,state][,cfg] | followed eventually by a `CLOSE` with the same ticket |
| `LOPEN` | time,posid,order,deal,dir,entry,sl,tp,lots,risk,stop,timeout,tag[,state][,entry=pending][,cfg] | the LIVE arm's own fill row — see §3c and §3c-bis |
| `LENTRY` | time,identity,entry price,source | prices a fill row whose entry price could not be known at write time (v1.25) — see §3c-bis |
| `CLOSE` | time,ticket,reason,exit,R,pnl,equity | `reason` ∈ SL/TP/TIME |
| `NOFILLSUM` | epoch, UTC day, 9 counters | the running refusal census — see §3a |
| `NOFILL` | epoch, 9 counters | a day that has ended — see §3a |
| `STATE` | UTC-now, signal bar, regime, trigger, sizing, governor[,cfg] | the HUD's view on the record — see §3b |

Two questions it answers:

1. **Is it alive?** The file's *last modified* moves at least every ~15 minutes.
2. **Is it honest?** Every `OPEN` has a matching `CLOSE` (same ticket), except at
   most one trailing `OPEN` which must match the chart HUD. `EQ` changes only on
   `CLOSE` rows.

**Do not touch the ledger.** Never edit, rename or "clean up" it. An empty file
with only `ERA`/`EQ` rows is a deliberate fresh book, not data loss.

### 3a. Why didn't it trade? (the refusal census)

An arm that does nothing has to be able to say why **from the record**, not from anyone's
memory of the chart. Two row types carry that, and they are the same nine counters:

| row | when | what it is |
|---|---|---|
| `NOFILLSUM,<epoch>,<utc day>,<9 counters>` | whenever a counter changes (at most once per evaluated M15 bar), and on deinit | the **running** census of the current UTC day |
| `NOFILL,<epoch>,<9 counters>` | when the UTC day rolls | the **final** census of the day that ended |

The nine counters, in this exact order (the reader in `scripts/morning_status.py` shares
this order, and a test pins both against the writer):

```
signal, mismatch, session, friday, spread, riskcap, breaker, no_trigger, news
```

`signal` counts evaluated bars that produced no trade; `no_trigger` is the lane that
dominates a quiet market — **the pattern never lined up**, which is a normal day, not a
fault. `session`, `friday`, `spread` and `riskcap` are the gates refusing a signal that
did fire; `news` is the stand-down of §5a.

```
python scripts/morning_status.py
  no-fill (day 20717, running): no_trigger=2  (the census so far; it rolls to a NOFILL row at the UTC day change)
  no-fill (24h): no_trigger=6, session=1      (days that have ENDED)
```

**Why the snapshot row exists (measured 2026-09-21).** The counters used to live only in
the EA's memory, with a "write once per 24h since the first refusal" rule. On a day the arm
was reloaded 22 times, each reload zeroed them and the day's census was never written at
all — the one record built to answer this question was unreachable exactly when the arm was
being restarted most. The EA now reads the last `NOFILLSUM` row back at init and says so:

```
[MIDAS1.20]NOFILL census restored: day=20717 signal=3 no-trigger=3 ... (from NOFILLSUM @1790016300)
[MIDAS1.20]NOFILL census: no snapshot row yet, counting from zero     <- a ledger with no
                                                                        snapshot row at all
```

**Read the version on those lines.** The census shipped while the tag still said `1.19`, so a
build *with* the census and a build *without* it could both stamp `[MIDAS1.19]` — and the ERA
row is where a replay learns which behaviour produced a day's rows. They are now `MIDAS1.20`
(2026-09-21), and `tests/test_midas_hud.py` pins `#property version` to `APP_VERSION` so the
banner, the ERA row and every reader of them cannot drift apart again.

A ledger with **no** `NOFILLSUM` row cannot answer for that day (a v1.18/v1.19 ledger, or a
day that predates this change), and `morning_status` reports nothing rather than a day of
zeros — "the arm's account of itself was erased" must never read as "the arm was idle".

### 3b. What is the engine actually seeing? (the HUD panel and its STATE row)

Since v1.21 the chart's panel answers *view*, not just liveness:

```
MIDASTOUCH MIDAS1.26 | mode=1 REVERSE_DIRECTION | entryTF=PERIOD_M15 | session 06-20 UTC
vEq: $25,004.26 acct (bal $25,004.26, +4.26 vs the $25,000 basis) | pos: flat
REGIME   H4 down / H1 down -> BEARISH (macro -1)
TRIGGER  none | RSI(14) 46.7 | last bar 2026.09.22 16:00
GATES    bar inside the 06-20 UTC window | tick spread $0.47 vs cap $0.62
SIZING   0.01 lots, risk $41.20 of $62.50 configured (0.25%) QUANTISED DOWN on 2.0xATR(H1)=$41.20
GOVERNOR floor $23,504 | today +4.31 of cap $250 | CLEAR
NEWS     stand-down OFF - the gate is not applied
trades: 1/30 LIVE closed (ledger LCLOSE rows) | wins 1 | cumR +0.104
eval: 34 no-trade bars | V: mis 4 no-trg 30 sess 0 spr 0
last: VETO NO-TRIGGER(mac=-1)
```

The values above are the armed arm's own, measured 2026-09-22 (the ledger's `STATE` row and
`NOFILLSUM` census); the refusal shown on the `last:` line is the layout's, not that moment's.

**The tally names which record it counts (v1.24).** `trades:` used to print the *paper* counters —
which on an armed arm never move, because no live close path incremented them — so after the arm's
first real closed trade on 2026-09-22 (+0.104R, in the ledger) the chart still read `trades: 0/30 |
cumR +0.00`. A chart that understates the arm's realized record is what an operator uses to decide
whether to keep it armed. The live tally now counts the **ledger's own `LCLOSE` rows**, restored at
init from the file, and the label says so: a bare `1/30` beside a ledger's `1/30` is fine, but a bare
`0/30` beside it is how a chart and a record disagree while both look right. `GOVERNOR` likewise
names an unmeasured state (`guard ON - readings not measured yet`) instead of printing `floor $0 |
today +0.00 of cap $0` for the bar-interval after every reload.

Read it top-down as the engine's own questions: **which way is gold trending** (H4 and H1
EMA20 versus close — the same two booleans that decide entries, so the chart cannot say
BULLISH while the engine refuses a long), **did the trigger fire on the bar just closed**
(BB touch-back or RSI 30/70, with the RSI reading so "how close was it" is visible),
**would an entry be allowed right now** (session window, live spread against the 1.5%-of-stop
cap), **what size would it take** (with `[MIN-LOT EXCEEDS BUDGET -> risk-cap veto]` when the
venue's floor is larger than the risk budget — that is a refusal, not a size), and **what the
governor is thinking** (shield floor, today's P&L against the Best Day cap, and the block
reason when there is one).

The panel is a *view*, not a record: it changes with the next tick and it is gone when the
terminal closes. So the same numbers are appended to the ledger as a `STATE` row on every
evaluated bar and on the 15-minute heartbeat, and `morning_status` renders them from the file:

```
view (ledger STATE, written 09-21 20:00 UTC | last bar 09-21 21:45 server): H4 down / H1 down
  -> BEARISH | trigger none | RSI 52.3 | inside session | 0.01 lots risk $31.84
  | day +0.00 of cap $250 | floor $23500
```

**Two clocks, deliberately, and they are not interchangeable.** The row's own timestamp is
UTC (`TimeUTCNow`); the bar epoch it evaluated is **server-stamped**, like every bar epoch in
this program — the parity clock work pinned the venue offset precisely because treating one as
the other is a whole-offset error that reads as a plausible time. The report therefore labels
the bar `server` and prints the offset line separately rather than converting silently.

That is the point of the row: "why didn't it trade at 14:15" is answerable tomorrow, from
the file, without the chart. The row is gated out of the strategy tester and the BAR replay,
so certified parity ledgers stay byte-identical, and the ERA note carries `+state-view` so a
reader knows the ledger it holds can answer that question at all.

---

### 3c. What risk did it actually take? (the `cfg` tail on a fill row, v1.22)

A fill row's `risk` field is the risk the fill **took** — derived from the lot size the venue
let the arm use. Since v1.22 every fill row also carries `cfg=<usd>@<pct>`, the risk the arm
was **configured** for (`InpRiskPercent` of the same equity base the sizing divided). It is one
keyed field, appended **last**, so `risk` and `cfg` always describe the same fill:

```
LOPEN,1790070019,308417,309001,309004,1,4389.07500,4359.41071,4448.40357,0.10,2.91,29.08429,
      43200,U25,cfg=62.50@0.25
                                                        ^^^^^^^^^^^^^^ configured, not taken
```

They are different numbers whenever the venue's lot step cannot express the budget, in either
direction, and **that is the normal case on this account**:

| what you see | what it means |
|---|---|
| `took $31.84 of $62.50 configured` — QUANTISED DOWN | the 0.01-lot floor is the only reachable size at this stop width; the budget is partly unspent. Not a fault, and not a rule breach — but a fill that took half its budget must not read like one that took all of it |
| `took $63.68 of $62.50 configured` — OVERSHOOT | the floor lot risks *more* than configured, which amendment 6 still permits while it stays under `InpMaxRiskPct`. Worth seeing rather than assuming |
| `AS CONFIGURED` | the venue's step expressed the budget exactly |

It is on the **`STATE` row** as well as the fill rows, and that is deliberate: the panel
already carries the prospective size, so the gap is answerable from the journal on the next
evaluated bar rather than only from the first fill.

```
STATE,1790064000,1790070300,-1,-1,-1,1,2377,1,2,6224,0.00,250.00,23500.00,cfg=62.50@0.25
view (...): H4 down / H1 down -> BEARISH | trigger none | RSI 23.8 | in session | 0.02 lots
  risk $62.24 of $62.50 configured (0.25%) QUANTISED DOWN | day +0.00 of cap $250
```

Where to read it: `scripts/midas_first_fills_audit.py` prints a `risk:` disclosure per closed
trade and a `risk basis:` summary line, `morning_status` prints it in the STATE view and under
a live `LOPEN`, and a row written before v1.22 simply carries no tail (absence is not a defect
— and a **tester** row never will, because a parity ledger is a reproduction artifact).

> **The stamp is not a licence to be oversized.** It is a disclosure. The bound that refuses a
trade is still `InpMaxRiskPct` (amendment 6), vetos on both paths, and nothing here changes it.

### 3c-bis. `entry=pending` and the `LENTRY` row: a fill row that could not know its price (v1.25)

**The price column of a fill row is not knowable at the instant the row is written.** Measured on
the arm's own first fill (2026-09-22): the EA took the entry price from `ResultPrice()` as the
order was acknowledged, on a venue where that field is 0 at that moment, and wrote
`LOPEN,…,0.00000,…` — while the true price (4333.07) was in the position **and** in the entry deal
within the same second. A `0` in a price column is read as a price by every reader, so the row
gave the first-fill packet a disagreement (`entry price: ledger 0.0 vs venue 4333.07`) that lived
as long as the row did.

Two things follow, and you will see both:

```
LOPEN,1790092800,0,18874164,0,-1,0.00000,4374.38000,4250.77000,0.01,41.20,41.20143,43200,U25,
      1790091900,13,1.39453,out,120,entry=pending,cfg=62.50@0.25
LENTRY,1790099656,18874164,4333.07000,entry deal
```

| what you see | what it means |
|---|---|
| `,entry=pending` on a fill row | the price could not be resolved when the row was written. **It is not a price, so no reader grades it as one**: the packet reports `PENDING` (neither agreement nor disagreement) and the position's own P&L is unaffected — the EA sizes and manages on its own stop geometry, not on this field |
| `LENTRY,<epoch>,<identity>,<price>,<source>` | the amendment: the venue reported the price, `<source>` says where from (`position` or `entry deal`), and the identity is whichever the fill row carries — **on netting that is the ORDER ticket**, because `posid` is still 0 when the row is written |

The EA writes the amendment at init (so a row written by an **earlier build** is healed on the next
reload — that is what happened to the arm's first fill, seconds after v1.25 reached the chart) and
again the moment a pending fill resolves. Readers pair it by identity; `midas_first_fill_packet`
grades the **amended** figure and prints where it came from, so a corrected row can never be mistaken
for one that always knew. An amendment that prices **no** fill row of the ledger is reported as a
problem, and a fill row still pending at the end of a pass is reported ungraded rather than dropped.

### 3d. Why did the journal stop repeating `TICK VALUE MISMATCH`? (v1.23)

The venue's spec fields are self-inconsistent on this account: `SYMBOL_TRADE_TICK_VALUE`
(0.10) ÷ tick size (0.01) = $10 per price unit, while `OrderCalcProfit` settles $100 — so
the EA sizes on the settled value and says so. Until v1.23 it said so on **every call** to
`DollarPerUnitPerLot()`: the 15-minute heartbeat calls it twice (the STATE row writer and
the HUD refresh), every evaluated bar calls it again, and the sizing sites add one per
attempt. MEASURED in the 2026-09-22 journal: the identical line at 09:45, 10:01, 10:16,
10:31, 10:46, 11:01, 11:16, 11:30, 11:31 … — a static fact, re-stated, burying the
`VETO`/`NOFILL` refusals the journal exists to carry.

Since v1.23 it prints **once per session** (each EA init) and again only when either number
moves past a 0.5% relative band, so a real broker spec change re-arms it. The same two
moments append a `SPEC` row, so the evidence outlives the journal scroll:

```
SPEC,1790076020,tv=0.10000,ts=0.01000,cs=100.00,broker=10.00,settled=100.0000,used=100.0000,ratio=0.1000
```

The fields are **keyed** (`tv=`, `ts=`, `cs=`, `broker=`, `settled=`, `used=`, `ratio=`), not
columns: the NOFILL mislabel of 2026-09-21 was a reader/writer order disagreement that a
permutation of zeros made invisible, and a new row type gets no second chance. `broker` is
`tv/ts` (what the raw spec implies), `used` is the value the arm sized on, `settled` is
`OrderCalcProfit`'s answer (0 when the venue cannot price the probe — `morning_status` then
says `sized on geometry`) and `ratio = broker/used`.

`morning_status` reads the last row back and renders it under the arm's view:

```
venue spec (ledger SPEC, written 09-22 11:20 UTC): broker tv/ts=10.00 vs order_calc_profit
  100.00 per price unit (ratio 0.10) — venue spec self-inconsistent; sized on the settled value
```

`SPEC` rows are gated out of the strategy tester and the BAR replay exactly like `STATE`
(certified parity ledgers stay byte-identical), and the ERA note carries `+spec-record` so a
ledger says from itself that it can answer this. Nothing here is read by a decision: the
sizing authority ladder (settled → agreeing raw → geometry → raw) is untouched, and
`InpMaxRiskPct` (amendment 6) is still the bound that refuses a trade.

### 3e. The sweep shadow (v1.28): a row that carries a setup and never an outcome

Since `MIDAS1.28` (ERA note `+sweep-shadow`), the arm appends one

```
SWEEPSHADOW,<write_epoch>,<sig_open>,<utc_day>,<asian_hi>,<asian_lo>,<range_bars>,<side>,<is_first>,<reclaim>,<stop>,<off_min>,<era_tag>
```

row for every evaluated M15 bar inside **UTC 07:00–18:00** — the window the Asian-sweep
study measured (`docs/ASIA_SWEEP_PREREG_20260922.md`, its strongest held-out result). The
row carries the **setup**: the day's Asian range, which side swept it, whether this bar is
the first sweep of that side, the reclaim flag, and the stop distance at the certified
geometry (the arm's own ATR read × `InpSlAtrMult`). It carries **no outcome and no R**, by
design: the EA cannot know the future, and a row claiming an R its writer could not have
measured is not evidence. The row is **positional** (13 fields, like the fill rows) and
pinned by `tests/test_midas_v128_record.py` (thirteen fields, no outcome column, one call
site, no decision function mentions it, gated out of tester/BAR runs).

What turns rows into a verdict is the resolver, `scripts/midas_sweep_shadow.py`: it reads
the ledger's rows, **rebuilds the signal array independently through the engine of
record's own `run_mode`, and refuses on any bar where the EA's row and the engine disagree**
— a `VOID` on the recorder, not a verdict on the rule. Resolution uses the forward window's
pre-registered rule (`docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md`, fixed before any row
existed): below **60 resolved outcomes** the state is ACCUMULATING and no interim number is
quotable; then one evaluation — PASS needs t ≥ 2.4, n ≥ 60, ≥ 0.30 fills/day, mean forward
R > 0 and both direction checks still negative; FAIL names the test that failed.

`morning_status` renders the tail:

```
sweep shadow (ledger SWEEPSHADOW): no rows yet — the shadow starts on the next evaluated bar inside UTC 07-18
  (record only — NO order path; resolved against the forward pre-registration by scripts/midas_sweep_shadow.py)
```

The three sentences to remember: **the shadow cannot place an order** (no order state, no
governor, no census counter, one call site); **an empty shadow is healthy** (rows exist only
inside 07–18 UTC, so evenings and weekends show zero); and **an interim count of rows is not
a result** — the pre-registration is the only thing allowed to say what the family did.
The arming record carries the same contract in `artifacts/live/armed.json`
(`sweep_shadow_forward`).

### 3f. Who closed the trade? (v1.29: the LCLOSE reason word)

Until v1.29 the ledger's answer to "who closed this?" was one word — `EXTERNAL` — for every
close the EA did not place: a server-side stop-out, a server-side take-profit, and a human
tapping Close on a phone were the **same row**. The distinction existed only in the venue's
deal history, outside the artifact this program keeps as evidence (the whole story:
`docs/LIVE_EXIT_AUDIT_20260922.md`). The LCLOSE reason slot now carries:

| word | what it means |
|---|---|
| `SL` / `TP` / `SO` | a server-side exit fired (stop-loss / take-profit / stop-out) — the EA did not place the closing order, but the exit is the arm's own geometry working |
| `EXPERT` | the closing deal bears our magic — the EA's own path (TIMEOUT, FRIDAY-FLAT), recorded here when its own row was somehow lost |
| `MANUAL-CLIENT` / `MANUAL-WEB` / `MANUAL-MOBILE` | an order placed from the platform's desktop, web, or mobile app closed it |
| `EXTERNAL-UNKNOWN` | the OUT deal exists but names no reason this arm recognises — deliberately NOT guessed |

Precedence is fixed and pinned (`tests/test_midas_v129_record.py`): the closing deal's
**magic is asked first** (WHOSE act was it), then the **reason** (WHAT kind of act). A close
whose deal carries our magic is `EXPERT` even if the venue also stamped a reason — WHO wins
over WHAT. This toolchain's `ENUM_DEAL_REASON` has no OTHER member (measured: error 256),
so reasons beyond the ones named stay `EXTERNAL-UNKNOWN` rather than acquiring a guessed
word. No decision function reads any of this — the vocabulary is written for the operator
and the record, and the flat-gate and reconciliation readers parse the row positionally,
so a future vocabulary extension cannot break them.

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

### The arm's first real fill

When the armed arm places its first order, three sources describe the same event and only
then: the venue's own deal history, the EA's ledger row, and the state stamp the EA wrote on
that row. `python scripts\midas_first_fill_packet.py` prints them side by side, field by
field, and names every disagreement with both values — a count of "1 fill" cannot say which
of the three is wrong. It runs automatically when the watchdog's completeness alarm first
sees a fill (`midas_watchdog.record_first_fill`), and its verdict and disagreements land in
`artifacts\live\first_fill.json` beside the raw rows.

One case it deliberately does NOT convert silently: the ledger is stamped in broker SERVER
time and the venue's deal times are the terminal's, so if the two agree only after the pinned
offset the packet says so in words. A reader that converts one side and compares the result
to the other can never be shown to be wrong.

The row the packet compares carries the v1.22 `cfg=<usd>@<pct>` tail (§3c), so the first real
fill is also the first time the configured-vs-taken risk is checkable against the venue's own
volume — a fill that took its size from the venue's floor rather than from the preset is
visible in the same row as the disagreement it may have caused.

---

## 5. The arm supervisor (and the night it was not there)

The scheduled task `MIDASTOUCH Arm Supervisor` runs one supervision pass every 20
minutes: `scripts\paper_supervisor.cmd` → `scripts\paper_supervisor.py` →
`scripts\midas_watchdog.py`. It is named for the ARM, not for a paper run: it
supervises whichever preset the arming record names (`preset_for_tag(tag,
armed=True)`), so an armed arm is not silently repaired back to a paper pin. The
full record of this change, with every number measured, is
`docs/UNATTENDED_OPERATION_20260922.md`.

Four rules, each of which was a real failure before it was a rule:

- It must point at a path **inside this repo**. `scripts\live_readiness.py`'s
  `scheduled task target` leg is the check; if it says `STALE`, re-run
  `powershell -NoProfile -File scripts\install_paper_task.ps1 -Apply` — the
  installer refuses rather than register a task whose wrapper is missing.
  **Measured 2026-09-20:** the wrapper did not exist in this repo, so the
  installer refused and the task kept running the *predecessor* checkout's
  supervisor; the leg read `STALE` on every run and an unattended machine had no
  supervision at all. The wrapper and its module now exist, and
  `tests/test_paper_supervisor.py` fails if they disappear.
- It must run **whether or not anyone is signed in** — LogonType S4U, a BootTrigger,
  and WakeToRun, read back from the task's own XML by `scripts/unattended.py` and
  required by the `supervisor runs unattended` leg.
  **Measured 2026-09-22:** the task was `Ready`, pointed inside this repo, and its
  principal was `InteractiveToken` — 54 passes in 25.3 h where a 20-minute cadence
  owes 76, **zero** passes in the 01:00–06:00 UTC hours, one gap of 407 minutes. A
  registered task with the wrong principal is not supervision.
- The **host** must be able to hold it. `scripts/host_power.py` reads the power
  posture and the `host can hold supervision overnight` leg **blocks** on a measured
  defect (wake timers off, a standing sleep timer) and renders **WARN** when nothing
  measured is wrong but the rest is not measurable from `powercfg` — which is where
  this host sits now, after `RTCWAKE` was turned on (measured `0x0` → `0x1`), because
  whether a wake timer actually wakes an S0 host is only answerable by a measured
  night. **"Sleep after = never" is not that check**: it was already true here and a
  282.8-minute hole happened anyway, because a Modern-Standby laptop suspends on lid
  close / S0 idle.
- One pass per firing, and the **exit code means something**: `0` when the pass
  completed and nothing new was found (including `action=NONE`, "no chart
  attached" — a task that goes red every 20 minutes is noise), non-zero when the
  watchdog's own escalation says a human must act (`>= 3` unrecovered restups) or
  when **this pass raised a new heartbeat-gap alarm**. A standing alarm deliberately
  does not re-red every pass; it is carried by the alarm record, `alerts.log` and
  `[3b]`, and `live_readiness` stays red until someone acknowledges it.

Neither the supervisor nor the watchdog contains an order-sending path. The wrapper
logs to `artifacts\live\supervisor.log` and resolves `python` from its own location —
never from the predecessor checkout's `.venv`, which would put that project's `src/`
on the import path.

### Reading a night

```
python scripts\live_coverage.py                  # the most recent complete night
python scripts\live_coverage.py --hours 24
python scripts\live_coverage.py --prereg         # the frozen rule, as data
python scripts\live_coverage.py --alarm-state    # the outstanding alarm, if any
python scripts\live_coverage.py --ack            # a human says it was read
python scripts\unattended.py                     # does the task run with nobody signed on?
python scripts\host_power.py                     # can this host hold it?
```

A window PASSES iff no interval between recorded passes exceeds **40 min** (2 × the
registered cadence) and no observed ledger heartbeat age exceeds **35 min**
(`midas_watchdog.STALE_MIN`). Both were fixed before the first post-fix night exists,
so the rule can fail. The **BASELINE** measured on 2026-09-22 — 55 passes/78 due,
69.7 % coverage, 4 gaps, longest 282.8 min, 0 passes in 01:00–06:00 UTC — is in
`docs/UNATTENDED_OPERATION_20260922.md` §1, labelled as a baseline rather than as a
test of the rule.

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
arm anything, and it does not *un*-arm anything either: `artifacts\live\armed.json` is
the arming event and the operator's override is on the record, so a terminal that starts
on another host runs the arm **as the record configures it** — which today means real
orders. Moving the machine is a hosting decision; it is never an arming decision.

**Before a VPS becomes the arm's home**, the host checklist in
`docs\UNATTENDED_OPERATION_20260922.md` §4 applies: start the terminal without an
interactive sign-in, `unattended.py` PASS, `host_power.py` PASS, one measured night of
`live_coverage.py` PASS with an empty alarm, and `live_readiness.py` READY. A host that
has not passed those is a host where the arm exists for part of each night and nothing
says so.

---

## 5a. The news stand-down (and why turning it on can stop the arm)

The playbook's standing policy — no new entries in a ±15-minute window around top-tier
USD releases, with open positions still managed — is implemented, and it is the only
gate in this EA that can legitimately stop trading for days at a time. Read this before
switching it on.

**The source is a file, and the EA maintains it.** The Python API has no calendar at
all (MetaTrader5 5.0.5735 exposes no calendar function) and the strategy tester cannot
call one (`CalendarValueHistory` returns `GetLastError() = 4014`, measured 2026-09-20),
so the events live in one shared file that both engines read:

```
MQL5\Files\MIDASTOUCH_news_calendar.csv
```

With `InpUseNewsFilter=true` the EA reads the venue's own calendar, writes that file
(every `InpNewsRefreshHours`, default 6), and vetoes entries inside the window.
`mql5/MIDASTOUCH/MidasNewsProbe.mq5` is the measurement twin: attach it once and it
prints what this venue actually returns. The file is only ever **overwritten by a
non-empty answer** — a call that returns nothing is a failure to measure, not news, and
destroying a usable calendar with it would manufacture the very stand-down the gate
exists to express.

**The refusal is the feature.** An unusable source vetoes entries and says which of
these it is, in the journal and in the daily `NOFILL` row:

| journal says | meaning |
|---|---|
| `calendar file missing` | nothing has written it on this machine yet |
| `calendar stale (Nh old > 24h)` | the source aged out; entries are refused until it is refreshed |
| `calendar does not cover the next 24h` | the window ends too soon to be trusted |
| `calendar file declares no event count` / `calendar truncated (declares N, holds M)` | the file was written incompletely |
| `calendar empty` | the venue returned nothing — **cannot see the news**, which is not the same as no news |

The window is symmetric (±15 min, `InpNewsWindowMin`), top-tier events only, and it is
**entry-only**: no exit path may ever consult it, because a rule that could trap a
position through a release would breach the shield it claims to protect.

**Why the presets ship it OFF.** Two reasons, both stated rather than implied: (1) the
certified corpus and the walk-forward were measured with the gate off, so an arm running
it is no longer the arm that was validated; (2) on this venue the calendar's own
availability is **unmeasured** — the terminal's news base is 428 bytes, and the only
probe we could run (in the tester) was refused by the platform. So switching it on may
do nothing, or may stand the arm down until the source is real. The read is one line: if
`NEWS FILTER ON — source …: usable` appears in the Experts log, the calendar came back;
if it prints one of the phrases above, the gate is holding and **that is why there are no
entries**. `InpNewsRefreshHours=0` disables the refresh for an operator who supplies the
file some other way.

Parity is unaffected: the replay runs with the filter off, and `InpBarModel` **plus**
`InpUseNewsFilter` refuses at init, because the BAR engine cannot apply a rule the other
engine of record does not — a filter that silently does nothing is the one failure mode
this whole mechanism exists to prevent.

### It has been rehearsed on the compiled EA (2026-09-21)

```
python scripts\news_gate_rehearsal.py            # every state; ~90 s, five tester passes
```

That script writes each calendar state and runs a real pass, so the phrases above are
MEASURED rather than asserted. On 2026-09-08/XAUUSD it produced, in the EA's own journal:

| fixture | the EA said |
|---|---|
| file absent | `NEWS VETO: calendar file missing (MIDASTOUCH_news_calendar.csv)` |
| `# events=3` with one row | `NEWS VETO: calendar truncated (declares 3 events, holds 1) — refresh it` |
| `# events=0` | `NEWS VETO: calendar empty — an empty calendar is not "no news"` |
| generated 30 h before the pass | `NEWS VETO: calendar stale (45.8h old > 24h) — refresh it` |
| eight HIGH events, fresh | `NEWS FILTER ON — source …: usable`, two `NEWS VETO: news blackout: … (within 15 min)` on the bars that signalled inside a window, and a fill on the bar that did not |

Two real defects came out of running it, both of which every source-level test had passed:

1. **The EA could never judge a calendar fresh.** It keyed on `" epoch_generated_utc"`
   (the writers put a space after the `#`, and only the right-hand side was trimmed), so
   `gen` was always 0 and every file — including the eight-event one — was refused as
   "carries no generation time". A fail-closed gate with a broken reader is not a gate; it
   is a permanent stand-down that looks like policy.
2. **The tester driver's defaults still described the closed V75/Deriv program**
   (`V75MacroEngine` on `Volatility 75 Index`, M30, $10,000, 1:100). A caller launching
   this repo's gold EA through the driver got a config naming an instrument this venue does
   not offer: no pass ever started, and the failure looked like a slow machine for the full
   420 s timeout. The defaults now name this venue, this basis and a tick-covered window.

**Note while reading its output:** inside the strategy tester the EA's clock is the
SIMULATED window time, so a fixture's freshness must be stated in that frame — a calendar
stamped with the host's clock reads as the future there, and a "stale" fixture is judged
usable. The rehearsal anchors to the pass's own day for this reason.

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
