#!/usr/bin/env python3
"""MIDASTOUCH Step 2 — Deriv symbol probe (read-only, fail-closed).

Attaches to the RUNNING MT5 terminal via the MetaTrader5 package (no login
change, no orders, nothing written into the terminal), then answers the only
two questions that matter before any gold strategy work:

  1. Does gold (XAUUSD and variants) exist on THIS account, and at what spec?
  2. What does the floor math say: dollars risked at volume_min for a typical
     H1 stop, and spread as a % of that stop (the toll that killed every
     alternative synthetic)?

Also dumps specs for the secondary watchlist (majors, indices, crypto) so the
Phase-4 cross-market extension has the same table.

Output: artifacts/deriv_symbols_<date>.json + a readable stdout table.
Exit codes: 0 probe ok; 2 fail-closed (terminal not reachable / no data).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

TERMINAL_EXE = r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"
OUT_DIR = os.path.join("artifacts")

PRIMARY = ["XAUUSD", "GOLD", "XAUUSD.r", "XAUUSDm", "XAUUSD#", "XAU/USD"]
WATCHLIST = ["EURUSD", "GBPUSD", "USDJPY", "US30", "US100", "NAS100",
             "BTCUSD", "XAGUSD"]


def fail(msg: str) -> int:
    print(f"PROBE FAILED (fail-closed): {msg}")
    return 2


def main() -> int:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return fail("MetaTrader5 python package not available in this venv")

    if not os.path.exists(TERMINAL_EXE):
        return fail(f"terminal exe not found: {TERMINAL_EXE}")

    # Attach to the RUNNING terminal. Never logs in, never trades.
    if not mt5.initialize(path=TERMINAL_EXE, timeout=30000):
        return fail(f"mt5.initialize failed: {mt5.last_error()} — "
                    "is the terminal running?")
    try:
        acct = mt5.account_info()
        if acct is None:
            return fail(f"account_info() returned None: {mt5.last_error()}")

        print("=" * 78)
        print(f"ACCOUNT  login={acct.login}  server={acct.server}")
        print(f"         trade_mode={acct.trade_mode} "
              f"(0=demo 1=contest 2=real)  leverage=1:{acct.leverage}")
        print(f"         balance={acct.balance} {acct.currency}  "
              f"margin_mode={acct.margin_mode}")
        print("=" * 78)

        all_syms = mt5.symbols_total()
        if all_syms is None or all_syms == 0:
            return fail(f"symbols_total() -> {all_syms}: {mt5.last_error()}")
        names = [s.name for s in (mt5.symbols_get() or [])]
        print(f"symbol table: {all_syms} symbols")

        # --- gold variants: exact + pattern search --------------------------
        gold_hits = [n for n in names
                     if n.upper() in [g.upper() for g in PRIMARY]
                     or ("XAU" in n.upper() or "GOLD" in n.upper())]
        watch_hits = [n for n in names
                      if n.upper() in [w.upper() for w in WATCHLIST]]
        print(f"gold-family symbols found: {gold_hits}")
        print(f"watchlist symbols found:   {watch_hits}")

        results: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "account": {"login": acct.login, "server": acct.server,
                        "trade_mode": acct.trade_mode,
                        "leverage": acct.leverage,
                        "balance": acct.balance, "currency": acct.currency},
            "symbols_total": all_syms,
            "gold_family": gold_hits,
            "watchlist": watch_hits,
            "specs": {},
        }

        def dump(name: str) -> dict | None:
            info = mt5.symbol_info(name)
            if info is None:
                return None
            if not info.visible:
                # read-only select is harmless; it only adds it to Market Watch
                if not mt5.symbol_select(name, True):
                    return None
                info = mt5.symbol_info(name)
                if info is None:
                    return None
            tick = mt5.symbol_info_tick(name)
            spread_pts = getattr(info, "spread", None)
            bid = getattr(tick, "bid", None) if tick else None
            ask = getattr(tick, "ask", None) if tick else None

            d: dict = {
                "name": info.name,
                "description": info.description,
                "digits": info.digits,
                "point": info.point,
                "spread_points": spread_pts,
                "spread_price": (ask - bid) if (bid and ask) else None,
                "bid": bid, "ask": ask,
                "tick_size": info.trade_tick_size,
                "tick_value": info.trade_tick_value,
                "contract_size": info.trade_contract_size,
                "volume_min": info.volume_min,
                "volume_step": info.volume_step,
                "volume_max": info.volume_max,
                "stops_level_points": info.trade_stops_level,
                "trade_mode": info.trade_mode,
                "margin_initial": info.margin_initial,
                "margin_maintenance": info.margin_maintenance,
                "path": info.path,
            }
            # tick-value identity check (the V75 5%-rule lesson, ported):
            # geometric value = contract_size * tick_size. If the broker's
            # trade_tick_value is far from it, flag it — sizing math depends
            # on which one is true.
            if info.trade_tick_size and info.trade_tick_value:
                geo = info.trade_contract_size * info.trade_tick_size
                if geo > 0:
                    d["tick_value_geometric"] = geo
                    d["tick_value_ratio_broker_over_geometric"] = (
                        info.trade_tick_value / geo)
            return d

        for name in gold_hits + [w for w in watch_hits if w not in gold_hits]:
            spec = dump(name)
            if spec:
                results["specs"][name] = spec

        # --- floor math + toll for gold (and majors for comparison) --------
        print("\n" + "=" * 78)
        print(f"{'symbol':<12}{'spread$':>9}{'h1_stop$':>10}{'toll%':>7}"
              f"{'risk@minlot$':>14}{'equity@1%':>11}")
        print("-" * 78)
        for name, spec in results["specs"].items():
            if not spec.get("spread_price"):
                continue
            rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, 300)
            if rates is None or len(rates) < 30:
                spec["h1_bars_available"] = 0
                continue
            spec["h1_bars_available"] = len(rates)
            # Wilder ATR(14) on H1
            trs = []
            for i in range(1, len(rates)):
                h, l, pc = rates[i]['high'], rates[i]['low'], rates[i - 1]['close']
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            atr = trs[0]
            for tr in trs[1:]:
                atr = (atr * 13 + tr) / 14
            stop = 2.0 * atr          # the v28 anchor: stop = 2x H1 ATR
            spec["h1_atr14"] = round(atr, 5)
            spec["typical_h1_stop"] = round(stop, 5)
            spread = spec["spread_price"]
            toll = spread / stop * 100 if stop > 0 else None
            spec["toll_pct_of_stop"] = round(toll, 2) if toll else None

            # floor math: dollars risked at volume_min over that stop
            ts, tv = spec["tick_size"], spec["tick_value"]
            vmin = spec["volume_min"]
            if ts and tv and vmin:
                risk_min_lot = stop / ts * tv * vmin
                spec["risk_dollars_at_min_lot"] = round(risk_min_lot, 2)
                spec["equity_needed_for_1pct"] = round(risk_min_lot / 0.01, 0)
                row = (f"{name:<12}{spread:>9.3f}{stop:>10.2f}{toll:>7.2f}"
                       f"{risk_min_lot:>14.2f}{risk_min_lot / 0.01:>11.0f}")
            else:
                row = f"{name:<12}{spread:>9.3f}{stop:>10.2f}{toll:>7.2f}{'n/a':>14}{'n/a':>11}"
            print(row)

        # --- feed depth on gold (bisect: oversized requests return None) ----
        def max_depth(name: str, tf: int) -> int:
            best = 0
            for want in (1000, 5000, 20000, 50000, 100000, 200000):
                bars = mt5.copy_rates_from_pos(name, tf, 0, want)
                if bars is None or len(bars) == 0:
                    break
                best = len(bars)
                if len(bars) < want:
                    break
            return best

        for name in gold_hits:
            for tf_name, tf in (("M15", mt5.TIMEFRAME_M15),
                                ("H1", mt5.TIMEFRAME_H1),
                                ("D1", mt5.TIMEFRAME_D1)):
                n = max_depth(name, tf)
                if n:
                    tail = mt5.copy_rates_from_pos(name, tf, n - 1, 1)
                    first = (datetime.fromtimestamp(tail[0]['time'], tz=timezone.utc)
                             if tail is not None and len(tail) else None)
                    results["specs"][name][f"feed_depth_{tf_name}"] = {
                        "bars": n,
                        "first_bar_utc": first.isoformat() if first else None}
                    print(f"feed depth {name} {tf_name}: {n} bars, "
                          f"first {first.date() if first else '?'}")

        os.makedirs(OUT_DIR, exist_ok=True)
        out = os.path.join(OUT_DIR,
                           f"deriv_symbols_{datetime.now():%Y%m%d}.json")
        with open(out, "w") as fh:
            json.dump(results, fh, indent=1, default=str)
        print(f"\nartifact written: {out}")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
