#!/usr/bin/env python3
"""Read-only venue probe: ground-truth symbol inventory for ANY MT5 broker.

Written for the Upcomers $25K Thunderbolt challenge (login 1428765,
server Upcomers) but deliberately broker-agnostic -- pass any terminal path,
login and server.

Answers, from the running server rather than from documentation:
  * Which symbols actually exist, grouped by the broker's own category path
  * Do any synthetic/volatility indices exist on this venue (the open question)
  * Per-symbol trade specs: min/step/max lot, tick value & size, contract size,
    stops level, spread, digits, trade mode, swap
  * REAL min-lot risk in dollars at a given stop distance (the arithmetic that
    decides position sizing, replacing any spreadsheet)
  * Which categories have a live tick RIGHT NOW -- run it on a weekend and it
    settles empirically whether the venue is 24/7

Nothing here sends, modifies or cancels an order. It only reads.

Usage (password via env to keep it out of shell history):
    MT5_PASSWORD='...' python scripts/venue_probe.py \
        --terminal "C:/Program Files/MetaTrader 5/terminal64.exe" \
        --login 1428765 --server Upcomers

    --out artifacts/upcomers_inventory.json   (full JSON inventory)
    --equity 25000                            (equity for the risk math)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - environment guard        print("MetaTrader5 package not installed. pip install MetaTrader5")
        sys.exit(2)


def _account_as_dict(acct) -> dict:
    """Serialise an MT5 account record.

    The bridge returns a named tuple, NOT a dataclass, so ``dataclasses.asdict``
    raises TypeError. Tolerate all three shapes rather than assuming one.
    """
    if hasattr(acct, "_asdict"):
        return dict(acct._asdict())
    if isinstance(acct, dict):
        return dict(acct)
    return dict(acct)


from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    classify_symbol,
    documented_commission_bps,
)

#: Names that would indicate Deriv-style synthetic indices. If this matches
#: nothing, the venue does not carry them.
SYNTHETIC_PATTERN = re.compile(
    r"volatilit|vol\s?\d|syn\d|boom|crash|jump|step|dex|drift|range\s?break",
    re.IGNORECASE,
)

#: How recently a tick must have arrived for a symbol to count as "live now".
LIVE_TICK_WINDOW_S = 900.0

#: How recently a tick must have arrived for a symbol to count as "traded" in the
#: by-class rollup. Wider than LIVE_TICK_WINDOW_S so a symbol that trades every few
#: minutes is not miscounted as shut.
TRADED_TODAY_WINDOW_S = 3600.0

TRADE_MODE = {
    0: "DISABLED",
    1: "LONGONLY",
    2: "SHORTONLY",
    3: "CLOSEONLY",
    4: "FULL",
}


@dataclasses.dataclass
class Sym:
    """Flattened, JSON-safe view of one MT5 symbol."""

    name: str
    path: str
    description: str
    group: str
    visible: bool
    trade_mode: str
    digits: int
    spread_points: float
    spread_raw: int
    bid: float
    ask: float
    point: float
    volume_min: float
    volume_step: float
    volume_max: float
    contract_size: float
    tick_value: float
    tick_size: float
    stops_level: int
    freeze_level: int
    swap_long: float
    swap_short: float
    last_tick_age_s: float | None
    # --- availability evidence -------------------------------------------------
    # The MT5 Python bridge exposes no session-TIME function, so the weekend /
    # 24-7 question cannot be answered from a session table. It can be answered
    # from the broker's own day counters: ``session_deals`` and ``session_volume``
    # accumulate only while the symbol is actually trading. Run the probe on a
    # Saturday and a non-zero counter is proof of weekend trading, while a zero
    # counter across a whole class is proof of a closed session.
    asset_class: str | None = None
    session_deals: int = 0
    session_volume: float = 0.0
    session_turnover: float = 0.0
    session_buy_orders: int = 0
    session_sell_orders: int = 0

    def min_lot_risk(self, stop_distance: float) -> float:
        """$ risked by the minimum lot if the stop is `stop_distance` away.

        Uses the broker's own tick value rather than a assumed pip value --
        this is the whole point of reading specs from the server.
        """
        if self.tick_size <= 0 or stop_distance <= 0:
            return float("nan")
        ticks = stop_distance / self.tick_size
        return self.volume_min * self.tick_value * ticks


def _connect(a) -> str:
    """Initialize the terminal. Returns a human-readable status line."""
    kwargs = {"path": str(Path(a.terminal))} if a.terminal else {}
    if a.login:
        kwargs["login"] = int(a.login)
        kwargs["password"] = a.password
        kwargs["server"] = a.server
    kwargs["timeout"] = a.timeout_ms
    if not mt5.initialize(**kwargs):
        code, msg = mt5.last_error()
        print(f"mt5.initialize failed: ({code}) {msg}")
        print("Check: terminal path exists, terminal is running, "
              "server string matches the broker's (e.g. 'Upcomers-Server').")
        sys.exit(1)
    t = mt5.terminal_info()
    return (f"terminal connected={getattr(t, 'connected', '?')} "
            f"trade_allowed={getattr(t, 'trade_allowed', '?')} "
            f"path={getattr(t, 'path', '?')}")


def _server_offset_s() -> float:
    """Seconds to ADD to the local clock to obtain the broker's server clock.

    Tick and bar timestamps from MT5 are in **server** time, which is neither UTC
    nor local time. On a venue where at least one symbol is live, the freshest tick
    on the whole book IS "now" in server time, so ``max(tick.time) - now`` is the
    offset. Snapped to a 15-minute grid: exchanges do not sit on odd offsets, and
    snapping stops a single stray future-stamped tick from skewing every age.

    Getting this wrong is not cosmetic. Comparing a server-time tick against a
    UTC clock once made a *live* BTCUSD.nx (server UTC+2) read as 120 minutes in
    the future, so the liveness filter reported zero symbols trading on a Saturday
    while crypto was in fact streaming. That false negative inverted the venue's
    single most important property.
    """
    newest = 0.0
    for s in mt5.symbols_get():
        t = mt5.symbol_info_tick(s.name)
        if t is not None and t.time:
            newest = max(newest, float(t.time))
    if not newest:
        return 0.0
    return round((newest - time.time()) / 900.0) * 900.0


def _collect(server_offset_s: float = 0.0) -> list[Sym]:
    out: list[Sym] = []
    now = time.time()
    for s in mt5.symbols_get():
        tick = mt5.symbol_info_tick(s.name)
        age = None
        bid = ask = 0.0
        if tick is not None:
            bid, ask = float(tick.bid), float(tick.ask)
            if tick.time:
                # tick.time is SERVER time -- correct before calling it "age".
                age = max(0.0, now + server_offset_s - float(tick.time))
        path = s.path or s.name
        # MT5 paths look like "Forex\\Majors\\EURUSD" -> group on the first leg
        group = path.split("\\")[0] if "\\" in path else "UNGROUPED"
        out.append(Sym(
            name=s.name,
            path=path,
            description=s.description or "",
            group=group,
            visible=bool(s.visible),
            trade_mode=TRADE_MODE.get(s.trade_mode, str(s.trade_mode)),
            digits=int(s.digits),
            spread_points=float(s.spread),
            spread_raw=int(s.spread),
            bid=bid,
            ask=ask,
            point=float(s.point),
            volume_min=float(s.volume_min),
            volume_step=float(s.volume_step),
            volume_max=float(s.volume_max),
            contract_size=float(s.trade_contract_size),
            tick_value=float(s.trade_tick_value),
            tick_size=float(s.trade_tick_size),
            stops_level=int(s.trade_stops_level),
            freeze_level=int(s.trade_freeze_level),
            swap_long=float(s.swap_long),
            swap_short=float(s.swap_short),
            last_tick_age_s=age,
            asset_class=classify_symbol(s.name, path, s.description or ""),
            session_deals=int(getattr(s, "session_deals", 0) or 0),
            session_volume=float(getattr(s, "session_volume", 0.0) or 0.0),
            session_turnover=float(getattr(s, "session_turnover", 0.0) or 0.0),
            session_buy_orders=int(getattr(s, "session_buy_orders", 0) or 0),
            session_sell_orders=int(getattr(s, "session_sell_orders", 0) or 0),
        ))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terminal", default=os.environ.get(
        "MT5_TERMINAL", r"C:\Program Files\MetaTrader 5\terminal64.exe"))
    ap.add_argument("--login", default=os.environ.get("MT5_LOGIN"))
    ap.add_argument("--password", default=os.environ.get("MT5_PASSWORD"))
    ap.add_argument("--server", default=os.environ.get("MT5_SERVER", "Upcomers"))
    ap.add_argument("--equity", type=float, default=25000.0,
                    help="equity for the min-lot risk math")
    ap.add_argument("--out", default=None, help="write full JSON inventory here")
    ap.add_argument("--timeout-ms", type=int, default=120000)
    a = ap.parse_args(argv)

    print(f"== connecting ==\n{_connect(a)}")

    acct = mt5.account_info()
    if acct:
        print(f"account: login={acct.login} name={acct.name!r} "
              f"server={acct.server!r}\n"
              f"         balance={acct.balance:.2f} equity={acct.equity:.2f} "
              f"margin_free={acct.margin_free:.2f} leverage=1:{acct.leverage}\n"
              f"         company={acct.company!r} currency={acct.currency} "
              f"trade_mode={acct.trade_mode} "
              f"margin_mode={acct.margin_mode}")
    else:
        print("WARNING: no account info -- terminal may not be logged in")

    total = mt5.symbols_total()
    server_offset = _server_offset_s()
    print(f"\nserver clock offset: {server_offset/3600:+.2f} h vs local "
          f"(tick/bar timestamps are server time)")
    syms = _collect(server_offset)
    print(f"\nsymbols_total={total}  collected={len(syms)}")

    now = time.time()
    print(f"now = {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))} local "
          f"({time.strftime('%A')})  |  "
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now))} UTC")

    # ---- the premise check -------------------------------------------------
    synth = [s for s in syms if SYNTHETIC_PATTERN.search(s.name)
             or SYNTHETIC_PATTERN.search(s.description)]
    print(f"\n=== SYNTHETIC-INDEX MATCHES: {len(synth)} ===")
    for s in sorted(synth, key=lambda x: x.name)[:40]:
        print(f"  {s.name:<24} {s.group:<12} {s.description[:40]!r}")

    # ---- broker's own categories ------------------------------------------
    by_group: dict[str, list[Sym]] = defaultdict(list)
    for s in syms:
        by_group[s.group].append(s)
    print(f"\n=== CATEGORIES ({len(by_group)}) ===")
    for g, items in sorted(by_group.items(), key=lambda kv: -len(kv[1])):
        live = sum(1 for s in items
                   if s.last_tick_age_s is not None
                   and s.last_tick_age_s <= LIVE_TICK_WINDOW_S)
        print(f"  {g:<22} n={len(items):<5} live_now={live}")

    # ---- 24/7 check: which categories have a fresh tick right now ----------
    live = [s for s in syms
            if s.last_tick_age_s is not None
            and s.last_tick_age_s <= LIVE_TICK_WINDOW_S]
    print(f"\n=== LIVE NOW (tick within {LIVE_TICK_WINDOW_S/60:.0f} min): "
          f"{len(live)} symbols ===")
    live_by_group = Counter(s.group for s in live)
    for g, n in live_by_group.most_common():
        print(f"  {g:<22} {n}")

    # ---- the 24/7 question, settled by the broker's own day counters -------
    print("\n=== ACTIVITY BY ASSET CLASS (last tick, server-clock corrected) ===")
    print("    A symbol is ACTIVE if a tick arrived within the last")
    print(f"    {TRADED_TODAY_WINDOW_S/60:.0f} minutes. Tick recency is the primary evidence: the")
    print("    broker's session_deals/session_volume counters are NOT populated for")
    print("    CFD symbols on every server, so a zero counter is not proof of a")
    print("    closed session. Those counters are still shown, as secondary data.")
    bps = documented_commission_bps()
    rollup: dict[str, list[Sym]] = defaultdict(list)
    for s in syms:
        if s.asset_class:
            rollup[s.asset_class].append(s)
    def _active(items: list[Sym]) -> list[Sym]:
        return [s for s in items if s.last_tick_age_s is not None
                and s.last_tick_age_s <= TRADED_TODAY_WINDOW_S]

    print(f"\n    {'class':<9} {'n':>5} {'active_1h':>10} {'deals':>9} "
          f"{'volume':>13} {'comm_bps':>9}")
    for cls in sorted(rollup, key=lambda c: -len(rollup[c])):
        items = rollup[cls]
        active = _active(items)
        print(f"    {cls:<9} {len(items):>5} {len(active):>13} "
              f"{sum(s.session_deals for s in items):>9} "
              f"{sum(s.session_volume for s in items):>13.4g} "
              f"{bps.get(cls, float('nan')):>9.3f}")
    print()
    for cls in sorted(rollup):
        items = rollup[cls]
        active = _active(items)
        verdict = "TRADING NOW" if active else "no activity today"
        print(f"    -> {cls:<9} {verdict}  ({len(active)}/{len(items)} symbols)")
    unclassified = [s for s in syms if not s.asset_class]
    if unclassified:
        print(f"    -> unclassified: {len(unclassified)} symbols excluded from the "
              f"cost ranking (never guess a class into the free band)")

    # ---- tradeable universe ------------------------------------------------
    tradeable = [s for s in syms if s.trade_mode == "FULL" and s.bid > 0]
    print(f"\n=== TRADEABLE (mode FULL, has a price): {len(tradeable)} ===")

    # ---- min-lot risk at a 1%-of-price stop, sorted by cost ----------------
    rows = []
    for s in tradeable:
        if s.tick_size <= 0 or s.bid <= 0:
            continue
        stop = s.bid * 0.01  # a 1%-of-price stop distance
        risk = s.min_lot_risk(stop)
        if risk != risk:  # NaN
            continue
        spread_cost = (s.spread_points * s.point) if s.point else 0.0
        rows.append((s, stop, risk, risk / a.equity * 100.0, spread_cost))
    print(f"{'symbol':<22} {'bid':>12} {'minlot':>7} {'$risk@1%stop':>13} "
          f"{'%equity':>8} {'sprd_pts':>9} {'tick_val':>10}")
    for s, _stop, risk, pct, _sc in sorted(rows, key=lambda r: -r[3])[:25]:
        print(f"{s.name:<22} {s.bid:>12.4f} {s.volume_min:>7} {risk:>13.2f} "
              f"{pct:>7.2f}% {s.spread_raw:>9} {s.tick_value:>10.6g}")
    print(f"... ({len(rows)} symbols with complete spec data)")

    if a.out:
        p = Path(a.out)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "probed_at": now,
            "terminal_path": str(Path(a.terminal)) if a.terminal else None,
            "account": (_account_as_dict(acct) if acct else None),
            "symbols_total": total,
            "synthetic_matches": [s.name for s in synth],
            "live_now": [s.name for s in live],
            "commission_bps_by_class": documented_commission_bps(),
            "server_time_offset_s": server_offset,
            "active_within_1h": [s.name for s in syms
                                 if s.last_tick_age_s is not None
                                 and s.last_tick_age_s <= TRADED_TODAY_WINDOW_S],
            "session_counters_nonzero": [s.name for s in syms
                                         if s.session_deals > 0
                                         or s.session_volume > 0],
            "symbols": [dataclasses.asdict(s) for s in syms],
        }, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {p}")

    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
