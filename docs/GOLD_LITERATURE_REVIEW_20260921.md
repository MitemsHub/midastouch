# What the trading literature says, and which parts of it this program can test

**Date:** 2026-09-21 · **Status:** survey + candidate list. One candidate is
pre-registered in `docs/GOLD_INTRADAY_MOMENTUM_PROTOCOL.md` before it was measured.

This file exists because the operator asked to mine an academic source for ideas. It records
what was read, what it claims, and — the part that matters — which claims are *decidable with
the data this venue can serve*. Literature is a prior, not an edge: nothing here overrides a
local test, and nothing here changes the standing verdict that the arm's own rule
(`artifacts/gold_wfo_ea.json`) is **NOT VALIDATED** (t = +1.07).

## How the papers were reached

`papers.ssrn.com` was the requested source. It **refuses automated clients by policy**, in its
own words:

```
GET https://papers.ssrn.com/robots.txt -> HTTP 403
Content Blocked
! We have detected that you may be using an automated script or search engine our site
  does not support. Please retry using an alternate way of accessing our site.
Contact Content_Protection_Services@Elsevier.com for more information.
```

That is an access-control decision, not a JavaScript challenge, so it is recorded and not
worked around — `scripts/research_fetch.py` stops at it. The same literature was then reached
over routes that permit fetching: author-hosted PDFs, NBER working papers, and conference
slides. Where a fetch was refused (SSRN itself; a PMC article returning 403), the tool says so
and the item is listed as **unread** rather than paraphrased from memory.

`scripts/research_fetch.py` is the reader. It honours `robots.txt` with longest-match/Allow-
wins precedence,refuses any page carrying a block-page or login-wall marker, sleeps between requests, caps a run at eight URLs, and never tries to look like a browser. It is a research
harness: no live entry point imports it (residue, by design).

## The four papers, and the claims taken from each

Read at abstract level plus the specific sections named; **not** read end to end, and the
per-asset-class tables were not extracted except where stated.

### 1. Baltussen, Da, Lammers & Martens (2021), *Hedging demand and market intraday momentum*, Journal of Financial Economics 142(1), 377–403

Verbatim from the abstract:

> Hedging short gamma exposure requires trading in the direction of price movements, thereby
> creating price momentum. Using intraday returns on over 60 futures on equities, bonds,
> commodities, and currencies between 1974 and 2020, we find strong market intraday momentum
> everywhere. The return during the last 30 minutes before the market close is positively
> predicted by the return during the rest of the day (from previous market close to the last
> 30 minutes). The predictive power is economically and statistically highly significant, and
> reverts over the next days.

Their buckets, from the data section: `FH` (first 30 min after the open), `M` (middle),
`SLH` (second-to-last 30 min), `LH` (last 30 min before the close). The paper reports the
effect as **distinct from intraday return seasonality** — `r_ROD` still predicts `r_LH` after
controlling for previous days' `r_LH` — and attributes it to gamma hedging demand from options
market makers and leveraged ETFs. It cites Heston et al. (2010) for half-hour return
seasonality persisting 1–40 days, and Barbon & Buraschi (2020) for gamma hedging driving both
momentum and reversal intraday in single stocks.

### 2. Ito & Hashimoto (2006), *Intra-day seasonality in activities of the foreign exchange markets*, NBER Working Paper 12413

From the abstract: the U-shape of intraday activity (deals and price changes) and of return
volatility is confirmed for Tokyo and London participants, **but not for New York**; activity
and volatility do not rise toward the end of New York business hours, even on Fridays. And on
the spread, the result this repo cares about:

> It is found that there exists a high positive correlation between volatility and activities
> and a negative correlation between volatility and the bid-ask spread. A negative correlation
> is observed between the number of deals and the width of bid-ask spread during business
> hours.

Coverage is USD/JPY and EUR/USD, not gold — so it is a *prior* about the shape of intraday
cost seasonality, not a gold measurement.

### 3. Iwatsubo, Watkins & Xu (2017), *Intraday seasonality in efficiency, liquidity, volatility and volume: platinum and gold futures in Tokyo and New York* (slides)

The only **gold-specific** item found. Findings taken from its results section:

- Each exchange is most liquid during its own day session; New York is **as liquid or more
  liquid than Tokyo in the gold market**; Tokyo spreads are roughly double New York's in
  platinum.
- Over the full day, TOCOM gold and platinum are dominated by **uninformed (liquidity) trading**,
  while the New York markets reflect both informed and uninformed trading.
- During the **New York day session, informed trading dominates for both metals**, and for gold
  that is *better supported* than for platinum; Tokyo is characterised as a liquidity traders'
  market.

### 4. Unread / refused

- SSRN search and abstract pages: 403, block page by policy (above).
- `pmc.ncbi.nlm.nih.gov/articles/PMC9759686/`: HTTP 403 (Cloudflare). Not read; not summarised.

## What this implies for *this* arm — and what is decidable

Tagged by whether the venue's own served data can settle it. The venue's series is
`data/forex/xauusd/XAUUSD_{M15,H1,D1}_upcomers.csv` — 179 stamped days, 2026-01-12 →
2026-09-18, M15 16,224 bars.

### A. The close-anchored momentum window is one this arm never trades — **decidable now**

The venue's day is not UTC-aligned, and the offset moves. From `configs/mt5/server_offsets.json`
(eras +60 min to 2026-03-31, +120 min from 2026-04-01) and the bars' own stamping (hour-23 has
one bar in the whole file; the last M15 stamp of a day is 22:45):

| | stamped | era −60 | era −120 |
|---|---|---|---|
| day opens | 00:00 | 23:00 UTC | 22:00 UTC |
| maintenance break | 23:00 | 22:00 UTC | 21:00 UTC |
| last M15 bar of the day | 22:45 | 21:45 UTC | 20:45 UTC |
| **last 30 min before the close** | 22:15–22:45 | **21:15–21:45 UTC** | **20:15–20:45 UTC** |

The arm's session is 06–20 UTC and it flattens by 22:00 UTC. So the paper's `LH` bucket is
**outside the session entirely**, and in the +120 era the arm's flat rule sits *after* the
venue's own break. If intraday momentum into this venue's close is real for gold, this arm has
never once been present for it. That is a single hypothesis with a defined sample: ~179 days,
one observation per day — pre-registered in `docs/GOLD_INTRADAY_MOMENTUM_PROTOCOL.md`.

### B. The trigger is a *reversion* rule run in the informed half of the day — **not decidable on this sample**

The EA's trigger (`iBands` touch-back-inside OR `iRSI` 30/70) is a mean-reversion entry, while
its macro filter (H1/H4 EMA20) is a trend filter. Iwatsubo et al. place reversion-friendly
liquidity trading in the Tokyo/Asian session and informed (continuation) flow in the New York
session. The arm trades 06–20 UTC — the London/NY half.

This was measured: `docs/GOLD_SESSION_HOURS_EA_VERDICT_20260921.md` found the 00–04 UTC block
carries a larger *share* of signals but the per-cell sample is **~37× short** of the declared
requirement, so no per-hour winner can be declared. The literature raises the question; it does
not answer it here, and neither can 174 days of one instrument.

### C. Cost seasonality is real in the model, absent in the strategy — **partially decidable**

Our cost model is already venue-measured rather than assumed: `midas_sweep` charges half the
bar's *recorded* spread each side, floored at `SPREAD_FLOOR = $0.10`. What no part of the
program does is condition any hour of the session on the cost/expected-move ratio — which is
the one lever Ito & Hashimoto's spread seasonality speaks to directly, and the lever that
matters most when the measured edge is +0.03–0.11R/trade against a toll of the same order.
Decidable only in part: spread-by-hour is in the bars, but deciding whether *any* hour's ratio
is better needs the same sample the session study lacked.

## The candidate list, ranked by what the literature supports and this repo can settle

| # | candidate | literature | sample available here | status |
|---|---|---|---|---|
| 1 | close-anchored intraday momentum into the venue's own day close | Baltussen et al. 2021 | ~179 days, 1/day | **pre-registered**, see protocol |
| 2 | hour-of-day cost filter on the existing rule | Ito & Hashimoto 2006; §C | spread by hour, 179 days | specifiable; edge per hour undecidable at this n |
| 3 | session split of the reversion trigger (Asia reversion vs NY continuation) | Iwatsubo et al. 2017; §B | 179 days | measured, **37× short** — not decidable |
| 4 | half-hour *seasonality* (same clock slot on previous days) | Heston et al. 2010, cited in #1 | 179 days × 92 slots | not pre-registered; multiple-comparison hazard is severe |

Nothing in this document authorises a preset, an input, or an arming change. Candidate 1's
result, whichever way it falls, is one measurement on one 8-month window of one instrument.
