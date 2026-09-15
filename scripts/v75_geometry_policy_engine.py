"""Chronological fold engine for the research-only V75 policy selector."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from v75_geometry_policy import (
    POLICY_CALIBRATED,
    POLICY_ORIGINAL,
    POLICIES,
    choose_policy,
    fit_policies,
    score_policies,
    validation_stress_results,
)
from v75_router_core import evaluate_frozen_portfolio
from v75_geometry_policy_snapshot import (
    SnapshotIntegrityError,
    build_provenance,
    prepare_snapshot_inputs,
)


def run(
    metrics: list[dict],
    start: datetime,
    end: datetime,
    train_days: int = 30,
    validation_days: int = 10,
    test_days: int = 10,
    portfolio_size: int = 8,
    min_samples: int = 20,
    min_validation_trades: int = 3,
    health_loss_streak: int = 3,
    stress_metrics: dict[float, list[dict]] | None = None,
    *,
    map_snapshot: Mapping[str, Any] | Path | str | None = None,
    stress_snapshots: Mapping[float | str, Mapping[str, Any] | Path | str] | None = None,
    tick_file: Path | None = None,
    opportunity_map_snapshot: Mapping[str, Any] | Path | str | None = None,
    stress_map_snapshots: Mapping[float | str, Mapping[str, Any] | Path | str] | None = None,
) -> dict:
    """Fit, validate, freeze, and test each rolling policy fold."""
    if min(
        train_days, validation_days, test_days, portfolio_size,
        min_samples, min_validation_trades, health_loss_streak,
    ) <= 0:
        raise ValueError("all window, portfolio, sample, and health values must be positive")
    if map_snapshot is not None and opportunity_map_snapshot is not None:
        raise SnapshotIntegrityError("supply only one base map snapshot")
    if stress_snapshots is not None and stress_map_snapshots is not None:
        raise SnapshotIntegrityError("supply only one stress snapshot mapping")
    selected_map_snapshot = (
        opportunity_map_snapshot if opportunity_map_snapshot is not None else map_snapshot
    )
    selected_stress_snapshots = (
        stress_map_snapshots if stress_map_snapshots is not None else stress_snapshots
    )
    prepared = prepare_snapshot_inputs(
        metrics, start, end, stress_metrics, selected_map_snapshot,
        selected_stress_snapshots, tick_file,
    )

    folds: list[dict] = []
    cursor = start
    fold = 0
    while cursor + timedelta(days=train_days + validation_days + test_days) <= end:
        fold += 1
        train_end = cursor + timedelta(days=train_days)
        validation_start = train_end
        validation_end = validation_start + timedelta(days=validation_days)
        test_end = validation_end + timedelta(days=test_days)

        fitted = fit_policies(prepared.metrics, cursor, train_end, min_samples)
        scored = score_policies(
            prepared.metrics, fitted, cursor, validation_start, validation_end,
        )
        portfolios = {
            policy: scored[policy][:portfolio_size] for policy in POLICIES
        }
        validation = {
            policy: evaluate_frozen_portfolio(
                prepared.metrics, portfolios[policy], validation_start,
                validation_end, health_loss_streak,
            )
            for policy in POLICIES
        }
        validation_stress = validation_stress_results(
            prepared.stress_metrics, portfolios, validation_start,
            validation_end, health_loss_streak,
        )
        winner, selection = choose_policy(
            validation, min_validation_trades, validation_stress,
        )
        test_by_policy = {
            policy: evaluate_frozen_portfolio(
                prepared.metrics, portfolios[policy], validation_end,
                test_end, health_loss_streak,
            )
            for policy in POLICIES
        }
        folds.append({
            "fold": fold,
            "train_window": [cursor.isoformat(), train_end.isoformat()],
            "validation_window": [validation_start.isoformat(), validation_end.isoformat()],
            "test_window": [validation_end.isoformat(), test_end.isoformat()],
            "policy_fit": {
                policy: {
                    "discovered": len(fitted[policy]),
                    "gated": len(scored[policy]),
                    "portfolio": portfolios[policy],
                }
                for policy in POLICIES
            },
            "validation": validation,
            "validation_stress": validation_stress,
            "selection": {**selection, "winner": winner},
            "test": test_by_policy[winner] if winner else evaluate_frozen_portfolio(
                prepared.metrics, [], validation_end, test_end,
            ),
            "test_by_policy": test_by_policy,
        })
        cursor += timedelta(days=test_days)

    return {
        "schema": "mitemshub.v75.geometry-policy-selector.v2",
        "research_only": True,
        "order_submission": False,
        "selection": (
            "fit both policies on training; apply identical gates and prior cost stress; "
            "choose frozen winner on validation; evaluate untouched test"
        ),
        "policies": {
            POLICY_ORIGINAL: "existing adaptive-router geometry",
            POLICY_CALIBRATED: "prior-only Wilson geometry calibration on the same signal setups",
        },
        "isolation": {
            "fit_excludes": "validation and test windows",
            "selection_excludes": "test window",
            "test_is_frozen": True,
        },
        "parameters": {
            "train_days": train_days,
            "validation_days": validation_days,
            "test_days": test_days,
            "portfolio_size": portfolio_size,
            "min_samples": min_samples,
            "min_validation_trades": min_validation_trades,
            "health_loss_streak": health_loss_streak,
            "stress_multipliers": sorted(prepared.stress_metrics),
        },
        "provenance": build_provenance(
            prepared.metrics, prepared.stress_metrics, prepared.base_snapshot,
            prepared.stress_snapshots, start, end, train_days, validation_days,
            test_days, portfolio_size, min_samples, min_validation_trades,
            health_loss_streak, tick_file, prepared.base_source,
        ),
        "folds": folds,
    }


__all__ = ["run"]
