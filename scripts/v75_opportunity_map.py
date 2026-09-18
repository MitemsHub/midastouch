#!/usr/bin/env python3
"""Causal Volatility 75 opportunity map.

This research-only tool measures every eligible M15 decision rather than only
signals that pass a pre-existing strategy.  It records, for both long and
short directions and 2/3/4-hour horizons:

* executable entry and spread;
* maximum favorable and adverse excursion from the tick path;
* horizon return;
* whether a target was reachable without exceeding the stop excursion;
* continuation/reversal context and observable feature bins.

The map is a discovery instrument, not a trading rule.  It deliberately does
not select a winner from the same data it reports as evidence.  Its output is
used to identify feature/regime pockets for the later chronological selector.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_DATA = ROOT / "artifacts" / "v75_blind90_fresh"
DEFAULT_TICKS = ROOT / "artifacts" / "data" / "volatility_75_index_ticks_fresh90.csv"
DEFAULT_OUTPUT = DEFAULT_DATA / "v75_opportunity_map.json"

HORIZONS = (8, 12, 16)
MAX_QUOTE_GAP_MS = 120_000

sys.path.insert(0, str(HERE))
from clean_slate_v75 import build_features, build_regimes, load_csv, parse_dt  # noqa: E402
from v75_router_core import GEOMETRIES  # noqa: E402

load_bars = load_csv
from tick_clean_slate_v75 import load_ticks  # noqa: E402


def transition_state(rows: list[dict], atr: list[float], index: int, regime: str) -> str:
    if regime != "TRANSITION" or index < 8:
        return "STABLE_" + regime
    short = rows[index]["c"] - rows[index - 4]["c"]
    prior = rows[index - 4]["c"] - rows[index - 8]["c"]
    expansion = abs(short) / max(atr[index], 1e-9)
    reversal = short * prior < 0
    if expansion >= 1.0 and not reversal:
        return "TRANSITION_EXPANSION_UP" if short > 0 else "TRANSITION_EXPANSION_DOWN"
    if reversal and expansion >= 0.45:
        return "TRANSITION_FAILED_MOVE_UP" if short > 0 else "TRANSITION_FAILED_MOVE_DOWN"
    return "TRANSITION_COMPRESSION"


@dataclass(frozen=True)
class PathMetric:
    timestamp: str
    direction: int
    horizon: int
    regime: str
    context: str
    transition_state: str
    m8_bin: str
    m16_bin: str
    m32_bin: str
    efficiency_bin: str
    extension_bin: str
    distance_bin: str
    spread: float
    atr: float
    mfe_r: float
    mae_r: float
    horizon_r: float
    target_reachable: dict[str, bool]
    target_before_stop: dict[str, bool]


def _bin(value: float, cuts: tuple[float, ...]) -> str:
    labels = [f"<{cuts[0]:g}"] + [f"{left:g}..{right:g}" for left, right in zip(cuts, cuts[1:])] + [f">={cuts[-1]:g}"]
    index = sum(value >= cut for cut in cuts)
    return labels[index]


def _context(feature: dict[str, float], regime: str) -> str:
    long_cont = feature["m32"] > 0 and feature["m16"] > 0 and feature["slope"] > 0 and feature["efficiency"] >= 0.30
    short_cont = feature["m32"] < 0 and feature["m16"] < 0 and feature["slope"] < 0 and feature["efficiency"] >= 0.30
    reversal = abs(feature["distance"]) >= 0.45 and abs(feature["m32"]) >= 0.18 and feature["m8"] * feature["m32"] < 0 and feature["efficiency"] <= 0.60
    if reversal:
        return "REVERSAL"
    if (long_cont or short_cont) and regime in {"BULL", "BEAR"}:
        return "CONTINUATION"
    return "NEUTRAL"


def _first_tick(path, timestamp: datetime) -> int | None:
    value = int(timestamp.timestamp() * 1000)
    index = int(np.searchsorted(path.times, value, side="left"))
    return index if index < len(path.times) else None


def _metrics_for_path(path, start: datetime, horizon: int, direction: int,
                      atr_value: float, spread_mult: float) -> tuple[float, float, float, float, np.ndarray] | None:
    start_index = _first_tick(path, start)
    if start_index is None or atr_value <= 0:
        return None
    end = start + timedelta(minutes=15 * horizon)
    end_ms = int(end.timestamp() * 1000)
    if end_ms > int(path.times[-1]):
        return None
    end_index = int(np.searchsorted(path.times, end_ms, side="right"))
    if end_index <= start_index:
        return None
    times = path.times[start_index:end_index]
    if len(times) < 2 or int(np.max(np.diff(times))) > MAX_QUOTE_GAP_MS:
        return None
    bids = path.bids[start_index:end_index]
    asks = path.asks[start_index:end_index]
    mids = (bids + asks) / 2.0
    half_spread = (asks[0] - bids[0]) * spread_mult / 2.0
    entry = (asks[0] if direction > 0 else bids[0])
    executable = mids - (asks - bids) * spread_mult / 2.0 if direction > 0 else mids + (asks - bids) * spread_mult / 2.0
    returns = direction * (executable - entry) / atr_value
    return float(np.max(returns)), float(np.min(returns)), float(returns[-1]), float(entry), returns


def _target_flags(returns: np.ndarray, direction: int, stop_atr: float, target_atr: float,
                  spread_atr: float = 0.0) -> tuple[bool, bool]:
    """Return reachable and conservative first-event target-before-stop flags.

    The path is normalized by ATR.  A positive return reaching target is a
    target opportunity; a return reaching -stop is a stop opportunity.  If
    both happen in one tick, stop wins.  This preserves the research engine's
    conservative execution convention.
    """
    # ``returns`` are measured from the executable entry and exit quotes, so
    # the observed spread is already paid.  Do not charge it a second time in
    # the path labels.
    target = target_atr
    stop = -stop_atr
    target_hits = np.flatnonzero(returns >= target)
    stop_hits = np.flatnonzero(returns <= stop)
    reachable = bool(len(target_hits))
    before_stop = bool(reachable and (not len(stop_hits) or target_hits[0] < stop_hits[0]))
    return reachable, before_stop


def build_map(data_dir: Path, ticks_path: Path, start: datetime, end: datetime,
              spread_mult: float = 1.0) -> dict:
    rows = load_bars(data_dir / "m15.csv")
    h1_rows = load_bars(data_dir / "h1.csv")
    atr, features = build_features(rows)
    regimes = build_regimes(rows, h1_rows, atr)
    ticks = load_ticks([ticks_path])
    metrics: list[dict] = []
    skipped = defaultdict(int)
    for index in range(64, len(rows)):
        timestamp = rows[index]["t"]
        if timestamp < start:
            continue
        if timestamp >= end:
            break
        feature = features[index]
        if feature is None or atr[index] <= 0:
            skipped["insufficient-history"] += 1
            continue
        entry_time = rows[index + 1]["t"] if index + 1 < len(rows) else None
        if entry_time is None:
            continue
        context = _context(feature, regimes[index])
        for direction in (1, -1):
            for horizon in HORIZONS:
                result = _metrics_for_path(ticks, entry_time, horizon, direction, atr[index], spread_mult)
                if result is None:
                    skipped["tick-coverage-or-gap"] += 1
                    continue
                mfe, mae, horizon_r, entry, returns = result
                spread = float(ticks.median_spread * spread_mult)
                spread_atr = spread / atr[index]
                reachable: dict[str, bool] = {}
                before_stop: dict[str, bool] = {}
                for stop_atr, target_atr in GEOMETRIES:
                    label = f"sl{stop_atr:g}_tp{target_atr:g}"
                    rch, bts = _target_flags(returns, direction, stop_atr, target_atr)
                    reachable[label] = rch
                    before_stop[label] = bts
                metrics.append(asdict(PathMetric(
                    timestamp=entry_time.isoformat(), direction=direction, horizon=horizon,
                    regime=regimes[index], context=context,
                    transition_state=transition_state(rows, atr, index, regimes[index]),
                    m8_bin=_bin(feature["m8"], (-0.75, -0.15, 0.15, 0.75)),
                    m16_bin=_bin(feature["m16"], (-0.75, -0.15, 0.15, 0.75)),
                    m32_bin=_bin(feature["m32"], (-0.75, -0.15, 0.15, 0.75)),
                    efficiency_bin=_bin(feature["efficiency"], (0.20, 0.35, 0.50, 0.70)),
                    extension_bin=_bin(abs(feature["m32"]), (0.18, 0.30, 0.60, 1.00)),
                    distance_bin=_bin(abs(feature["distance"]), (0.25, 0.45, 0.75, 1.25)),
                    spread=spread, atr=float(atr[index]), mfe_r=mfe, mae_r=mae,
                    horizon_r=horizon_r, target_reachable=reachable,
                    target_before_stop=before_stop,
                )))
    return {
        "schema": "mitemshub.v75.opportunity-map.v1",
        "symbol": "Volatility 75 Index",
        "windows": {"start": start.isoformat(), "end": end.isoformat()},
        "tick_file": str(ticks_path),
        "tick_coverage": {"first": ticks.first.isoformat(), "last": ticks.last.isoformat(),
                          "ticks": len(ticks.times), "median_spread": ticks.median_spread,
                          "gap_count_over_120s": ticks.gap_count, "max_gap_ms": ticks.max_gap_ms},
        "parameters": {"horizons_bars": HORIZONS, "geometries": GEOMETRIES,
                       "spread_multiplier": spread_mult, "decision_frequency": "every M15 bar",
                       "same_tick_policy": "stop first", "feature_source": "closed M15/H1 bars"},
        "metrics_count": len(metrics), "skipped": dict(skipped), "metrics": metrics,
    }


def summarize(report: dict, min_samples: int = 20) -> dict:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in report["metrics"]:
        key = (row["context"], row["regime"], row["direction"], row["horizon"])
        groups[key].append(row)
    summaries: list[dict] = []
    for key, rows in groups.items():
        for geometry in report["parameters"]["geometries"]:
            label = f"sl{geometry[0]:g}_tp{geometry[1]:g}"
            n = len(rows)
            wins = sum(row["target_before_stop"][label] for row in rows)
            reachable = sum(row["target_reachable"][label] for row in rows)
            expected_path_r = np.asarray([
                (geometry[1] / geometry[0]) if row["target_before_stop"][label]
                else -1.0 if row["mae_r"] <= -geometry[0]
                else row["horizon_r"] / geometry[0]
                for row in rows
            ])
            summaries.append({
                "context": key[0], "regime": key[1], "direction": key[2], "horizon": key[3],
                "geometry": label, "n": n,
                "target_before_stop_rate": round(wins / n, 5) if n else 0.0,
                "target_reachable_rate": round(reachable / n, 5) if n else 0.0,
                "mean_mfe_r": round(float(np.mean([row["mfe_r"] for row in rows])), 5),
                "mean_mae_r": round(float(np.mean([row["mae_r"] for row in rows])), 5),
                "mean_horizon_r": round(float(np.mean([row["horizon_r"] for row in rows])), 5),
                "path_expectancy_r": round(float(np.mean(expected_path_r)), 5),
                "enough_data": n >= min_samples,
            })
    summaries.sort(key=lambda row: (row["enough_data"], row["path_expectancy_r"], row["n"]), reverse=True)
    return {"min_samples": min_samples, "groups": summaries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--ticks", type=Path, default=DEFAULT_TICKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--spread-mult", type=float, default=1.0)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()
    report = build_map(args.data_dir, args.ticks, args.start, args.end, args.spread_mult)
    report["summary"] = summarize(report, args.min_samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    summary_path = args.summary_output or args.output.with_name(args.output.stem + "_summary.json")
    summary_path.write_text(json.dumps(report["summary"], indent=1), encoding="utf-8")
    print(f"metrics={report['metrics_count']} skipped={report['skipped']}")
    for row in report["summary"]["groups"][:20]:
        print(f"{row['context']:12s} {row['regime']:10s} dir={row['direction']:+d} h={row['horizon']:2d} "
              f"{row['geometry']:12s} n={row['n']:4d} p={row['target_before_stop_rate']:.3f} "
              f"E={row['path_expectancy_r']:+.3f}R")
    print("wrote", args.output)
    print("wrote", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
