from __future__ import annotations

from scripts.clean_slate_v75 import Signal, StrategyConfig
from scripts.tick_path_probability_v75 import (
    ProbabilityStats,
    _decision_for,
    choose_signal,
    wilson_lower,
)


CONFIG = StrategyConfig(
    name="test",
    horizon=12,
    stop_atr=1.0,
    target_atr=2.0,
    min_efficiency=0.3,
    min_extension=0.18,
    reversal_distance=0.45,
)


def test_wilson_bound_is_conservative_for_small_sample() -> None:
    assert wilson_lower(4, 4) < 0.8
    assert wilson_lower(60, 100) > wilson_lower(6, 10)


def test_probability_gate_rejects_high_raw_rate_without_sample() -> None:
    key = ("BULL", "CONTINUATION", 1)
    stats = {key: ProbabilityStats(4, 4, 8.0, 8.0, 0.0, 2.0)}

    decision = _decision_for(stats, Signal("CONTINUATION", 1, 1.0, "BULL"), CONFIG, 100.0, 10.0)

    assert not decision.accepted
    assert decision.reason == "insufficient-sample"


def test_probability_gate_requires_lower_bound_and_expectancy() -> None:
    key = ("BULL", "CONTINUATION", 1)
    stats = {key: ProbabilityStats(20, 18, -1.0, 10.0, -1.0, 1.0)}

    decision = _decision_for(stats, Signal("CONTINUATION", 1, 1.0, "BULL"), CONFIG, 100.0, 10.0)

    assert not decision.accepted
    assert decision.reason in {
        "probability-lower-bound-below-break-even",
        "negative-executable-expectancy",
    }


def test_choose_signal_returns_no_trade_when_hypotheses_are_too_close() -> None:
    continuation = Signal("CONTINUATION", 1, 1.0, "BULL")
    reversal = Signal("REVERSAL", -1, 1.0, "BULL")
    stats = {
        ("BULL", "CONTINUATION", 1): ProbabilityStats(40, 35, 30.0, 30.0, -1.0, 2.0),
        ("BULL", "REVERSAL", -1): ProbabilityStats(40, 35, 29.5, 30.0, -1.0, 2.0),
    }

    decision, runner = choose_signal(stats, [continuation, reversal], CONFIG, 100.0, 10.0)

    assert not decision.accepted
    assert decision.reason == "continuation-reversal-too-close"
    assert runner is not None


def test_choose_signal_accepts_clear_validated_winner() -> None:
    continuation = Signal("CONTINUATION", 1, 1.0, "BULL")
    reversal = Signal("REVERSAL", -1, 1.0, "BULL")
    stats = {
        ("BULL", "CONTINUATION", 1): ProbabilityStats(40, 39, 38.0, 50.0, -1.0, 2.0),
        ("BULL", "REVERSAL", -1): ProbabilityStats(40, 25, 5.0, 20.0, -1.0, 1.0),
    }

    decision, _ = choose_signal(stats, [continuation, reversal], CONFIG, 100.0, 10.0)

    assert decision.accepted
    assert decision.key == ("BULL", "CONTINUATION", 1)
