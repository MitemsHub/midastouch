# MIDASTOUCH GOLD PLAYBOOK — XAUUSD on Deriv MT5 (measured 2026-09-16)

Every number below is measured on **our broker's feed, our account** — not
imported folklore. Sources: `artifacts/deriv_symbols_20260916.json` (live
specs) and `data/forex/xauusd/XAUUSD_H1.csv` (14,414 continuous bars,
2024-04-10 → 2026-09-16, validated in `artifacts/midas_history_20260916.json`).

## 1. The instrument on OUR account (login 140778269, DerivSVG-Server-03, 1:1000)

| spec | XAUUSD (standard) | XAUUSD |
|---|---|---|
| point / tick size | 0.01 | 0.01 |
| tick value | $1.00 per 0.01 move per **1.0 lot** (⇒ 100 oz contract) | $0.01 per 0.01 move per 0.1 lot (⇒ 1 oz/lot basis) |
| volume min / step | 0.01 | 0.10 |
| observed spread (H1 mean / worst) | **$0.10 / $0.17** (probe snapshot $0.34 on quiet quote) | $0.10 / $0.17 (same market, quoted identically) |
| risk at min lot, 2×H1-ATR stop (~$49.6) | **$49.59 → 1% ⇒ ~$4,959 book** | **$4.96 → 1% ⇒ ~$496 book** |
| typical H1 ATR(14) | ~$24.8 (2× = $49.6 stop) | same market |

**The floor verdict:** at this account's size the tradeable instrument is
**XAUUSD** ($4.96/trade at min lot). XAUUSD standard re-enters the
picture only when the book approaches ~$5,000. The EA prices both from the
symbol's own spec — same logic, two symbols, chosen by `InpSymbol`.

**Cost geometry:** spread ≈ 0.10–0.34 against a ~$49.6 typical H1 stop =
**0.2–0.7% toll** — roughly 8–25× cheaper than the 5.6% that killed V75(1s).
This is why gold is buildable and the alternatives were not.

## 2. Session fingerprint (our own H1 data, mean per-hour range in $)

| hour UTC | mean range | | hour UTC | mean range |
|---|---|---|---|---|
| 04 | 8.48 (trough) | | 13 | 20.88 |
| 07–11 | 11–12.7 | | **14** | **21.06 (peak)** |
| 12 | 17.03 | | 15 | 18.16 |

- **Volatility core: 12:00–16:00 UTC** (London afternoon + New York morning,
  the overlap). Trough 03:00–05:00 UTC (Asia lull).
- **Spread is nearly flat all day** ($0.097–0.108), two exceptions: the
  22:00 rollover hour ($0.174) and the Sunday reopen ($0.172). No lunch-
  time spike structure like FX — gold trades on one global book.
- **Day of week barely matters** ($13.1–13.7 range Mon–Fri) — gold's
  calendar rhythm is intraday, not weekday.
- Hour 21 has only 166 bars vs ~629 elsewhere: the **daily break** (~1h)
  sits before 22:00 (server time differs; the break is real and the EA
  must not treat it as a data error).
- Bars stamped Sunday are the legal **Sunday reopen** (~2.4h of Monday
  Asia at current server offset).

## 3. Market structure facts that shape the EA

1. **24/5 with a ~1h daily break and Sunday reopen** — no weekend candles,
   so the only gap risk is Friday-close → Sunday-open. Measured DOW spread
   says Sunday quotes are already wide; treat the first hours after reopen
   as a stand-down window, not an entry window.
2. **Easter holidays** close gold entirely (measured 3.1-day holes in 2025
   and 2026). Holiday stand-down can't be hardcoded — the EA's staleness
   guard (no fresh bar for N minutes → no trading) covers it generically.
3. **Trend persistence** is gold's defining behavior (macro drivers: real
   rates, USD, central-bank demand). This is the natural habitat of the
   program's macro-filter + trigger family — the strategy DNA transfers,
   the market is simply better.
4. **Volatility clustering** is strong (see the 13:00 vs 04:00 ranges) —
   ATR-scaled stops are mandatory, fixed-dollar stops are malpractice.
5. **Broker-feed reality:** the H1/M15 backfill starts continuous at
   2024-04-10 (a 112-day hole 2023-12-20→2024-04-10 was found and excluded);
   D1 carries the same hole plus Sunday-stamped bars — **D1 is
   reference-only** in this program. Research timeframes: H1 (macro) +
   M15 (trigger).

## 4. Standing policies for every MIDASTOUCH build

- **ATR-scaled stops** from the H1 anchor; never fixed-dollar.
- **Spread-cap veto:** no entry when spread > 1.5% of stop distance
  (measured mean is 0.2%; the cap trips only in genuine stress).
- **News stand-down:** no new entries in a ±15-min window around top-tier
  USD releases; positions already open are managed, not opened.
- **Session gate:** entries allowed only in the 06:00–20:00 UTC activity
  band (measured); Friday-after-20:00 UTC = flat policy unless the position
  is in profit and trailing (gap policy is an input, default conservative).
- **Weekend/holiday:** nothing held over the weekend by default.
- **Sizing:** risk % of equity via the symbol's own tick value — with the
  **geometric identity check** (contract × tick_size) pinned against the
  broker value, min-lot floor disclosed, and the floor table printed at init.
- **Paper mode is the default state**, forever, until the frozen gates say
  otherwise (see MIDASTOUCH_PROTOCOL).

## 5. What the playbook does NOT claim

No claim here about any strategy's edge — that is Step 4's job, under the
frozen protocol. This document only fixes the battlefield's ground truth.
Numbers were measured 2026-09-16; re-measure if the account, broker, or
symbol changes.
