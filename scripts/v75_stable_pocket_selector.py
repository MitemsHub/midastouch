#!/usr/bin/env python3
"""Select Volatility 75 opportunity pockets stable across prior windows.

This is the next research-only layer after the opportunity map and local
walk-forward selector.  A pocket is eligible for a target window only when
its exact causal signature (context, regime, feature bins, direction, horizon,
and geometry) has positive sequential expectancy in *both* prior independent
windows.  Ranking uses the weaker prior-window result first, not the best
result.  The target window is evaluated only after the stable set is frozen.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from clean_slate_v75 import parse_dt  # noqa: E402
from v75_opportunity_map import build_map  # noqa: E402
from v75_opportunity_selector import (Pocket, evaluate_baseline, evaluate_pocket,
                                      select_pockets)  # noqa: E402
from v75_router_core import evaluate_frozen_portfolio, pocket_key  # noqa: E402


def _key(pocket: Pocket) -> tuple:
    return pocket_key(pocket)


def stable_candidates(source_a: dict, source_b: dict, start_a: datetime, end_a: datetime,
                      start_b: datetime, end_b: datetime, min_samples: int) -> list[dict]:
    pockets_a = {_key(pocket): pocket for pocket in select_pockets(
        source_a["metrics"], start_a, end_a, min_samples)}
    pockets_b = {_key(pocket): pocket for pocket in select_pockets(
        source_b["metrics"], start_b, end_b, min_samples)}
    stable: list[dict] = []
    for key in sorted(pockets_a.keys() & pockets_b.keys()):
        pocket = pockets_a[key]
        first = evaluate_pocket(source_a["metrics"], pocket, start_a, end_a)
        second = evaluate_pocket(source_b["metrics"], pocket, start_b, end_b)
        if (first["n"] >= min_samples and second["n"] >= min_samples
                and first["mean_r"] > 0 and second["mean_r"] > 0):
            stable.append({
                "pocket": asdict(pocket),
                "source_a": first,
                "source_b": second,
                "worst_mean_r": min(first["mean_r"], second["mean_r"]),
                "worst_total_r": min(first["total_r"], second["total_r"]),
            })
    return sorted(stable, key=lambda row: (row["worst_mean_r"], row["worst_total_r"]), reverse=True)


def evaluate_portfolio(metrics: list[dict], pockets: list[dict], start: datetime,
                       end: datetime) -> dict:
    """Evaluate a frozen portfolio through the shared lifecycle owner."""
    return evaluate_frozen_portfolio(metrics, pockets, start, end)


def run(source_a: dict, source_b: dict, target: dict, start_a: datetime, end_a: datetime,
        start_b: datetime, end_b: datetime, target_start: datetime, target_end: datetime,
        min_samples: int, portfolio_size: int) -> dict:
    stable = stable_candidates(source_a, source_b, start_a, end_a, start_b, end_b, min_samples)
    portfolio = stable[:portfolio_size]
    target_result = evaluate_portfolio(target["metrics"], portfolio, target_start, target_end)
    transfers: list[dict] = []
    for candidate in portfolio:
        pocket = Pocket(**candidate["pocket"])
        target_single = evaluate_pocket(target["metrics"], pocket, target_start, target_end)
        transfers.append({**candidate, "target": target_single})
    return {
        "schema": "mitemshub.v75.stable-pocket-selector.v1",
        "selection": "exact pocket signature must be profitable in both prior windows; rank by worst prior expectancy",
        "source_a_window": [start_a.isoformat(), end_a.isoformat()],
        "source_b_window": [start_b.isoformat(), end_b.isoformat()],
        "target_window": [target_start.isoformat(), target_end.isoformat()],
        "stable_count": len(stable),
        "portfolio_size": len(portfolio),
        "portfolio": {"source_a": evaluate_portfolio(source_a["metrics"], portfolio, start_a, end_a),
                       "source_b": evaluate_portfolio(source_b["metrics"], portfolio, start_b, end_b),
                       "target": target_result},
        "target_baselines": {
            "long": evaluate_baseline(target["metrics"], target_start, target_end, 1),
            "short": evaluate_baseline(target["metrics"], target_start, target_end, -1),
        },
        "transfers": transfers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for prefix in ("a", "b", "target"):
        parser.add_argument(f"--{prefix}-data-dir", type=Path, required=True)
        parser.add_argument(f"--{prefix}-ticks", type=Path, required=True)
        parser.add_argument(f"--{prefix}-start", type=parse_dt, required=True)
        parser.add_argument(f"--{prefix}-end", type=parse_dt, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--portfolio-size", type=int, default=8)
    args = parser.parse_args()
    source_a = build_map(args.a_data_dir, args.a_ticks, args.a_start, args.a_end)
    source_b = build_map(args.b_data_dir, args.b_ticks, args.b_start, args.b_end)
    target = build_map(args.target_data_dir, args.target_ticks, args.target_start, args.target_end)
    result = run(source_a, source_b, target, args.a_start, args.a_end, args.b_start, args.b_end,
                 args.target_start, args.target_end, args.min_samples, args.portfolio_size)
    result["metrics"] = {"source_a": source_a["metrics_count"], "source_b": source_b["metrics_count"],
                          "target": target["metrics_count"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("stable pockets:", result["stable_count"])
    for row in result["transfers"][:20]:
        p = row["pocket"]
        print(f"{p['context']:12s} {p['regime']:10s} dir={p['direction']:+d} h={p['horizon']:2d} "
              f"{p['geometry']:12s} worst={row['worst_mean_r']:+.3f}R "
              f"target={row['target']['total_r']:+.3f}R n={row['target']['n']}")
    print("target baselines:", result["target_baselines"])
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
