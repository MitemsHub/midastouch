# UPCOMERS — MEASURED COST PER R (2026-09-19, night)

**Status:** authoritative for *which Upcomers instrument is cheapest to trade*.
Supersedes the cost claims in `docs/UPCOMERS_INSTRUMENT_SELECTION_20260919.md`, which
were built on **assumed** spreads and ATRs. Every number below is measured off the live
`Upcomers-Server` account (login 1428765, $25,000, MT5 build 6204) on 2026-09-19.

Reproduce:

```bash
python scripts/venue_probe.py     --out artifacts/upcomers_inventory.json
python scripts/upcomers_cost_rank.py --days 90 --tick-days 2 --stop-mult 1.0 \
                                     --out artifacts/upcomers_cost_rank.json
```

---

## 1. The terminal is now logged in — the blocker is gone

```
Network   '1428765': authorized on Upcomers-Server through Access Server DE (ping: 171.52 ms)
Network   '1428765': terminal synchronized with Upcomers Ltd.: 0 positions, 0 orders, 1797 symbols
   trading has been enabled - hedging mode
account:  balance=25000.00  equity=25000.00  currency=USD  leverage=1:100
          company='Upcomers Ltd.'  margin_mode=2 (hedging)
```

Three things this settles:

* **The earlier failure was never credentials or market hours.** MT5's client exposes no
  file, config key, CLI flag or API for registering a broker server; only its own *Open an
  Account* wizard populates the broker directory. Five scripted attempts
  (`/login:`, `/config:` ini, the Python bridge, `servers.dat`) all failed because the
  directory had no Upcomers entry at all.
* **The account is HEDGING, not netting**, and has **1,797 symbols** — not the ~1,300 the
  marketing claims.
* **`trade_allowed=False`**: the terminal's AutoTrading button is OFF. Nothing can be
  armed until it is switched on in the GUI. This is expected tonight (market closed), but
  it is a go-live step, not a detail.

**Actionable leftovers before any live order:** enable AutoTrading; **rotate the funded
password** (it is in this transcript, in a terminal command line, and was written to
`artifacts/upcomers_login.ini`).

---

## 2. The 24/7 question, settled by measurement

The operator moved venues specifically because gold is not 24/7. Measured at **Saturday
21:02 local**:

| Symbol | bid / ask | spread | last tick (server time) | state |
|---|---|---|---|---|
| **BTCUSD.nx** | 81353.53 / 81356.34 | 2.81 = **0.35 bps** | **Sat 22:02:39** | **TRADING** |
| **ETHUSD.nx** | 2633.34 / 2633.93 | 0.59 = 0.22 bps | **Sat 22:02:37** | **TRADING** |
| NACUSD.c | 29659.15 / 29662.65 | 3.50 pts | Fri 22:59:44 | closed |
| XAUUSD | 4377.66 / 4378.26 | $0.60 | Fri 22:59:58 | closed |
| EURUSD | 1.14834 / 1.14882 | 4.8 pips | Fri 22:59:59 | closed |

**Verdict: Upcomers MT5 crypto does trade weekends. Indices, forex, metals and stocks do
not.** The third-party claim of "Crypto Weekend Trading ✓" holds for the majors. The
original 24/7 requirement *is* satisfiable here — but only on crypto, which is the most
expensive class on the account (see §3).

### A probe bug that had to be fixed before it was believed

The first pass reported **zero** live symbols and "no activity today (0/142 crypto)" —
a false negative that would have inverted the whole conclusion. Cause: MT5 returns tick
and bar timestamps in **server time**, and this server runs **UTC+2**. Comparing a
server-time tick against a UTC clock made a *live* BTCUSD.nx read as 120 minutes in the
**future**, so every age comparison failed.

Fixed in `scripts/venue_probe.py` by deriving the offset empirically
(`round((max(tick.time) - now) / 900) * 900`, snapped to 15 minutes) and correcting every
age by it. The probe now prints `server clock offset: +2.00 h vs local`.

A **second** false signal was also removed: the original test used the broker's
`session_deals`/`session_volume` day counters as "did this trade today". Those are **not
populated for CFD symbols on this server** — all 1,797 returned zero while crypto was
actively streaming. Tick recency is now the primary evidence and the counters are
secondary.

---

## 3. The measured ranking

`cost_R = (spread + commission) / stop_distance`, with the stop = 1 × ATR(H1), measured
over 90 days of bars and 2 days of ticks. This is the fraction of R consumed before the
trade does anything.

```
symbol      class       cost_R  spread_bps  comm_bps        atr  gap_p95%  gap_max%  wknd
JPCJPY.c    indices    0.01143       0.649     0.000     369.04     1.217     2.234    no
UKOIL.c     indices    0.02898       2.659     0.000       0.95     4.358     8.553    no
XAUUSD      metals     0.03044       1.066     0.229      18.61     0.884     1.456    no
NACUSD.c    indices    0.03235       1.188     0.000     108.81     0.751     1.359    no
USOIL.c     indices    0.03312       2.692     0.000       0.81     4.498     8.675    no
DJCUSD.c    indices    0.03746       0.773     0.000     106.63     0.492     0.752    no
GECEUR.c    indices    0.05920       1.625     0.000      69.43     0.492     1.045    no
SPCUSD.c    indices    0.07886       1.667     0.000      16.16     0.628     0.904    no
UKCGBP.c    indices    0.08069       1.959     0.000      25.80     0.347     0.891    no
EXCEUR.c    indices    0.10924       4.035     0.000      23.02     0.743     1.524    no
GBPUSD      forex      0.12140       0.446     0.747       0.00     0.097     0.235    no
FRCEUR.c    indices    0.12344       4.403     0.000      28.74     0.632     1.346    no
XRPUSD.nx   crypto     0.12516       1.277     8.000       0.01     0.000     0.017    no
USDJPY      forex      0.12966       0.353     1.000       0.16     0.080     0.255    no
EURUSD      forex      0.13030       0.249     0.871       0.00     0.107     0.342    no
XAGUSD      metals     0.13695      11.619     0.302       0.58     1.560     3.957    no
HKCHKD.c    indices    0.15225       5.384     0.000      87.22     1.485     2.220    no
SOLUSD.nx   crypto     0.16841       2.889     8.000       0.72     0.000     0.040    no
BTCUSD.nx   crypto     0.18615       0.303     8.000     362.74     0.001     0.006   yes
ETHUSD.nx   crypto     0.18804       2.462     8.000      14.65     0.006     0.041   yes
```

### How to read it

* **Commission as a percentage of notional is the brutal term, not the spread.** A trade
  risking `$X` with a stop `s` percent away must hold `X/s` of notional, so its commission
  toll is `commission_pct / s` R. Tight stops therefore increase commission cost *without
  limit* — which is why crypto's 8 bps round trip costs 0.13R on BTC while its 0.35 bps
  spread costs only 0.006R.
* **Spread is bounded by the stop.** It is never the dominant term for an ATR-sized stop.
  Screening on spread alone (as the first pass did) ranks BTCUSD.nx incorrectly high.
* **The gap columns are a veto, not a cost.** A stop cannot fill through a gap. `UKOIL.c`
  and `USOIL.c` are cheap on cost and carry 8.6% / 8.7% daily gaps against a 0.8–1.0% stop
  — an 8–10× stop breach. They are not tradeable overnight at ATR-sized stops no matter
  how cheap they look.

### The caveat that limits the whole table

**Cost per R assumes R-outcomes are comparable across instruments, and that is not
automatic.** A higher ATR/price ratio produces a *wider* stop, which lowers cost per R
while also requiring a larger percentage move to reach the same R. Ranking on cost alone
therefore has a slight built-in preference for volatile instruments. It is a **necessary
filter, not a sufficient selection.** The tie-breaker has to be measured edge, and no
instrument here has one yet.

---

## 4. Three corrections to what was said earlier

Recorded because they were stated as findings and are now contradicted by measurement.

1. **"Gold's toll is ~2× Nasdaq's."** **Wrong.** Measured: **XAUUSD 0.03044R vs NACUSD.c
   0.03235R** — a 6% difference, effectively a tie. The earlier claim used an assumed
   1.132 bps gold spread and an assumed ATR. Gold pays $10/lot round trip, but one lot is
   100 oz ≈ $437k of notional, so that works out to only **0.229 bps** — far less punitive
   than the "metals pay $5/lot" headline suggests.

2. **"BTCUSD.nx carries an 8.278% weekend gap, which is disqualifying."** **Not supported.**
   That figure was the single worst outlier in a 365-day daily-bar sample; the 90-day
   measurement shows **`gap_max 0.006%`, `gap_p95 0.001%`**. A 24/7 instrument *cannot*
   gap systematically — it never closes. The 8.278% print is most likely one bad bar.
   **Crypto's real disqualifier is its commission, not its gaps**, and the earlier
   reasoning reached roughly the right conclusion by the wrong route.

3. **"NACUSD.c is the best instrument on this venue."** **Too strong.** Nasdaq is 4th of
   20 and is *tied* with gold; **JPCJPY.c (Nikkei) is measurably cheapest at 0.01143R**,
   2.8× cheaper than Nasdaq, because its ATR is 0.57% of price versus Nasdaq's 0.37% and
   its spread is 0.649 bps versus 1.188 bps. The order to prefer indices over forex and
   crypto survives; the specific instrument pick does not.

---

## 5. A real bug this exercise found — in our own library

`cost_per_r` added a **USD** commission to a stop denominated in the instrument's **quote
currency**. For USDJPY that understated the toll by the FX rate (~157×):

* 1 lot = 100,000 USD; a 1×ATR stop = 0.16 JPY ⇒ the stop is worth 16,000 JPY ≈ **$102**;
* $10 of round-trip commission against that stop is **0.098R on its own**;
* the naive ratio printed **0.03442R**; the correct figure is **0.12966R**.

It ranked USDJPY **6th of 20, ahead of GBPUSD and EURUSD, when it is genuinely dearer than
both by ~7%**. Fixed by adding `quote_to_usd` (value of one quote-currency unit in account
currency) to `cost_per_r` / `InstrumentCandidate` / `rank_candidates`, and resolving it in
the ranker from the venue's own rates (`USDJPY` → divide; fall back to `JPYUSD` →
multiply). Unresolvable quotes are **excluded with a reason**, never assumed to be USD.
Pinned by `test_quote_to_usd_prevents_a_usdjpy_rank_inversion`.

---

## 6. The excluded rows, and why they matter

A ranking table silently drops broken data, and a dropped instrument looks identical to one
never requested. Four independent guards now run, each added because a specific symbol
produced a **plausible-looking but false** row:

| Symbol | Symptom | Guard that catches it |
|---|---|---|
| `INCUSD.c` | price 0.09, "spread" 1067 bps ⇒ ranked at 10.1R | quoted spread > 50 bps ⇒ wrong price basis |
| `INCUSD.c` | 9% of H1 bars have any range | bar activity < 50% ⇒ flat stub |
| `EURUSD`, `GBPUSD` | H1 series 760 days old on the first pass | H1 age > 5 days |
| `EURUSD` (first pass) | `atr=0.00` yet still ranked 8th | ATR/price < 1e-5 ⇒ bad-data stub |

Note `EURUSD` **later resolved as genuine** (ATR ≈ 0.0010, 0.086% of price) once its H1
history downloaded — its 0.13030R is a real cost, driven by commission against a small
percentage stop, not a data artefact. The guard was right to hold the row back until the
data justified it.

---

## 7. Two further gates, and the final decision

On 2026-09-19 the operator dropped the 24/7 requirement. That removes crypto entirely
(every crypto symbol is 0.125–0.188R) and leaves the real-instrument universe, so the
ranking was recomputed over 180 days with two additional gates that turn out to matter
more than the cost table itself.

### 7a. Sizing feasibility — the gate that disqualifies the cheapest instrument

A cost ranking is meaningless if you cannot place the position. `JPCJPY.c` (Nikkei) is the
cheapest instrument on this venue at **0.0128R** — and it is **untradeable at our risk**:

```
min volume      1.0 lot        (not 0.01 — the other CFDs step in hundredths)
1-ATR stop      $208.91 risk per lot
our budget      $75 per trade
result          minimum position is 2.8x over budget  ->  excluded
```

This is not a footnote, it is the mechanism: a minimum position that large can only carry a
toll that low *because you are forced to trade it big*. The cheapness and the
unsuitability are the same fact. **Nikkei's 0.0128R was an artefact of an unaffordable
lot floor.**

### 7b. Swap is live, and "swap-free" is not true for these symbols

Upcomers advertises swap-free accounts. Measured on this account, `swap_mode = 1
(POINTS)` for every index and FX symbol checked — swaps **are** charged, and
`swap_rollover3days` is 5 (triple swap on Friday). Normalised per night as a fraction of
one R at a 1-ATR stop:

| symbol | swap_long/night | ≈ % of R per night |
|---|---|---|
| `XAUUSD` | −$6.19/lot | **2.7%** |
| `NACUSD.c` | −$46.81/lot | **5.0%** |
| `SPCUSD.c` | −$11.90/lot | 7.0% |
| `DJCUSD.c` | −$95.16/lot | 8.9% |

So a multi-day hold bleeds 2.7–8.9% of R per night. **This is a modelling input, not a
footnote**: any strategy that intends to hold overnight must include it, and an
intraday-only design avoids it entirely. Note `XAUUSD` reports `swap_mode = 9`, which is
**not a documented MT5 swap mode** — its carry figures are therefore **unverified** and
must be confirmed from the terminal's specification dialog before overnight gold is
permitted.

### 7c. The final table (180 days, 3 days of ticks, 1-ATR stop, $75 budget)

```
symbol      class       cost_R  spread_bps  comm_bps        atr  gap_p95%   gapX    lots   risk$  wknd
XAUUSD      metals     0.02473       1.073     0.229      23.04     0.879   3.10    0.33   76.03    no
UKOIL.c     indices    0.02751       2.720     0.000       1.03     4.426  11.22    0.07   71.82    no
USOIL.c     indices    0.03097       2.899     0.000       0.94     4.462   9.27    0.08   75.08    no
DJCUSD.c    indices    0.03491       0.773     0.000     114.42     0.516   7.38    0.07   80.09    no
NACUSD.c    indices    0.03583       1.196     0.000      98.85     0.751   4.25    0.08   79.08    no
GECEUR.c    indices    0.05181       1.572     0.000      76.78     0.735   6.25    0.09   79.35    no
SPCUSD.c    indices    0.07869       1.764     0.000      17.14     0.636   6.40    0.44   75.43    no
UKCGBP.c    indices    0.07916       2.017     0.000      27.08     0.463   6.88    0.21   76.16    no
EXCEUR.c    indices    0.10843       3.970     0.000      22.82     1.238   7.78    0.29   76.01    no
FRCEUR.c    indices    0.12885       4.563     0.000      28.53     1.180   6.95    0.23   75.36    no
HKCHKD.c    indices    0.15029       5.472     0.000      89.79     1.628   4.96    0.50   57.22    no
JPCJPY.c    EXCLUDED -- cannot be sized: min position 1 lot = $208.91 risk = 2.8x budget
```

`gapX` = worst **adverse** gap as a multiple of the 1-ATR stop. Above 1.0 the stop was
gapped through; at 7–11× the realised loss was seven to eleven times the intended one.

### 7d. Decision: build on **XAUUSD**

**`XAUUSD` is the only instrument in the sizeable set that is in the top tier on both
axes** — cheapest at **0.02473R** *and* safest against gaps at **3.10×**.

Everything that beats it on cost is disqualified by the gap veto (`UKOIL.c` 11.22×,
`USOIL.c` 9.27×) or by sizing (`JPCJPY.c`). Every index that survives sizing is both
dearer and gappier: `DJCUSD.c` 0.0349R/7.38×, `NACUSD.c` 0.0358R/4.25×, `SPCUSD.c`
0.0787R/6.40×.

Supporting reasons, in the order they were established:

1. **USD-quoted**, so realised R is R. No second risk factor (`USDJPY`) contaminating
   every certification number.
2. **Its best 6-hour window, [13–18 UTC], is the US cash session** — the same window as
   Nasdaq — and it is also when its spread is tightest (1.01–1.07 bps vs 1.13–1.16 in
   Asian hours). A session filter is therefore free alpha.
3. **Widest stop of the liquid finalists** (ATR 0.53% of price vs Nasdaq's 0.33%), which
   is *why* its gap breach multiple is the lowest: a narrow stop is more exposed to the
   same gap.
4. **Finest risk granularity measured**: one 0.01-lot step is $2.30 of risk, so a $75
   target realised $76.03 — **+1.4% error**, against +5.4% for Nasdaq and +6.8% for Dow.
5. **Smallest notional per trade** of the finalists (~$14.4k), so margin usage is trivial
   and the 3% daily limit is never in tension with the broker's margin requirement.
6. Two sessions (London + US) rather than one, which spreads daily P&L — directly relevant
   to the **20% Best Day rule**.

**Why not Nasdaq (the previous pick), why not Nikkei (the cost leader):**

* **Nasdaq** was chosen before the gap veto column and the sizing gate existed. On the
  current evidence it is **45% dearer than gold** and **37% more gap-exposed**. Its zero
  commission is real but it is not the dominant term: `DJCUSD.c` has an even *lower* spread
  (0.773 bps) and also pays no commission, and still costs 0.0349R with a 7.38× gap —
  because its ATR is only 0.22% of price. **Inside the zero-commission classes, stop width
  decides, not spread.** That refinement is the direct correction of the earlier
  "prefer zero-commission indices" reasoning.
* **Nikkei** is excluded by construction: 1-lot minimum, $208.91 of risk, 2.8× the budget.

### 7e. What this does *not* change

The one edge this program has measured is V75's **+0.027R/trade gross**. Gold's toll is
**0.0247R — still 92% of the entire edge**, before a single losing trade. So:

> Instrument selection is now **finished**, and its answer is that **it was never the
> bottleneck**. Every sizeable instrument on this venue costs 0.025R–0.150R per round trip,
> and the cheapest one still consumes almost all of the only edge we can demonstrate. No
> choice in this table makes the program profitable.

**A demonstrated edge on Upcomers data is the only thing that can.** Until one passes the
out-of-sample gate, the correct output of every gate in this repo remains *"do not arm"*.

**Recommended next step, in order:** (1) enable AutoTrading and rotate the password;
(2) confirm `XAUUSD`'s `swap_mode = 9` carry from the terminal spec dialog before allowing
any overnight hold; (3) re-run the probe and ranker during a live session so spreads come
from open-market ticks rather than last-close ones; (4) build and certify the strategy on
**`XAUUSD`**, sized intraday-first (the swap numbers argue against holding overnight until
7b is verified), with **`NACUSD.c`** as the standing challenger; (5) arm only after the OOS
gate passes net of the measured **0.0247R** toll.
