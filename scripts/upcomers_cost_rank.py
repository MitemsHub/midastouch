#!/usr/bin/env python3
"""Rank Upcomers instruments by MEASURED round-trip cost per R.

WHY THIS EXISTS. `scripts/venue_probe.py` reads the venue's *specs* but cannot
measure volatility or realised spread, and `scripts/profile_instrument.py`
profiles *one* symbol in depth. Neither answers the question the operator actually
asked -- "which instrument should we trade here?" -- because that question is a
ranking, and a ranking needs the same two measured quantities for every candidate:

  1. **How far the thing moves** (ATR), and
  2. **What it costs to get in and out** (realised spread + published commission).

THE METRIC. Cost per R, where 1R is the stop distance:

    cost_R = (spread_price + commission_round_trip) / stop_distance

Both terms scale with size while the stop scales with size too, so the ratio is
size-independent -- which is why it can rank a 0.01-lot Nasdaq CFD against a
100,000-unit FX contract honestly. Two consequences follow, and they are the
reason this replaces "which instrument feels good":

  * **Commission as a percentage of notional is the brutal term.** A strategy that
    risks $X with a stop `s` percent away must hold `X/s` of notional, so its
    commission toll is `commission_pct / s` R. Tight stops therefore *increase*
    commission cost without limit. Crypto at 0.04%/side against a 0.6% stop is
    ~0.13R of pure commission before a single spread is paid.
  * **Spread, by contrast, is bounded by the stop.** A 0.35 bps spread on a 60 bps
    stop is 0.6% of R. This is why BTCUSD.nx looks cheapest on a spread table and
    is not.

For reference, our measured V75 gross edge was +0.027R/trade. Any instrument whose
toll is an order of magnitude above that cannot be traded profitably on this
strategy regardless of signal quality, so the honest output of this script can be
"none of them".

Gap columns are printed but deliberately do NOT enter the ranking: a stop cannot
protect against a gap, so gap risk is a separate, non-linear veto rather than a
cost term. `worst_weekend_gap_pct` against the stop distance is the number that
decides whether an instrument may be held over a weekend at all.

Read-only: connects to the terminal, reads bars and ticks, closes nothing.

Usage:
    python scripts/upcomers_cost_rank.py \\
        --inventory artifacts/upcomers_inventory.json \\
        --symbols NACUSD.c,SPCUSD.c,XAUUSD,BTCUSD.nx \\
        --days 90 --tick-days 3 --stop-mult 1.0 \\
        --out artifacts/upcomers_cost_rank.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from midas_prop.risk.upcomers_rules import (  # noqa: E402
    FOREX,
    CommissionSchedule,
    InstrumentCandidate,
    classify_symbol,
    rank_candidates,
)

import profile_instrument as pi  # noqa: E402

#: Default shortlist: every index/energy CFD that exists (there are only 17 `*.c`
#: symbols), plus the two metals and FX majors people reach for, plus the crypto
#: majors that are the only instruments proven to trade at the weekend.
#: Daily-bar age past which the instrument's ATR is treated as untrustworthy and
#: flagged in the output. A terminal that has never downloaded a symbol's recent
#: history returns whatever it has, without complaint.
STALE_HISTORY_DAYS = 7

#: An ATR smaller than this fraction of price is a data failure, not a cheap
#: instrument. EURUSD once ranked 8th of 10 with ``atr=0.00`` because the terminal
#: held current DAILY bars but a flat 2024 stub for H1 -- the daily staleness guard
#: did not fire, and a zero ATR silently produced a plausible-looking cost per R.
MIN_ATR_FRACTION = 1e-5

#: An H1 bar older than this many days means the intraday series is not real.
#: Generous enough to survive a long weekend plus a holiday.
STALE_H1_DAYS = 5.0

#: Fraction of H1 bars that must have a non-zero high-low range before the series
#: is trusted. A flat stub (open == high == low == close) is what a terminal
#: returns for a symbol it has never actually downloaded, and its ATR is ~0 while
#: still clearing MIN_ATR_FRACTION. EURUSD did exactly this.
MIN_BAR_ACTIVITY = 0.5

#: A spread wider than this, in bps of mid, means the derived price and the quoted
#: spread are not on the same basis (INCUSD.c reported 1067 bps off a 0.09 price),
#: so the row describes a broken feed rather than an expensive market.
MAX_PLAUSIBLE_SPREAD_BPS = 50.0

DEFAULT_SYMBOLS = (
    "NACUSD.c,SPCUSD.c,DJCUSD.c,GECEUR.c,FRCEUR.c,UKCGBP.c,JPCJPY.c,EXCEUR.c,"
    "HKCHKD.c,INCUSD.c,USOIL.c,UKOIL.c,"
    "XAUUSD,XAGUSD,"
    "EURUSD,GBPUSD,USDJPY,"
    "BTCUSD.nx,ETHUSD.nx,SOLUSD.nx,XRPUSD.nx"
)


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without a terminal)
# --------------------------------------------------------------------------- #


def parse_window(spec: str) -> list[int] | None:
    """Parse ``"14-19"`` / ``"14,15,16"`` / ``"all"`` into a sorted hour list.

    Returns None for ``all`` so callers can distinguish "no filter" from "an empty
    window", which would otherwise silently average nothing.
    """
    text = (spec or "all").strip().lower()
    if text in ("", "all", "*"):
        return None
    hours: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, _, hi_s = part.partition("-")
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:
                lo, hi = hi, lo
            hours.update(range(lo, hi + 1))
        else:
            hours.add(int(part))
    bad = [h for h in hours if not 0 <= h <= 23]
    if bad:
        raise ValueError(f"hour out of range: {sorted(bad)}")
    return sorted(hours)


def select_hours(by_hour: Mapping[int, float], window: Sequence[int] | None,
                 ) -> dict[int, float]:
    """Restrict a per-hour mapping to `window` (all hours when window is None)."""
    if window is None:
        return dict(by_hour)
    wanted = set(window)
    return {h: v for h, v in by_hour.items() if h in wanted}


def mean_or_none(values: Iterable[float]) -> float | None:
    """Mean of the values, or None when there are none (never 0.0, which would lie)."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return statistics.fmean(vals)


def representative_atr(atr_by_hour: Mapping[int, float],
                       window: Sequence[int] | None) -> float | None:
    """Mean ATR over the trading window, falling back to all hours.

    The fallback matters: restricting to a window that has no bars must not be
    silent, because an ATR of 0 would report an infinite cost per R.
    """
    scoped = select_hours(atr_by_hour, window)
    return mean_or_none(scoped.values()) or mean_or_none(atr_by_hour.values())


def quote_currency(symbol: str, asset_class: str) -> str | None:
    """Quote currency of a symbol, or None when it cannot be determined safely.

    Only forex needs this: indices, metals and crypto on this venue are USD-quoted,
    and indices pay no commission at all, so their conversion factor is irrelevant.
    An unparseable FX name returns None -- NOT "USD" -- because assuming USD in the
    wrong direction scales the toll by the FX rate, and the whole point of this
    script is to stop publishing numbers that are quietly off.
    """
    if asset_class != FOREX:
        return "USD"
    if len(symbol) == 6 and symbol.isalpha():
        return symbol[3:].upper()
    return None


def resolve_quote_to_usd(quote: str, price_map: dict[str, float], days: int,
                         terminal: str | None,
                         window: Sequence[int] | None,
                         ) -> tuple[float | None, str]:
    """USD value of one unit of `quote`, measured from the venue where possible.

    Tries ``USD<quote>`` (divide) then ``<quote>USD`` (multiply), measuring the
    conversion pair on demand if it was not already in the run. Returns a reason
    instead of a guess when neither exists.
    """
    if quote == "USD":
        return 1.0, ""
    for cand in (f"USD{quote}", f"{quote}USD"):
        price = price_map.get(cand)
        if price is None:
            m = measure(cand, days, 1, terminal, window)
            if m and m["price"] > 0:
                price = m["price"]
                price_map[cand] = price
        if price and price > 0:
            return (1.0 / price, "") if cand.startswith("USD") else (price, "")
    return None, (f"no conversion rate for {quote} "
                  f"(tried USD{quote} and {quote}USD on the venue)")


def representative_spread_bps(spread_by_hour: Mapping[int, float],
                              window: Sequence[int] | None) -> float | None:
    """Mean spread in bps of mid over the window, falling back to all hours."""
    scoped = select_hours(spread_by_hour, window)
    return mean_or_none(scoped.values()) or mean_or_none(spread_by_hour.values())


def size_lots(risk_usd: float, atr_price: float, tick_size: float,
              tick_value: float, volume_min: float, volume_step: float,
              ) -> tuple[float | None, float | None, str]:
    """Lots that risk exactly `risk_usd` at a 1-ATR stop, snapped to the venue step.

    Returns ``(lots, realized_risk_usd, reason)``; ``lots`` is None when the
    instrument **cannot be sized at all**.

    This is the guard that catches the failure the rest of the table cannot see.
    ``JPCJPY.c`` is measurably the cheapest instrument on this venue at 0.0128R --
    but its minimum position is **1.0 lot** against a $208.91 risk at a 1-ATR stop.
    Against a $75 per-trade budget that is 2.8x over, so the instrument is
    unavailable, and its cheapness is in fact a *consequence* of the same fact: a
    minimum position that large can only carry a toll that low because you are
    forced to trade it big. A cost ranking without a sizing feasibility check ranks
    instruments you are not allowed to trade.
    """
    if tick_size <= 0 or risk_usd <= 0 or atr_price <= 0:
        return None, None, "degenerate spec"
    per_lot = atr_price / tick_size * tick_value
    if per_lot <= 0:
        return None, None, "zero value per lot"
    raw = risk_usd / per_lot
    floor_risk = volume_min * per_lot
    if raw < volume_min:
        return None, None, (
            f"cannot be sized: minimum position is {volume_min:g} lot, which risks "
            f"${floor_risk:.2f} at a 1-ATR stop -- {floor_risk/risk_usd:.1f}x the "
            f"${risk_usd:.0f} per-trade budget")
    step = volume_step if volume_step > 0 else volume_min
    lots = max(volume_min, round(raw / step) * step)
    return lots, lots * per_lot, ""


def gap_veto_multiple(gaps: Mapping[str, float], atr_price: float,
                      price: float) -> float | None:
    """Worst ADVERSE gap, as a multiple of the 1-ATR stop. A veto, not a cost.

    Only the adverse side counts: a favourable gap is a windfall, not a risk. Above
    1.0 the stop was gapped through; at 3.0 the realised loss was three times the
    intended one, which on a 3%-daily-loss account is the difference between a bad
    day and a dead account.

    Caveat worth stating in any report: this uses the ATR of the hours measured. If
    trading is filtered to a volatile window, that window's ATR is LARGER, so the
    stop in percent is WIDER and this multiple is *smaller*. The sizing basis and
    the veto basis must be the same ATR or the number is meaningless.
    """
    adverse = gaps.get("worst_adverse_gap_pct")
    if adverse is None or price <= 0 or atr_price <= 0:
        return None
    return pi.gap_breach_multiple(float(adverse), 100.0 * atr_price / price)


def bar_activity(bars: Sequence[Mapping[str, float]]) -> float | None:
    """Fraction of bars that actually moved (high > low).

    The cheapest and most reliable test of "did the terminal download this, or is
    it showing a placeholder": real bars have a range, stubs do not.
    """
    if not bars:
        return None
    moved = sum(1 for b in bars if float(b["high"]) > float(b["low"]))
    return moved / len(bars)


def reject_reason(atr: float | None, price: float | None,
                  h1_lag_days: float | None, *,
                  activity: float | None = None,
                  spread_bps: float | None = None) -> str | None:
    """Why this symbol cannot be ranked, or None when it can.

    Returning a *reason* rather than a bare bool is deliberate: a silently dropped
    instrument looks identical to one that was never requested, and the operator
    reading the table has no way to tell the difference.

    Four independent failure modes are checked, because each one produced a
    plausible-looking ranking row that was pure noise:

    * zero/absent ATR;
    * ATR too small a fraction of price to be a real series;
    * H1 bars that never move (a stub) or are very old;
    * a spread so wide that price and quote are on different bases.
    """
    if atr is None or atr <= 0:
        return "no usable ATR (flat or missing H1 history)"
    if price is None or price <= 0:
        return "no price"
    if atr / price < MIN_ATR_FRACTION:
        return (f"ATR is {atr/price:.2e} of price -- below {MIN_ATR_FRACTION:.0e}, "
                "so this is a bad-data stub, not a cheap instrument")
    if activity is not None and activity < MIN_BAR_ACTIVITY:
        return (f"only {activity:.0%} of H1 bars have any range -- flat stub "
                "history, not a real series")
    if h1_lag_days is not None and h1_lag_days > STALE_H1_DAYS:
        return f"H1 history is {h1_lag_days:.0f} days old"
    if (spread_bps is not None
            and spread_bps > MAX_PLAUSIBLE_SPREAD_BPS):
        return (f"quoted spread of {spread_bps:.0f} bps is implausible -- the "
                "price basis is wrong, so this row is broken feed not a cost")
    return None


# --------------------------------------------------------------------------- #
# Terminal-bound work
# --------------------------------------------------------------------------- #


def load_specs(inventory_path: Path) -> dict[str, dict]:
    """Index the probe's inventory by symbol name."""
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    return {s["name"]: s for s in data.get("symbols", [])}


def measure(symbol: str, days: int, tick_days: int, terminal: str | None,
            window: list[int] | None) -> dict | None:
    """Measure one symbol. Returns None when it has no usable history."""
    try:
        bars, samples, day_rows = pi.collect(symbol, days, terminal,
                                             tick_days=tick_days)
    except SystemExit as exc:
        print(f"  ! {symbol}: {exc}")
        return None
    atr_all = pi.atr_by_hour(bars)
    sprd_all = pi.spread_bps_by_hour(samples)
    atr = representative_atr(atr_all, window)
    sprd = representative_spread_bps(sprd_all, window)
    if atr is None or sprd is None:
        print(f"  ! {symbol}: no usable ATR/spread "
              f"(bars={len(bars)} spread_samples={len(samples)})")
        return None
    price = None
    for b in reversed(bars):
        if float(b.get("prev_close") or 0) > 0:
            price = float(b["prev_close"])
            break
    if price is None:
        for b in reversed(bars):
            hi = float(b.get("high") or 0)
            if hi > 0:
                price = hi
                break
    if price is None:
        print(f"  ! {symbol}: no price in history")
        return None
    import time as _time
    now_ts = _time.time()

    def _lag(rows) -> float | None:
        for row in reversed(rows):
            if row.get("time"):
                return (now_ts - float(row["time"])) / 86400.0
        return None

    return {
        "atr": atr,
        "stale_days": _lag(day_rows),
        "h1_lag_days": _lag(bars),
        "bar_activity": bar_activity(bars),
        "spread_bps": sprd,
        "price": price,
        "gaps": pi.gap_stats(day_rows) if day_rows else {},
        "atr_by_hour": atr_all,
        "spread_bps_by_hour": sprd_all,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--inventory", default="artifacts/upcomers_inventory.json")
    ap.add_argument("--terminal", default=r"C:\Program Files\MetaTrader 5\terminal64.exe")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--tick-days", type=int, default=3,
                    help="days of ticks sampled for the spread estimate")
    ap.add_argument("--stop-mult", type=float, default=1.0,
                    help="stop distance in ATR units")
    ap.add_argument("--window", default="all",
                    help="UTC hours to measure, e.g. 14-19, or 'all'")
    ap.add_argument("--risk-usd", type=float, default=75.0,
                    help="per-trade risk budget; instruments whose MINIMUM position "
                         "exceeds it are excluded as untradeable")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    window = parse_window(a.window)
    inv_path = Path(a.inventory)
    if not inv_path.is_absolute():
        inv_path = ROOT / inv_path
    if not inv_path.exists():
        print(f"inventory not found: {inv_path}\n"
              "run scripts/venue_probe.py first")
        return 2
    specs = load_specs(inv_path)
    weekend_live = set(json.loads(inv_path.read_text(encoding="utf-8"))
                       .get("active_within_1h", []))

    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    print(f"measuring {len(symbols)} symbols: {a.days}d bars, "
          f"{a.tick_days}d ticks, window={a.window}, stop={a.stop_mult}xATR")

    pending: list[dict] = []
    candidates: list[InstrumentCandidate] = []
    extras: dict[str, dict] = {}
    for sym in symbols:
        spec = specs.get(sym)
        if spec is None:
            print(f"  ! {sym}: not in inventory (check the exact symbol name)")
            continue
        m = measure(sym, a.days, a.tick_days, a.terminal, window)
        if m is None:
            continue
        cls = spec.get("asset_class") or classify_symbol(sym, spec.get("path", ""),
                                                         spec.get("description", ""))
        if cls is None:
            print(f"  ! {sym}: unclassifiable -- excluded, so it cannot be "
                  "silently promoted into the zero-commission band")
            continue
        why = reject_reason(m["atr"], m["price"], m.get("h1_lag_days"),
                            activity=m.get("bar_activity"),
                            spread_bps=m["spread_bps"])
        if why:
            print(f"  ! {sym}: excluded -- {why}")
            continue
        contract = float(spec.get("contract_size") or 0.0) or 1.0
        spread_price = m["price"] * m["spread_bps"] / 1e4
        lag = m.get("stale_days")
        stale = lag is not None and lag > STALE_HISTORY_DAYS
        pending.append({
            "symbol": sym, "cls": cls, "m": m, "contract": contract,
            "spread_price": spread_price, "stale": stale, "lag": lag,
            "min_lot": float(spec.get("volume_min") or 0.01),
            "tick_size": float(spec.get("tick_size") or 0.0),
            "tick_value": float(spec.get("tick_value") or 0.0),
            "volume_step": float(spec.get("volume_step") or 0.0),
            "desc": spec.get("description", "") or "",
        })
        extras[sym] = m
        flag = ""
        if stale:
            flag = f"  << STALE DAILY HISTORY: {lag:.0f}d old"
        print(f"  + {sym:<11} atr={m['atr']:>10.2f} spread={m['spread_bps']:>7.3f}bps "
              f"price={m['price']:>11.2f}{flag}")

    # ---- resolve quote->USD before ANY commission is compared with a stop ----
    price_map = {p["symbol"]: p["m"]["price"] for p in pending}
    conversions: dict[str, float] = {"USD": 1.0}
    failed_quote: dict[str, str] = {}
    for p in pending:
        q = quote_currency(p["symbol"], p["cls"])
        if q is None:
            failed_quote[p["symbol"]] = (
                "quote currency is not parseable and this class pays a per-lot "
                "commission, so its cost cannot be computed safely")
            continue
        if q in conversions or q in failed_quote:
            continue
        rate, why = resolve_quote_to_usd(q, price_map, a.days, a.terminal, window)
        if rate is None:
            failed_quote[q] = why
        else:
            conversions[q] = rate

    for p in pending:
        sym, q = p["symbol"], quote_currency(p["symbol"], p["cls"])
        if sym in failed_quote:
            print(f"  ! {sym}: excluded -- {failed_quote[sym]}")
            continue
        if q is not None and q not in conversions:
            print(f"  ! {sym}: excluded -- {failed_quote.get(q, 'unresolved quote')}")
            continue
        rate = conversions.get(q or "USD", 1.0)
        lots, realized, why = size_lots(
            a.risk_usd, p["m"]["atr"], p["tick_size"], p["tick_value"],
            p["min_lot"], p["volume_step"])
        if lots is None:
            print(f"  ! {sym}: excluded -- {why}")
            continue
        extras[sym]["lots"] = lots
        extras[sym]["realized_risk"] = realized
        candidates.append(InstrumentCandidate(
            symbol=sym,
            asset_class=p["cls"],
            price=p["m"]["price"],
            contract_size=p["contract"],
            atr_price=p["m"]["atr"],
            spread_price=p["spread_price"],
            min_lot=p["min_lot"],
            weekend_capable=sym in weekend_live,
            notes=p["desc"] + (f" | STALE HISTORY {p['lag']:.0f}d" if p["stale"] else ""),
            quote_to_usd=rate,
        ))

    if not candidates:
        print("\nno candidates measured -- nothing to rank")
        return 1

    ranked = rank_candidates(candidates, stop_mult=a.stop_mult,
                             commission=CommissionSchedule())

    print(f"\n=== COST PER R (stop = {a.stop_mult:g}xATR, window={a.window}) ===")
    print(f"{'symbol':<12}{'class':<9}{'cost_R':>9}{'spread_bps':>12}"
          f"{'comm_bps':>10}{'atr':>11}{'gap_p95%':>10}{'gapX':>7}"
          f"{'lots':>8}{'risk$':>8}{'wknd':>6}")
    for r in ranked:
        c = r.candidate
        g = extras[c.symbol]["gaps"]
        # Commission per 1 lot of notional expressed in ACCOUNT currency. The raw
        # figure divides USD commission by a notional measured in the QUOTE
        # currency, which for USDJPY understates it by the FX rate (~157x).
        comm_bps = r.commission_bps / c.quote_to_usd
        print(f"{c.symbol:<12}{c.asset_class:<9}{r.cost_r:>9.5f}"
              f"{r.spread_bps:>12.3f}{comm_bps:>10.3f}"
              f"{c.atr_price:>11.2f}"
              f"{g.get('abs_gap_p95_pct', float('nan')):>10.3f}"
              f"{(gap_veto_multiple(g, c.atr_price, c.price) or float('nan')):>7.2f}"
              f"{extras[c.symbol].get('lots', float('nan')):>8.2f}"
              f"{extras[c.symbol].get('realized_risk', float('nan')):>8.2f}"
              f"{'yes' if c.weekend_capable else 'no':>6}")

    best = ranked[0]
    print(f"\ncheapest: {best.candidate.symbol} at {best.cost_r:.5f}R per round trip")
    print("  (V75's measured gross edge was +0.027R/trade -- compare like for like)")
    print("\ngapX = worst ADVERSE gap as a multiple of the 1-ATR stop:")
    print("  >1.0 the stop was gapped through; >=3.0 the realised loss was 3x intended.")
    print("  A stop cannot fill through a gap, so this is a veto, not a cost term.")

    if a.out:
        out = Path(a.out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "window": a.window,
            "quote_to_usd": conversions,
            "stop_mult": a.stop_mult,
            "tick_days": a.tick_days,
            "ranked": [
                {
                    "symbol": r.candidate.symbol,
                    "asset_class": r.candidate.asset_class,
                    "cost_r": r.cost_r,
                    "spread_bps": r.spread_bps,
                    "commission_bps": r.commission_bps,
                    "atr": r.candidate.atr_price,
                    "price": r.candidate.price,
                    "contract_size": r.candidate.contract_size,
                    "weekend_capable": r.candidate.weekend_capable,
                    "gap_veto_multiple": gap_veto_multiple(
                        extras[r.candidate.symbol]["gaps"],
                        r.candidate.atr_price, r.candidate.price),
                    "gaps": extras[r.candidate.symbol]["gaps"],
                }
                for r in ranked
            ],
        }, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
