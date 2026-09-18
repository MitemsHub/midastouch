from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from scripts.tick_clean_slate_v75 import (
    MAX_QUOTE_GAP_MS,
    TickPath,
    covers_window,
    tick_outcome,
)


def _path(prices: list[tuple[float, float]], step_ms: int = 1_000) -> TickPath:
    start = 1_700_000_000_000
    times = np.asarray([start + i * step_ms for i in range(len(prices))], dtype=np.int64)
    bids = np.asarray([bid for bid, _ in prices], dtype=float)
    asks = np.asarray([ask for _, ask in prices], dtype=float)
    return TickPath(
        times=times,
        bids=bids,
        asks=asks,
        median_spread=float(np.median(asks - bids)),
        first=datetime.fromtimestamp(times[0] / 1000, timezone.utc),
        last=datetime.fromtimestamp(times[-1] / 1000, timezone.utc),
        gap_count=0,
        max_gap_ms=step_ms,
    )


def _start() -> datetime:
    return datetime.fromtimestamp(1_700_000_000, timezone.utc)


def test_buy_uses_ask_entry_and_bid_exit() -> None:
    path = _path(
        [(100.0, 100.5)] + [(101.5, 102.0)] * 15 + [(102.5, 103.0)] * 15,
        60_000,
    )

    outcome = tick_outcome(path, 1, _start(), 2, 1.0, 2.0, 1.0)

    assert outcome is not None
    assert outcome.reason == "TARGET"
    assert outcome.r == 2.0


def test_sell_uses_bid_entry_and_ask_exit() -> None:
    path = _path(
        [(100.0, 100.5)] + [(98.5, 99.0)] * 15 + [(97.5, 98.0)] * 15,
        60_000,
    )

    outcome = tick_outcome(path, -1, _start(), 2, 1.0, 2.0, 1.0)

    assert outcome is not None
    assert outcome.reason == "TARGET"
    assert outcome.r == 2.0


def test_executable_tick_stop_is_deterministic() -> None:
    path = _path(
        [(100.0, 100.5)] + [(98.0, 101.5)] * 30,
        60_000,
    )

    outcome = tick_outcome(path, 1, _start(), 1, 1.0, 1.0, 1.0)

    assert outcome is not None
    assert outcome.reason == "STOP"
    assert outcome.r == -1.0


def test_large_quote_gap_fails_closed() -> None:
    path = _path([(100.0, 100.5), (101.0, 101.5)], MAX_QUOTE_GAP_MS + 1)

    outcome = tick_outcome(path, 1, _start(), 1, 1.0, 2.0, 1.0)

    assert outcome is None


def test_coverage_guard_reports_gap() -> None:
    path = _path([(100.0, 100.5), (101.0, 101.5)], MAX_QUOTE_GAP_MS + 1)
    end = _start() + timedelta(seconds=180)

    assert not covers_window(path, _start(), end)
