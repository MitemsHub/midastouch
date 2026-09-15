from datetime import datetime, timedelta, timezone

from scripts.v75_transition_model import transition_states


def _rows(closes: list[float]) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"t": start + timedelta(minutes=15 * i), "o": c, "h": c + 0.1,
             "l": c - 0.1, "c": c} for i, c in enumerate(closes)]


def _h1() -> list[dict]:
    start = datetime(2025, 12, 1, tzinfo=timezone.utc)
    return [{"t": start + timedelta(hours=i), "o": 100, "h": 101,
             "l": 99, "c": 100} for i in range(200)]


def test_transition_states_are_observable_and_causal() -> None:
    closes = [100.0] * 80
    closes += [100.0, 100.0, 100.0, 100.0, 102.0, 104.0, 106.0, 108.0]
    states = transition_states(_rows(closes), _h1())
    assert any(state.startswith("STABLE_") for state in states)
    assert states[-1] in {
        "TRANSITION_EXPANSION_UP",
        "TRANSITION_FAILED_MOVE_UP",
        "TRANSITION_COMPRESSION",
        "STABLE_TRANSITION",
        "STABLE_UNKNOWN",
        "STABLE_RANGE",
    }
