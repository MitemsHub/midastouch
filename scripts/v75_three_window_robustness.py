#!/usr/bin/env python3
"""Require Volatility 75 opportunity pockets to survive three windows.

This is a research-only promotion gate.  It intersects exact opportunity
signatures from three independent windows and keeps only signatures with
positive sequential expectancy and sufficient observations in all three.
Ranking is based on the weakest window, so one exceptional period cannot hide
a failure elsewhere.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from clean_slate_v75 import parse_dt  # noqa: E402
from v75_opportunity_map import build_map  # noqa: E402
from v75_opportunity_selector import evaluate_baseline, evaluate_pocket, select_pockets  # noqa: E402
from v75_stable_pocket_selector import _key  # noqa: E402


def robust_candidates(reports: list[dict], windows: list[tuple[datetime, datetime]],
                      min_samples: int) -> list[dict]:
    pocket_sets = [
        {_key(pocket): pocket for pocket in select_pockets(report["metrics"], start, end, min_samples)}
        for report, (start, end) in zip(reports, windows)
    ]
    stable_keys = set.intersection(*(set(items) for items in pocket_sets)) if pocket_sets else set()
    result: list[dict] = []
    for key in sorted(stable_keys):
        pocket = pocket_sets[0][key]
        outcomes = [evaluate_pocket(report["metrics"], pocket, start, end)
                    for report, (start, end) in zip(reports, windows)]
        if all(item["n"] >= min_samples and item["mean_r"] > 0 for item in outcomes):
            result.append({
                "pocket": asdict(pocket),
                "windows": outcomes,
                "worst_mean_r": min(item["mean_r"] for item in outcomes),
                "worst_total_r": min(item["total_r"] for item in outcomes),
            })
    return sorted(result, key=lambda item: (item["worst_mean_r"], item["worst_total_r"]), reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for prefix in ("old", "middle", "recent"):
        parser.add_argument(f"--{prefix}-data-dir", type=Path, required=True)
        parser.add_argument(f"--{prefix}-ticks", type=Path, required=True)
        parser.add_argument(f"--{prefix}-start", type=parse_dt, required=True)
        parser.add_argument(f"--{prefix}-end", type=parse_dt, required=True)
    parser.add_argument("--target", choices=("old", "middle", "recent"), default="recent")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()
    specs = [
        (args.old_data_dir, args.old_ticks, args.old_start, args.old_end),
        (args.middle_data_dir, args.middle_ticks, args.middle_start, args.middle_end),
        (args.recent_data_dir, args.recent_ticks, args.recent_start, args.recent_end),
    ]
    reports = [build_map(data_dir, ticks, start, end) for data_dir, ticks, start, end in specs]
    windows = [(start, end) for _, _, start, end in specs]
    stable = robust_candidates(reports, windows, args.min_samples)
    target_index = {"old": 0, "middle": 1, "recent": 2}[args.target]
    target_report = reports[target_index]
    target_start, target_end = windows[target_index]
    result = {
        "schema": "mitemshub.v75.three-window-robustness.v1",
        "selection": "exact feature pocket must be positive with sufficient sequential samples in all three windows",
        "windows": [[start.isoformat(), end.isoformat()] for start, end in windows],
        "stable_count": len(stable),
        "target": args.target,
        "target_baselines": {
            "long": evaluate_baseline(target_report["metrics"], target_start, target_end, 1),
            "short": evaluate_baseline(target_report["metrics"], target_start, target_end, -1),
        },
        "candidates": stable,
        "metrics": {"windows": [report["metrics_count"] for report in reports]},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("stable all-three-window pockets:", len(stable))
    for item in stable[:20]:
        pocket = item["pocket"]
        totals = ", ".join(f"{row['total_r']:+.3f}R" for row in item["windows"])
        print(f"{pocket['context']:12s} {pocket['regime']:10s} dir={pocket['direction']:+d} "
              f"h={pocket['horizon']:2d} {pocket['geometry']:12s} "
              f"worst={item['worst_mean_r']:+.3f}R windows=[{totals}]")
    print("target baselines:", result["target_baselines"])
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
