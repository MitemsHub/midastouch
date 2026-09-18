from __future__ import annotations

import numpy as np

from scripts.v75_opportunity_map import _context, _target_flags, summarize


def test_target_before_stop_is_path_ordered() -> None:
    reachable, before_stop = _target_flags(np.asarray([0.2, 1.6]), 1, 0.75, 1.5)
    assert reachable is True
    assert before_stop is True

    reachable, before_stop = _target_flags(np.asarray([-0.8, 1.6]), 1, 0.75, 1.5)
    assert reachable is True
    assert before_stop is False


def test_context_separates_continuation_and_reversal() -> None:
    continuation = {
        "m8": 0.5, "m16": 0.6, "m32": 0.8,
        "slope": 0.4, "efficiency": 0.7, "distance": 0.1,
    }
    assert _context(continuation, "BULL") == "CONTINUATION"

    reversal = {
        "m8": -0.4, "m16": 0.2, "m32": 0.8,
        "slope": 0.1, "efficiency": 0.4, "distance": 0.7,
    }
    assert _context(reversal, "RANGE") == "REVERSAL"


def test_summary_marks_thin_groups() -> None:
    report = {
        "parameters": {"geometries": ((0.75, 1.5),)},
        "metrics": [{
            "context": "CONTINUATION", "regime": "BULL", "direction": 1, "horizon": 8,
            "target_before_stop": {"sl0.75_tp1.5": True},
            "target_reachable": {"sl0.75_tp1.5": True},
            "mfe_r": 2.0, "mae_r": -0.2, "horizon_r": 1.0,
            "spread": 16.0, "atr": 100.0,
        }],
    }

    result = summarize(report, min_samples=2)

    assert result["groups"][0]["enough_data"] is False
    assert result["groups"][0]["path_expectancy_r"] > 0
