#!/usr/bin/env python3
"""Account-independent causal 2--4 hour horizon candidate backtest.

The signal uses only closes available at the decision bar. A position opens at
the next M15 bar's bid/ask-adjusted open, uses an ATR-derived stop and target,
and is closed at the first stop/target or at a fixed 8/16-bar horizon. This
module is deliberately independent of account equity and lot sizing so it can
answer the strategy question before money management is considered.

Same-bar stop/target ambiguity is resolved conservatively in favor of the stop.
No parameter is selected from the holdout in this script; all grid cells are
reported for audit.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from replay_v75_week import wilder_atr  # noqa: E402

DEFAULT_DATA = ROOT / "artifacts" / "v75_blind90"
DEFAULT_OUTPUT = DEFAULT_DATA / "horizon_candidate_grid.json"
SPREAD = 18.5
SIGNAL_LOOKBACKS = (8, 16, 32)
TRADE_HORIZONS = (8, 16)
STOP_ATR = (0.5, 0.75, 1.0, 1.25, 1.5)
TARGET_ATR = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5)


@dataclass(frozen=True)
class Candidate:
    """Fixed causal signal and exit geometry."""

    lookback: int
    horizon: int
    stop_atr: float
    target_atr: float


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def signal_direction(closes: list[float], index: int, lookback: int) -> int:
    if closes[index] > closes[index - lookback]:
        return 1
    if closes[index] < closes[index - lookback]:
        return -1
    return 0


def evaluate_trade(rows: list[dict], direction: int, entry: float, stop_distance: float,
                   target_distance: float) -> tuple[float, str, int]:
    half_spread = SPREAD / 2.0
    stop = entry - direction * stop_distance
    target = entry + direction * target_distance
    for offset, row in enumerate(rows, start=1):
        if direction > 0:
            # Long positions exit at bid; rows contain broker-mid OHLC.
            hit_stop = row["l"] - half_spread <= stop
            hit_target = row["h"] - half_spread >= target
        else:
            # Short positions exit at ask; rows contain broker-mid OHLC.
            hit_stop = row["h"] + half_spread >= stop
            hit_target = row["l"] + half_spread <= target
        if hit_stop and hit_target:
            return -1.0, "STOP_AMBIG", offset
        if hit_stop:
            return -1.0, "STOP", offset
        if hit_target:
            return target_distance / stop_distance, "TARGET", offset

    exit_mid = rows[-1]["c"]
    exit_fill = exit_mid - direction * (SPREAD / 2.0)
    return direction * (exit_fill - entry) / stop_distance, "HORIZON", len(rows)


def run_candidate(rows: list[dict], atr: list[float], candidate: Candidate,
                  start: datetime, end: datetime) -> dict:
    closes = [row["c"] for row in rows]
    trades: list[dict] = []
    index = max(480, candidate.lookback)
    while index + candidate.horizon < len(rows):
        timestamp = rows[index]["t"]
        if timestamp < start:
            index += 1
            continue
        if timestamp >= end:
            break
        direction = signal_direction(closes, index, candidate.lookback)
        if direction == 0 or atr[index] <= 0:
            index += 1
            continue

        entry_mid = rows[index + 1]["o"]
        entry = entry_mid + direction * SPREAD / 2.0
        stop_distance = candidate.stop_atr * atr[index]
        target_distance = candidate.target_atr * atr[index]
        future = rows[index + 1:index + candidate.horizon + 1]
        result_r, reason, exit_bars = evaluate_trade(
            future, direction, entry, stop_distance, target_distance,
        )
        trades.append({"time": rows[index + 1]["t"].isoformat(), "direction": direction,
                       "r": result_r, "reason": reason})
        index += max(1, exit_bars)

    values = [trade["r"] for trade in trades]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "n": len(values),
        "wins": sum(value > 0 for value in values),
        "win_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else 0.0,
        "total_r": round(sum(values), 6),
        "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
        "median_r": round(float(np.median(values)), 6) if values else 0.0,
        "max_drawdown_r": round(max_drawdown, 6),
        "exit_reasons": {reason: sum(trade["reason"] == reason for trade in trades)
                         for reason in ("TARGET", "STOP", "STOP_AMBIG", "HORIZON")},
    }


def run(data_dir: Path, start: datetime, split: datetime, end: datetime) -> dict:
    rows = load_from_dir(data_dir / "m15.csv")
    atr = wilder_atr(rows, 14)
    results = []
    for lookback in SIGNAL_LOOKBACKS:
        for horizon in TRADE_HORIZONS:
            for stop_atr in STOP_ATR:
                for target_atr in TARGET_ATR:
                    candidate = Candidate(lookback, horizon, stop_atr, target_atr)
                    results.append({
                        "candidate": candidate.__dict__,
                        "train": run_candidate(rows, atr, candidate, start, split),
                        "holdout": run_candidate(rows, atr, candidate, split, end),
                    })
    return {
        "schema": "mitemshub.v75.horizon-candidate-grid.v1",
        "symbol": "Volatility 75 Index",
        "data_dir": str(data_dir),
        "windows": {"train": [start.isoformat(), split.isoformat()],
                    "holdout": [split.isoformat(), end.isoformat()]},
        "cost_spec": {"spread": SPREAD, "entry": "next M15 open plus bid/ask half-spread",
                      "same_bar_policy": "stop first"},
        "grid": {"signal_lookbacks": SIGNAL_LOOKBACKS, "trade_horizons": TRADE_HORIZONS,
                 "stop_atr": STOP_ATR, "target_atr": TARGET_ATR},
        "results": results,
    }


def load_from_dir(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [{"t": datetime.fromisoformat(row["time"]), "o": float(row["open"]),
                 "h": float(row["high"]), "l": float(row["low"]), "c": float(row["close"])}
                for row in csv.DictReader(handle)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CERT_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--split", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    args = parser.parse_args()
    result = run(args.data_dir, args.start, args.split, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for row in sorted(result["results"], key=lambda item: item["holdout"]["total_r"], reverse=True)[:20]:
        candidate = row["candidate"]
        train, holdout = row["train"], row["holdout"]
        print(f"lb={candidate['lookback']:2d} h={candidate['horizon']:2d} "
              f"sl={candidate['stop_atr']:.2f} tp={candidate['target_atr']:.2f} "
              f"train n={train['n']:3d} R={train['total_r']:+.3f} "
              f"hold n={holdout['n']:3d} R={holdout['total_r']:+.3f} "
              f"hold DD={holdout['max_drawdown_r']:.2f}R")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
