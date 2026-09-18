#!/usr/bin/env python3
"""CLI for the research-only V75 geometry-policy comparison."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from clean_slate_v75 import parse_dt  # noqa: E402
from v75_geometry_policy import (  # noqa: E402
    POLICY_CALIBRATED,
    POLICY_ORIGINAL,
    POLICIES,
    choose_policy,
    fit_calibrated,
    fit_policies,
    score_policies,
    validation_stress_results,
)
from v75_geometry_policy_engine import run  # noqa: E402
from v75_geometry_policy_snapshot import (  # noqa: E402
    SnapshotIntegrityError,
    deterministic_fingerprint,
    resolve_cli_snapshots,
    validate_map_snapshot,
)
from v75_opportunity_map import build_map  # noqa: E402


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
    parser.add_argument("--min-validation-trades", type=int, default=3)
    parser.add_argument("--health-loss-streak", type=int, default=3)
    parser.add_argument("--map-snapshot", "--opportunity-map-snapshot", type=Path, default=None)
    parser.add_argument("--stress-map-snapshot", "--stress-snapshot", action="append", nargs=2,
                        metavar=("MULTIPLIER", "SNAPSHOT"), default=[])
    args = parser.parse_args()

    base, stress = resolve_cli_snapshots(
        args.data_dir,
        args.ticks,
        args.start,
        args.end,
        args.map_snapshot,
        [(float(multiplier), Path(snapshot))
         for multiplier, snapshot in args.stress_map_snapshot],
        build_map,
    )
    result = run(
        base["metrics"], args.start, args.end, args.train_days,
        args.validation_days, args.test_days, args.portfolio_size,
        args.min_samples, args.min_validation_trades, args.health_loss_streak,
        {multiplier: item["metrics"] for multiplier, item in stress.items()},
        map_snapshot=base,
        stress_snapshots=stress,
        tick_file=args.ticks,
    )
    result["map_source"] = {
        "metrics": base["metrics_count"],
        "tick_file": str(args.ticks),
        "snapshot": str(args.map_snapshot) if args.map_snapshot else "built-once",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for fold in result["folds"]:
        print(
            f"fold={fold['fold']} winner={fold['selection']['winner'] or 'NO_TRADE'} "
            f"validation_original={fold['validation'][POLICY_ORIGINAL]['mean_r']:+.4f} "
            f"validation_calibrated={fold['validation'][POLICY_CALIBRATED]['mean_r']:+.4f} "
            f"test_n={fold['test']['n']} test_R={fold['test']['total_r']:+.3f}"
        )
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "POLICY_CALIBRATED",
    "POLICY_ORIGINAL",
    "POLICIES",
    "SnapshotIntegrityError",
    "choose_policy",
    "deterministic_fingerprint",
    "fit_calibrated",
    "fit_policies",
    "main",
    "run",
    "score_policies",
    "validate_map_snapshot",
    "validation_stress_results",
]
