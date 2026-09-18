from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone

from scripts.v75_adaptive_router import evaluate_router, score_candidates
from scripts.v75_opportunity_selector import Pocket, evaluate_pocket


def _row(timestamp: str, positive: bool, context: str = "REVERSAL") -> dict:
    geometry = "sl0.75_tp1.5"
    return {
        "timestamp": timestamp,
        "context": context,
        "regime": "RANGE",
        "m32_bin": "0.15..0.75",
        "efficiency_bin": "0.35..0.50",
        "distance_bin": "0.45..0.75",
        "direction": -1,
        "horizon": 8,
        "target_before_stop": {geometry: positive},
        "target_reachable": {geometry: positive},
        "mfe_r": 2.0 if positive else 0.1,
        "mae_r": -0.2 if positive else -1.0,
        "horizon_r": 1.0 if positive else -1.0,
        "spread": 10.0,
        "atr": 100.0,
    }


def _pocket() -> Pocket:
    return Pocket("REVERSAL", "RANGE", "0.15..0.75", "0.35..0.50", "0.45..0.75", -1, 8, "sl0.75_tp1.5", 3, 1.0, 1.0)



def test_router_core_is_importable_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import scripts.v75_router_core"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_recent_validation_is_used_for_score() -> None:
    pocket = _pocket()
    rows = [_row(f"2026-01-01T{hour:02d}:00:00+00:00", True) for hour in range(6)]
    rows += [_row(f"2026-01-02T{hour:02d}:00:00+00:00", False) for hour in range(6)]
    scored = score_candidates(
        rows,
        {("key",): pocket},
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        recent_weight=0.8,
        min_validation_samples=1,
    )
    assert scored == []


def test_router_waits_for_horizon_between_entries() -> None:
    rows = [_row("2026-01-01T00:00:00+00:00", True),
            _row("2026-01-01T00:15:00+00:00", True),
            _row("2026-01-01T02:00:00+00:00", True)]
    result = evaluate_router(
        rows,
        [{"pocket": _pocket().__dict__}],
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 4, tzinfo=timezone.utc),
    )
    assert result["n"] == 2


def test_pocket_evaluation_orders_offset_timestamps_chronologically() -> None:
    rows = [
        _row("2026-01-01T00:00:00+02:00", True),
        _row("2025-12-31T23:30:00+00:00", False),
    ]
    pocket = _pocket()
    result = evaluate_pocket(
        rows,
        pocket,
        datetime(2025, 12, 31, 21, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert result["n"] == 1
    assert result["total_r"] == 2.0


def test_router_invalidates_family_after_closed_loss_streak() -> None:
    rows = [_row(f"2026-01-01T{hour:02d}:00:00+00:00", False)
            for hour in (0, 2, 4, 6)]
    result = evaluate_router(
        rows,
        [{"pocket": _pocket().__dict__}],
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
        health_loss_streak=3,
    )
    assert result["n"] == 3
    assert result["invalidated_families"] == ["REVERSAL|RANGE|-1"]
