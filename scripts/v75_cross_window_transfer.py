#!/usr/bin/env python3
"""Transfer Volatility 75 opportunity pockets across independent windows.

Pockets are discovered exclusively in a historical source window, ranked by
source-window expectancy, and then evaluated unchanged in a later target
window.  No target-window outcome is used for selection.  This is the direct
anti-curve-fit test for the opportunity-map strategy.
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


def transfer(source_report: dict, target_report: dict, source_start: datetime,
             source_end: datetime, target_start: datetime, target_end: datetime,
             min_samples: int) -> dict:
    candidates = select_pockets(source_report["metrics"], source_start, source_end, min_samples)
    ranked = []
    for pocket in candidates:
        source = evaluate_pocket(source_report["metrics"], pocket, source_start, source_end)
        if source["n"] >= min_samples and source["mean_r"] > 0:
            target = evaluate_pocket(target_report["metrics"], pocket, target_start, target_end)
            ranked.append({"pocket": asdict(pocket), "source": source, "target": target})
    ranked.sort(key=lambda row: (row["source"]["mean_r"], row["source"]["n"]), reverse=True)
    long_baseline = evaluate_baseline(target_report["metrics"], target_start, target_end, 1)
    short_baseline = evaluate_baseline(target_report["metrics"], target_start, target_end, -1)
    return {
        "schema": "mitemshub.v75.cross-window-transfer.v1",
        "selection": "source-window positive expectancy only; target untouched",
        "source_window": [source_start.isoformat(), source_end.isoformat()],
        "target_window": [target_start.isoformat(), target_end.isoformat()],
        "candidate_count": len(ranked),
        "target_baselines": {"long": long_baseline, "short": short_baseline},
        "transfers": ranked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-data-dir", type=Path, required=True)
    parser.add_argument("--source-ticks", type=Path, required=True)
    parser.add_argument("--source-start", type=parse_dt, required=True)
    parser.add_argument("--source-end", type=parse_dt, required=True)
    parser.add_argument("--target-data-dir", type=Path, required=True)
    parser.add_argument("--target-ticks", type=Path, required=True)
    parser.add_argument("--target-start", type=parse_dt, required=True)
    parser.add_argument("--target-end", type=parse_dt, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()
    source = build_map(args.source_data_dir, args.source_ticks, args.source_start, args.source_end)
    target = build_map(args.target_data_dir, args.target_ticks, args.target_start, args.target_end)
    result = transfer(source, target, args.source_start, args.source_end,
                      args.target_start, args.target_end, args.min_samples)
    result["source_metrics"] = source["metrics_count"]
    result["target_metrics"] = target["metrics_count"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("source metrics:", source["metrics_count"], "target metrics:", target["metrics_count"])
    print("eligible transfers:", result["candidate_count"])
    for row in result["transfers"][:10]:
        pocket = row["pocket"]
        print(f"{pocket['context']:12s} {pocket['regime']:10s} dir={pocket['direction']:+d} "
              f"h={pocket['horizon']:2d} {pocket['geometry']:12s} "
              f"source={row['source']['total_r']:+.3f}R target={row['target']['total_r']:+.3f}R "
              f"target_n={row['target']['n']}")
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
