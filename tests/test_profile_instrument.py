"""Pins for the instrument profiler.

The load-bearing tests are:

* ``test_best_window_wraps_midnight`` -- a session is circular and the US cash
  session the index actually trades in straddles a UTC boundary in some zones. A
  naive max-slice would miss it and silently recommend the wrong hours.
* ``test_gap_breach_multiple_is_how_many_stops_a_gap_covers`` -- this is the number
  that decides whether overnight holding is allowed at all, and it is the one risk
  a synthetic index never presented. If it were computed loosely, a stop-loss would
  be trusted where it cannot protect.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import profile_instrument as prof  # noqa: E402


# --------------------------------------------------------------------------- #
# True range, binned by hour
# --------------------------------------------------------------------------- #


def test_atr_by_hour_uses_true_range_not_just_the_bar():
    # high-low = 2.0, but the gap from prev_close makes TR = 5.0. TR must win.
    bars = [{"hour": 9, "high": 10.0, "low": 8.0, "prev_close": 5.0}]
    assert prof.atr_by_hour(bars) == {9: 5.0}


def test_atr_by_hour_averages_within_an_hour_across_days():
    bars = [
        {"hour": 9, "high": 10.0, "low": 8.0, "prev_close": 9.0},   # TR 2
        {"hour": 9, "high": 10.0, "low": 6.0, "prev_close": 9.0},   # TR 4
        {"hour": 10, "high": 10.0, "low": 9.0, "prev_close": 9.5},  # TR 1
    ]
    out = prof.atr_by_hour(bars)
    assert out[9] == pytest.approx(3.0)
    assert out[10] == pytest.approx(1.0)


def test_atr_by_hour_is_empty_safe():
    assert prof.atr_by_hour([]) == {}


# --------------------------------------------------------------------------- #
# Spread in bps (the only comparable form)
# --------------------------------------------------------------------------- #


def test_spread_is_normalised_to_basis_points_of_mid():
    # 2 points of spread on a 22000 index = 0.909 bps, not "2".
    out = prof.spread_bps_by_hour([{"hour": 14, "mid": 22000.0, "spread": 2.0}])
    assert out[14] == pytest.approx(2.0 / 22000.0 * 1e4)
    assert out[14] == pytest.approx(0.90909, abs=1e-4)


def test_spread_bps_skips_degenerate_quotes():
    out = prof.spread_bps_by_hour([
        {"hour": 3, "mid": 0.0, "spread": 1.0},      # no mid -> excluded
        {"hour": 3, "mid": 100.0, "spread": 0.5},
    ])
    assert out[3] == pytest.approx(50.0)


def test_quality_by_hour_is_movement_per_unit_of_cost():
    q = prof.quality_by_hour({9: 1.0}, {9: 1.0})
    assert q[9] == pytest.approx(1e4)


def test_quality_by_hour_omits_hours_with_no_spread_sample():
    """No spread sample is NOT the same as a free spread."""
    assert prof.quality_by_hour({9: 1.0}, {}) == {}


# --------------------------------------------------------------------------- #
# Session window
# --------------------------------------------------------------------------- #


def test_best_window_wraps_midnight():
    """A 4-hour session spanning 22:00-01:00 UTC must be found."""
    quality = {h: 1.0 for h in range(24)}
    for h in (22, 23, 0, 1):
        quality[h] = 100.0
    window, score = prof.best_window(quality, hours=4)
    assert window == [0, 1, 22, 23]
    assert score == pytest.approx(100.0)


def test_best_window_picks_the_genuine_best_block():
    quality = {h: 1.0 for h in range(24)}
    for h in (14, 15, 16):
        quality[h] = 50.0
    window, _ = prof.best_window(quality, hours=3)
    assert window == [14, 15, 16]


def test_best_window_is_empty_safe_and_clamps():
    assert prof.best_window({}) == ([], 0.0)
    # Asking for more hours than exist must not hang or raise.
    window, score = prof.best_window({1: 2.0, 2: 4.0}, hours=10)
    assert window == [1, 2] and score == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
# Gap behaviour -- the risk a synthetic index never had
# --------------------------------------------------------------------------- #


def _days(*rows):
    """rows are ``(open, close)`` or ``(open, close, weekday)``; default is Tue.

    The weekday is explicit rather than positional: an index-based fixture made
    row 1 a Tuesday while the test read it as a Monday, so the weekend test passed
    vacuously against the wrong day. Fixtures that encode meaning by position are
    how a green test stops meaning anything.
    """
    return [{"open": float(r[0]), "close": float(r[1]),
             "weekday": r[2] if len(r) > 2 else "Tue"}
            for r in rows]


def test_gap_stats_measures_the_overnight_jump():
    days = _days((100.0, 100.0), (102.0, 103.0))
    g = prof.gap_stats(days)
    assert g["n_days"] == 1
    assert g["abs_gap_max_pct"] == pytest.approx(2.0)
    assert g["worst_favourable_gap_pct"] == pytest.approx(2.0)
    assert g["worst_adverse_gap_pct"] == pytest.approx(2.0)


def test_gap_stats_captures_the_adverse_direction():
    days = _days((100.0, 100.0), (97.0, 96.0))
    g = prof.gap_stats(days)
    assert g["worst_adverse_gap_pct"] == pytest.approx(-3.0)
    assert g["worst_favourable_gap_pct"] == pytest.approx(-3.0)


def test_gap_stats_flags_weekend_gaps_separately():
    days = _days((100.0, 100.0, "Fri"), (105.0, 105.0, "Mon"))
    g = prof.gap_stats(days)
    assert g["n_weekend_gaps"] == 1
    assert g["worst_weekend_gap_pct"] == pytest.approx(5.0)


def test_a_midweek_gap_is_not_counted_as_a_weekend_gap():
    days = _days((100.0, 100.0, "Tue"), (105.0, 105.0, "Wed"))
    g = prof.gap_stats(days)
    assert g["n_days"] == 1
    assert g["n_weekend_gaps"] == 0
    assert g["worst_weekend_gap_pct"] == 0.0


def test_gap_stats_empty_safe():
    assert prof.gap_stats([]) == {}
    assert prof.gap_stats(_days((100.0, 100.0))) == {}


def test_gap_breach_multiple_is_how_many_stops_a_gap_covers():
    # A 3% gap against a 1% stop means the stop was filled three stops away.
    assert prof.gap_breach_multiple(-0.03, 0.01) == pytest.approx(3.0)
    assert prof.gap_breach_multiple(0.03, 0.01) == pytest.approx(3.0)
    with pytest.raises(ValueError):
        prof.gap_breach_multiple(0.03, 0.0)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def test_render_marks_the_chosen_window_and_survives_sparse_data():
    text = prof.render({9: 1.0}, {9: 0.5}, {9: 100.0}, [9], 100.0, {})
    assert " *" in text
    assert "best 1-hour window" in text
    # hours with no data must render as blanks, not raise
    assert "  23" in text


def test_render_includes_gap_section_when_present():
    text = prof.render({}, {}, {}, [], 0.0, {"abs_gap_max_pct": 1.5})
    assert "gap behaviour" in text
    assert "abs_gap_max_pct" in text
