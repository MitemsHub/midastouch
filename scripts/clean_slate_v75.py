#!/usr/bin/env python3
"""Clean-slate Volatility 75 path-based strategy research engine.

This module is independent of the legacy EA.  It labels a decision by the
trade path that follows it: target-before-stop, stop-before-target, or a
quote-aware horizon exit.  It fits separate continuation and reversal
hypotheses by observable regime and direction, then trades only when the
out-of-sample model clears its cost, confidence, sample, and health gates.

No account balance, lot size, or future information is used by the signal
model.  A failed gate is an explicit NO_TRADE decision.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_DATA = ROOT / "artifacts" / "v75_blind90"
DEFAULT_OUTPUT = DEFAULT_DATA / "clean_slate_v75.json"
SPREADS = (18.5, 27.75, 37.0)
FEATURE_NAMES = ("m8", "m16", "m32", "slope", "distance", "efficiency")


@dataclass(frozen=True)
class StrategyConfig:
    """Small fixed strategy family; values are selected only on validation."""

    name: str
    horizon: int
    stop_atr: float
    target_atr: float
    min_efficiency: float
    min_extension: float
    reversal_distance: float
    min_samples: int = 12
    min_confidence_margin: float = 0.04
    cost_buffer: float = 1.25
    drift_limit: float = 2.75


@dataclass(frozen=True)
class Signal:
    hypothesis: str
    direction: int
    strength: float
    regime: str


@dataclass(frozen=True)
class PathOutcome:
    r: float
    favorable_r: float
    reason: str
    bars: int


@dataclass(frozen=True)
class ModelStats:
    n: int
    wins: int
    sum_r: float
    sum_favorable_r: float


@dataclass
class HealthState:
    recent_r: deque[float]
    invalidated: bool = False
    reason: str = ""


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {
                "t": parse_dt(row["time"] if "time" in row else datetime.fromtimestamp(
                    float(row["ts"]), timezone.utc
                ).isoformat()),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
            }
            for row in csv.DictReader(handle)
        ]


def ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def atr14(rows: list[dict]) -> list[float]:
    true_ranges: list[float] = []
    for index, row in enumerate(rows):
        if index == 0:
            true_ranges.append(row["h"] - row["l"])
            continue
        previous = rows[index - 1]["c"]
        true_ranges.append(max(row["h"] - row["l"], abs(row["h"] - previous), abs(row["l"] - previous)))
    result = [true_ranges[0]]
    for value in true_ranges[1:]:
        result.append((result[-1] * 13.0 + value) / 14.0)
    return result


def build_regimes(rows: list[dict], h1_rows: list[dict], atr: list[float]) -> list[str]:
    """Precompute the last-closed-H1 regime for every M15 decision bar."""
    h1_times = [row["t"] for row in h1_rows]
    h1_closes = [row["c"] for row in h1_rows]
    fast = ema(h1_closes, 20)
    mid = ema(h1_closes, 50)
    slow = ema(h1_closes, 100)
    regimes: list[str] = []
    h1_index = 0
    for row, current_atr in zip(rows, atr):
        while h1_index + 1 < len(h1_rows) and h1_times[h1_index + 1] <= row["t"]:
            h1_index += 1
        causal_index = h1_index
        if h1_times[causal_index] == row["t"] and causal_index > 0:
            causal_index -= 1
        if causal_index < 99 or current_atr <= 0:
            regimes.append("UNKNOWN")
            continue
        separation = abs(fast[causal_index] - mid[causal_index]) / current_atr
        price = h1_closes[causal_index]
        if separation < 0.20:
            regimes.append("RANGE")
        elif fast[causal_index] > mid[causal_index] > slow[causal_index] and price > fast[causal_index]:
            regimes.append("BULL")
        elif fast[causal_index] < mid[causal_index] < slow[causal_index] and price < fast[causal_index]:
            regimes.append("BEAR")
        else:
            regimes.append("TRANSITION")
    return regimes


def feature_at(rows: list[dict], atr: list[float], ema8: list[float], ema32: list[float], index: int) -> dict[str, float] | None:
    if index < 64 or atr[index] <= 0:
        return None
    close = rows[index]["c"]
    deltas = {period: close - rows[index - period]["c"] for period in (8, 16, 32)}
    m8, m16, m32 = (deltas[period] / atr[index] for period in (8, 16, 32))
    path = sum(abs(rows[k]["c"] - rows[k - 1]["c"]) for k in range(index - 31, index + 1))
    efficiency = abs(deltas[32]) / path if path > 0 else 0.0
    return {
        "m8": float(np.clip(m8 / 3.0, -3.0, 3.0)),
        "m16": float(np.clip(m16 / 3.0, -3.0, 3.0)),
        "m32": float(np.clip(m32 / 3.0, -3.0, 3.0)),
        "slope": float(np.clip((ema8[index] - ema32[index]) / atr[index] / 2.0, -3.0, 3.0)),
        "distance": float(np.clip((close - ema32[index]) / atr[index] / 3.0, -3.0, 3.0)),
        "efficiency": efficiency,
    }


def build_features(rows: list[dict]) -> tuple[list[float], list[dict[str, float] | None]]:
    closes = [row["c"] for row in rows]
    atr = atr14(rows)
    ema8 = ema(closes, 8)
    ema32 = ema(closes, 32)
    return atr, [feature_at(rows, atr, ema8, ema32, index) for index in range(len(rows))]


def hypotheses(feature: dict[str, float], regime: str, config: StrategyConfig) -> list[Signal]:
    sign = 1 if feature["m32"] > 0 else -1 if feature["m32"] < 0 else 0
    if sign == 0 or regime == "UNKNOWN":
        return []
    result: list[Signal] = []
    continuation = (
        abs(feature["m32"]) >= config.min_extension
        and sign * feature["m16"] > 0
        and sign * feature["slope"] > 0
        and feature["efficiency"] >= config.min_efficiency
        and regime in {"BULL", "BEAR"}
    )
    if continuation:
        strength = abs(feature["m32"]) + abs(feature["m16"]) + feature["efficiency"]
        result.append(Signal("CONTINUATION", sign, strength, regime))
    reversal = (
        abs(feature["m32"]) >= config.min_extension
        and abs(feature["distance"]) >= config.reversal_distance
        and sign * feature["m8"] < 0
        and feature["efficiency"] <= 0.60
        and regime in {"RANGE", "TRANSITION", "BULL", "BEAR"}
    )
    if reversal:
        strength = abs(feature["distance"]) + abs(feature["m8"]) + (1.0 - feature["efficiency"])
        result.append(Signal("REVERSAL", -sign, strength, regime))
    return result


def path_outcome(rows: list[dict], direction: int, entry: float, stop_distance: float,
                 target_distance: float, horizon: int, spread: float) -> PathOutcome:
    half = spread / 2.0
    stop = entry - direction * stop_distance
    target = entry + direction * target_distance
    entry_mid = entry - direction * half
    max_favorable = 0.0
    future = rows[:horizon]
    for offset, row in enumerate(future, start=1):
        favorable_mid = row["h"] if direction > 0 else row["l"]
        max_favorable = max(max_favorable, direction * (favorable_mid - entry_mid) / stop_distance)
        hit_stop = row["l"] - half <= stop if direction > 0 else row["h"] + half >= stop
        hit_target = row["h"] - half >= target if direction > 0 else row["l"] + half <= target
        if hit_stop and hit_target:
            return PathOutcome(-1.0, max_favorable, "STOP_AMBIG", offset)
        if hit_stop:
            return PathOutcome(-1.0, max_favorable, "STOP", offset)
        if hit_target:
            return PathOutcome(target_distance / stop_distance, max_favorable, "TARGET", offset)
    exit_fill = future[-1]["c"] - direction * half
    return PathOutcome(direction * (exit_fill - entry) / stop_distance, max_favorable, "HORIZON", len(future))


def model_key(signal: Signal) -> tuple[str, str, int]:
    return signal.regime, signal.hypothesis, signal.direction


def fit_stats(rows: list[dict], regimes: list[str], features: list[dict | None], atr: list[float],
              config: StrategyConfig, start: datetime, end: datetime, spread: float) -> dict[tuple[str, str, int], ModelStats]:
    raw: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    index = 480
    while index + config.horizon < len(rows):
        timestamp = rows[index]["t"]
        if timestamp < start:
            index += 1
            continue
        if timestamp >= end:
            break
        feature = features[index]
        if feature is None:
            index += 1
            continue
        regime = regimes[index]
        signals = hypotheses(feature, regime, config)
        if not signals:
            index += 1
            continue
        for signal in signals:
            entry = rows[index + 1]["o"] + signal.direction * spread / 2.0
            outcome = path_outcome(rows[index + 1:index + 1 + config.horizon], signal.direction, entry,
                                   config.stop_atr * atr[index], config.target_atr * atr[index],
                                   config.horizon, spread)
            raw[model_key(signal)].extend((outcome.r, outcome.favorable_r))
        # Fit on independent, completion-spaced opportunities.
        exit_bars = min(
            path_outcome(rows[index + 1:index + 1 + config.horizon], signal.direction,
                         rows[index + 1]["o"] + signal.direction * spread / 2.0,
                         config.stop_atr * atr[index], config.target_atr * atr[index],
                         config.horizon, spread).bars
            for signal in signals
        )
        index += max(1, exit_bars + 20)
    result: dict[tuple[str, str, int], ModelStats] = {}
    for key, values in raw.items():
        returns = values[0::2]
        favorable = values[1::2]
        result[key] = ModelStats(len(returns), sum(value > 0 for value in returns),
                                 sum(returns), sum(favorable))
    return result


def decision(stats: dict[tuple[str, str, int], ModelStats], signal: Signal, feature: dict[str, float],
             config: StrategyConfig, atr: float, spread: float, health: HealthState) -> tuple[bool, str]:
    if health.invalidated:
        return False, f"model-invalid:{health.reason}"
    item = stats.get(model_key(signal))
    if item is None or item.n < config.min_samples:
        return False, "insufficient-regime-hypothesis-sample"
    probability = (item.wins + 1.0) / (item.n + 2.0)
    payoff = config.target_atr / config.stop_atr
    break_even = 1.0 / (1.0 + payoff)
    expected_r = item.sum_r / item.n
    mean_favorable = item.sum_favorable_r / item.n
    cost_floor = config.cost_buffer * spread / max(config.stop_atr * atr, 1e-9)
    if expected_r <= 0:
        return False, "negative-expected-r"
    if probability < break_even + config.min_confidence_margin:
        return False, "confidence-below-break-even-margin"
    if mean_favorable < max(0.20, cost_floor):
        return False, "favorable-move-below-cost"
    return True, "accepted"


def evaluate(rows: list[dict], regimes: list[str], features: list[dict | None], atr: list[float],
             stats: dict[tuple[str, str, int], ModelStats], config: StrategyConfig,
             start: datetime, end: datetime, spread: float) -> dict:
    values: list[float] = []
    reasons: dict[str, int] = defaultdict(int)
    hypotheses_used: dict[str, int] = defaultdict(int)
    health = HealthState(deque(maxlen=6))
    index = 480
    while index + config.horizon < len(rows):
        timestamp = rows[index]["t"]
        if timestamp < start:
            index += 1
            continue
        if timestamp >= end:
            break
        feature = features[index]
        if feature is None:
            index += 1
            continue
        regime = regimes[index]
        signals = hypotheses(feature, regime, config)
        if not signals:
            reasons["no-hypothesis"] += 1
            index += 1
            continue
        accepted: list[Signal] = []
        for signal in signals:
            ok, reason = decision(stats, signal, feature, config, atr[index], spread, health)
            if ok:
                accepted.append(signal)
            else:
                reasons[reason] += 1
        if len(accepted) != 1:
            reasons["no-trade-ambiguous-or-rejected"] += 1
            index += 1
            continue
        signal = accepted[0]
        entry = rows[index + 1]["o"] + signal.direction * spread / 2.0
        outcome = path_outcome(rows[index + 1:index + 1 + config.horizon], signal.direction, entry,
                               config.stop_atr * atr[index], config.target_atr * atr[index],
                               config.horizon, spread)
        values.append(outcome.r)
        hypotheses_used[signal.hypothesis] += 1
        health.recent_r.append(outcome.r)
        if len(health.recent_r) == health.recent_r.maxlen and sum(health.recent_r) <= -2.0:
            health.invalidated = True
            health.reason = "six-trade-loss-window"
        index += max(1, outcome.bars + 20)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    days = max((end - start).total_seconds() / 86400.0, 1.0)
    return {
        "n": len(values),
        "wins": sum(value > 0 for value in values),
        "hit_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else 0.0,
        "total_r": round(sum(values), 6),
        "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
        "max_drawdown_r": round(max_dd, 6),
        "trades_per_day": round(len(values) / days, 3),
        "hypotheses": dict(hypotheses_used),
        "rejections": dict(reasons),
        "model_invalidated": health.invalidated,
        "invalidation_reason": health.reason,
    }


def configs() -> list[StrategyConfig]:
    result: list[StrategyConfig] = []
    for horizon in (12, 16):
        for stop_atr, target_atr in ((0.75, 2.0), (0.75, 2.5), (1.0, 2.5)):
            for efficiency in (0.30, 0.45):
                for extension in (0.18, 0.30):
                    result.append(StrategyConfig(
                        name=f"h{horizon}_sl{stop_atr}_tp{target_atr}_e{efficiency}_x{extension}",
                        horizon=horizon, stop_atr=stop_atr, target_atr=target_atr,
                        min_efficiency=efficiency, min_extension=extension,
                        reversal_distance=0.45,
                    ))
    return result


def run(data_dir: Path, start: datetime, end: datetime, train_days: int, test_days: int) -> dict:
    rows = load_csv(data_dir / "m15.csv")
    h1_rows = load_csv(data_dir / "h1.csv")
    atr, features = build_features(rows)
    regimes = build_regimes(rows, h1_rows, atr)
    folds: list[dict] = []
    cursor = start
    for fold in range(1, 7):
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        validation_start = train_end - timedelta(days=test_days)
        scored: list[tuple[StrategyConfig, dict]] = []
        for config in configs():
            stats = fit_stats(rows, regimes, features, atr, config, cursor, validation_start, SPREADS[0])
            validation = evaluate(rows, regimes, features, atr, stats, config, validation_start, train_end, SPREADS[0])
            stress = evaluate(rows, regimes, features, atr, stats, config, validation_start, train_end, SPREADS[0] * 1.5)
            if validation["n"] >= 4 and validation["mean_r"] > 0 and stress["mean_r"] > 0:
                scored.append((config, validation))
        if scored:
            selected, validation = max(scored, key=lambda item: (item[1]["mean_r"], item[1]["n"]))
            stats = fit_stats(rows, regimes, features, atr, selected, cursor, train_end, SPREADS[0])
            test = evaluate(rows, regimes, features, atr, stats, selected, train_end, test_end, SPREADS[0])
            stress = {str(spread): evaluate(rows, regimes, features, atr, stats, selected, train_end, test_end, spread)
                      for spread in SPREADS}
            selection = {"config": asdict(selected), "validation": validation}
        else:
            selected = None
            test = {"n": 0, "total_r": 0.0, "mean_r": 0.0, "max_drawdown_r": 0.0}
            stress = {}
            selection = {"config": None, "reason": "no positive validation configuration"}
        folds.append({"fold": fold, "train_window": [cursor.isoformat(), train_end.isoformat()],
                      "test_window": [train_end.isoformat(), test_end.isoformat()],
                      "selection": selection, "test_base_spread": test, "test_spread_stress": stress})
        cursor += timedelta(days=test_days)
        if cursor + timedelta(days=train_days) > end:
            break
    return {"schema": "mitemshub.v75.clean-slate-path.v1", "data_dir": str(data_dir),
            "design": {"labels": "target-before-stop, stop-before-target, or quote-aware horizon exit",
                       "hypotheses": ["CONTINUATION", "REVERSAL"],
                       "gates": ["regime-specific sample", "break-even confidence margin", "expected R", "favorable excursion vs spread", "six-trade health invalidation"],
                       "selection": "chronological validation, then refit on outer training window",
                       "spreads": SPREADS, "config_count": len(configs())}, "folds": folds}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CERT_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=10)
    args = parser.parse_args()
    result = run(args.data_dir, args.start, args.end, args.train_days, args.test_days)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for fold in result["folds"]:
        config = fold["selection"]["config"]
        test = fold["test_base_spread"]
        print(f"fold={fold['fold']} selected={config['name'] if config else 'NO_TRADE'} n={test['n']} R={test['total_r']:+.3f} DD={test['max_drawdown_r']:.2f}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
