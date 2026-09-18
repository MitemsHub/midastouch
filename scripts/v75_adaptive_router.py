#!/usr/bin/env python3
"""Recency-weighted state-adaptive Volatility 75 research router.

At each walk-forward fold the router learns candidate pockets from a historical
window, scores them on a separate recent validation window, and then trades
only the selected state-matched pocket portfolio in the untouched test window.
The validation score blends long-history expectancy with recent expectancy so
the system can adapt when continuation becomes reversal (or vice versa)
without selecting on the test window.

This module is research-only and does not modify the EA.
"""
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
from v75_opportunity_selector import (  # noqa: E402
    evaluate_baseline,
    evaluate_pocket,
    select_pockets,
)
from v75_router_core import (  # noqa: E402
    Pocket,
    evaluate_frozen_portfolio,
    matches as _matches,
    path_r as _path_r,
    pocket_key as _key,
    sequential_rows as _sequential_rows,
)


def discover(metrics: list[dict], start: datetime, end: datetime,
             min_samples: int = 20) -> dict[tuple, Pocket]:
    """Discover positive candidate pockets without looking beyond ``end``."""
    return {_key(pocket): pocket for pocket in select_pockets(metrics, start, end, min_samples)}


def score_candidates(metrics: list[dict], candidates: dict[tuple, Pocket],
                     long_start: datetime, validation_start: datetime,
                     validation_end: datetime, recent_weight: float = 0.65,
                     min_validation_samples: int = 3) -> list[dict]:
    scored: list[dict] = []
    for key, pocket in candidates.items():
        long_result = evaluate_pocket(metrics, pocket, long_start, validation_start)
        recent_result = evaluate_pocket(metrics, pocket, validation_start, validation_end)
        validation_candidates = [
            row for row in metrics
            if validation_start <= parse_dt(row["timestamp"]) < validation_end
            and _matches(row, pocket)
        ]
        validation_rows = _sequential_rows(validation_candidates, pocket.horizon)
        if recent_result["n"] < min_validation_samples or recent_result["mean_r"] <= 0:
            continue
        if not validation_rows:
            continue
        target_atr = float(pocket.geometry.split("_tp", 1)[1])
        stop_atr = float(pocket.geometry[2:].split("_", 1)[0])
        target_rate = float(np.mean([
            row["target_before_stop"].get(pocket.geometry, False)
            for row in validation_rows
        ]))
        stop_rate = float(np.mean([
            row["mae_r"] <= -stop_atr for row in validation_rows
        ]))
        break_even_rate = 1.0 / (1.0 + target_atr / stop_atr)
        if target_rate < break_even_rate + 0.03 or stop_rate > 0.65:
            continue
        blended = ((1.0 - recent_weight) * long_result["mean_r"]
                   + recent_weight * recent_result["mean_r"])
        transition_groups: dict[str, list[dict]] = defaultdict(list)
        for row in metrics:
            timestamp = parse_dt(row["timestamp"])
            if validation_start <= timestamp < validation_end and _matches(row, pocket):
                transition_groups[row.get("transition_state", "UNKNOWN")].append(row)
        allowed_states = ["STABLE_BULL", "STABLE_BEAR", "STABLE_RANGE", "STABLE_TRANSITION", "STABLE_UNKNOWN"]
        for state, state_rows in transition_groups.items():
            state_values = [_path_r(row, pocket.geometry) for row in state_rows]
            if len(state_values) >= 2 and float(np.mean(state_values)) > 0:
                allowed_states.append(state)
        scored.append({"pocket": asdict(pocket), "long": long_result,
                       "recent": recent_result, "blended_mean_r": blended,
                       "target_rate": round(target_rate, 6),
                       "stop_rate": round(stop_rate, 6),
                       "geometry_cost_gate": "target_rate>break_even+0.03 and stop_rate<=0.65",
                       "allowed_transition_states": sorted(set(allowed_states))})
    return sorted(scored, key=lambda item: (item["blended_mean_r"], item["recent"]["mean_r"]), reverse=True)


def evaluate_router(metrics: list[dict], selected: list[dict], start: datetime,
                    end: datetime, health_loss_streak: int = 3) -> dict:
    """Evaluate a frozen portfolio through the shared router lifecycle."""
    return evaluate_frozen_portfolio(metrics, selected, start, end, health_loss_streak)


def run(metrics: list[dict], start: datetime, end: datetime, train_days: int,
        validation_days: int, test_days: int, portfolio_size: int,
        min_samples: int, recent_weight: float,
        stress_metrics: dict[float, list[dict]] | None = None,
        health_loss_streak: int = 3) -> dict:
    folds: list[dict] = []
    cursor = start
    while cursor + timedelta(days=train_days + validation_days + test_days) <= end:
        train_end = cursor + timedelta(days=train_days)
        validation_start = train_end
        validation_end = validation_start + timedelta(days=validation_days)
        test_end = validation_end + timedelta(days=test_days)
        discovered = discover(metrics, cursor, train_end, min_samples)
        scored = score_candidates(metrics, discovered, cursor, validation_start,
                                 validation_end, recent_weight)
        selected = scored[:portfolio_size]
        test = evaluate_router(metrics, selected, validation_end, test_end, health_loss_streak)
        stress = {
            str(multiplier): evaluate_router(rows, selected, validation_end, test_end,
                                             health_loss_streak)
            for multiplier, rows in (stress_metrics or {}).items()
        }
        folds.append({"train_window": [cursor.isoformat(), train_end.isoformat()],
                      "validation_window": [validation_start.isoformat(), validation_end.isoformat()],
                      "test_window": [validation_end.isoformat(), test_end.isoformat()],
                      "discovered": len(discovered), "selected": selected,
                      "test": test, "stress": stress,
                      "baseline_long": evaluate_baseline(metrics, validation_end, test_end, 1),
                      "baseline_short": evaluate_baseline(metrics, validation_end, test_end, -1)})
        cursor += timedelta(days=test_days)
    return {"schema": "mitemshub.v75.adaptive-router.v1",
            "selection": "training discovery + recency-weighted validation; untouched test",
            "router": {"train_days": train_days, "validation_days": validation_days,
                       "test_days": test_days, "portfolio_size": portfolio_size,
                       "recent_weight": recent_weight, "min_samples": min_samples,
                       "health_loss_streak": health_loss_streak,
                       "stress_multipliers": sorted(stress_metrics or {})},
            "folds": folds}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--ticks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--validation-days", type=int, default=10)
    parser.add_argument("--test-days", type=int, default=10)
    parser.add_argument("--portfolio-size", type=int, default=8)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--recent-weight", type=float, default=0.65)
    parser.add_argument("--health-loss-streak", type=int, default=3)
    args = parser.parse_args()
    report = build_map(args.data_dir, args.ticks, args.start, args.end)
    stress_reports = {
        multiplier: build_map(args.data_dir, args.ticks, args.start, args.end, multiplier)
        for multiplier in (1.5, 2.0)
    }
    result = run(report["metrics"], args.start, args.end, args.train_days,
                 args.validation_days, args.test_days, args.portfolio_size,
                 args.min_samples, args.recent_weight,
                 {multiplier: stress_report["metrics"]
                  for multiplier, stress_report in stress_reports.items()},
                 args.health_loss_streak)
    result["map_source"] = {"metrics": report["metrics_count"], "tick_file": str(args.ticks)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for index, fold in enumerate(result["folds"], 1):
        print(f"fold={index} selected={len(fold['selected'])} test_n={fold['test']['n']} "
              f"test_R={fold['test']['total_r']:+.3f} "
              f"long_R={fold['baseline_long']['total_r']:+.3f} "
              f"short_R={fold['baseline_short']['total_r']:+.3f}")
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
