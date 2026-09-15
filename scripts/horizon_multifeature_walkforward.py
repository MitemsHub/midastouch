#!/usr/bin/env python3
"""Walk-forward test of a causal multi-feature 2--4 hour horizon classifier.

The classifier is deliberately small and interpretable. It uses only data known
at the decision bar: multi-scale momentum, EMA slope/distance, and directional
efficiency. A signal is emitted only when the score and feature agreement pass
fixed candidate thresholds; otherwise the result is NO_TRADE.

For every rolling fold, candidates are selected from the preceding training
window only. The following test window is then evaluated with quote-aware
entry/exit fills, measured spread, conservative same-bar handling, and a fixed
post-trade reassessment cadence. Account equity and lot sizing are excluded so
this measures the directional/exit hypothesis rather than account geometry.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from replay_v75_week import ema, wilder_atr  # noqa: E402

DEFAULT_DATA = ROOT / "artifacts" / "v75_blind90"
DEFAULT_OUTPUT = DEFAULT_DATA / "horizon_multifeature_walkforward.json"
BASE_SPREAD = 18.5
SPREADS = (18.5, 27.75, 37.0)
LOOKBACK = 32
HORIZON = 16
REASSESS_BARS = 20


@dataclass(frozen=True)
class Classifier:
    """A fixed causal score and trade geometry."""

    name: str
    w_m8: float
    w_m16: float
    w_m32: float
    w_slope: float
    w_distance: float
    threshold: float
    min_agreement: int
    min_efficiency: float
    require_slope: bool
    max_abs_distance: float
    stop_atr: float
    target_atr: float


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [{
            "t": datetime.fromisoformat(row["time"]),
            "o": float(row["open"]),
            "h": float(row["high"]),
            "l": float(row["low"]),
            "c": float(row["close"]),
        } for row in csv.DictReader(handle)]


def clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def feature_at(rows: list[dict], closes: list[float], ema8: list[float], ema32: list[float],
               atr: list[float], index: int) -> dict | None:
    if index < max(LOOKBACK, 32) or atr[index] <= 0:
        return None
    current_atr = atr[index]
    deltas = [closes[index] - closes[index - n] for n in (8, 16, 32)]
    m8, m16, m32 = [clip(delta / current_atr / 3.0) for delta in deltas]
    slope = clip((ema8[index] - ema32[index]) / current_atr / 2.0)
    distance = clip((closes[index] - ema32[index]) / current_atr / 3.0)
    path = sum(abs(closes[k] - closes[k - 1]) for k in range(index - 31, index + 1))
    efficiency = abs(deltas[2]) / path if path > 0 else 0.0
    direction_sign = 1 if deltas[2] > 0 else -1 if deltas[2] < 0 else 0
    signed_efficiency = efficiency * direction_sign
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in (m8, m16, m32, slope)]
    return {
        "m8": m8,
        "m16": m16,
        "m32": m32,
        "slope": slope,
        "distance": distance,
        "efficiency": efficiency,
        "signed_efficiency": signed_efficiency,
        "agreement": sum(sign == direction_sign for sign in signs),
        "direction_sign": direction_sign,
    }


def score_feature(feature: dict, candidate: Classifier) -> float:
    return (
        candidate.w_m8 * feature["m8"]
        + candidate.w_m16 * feature["m16"]
        + candidate.w_m32 * feature["m32"]
        + candidate.w_slope * feature["slope"]
        + candidate.w_distance * feature["distance"]
    )


def direction_for(feature: dict, candidate: Classifier) -> int:
    score = score_feature(feature, candidate)
    if abs(score) < candidate.threshold:
        return 0
    if feature["agreement"] < candidate.min_agreement:
        return 0
    if feature["efficiency"] < candidate.min_efficiency:
        return 0
    if candidate.require_slope and feature["slope"] * score <= 0:
        return 0
    if abs(feature["distance"]) > candidate.max_abs_distance:
        return 0
    return 1 if score > 0 else -1


def evaluate_trade(rows: list[dict], direction: int, entry: float, stop_distance: float,
                   target_distance: float, spread: float) -> tuple[float, str, int]:
    half_spread = spread / 2.0
    stop = entry - direction * stop_distance
    target = entry + direction * target_distance
    for offset, row in enumerate(rows, start=1):
        if direction > 0:
            hit_stop = row["l"] - half_spread <= stop
            hit_target = row["h"] - half_spread >= target
        else:
            hit_stop = row["h"] + half_spread >= stop
            hit_target = row["l"] + half_spread <= target
        if hit_stop and hit_target:
            return -1.0, "STOP_AMBIG", offset
        if hit_stop:
            return -1.0, "STOP", offset
        if hit_target:
            return target_distance / stop_distance, "TARGET", offset
    exit_fill = rows[-1]["c"] - direction * half_spread
    return direction * (exit_fill - entry) / stop_distance, "HORIZON", len(rows)


def summarize(values: list[float], reasons: list[str]) -> dict:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    counts = {reason: reasons.count(reason) for reason in ("TARGET", "STOP", "STOP_AMBIG", "HORIZON")}
    return {
        "n": len(values),
        "wins": sum(value > 0 for value in values),
        "hit_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else 0.0,
        "total_r": round(sum(values), 6),
        "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
        "max_drawdown_r": round(max_dd, 6),
        "exit_reasons": counts,
        "trade_days_per_day": None,
    }


def evaluate(rows: list[dict], features: list[dict | None], atr: list[float],
             candidate: Classifier, start: datetime, end: datetime, spread: float,
             reassess_bars: int = REASSESS_BARS) -> dict:
    values: list[float] = []
    reasons: list[str] = []
    trades: list[dict] = []
    recent_r: deque[float] = deque(maxlen=6)
    model_invalidated = False
    invalidation_reason = ""
    index = max(480, LOOKBACK)
    while index + HORIZON < len(rows):
        timestamp = rows[index]["t"]
        if timestamp < start:
            index += 1
            continue
        if timestamp >= end:
            break
        feature = features[index]
        if model_invalidated:
            index += 1
            continue
        direction = direction_for(feature, candidate) if feature else 0
        if direction == 0:
            index += 1
            continue
        entry = rows[index + 1]["o"] + direction * spread / 2.0
        stop_distance = candidate.stop_atr * atr[index]
        target_distance = candidate.target_atr * atr[index]
        value, reason, exit_bars = evaluate_trade(
            rows[index + 1:index + HORIZON + 1], direction, entry,
            stop_distance, target_distance, spread,
        )
        values.append(value)
        reasons.append(reason)
        recent_r.append(value)
        if len(recent_r) == recent_r.maxlen and sum(recent_r) <= -2.0:
            model_invalidated = True
            invalidation_reason = "six-trade-loss-window"
        trades.append({"time": rows[index + 1]["t"].isoformat(), "direction": direction,
                       "r": round(value, 6), "reason": reason, "exit_bars": exit_bars})
        # Reassess after the position has actually completed. A zero gap means
        # the next bar after the close is eligible; a positive gap is explicit.
        index += max(1, exit_bars + reassess_bars)
    result = summarize(values, reasons)
    days = max((end - start).total_seconds() / 86400.0, 1.0)
    result["trade_days_per_day"] = round(len(values) / days, 3)
    result["model_invalidated"] = model_invalidated
    result["invalidation_reason"] = invalidation_reason
    result["trades"] = trades
    return result


def candidates() -> list[Classifier]:
    families = [
        ("mom32", 0.0, 0.0, 1.0, 0.0, 0.0),
        ("mom_multi", 0.15, 0.25, 0.60, 0.0, 0.0),
        ("mom_slope", 0.10, 0.20, 0.45, 0.25, 0.0),
        ("mom_structure", 0.10, 0.20, 0.40, 0.20, 0.10),
        ("slope_structure", 0.05, 0.15, 0.35, 0.30, 0.15),
        ("balanced", 0.15, 0.20, 0.30, 0.20, 0.15),
    ]
    result: list[Classifier] = []
    for family, w8, w16, w32, wslope, wdistance in families:
        for threshold in (0.08, 0.14):
            for min_agreement in (3, 4):
                for min_efficiency in (0.30, 0.45):
                    for require_slope in (False, True):
                        for max_abs_distance in (1.5, 3.0):
                            for stop_atr, target_atr in ((0.75, 2.5), (1.0, 2.5), (0.75, 2.0), (1.0, 2.0)):
                                result.append(Classifier(
                                    f"{family}_z{threshold:.2f}_a{min_agreement}_e{min_efficiency:.2f}_"
                                    f"s{int(require_slope)}_d{max_abs_distance:.1f}_sl{stop_atr:.2f}_tp{target_atr:.2f}",
                                    w8, w16, w32, wslope, wdistance, threshold,
                                    min_agreement, min_efficiency, require_slope,
                                    max_abs_distance, stop_atr, target_atr,
                                ))
    return result


def select_validation(
    validation_results: list[tuple[Classifier, dict, dict, dict]],
) -> tuple[Classifier | None, dict]:
    """Select only from a chronological validation slice.

    The prior selector ranked candidates on the same window used to report
    their training performance. That is not a blind test, even when the final
    test window is untouched. Requiring positive validation expectancy at the
    measured spread and at 1.5x spread removes that selection leakage.
    """
    eligible = [
        (candidate, base, stress, stress_2x)
        for candidate, base, stress, stress_2x in validation_results
        if base["n"] >= 8
        and base["mean_r"] > 0.0
        and stress["mean_r"] > 0.0
        and stress_2x["mean_r"] > 0.0
    ]
    if not eligible:
        return None, {
            "reason": "no candidate passed positive validation at base, 1.5x, and 2x spread",
            "candidate": None,
        }
    ranked = sorted(
        eligible,
        key=lambda item: (
            min(item[1]["mean_r"], item[2]["mean_r"], item[3]["mean_r"])
            - 0.01 * item[1]["max_drawdown_r"] / max(item[1]["n"], 1),
            item[1]["n"],
        ),
        reverse=True,
    )
    candidate, base, stress, stress_2x = ranked[0]
    return candidate, {
        "reason": "selected from validation only",
        "candidate": asdict(candidate),
        "validation": base,
        "validation_1_5x_spread": stress,
        "validation_2x_spread": stress_2x,
        "top5": [
            {
                "candidate": asdict(c),
                "validation": b,
                "validation_1_5x_spread": s,
                "validation_2x_spread": s2,
            }
            for c, b, s, s2 in ranked[:5]
        ],
    }


def build_features(rows: list[dict]) -> tuple[list[float], list[dict | None]]:
    closes = [row["c"] for row in rows]
    atr = wilder_atr(rows, 14)
    ema8 = ema(closes, 8)
    ema32 = ema(closes, 32)
    features = [feature_at(rows, closes, ema8, ema32, atr, index) for index in range(len(rows))]
    return atr, features


def run(data_dir: Path, start: datetime, end: datetime, train_days: int, test_days: int,
        reassess_bars: int) -> dict:
    rows = load_rows(data_dir / "m15.csv")
    atr, features = build_features(rows)
    all_candidates = candidates()
    folds = []
    cursor = start
    fold_number = 1
    while cursor + timedelta(days=train_days + test_days) <= end:
        train_start = cursor
        train_end = cursor + timedelta(days=train_days)
        test_start = train_end
        test_end = train_end + timedelta(days=test_days)
        validation_start = train_end - timedelta(days=test_days)
        validation_results = []
        for candidate in all_candidates:
            validation = evaluate(
                rows, features, atr, candidate, validation_start, train_end,
                BASE_SPREAD, reassess_bars
            )
            validation_stress = evaluate(
                rows, features, atr, candidate, validation_start, train_end,
                BASE_SPREAD * 1.5, reassess_bars
            )
            validation_stress_2x = evaluate(
                rows, features, atr, candidate, validation_start, train_end,
                BASE_SPREAD * 2.0, reassess_bars
            )
            validation_results.append((candidate, validation, validation_stress, validation_stress_2x))
        selected, selection = select_validation(validation_results)
        if selected is not None:
            selection["validation_window"] = [validation_start.isoformat(), train_end.isoformat()]
            selection["outer_train_context"] = [train_start.isoformat(), validation_start.isoformat()]
        test = evaluate(rows, features, atr, selected, test_start, test_end, BASE_SPREAD,
                          reassess_bars) if selected else summarize([], [])
        stress = {
            str(spread): evaluate(rows, features, atr, selected, test_start, test_end, spread,
                              reassess_bars)
            if selected else summarize([], [])
            for spread in SPREADS
        }
        folds.append({
            "fold": fold_number,
            "train_window": [train_start.isoformat(), train_end.isoformat()],
            "test_window": [test_start.isoformat(), test_end.isoformat()],
            "selection": selection,
            "test_base_spread": test,
            "test_spread_stress": stress,
        })
        cursor += timedelta(days=test_days)
        fold_number += 1
    return {
        "schema": "mitemshub.v75.horizon-multifeature-walkforward.v1",
        "symbol": "Volatility 75 Index",
        "data_dir": str(data_dir),
        "design": {
            "lookback_bars": LOOKBACK,
            "horizon_bars": HORIZON,
            "reassess_bars": "bars after actual trade completion before another analysis (0 = next bar)",
            "features": ["momentum_8/16/32", "EMA8-EMA32 slope", "close-EMA32 distance", "32-bar efficiency"],
            "signal_rule": "score threshold + at least 3 of 4 directional features agree + efficiency >= 0.30",
            "no_trade": "any failed gate emits no order; six-trade loss window invalidates the current policy",
            "entry": "next M15 open plus directional half-spread",
            "exit": "quote-aware ATR stop/target, stop first if same bar, fixed horizon otherwise",
            "selection": "nested chronological validation slice; validation must be positive at base, 1.5x, and 2x spread before outer test",
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
    parser.add_argument("--reassess-bars", type=int, default=0,
                        help="bars after actual completion before re-analysis; 0 means next bar")
    args = parser.parse_args()
    if args.train_days <= 0 or args.test_days <= 0 or args.reassess_bars < 0:
        parser.error("train/test days must be positive and reassess-bars cannot be negative")
    result = run(args.data_dir, args.start, args.end, args.train_days, args.test_days,
                 args.reassess_bars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for fold in result["folds"]:
        selected = fold["selection"]["candidate"]
        test = fold["test_base_spread"]
        print(f"fold={fold['fold']} selected={selected['name'] if selected else 'NO_TRADE'} "
              f"test n={test['n']:3d} R={test['total_r']:+.3f} mean={test['mean_r']:+.4f} "
              f"DD={test['max_drawdown_r']:.2f} trades/day={test['trade_days_per_day']}")
        for spread, stress in fold["test_spread_stress"].items():
            print(f"  spread={float(spread):5.2f} n={stress['n']:3d} R={stress['total_r']:+.3f}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
