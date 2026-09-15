#!/usr/bin/env python3
"""Measure whether the current V75 context predicts the next 2--4 hours.

This is a read-only research diagnostic. It does not simulate orders and does
not use account equity, minimum lots, or compounding. At every eligible closed
M15 bar it records the current H1 trend context, M15 EMA pullback context,
return momentum, RSI, ATR percentile, and EGARCH sigma state. It then measures
forward 8-bar and 16-bar outcomes (2h and 4h) from the next bar's open,
including maximum favorable/adverse excursion over each horizon.

The output is descriptive only: no thresholds are selected from the output and
no production preset is changed.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from replay_v75_week import (  # noqa: E402
    Egarch,
    ema,
    wilder_atr,
    wilder_rsi,
    EMA_FAST,
    EMA_MID,
    EMA_SLOW,
    MIN_EMA_SEP,
    ATR_LOOKBACK,
    BULL,
    BEAR,
    RANGE,
    HVOL,
    NOTRADE,
    RNAME,
)

DEFAULT_DATA = ROOT / "artifacts" / "v75_blind90"
DEFAULT_OUTPUT = DEFAULT_DATA / "horizon_diagnostic_2h_4h.json"
HORIZONS = (8, 16)


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def percentile(value: float, history: list[float]) -> float:
    if len(history) < 40:
        return 50.0
    window = history[-ATR_LOOKBACK:]
    return sum(item < value for item in window) / len(window) * 100.0


def regime_at(index: int, m15: list[dict], atr: list[float], h1: list[dict],
              h_fast: list[float], h_mid: list[float], h_slow: list[float],
              atr_history: list[float]) -> tuple[str, float]:
    target_time = m15[index]["t"]
    h1_times = [row["t"] for row in h1]
    h_index = max(0, np.searchsorted(h1_times, target_time, side="right") - 1)
    if h1[h_index]["t"] == target_time and h_index > 0:
        h_index -= 1
    current_atr = atr[index]
    atr_pct = percentile(current_atr, atr_history)
    if atr_pct > 92.0:
        return "HIGH_VOL", atr_pct
    if atr_pct < 10.0:
        return "NO_TRADE", atr_pct
    close = h1[h_index]["c"]
    separation = abs(h_fast[h_index] - h_mid[h_index]) / current_atr if current_atr > 0 else 0.0
    if h_fast[h_index] > h_mid[h_index] > h_slow[h_index] and close > h_fast[h_index] and separation >= MIN_EMA_SEP:
        return "BULLISH", atr_pct
    if h_fast[h_index] < h_mid[h_index] < h_slow[h_index] and close < h_fast[h_index] and separation >= MIN_EMA_SEP:
        return "BEARISH", atr_pct
    return "RANGING", atr_pct


def classify_forward(rows: list[dict], direction: int, horizon: int) -> dict:
    start = rows[0]["open_next"]
    end = rows[horizon - 1]["c"]
    signed_return = direction * (end - start) / start if start else 0.0
    signed_high = max(direction * (row["h"] - start) / start for row in rows)
    signed_low = min(direction * (row["l"] - start) / start for row in rows)
    return {
        "signed_return": signed_return,
        "mfe": signed_high,
        "mae": signed_low,
        "hit": signed_return > 0,
    }


def summarize(records: list[dict], horizon: int) -> dict:
    selected = [record for record in records if record["horizons"].get(str(horizon))]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in selected:
        grouped[record["bucket"]].append(record["horizons"][str(horizon)])

    def stats(items: list[dict]) -> dict:
        if not items:
            return {"n": 0, "hit_rate": None, "mean_return": None, "median_return": None,
                    "mean_mfe": None, "mean_mae": None}
        return {
            "n": len(items),
            "hit_rate": round(sum(item["hit"] for item in items) / len(items) * 100.0, 2),
            "mean_return": round(float(np.mean([item["signed_return"] for item in items])), 6),
            "median_return": round(float(np.median([item["signed_return"] for item in items])), 6),
            "mean_mfe": round(float(np.mean([item["mfe"] for item in items])), 6),
            "mean_mae": round(float(np.mean([item["mae"] for item in items])), 6),
        }

    return {bucket: stats(items) for bucket, items in sorted(grouped.items())}


def run(data_dir: Path, start: datetime | None, end: datetime | None) -> dict:
    m15 = load_from_dir(data_dir / "m15.csv")
    h1 = load_from_dir(data_dir / "h1.csv")
    closes = [row["c"] for row in m15]
    e_fast, e_mid, e_slow = ema(closes, EMA_FAST), ema(closes, EMA_MID), ema(closes, EMA_SLOW)
    atr = wilder_atr(m15, 14)
    rsi = wilder_rsi(closes)
    h1_closes = [row["c"] for row in h1]
    h_fast = ema(h1_closes, EMA_FAST)
    h_mid = ema(h1_closes, EMA_MID)
    h_slow = ema(h1_closes, EMA_SLOW)

    garch = Egarch()
    sigma_ema = 0.0
    sigma_ready = False
    atr_history: list[float] = []
    rows_by_time = [row["t"] for row in m15]
    records: list[dict] = []
    warmup = max(480, 200)
    first = warmup
    if start is not None:
        first = max(first, next((i for i, row in enumerate(m15) if row["t"] >= start), len(m15)))
    last = len(m15) - max(HORIZONS) - 1
    if end is not None:
        last = min(last, next((i for i, row in enumerate(m15) if row["t"] >= end), len(m15)) - 1)

    for index in range(first, last + 1):
        if index > 0:
            sigma, warm = garch.update(math.log(closes[index] / closes[index - 1]))
            if sigma_ready:
                alpha = 2.0 / 31.0
                sigma_ema = alpha * sigma + (1.0 - alpha) * sigma_ema
            else:
                sigma_ema, sigma_ready = sigma, True
        current_atr = atr[index]
        regime, atr_pct = regime_at(index, m15, atr, h1, h_fast, h_mid, h_slow, atr_history)
        atr_history.append(current_atr)
        if len(atr_history) > ATR_LOOKBACK + 10:
            atr_history.pop(0)

        close = closes[index]
        ema_distance = (close - e_fast[index]) / current_atr if current_atr else 0.0
        body = m15[index]["c"] - m15[index]["o"]
        candle_range = m15[index]["h"] - m15[index]["l"]
        momentum = body / candle_range if candle_range else 0.0
        sigma_ratio = sigma / sigma_ema if sigma_ready and sigma_ema > 0 else 1.0
        directional_bias = 1 if regime == "BULLISH" else -1 if regime == "BEARISH" else 0
        if directional_bias == 0:
            bucket = "NEUTRAL"
        elif abs(ema_distance) < 0.3:
            bucket = "TREND_NEAR_EMA"
        elif abs(ema_distance) <= 2.2:
            bucket = "TREND_PULLBACK_ZONE"
        else:
            bucket = "TREND_EXTENDED"

        horizon_rows = []
        for offset in range(1, max(HORIZONS) + 1):
            bar = m15[index + offset]
            horizon_rows.append({"open_next": m15[index + 1]["o"], **bar})
        horizons = {}
        for horizon in HORIZONS:
            horizons[str(horizon)] = classify_forward(horizon_rows[:horizon], directional_bias, horizon) if directional_bias else None

        records.append({
            "time": m15[index]["t"].isoformat(),
            "regime": regime,
            "bucket": bucket,
            "direction": directional_bias,
            "atr_percentile": round(atr_pct, 2),
            "ema_distance_atr": round(ema_distance, 4),
            "rsi": round(rsi[index], 4) if rsi[index] is not None else None,
            "body_ratio": round(momentum, 4),
            "sigma_ratio": round(sigma_ratio, 4),
            "horizons": horizons,
        })

    return {
        "schema": "mitemshub.v75.horizon-diagnostic.v1",
        "symbol": "Volatility 75 Index",
        "data_dir": str(data_dir),
        "window": {
            "start": records[0]["time"] if records else None,
            "end": records[-1]["time"] if records else None,
            "records": len(records),
        },
        "horizons": {
            "2h": summarize(records, 8),
            "4h": summarize(records, 16),
        },
        "records": records,
    }


def load_from_dir(path: Path) -> list[dict]:
    """Load the explicit OHLC corpus requested by the caller."""
    with path.open(encoding="utf-8", newline="") as handle:
        return [{
            "t": datetime.fromisoformat(row["time"]),
            "o": float(row["open"]),
            "h": float(row["high"]),
            "l": float(row["low"]),
            "c": float(row["close"]),
        } for row in csv.DictReader(handle)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CERT_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=parse_dt, default=None)
    parser.add_argument("--end", type=parse_dt, default=None)
    args = parser.parse_args()
    result = run(args.data_dir, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"wrote {args.output}")
    for horizon, groups in result["horizons"].items():
        print(horizon)
        for bucket, stats in groups.items():
            print(f"  {bucket:22s} n={stats['n']:4d} hit={stats['hit_rate']}% "
                  f"mean={stats['mean_return']} mfe={stats['mean_mfe']} mae={stats['mean_mae']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
