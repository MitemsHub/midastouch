#!/usr/bin/env python3
"""Causal regime-aware 2--4 hour horizon policy.

The policy separates continuation and reversal hypotheses.  It fits their
historical outcomes only on the preceding training window, then permits a test
trade only when:

* one hypothesis dominates the other by expected net R;
* the fitted gross move clears the current spread and execution buffer;
* Bayesian win confidence and sample size are adequate;
* the current feature distribution has not drifted too far from training; and
* recent live outcomes have not invalidated the fitted model.

Every failed condition returns NO_TRADE.  Account equity and lot sizing are
intentionally excluded from this directional study.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
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
sys.path.insert(0, str(HERE))
from replay_v75_week import ema, wilder_atr  # noqa: E402

DEFAULT_DATA = ROOT / "artifacts" / "v75_blind90"
DEFAULT_OUTPUT = DEFAULT_DATA / "horizon_regime_policy.json"
SPREADS = (18.5, 27.75, 37.0)


@dataclass(frozen=True)
class PolicyCandidate:
    name: str
    mode: str
    min_m32: float
    min_efficiency: float
    reversal_distance: float
    reversal_max_efficiency: float
    dominance_margin: float
    min_confidence: float
    min_samples: int
    drift_limit: float
    cost_buffer: float
    min_move_r: float
    stop_atr: float
    target_atr: float


@dataclass(frozen=True)
class Signal:
    category: str
    direction: int
    strength: float
    predicted_move_r: float


@dataclass
class PolicyState:
    recent_r: deque[float]
    invalidated: bool = False
    invalidation_reason: str = ""


@dataclass(frozen=True)
class Model:
    stats: dict[tuple[str, int], dict[str, float]]
    feature_mean: np.ndarray
    feature_std: np.ndarray


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def load_rows(path: Path) -> list[dict[str, float | datetime]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {
                "t": datetime.fromisoformat(row["time"]),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
            }
            for row in csv.DictReader(handle)
        ]


def clip(value: float, low: float = -3.0, high: float = 3.0) -> float:
    return max(low, min(high, value))


def feature_at(
    rows: list[dict],
    closes: list[float],
    ema8: list[float],
    ema32: list[float],
    atr: list[float],
    index: int,
) -> dict[str, float] | None:
    if index < 32 or atr[index] <= 0:
        return None
    current_atr = atr[index]
    deltas = [closes[index] - closes[index - n] for n in (8, 16, 32)]
    m8, m16, m32 = [clip(delta / current_atr / 3.0) for delta in deltas]
    slope = clip((ema8[index] - ema32[index]) / current_atr / 2.0)
    distance = clip((closes[index] - ema32[index]) / current_atr / 3.0)
    path = sum(abs(closes[k] - closes[k - 1]) for k in range(index - 31, index + 1))
    efficiency = abs(deltas[2]) / path if path > 0 else 0.0
    sign32 = 1 if m32 > 0 else -1 if m32 < 0 else 0
    sign8 = 1 if m8 > 0 else -1 if m8 < 0 else 0
    return {
        "m8": m8,
        "m16": m16,
        "m32": m32,
        "slope": slope,
        "distance": distance,
        "efficiency": efficiency,
        "sign32": float(sign32),
        "sign8": float(sign8),
    }


def build_features(rows: list[dict]) -> tuple[list[float], list[dict[str, float] | None]]:
    closes = [float(row["c"]) for row in rows]
    atr = wilder_atr(rows, 14)
    ema8 = ema(closes, 8)
    ema32 = ema(closes, 32)
    features = [feature_at(rows, closes, ema8, ema32, atr, i) for i in range(len(rows))]
    return atr, features


def raw_signals(feature: dict[str, float], candidate: PolicyCandidate) -> list[Signal]:
    sign32 = int(feature["sign32"])
    if sign32 == 0:
        return []
    signals: list[Signal] = []
    aligned = (
        sign32 * feature["m16"] > 0
        and sign32 * feature["slope"] > 0
        and feature["efficiency"] >= candidate.min_efficiency
        and abs(feature["m32"]) >= candidate.min_m32
    )
    if aligned:
        strength = (
            abs(feature["m32"]) + abs(feature["m16"]) + abs(feature["slope"])
        ) / 3.0 + feature["efficiency"]
        signals.append(Signal("CONTINUATION", sign32, strength, abs(feature["m32"])))

    reversal = (
        abs(feature["m32"]) >= candidate.min_m32
        and abs(feature["distance"]) >= candidate.reversal_distance
        and sign32 * feature["m8"] < 0
        and feature["efficiency"] <= candidate.reversal_max_efficiency
    )
    if reversal:
        strength = abs(feature["distance"]) + abs(feature["m32"]) + (1.0 - feature["efficiency"])
        signals.append(Signal("REVERSAL", -sign32, strength, abs(feature["distance"]) + abs(feature["m8"])))

    if candidate.mode != "AUTO":
        signals = [signal for signal in signals if signal.category == candidate.mode]
    return signals


def evaluate_trade(
    rows: list[dict],
    direction: int,
    entry: float,
    stop_distance: float,
    target_distance: float,
    spread: float,
) -> tuple[float, float, str, int]:
    half_spread = spread / 2.0
    stop = entry - direction * stop_distance
    target = entry + direction * target_distance
    entry_mid = entry - direction * half_spread
    max_favorable_r = 0.0
    for offset, row in enumerate(rows, start=1):
        favorable_mid = float(row["h"]) if direction > 0 else float(row["l"])
        favorable_r = direction * (favorable_mid - entry_mid) / stop_distance
        max_favorable_r = max(max_favorable_r, favorable_r)
        if direction > 0:
            hit_stop = float(row["l"]) - half_spread <= stop
            hit_target = float(row["h"]) - half_spread >= target
        else:
            hit_stop = float(row["h"]) + half_spread >= stop
            hit_target = float(row["l"]) + half_spread <= target
        if hit_stop and hit_target:
            exit_mid = float(row["l"]) if direction > 0 else float(row["h"])
            return -1.0, max_favorable_r, "STOP_AMBIG", offset
        if hit_stop:
            exit_mid = float(row["l"]) if direction > 0 else float(row["h"])
            return -1.0, max_favorable_r, "STOP", offset
        if hit_target:
            exit_mid = float(row["h"]) if direction > 0 else float(row["l"])
            return target_distance / stop_distance, max_favorable_r, "TARGET", offset
    exit_mid = float(rows[-1]["c"])
    exit_fill = exit_mid - direction * half_spread
    return direction * (exit_fill - entry) / stop_distance, max_favorable_r, "HORIZON", len(rows)


def iter_events(
    rows: list[dict],
    features: list[dict[str, float] | None],
    atr: list[float],
    candidate: PolicyCandidate,
    start: datetime,
    end: datetime,
    spread: float,
    reassess_bars: int,
) -> Iterable[tuple[int, Signal, float, float, str, int]]:
    index = max(480, 32)
    while index + 16 < len(rows):
        timestamp = rows[index]["t"]
        if timestamp < start:
            index += 1
            continue
        if timestamp >= end:
            return
        feature = features[index]
        signals = raw_signals(feature, candidate) if feature else []
        if not signals or atr[index] <= 0:
            index += 1
            continue
        # Fitting records each available hypothesis. AUTO selection happens
        # only after the category statistics have been fitted.
        for signal in signals:
            entry = float(rows[index + 1]["o"]) + signal.direction * spread / 2.0
            stop_distance = candidate.stop_atr * atr[index]
            target_distance = candidate.target_atr * atr[index]
            value, gross_atr, reason, exit_bars = evaluate_trade(
                rows[index + 1:index + 17], signal.direction, entry,
                stop_distance, target_distance, spread,
            )
            yield index, signal, value, gross_atr, reason, exit_bars
        # Events are spaced after the observed completion, not after entry.
        # When both hypotheses exist they describe one market state; consume
        # the longer trade path once rather than double-counting exposure.
        exit_bars = min(
            evaluate_trade(
                rows[index + 1:index + 17],
                signal.direction,
                float(rows[index + 1]["o"]) + signal.direction * spread / 2.0,
                candidate.stop_atr * atr[index],
                candidate.target_atr * atr[index],
                spread,
            )[3]
            for signal in signals
        )
        index += max(1, exit_bars + reassess_bars)


def fit_model(
    rows: list[dict],
    features: list[dict[str, float] | None],
    atr: list[float],
    candidate: PolicyCandidate,
    start: datetime,
    end: datetime,
    spread: float,
    reassess_bars: int,
) -> Model:
    stats: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {"n": 0.0, "wins": 0.0, "sum_r": 0.0, "sum_mfe_r": 0.0}
    )
    feature_values: list[list[float]] = []
    for index in range(max(480, 32), len(rows)):
        if start <= rows[index]["t"] < end and features[index] is not None:
            feature_values.append([
                features[index]["m8"], features[index]["m16"], features[index]["m32"],
                features[index]["slope"], features[index]["distance"], features[index]["efficiency"],
            ])
    for _, signal, value, mfe_r, _, _ in iter_events(
        rows, features, atr, candidate, start, end, spread, reassess_bars
    ):
        item = stats[(signal.category, signal.direction)]
        item["n"] += 1
        item["wins"] += value > 0
        item["sum_r"] += value
        item["sum_mfe_r"] += mfe_r
    if feature_values:
        matrix = np.asarray(feature_values, dtype=float)
        feature_mean = matrix.mean(axis=0)
        feature_std = np.maximum(matrix.std(axis=0), 0.05)
    else:
        feature_mean = np.zeros(6)
        feature_std = np.ones(6)
    return Model(dict(stats), feature_mean, feature_std)


def choose_signal(
    model: Model,
    feature: dict[str, float],
    candidate: PolicyCandidate,
    current_atr: float,
    spread: float,
    state: PolicyState,
    recent_features: list[dict[str, float]],
) -> tuple[Signal | None, str, float]:
    if state.invalidated:
        return None, f"model-invalidated:{state.invalidation_reason}", 0.0
    if len(recent_features) >= 24:
        current = np.asarray([
            np.mean([item[key] for item in recent_features[-24:]])
            for key in ("m8", "m16", "m32", "slope", "distance", "efficiency")
        ])
        drift_z = float(np.mean(np.abs(current - model.feature_mean) / model.feature_std))
        if drift_z > candidate.drift_limit:
            state.invalidated = True
            state.invalidation_reason = f"feature-drift-z={drift_z:.2f}"
            return None, state.invalidation_reason, drift_z
    else:
        drift_z = 0.0

    viable: list[tuple[Signal, float, float, float]] = []
    for signal in raw_signals(feature, candidate):
        item = model.stats.get((signal.category, signal.direction))
        if not item or item["n"] < candidate.min_samples:
            continue
        posterior_confidence = (item["wins"] + 1.0) / (item["n"] + 2.0)
        expected_r = item["sum_r"] / item["n"]
        predicted_move_r = item["sum_mfe_r"] / item["n"]
        payoff_r = candidate.target_atr / candidate.stop_atr
        break_even_win_rate = 1.0 / (1.0 + payoff_r)
        # A target larger than the stop can be profitable below 50% wins. The
        # confidence gate is therefore measured above the strategy's actual
        # break-even win probability, not against an arbitrary 50% threshold.
        required_win_rate = break_even_win_rate + candidate.min_confidence
        cost_floor_r = candidate.cost_buffer * spread / max(candidate.stop_atr * current_atr, 1e-9)
        if posterior_confidence < required_win_rate:
            continue
        if predicted_move_r < max(candidate.min_move_r, cost_floor_r):
            continue
        if expected_r <= 0.0:
            continue
        viable.append((signal, expected_r, posterior_confidence, predicted_move_r))
    if not viable:
        return None, "no-candidate-cleared-confidence-cost", drift_z
    viable.sort(key=lambda item: item[1], reverse=True)
    best = viable[0]
    if len(viable) > 1 and best[1] - viable[1][1] < candidate.dominance_margin:
        return None, "continuation-reversal-not-dominant", drift_z
    signal = best[0]
    return Signal(signal.category, signal.direction, signal.strength, best[3]), signal.category, drift_z


def evaluate_test(
    rows: list[dict],
    features: list[dict[str, float] | None],
    atr: list[float],
    model: Model,
    candidate: PolicyCandidate,
    start: datetime,
    end: datetime,
    spread: float,
    reassess_bars: int,
) -> dict:
    values: list[float] = []
    reasons: list[str] = []
    categories: dict[str, int] = {"CONTINUATION": 0, "REVERSAL": 0}
    recent_features: list[dict[str, float]] = []
    state = PolicyState(deque(maxlen=6))
    index = max(480, 32)
    invalidation_events = 0
    while index + 16 < len(rows):
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
        recent_features.append(feature)
        signal, reason, _ = choose_signal(
            model, feature, candidate, atr[index], spread, state, recent_features
        )
        if signal is None:
            if state.invalidated and reason.startswith("feature-drift"):
                invalidation_events += 1
            index += 1
            continue
        entry = float(rows[index + 1]["o"]) + signal.direction * spread / 2.0
        value, _, exit_reason, exit_bars = evaluate_trade(
            rows[index + 1:index + 17], signal.direction, entry,
            candidate.stop_atr * atr[index], candidate.target_atr * atr[index], spread,
        )
        values.append(value)
        state.recent_r.append(value)
        reasons.append(exit_reason)
        categories[signal.category] += 1
        if len(state.recent_r) >= 6 and sum(state.recent_r) <= -2.0:
            state.invalidated = True
            state.invalidation_reason = "six-trade-loss-window"
            invalidation_events += 1
        index += max(1, exit_bars + reassess_bars)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "n": len(values),
        "wins": sum(value > 0 for value in values),
        "hit_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else 0.0,
        "total_r": round(sum(values), 6),
        "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
        "max_drawdown_r": round(max_dd, 6),
        "exit_reasons": {reason: reasons.count(reason) for reason in ("TARGET", "STOP", "STOP_AMBIG", "HORIZON")},
        "categories": categories,
        "model_invalidated": state.invalidated,
        "invalidation_reason": state.invalidation_reason,
        "invalidation_events": invalidation_events,
        "trades_per_day": round(len(values) / max((end - start).total_seconds() / 86400.0, 1.0), 3),
    }


def make_candidates() -> list[PolicyCandidate]:
    result: list[PolicyCandidate] = []
    for mode in ("AUTO", "CONTINUATION", "REVERSAL"):
        for min_m32 in (0.18, 0.30, 0.45):
            for min_efficiency in (0.25, 0.35, 0.45):
                for reversal_distance in (0.45, 0.75):
                    for confidence in (0.05, 0.10):
                        result.append(PolicyCandidate(
                            name=f"{mode}_m{min_m32:.2f}_e{min_efficiency:.2f}_d{reversal_distance:.2f}_c{confidence:.2f}",
                            mode=mode,
                            min_m32=min_m32,
                            min_efficiency=min_efficiency,
                            reversal_distance=reversal_distance,
                            reversal_max_efficiency=0.60,
                            dominance_margin=0.05,
                            min_confidence=confidence,
                            min_samples=12,
                            drift_limit=3.0,
                            cost_buffer=1.25,
                            min_move_r=0.20,
                            stop_atr=0.75,
                            target_atr=2.5,
                        ))
    return result


def run(data_dir: Path, start: datetime, end: datetime, train_days: int, test_days: int, reassess_bars: int) -> dict:
    rows = load_rows(data_dir / "m15.csv")
    atr, features = build_features(rows)
    all_candidates = make_candidates()
    folds: list[dict] = []
    cursor = start
    fold_number = 1
    while cursor + timedelta(days=train_days + test_days) <= end:
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        # Nested chronological selection: choose on an inner validation slice,
        # never on the same outcomes used to fit the candidate model. The
        # selected candidate is refit on the complete outer training window
        # before the untouched test window is evaluated.
        inner_fit_end = train_end - timedelta(days=test_days)
        inner_validation_start = inner_fit_end
        selection_results: list[tuple[PolicyCandidate, dict]] = []
        for candidate in all_candidates:
            inner_model = fit_model(
                rows, features, atr, candidate, cursor, inner_fit_end,
                SPREADS[0], reassess_bars
            )
            validation_result = evaluate_test(
                rows, features, atr, inner_model, candidate,
                inner_validation_start, train_end, SPREADS[0], reassess_bars
            )
            selection_results.append((candidate, validation_result))
        eligible = [
            item for item in selection_results
            if item[1]["n"] >= 6 and item[1]["mean_r"] > 0.0
        ]
        if eligible:
            selected, validation_result = max(
                eligible,
                key=lambda item: (
                    item[1]["mean_r"],
                    item[1]["total_r"],
                    -item[1]["max_drawdown_r"],
                ),
            )
            # Refit only after the policy has been selected.
            model = fit_model(
                rows, features, atr, selected, cursor, train_end,
                SPREADS[0], reassess_bars
            )
            test_result = evaluate_test(
                rows, features, atr, model, selected,
                train_end, test_end, SPREADS[0], reassess_bars
            )
            stress = {
                str(spread): evaluate_test(
                    rows, features, atr, model, selected,
                    train_end, test_end, spread, reassess_bars
                )
                for spread in SPREADS
            }
            selection = {
                "candidate": asdict(selected),
                "inner_validation": validation_result,
                "inner_validation_window": [
                    inner_validation_start.isoformat(), train_end.isoformat()
                ],
                "refit_window": [cursor.isoformat(), train_end.isoformat()],
            }
        else:
            selected = None
            test_result = {"n": 0, "total_r": 0.0, "mean_r": 0.0}
            stress = {}
            selection = {
                "candidate": None,
                "reason": "no candidate passed positive inner validation and minimum sample gates",
            }
        folds.append({
            "fold": fold_number,
            "train_window": [cursor.isoformat(), train_end.isoformat()],
            "test_window": [train_end.isoformat(), test_end.isoformat()],
            "selection": selection,
            "test_base_spread": test_result,
            "test_spread_stress": stress,
        })
        cursor += timedelta(days=test_days)
        fold_number += 1
    return {
        "schema": "mitemshub.v75.horizon-regime-policy.v1",
        "symbol": "Volatility 75 Index",
        "data_dir": str(data_dir),
        "design": {
            "hypotheses": ["CONTINUATION", "REVERSAL"],
            "no_trade_gates": ["hypothesis dominance", "predicted move > spread buffer", "Bayesian confidence", "feature drift", "recent model invalidation"],
            "entry": "next M15 open with quote-aware half-spread",
            "management": "0.75 ATR stop, 2.5 ATR target, 16-bar maximum horizon",
            "reassessment": "after actual completion plus configured bars",
            "selection": "nested chronological inner validation, then refit on the outer training window only",
            "candidate_count": len(all_candidates),
            "spreads": SPREADS,
        },
        "folds": folds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CERT_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--test-days", type=int, default=10)
    parser.add_argument("--reassess-bars", type=int, default=20)
    args = parser.parse_args()
    if args.train_days <= 0 or args.test_days <= 0 or args.reassess_bars < 0:
        parser.error("train/test days must be positive and reassess-bars cannot be negative")
    result = run(args.data_dir, args.start, args.end, args.train_days, args.test_days, args.reassess_bars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for fold in result["folds"]:
        candidate = fold["selection"]["candidate"]
        test = fold["test_base_spread"]
        print(f"fold={fold['fold']} selected={candidate['name'] if candidate else 'NO_TRADE'} "
              f"test n={test['n']:3d} R={test['total_r']:+.3f} mean={test['mean_r']:+.4f} "
              f"DD={test.get('max_drawdown_r', 0.0):.2f} trades/day={test.get('trades_per_day', 0.0)}")
        for spread, stress in fold["test_spread_stress"].items():
            print(f"  spread={float(spread):5.2f} n={stress['n']:3d} R={stress['total_r']:+.3f}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
