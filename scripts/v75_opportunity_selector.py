#!/usr/bin/env python3
"""Causal opportunity-pocket discovery and reference evaluation for V75."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from clean_slate_v75 import parse_dt  # noqa: E402
from v75_opportunity_map import build_map  # noqa: E402
from v75_router_core import (  # noqa: E402
    GEOMETRIES,
    Pocket,
    evaluate_pocket,
    matches as _matches,
    metric_key,
    path_r as _path_r,
    sequential_rows as _sequential_rows,
)


def pocket_key(row: dict, geometry: str) -> tuple:
    return metric_key(row, geometry)


def select_pockets(metrics: list[dict], start: datetime, end: datetime,
                   min_samples: int = 20, min_target_rate: float = 0.30) -> list[Pocket]:
    """Discover positive pockets from the supplied historical window only."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in metrics:
        timestamp = parse_dt(row["timestamp"])
        if start <= timestamp < end:
            for stop, target in GEOMETRIES:
                geometry = f"sl{stop:g}_tp{target:g}"
                if geometry in row["target_before_stop"]:
                    groups[pocket_key(row, geometry)].append(row)

    pockets: list[Pocket] = []
    for key, candidate_rows in groups.items():
        rows = _sequential_rows(candidate_rows, key[6])
        target_rate = sum(row["target_before_stop"][key[-1]] for row in rows) / len(rows)
        values = [_path_r(row, key[-1]) for row in rows]
        expectancy = float(np.mean(values))
        if len(rows) >= min_samples and target_rate >= min_target_rate and expectancy > 0:
            pocket = Pocket(
                context=key[0], regime=key[1], m32_bin=key[2],
                efficiency_bin=key[3], distance_bin=key[4], direction=key[5],
                horizon=key[6], geometry=key[7], n=len(rows),
                expectancy_r=expectancy, target_rate=target_rate,
            )
            pockets.append(pocket)
    return sorted(pockets, key=lambda pocket: (pocket.expectancy_r, pocket.n), reverse=True)


def evaluate_baseline(metrics: list[dict], start: datetime, end: datetime, direction: int,
                      horizon: int = 12, geometry: str = "sl0.75_tp1.5") -> dict:
    rows = _sequential_rows(
        [row for row in metrics
         if start <= parse_dt(row["timestamp"]) < end
         and row["direction"] == direction and row["horizon"] == horizon],
        horizon,
    )
    values = [_path_r(row, geometry) for row in rows]
    return {"n": len(values), "wins": sum(value > 0 for value in values),
            "total_r": round(float(sum(values)), 6),
            "mean_r": round(float(np.mean(values)), 6) if values else 0.0}


def run_map_selector(map_report: dict, start: datetime, end: datetime,
                     train_days: int, test_days: int, min_samples: int) -> dict:
    metrics = map_report["metrics"]
    folds: list[dict] = []
    cursor = start
    while cursor + timedelta(days=train_days + test_days) <= end:
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        validation_start = train_end - timedelta(days=test_days)
        candidates = select_pockets(metrics, cursor, validation_start, min_samples)
        ranked = [(candidate, evaluate_pocket(metrics, candidate, validation_start, train_end))
                  for candidate in candidates]
        ranked = [item for item in ranked if item[1]["n"] >= 3 and item[1]["mean_r"] > 0]
        selected, validation = (max(ranked, key=lambda item: (item[1]["mean_r"], item[1]["n"]))) \
            if ranked else (None, {"n": 0, "total_r": 0.0, "mean_r": 0.0})
        test = evaluate_pocket(metrics, selected, train_end, test_end) if selected else {"n": 0, "total_r": 0.0}
        folds.append({"train_window": [cursor.isoformat(), train_end.isoformat()],
                      "validation_window": [validation_start.isoformat(), train_end.isoformat()],
                      "test_window": [train_end.isoformat(), test_end.isoformat()],
                      "candidate_count": len(candidates),
                      "selection": asdict(selected) if selected else None,
                      "validation": validation, "test": test,
                      "baseline_long": evaluate_baseline(metrics, train_end, test_end, 1),
                      "baseline_short": evaluate_baseline(metrics, train_end, test_end, -1)})
        cursor += timedelta(days=test_days)
    return {"schema": "mitemshub.v75.opportunity-selector.v1",
            "selection": "candidates from training; highest positive validation expectancy wins",
            "no_trade": "no validated pocket means no trade", "folds": folds}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--ticks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=10)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()
    report = build_map(args.data_dir, args.ticks, args.start, args.end)
    result = run_map_selector(report, args.start, args.end, args.train_days, args.test_days, args.min_samples)
    result["map_source"] = {"metrics": report["metrics_count"], "tick_file": str(args.ticks)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for index, fold in enumerate(result["folds"], 1):
        selected = fold["selection"]
        print(f"fold={index} selected={selected['context'] if selected else 'NO_TRADE'} "
              f"test_n={fold['test']['n']} test_R={fold['test']['total_r']:+.3f}")
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
