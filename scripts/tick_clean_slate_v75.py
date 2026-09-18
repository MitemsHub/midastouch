#!/usr/bin/env python3
"""Tick-level clean-slate Volatility 75 research engine.

This is a research-only companion to ``clean_slate_v75.py``.  It keeps the
M15/H1 signal features but replaces OHLC outcome labels with the executable
broker bid/ask path.  A trade is entered on the first quote of the next M15
bar, pays the observed spread, and is scored target-before-stop with a
conservative same-tick stop decision.

The engine is deliberately fail-closed:
* ticks must cover the complete trade path;
* gaps larger than the configured maximum invalidate a trade;
* settings are selected on a chronological validation slice only;
* the outer test slice is untouched until after selection and refitting.

It does not modify the EA or any production preset.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_DATA = ROOT / "artifacts" / "v75_replay"
DEFAULT_TICKS = ROOT / "artifacts" / "data"
DEFAULT_OUTPUT = DEFAULT_DATA / "tick_clean_slate_v75.json"
SPREAD_STRESS = (1.0, 1.5, 2.0)
MAX_QUOTE_GAP_MS = 120_000

sys.path.insert(0, str(HERE))
from clean_slate_v75 import (  # noqa: E402
    StrategyConfig,
    atr14,
    build_features,
    build_regimes,
    configs,
    hypotheses,
    model_key,
    parse_dt,
)


@dataclass(frozen=True)
class TickPath:
    times: np.ndarray
    bids: np.ndarray
    asks: np.ndarray
    median_spread: float
    first: datetime
    last: datetime
    gap_count: int
    max_gap_ms: int


@dataclass(frozen=True)
class TickOutcome:
    r: float
    favorable_r: float
    reason: str
    bars: int


@dataclass(frozen=True)
class TickStats:
    n: int
    wins: int
    sum_r: float
    sum_favorable_r: float


def load_bars(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {"t": parse_dt(row["time"]), "o": float(row["open"]),
             "h": float(row["high"]), "l": float(row["low"]),
             "c": float(row["close"])}
            for row in csv.DictReader(handle)
        ]


def load_ticks(paths: list[Path]) -> TickPath:
    rows: list[tuple[int, float, float]] = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            time_key = "epoch_ms" if "epoch_ms" in fields else "ts"
            multiplier = 1 if time_key == "epoch_ms" else 1000
            for row in reader:
                timestamp = int(float(row[time_key]) * multiplier)
                bid, ask = float(row["bid"]), float(row["ask"])
                if timestamp > 0 and 0 < bid < ask:
                    rows.append((timestamp, bid, ask))
    if not rows:
        raise ValueError("no usable bid/ask ticks found")
    rows.sort()
    deduped: list[tuple[int, float, float]] = []
    for row in rows:
        if not deduped or row != deduped[-1]:
            deduped.append(row)
    times = np.asarray([row[0] for row in deduped], dtype=np.int64)
    bids = np.asarray([row[1] for row in deduped], dtype=np.float64)
    asks = np.asarray([row[2] for row in deduped], dtype=np.float64)
    gaps = np.diff(times)
    return TickPath(
        times=times,
        bids=bids,
        asks=asks,
        median_spread=float(np.median(asks - bids)),
        first=datetime.fromtimestamp(times[0] / 1000, timezone.utc),
        last=datetime.fromtimestamp(times[-1] / 1000, timezone.utc),
        gap_count=int(np.sum(gaps > MAX_QUOTE_GAP_MS)),
        max_gap_ms=int(gaps.max()) if len(gaps) else 0,
    )


def _first_tick(path: TickPath, timestamp: datetime) -> int | None:
    value = int(timestamp.timestamp() * 1000)
    index = int(np.searchsorted(path.times, value, side="left"))
    return index if index < len(path.times) else None


def covers_window(path: TickPath, start: datetime, end: datetime) -> bool:
    """Return whether the complete window has continuous quote coverage."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    if start_ms < int(path.times[0]) or end_ms > int(path.times[-1]):
        return False
    lo = int(np.searchsorted(path.times, start_ms, side="left"))
    hi = int(np.searchsorted(path.times, end_ms, side="right"))
    if hi - lo < 2:
        return False
    return int(np.max(np.diff(path.times[lo:hi]))) <= MAX_QUOTE_GAP_MS


def tick_outcome(path: TickPath, direction: int, start: datetime, horizon_bars: int,
                 stop_distance: float, target_distance: float, spread_mult: float) -> TickOutcome | None:
    """Replay one trade using executable bid/ask prices.

    ``start`` is the open of the next M15 bar.  The quote immediately before
    entry is not used: entry is ask for a buy and bid for a sell.  A missing
    quote or a large data gap fails closed instead of silently carrying a
    position through unknown market behavior.
    """
    start_index = _first_tick(path, start)
    if start_index is None:
        return None
    end_ms = int((start + timedelta(minutes=15 * horizon_bars)).timestamp() * 1000)
    if int(path.times[-1]) < end_ms:
        return None
    end_index = int(np.searchsorted(path.times, end_ms, side="right"))
    if end_index <= start_index:
        return None
    local_times = path.times[start_index:end_index]
    if len(local_times) < 2 or int(np.max(np.diff(local_times))) > MAX_QUOTE_GAP_MS:
        return None
    base_spread = float(path.asks[start_index] - path.bids[start_index])
    spread = base_spread * spread_mult

    def executable_quotes(index: int) -> tuple[float, float]:
        mid = (float(path.bids[index]) + float(path.asks[index])) / 2.0
        half_spread = (float(path.asks[index]) - float(path.bids[index])) * spread_mult / 2.0
        return mid - half_spread, mid + half_spread

    entry_bid, entry_ask = executable_quotes(start_index)
    entry = entry_ask if direction > 0 else entry_bid
    stop = entry - direction * stop_distance
    target = entry + direction * target_distance
    favorable = 0.0
    last_r = 0.0
    start_ms = int(start.timestamp() * 1000)

    def elapsed_bars(index: int) -> int:
        elapsed_ms = max(0, int(path.times[index]) - start_ms)
        return min(horizon_bars, max(1, math.ceil(elapsed_ms / (15 * 60 * 1000))))

    for index in range(start_index, end_index):
        bid, ask = executable_quotes(index)
        executable = bid if direction > 0 else ask
        last_r = direction * (executable - entry) / stop_distance
        favorable = max(favorable, last_r)
        stop_hit = bid <= stop if direction > 0 else ask >= stop
        target_hit = bid >= target if direction > 0 else ask <= target
        bars = elapsed_bars(index)
        if stop_hit and target_hit:
            return TickOutcome(-1.0, favorable, "STOP_AMBIG", bars)
        if stop_hit:
            return TickOutcome(-1.0, favorable, "STOP", bars)
        if target_hit:
            return TickOutcome(target_distance / stop_distance, favorable, "TARGET", bars)
    # The spread was paid at entry and the executable side is used at exit.
    return TickOutcome(last_r, favorable, "HORIZON", horizon_bars)


def _candidate_paths(rows: list[dict], features: list[dict | None], regimes: list[str],
                     atr: list[float], config: StrategyConfig, start: datetime, end: datetime,
                     path: TickPath, spread_mult: float) -> list[tuple[tuple[str, str, int], TickOutcome]]:
    results: list[tuple[tuple[str, str, int], TickOutcome]] = []
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
        outcomes: list[tuple[tuple[str, str, int], TickOutcome]] = []
        entry_time = rows[index + 1]["t"]
        for signal in signals:
            outcome = tick_outcome(
                path, signal.direction, entry_time, config.horizon,
                config.stop_atr * atr[index], config.target_atr * atr[index], spread_mult,
            )
            if outcome is not None:
                outcomes.append((model_key(signal), outcome))
        results.extend(outcomes)
        # Do not let overlapping hypothetical trades multiply the sample.
        # All competing hypotheses at this decision share the same next-entry
        # timestamp; skip past the longest modeled path before reconsidering.
        index += max((outcome.bars for _, outcome in outcomes), default=1) + 1
    return results


def fit_stats(rows: list[dict], features: list[dict | None], regimes: list[str], atr: list[float],
              config: StrategyConfig, start: datetime, end: datetime, path: TickPath,
              spread_mult: float) -> dict[tuple[str, str, int], TickStats]:
    raw: dict[tuple[str, str, int], list[TickOutcome]] = defaultdict(list)
    for key, outcome in _candidate_paths(rows, features, regimes, atr, config, start, end, path, spread_mult):
        raw[key].append(outcome)
    return {
        key: TickStats(len(outcomes), sum(outcome.r > 0 for outcome in outcomes),
                       sum(outcome.r for outcome in outcomes),
                       sum(outcome.favorable_r for outcome in outcomes))
        for key, outcomes in raw.items()
    }


def decide(stats: dict[tuple[str, str, int], TickStats], key: tuple[str, str, int],
           config: StrategyConfig, atr_value: float, observed_spread: float) -> tuple[bool, str]:
    item = stats.get(key)
    if item is None or item.n < config.min_samples:
        return False, "insufficient-sample"
    payoff = config.target_atr / config.stop_atr
    break_even = 1.0 / (1.0 + payoff)
    probability = (item.wins + 1.0) / (item.n + 2.0)
    expected_r = item.sum_r / item.n
    favorable = item.sum_favorable_r / item.n
    cost_floor = 1.25 * observed_spread / max(config.stop_atr * atr_value, 1e-9)
    if expected_r <= 0:
        return False, "negative-expected-r"
    if probability < break_even + config.min_confidence_margin:
        return False, "confidence-below-break-even"
    if favorable < max(0.2, cost_floor):
        return False, "favorable-move-below-spread-cost"
    return True, "accepted"


def evaluate(rows: list[dict], features: list[dict | None], regimes: list[str], atr: list[float],
             config: StrategyConfig, stats: dict[tuple[str, str, int], TickStats], start: datetime,
             end: datetime, path: TickPath, spread_mult: float) -> dict:
    values: list[float] = []
    reasons: dict[str, int] = defaultdict(int)
    used: dict[str, int] = defaultdict(int)
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
        accepted: list[tuple[object, TickOutcome]] = []
        for signal in signals:
            key = model_key(signal)
            ok, reason = decide(stats, key, config, atr[index], path.median_spread * spread_mult)
            if not ok:
                reasons[reason] += 1
                continue
            outcome = tick_outcome(path, signal.direction, rows[index + 1]["t"], config.horizon,
                                   config.stop_atr * atr[index], config.target_atr * atr[index], spread_mult)
            if outcome is not None:
                accepted.append((signal, outcome))
            else:
                reasons["tick-coverage-gap"] += 1
        if len(accepted) != 1:
            if signals:
                reasons["no-trade-ambiguous-or-rejected"] += 1
            index += 1
            continue
        signal, outcome = accepted[0]
        values.append(outcome.r)
        used[signal.hypothesis] += 1
        # A new analysis is allowed only after this trade's path has ended.
        index += outcome.bars + 1
    equity = np.cumsum(values) if values else np.asarray([], dtype=float)
    drawdown = float(np.max(np.maximum.accumulate(equity) - equity)) if len(equity) else 0.0
    days = max((end - start).total_seconds() / 86400, 1.0)
    return {
        "n": len(values),
        "wins": int(sum(value > 0 for value in values)),
        "total_r": round(float(sum(values)), 6),
        "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
        "max_drawdown_r": round(drawdown, 6),
        "trades_per_day": round(len(values) / days, 3),
        "hypotheses": dict(used),
        "rejections": dict(reasons),
    }


def run(data_dir: Path, tick_paths: list[Path], start: datetime, end: datetime,
        train_days: int, test_days: int, m15_path: Path | None = None,
        h1_path: Path | None = None) -> dict:
    rows = load_bars(m15_path or data_dir / "m15.csv")
    h1_rows = load_bars(h1_path or data_dir / "h1.csv")
    atr, features = build_features(rows)
    regimes = build_regimes(rows, h1_rows, atr)
    ticks = load_ticks(tick_paths)
    folds: list[dict] = []
    cursor = start
    for fold in range(1, 7):
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        validation_start = train_end - timedelta(days=test_days)
        choices: list[tuple[StrategyConfig, dict]] = []
        for config in configs():
            fitted = fit_stats(rows, features, regimes, atr, config, cursor, validation_start, ticks, 1.0)
            validation = evaluate(rows, features, regimes, atr, config, fitted,
                                  validation_start, train_end, ticks, 1.0)
            stress_fit = fit_stats(rows, features, regimes, atr, config, cursor, validation_start, ticks, 1.5)
            stress = evaluate(rows, features, regimes, atr, config, stress_fit,
                              validation_start, train_end, ticks, 1.5)
            if validation["n"] >= 4 and validation["mean_r"] > 0 and stress["mean_r"] > 0:
                choices.append((config, validation))
        if choices:
            selected, validation = max(choices, key=lambda item: (item[1]["mean_r"], item[1]["n"]))
            fitted = fit_stats(rows, features, regimes, atr, selected, cursor, train_end, ticks, 1.0)
            test = evaluate(rows, features, regimes, atr, selected, fitted, train_end, test_end, ticks, 1.0)
            stress = {}
            for multiplier in SPREAD_STRESS:
                stress_fit = fit_stats(rows, features, regimes, atr, selected, cursor, train_end, ticks, multiplier)
                stress[str(multiplier)] = evaluate(rows, features, regimes, atr, selected, stress_fit,
                                                    train_end, test_end, ticks, multiplier)
            selection = {"config": asdict(selected), "validation": validation}
        else:
            selected = None
            test = {"n": 0, "total_r": 0.0, "mean_r": 0.0, "max_drawdown_r": 0.0}
            stress = {}
            selection = {"config": None, "reason": "no-positive-tick-validation-configuration"}
        available = covers_window(ticks, cursor, test_end)
        folds.append({"fold": fold, "train_window": [cursor.isoformat(), train_end.isoformat()],
                      "test_window": [train_end.isoformat(), test_end.isoformat()],
                      "tick_window_continuous": available,
                      "selection": selection, "test_base_spread": test,
                      "test_spread_stress": stress})
        cursor += timedelta(days=test_days)
        if cursor + timedelta(days=train_days) > end:
            break
    return {
        "schema": "mitemshub.v75.clean-slate-tick-path.v1",
        "data_dir": str(data_dir),
        "tick_files": [str(path) for path in tick_paths],
        "tick_coverage": {"first": ticks.first.isoformat(), "last": ticks.last.isoformat(),
                          "ticks": len(ticks.times), "median_spread": ticks.median_spread,
                          "gap_count_over_120s": ticks.gap_count, "max_gap_ms": ticks.max_gap_ms},
        "design": {"entry": "first broker quote at next M15 bar; ask for buy, bid for sell",
                   "exit": "bid for buy, ask for sell; target/stop same-tick ambiguity resolves to stop",
                   "selection": "chronological validation, spread stress, then untouched outer test",
                   "no_trade": "explicit when continuation/reversal is absent, ambiguous, costly, or under-sampled",
                   "spread_stress": SPREAD_STRESS, "config_count": len(configs())},
        "folds": folds,
    }


def _default_tick_paths() -> list[Path]:
    return sorted(DEFAULT_TICKS.glob("volatility_75_index_ticks_*.csv"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--m15", type=Path, default=None, help="explicit matching M15 bar CSV")
    parser.add_argument("--h1", type=Path, default=None, help="explicit matching H1 bar CSV")
    parser.add_argument("--ticks", nargs="+", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=10)
    args = parser.parse_args()
    tick_paths = args.ticks or _default_tick_paths()
    if not tick_paths:
        raise SystemExit("No tick files found. Supply --ticks explicitly.")
    result = run(args.data_dir, tick_paths, args.start, args.end, args.train_days,
                 args.test_days, args.m15, args.h1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("tick coverage:", result["tick_coverage"])
    for fold in result["folds"]:
        config = fold["selection"]["config"]
        test = fold["test_base_spread"]
        name = config["name"] if config else "NO_TRADE"
        print(f"fold={fold['fold']} selected={name} n={test['n']} R={test['total_r']:+.3f} DD={test['max_drawdown_r']:.2f}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
