# The first live fill, audited — 2026-09-22

**The question.** The arm's only live fill came back from the venue with `magic 0` and the ledger
recorded it as `EXTERNAL`. Why wasn't the EA's own exit the thing that closed it, and what would have
to be true for it to be?

**The answer, one line.** Because an order the venue attributes to the **MetaTrader *mobile*
application** closed it **6 min 37 s** after entry at +0.104R, while every exit the arm owns was still
out of reach: the server-side SL/TP were **0.95 % / 1.90 % of price** away and the timeout was
**12 hours** away.

---

## 1. The venue's record — the only party that knows why

`mt5.history_deals_get(position=18874164)` and `mt5.history_orders_get(position=18874164)`, read
2026-09-22. Times as the venue stamped them (server = UTC+2), with UTC beside.

| | ticket | side | price | time | magic | reason | comment | $ |
|---|---|---|---|---|---|---|---|---|
| **in** | 18137411 | sell 0.01 | 4333.07 | 16:00:00 (14:00:00Z) | **7825001** | **3 = EXPERT** | `MIDAS` | commission −0.05 |
| **out** | 18138688 | buy 0.01 | 4328.76 | 16:06:37 (14:06:37Z) | **0** | **1 = DEAL_REASON_MOBILE** | *(empty)* | **+4.31** |

| order | state | sl | tp | magic | reason |
|---|---|---|---|---|---|
| 18874164 (the position's own order) | filled | **4374.38** | **4250.77** | 7825001 | 3 |
| 18875539 (the close) | filled | 0 | 0 | **0** | **1** |

Read those four rows together, because they are the whole answer:

* the **entry** carries our magic, our comment and `reason 3` — that is what this EA's orders look
  like in the venue's history;
* the **exit** carries **none of it**: magic 0, an empty comment, and a reason code that means the
  order was placed from a *mobile* application. It is not an SL, not a TP, not a stop-out, and not the
  EA;
*  the closing price **4328.76 is inside both** levels the EA set — 45.62 short of the SL, 77.99 clear
  of the TP — so no protective order fired and no level was touched. SL distance from entry was
  41.31 (0.953 % of price), TP 82.30 (1.90 %); the trade ended 4.31 favourable, `+4.31 / 41.31 =
  +0.104R`.

## 2. Timeline of the position's life (terminal journal + ledger, measured)

| UTC | what the machine recorded |
|---|---|
| 14:00:00 | EA opens SHORT 0.01 @ 4333.07 (signal bar 13:45); SL 4374.38 / TP 4250.77 placed **server-side**; risk $41.20; journal `LIVE FILL SELL vol=0.01 … retcode=10009`, and (v1.25's subject) the row went out with a 0.00000 price to be healed later by an `LENTRY` row |
| 14:01:40 | a **second terminal instance** starts from `config\v75_regress_midas_tickcov_rd_rd.ini` — the parity harness's tester config (`Expert=MIDASTOUCH_parity\MidastouchAI`, `ShutdownTerminal=1`); the account reports **1 position** open |
| 14:02:34 | that instance shuts itself down (`ShutdownTerminal=1`); 13 s later the arm's terminal is relaunched from `midas_attach.ini` — artifact `midas_parity_result_20260922_1502.json`, `ts 14:02:45Z`, `PASS` |
| 14:03:10 | EA re-initialises and **re-adopts the live position**: `LIVE RECOVERED ticket=18874164 dir=-1 entry=4333.07000 SL=4374.38000 TP=4250.77000` |
| 14:06:37 | the venue fills order 18875539 (BUY 0.01 @ 4328.76, magic 0, reason MOBILE); the EA sees the position gone **within the same second** and writes `LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104` |
| 14:25:29–14:26:03 | the same tester instance again, after the trade was closed — artifact `…_1526.json`, `ts 14:26:14Z` |

## 3. Why the arm's exit never had a chance

The EA owns exactly **three** exits, and only two of them are the EA's own actions:

1. **SL / TP**, placed on the venue at entry (`LiveSendOrder`) — server-side, so they fire whether or
   not the terminal is running. Distances above: 0.95 % and 1.90 % of price.
2. **Timeout** — `InpTimeoutMinutes = 720` compared on real UTC (`TimeUTCNow() >= g_lv_expiration`) →
   `LiveClosePosition("TIMEOUT")`. Expiry for this fill was **02:00Z the next morning**.
3. **Friday flat** — `LiveFridayFlatCheck()`. The fill was opened on a Tuesday.

And one thing that is **not** an exit, worth stating because it is a natural assumption: the governor
does **not** flatten. `PropGovernorBlock()` (the daily cap, the shield, the best-day ceiling) is
consulted on the **entry** path only — while the arm holds a position, `LiveOnTick` calls
`LiveCheckExits()` and returns. The breaker can refuse the *next* trade; it has no path that closes an
open one.

The trade therefore needed to survive to 02:00Z, or reach a 0.95 % adverse / 1.90 % favourable move,
to meet the EA at all. It survived 6 minutes 37 seconds.

## 4. What it would take for the EA's exit to be the one that closes a trade

All four of these, and each is stated with what is *measured* versus what is *expected*:

1. **Nothing external closes it first.** The venue accepts a mobile/web/desktop order on this account
   and the EA has **no veto** — it can only reconcile. Unmeasured until it happens: whether the
   platform reports an *EA* close (which would be `reason 3` + our magic, exactly as the *entry* deal
   does) and an *SL/TP* close (expected `reason 4`/`5`) as cleanly distinct in the closing deal.
   **What would measure it:** the first such exit. The parity harness's `--live-stance` pass closes
   trades in the *tester*, which exercises the same code path but produces no venue attribution at all.
2. **The position reaches one of the three exits.** 0.95 % / 1.90 % of price, or 12 hours. At this
   arm's sizing (0.01 lot, `$41.20` at risk on a $62.50 budget) the stop is a real 0.95 % move, so this
   is not the constraint — the constraint is (1).
3. **For the two exits the EA executes, the chart must be up.** The timeout and the Friday flat are EA
   actions: terminal running, chart attached, AutoTrading on, `InpLiveExecution` true. (The SL/TP exits
   need none of that — that is the point of placing them at the venue.)
4. **And the record has to be able to say which happened** — see §5, where it cannot.

## 5. The record gap this exposed: `EXTERNAL` is two different events

`LiveCheckExits()` handles the closed-underneath-us case by reading the OUT deal's **price** and
writing a fixed word:

```cpp
PrintFormat(VersionTag() + "LIVE EXTERNAL CLOSE exit=%.5f R=%+.3f", exit, r);
PaperLog(StringFormat("LCLOSE,%I64d,%I64u,EXTERNAL,%.5f,%.3f", (long)TimeCurrent(), g_lv_posid, exit, r));
```

It never reads `DEAL_REASON` or `DEAL_MAGIC`. So **"my stop was hit" and "a human tapped Close on
their phone" produce the same row** in this program's own record — and the distinction between them is
the first thing an operator asks about a live fill. It currently lives only in the venue's history,
i.e. outside the artifact this repo keeps as the evidence of record.

The additive fix, for whenever a build is next shipped: in that branch, select the OUT deal and write
its reason word and whether its magic was ours — `SL` / `TP` / `SO` / `EXPERT` / `MANUAL-mobile` /
`MANUAL-web` / `MANUAL-desktop` (reasons 4/5/6/3/1/2/0, mapped through the same constants
`MetaTrader5` exposes) — into the row's existing `reason` field. Append-only, one field, display-only
by construction; it needs a compiler, a parity certificate and a version bump, which is why it is a
proposal here and not a change.

## 6. What this audit also turned up: the certification run stopped the live terminal **with the
position open**

§2's first two rows are not incidental. A full parity certification run happened **1 minute 40
seconds after the live fill, while the position was open** (artifact `…_1502`, `PASS`), and its
sequence is *stop the terminal → run the tester → relaunch the arm*. The position survived because the
EA's stop and target sit at the venue and the EA re-adopts the position on re-init (`LIVE RECOVERED`).
What the arm did **not** have for those ~67 seconds is the only thing it executes itself: the timeout
and the Friday-flat flatten.

Why the gate that exists to prevent exactly this did not fire — `midas_parity.py`, 3068:

```python
arms = R.inventory_arms(data_folder)      # chart PROFILES only — this arm is start-up-attached
flat, bad = R.verify_all_flat(arms)       # []  →  (True, [])   →  gate passes, vacuously
```

The arm is attached by `config\midas_attach.ini`, so it appears in **no** chart profile, so the
inventory is empty, so the flat-check reports `flat-check OK (0 gold arm book(s) on the terminal)` —
an honest count of the books it could look at and a false statement about the books that exist. The
live book (`MIDASTOUCH_paper_XAUUSD_U25.csv`) is not read by this gate. `verify_all_flat`'s own
docstring names the trap — *"An EMPTY arm list returns `(True, [])`. Callers must therefore treat 'no
arms inventoried' as its own finding … zero books is not the same as zero open trades"* — and the
watchdog does treat it that way; this caller does not.

The one-line direction of the fix, for the same future build: discover the arms the way every other
tool does (`startup_attached_arms` ∪ `inventory_arms`) and **refuse when the inventory is empty**,
because "I could not see any book" and "there is no open book" are different answers and only one of
them is safe to stop a live terminal on.

## 7. What is NOT claimed

* **Not claimed: who placed the mobile order, or why.** The venue says *mobile application*; it does
  not say whose hands. The account's own authorization log shows one client address
  (`143.105.174.121`) for the whole morning and a second (`102.91.102.195`) only from ~15:37Z — so the
  14:06:37Z close came from the **same public address the desktop terminal used**, which is exactly
  what a phone on the same network looks like. MT5's mobile client keeps its own log on the device;
  nothing on this machine can be asked. A broker-side action would not read `MOBILE`; an SL/TP would
  read 4/5.
* **Not claimed: that the close was a mistake.** It is on the venue's record and on the account
  (+$4.31); this document reports what happened, not whether it should have.
* **Not claimed: that the tester run closed the position.** A Strategy Tester session cannot send an
  order to the live account, and this one ran `InpLiveExecution=false` with its own magic 7801001. It
  is in this audit because of *when* it ran, not because of what it did.
* **Not claimed: that any of this is a strategy result.** One fill, closed by hand, is a story about
  the plumbing. It says nothing about the arm's expectancy, which remains **NOT VALIDATED**.

## 8. Reproduced by

```bash
# the venue's attribution (read-only)
python -c "import MetaTrader5 as mt5; mt5.initialize(); \
print(mt5.history_deals_get(position=18874164)); print(mt5.history_orders_get(position=18874164))"
# the arm's journal for the window, and the ledger's own rows
grep -n "LIVE \|EXTERNAL" "…/MQL5/Logs/20260922.log"
grep -n "^LOPEN,\|^LCLOSE,\|^LENTRY," "…/MQL5/Files/MIDASTOUCH_paper_XAUUSD_U25.csv"
# the certification runs that bracketed it
python -c "import json; print(json.load(open('artifacts/midas_parity_result_20260922_1502.json'))['ts'])"
```

---

## 9. Addendum, same evening: what was built in response (v1.29 and the flat gate)

Three things this audit prescribed were implemented the same evening:

1. **The exit-reason word** (v1.29, `+exit-reason` in the ERA note): §4's gap — "`EXTERNAL`
   is two different events" — is closed. The adoption scan now reads `DEAL_REASON` and
   `DEAL_MAGIC` and writes `SL`/`TP`/`SO`/`EXPERT`/`MANUAL-CLIENT`/`MANUAL-WEB`/
   `MANUAL-MOBILE`, with `EXTERNAL-UNKNOWN` as the only fallback. Precedence is WHO
   (magic) before WHAT (reason), pinned in `tests/test_midas_v129_record.py`. Had this
   build been live today, the 14:06:37Z row would have read
   `LCLOSE,…,MANUAL-MOBILE,4328.76000,+0.104` — the audit's central fact on the ledger
   instead of in a forensic session. No decision function reads the word; it is written
   for the operator and the record.
2. **The flat gate of §5 is no longer vacuous.** The parity harness's flat check now
   (a) discovers arms from the attach-config path — the start-up-attached arm this audit
   caught never appears in `Profiles`, so profile-derived inventory was empty by
   construction; (b) refuses when the arming record names an arm but discovery finds no
   book to check — no more `verify_all_flat([])` vacuous truth; (c) takes a **second
   witness**: `mt5_ops.venue_open_position_count()` reads the venue's actual position book
   directly and attributes each position by its IN deal's magic, so
   ledger-flat-but-venue-open refuses, and an unanswerable venue refuses rather than
   passing. The certification runs that stopped the terminal under this arm's open
   position (§5) cannot pass that gate again.
3. **The first certification run under the fixed gate** produced the v1.29 parity PASS
   (`artifacts/midas_parity_result_20260922_2311.json`, same nine trades, max|dR| 0.0004,
   0 over tolerance): the gate's discovery printed the arm's book, the venue cross-check
   agreed at 0 open positions, and only then did the run stop the terminal.

The word that would have changed today's story: the ledger row for the external close now
splits the two events §4 found merged. `SL` and `MANUAL-*` can never be confused again —
and the question this audit had to answer by reading the venue's deal history is now
answered by `grep LCLOSE`.
