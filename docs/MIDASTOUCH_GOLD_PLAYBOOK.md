# MIDASTOUCH GOLD PLAYBOOK — XAUUSD on the Upcomers $25,000 evaluation

**Account:** 1428765 @ Upcomers-Server (Upcomers Ltd.) · **Book:** $25,000
Thunderbolt Classic · **Instrument:** XAUUSD · **Status:** not armed.

Every number below is **measured on this account's venue** or is the venue's own
published rule, and each one names where it came from. Nothing here is imported
folklore, and nothing here claims an edge — see §6.

Sources: `docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` (measured cost-per-R, off
the live server), `docs/UPCOMERS_RULES_AUDIT_20260919.md` (the rule set, from
Upcomers' own Help Center), `artifacts/midas_history_20260920-upcomers.json` and
`data/forex/xauusd/XAUUSD_H1_upcomers.csv` (this venue's own bars, 2026-01-12 →
2026-09-18).

> **The Deriv-era gold playbook is retired.** That document measured a different
> broker, a different account and a `XAUUSD` quoted on a Deriv feed. None of its
> numbers apply here, and the `Synthetic Indices Bot` project folder it lived
> beside is a different repository. Do not carry its figures over.

---

## 1. The instrument on THIS account

| spec | value | source |
|---|---|---|
| symbol | `XAUUSD` (commodities → precious metals) | live server |
| contract size | 100 oz per 1.0 lot | live server |
| tick size / tick value | 0.01 / $1.00 per tick per lot | geometric check, settled with `order_calc_profit` |
| volume min / step | **0.01** / 0.01 | live server |
| **commission** | **$5 / lot / side → $10 round trip** = **0.229 bps** | Upcomers published schedule |
| measured spread | **1.073 bps** of price (≈ $0.47 at 4,376) | tick-derived mean, 365 d |
| ATR(H1, 180 d) | **23.04** | `docs/UPCOMERS_MEASURED_COST_RANK_20260919.md` §7c |
| **cost per R** (1×ATR stop) | **0.02473 R** | measured ranking |
| worst adverse gap | **3.10 ×** the 1-ATR stop | measured gap veto |
| risk granularity | one 0.01-lot step = **$2.30** | measured |
| account leverage | 1:100 (metals 1:30) | venue |

**The tick-value trap, already paid for once.** `tick_value / tick_size` and
`SYMBOL_TRADE_TICK_VALUE` both disagreed with the truth on this venue (`0.10`
where `order_calc_profit(1 lot, +$1.00)` returns `$100.00`). The EA now uses one
authority order — **settled > geometric > raw** — and **refuses** rather than
warning when they disagree. An intended $250 (1% of $25,000) stop was once sized
as $2,500 (10%): two thirds of the trailing budget in a single trade. Never
"fix" a sizing disagreement by editing a value; fix the authority that produced
it (`scripts/floor_zone.py`, `scripts/midas_fetch_history.py`).

---

## 2. Why gold, measured rather than assumed

`XAUUSD` is the cheapest instrument on this venue that can actually be sized,
and it is also the safest against gaps:

```
symbol      class    cost_R   spread_bps  comm_bps   atr     gap_p95%  gapX   lots  risk$  wknd
XAUUSD      metals  0.02473       1.073     0.229   23.04     0.879   3.10   0.33  76.03    no
UKOIL.c     indices 0.02751       2.720     0.000    1.03     4.426  11.22   0.07  71.82    no
USOIL.c     indices 0.03097       2.899     0.000    0.94     4.462   9.27   0.08  75.08    no
DJCUSD.c    indices 0.03491       0.773     0.000  114.42     0.516   7.38   0.07  80.09    no
NACUSD.c    indices 0.03583       1.196     0.000   98.85     0.751   4.25   0.08  79.08    no
```

`gapX` = worst **adverse** gap as a multiple of the 1-ATR stop; above 1.0 the stop
was gapped through. Everything cheaper than gold is either gappier
(`UKOIL.c` 11.22×, `USOIL.c` 9.27×) or unsizeable — `JPCJPY.c` is the cheapest
symbol on the venue at 0.0128R and is **excluded**: its minimum position is
**1.0 lot** = $208.91 of risk at a 1-ATR stop, 2.8× the per-trade budget. Its
cheapness and its untradeability are the same fact.

Supporting reasons, in the order they were established:

1. **USD-quoted**, so realised R is R — no second risk factor contaminating every
   right-hand side.
2. Its tightest spread is **13–18 UTC** (1.01–1.07 bps vs 1.13–1.16 in Asian
   hours), which is the US cash session — a session filter is free.
3. The widest stop of the liquid finalists (ATR 0.53% of price), which is *why*
   its gap breach multiple is lowest.
4. Finest risk granularity measured: a $75 target realised $76.03 (+1.4% error).
5. Smallest notional per trade of the finalists (~$14.4k), so the 3% daily limit
   never interacts with margin.
6. Two sessions (London + US), which spreads daily P&L — directly relevant to the
   Best Day rule.

---

## 3. The venue's rule set (as encoded, and what is still unverified)

| rule | value | character |
|---|---|---|
| profit target | **5% = $1,250** | challenge only |
| **daily drawdown** | **3% = $750**, 00:00–23:59 **UTC** | breach ends the account |
| **Dynamic Risk Shield** | **6% = $1,500**, trails the equity high-water mark, locks at the initial balance | breach ends the account; **open positions count** |
| max single trade loss | **3% = $750** | **UNVERIFIED** — see below |
| **Best Day** | **20%** | SOFT: delays payout only |
| minimum valid days | none for Classic (non-Turbo) | — |
| daily break / weekend | ~21:00–22:00 UTC; closed at weekends | gold is not 24/7 |

All four numeric gates are enforced in `PropGovernorBlock()` in
`mql5/MIDASTOUCH/MidastouchAI.mq5`, and they gate **entries only** — an open
position is never force-closed by the governor mid-life.

**The one number that is deliberately not modelled.** The 3% single-trade cap is
recorded from the Thunderbolt rules page but was **not re-confirmed** in the last
audit, and Upcomers' own pages contradict each other on it (3% on one page, 1.5%
on another). `src/midas_prop/risk/upcomers_rules.py` therefore refuses to
assume it: `risk_budget_usd()` takes it as an explicit parameter and prints
*"single-trade cap not modelled — verify the current rulebook"* when absent. **An
unverified number must not silently decide position size.** Confirm it from the
terminal's own rules dialog, in writing, before sizing on it.

---

## 4. Market-structure facts that shape the EA

1. **Gold is 24/5.** There is a ~1-hour daily break around 21:00–22:00 UTC and a
   weekend close. The only gap risk is Friday-close → Sunday-open (measured
   `gapX = 3.10`), which is why the protocol's standing policy is **flat over the
   weekend**.
2. **Holidays close gold entirely.** Not hardcoded — the EA's staleness guard
   (no fresh bar for N minutes ⇒ no trading) covers it generically.
3. **Volatility clusters** (13:00 vs 04:00 UTC ranges), so ATR-scaled stops are
   mandatory and fixed-dollar stops are malpractice.
4. **Swap is real and its figures are unverified.** Upcomers advertises
   swap-free, but every index and FX symbol checked reports `swap_mode = 1
   (POINTS)` with triple swap on Friday; `XAUUSD` reports `swap_mode = 9`, which
   is **not a documented MT5 swap mode**, so its carry is unverified. Measured
   per-night bleed on the symbols we could read: `XAUUSD` ≈ 2.7% of R,
   `NACUSD.c` 5.0%, `SPCUSD.c` 7.0%, `DJCUSD.c` 8.9%. **Consequence: design
   intraday-first and confirm gold's carry from the terminal spec dialog before
   permitting any overnight hold.**
5. Research timeframes are **H1 (regime) + M15 (trigger)**; D1 on this venue is
   reference-only (only 179 bars, 2026-01-12 →).

---

## 5. Standing policies for every MIDASTOUCH build

- **ATR-scaled stops** from the H1 anchor; never fixed-dollar.
- **Spread-cap veto:** no entry when spread > 1.5% of stop distance.
- **News stand-down:** no new entries in a ±15-minute window around top-tier USD
  releases; open positions are managed, not opened. Implemented as a fail-closed gate
  on the entry path in `MidastouchAI.mq5`, fed by a shared calendar file
  (`MQL5\Files\MIDASTOUCH_news_calendar.csv`) that the EA refreshes itself and
  `mql5/MIDASTOUCH/MidasNewsProbe.mq5` measures. An unusable source — missing, stale,
  not covering now, truncated, or **empty** — vetoes entries and names which it is: an
  empty calendar means "we cannot see the news", never "no news". It ships **off**
  (`InpUseNewsFilter=false`) in every preset, because the certified corpus was measured
  without it; the health guide §5a states what turning it on costs and proves.
- **Session gate:** entries only inside the declared UTC activity band; Friday
  after the cutoff = flat unless the position is in profit and trailing.
- **Weekend:** nothing held over the weekend by default.
- **Sizing:** risk % of equity via the symbol's own tick value, with the
  geometric identity check pinned against the broker's settled value, the
  min-lot floor disclosed, and the floor table printed at init.
- **Paper mode is the default state, forever**, until a frozen gate says
  otherwise — and arming is an **arming-record event**, never an input edit.

---

## 6. What the playbook does NOT claim

**No claim about any strategy's edge.** That is the walk-forward gate's job, under
`docs/GOLD_WFO_PROTOCOL.md`, and it has not been passed.

The honest arithmetic, stated plainly: the only edge this program has ever
measured is V75's **+0.027R/trade gross**, and gold's toll here is **0.0247R —
still 92% of that entire edge**, before a single losing trade. Instrument
selection is finished and its answer is that **it was never the bottleneck**.

> A demonstrated edge on this venue's own data is the only thing that can change
> that. Until one passes the out-of-sample gate, the correct output of every gate
> in this repository remains **"do not arm."**
