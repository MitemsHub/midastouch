#!/usr/bin/env python3
"""Rank the Upcomers universe by what it costs to trade, not by what looks exciting.

WHY THIS EXISTS. "Which instrument should I trade?" is normally answered with
volatility, trendiness or vibes. On this account it is answered with arithmetic,
because Upcomers publishes a cost schedule whose classes differ by more than 8x:

    indices / stocks / energies   0        (zero commission)
    metals                        ~0.38 bps round trip   ($5/lot)
    forex                         ~0.91 bps round trip   ($5/lot)
    crypto                         8.0 bps round trip    (0.04% of notional)

Our own pre-registered study found spread cost consuming 100.5% of V75's gross
edge, and that widening the stop halved the toll while collapsing the edge. So the
number that decides whether an instrument is tradeable is

    cost per R = (round-trip commission + spread) / (stop_mult x ATR)

and the screen below computes exactly that, per symbol, from the venue's live
specs and the symbol's own measured ATR.

MODES
  --commission-table   the documented class table; needs no terminal (works offline)
  --live               measure the venue directly: spreads, contract sizes and ATR
                       from the running MT5 terminal
  --candidates FILE    rank a saved candidate JSON (offline, deterministic, testable)

The commission table is the one result that is already final: it depends only on
the published schedule, so it does not change when the terminal comes up. The ATR
and spread columns do, and are the reason --live exists.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# ``classify_symbol`` lives in the library so the venue probe and this screen
# cannot drift apart on what counts as crypto. Re-exported under this name for
# callers that only import the script.
from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    CRYPTO,
    ENERGIES,
    FOREX,
    INDICES,
    METALS,
    STOCKS,
    CommissionSchedule,
    InstrumentCandidate,
    classify_symbol,
    documented_commission_bps,
    rank_candidates,
)

#: Stop distances to price the screen at, in ATR units.
DEFAULT_STOP_MULTS: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0)


def load_candidates(path: Path) -> list[InstrumentCandidate]:
    """Read candidate rows from JSON.

    Accepted keys per row: symbol, asset_class (optional -- inferred if absent),
    price, contract_size, atr_price, spread_price, min_lot, weekend_capable,
    notes, path, description.
    """
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("candidates", [])
    out: list[InstrumentCandidate] = []
    for i, row in enumerate(rows):
        symbol = row.get("symbol")
        if not symbol:
            raise ValueError(f"candidate #{i} has no 'symbol'")
        cls = row.get("asset_class") or classify_symbol(
            symbol, row.get("path", ""), row.get("description", "")
        )
        if cls is None:
            raise ValueError(
                f"candidate #{i} ({symbol}) cannot be classified; "
                "set 'asset_class' explicitly rather than letting it default"
            )
        out.append(InstrumentCandidate(
            symbol=symbol,
            asset_class=cls,
            price=float(row["price"]),
            contract_size=float(row["contract_size"]),
            atr_price=float(row["atr_price"]),
            spread_price=float(row["spread_price"]),
            min_lot=float(row.get("min_lot", 0.01)),
            weekend_capable=row.get("weekend_capable"),
            notes=row.get("notes", ""),
        ))
    return out


def atr_from_rates(rates, period: int = 14) -> float:
    """Simple ATR over MT5 rate tuples (uses high/low/close, Wilder-free mean range)."""
    if rates is None or len(rates) < period + 1:
        return float("nan")
    highs = [float(r["high"]) for r in rates]
    lows = [float(r["low"]) for r in rates]
    closes = [float(r["close"]) for r in rates]
    trs = []
    for i in range(1, len(rates)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    if len(trs) < period:
        return float("nan")
    return sum(trs[-period:]) / period


def collect_live(symbols: list[str] | None, timeframe: str, atr_period: int,
                 terminal: str | None) -> list[InstrumentCandidate]:
    """Measure candidate rows from a running terminal. Read-only."""
    try:
        import MetaTrader5 as mt5
    except ImportError:  # pragma: no cover - environment guard
        raise SystemExit("MetaTrader5 package not installed. pip install MetaTrader5")

    kwargs = {"path": terminal} if terminal else {}
    kwargs["timeout"] = 120_000
    if not mt5.initialize(**kwargs):
        raise SystemExit(
            f"mt5.initialize failed: {mt5.last_error()} -- the terminal must be "
            "running AND logged in to Upcomers-Server for live measurement"
        )

    tf = getattr(mt5, f"TIMEFRAME_{timeframe.upper()}", mt5.TIMEFRAME_H1)
    names = symbols or [s.name for s in mt5.symbols_get()]
    out: list[InstrumentCandidate] = []
    for name in names:
        info = mt5.symbol_info(name)
        if info is None:
            continue
        cls = classify_symbol(name, info.path or "", info.description or "")
        if cls is None:
            continue
        tick = mt5.symbol_info_tick(name)
        if tick is None or not tick.bid:
            continue
        spread = float(tick.ask - tick.bid)
        rates = mt5.copy_rates_from_pos(name, tf, 0, atr_period + 60)
        a = atr_from_rates(rates, atr_period)
        if a != a or a <= 0:  # NaN or degenerate
            continue
        out.append(InstrumentCandidate(
            symbol=name,
            asset_class=cls,
            price=float(tick.bid),
            contract_size=float(info.trade_contract_size or 1.0),
            atr_price=a,
            spread_price=spread,
            min_lot=float(info.volume_min or 0.01),
            weekend_capable=None,
            notes=(info.path or ""),
        ))
    mt5.shutdown()
    return out


def render_commission_table() -> str:
    bps = documented_commission_bps()
    lines = [
        "== documented round-trip commission, in basis points of notional ==",
        "   (source: Upcomers published schedule; see UPCOMERS_RULES_AUDIT)",
        "",
        f"   {'class':<10} {'bps':>8}   basis",
    ]
    basis = {
        INDICES: "zero commission",
        STOCKS: "zero commission",
        ENERGIES: "zero commission",
        METALS: "$5/lot, representative 100oz gold",
        FOREX: "$5/lot, representative 1.10 quote",
        CRYPTO: "0.04% of notional (exact, no assumption)",
    }
    for cls in (INDICES, STOCKS, ENERGIES, METALS, FOREX, CRYPTO):
        lines.append(f"   {cls:<10} {bps[cls]:>8.3f}   {basis[cls]}")
    lines += [
        "",
        "   The crypto/forex gap is exact and price-independent: 8.0 vs 0.91 bps.",
        "   Nothing about signal quality differs by 8x between two instruments on",
        "   the same account; this gap is the venue's, not the strategy's.",
    ]
    return "\n".join(lines)


def render_ranking(ranked, stop_mults: tuple[float, ...]) -> str:
    if not ranked:
        return "no candidates survived classification -- nothing to rank"
    header = f"{'symbol':<16} {'class':<9} {'sprd_bps':>9} {'comm_bps':>9} " + \
             " ".join(f"{m:>7}xATR" for m in stop_mults)
    lines = ["", "== cost per R (round trip), cheapest first ==", "", "   " + header]
    for r in ranked:
        cells = " ".join(f"{r.cost_r / m:>10.4f}" for m in stop_mults)
        lines.append(
            f"   {r.candidate.symbol:<16} {r.candidate.asset_class:<9} "
            f"{r.spread_bps:>9.3f} {r.commission_bps:>9.3f} {cells}"
        )
    lines += [
        "",
        "   Read a cell as: this fraction of R is gone before the trade does",
        "   anything. A 0.20 needs +0.20R of gross edge per trade just to break",
        "   even. Our measured V75 gross edge was +0.027R per trade.",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commission-table", action="store_true",
                    help="print the documented class table and exit (no terminal needed)")
    ap.add_argument("--live", action="store_true",
                    help="measure spreads/specs/ATR from a running, logged-in terminal")
    ap.add_argument("--candidates", default=None,
                    help="JSON file of candidate rows to rank offline")
    ap.add_argument("--symbols", default=None, help="comma-separated subset for --live")
    ap.add_argument("--timeframe", default="H1", help="ATR timeframe (default H1)")
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--stop-mults", default=",".join(str(m) for m in DEFAULT_STOP_MULTS),
                    help="stop distances in ATR units")
    ap.add_argument("--terminal", default=None)
    ap.add_argument("--out", default=None, help="write the ranking as JSON here")
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args(argv)

    if a.commission_table or not (a.live or a.candidates):
        print(render_commission_table())
        if not (a.live or a.candidates):
            print("\n(pass --live or --candidates to rank symbols by cost per R)")
        return 0

    stop_mults = tuple(float(x) for x in a.stop_mults.split(",") if x.strip())
    if a.candidates:
        p = Path(a.candidates)
        if not p.is_absolute():
            p = ROOT / p
        candidates = load_candidates(p)
        print(f"loaded {len(candidates)} candidates from {p}")
    else:
        syms = [s.strip() for s in a.symbols.split(",")] if a.symbols else None
        candidates = collect_live(syms, a.timeframe, a.atr_period, a.terminal)
        print(f"measured {len(candidates)} symbols live at {a.timeframe} ATR({a.atr_period})")

    ranked = rank_candidates(candidates, stop_mult=stop_mults[0])
    print(render_ranking(ranked[: a.top], stop_mults))

    if a.out:
        p = Path(a.out)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "stop_mults": list(stop_mults),
            "commission_bps_by_class": documented_commission_bps(),
            "ranked": [
                {
                    "symbol": r.candidate.symbol,
                    "asset_class": r.candidate.asset_class,
                    "price": r.candidate.price,
                    "atr_price": r.candidate.atr_price,
                    "spread_price": r.candidate.spread_price,
                    "spread_bps": r.spread_bps,
                    "commission_bps": r.commission_bps,
                    "cost_per_r": {str(m): r.cost_r / m for m in stop_mults},
                }
                for r in ranked
            ],
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
