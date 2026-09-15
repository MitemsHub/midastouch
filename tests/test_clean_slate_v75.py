from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.clean_slate_v75 import (
    HealthState,
    PathOutcome,
    StrategyConfig,
    decision,
    path_outcome,
)


def _rows(closes: list[float]) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "t": start + timedelta(minutes=15 * index),
            "o": close,
            "h": close,
            "l": close,
            "c": close,
        }
        for index, close in enumerate(closes)
    ]


def test_path_outcome_prefers_stop_when_both_are_hit() -> None:
    rows = [
        {"c": 100.0, "h": 105.0, "l": 97.0},
    ]
    result = path_outcome(rows, 1, 100.0, 2.0, 4.0, 1, 0.0)
    assert isinstance(result, PathOutcome)
    assert result.reason == "STOP_AMBIG"
    assert result.r == -1.0


def test_negative_model_expectancy_is_no_trade() -> None:
    config = StrategyConfig(
        name="test",
        horizon=4,
        stop_atr=1.0,
        target_atr=2.0,
        min_efficiency=0.3,
        min_extension=0.18,
        reversal_distance=0.45,
    )
    stats = {("BULL", "CONTINUATION", 1): type("Stats", (), {
        "n": 20,
        "wins": 5,
        "sum_r": -5.0,
        "sum_favorable_r": 20.0,
    })()}
    signal = type("Signal", (), {
        "regime": "BULL",
        "hypothesis": "CONTINUATION",
        "direction": 1,
    })()
    ok, reason = decision(stats, signal, {}, config, 10.0, 1.0, HealthState([]))
    assert not ok
    assert reason == "negative-expected-r"
