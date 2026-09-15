"""V75 geometry policy fitting and common validation scoring."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime

from clean_slate_v75 import parse_dt
from v75_adaptive_router import discover, score_candidates
from v75_router_core import (
    GEOMETRIES,
    Pocket,
    evaluate_frozen_portfolio,
    evaluate_pocket,
    matches,
    pocket_key,
    setup_key,
    sequential_rows,
)

POLICY_ORIGINAL = "original"
POLICY_CALIBRATED = "calibrated"
POLICIES = (POLICY_ORIGINAL, POLICY_CALIBRATED)


def wilson_lower(wins: int, n: int, z: float = 1.645) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    denominator = 1.0 + z * z / n
    center = p + z * z / (2.0 * n)
    spread = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (center - spread) / denominator)


def geometry_stats(metrics: list[dict], pocket: Pocket, start: datetime, end: datetime) -> dict:
    result = evaluate_pocket(metrics, pocket, start, end)
    stop, target = next((stop, target) for stop, target in GEOMETRIES
                        if f"sl{stop:g}_tp{target:g}" == pocket.geometry)
    rows = sequential_rows([row for row in metrics
                             if start <= parse_dt(row["timestamp"]) < end
                             and matches(row, pocket)], pocket.horizon)
    wins = sum(row["target_before_stop"].get(pocket.geometry, False) for row in rows)
    lower = wilson_lower(wins, len(rows))
    break_even = stop / (stop + target)
    return {**result, "target_rate": round(wins / len(rows), 6) if rows else 0.0,
            "target_lower_bound": round(lower, 6), "break_even_rate": round(break_even, 6),
            "calibration_margin": round(lower - break_even, 6)}


def _calibration_score(stats: dict) -> tuple[float, float, float, int]:
    return (stats["calibration_margin"], stats["mean_r"], -stats["max_drawdown_r"], stats["n"])


def fit_original(metrics: list[dict], start: datetime, end: datetime, min_samples: int) -> list[dict]:
    return [{"pocket": asdict(pocket), "fit": {
        "n": pocket.n, "mean_r": pocket.expectancy_r,
        "target_rate": pocket.target_rate, "geometry_source": "opportunity-map-discovery",
    }} for pocket in discover(metrics, start, end, min_samples).values()]


def fit_calibrated(metrics: list[dict], start: datetime, end: datetime,
                   min_samples: int, portfolio_size: int | None = None) -> list[dict]:
    discovered = discover(metrics, start, end, min_samples)
    by_setup: dict[tuple, list[Pocket]] = defaultdict(list)
    for pocket in discovered.values():
        by_setup[setup_key(pocket)].append(pocket)
    candidates: list[dict] = []
    for setup, pockets in by_setup.items():
        base = pockets[0]
        options: list[tuple[tuple, Pocket, dict]] = []
        for stop, target in GEOMETRIES:
            geometry = f"sl{stop:g}_tp{target:g}"
            candidate = Pocket(base.context, base.regime, base.m32_bin,
                               base.efficiency_bin, base.distance_bin, base.direction,
                               base.horizon, geometry, base.n, base.expectancy_r, base.target_rate)
            stats = geometry_stats(metrics, candidate, start, end)
            if stats["n"] >= min_samples:
                options.append((_calibration_score(stats), candidate, stats))
        if options:
            _, pocket, stats = max(options, key=lambda item: item[0])
            calibrated = Pocket(pocket.context, pocket.regime, pocket.m32_bin,
                                pocket.efficiency_bin, pocket.distance_bin, pocket.direction,
                                pocket.horizon, pocket.geometry, stats["n"],
                                stats["mean_r"], stats["target_rate"])
            candidates.append({"pocket": asdict(calibrated), "fit": {
                **stats, "geometry_source": "prior-only-wilson-calibration",
                "setup": list(setup)}})
    return candidates[:portfolio_size] if portfolio_size is not None else candidates


def fit_policies(metrics: list[dict], start: datetime, end: datetime,
                 min_samples: int = 20, portfolio_size: int = 8) -> dict[str, list[dict]]:
    return {POLICY_ORIGINAL: fit_original(metrics, start, end, min_samples),
            POLICY_CALIBRATED: fit_calibrated(metrics, start, end, min_samples,
                                               portfolio_size)}


def score_policies(metrics: list[dict], fitted: dict[str, list[dict]],
                   long_start: datetime, validation_start: datetime,
                   validation_end: datetime, recent_weight: float = 0.65,
                   min_validation_samples: int = 3) -> dict[str, list[dict]]:
    return {policy: score_candidates(
        metrics,
        {pocket_key(Pocket(**item["pocket"])): Pocket(**item["pocket"])
         for item in fitted[policy]},
        long_start, validation_start, validation_end, recent_weight,
        min_validation_samples,
    ) for policy in POLICIES}


def validation_stress_results(metrics_by_multiplier: dict[float, list[dict]],
                              portfolios: dict[str, list[dict]], start: datetime,
                              end: datetime, health_loss_streak: int = 3) -> dict[str, list[dict]]:
    return {policy: [evaluate_frozen_portfolio(rows, portfolios[policy], start, end,
                                               health_loss_streak)
                     for _, rows in sorted(metrics_by_multiplier.items())]
            for policy in POLICIES}


def policy_score(result: dict, min_validation_trades: int,
                 stress_results: list[dict] | None = None) -> tuple[float, float, float]:
    all_results = [result, *(stress_results or [])]
    if any(item["n"] < min_validation_trades or item["mean_r"] <= 0.0
           for item in all_results):
        return (-math.inf, -math.inf, -math.inf)
    return (min(item["mean_r"] for item in all_results),
            -max(item["max_drawdown_r"] for item in all_results),
            min(item["n"] for item in all_results))


def choose_policy(validation: dict[str, dict], min_validation_trades: int = 3,
                  validation_stress: dict[str, list[dict]] | None = None) -> tuple[str | None, dict]:
    scores = {policy: policy_score(validation.get(policy, {"n": 0, "mean_r": 0.0,
                                                             "max_drawdown_r": 0.0}),
                                   min_validation_trades,
                                   (validation_stress or {}).get(policy))
              for policy in POLICIES}
    eligible = [policy for policy in POLICIES if math.isfinite(scores[policy][0])]
    if not eligible:
        winner = None
        reason = "no-policy-passed-validation-sample-gate"
    else:
        winner = max(eligible, key=lambda policy: scores[policy])
        reason = "selected-from-prior-validation-only"
    return winner, {"reason": reason,
                    "metric": "worst_validation_mean_r_then_worst_drawdown_then_min_n",
                    "scores": {policy: list(scores[policy]) for policy in POLICIES},
                    "eligible": eligible}


__all__ = ["POLICY_ORIGINAL", "POLICY_CALIBRATED", "POLICIES", "Pocket",
           "choose_policy", "fit_policies", "score_policies", "validation_stress_results",
           "evaluate_frozen_portfolio"]
