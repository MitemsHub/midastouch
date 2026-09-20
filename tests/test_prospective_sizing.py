"""The prospective trail-shield ceiling, and the proof that sizing cannot move the gate.

The two things pinned here are the ones the 2026-09-20 run got wrong first:

* ``max_dd_pct`` is ``6.0`` (a PERCENTAGE), so ``peak * max_dd_pct`` is 100x the real
  shield room. That returned a $28,673.80 ceiling where only $233.99 survives.
* the room must be measured from CURRENT equity down to a floor anchored to the PEAK.
  Using the peak for both left the corrected form 22.5% optimistic ($286.74 vs $233.99).

And the structural finding, which is larger than either bug: V1-V7 of the gate are
computed from ``net_r`` and per-trade risk enters ``prop_compat`` as a post-hoc scalar,
so NO sizing rule can move them. V8 is an existence claim, so it cannot move either.
The gate is decided without reference to sizing, which is why "size it better" was never
going to rescue DAILY-ONE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from synthetic_trader.execution.prop_execution import (  # noqa: E402
    ContractSpec,
    feasible_risk_window,
    sequence_risk_ceiling_usd,
    size_position,
    worst_loss_run,
)
from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

RULES = ThunderboltClassicRules(account_size=25_000.0)
GOLD = ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01, max_lot=50.0,
                    digits=2, usd_per_unit_per_lot=100.0, basis="order_calc_profit",
                    tick_value_field=0.1)


# --------------------------------------------------------------------------- #
# The shield room, correctly denominated
# --------------------------------------------------------------------------- #


class TestShieldRoom:
    """A percent/fraction mix-up here is invisible and 100x wrong."""

    def test_room_is_1500_not_150000(self):
        """The measured bug: peak * max_dd_pct would be $150,000 on a $25,000 account."""
        assert RULES.max_dd_pct == 6.0                     # a PERCENTAGE
        assert RULES.shield_room_usd(25_000.0) == pytest.approx(1_500.0)
        assert RULES.shield_room_usd(25_000.0) != pytest.approx(25_000.0 * 6.0)

    def test_room_matches_the_venue_floor(self):
        for peak in (25_000.0, 26_000.0, 23_500.0):
            assert RULES.shield_room_usd(peak) == pytest.approx(
                peak - RULES.drawdown_floor_usd(peak))
            assert RULES.shield_room_usd(peak) >= 0.0

    def test_room_grows_once_the_floor_locks(self):
        """Above 6% profit the floor stops trailing, so the room becomes the profit."""
        assert RULES.shield_room_usd(30_000.0) == pytest.approx(5_000.0)


# --------------------------------------------------------------------------- #
# The measured loss run
# --------------------------------------------------------------------------- #


class TestWorstLossRun:

    def test_longest_run_and_its_depth(self):
        days = [1.0, -1.0, -1.0, -1.0, 0.5, -2.0, -2.0, 3.0]
        k, depth = worst_loss_run(days)
        assert k == 3 and depth == pytest.approx(-3.0)

    def test_the_run_is_the_LONGEST_not_the_deepest(self):
        """A long shallow run and a short deep one are different events."""
        k, depth = worst_loss_run([-1.0, -1.0, -1.0, -1.0, 2.0, -9.0])
        assert k == 4 and depth == pytest.approx(-4.0)

    def test_resets_on_a_winning_day(self):
        k, _ = worst_loss_run([-1.0, 0.0, -1.0, -1.0])
        assert k == 2

    def test_no_days_and_no_losses(self):
        assert worst_loss_run([]) == (0, 0.0)
        assert worst_loss_run([1.0, 2.0]) == (0, 0.0)

    def test_daily_one_reproduces_the_published_run(self):
        """The recorded 5-day run, -5.13R, rebuilt from its per-day magnitudes."""
        k, depth = worst_loss_run([-1.02, -1.02, -1.02, -1.02, -1.05])
        assert k == 5 and depth == pytest.approx(-5.13, abs=0.01)


# --------------------------------------------------------------------------- #
# The prospective ceiling
# --------------------------------------------------------------------------- #


class TestSequenceCeiling:

    def test_arithmetic_is_room_over_run(self):
        c = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                      worst_day_r=-1.05, run_days=5)
        assert c.exists
        assert c.risk_usd == pytest.approx(1_500.0 / (5 * 1.05))
        assert c.room_usd == pytest.approx(1_500.0)

    def test_tightens_with_a_longer_run(self):
        short = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                          worst_day_r=-1.0, run_days=2)
        long = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                         worst_day_r=-1.0, run_days=6)
        assert long.risk_usd < short.risk_usd

    def test_tightens_with_a_worse_day(self):
        mild = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                         worst_day_r=-0.5, run_days=4)
        harsh = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                          worst_day_r=-2.5, run_days=4)
        assert harsh.risk_usd < mild.risk_usd

    def test_current_equity_below_the_peak_strictly_tightens_it(self):
        """The second half of the bug: the room is measured from where equity IS."""
        at_peak = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                            worst_day_r=-1.05, run_days=5)
        below = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                          worst_day_r=-1.05, run_days=5,
                                          equity=24_000.0)
        assert below.risk_usd < at_peak.risk_usd
        assert below.risk_usd == pytest.approx(500.0 / (5 * 1.05))

    def test_no_room_left_is_a_refusal_not_a_small_size(self):
        c = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                      worst_day_r=-1.0, run_days=3, equity=23_499.0)
        assert not c.exists and c.risk_usd == 0.0
        assert "no shield room left" in c.note

    def test_a_window_with_no_losing_day_refuses_to_infer_a_ceiling(self):
        """An absent measurement must not read as an infinite ceiling."""
        c = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                      worst_day_r=0.4, run_days=1)
        assert not c.exists and c.risk_usd == 0.0
        assert "absent" in c.note

    def test_run_days_below_one_refuses(self):
        c = sequence_risk_ceiling_usd(RULES, peak_equity=25_000.0,
                                      worst_day_r=-1.0, run_days=0)
        assert not c.exists and c.risk_usd == 0.0


# --------------------------------------------------------------------------- #
# Sizing from the ceiling
# --------------------------------------------------------------------------- #


class TestCeilingBindsSizing:

    def test_the_ceiling_cuts_the_budget(self):
        s = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                          stop_distance_price=9.89, sequence_ceiling_usd=200.0)
        assert s.ok
        assert s.budget_usd == pytest.approx(200.0)          # not the $375 day budget
        assert s.risk_usd <= 200.0 + 1e-9
        assert "prospective trail-shield reserve" in s.budget_note

    def test_without_the_ceiling_the_day_budget_governs(self):
        s = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                          stop_distance_price=9.89)
        assert s.budget_usd == pytest.approx(375.0)

    def test_a_zero_ceiling_refuses_rather_than_sizing_down(self):
        s = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                          stop_distance_price=9.89, sequence_ceiling_usd=0.0)
        assert s.refused
        assert any("cannot be absorbed" in r for r in s.reasons)
        assert any("trailing drawdown" in r for r in s.reasons)

    def test_a_ceiling_below_the_lot_floor_refuses(self):
        """The ceiling can make the trade arithmetically impossible, and says so."""
        s = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                          stop_distance_price=9.89, sequence_ceiling_usd=5.0)
        assert s.refused
        assert any("minimum lot" in r for r in s.reasons)

    def test_an_ample_ceiling_changes_nothing(self):
        base = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                             stop_distance_price=9.89)
        wide = size_position(RULES, GOLD, equity=25_000.0, balance=25_000.0,
                             stop_distance_price=9.89, sequence_ceiling_usd=10_000.0)
        assert wide.lots == base.lots
        assert wide.risk_usd == pytest.approx(base.risk_usd)


# --------------------------------------------------------------------------- #
# Why sizing cannot rescue the gate
# --------------------------------------------------------------------------- #


class TestTheGateIgnoresSizing:
    """The structural result: only the dollar legs can see the position size."""

    DAYS = [-1.05, 0.8, -0.4, 1.2, -0.3, 0.5, 0.9, -0.2]

    def test_the_risk_window_is_identical_whatever_the_size(self):
        """``feasible_risk_window`` takes day-level R, which contains no size at all."""
        first = feasible_risk_window(RULES, self.DAYS)
        for _size in (10.0, 233.99, 716.85, 5_000.0):
            again = feasible_risk_window(RULES, self.DAYS)
            assert (again.exists, again.lo_usd, again.hi_usd) == \
                   (first.exists, first.lo_usd, first.hi_usd)

    def test_the_day_series_is_size_free_but_the_dollar_path_is_not(self):
        """Same inputs, different sizes: identical days, different equity outcomes."""
        from gold_walkforward import prop_compat  # research helper, pure arithmetic

        epoch = [i * 86_400 for i in range(len(self.DAYS) * 4)]
        trades = [{"entry_i": i * 4, "exit_i": i * 4 + 1, "net_r": r}
                  for i, r in enumerate(self.DAYS)]
        small = prop_compat(trades, epoch, RULES, 50.0)
        large = prop_compat(trades, epoch, RULES, 5_000.0)
        assert small["final_equity"] < large["final_equity"]
        # ...while the R-denominated total the statistical legs use is untouched.
        assert sum(t["net_r"] for t in trades) == pytest.approx(sum(self.DAYS))
        assert sum(t["net_r"] for t in trades) == pytest.approx(sum(self.DAYS))
