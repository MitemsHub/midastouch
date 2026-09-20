#!/usr/bin/env python3
"""Measure the LIVE XAUUSD spread and compare it against the research cost model.

WHY THIS EXISTS. Every gold verdict in this repo is quoted in R net of a modelled cost
of `SPREAD_BPS = 1.073` basis points on the entry price plus `$10`/lot round-trip
commission (`scripts/gold_walkforward.py`). Those numbers came from a study, not from
this venue, and the account's whole edge is thin enough that a wrong cost figure changes
verdicts: DAILY-ONE cleared its null by 0.50R at 32 reps and failed by 0.19R at 200. A
cost that is 30% wider than modelled is the same order of magnitude as the entire
disagreement between the two measurements.

WHAT IT MEASURES, AND WHAT IT CANNOT.
* **Spread**: measurable directly, from `ask - bid`, in the same units the cost model
  uses (fraction of price). Sampled repeatedly, because a single reading is one moment.
* **Commission**: NOT measurable without placing a trade, and this repo sends no orders.
  So the documented `$10`/lot is taken as given and reported as **unverified** rather
  than passed off as measured.
* **Slippage**: not measurable without fills. Not claimed.

REFUSES WHEN THE MARKET IS CLOSED. A weekend or overnight spread is typically much wider
than an in-session spread — the readiness gate read 60 points on a Saturday — and feeding
that into a cost model would make the model pessimistic for the wrong reason. So a stale
tick is a refusal (exit 3), not a measurement.

    python scripts/measure_live_costs.py                 # 20 samples, 3s apart
    python scripts/measure_live_costs.py --samples 60 --interval 5
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from gold_walkforward import COMMISSION_PER_LOT_RT, SPREAD_BPS  # noqa: E402

SAMPLES_PATH = ROOT / "artifacts" / "live" / "cost_samples.jsonl"
TICK_FRESH_S = 300


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--stop-atr-mult", type=float, default=2.0,
                    help="stop as a multiple of ATR, to express cost per R")
    ap.add_argument("--atr-price", type=float, default=None,
                    help="ATR in price units; if omitted the tool refuses to give R")
    ap.add_argument("--tolerance", type=float, default=0.25,
                    help="fractional excess over the model that counts as OPTIMISTIC")
    args = ap.parse_args(argv)

    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        print(f"TERMINAL UNAVAILABLE: MetaTrader5 module not installed ({exc})",
              file=sys.stderr)
        return 3
    if not mt5.initialize():
        print(f"TERMINAL UNAVAILABLE: mt5.initialize() failed, "
              f"code {mt5.last_error()}", file=sys.stderr)
        return 3

    now = datetime.now(timezone.utc)
    readings: list[dict] = []
    try:
        first = mt5.symbol_info_tick(args.symbol)
        if first is None:
            print(f"TERMINAL UNAVAILABLE: no tick for {args.symbol}", file=sys.stderr)
            return 3
        age = now.timestamp() - float(first.time)
        if age > TICK_FRESH_S:
            print(f"REFUSING: last {args.symbol} tick was {age / 60:.0f} min ago, so "
                  f"the market is closed. A closed-market spread is typically much "
                  f"wider than an in-session one, and using it would make the cost "
                  f"model pessimistic for the wrong reason. Re-run during the "
                  f"session.", file=sys.stderr)
            return 3
        digits = mt5.symbol_info(args.symbol).digits
        for i in range(args.samples):
            t = mt5.symbol_info_tick(args.symbol)
            info = mt5.symbol_info(args.symbol)
            if t is None or info is None:
                break
            bid, ask = float(t.bid), float(t.ask)
            if bid <= 0 or ask <= 0:
                break
            mid = (bid + ask) / 2.0
            readings.append({
                "utc": datetime.fromtimestamp(float(t.time), timezone.utc).isoformat(
                    timespec="seconds"),
                "bid": bid, "ask": ask,
                "spread_price": round(ask - bid, 6),
                "spread_points": int(info.spread),
                "spread_bps": round((ask - bid) / mid * 1e4, 4) if mid else None,
            })
            if i + 1 < args.samples:
                time.sleep(args.interval)
    finally:
        mt5.shutdown()

    if not readings:
        print("no usable readings collected", file=sys.stderr)
        return 3

    bps = [r["spread_bps"] for r in readings if r["spread_bps"]]
    prices = [r["bid"] for r in readings]
    median_bps = statistics.median(bps)
    mean_bps = statistics.mean(bps)
    worst_bps = max(bps)
    model_price = statistics.median(prices) * SPREAD_BPS / 1e4
    measured_price = statistics.median(prices) * median_bps / 1e4

    print(f"=== LIVE COST MEASUREMENT — {args.symbol} @ "
          f"{now:%Y-%m-%d %H:%M} UTC ===")
    print(f"readings        {len(readings)} over {args.samples * args.interval:.0f}s "
          f"(price ~{statistics.median(prices):,.2f})")
    print(f"spread bps      median {median_bps:.4f}   mean {mean_bps:.4f}   "
          f"max {worst_bps:.4f}")
    print(f"spread price    median ${measured_price:.4f} "
          f"(points {readings[len(readings)//2]['spread_points']})")
    print(f"model spread    {SPREAD_BPS:.4f} bps = ${model_price:.4f}")
    ratio = median_bps / SPREAD_BPS if SPREAD_BPS else float("inf")
    optimistic = ratio > 1.0 + args.tolerance
    print(f"model vs live   {ratio:.2f}x  -> "
          f"{'MODEL IS OPTIMISTIC' if optimistic else 'model holds'}")
    print(f"commission      ${COMMISSION_PER_LOT_RT:.2f}/lot round trip — "
          f"NOT MEASURED (no orders are sent, so this is the documented figure, not "
          f"an observation)")

    per_r = None
    if args.atr_price:
        stop = args.stop_atr_mult * args.atr_price
        per_r = (measured_price / (stop * 100.0)) if stop else None
        print(f"cost per R      ${measured_price + COMMISSION_PER_LOT_RT * 0.01:,.4f} "
              f"on a {stop:,.2f} stop "
              f"({(measured_price + COMMISSION_PER_LOT_RT * 0.01) / stop:.4f}R)")
    else:
        print("cost per R      withheld: pass --atr-price to convert, because a cost "
              "in R without a stop distance is the same mistake the geometry study "
              "found in the 0.0247R figure.")

    row = {"utc": now.isoformat(timespec="seconds"), "symbol": args.symbol,
           "readings": len(readings), "median_bps": median_bps, "mean_bps": mean_bps,
           "max_bps": worst_bps, "model_bps": SPREAD_BPS, "ratio": ratio,
           "model_optimistic": optimistic, "per_r": per_r,
           "commission_measured": False}
    SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(f"\nappended to {SAMPLES_PATH}")
    if optimistic:
        print(f"WARNING: the live spread is {ratio:.2f}x the modelled "
              f"{SPREAD_BPS:.4f} bps. Any verdict that turned on a margin smaller than "
              f"{(ratio - 1):.0%} of the cost component should be re-run before it is "
              f"trusted.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
