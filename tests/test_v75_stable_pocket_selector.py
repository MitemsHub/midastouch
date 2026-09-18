from __future__ import annotations

from scripts.v75_stable_pocket_selector import stable_candidates


def _row(timestamp: str, positive: bool) -> dict:
    geometry = "sl0.75_tp1.5"
    return {
        "timestamp": timestamp,
        "context": "REVERSAL",
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


def _report(rows: list[dict]) -> dict:
    return {"metrics": rows}


def test_stable_candidates_require_both_source_windows_positive() -> None:
    rows_a = [_row(f"2026-01-01T{hour:02d}:00:00+00:00", True) for hour in range(0, 6)]
    rows_b = [_row(f"2026-02-01T{hour:02d}:00:00+00:00", True) for hour in range(0, 6)]

    stable = stable_candidates(
        _report(rows_a), _report(rows_b),
        __import__("datetime").datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-01-01T06:00:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-02-01T00:00:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-02-01T06:00:00+00:00"),
        min_samples=2,
    )

    assert stable
    assert stable[0]["source_a"]["mean_r"] > 0
    assert stable[0]["source_b"]["mean_r"] > 0


def test_losing_source_window_removes_candidate() -> None:
    rows_a = [_row(f"2026-01-01T{hour:02d}:00:00+00:00", True) for hour in range(0, 6)]
    rows_b = [_row(f"2026-02-01T{hour:02d}:00:00+00:00", False) for hour in range(0, 6)]

    stable = stable_candidates(
        _report(rows_a), _report(rows_b),
        __import__("datetime").datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-01-01T06:00:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-02-01T00:00:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-02-01T06:00:00+00:00"),
        min_samples=2,
    )

    assert stable == []
