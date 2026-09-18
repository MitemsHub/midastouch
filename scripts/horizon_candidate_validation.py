#!/usr/bin/env python3
"""Validate a fixed causal horizon candidate across folds and spread stress."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from replay_v75_week import wilder_atr  # noqa: E402

DEFAULT_DATA = ROOT / "artifacts" / "v75_blind90"


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [{"t": datetime.fromisoformat(row["time"]), "o": float(row["open"]),
                 "h": float(row["high"]), "l": float(row["low"]), "c": float(row["close"])}
                for row in csv.DictReader(handle)]


def evaluate(rows: list[dict], atr: list[float], start: datetime, end: datetime,
             lookback: int, horizon: int, stop_atr: float, target_atr: float,
             spread: float, reassess_bars: int) -> dict:
    closes = [row["c"] for row in rows]
    values: list[float] = []
    reasons: dict[str, int] = {"TARGET": 0, "STOP": 0, "STOP_AMBIG": 0, "HORIZON": 0}
    index = max(480, lookback)
    while index + horizon < len(rows):
        if rows[index]["t"] < start:
            index += 1
            continue
        if rows[index]["t"] >= end:
            break
        direction = 1 if closes[index] > closes[index - lookback] else -1 if closes[index] < closes[index - lookback] else 0
        if direction == 0 or atr[index] <= 0:
            index += 1
            continue
        entry = rows[index + 1]["o"] + direction * spread / 2.0
        stop_distance = stop_atr * atr[index]
        target_distance = target_atr * atr[index]
        half_spread = spread / 2.0
        stop = entry - direction * stop_distance
        target = entry + direction * target_distance
        exit_bars = horizon
        reason = "HORIZON"
        value = None
        for offset, row in enumerate(rows[index + 1:index + horizon + 1], start=1):
            hit_stop = row["l"] - half_spread <= stop if direction > 0 else row["h"] + half_spread >= stop
            hit_target = row["h"] - half_spread >= target if direction > 0 else row["l"] + half_spread <= target
            if hit_stop and hit_target:
                value, reason = -1.0, "STOP_AMBIG"
                exit_bars = offset
                break
            if hit_stop:
                value, reason = -1.0, "STOP"
                exit_bars = offset
                break
            if hit_target:
                value, reason = target_distance / stop_distance, "TARGET"
                exit_bars = offset
                break
        if value is None:
            exit_fill = rows[index + horizon]["c"] - direction * spread / 2.0
            value = direction * (exit_fill - entry) / stop_distance
        values.append(value)
        reasons[reason] += 1
        index += max(1, exit_bars + reassess_bars)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {"n": len(values), "wins": sum(value > 0 for value in values),
            "hit_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else 0.0,
            "total_r": round(sum(values), 6),
            "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
            "max_drawdown_r": round(max_dd, 6), "exit_reasons": reasons}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CERT_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--output", type=Path, default=DEFAULT_DATA / "horizon_candidate_validation.json")
    parser.add_argument("--lookback", type=int, default=32)
    parser.add_argument("--horizon", type=int, default=16)
    parser.add_argument("--stop-atr", type=float, default=0.75)
    parser.add_argument("--target-atr", type=float, default=2.5)
    parser.add_argument("--reassess-bars", type=int, default=20,
                        help="bars between completed-trade reassessments (20 ~= 4.8/day)")
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    args = parser.parse_args()
    if args.reassess_bars < 0:
        parser.error("--reassess-bars cannot be negative")
    rows = load_rows(args.data_dir / "m15.csv")
    atr = wilder_atr(rows, 14)
    spreads = (18.5, 27.75, 37.0)
    results = []
    for spread in spreads:
        for fold in range(3):
            start = args.start + (args.end - args.start) * fold / 3
            end = args.start + (args.end - args.start) * (fold + 1) / 3
            results.append({"spread": spread, "fold": fold + 1,
                            "window": [start.isoformat(), end.isoformat()],
                            "result": evaluate(rows, atr, start, end, args.lookback, args.horizon,
                                               args.stop_atr, args.target_atr, spread,
                                               args.reassess_bars)})
    output = {"schema": "mitemshub.v75.horizon-candidate-validation.v1",
              "candidate": {"lookback": args.lookback, "horizon": args.horizon,
                            "reassess_bars": args.reassess_bars,
                            "stop_atr": args.stop_atr, "target_atr": args.target_atr},
              "spreads": spreads, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=1), encoding="utf-8")
    for row in results:
        result = row["result"]
        print(f"spread={row['spread']:5.2f} fold={row['fold']} n={result['n']:3d} "
              f"R={result['total_r']:+8.3f} mean={result['mean_r']:+.5f} "
              f"hit={result['hit_rate']:5.1f}% DD={result['max_drawdown_r']:.2f}R")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
