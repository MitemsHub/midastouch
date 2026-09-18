from datetime import datetime, timezone

from scripts.v75_opportunity_selector import Pocket, evaluate_pocket, select_pockets


def _row(timestamp: str, value: bool, r: float = 1.0) -> dict:
    return {
        "timestamp": timestamp,
        "context": "REVERSAL",
        "regime": "RANGE",
        "m32_bin": "0.15..0.75",
        "efficiency_bin": "0.35..0.50",
        "distance_bin": "0.45..0.75",
        "direction": -1,
        "horizon": 8,
        "target_before_stop": {"sl0.75_tp1.5": value},
        "target_reachable": {"sl0.75_tp1.5": value},
        "mfe_r": 2.0 if value else 0.1,
        "mae_r": -0.2 if value else -1.0,
        "horizon_r": r,
        "spread": 10.0,
        "atr": 100.0,
    }


def test_select_pockets_uses_only_prior_window() -> None:
    rows = [
        _row("2026-01-01T00:00:00+00:00", True),
        _row("2026-01-01T02:00:00+00:00", True),
        _row("2026-01-01T04:00:00+00:00", True),
    ]

    pockets = select_pockets(
        rows,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 6, tzinfo=timezone.utc),
        min_samples=2,
    )

    assert pockets
    assert pockets[0].n == 3


def test_evaluate_pocket_does_not_overlap_entries() -> None:
    pocket = Pocket("REVERSAL", "RANGE", "0.15..0.75", "0.35..0.50", "0.45..0.75", -1, 8, "sl0.75_tp1.5", 3, 1.0, 1.0)
    rows = [_row("2026-01-01T00:00:00+00:00", True),
            _row("2026-01-01T00:15:00+00:00", True),
            _row("2026-01-01T02:00:00+00:00", True)]

    result = evaluate_pocket(
        rows,
        pocket,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 4, tzinfo=timezone.utc),
    )

    assert result["n"] == 2
