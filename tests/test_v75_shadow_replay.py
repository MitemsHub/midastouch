from __future__ import annotations

from datetime import datetime, timezone

from scripts.v75_adaptive_router import evaluate_router
from scripts.v75_shadow_replay import replay_window
from scripts.v75_opportunity_selector import Pocket


def _row(timestamp: str, positive: bool = True) -> dict:
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
        "mae_r": -0.2 if positive else -1.0,
        "horizon_r": 1.0 if positive else -1.0,
    }


def _selected() -> list[dict]:
    pocket = Pocket(
        "REVERSAL", "RANGE", "0.15..0.75", "0.35..0.50", "0.45..0.75",
        -1, 8, "sl0.75_tp1.5", 20, 1.0, 0.5,
    )
    return [{"pocket": pocket.__dict__}]


def _bounds() -> tuple[datetime, datetime]:
    return (
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 4, tzinfo=timezone.utc),
    )


def test_shadow_replay_waits_until_horizon_closes() -> None:
    rows = [
        _row("2026-01-01T00:00:00+00:00"),
        _row("2026-01-01T00:15:00+00:00"),
        _row("2026-01-01T02:00:00+00:00"),
    ]
    start, end = _bounds()
    decisions = replay_window(rows, _selected(), start, end, fold=1)

    assert [decision.action for decision in decisions] == ["SELL", "NO_TRADE", "SELL"]
    assert decisions[1].reason == "position_open"
    assert decisions[0].outcome == "TARGET"


def test_shadow_replay_invalidates_family_after_losses() -> None:
    rows = [
        _row("2026-01-01T00:00:00+00:00", False),
        _row("2026-01-01T02:00:00+00:00", False),
        _row("2026-01-01T04:00:00+00:00", False),
        _row("2026-01-01T06:00:00+00:00", True),
    ]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    decisions = replay_window(rows, _selected(), start, end, fold=2, health_loss_streak=3)

    assert [decision.action for decision in decisions] == ["SELL", "SELL", "SELL", "NO_TRADE"]
    assert decisions[-1].reason == "family_invalidated"


def test_shadow_replay_logs_no_trade_when_no_pocket_matches() -> None:
    start, end = _bounds()
    decisions = replay_window(
        [_row("2026-01-01T00:00:00+00:00", True)],
        [],
        start,
        end,
        fold=3,
    )

    assert decisions[0].action == "NO_TRADE"
    assert decisions[0].reason == "no_validated_pocket"


def test_shadow_replay_matches_router_total() -> None:
    rows = [
        _row("2026-01-01T00:00:00+00:00", True),
        _row("2026-01-01T00:15:00+00:00", False),
        _row("2026-01-01T02:00:00+00:00", True),
    ]
    start, end = _bounds()
    selected = _selected()
    decisions = replay_window(rows, selected, start, end, fold=4)
    router = evaluate_router(rows, selected, start, end)

    assert router["n"] == sum(decision.action in {"BUY", "SELL"} for decision in decisions)
    assert router["total_r"] == round(sum(decision.path_r for decision in decisions), 6)


def test_replay_and_router_order_offset_timestamps_chronologically() -> None:
    rows = [
        _row("2026-01-01T00:00:00+02:00", True),
        _row("2025-12-31T23:30:00+00:00", False),
    ]
    start = datetime(2025, 12, 31, 21, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    selected = _selected()

    router = evaluate_router(rows, selected, start, end)
    decisions = replay_window(rows, selected, start, end, fold=5)

    assert router["n"] == 1
    assert router["total_r"] == 2.0
    assert [(decision.timestamp, decision.action) for decision in decisions] == [
        ("2026-01-01T00:00:00+02:00", "SELL"),
        ("2025-12-31T23:30:00+00:00", "NO_TRADE"),
    ]
    assert decisions[1].reason == "position_open"
