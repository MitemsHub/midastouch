#!/usr/bin/env python3
"""Calibrated continuation/reversal path-probability research for Volatility 75.

This research-only engine is intentionally separate from the production EA and
from the earlier parameter grid.  It uses the existing causal M15/H1 feature
hypotheses, but fits a probability of *target before stop* for each
(regime, hypothesis, direction) bucket from executable bid/ask paths.

The decision contract is:
1. both hypotheses are evaluated independently;
2. Wilson lower confidence bounds must clear break-even;
3. expected executable R must be positive after the observed spread;
4. favorable excursion must clear a spread buffer;
5. the strongest hypothesis must beat the runner-up by a margin;
6. otherwise return NO_TRADE.

Chronological validation, spread stress, sequential trade lifecycle, and
fail-closed tick-gap handling are retained.  No live EA setting is changed.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from tick_clean_slate_v75 import (
    DEFAULT_DATA,
    DEFAULT_TICKS,
    SPREAD_STRESS,
    TickOutcome,
    TickPath,
    _first_tick,
    build_features,
    build_regimes,
    configs,
    hypotheses,
    load_bars,
    load_ticks,
    model_key,
    parse_dt,
    tick_outcome,
)


@dataclass(frozen=True)
class ProbabilityStats:
    n: int
    wins: int  # target-before-stop outcomes only; horizon exits are not wins
    sum_r: float
    sum_favorable_r: float
    mean_loss_r: float
    mean_win_r: float


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    probability: float
    lower_bound: float
    expected_r: float
    favorable_r: float
    key: tuple[str, str, int] | None


MIN_SAMPLES = 12
CONFIDENCE_Z = 1.645  # one-sided 95% Wilson lower bound
EDGE_MARGIN = 0.05
COST_BUFFER = 1.25


def wilson_lower(wins: int, n: int, z: float = CONFIDENCE_Z) -> float:
    """Return a conservative one-sided Wilson lower confidence bound."""
    if n <= 0:
        return 0.0
    p = wins / n
    denominator = 1.0 + z * z / n
    center = p + z * z / (2.0 * n)
    spread = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (center - spread) / denominator)


def _outcomes(rows: list[dict], features: list[dict | None], regimes: list[str],
              atr: list[float], config, start: datetime, end: datetime,
              path: TickPath, spread_mult: float) -> list[tuple[tuple[str, str, int], TickOutcome]]:
    """Collect non-overlapping executable outcomes for model fitting."""
    result: list[tuple[tuple[str, str, int], TickOutcome]] = []
    index = 64
    while index < len(rows) - config.horizon - 1:
        timestamp = rows[index]["t"]
        if timestamp < start:
            index += 1
            continue
        if timestamp >= end:
            break
        feature = features[index]
        if feature is None or atr[index] <= 0:
            index += 1
            continue
        signals = hypotheses(feature, regimes[index], config)
        if not signals:
            index += 1
            continue
        candidates: list[tuple[tuple[str, str, int], TickOutcome]] = []
        entry_time = rows[index + 1]["t"]
        for signal in signals:
            outcome = tick_outcome(
                path, signal.direction, entry_time, config.horizon,
                config.stop_atr * atr[index], config.target_atr * atr[index], spread_mult,
            )
            if outcome is not None:
                candidates.append((model_key(signal), outcome))
        result.extend(candidates)
        index += max((outcome.bars for _, outcome in candidates), default=1) + 1
    return result


def fit_probability(rows: list[dict], features: list[dict | None], regimes: list[str],
                    atr: list[float], config, start: datetime, end: datetime,
                    path: TickPath, spread_mult: float) -> dict[tuple[str, str, int], ProbabilityStats]:
    buckets: dict[tuple[str, str, int], list[TickOutcome]] = defaultdict(list)
    for key, outcome in _outcomes(rows, features, regimes, atr, config, start, end, path, spread_mult):
        buckets[key].append(outcome)
    result: dict[tuple[str, str, int], ProbabilityStats] = {}
    for key, values in buckets.items():
        wins = [item.r for item in values if item.r > 0]
        losses = [item.r for item in values if item.r <= 0]
        result[key] = ProbabilityStats(
            n=len(values),
            wins=sum(item.reason == "TARGET" for item in values),
            sum_r=sum(item.r for item in values),
            sum_favorable_r=sum(item.favorable_r for item in values),
            mean_loss_r=float(np.mean(losses)) if losses else 0.0,
            mean_win_r=float(np.mean(wins)) if wins else 0.0,
        )
    return result


def _decision_for(stats: dict[tuple[str, str, int], ProbabilityStats], signal,
                  config, atr_value: float, observed_spread: float) -> Decision:
    key = model_key(signal)
    item = stats.get(key)
    if item is None or item.n < MIN_SAMPLES:
        return Decision(False, "insufficient-sample", 0.0, 0.0, 0.0, 0.0, key)
    probability = (item.wins + 1.0) / (item.n + 2.0)
    lower = wilson_lower(item.wins, item.n)
    expected_r = item.sum_r / item.n
    favorable = item.sum_favorable_r / item.n
    break_even = config.stop_atr / (config.stop_atr + config.target_atr)
    cost_floor = COST_BUFFER * observed_spread / max(config.stop_atr * atr_value, 1e-9)
    if lower <= break_even:
        return Decision(False, "probability-lower-bound-below-break-even", probability, lower,
                        expected_r, favorable, key)
    if expected_r <= 0:
        return Decision(False, "negative-executable-expectancy", probability, lower,
                        expected_r, favorable, key)
    if favorable < max(0.20, cost_floor):
        return Decision(False, "favorable-excursion-below-cost", probability, lower,
                        expected_r, favorable, key)
    return Decision(True, "accepted", probability, lower, expected_r, favorable, key)


def choose_signal(stats: dict[tuple[str, str, int], ProbabilityStats], signals, config,
                  atr_value: float, observed_spread: float) -> tuple[Decision, Decision | None]:
    decisions = [_decision_for(stats, signal, config, atr_value, observed_spread) for signal in signals]
    accepted = [decision for decision in decisions if decision.accepted]
    if not accepted:
        best = max(decisions, key=lambda item: item.lower_bound, default=Decision(
            False, "no-hypothesis", 0.0, 0.0, 0.0, 0.0, None))
        return Decision(False, "no-trade", best.probability, best.lower_bound,
                        best.expected_r, best.favorable_r, best.key), None
    accepted.sort(key=lambda item: (item.lower_bound, item.expected_r), reverse=True)
    best = accepted[0]
    runner = accepted[1] if len(accepted) > 1 else None
    if runner is not None and best.lower_bound - runner.lower_bound < EDGE_MARGIN:
        return Decision(False, "continuation-reversal-too-close", best.probability,
                        best.lower_bound, best.expected_r, best.favorable_r, best.key), runner
    return best, runner


def evaluate(rows: list[dict], features: list[dict | None], regimes: list[str], atr: list[float],
             stats: dict[tuple[str, str, int], ProbabilityStats], config, start: datetime,
             end: datetime, path: TickPath, spread_mult: float) -> dict:
    values: list[float] = []
    reasons: dict[str, int] = defaultdict(int)
    used: dict[str, int] = defaultdict(int)
    probabilities: list[float] = []
    index = 64
    while index < len(rows) - config.horizon - 1:
        timestamp = rows[index]["t"]
        if timestamp < start:
            index += 1
            continue
        if timestamp >= end:
            break
        feature = features[index]
        if feature is None or atr[index] <= 0:
            index += 1
            continue
        signals = hypotheses(feature, regimes[index], config)
        if not signals:
            reasons["no-hypothesis"] += 1
            index += 1
            continue
        best, _ = choose_signal(stats, signals, config, atr[index], path.median_spread * spread_mult)
        if not best.accepted or best.key is None:
            reasons[best.reason] += 1
            index += 1
            continue
        direction = best.key[2]
        outcome = tick_outcome(path, direction, rows[index + 1]["t"], config.horizon,
                               config.stop_atr * atr[index], config.target_atr * atr[index], spread_mult)
        if outcome is None:
            reasons["tick-coverage-gap"] += 1
            index += 1
            continue
        values.append(outcome.r)
        probabilities.append(best.lower_bound)
        used[best.key[1]] += 1
        index += outcome.bars + 1
    equity = np.cumsum(values) if values else np.asarray([], dtype=float)
    drawdown = float(np.max(np.maximum.accumulate(equity) - equity)) if len(equity) else 0.0
    days = max((end - start).total_seconds() / 86400.0, 1.0)
    return {
        "n": len(values), "wins": int(sum(value > 0 for value in values)),
        "total_r": round(float(sum(values)), 6),
        "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
        "max_drawdown_r": round(drawdown, 6),
        "trades_per_day": round(len(values) / days, 3),
        "mean_probability_lower_bound": round(float(np.mean(probabilities)), 6) if probabilities else 0.0,
        "hypotheses": dict(used), "rejections": dict(reasons),
    }


def run(data_dir: Path, tick_paths: list[Path], start: datetime, end: datetime,
        train_days: int, test_days: int, m15_path: Path | None = None,
        h1_path: Path | None = None) -> dict:
    rows = load_bars(m15_path or data_dir / "m15.csv")
    h1_rows = load_bars(h1_path or data_dir / "h1.csv")
    atr, features = build_features(rows)
    regimes = build_regimes(rows, h1_rows, atr)
    path = load_ticks(tick_paths)
    folds: list[dict] = []
    cursor = start
    for fold in range(1, 7):
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        validation_start = train_end - timedelta(days=test_days)
        candidates: list[tuple[object, dict]] = []
        for config in configs():
            stats = fit_probability(rows, features, regimes, atr, config, cursor, validation_start, path, 1.0)
            validation = evaluate(rows, features, regimes, atr, stats, config,
                                  validation_start, train_end, path, 1.0)
            stress_stats = fit_probability(rows, features, regimes, atr, config,
                                           cursor, validation_start, path, 1.5)
            stress = evaluate(rows, features, regimes, atr, stress_stats, config,
                              validation_start, train_end, path, 1.5)
            if validation["n"] >= 8 and stress["n"] >= 8 and validation["mean_r"] > 0 and stress["mean_r"] > 0:
                candidates.append((config, validation))
        if candidates:
            selected, validation = max(candidates, key=lambda item: (item[1]["mean_r"], item[1]["n"]))
            stats = fit_probability(rows, features, regimes, atr, selected, cursor, train_end, path, 1.0)
            test = evaluate(rows, features, regimes, atr, stats, selected, train_end, test_end, path, 1.0)
            stress = {}
            for multiplier in SPREAD_STRESS:
                stress_stats = fit_probability(rows, features, regimes, atr, selected,
                                               cursor, train_end, path, multiplier)
                stress[str(multiplier)] = evaluate(rows, features, regimes, atr, stress_stats,
                                                   selected, train_end, test_end, path, multiplier)
            selection = {"config": asdict(selected), "validation": validation}
        else:
            test = {"n": 0, "total_r": 0.0, "mean_r": 0.0, "max_drawdown_r": 0.0}
            stress = {}
            selection = {"config": None, "reason": "no-positive-probability-validation-configuration"}
        folds.append({"fold": fold, "train_window": [cursor.isoformat(), train_end.isoformat()],
                      "test_window": [train_end.isoformat(), test_end.isoformat()],
                      "selection": selection, "test_base_spread": test,
                      "test_spread_stress": stress})
        cursor += timedelta(days=test_days)
        if cursor + timedelta(days=train_days) > end:
            break
    return {
        "schema": "mitemshub.v75.tick-path-probability.v1",
        "data_dir": str(data_dir), "tick_files": [str(path) for path in tick_paths],
        "tick_coverage": {"first": path.first.isoformat(), "last": path.last.isoformat(),
                          "ticks": len(path.times), "median_spread": path.median_spread,
                          "gap_count_over_120s": path.gap_count, "max_gap_ms": path.max_gap_ms},
        "design": {                   "calibration": "Wilson one-sided 95% lower bound on target-before-stop probability; horizon exits count only in expectancy",
                   "hypotheses": ["CONTINUATION", "REVERSAL"],
                   "decision": "probability lower bound + executable expectancy + cost + winner margin",
                   "lifecycle": "sequential; reassess only after path completion",
                   "no_trade": "explicit for insufficient, ambiguous, costly, or unvalidated evidence",
                   "spread_stress": SPREAD_STRESS, "config_count": len(configs())},
        "folds": folds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--m15", type=Path, default=None)
    parser.add_argument("--h1", type=Path, default=None)
    parser.add_argument("--ticks", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=10)
    args = parser.parse_args()
    result = run(args.data_dir, args.ticks, args.start, args.end, args.train_days,
                 args.test_days, args.m15, args.h1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for fold in result["folds"]:
        config = fold["selection"]["config"]
        test = fold["test_base_spread"]
        print(f"fold={fold['fold']} selected={config['name'] if config else 'NO_TRADE'} "
              f"n={test['n']} R={test['total_r']:+.3f} DD={test['max_drawdown_r']:.2f}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
