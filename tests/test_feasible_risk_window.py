"""Pins for the feasible risk-per-trade window.

WHY THE `exists` FLAG IS THE POINT. A gate leg that asks "does a legal size exist?" and
is implemented as "does the largest plausible size survive?" gets the wrong answer in
the one case that matters — which is exactly what happened on 2026-09-19, turning a PASS
into a FAIL. So the existence question and the bound are separate fields here, and both
are pinned, including the case where the window is non-empty but its upper end is not
survivable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from synthetic_trader.execution.prop_execution import (  # noqa: E402
    SINGLE_DAY_BOUND_CAVEAT,
    feasible_risk_window,
)
from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

RULES = ThunderboltClassicRules(account_size=25_000.0)


class TestTheWindowItself:
    def test_bounds_come_from_the_target_and_the_worst_day(self):
        w = feasible_risk_window(RULES, [3.0, 2.0, -1.0])
        assert w.exists is True
        assert w.lo_usd == pytest.approx(1250.0 / 4.0)
        assert w.hi_usd == pytest.approx(750.0 / 1.0)

    def test_existence_is_scale_invariant_though_the_bounds_are_not(self):
        """What scales is the R size, not the dollars-per-R.

        Scaling every day by 100 does NOT leave the window where it was — the target
        is fixed in dollars, so each R is worth 100x less and the bounds shrink by
        100. What survives scaling is the *existence* of a window, because it depends
        only on ``|worst|/total <= limit/target``. (Best Day's scale-invariance is a
        fact about the day SHARE, which is tested in `test_best_day_cap.py`; asserting
        it about this window would have been wrong, and was.)
        """
        a = feasible_risk_window(RULES, [3.0, 2.0, -1.0])
        b = feasible_risk_window(RULES, [300.0, 200.0, -100.0])
        assert a.exists is b.exists is True
        assert b.lo_usd == pytest.approx(a.lo_usd / 100.0)
        assert b.hi_usd == pytest.approx(a.hi_usd / 100.0)

    def test_existence_is_invariant_under_a_shift_in_scale_that_keeps_ratio(self):
        same = feasible_risk_window(RULES, [2.0, -0.5])
        scaled = feasible_risk_window(RULES, [20.0, -5.0])
        assert same.exists is scaled.exists is True

    def test_accepts_a_date_keyed_mapping(self):
        w = feasible_risk_window(RULES, {"2026-09-01": 3.0, "2026-09-02": -1.0})
        assert w.exists is True and w.total_r == pytest.approx(2.0)


class TestTheRefusals:
    def test_an_empty_window_is_reported_as_nonexistent(self):
        # A PROFITABLE window (+1R) whose worst day (-4R) is bigger than
        # limit/target = 0.6 of the total profit: the daily limit forbids every size
        # that could reach the target. Note the total must stay positive to reach
        # this branch -- a losing window is a different refusal (below).
        w = feasible_risk_window(RULES, [3.0, 2.0, -4.0])
        assert w.exists is False
        assert w.total_r > 0, "this branch is about a profitable but unsatisfiable window"
        assert w.lo_usd > w.hi_usd
        assert "EMPTY" in w.note

    def test_an_unprofitable_window_has_no_size_at_all(self):
        w = feasible_risk_window(RULES, [-5.0, -3.0])
        assert w.exists is False
        assert w.lo_usd == float("inf")
        assert "no profit" in w.note

    def test_no_days_is_a_refusal_not_an_empty_pass(self):
        w = feasible_risk_window(RULES, [])
        assert w.exists is False
        assert "no day-level results" in w.note

    def test_a_profit_only_window_has_an_unbounded_upper_end(self):
        """No losing day means the daily limit cannot bind -- reported, not special-cased."""
        w = feasible_risk_window(RULES, [2.0, 3.0])
        assert w.exists is True
        assert w.hi_usd == float("inf")


class TestTheCaveatIsAttachedWheneverItApplies:
    """The bound is optimistic; a caller must not read it as a survivable size."""

    def test_a_feasible_window_carries_the_trailing_shield_warning(self):
        w = feasible_risk_window(RULES, [3.0, 2.0, -1.0])
        assert w.note == SINGLE_DAY_BOUND_CAVEAT
        assert "OPTIMISTIC" in w.note

    def test_an_empty_window_still_carries_it(self):
        w = feasible_risk_window(RULES, [3.0, 2.0, -4.0])
        assert w.exists is False
        assert "optimistic ceiling" in w.note.lower()

    def test_the_daily_one_numbers_reproduce_the_measured_discrepancy(self):
        """The real case: window said $716.85, only $233.99 survived."""
        days = [1.0] * 12 + [-1.05] + [-0.5] * 2  # worst day -1.05R, total +10.45R
        w = feasible_risk_window(RULES, days)
        assert w.exists is True
        assert w.hi_usd == pytest.approx(750.0 / 1.05, rel=1e-6)
        assert w.hi_usd / 233.99 > 3.0, ("the single-day bound overstates the "
                                         "survivable size by ~3x, which is why the "
                                         "caveat exists")
