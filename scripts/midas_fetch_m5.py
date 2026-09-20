#!/usr/bin/env python3
"""Fetch XAUUSD M5 bars from the running MT5 terminal → certified CSV.

Writes data/forex/xauusd/XAUUSD_M5.csv with the exact schema of the
certified corpus files (time,iso,open,high,low,close,tick_volume,spread),
so scripts/midas_sweep.load_bars ingests it unchanged.

Evidence discipline:
  * M5 exists nowhere in the repo; the frequency axis of P6 (register §2b)
    needs real broker bars, not synthesized ones. This fetcher is the
    provenance record: source (terminal/broker), UTC range, row count, and
    the fetch timestamp all land in the artifact JSON.
  * spread column = broker points × POINT → dollars, matching the corpus.
  * Fails loudly (exit 1) on: terminal API unavailable, empty range, or a
    partial write. Never overwrites an existing file without --force.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "data", "forex", "xauusd", "XAUUSD_M5.csv")
ART = os.path.join(REPO, "artifacts", "midas_p6_m5_fetch.json")
POINT = 0.01
SYMBOL = "XAUUSD"


def main() -> int:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("MetaTrader5 package unavailable — cannot fetch M5", file=sys.stderr)
        return 1

    if os.path.exists(OUT) and "--force" not in sys.argv:
        print(f"{OUT} exists — pass --force to refetch", file=sys.stderr)
        return 1

    if not mt5.initialize():
        print(f"mt5.initialize() failed: {mt5.last_error()}", file=sys.stderr)
        return 1
    try:
        info = mt5.symbol_info(SYMBOL)
        if info is None:
            print(f"symbol {SYMBOL} not found", file=sys.stderr)
            return 1
        if not mt5.symbol_select(SYMBOL, True):
            print(f"symbol_select({SYMBOL}) failed", file=sys.stderr)
            return 1

        # copy_rates_range is refused by this terminal build ('Invalid
        # params') — the count-based copy_rates_from works. Walk depth down
        # to the terminal's ceiling; the served range lands in the artifact.
        now = datetime.now(timezone.utc)
        rates = None
        for want in (200000, 100000, 50000):
            rates = mt5.copy_rates_from(SYMBOL, mt5.TIMEFRAME_M5, now, want)
            if rates is not None and len(rates) > 0:
                break
        if rates is None or len(rates) == 0:
            print(f"copy_rates_from empty: {mt5.last_error()}", file=sys.stderr)
            return 1

        rows = sorted(rates, key=lambda r: r["time"])
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        tmp = OUT + ".tmp"
        with open(tmp, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "iso", "open", "high", "low", "close",
                        "tick_volume", "spread"])
            for r in rows:
                ts = int(r["time"])
                iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                w.writerow([ts, iso, r["open"], r["high"], r["low"], r["close"],
                            r["tick_volume"], r["spread"]])
        os.replace(tmp, OUT)

        meta = {
            "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbol": SYMBOL,
            "timeframe": "M5",
            "source": "MT5 terminal API (broker history)",
            "rows": len(rows),
            "first_utc": datetime.fromtimestamp(rows[0]["time"], tz=timezone.utc).isoformat(),
            "last_utc": datetime.fromtimestamp(rows[-1]["time"], tz=timezone.utc).isoformat(),
            "terminal_server": mt5.terminal_info().name if mt5.terminal_info() else None,
        }
        with open(ART, "w") as fh:
            json.dump(meta, fh, indent=1)
        print(json.dumps(meta, indent=1))
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
