#!/usr/bin/env python3
"""Causal regime-transition states for Volatility 75 research."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from clean_slate_v75 import build_features, build_regimes, load_csv, parse_dt  # noqa: E402
from v75_opportunity_map import build_map  # noqa: E402
from v75_opportunity_selector import _path_r


def transition_states(rows: list[dict], h1_rows: list[dict]) -> list[str]:
    """Classify each M15 bar using closed-bar information only."""
    atr, features = build_features(rows)
    regimes = build_regimes(rows, h1_rows, atr)
    closes = np.asarray([row["c"] for row in rows], dtype=float)
    states: list[str] = []
    for index, (regime, feature) in enumerate(zip(regimes, features)):
        if feature is None or regime != "TRANSITION" or index < 8:
            states.append("STABLE_" + regime)
            continue
        short = closes[index] - closes[index - 4]
        prior = closes[index - 4] - closes[index - 8]
        expansion = abs(short) / max(atr[index], 1e-9)
        reversal = short * prior < 0
        if expansion >= 1.0 and not reversal:
            states.append("TRANSITION_EXPANSION_UP" if short > 0 else "TRANSITION_EXPANSION_DOWN")
        elif reversal and expansion >= 0.45:
            states.append("TRANSITION_FAILED_MOVE_UP" if short > 0 else "TRANSITION_FAILED_MOVE_DOWN")
        else:
            states.append("TRANSITION_COMPRESSION")
    return states


def analyze(data_dir: Path, ticks: Path, start: datetime, end: datetime) -> dict:
    rows = load_csv(data_dir / "m15.csv")
    h1_rows = load_csv(data_dir / "h1.csv")
    states = transition_states(rows, h1_rows)
    report = build_map(data_dir, ticks, start, end)
    state_by_time = {rows[i + 1]["t"].isoformat(): states[i] for i in range(len(rows) - 1)}
    groups: dict[tuple, list[float]] = defaultdict(list)
    for metric in report["metrics"]:
        state = state_by_time.get(metric["timestamp"], "UNKNOWN")
        geometry = "sl0.75_tp1.5"
        groups[(state, metric["direction"], metric["horizon"])].append(_path_r(metric, geometry))
    results = []
    for (state, direction, horizon), values in groups.items():
        results.append({
            "state": state,
            "direction": direction,
            "horizon": horizon,
            "n": len(values),
            "total_r": round(float(sum(values)), 6),
            "mean_r": round(float(np.mean(values)), 6),
            "win_rate": round(float(np.mean(np.asarray(values) > 0)), 6),
        })
    results.sort(key=lambda item: (item["mean_r"], item["n"]), reverse=True)
    return {
        "schema": "mitemshub.v75.transition-analysis.v1",
        "causal": True,
        "states": sorted(set(states)),
        "results": results,
        "state_counts": {state: states.count(state) for state in sorted(set(states))},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--ticks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    args = parser.parse_args()
    result = analyze(args.data_dir, args.ticks, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for row in result["results"][:20]:
        print(row)
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
