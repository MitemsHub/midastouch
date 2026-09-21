"""Pins for the Upcomers Thunderbolt Classic rule pack and cost model.

The load-bearing tests here are:

* ``test_commission_classes_differ_by_more_than_eight_times`` -- the whole
  instrument-selection argument rests on a *published* cost difference of >8x
  between asset classes. If that gap were small, cost would not decide the
  instrument and this module would be incidental.
* ``test_drawdown_floor_locks_at_initial_balance`` -- the trailing shield stops
  rising once the account is 6% up, which is the only structural asymmetry the
  rule set hands us. A silent change in that behaviour changes every scaling
  decision downstream.
* ``test_cost_per_r_is_lot_independent`` -- if cost/R ever became size-dependent,
  the screen's ranking would be an artefact of a chosen lot size rather than a
  property of the instrument.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from midas_prop.risk.upcomers_rules import (  # noqa: E402
    CRYPTO,
    ENERGIES,
    FOREX,
    INDICES,
    METALS,
    STOCKS,
    CommissionSchedule,
    InstrumentCandidate,
    ThunderboltClassicRules,
    cost_per_r,
    documented_commission_bps,
    max_consecutive_losses,
    rank_candidates,
    risk_budget_usd,
)


# --------------------------------------------------------------------------- #
# Commission: the class gap
# --------------------------------------------------------------------------- #


def test_commission_classes_differ_by_more_than_eight_times():
    bps = documented_commission_bps()
    assert bps[INDICES] == bps[STOCKS] == bps[ENERGIES] == 0.0
    assert bps[METALS] < bps[FOREX] < bps[CRYPTO]
    assert bps[CRYPTO] / bps[FOREX] > 8.0


def test_crypto_commission_is_exactly_eight_bps_round_trip():
    """0.04% per side needs no price assumption -- it is a notional percentage."""
    bps = documented_commission_bps()
    assert bps[CRYPTO] == pytest.approx(8.0, abs=1e-9)


def test_free_classes_never_charge():
    comm = CommissionSchedule()
    for cls in (INDICES, STOCKS, ENERGIES):
        assert comm.round_trip_usd(cls, lots=7.0, price=6000.0, contract_size=1.0) == 0.0


def test_forex_and_metals_are_per_lot_not_per_notional():
    comm = CommissionSchedule()
    # $5/lot per side -> $10 round trip regardless of price.
    assert comm.round_trip_usd(FOREX, lots=2.0, price=1.10, contract_size=100_000.0) == 20.0
    assert comm.round_trip_usd(METALS, lots=2.0, price=2650.0, contract_size=100.0) == 20.0


def test_round_trip_multiplier_is_data_not_baked_in():
    """If a statement shows the published figure already covers both legs, 1.0."""
    per_side = CommissionSchedule(round_trip_multiplier=1.0)
    both = CommissionSchedule(round_trip_multiplier=2.0)
    a = per_side.round_trip_usd(CRYPTO, lots=1.0, price=100_000.0, contract_size=1.0)
    b = both.round_trip_usd(CRYPTO, lots=1.0, price=100_000.0, contract_size=1.0)
    assert b == pytest.approx(2 * a)


def test_unknown_asset_class_raises():
    with pytest.raises(ValueError):
        CommissionSchedule().cost_per_side_usd(
            "bonds", lots=1.0, price=1.0, contract_size=1.0
        )


# --------------------------------------------------------------------------- #
# Program rules
# --------------------------------------------------------------------------- #


def test_thunderbolt_classic_stated_limits():
    r = ThunderboltClassicRules(account_size=25_000.0)
    assert r.profit_target_usd == pytest.approx(1_250.0)  # 5%
    assert r.daily_loss_limit_usd == pytest.approx(750.0)  # 3%
    assert r.max_drawdown_usd == pytest.approx(1_500.0)  # 6%


def test_daily_reference_takes_the_higher_of_equity_and_balance():
    r = ThunderboltClassicRules()
    assert r.daily_reference_equity(26_000.0, 25_000.0) == 26_000.0
    assert r.daily_reference_equity(24_000.0, 25_000.0) == 25_000.0
    assert r.daily_loss_floor_usd(26_000.0, 25_000.0) == pytest.approx(25_250.0)


def test_drawdown_floor_locks_at_initial_balance():
    r = ThunderboltClassicRules(account_size=25_000.0)
    # At inception the floor sits 6% below the account size.
    assert r.drawdown_floor_usd(25_000.0) == pytest.approx(23_500.0)
    # Once 6% up, the floor has locked at the initial balance and stops rising.
    assert r.drawdown_floor_usd(26_500.0) == pytest.approx(25_000.0)
    assert r.drawdown_floor_usd(40_000.0) == pytest.approx(25_000.0)
    # A drawdown below the high-water mark never pushes the floor lower than
    # initial - 6%: the shield does not follow you down.
    assert r.drawdown_floor_usd(20_000.0) == pytest.approx(23_500.0)


def test_best_day_rule_is_twenty_percent():
    r = ThunderboltClassicRules()
    assert r.best_day_ok([50, 50, 50, 50, 50]) is True  # exactly 20%
    assert r.best_day_ok([100, 90, 85, 75]) is False  # 28.6%
    assert r.best_day_share([200, 100, 100]) == pytest.approx(0.5)
    # Not in profit -> no consistency exposure yet.
    assert r.best_day_share([-10, -20]) == 0.0
    assert r.best_day_ok([-10, -20]) is True


# --------------------------------------------------------------------------- #
# Risk budget
# --------------------------------------------------------------------------- #


def test_risk_budget_flags_the_unmodelled_single_trade_cap():
    r = ThunderboltClassicRules()
    budget, note = risk_budget_usd(r, equity=25_000.0, balance=25_000.0)
    assert budget == pytest.approx(750.0)
    assert "single-trade cap not modelled" in note


def test_risk_budget_takes_the_tighter_ceiling():
    r = ThunderboltClassicRules()
    budget, note = risk_budget_usd(
        r, equity=25_000.0, balance=25_000.0, single_trade_cap_pct=1.0
    )
    assert budget == pytest.approx(250.0)
    assert "single-trade 1% cap" in note


def test_risk_budget_safety_fraction_and_validation():
    r = ThunderboltClassicRules()
    budget, _ = risk_budget_usd(
        r, equity=25_000.0, balance=25_000.0, safety_fraction=0.25
    )
    assert budget == pytest.approx(187.5)
    with pytest.raises(ValueError):
        risk_budget_usd(r, equity=1.0, balance=1.0, safety_fraction=0.0)
    with pytest.raises(ValueError):
        risk_budget_usd(r, equity=1.0, balance=1.0, safety_fraction=1.5)


def test_loss_decay_within_the_daily_limit():
    r = ThunderboltClassicRules()
    assert max_consecutive_losses(r.daily_loss_limit_usd, 250.0) == 3
    assert max_consecutive_losses(r.max_drawdown_usd, 250.0) == 6
    with pytest.raises(ValueError):
        max_consecutive_losses(750.0, 0.0)


# --------------------------------------------------------------------------- #
# Cost per R
# --------------------------------------------------------------------------- #


def test_cost_per_r_worked_example_crypto():
    """BTCUSD.nx: $30 spread + $80 commission over a 1xATR($500) stop."""
    r = cost_per_r(
        asset_class=CRYPTO, price=100_000.0, contract_size=1.0,
        atr_price=500.0, spread_price=30.0, stop_mult=1.0,
        commission=CommissionSchedule(),
    )
    assert r == pytest.approx(0.22)


def test_cost_per_r_worked_example_forex():
    """EURUSD: 0.1-pip spread ($1) + $10 commission over a 1xATR(8 pip) stop."""
    r = cost_per_r(
        asset_class=FOREX, price=1.10, contract_size=100_000.0,
        atr_price=0.0008, spread_price=0.00001, stop_mult=1.0,
        commission=CommissionSchedule(),
    )
    assert r == pytest.approx(0.1375)


def test_quote_to_usd_prevents_a_usdjpy_rank_inversion():
    """The unit trap, using the venue's real USDJPY specs.

    1 lot is 100,000 USD and a 1xATR stop is 0.16 JPY, so the stop is worth
    100,000 x 0.16 = 16,000 JPY ~= $102 at 156.73. $10 of commission against that
    stop is ~0.098R on its own, so the honest toll is ~0.13R. The naive ratio adds
    USD commission to a JPY stop, understating it ~157x, which ranked USDJPY 6th of
    20 at a fictional 0.034R -- ahead of instruments it is genuinely dearer than.
    """
    comm = CommissionSchedule()
    fx = 1.0 / 156.73  # USD value of one JPY
    kwargs = dict(asset_class=FOREX, price=156.73, contract_size=100_000.0,
                  atr_price=0.16, spread_price=0.0055, stop_mult=1.0,
                  commission=comm)
    naive = cost_per_r(**kwargs)
    right = cost_per_r(**kwargs, quote_to_usd=fx)
    assert naive == pytest.approx(0.035, abs=0.002)
    assert right == pytest.approx(0.1323, abs=0.002)
    assert right > naive * 3


def test_quote_to_usd_leaves_usd_quoted_instruments_untouched():
    """The conversion must be a no-op for anything already quoted in USD."""
    comm = CommissionSchedule()
    args = dict(asset_class=INDICES, price=29_624.0, contract_size=10.0,
                atr_price=108.81, spread_price=3.5, stop_mult=1.0, commission=comm)
    assert cost_per_r(**args) == pytest.approx(cost_per_r(**args, quote_to_usd=1.0))


def test_quote_to_usd_rejects_degenerate_inputs():
    with pytest.raises(ValueError):
        cost_per_r(asset_class=CRYPTO, price=1.0, contract_size=1.0,
                   atr_price=1.0, spread_price=0.1, stop_mult=1.0,
                   commission=CommissionSchedule(), quote_to_usd=0.0)


def test_cost_per_r_is_lot_independent():
    """Both cost and stop scale with size, so the ratio must not move."""
    comm = CommissionSchedule()
    one = cost_per_r(
        asset_class=CRYPTO, price=100_000.0, contract_size=1.0,
        atr_price=500.0, spread_price=30.0, stop_mult=1.0, commission=comm,
    )
    lots = 5.0
    spread_usd = 30.0 * lots
    commission_usd = comm.round_trip_usd(
        CRYPTO, lots=lots, price=100_000.0, contract_size=1.0
    )
    stop_usd = 1.0 * 500.0 * lots
    assert (spread_usd + commission_usd) / stop_usd == pytest.approx(one)


def test_tighter_stop_makes_cost_r_worse_linearly():
    """The V75 lesson: halving the stop doubles the toll."""
    kwargs = dict(
        asset_class=CRYPTO, price=100_000.0, contract_size=1.0,
        atr_price=500.0, spread_price=30.0, commission=CommissionSchedule(),
    )
    wide = cost_per_r(stop_mult=2.0, **kwargs)
    tight = cost_per_r(stop_mult=1.0, **kwargs)
    assert tight == pytest.approx(2 * wide)


def test_cost_per_r_rejects_degenerate_inputs():
    with pytest.raises(ValueError):
        cost_per_r(asset_class=CRYPTO, price=1.0, contract_size=1.0,
                   atr_price=0.0, spread_price=0.0, stop_mult=1.0,
                   commission=CommissionSchedule())
    with pytest.raises(ValueError):
        cost_per_r(asset_class=CRYPTO, price=1.0, contract_size=1.0,
                   atr_price=1.0, spread_price=0.0, stop_mult=0.0,
                   commission=CommissionSchedule())


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #


def test_rank_candidates_orders_cheapest_first():
    candidates = [
        InstrumentCandidate("BTCUSD.nx", CRYPTO, 100_000.0, 1.0, 500.0, 30.0),
        InstrumentCandidate("XAUUSD", METALS, 2_650.0, 100.0, 12.0, 0.25),
        InstrumentCandidate("SPCUSD.c", INDICES, 6_000.0, 1.0, 15.0, 0.5),
    ]
    ranked = rank_candidates(candidates, stop_mult=1.0)
    order = [r.candidate.symbol for r in ranked]
    assert order[0] == "XAUUSD"
    assert order[-1] == "BTCUSD.nx"
    assert [r.cost_r for r in ranked] == sorted(r.cost_r for r in ranked)


def test_ranked_crypto_has_the_highest_commission_but_not_the_whole_cost():
    candidates = [
        InstrumentCandidate("BTCUSD.nx", CRYPTO, 100_000.0, 1.0, 500.0, 30.0),
        InstrumentCandidate("EURUSD", FOREX, 1.10, 100_000.0, 0.0008, 0.00001),
    ]
    ranked = {r.candidate.symbol: r for r in rank_candidates(candidates, stop_mult=1.0)}
    assert ranked["BTCUSD.nx"].commission_bps > ranked["EURUSD"].commission_bps
    # ...and crypto also pays the wider spread in bps.
    assert ranked["BTCUSD.nx"].spread_bps > ranked["EURUSD"].spread_bps
