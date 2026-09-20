"""Pins for the simulated broker behind the paper trader.

WHY THE SEMANTICS ARE THE TEST. A paper account is only worth running if it is at
least as pessimistic as the venue. Two choices decide that, and both are the kind of
detail that silently flatters a result if it drifts:

* when a bar gaps past a barrier, the fill is the **open**, not the barrier;
* when both barriers sit inside one bar, the **stop** is assumed first.

They are the same rules the research harness uses. If they ever diverge, a paper run
stops being comparable to the backtest it is supposed to confirm — so they are pinned
here rather than left to inspection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from synthetic_trader.execution.paper_broker import (  # noqa: E402
    CostModel,
    PaperAccount,
    SimPosition,
)

FREE = CostModel(spread_bps=0.0, commission_per_lot_rt=0.0,
                 usd_per_unit_per_lot=100.0)
COSTLY = CostModel(spread_bps=1.073, commission_per_lot_rt=10.0,
                   usd_per_unit_per_lot=100.0)


def long(**kw) -> SimPosition:
    base = dict(direction=1, lots=0.1, entry=2000.0, stop=1990.0, target=2020.0,
                risk_usd=100.0, opened_utc="2026-09-19T10:00:00+00:00")
    base.update(kw)
    return SimPosition(**base)


def bar(account: PaperAccount, *, h: float, l: float, o: float = 2000.0,
        c: float = 2000.0, ts: int = 1) -> object:
    """One bar. The open defaults to the entry price, NOT to the low.

    Defaulting it to the low would trip the gap rule on every bar for a long, which
    is how the first version of this helper made three passing tests fail while the
    engine was correct.
    """
    return account.on_bar(high=h, low=l, close=c, open_=o,
                          ts=ts, ts_utc="2026-09-19T10:15:00+00:00")


class TestExitSemantics:
    def test_target_hit_fills_at_the_target(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        fill = bar(acc, h=2025.0, l=1995.0)
        assert fill.exit == 2020.0 and fill.exit_reason == "target"
        assert fill.gross_usd == pytest.approx(200.0)  # 20.0 x 0.1 x 100

    def test_stop_hit_fills_at_the_stop(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        fill = bar(acc, h=2005.0, l=1985.0)
        assert fill.exit == 1990.0 and fill.exit_reason == "stop"
        assert fill.gross_usd == pytest.approx(-100.0)

    def test_both_barriers_in_one_bar_assumes_the_stop(self):
        """The pessimistic reading: it cannot flatter the result."""
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        fill = bar(acc, h=2025.0, l=1985.0)
        assert fill.exit_reason == "stop" and fill.net_usd < 0

    def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        fill = bar(acc, h=1995.0, l=1970.0, o=1980.0)
        assert fill.exit == 1980.0 and fill.exit_reason == "gap_stop"
        assert fill.net_usd == pytest.approx(-200.0), "worse than the stop, as it would be"

    def test_a_short_stops_upward(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long(direction=-1, stop=2010.0, target=1980.0))
        fill = bar(acc, h=2015.0, l=1995.0, o=2000.0)
        assert fill.exit == 2010.0 and fill.exit_reason == "stop"

    def test_no_fill_while_inside_the_bracket(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        assert bar(acc, h=2010.0, l=1995.0) is None
        assert acc.position is not None


class TestCosts:
    def test_costs_reduce_a_winning_trade(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=COSTLY)
        acc.open(long())
        fill = bar(acc, h=2025.0, l=1995.0)
        assert fill.net_usd < fill.gross_usd
        assert fill.cost_usd == pytest.approx(1.073 / 1e4 * 2000.0 * 0.1 * 100
                                              + 10.0 * 0.1)

    def test_a_winning_gross_can_be_a_losing_net(self):
        """Realism check: costs are not decoration."""
        acc = PaperAccount(starting_balance=10_000.0, cost_model=COSTLY)
        # A target only 0.2 price units away earns $2 gross on 0.1 lots, while the
        # round trip costs ~$3.15 -- so the trade WINS and still loses money.
        acc.open(long(stop=1999.0, target=2000.2, risk_usd=10.0))
        fill = bar(acc, h=2000.5, l=1999.5)
        assert fill.gross_usd == pytest.approx(2.0)
        assert fill.net_usd < 0, "a winner that costs more than it earns"

    def test_net_r_is_relative_to_the_risk_that_was_sized(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long(risk_usd=100.0))
        fill = bar(acc, h=2025.0, l=1995.0)
        assert fill.net_r == pytest.approx(2.0)


class TestBookkeeping:
    def test_only_one_position_at_a_time(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        with pytest.raises(RuntimeError, match="one.*position at a time"):
            acc.open(long())

    def test_balance_moves_only_on_a_completed_fill(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        assert acc.balance == 10_000.0
        bar(acc, h=2005.0, l=1995.0)
        assert acc.balance == 10_000.0, "an open position is not realised P&L"
        bar(acc, h=2025.0, l=1995.0, ts=2)
        assert acc.balance == pytest.approx(10_200.0)

    def test_equity_marks_the_open_position(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        assert acc.equity(2005.0) == pytest.approx(10_050.0)
        assert acc.equity(2005.0) != acc.balance, "the rules read equity, not balance"

    def test_realised_since_filters_by_exit_time(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        bar(acc, h=2025.0, l=1995.0)
        assert acc.realised_since("2026-09-19T10:00:00+00:00") == pytest.approx(200.0)
        assert acc.realised_since("2026-09-19T11:00:00+00:00") == 0.0

    def test_restore_round_trips_position_and_history(self):
        acc = PaperAccount(starting_balance=10_000.0, cost_model=FREE)
        acc.open(long())
        bar(acc, h=2025.0, l=1995.0)
        acc.open(long(entry=2001.0))
        back = PaperAccount.restore(acc.snapshot(), FREE)
        assert back.balance == acc.balance
        assert len(back.closed) == 1
        assert back.position is not None and back.position.entry == 2001.0

    def test_an_impossible_position_is_rejected_at_construction(self):
        with pytest.raises(ValueError):
            long(direction=0)
        with pytest.raises(ValueError):
            long(lots=0.0)


class TestStopLevelsWarnAboutSingleShotDays:
    """Found on the first live paper run: the defaults allowed 1.02 attempts."""

    def test_defaults_are_a_single_shot_day(self):
        from synthetic_trader.execution.prop_execution import DailyStopConfig
        from synthetic_trader.risk.upcomers_rules import (
            ThunderboltClassicRules,
        )
        rules = ThunderboltClassicRules(account_size=25_000.0)
        cfg = DailyStopConfig()
        per_trade = 0.5 * rules.daily_loss_limit_usd
        assert cfg.attempts_allowed(rules, per_trade) <= 1.05

    def test_a_wider_stop_allows_more_attempts(self):
        from synthetic_trader.execution.prop_execution import DailyStopConfig
        from synthetic_trader.risk.upcomers_rules import (
            ThunderboltClassicRules,
        )
        rules = ThunderboltClassicRules(account_size=25_000.0)
        assert DailyStopConfig(loss_stop_fraction=0.9).attempts_allowed(
            rules, 375.0) == pytest.approx(1.8)

    def test_zero_risk_is_rejected(self):
        from synthetic_trader.execution.prop_execution import DailyStopConfig
        from synthetic_trader.risk.upcomers_rules import (
            ThunderboltClassicRules,
        )
        with pytest.raises(ValueError):
            DailyStopConfig().attempts_allowed(
                ThunderboltClassicRules(account_size=25_000.0), 0.0)
