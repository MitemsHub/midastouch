"""Pins for the measured-cost ranker.

The load-bearing tests are:

* ``test_representative_atr_falls_back_when_window_is_empty`` -- if restricting to a
  trading window selected no hours, returning 0.0 (or raising inside a mean of an
  empty sequence) would either report an infinite cost per R or crash the ranking.
  The fallback has to be explicit, and falsey-but-real values must not trip it.
* ``test_parse_window_reversed_range_is_still_the_whole_range`` -- ``"19-14"`` is a
  user typing the US session backwards; silently producing an empty hour set would
  make every instrument look identical.
* ``test_select_hours_never_invents_hours`` -- hours absent from the measurement
  must stay absent, because a missing spread hour must not be treated as free.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import upcomers_cost_rank as rank  # noqa: E402


# --------------------------------------------------------------------------- #
# Window parsing
# --------------------------------------------------------------------------- #


def test_parse_window_all_means_no_filter():
    assert rank.parse_window("all") is None
    assert rank.parse_window("") is None
    assert rank.parse_window("*") is None


def test_parse_window_range_is_inclusive():
    assert rank.parse_window("14-19") == [14, 15, 16, 17, 18, 19]


def test_parse_window_reversed_range_is_still_the_whole_range():
    assert rank.parse_window("19-14") == [14, 15, 16, 17, 18, 19]


def test_parse_window_mixed_list_is_deduped_and_sorted():
    assert rank.parse_window("15,14,14-16") == [14, 15, 16]


def test_parse_window_rejects_out_of_range_hours():
    with pytest.raises(ValueError):
        rank.parse_window("24")
    with pytest.raises(ValueError):
        rank.parse_window("13-25")


# --------------------------------------------------------------------------- #
# Hour selection
# --------------------------------------------------------------------------- #


def test_select_hours_never_invents_hours():
    by_hour = {14: 100.0, 15: 200.0, 3: 50.0}
    assert rank.select_hours(by_hour, [14, 15, 16]) == {14: 100.0, 15: 200.0}


def test_select_hours_none_keeps_everything():
    by_hour = {0: 1.0, 23: 2.0}
    assert rank.select_hours(by_hour, None) == by_hour


# --------------------------------------------------------------------------- #
# Mean / representative values
# --------------------------------------------------------------------------- #


def test_mean_or_none_is_none_not_zero_when_empty():
    """0.0 would mean 'free', which is a very different claim from 'unknown'."""
    assert rank.mean_or_none([]) is None
    assert rank.mean_or_none([None]) is None
    assert rank.mean_or_none([2.0, 4.0]) == pytest.approx(3.0)


def test_representative_atr_uses_the_window():
    atr = {14: 100.0, 15: 300.0, 3: 10.0}
    assert rank.representative_atr(atr, [14, 15]) == pytest.approx(200.0)


def test_representative_atr_falls_back_when_window_is_empty():
    atr = {14: 100.0, 15: 300.0}
    assert rank.representative_atr(atr, [1, 2]) == pytest.approx(200.0)


def test_representative_atr_is_none_when_nothing_measured():
    assert rank.representative_atr({}, [14]) is None


def test_representative_spread_uses_the_window_and_falls_back():
    sprd = {14: 1.0, 15: 3.0, 2: 99.0}
    assert rank.representative_spread_bps(sprd, [14, 15]) == pytest.approx(2.0)
    assert rank.representative_spread_bps(sprd, [7]) == pytest.approx(34.3333333)


# --------------------------------------------------------------------------- #
# Sizing feasibility -- the filter that disqualifies the cheapest instrument
# --------------------------------------------------------------------------- #


def test_jpcjpy_minimum_position_exceeds_a_75_dollar_budget():
    """The Nikkei regression pin, off the venue's real specs.

    contract 100, tick_size 0.01, tick_value 0.0063736, volume_min **1.0** and ATR
    327.77: one lot risks ~$208.91, i.e. 2.8x a $75 per-trade budget. It is the
    cheapest instrument on the venue by cost per R and it cannot be traded at this
    risk. Both facts are true at once, which is exactly why this guard exists.
    """
    lots, realized, why = rank.size_lots(
        risk_usd=75.0, atr_price=327.77, tick_size=0.01,
        tick_value=0.006373648786457272, volume_min=1.0, volume_step=1.0)
    assert lots is None and realized is None
    assert "cannot be sized" in why and "2.8x" in why


def test_xauusd_sizes_almost_exactly_at_the_target():
    """Gold's granularity is why it wins the tie-break: 0.01-lot steps are $2.30 of
    risk, so the realised risk lands within 1.5% of target."""
    lots, realized, why = rank.size_lots(
        risk_usd=75.0, atr_price=23.04, tick_size=0.01,
        tick_value=0.1, volume_min=0.01, volume_step=0.01)
    assert why == "" and lots == pytest.approx(0.33)
    assert realized == pytest.approx(76.03, abs=0.05)
    assert abs(realized - 75.0) / 75.0 < 0.015


def test_nasdaq_granularity_is_coarser_than_gold():
    """0.01 lots of NACUSD.c is $9.88 of risk, so the same budget quantises worse."""
    _, gold, _ = rank.size_lots(75.0, 23.04, 0.01, 0.1, 0.01, 0.01)
    _, nas, _ = rank.size_lots(75.0, 98.85, 0.01, 0.1, 0.01, 0.01)
    assert abs(gold - 75.0) < abs(nas - 75.0)


def test_sizing_never_returns_a_position_below_the_minimum():
    lots, _, why = rank.size_lots(1.0, 23.04, 0.01, 0.1, 0.01, 0.01)
    assert lots is None and "cannot be sized" in why


def test_sizing_rejects_degenerate_specs():
    assert rank.size_lots(75.0, 23.04, 0.0, 0.1, 0.01, 0.01)[0] is None
    assert rank.size_lots(0.0, 23.04, 0.01, 0.1, 0.01, 0.01)[0] is None


# --------------------------------------------------------------------------- #
# Gap veto
# --------------------------------------------------------------------------- #


def test_gap_veto_uses_the_adverse_side_only():
    """A favourable gap is a windfall; only the adverse one can hurt."""
    gaps = {"worst_adverse_gap_pct": -1.42, "worst_favourable_gap_pct": 1.359}
    # ATR 108.81 on a 29,624 price is a 0.367% stop, so 1.42% is ~3.9 stops.
    assert rank.gap_veto_multiple(gaps, 108.81, 29_624.25) == pytest.approx(3.87, abs=0.02)


def test_gap_veto_returns_none_without_evidence():
    assert rank.gap_veto_multiple({}, 1.0, 100.0) is None
    assert rank.gap_veto_multiple({"worst_adverse_gap_pct": -1.0}, 0.0, 100.0) is None


def test_a_wider_stop_makes_a_gap_safer():
    """The sizing basis and the veto basis must be the same ATR.

    Doubling the ATR doubles the stop distance in percent, which halves the breach
    multiple. This is why filtering trades into a volatile window (larger ATR) makes
    the SAME gap less dangerous -- and why a veto quoted off a quiet-hour ATR would
    overstate the danger of a strategy that only trades the loud hours.
    """
    gaps = {"worst_adverse_gap_pct": -1.42}
    tight = rank.gap_veto_multiple(gaps, 108.81, 29_624.25)
    wide = rank.gap_veto_multiple(gaps, 217.62, 29_624.25)
    assert tight is not None and wide is not None
    assert wide == pytest.approx(tight / 2)


# --------------------------------------------------------------------------- #
# Bad-data rejection -- the guard that stops a broken feed ranking as "cheap"
# --------------------------------------------------------------------------- #


def test_zero_atr_is_rejected_not_ranked():
    """EURUSD regression pin.

    With current daily bars but a flat H1 stub, EURUSD measured ``atr=0.00`` and
    still produced a plausible-looking 0.130R, which would have ranked it 8th of 10
    ahead of nothing useful and behind nothing meaningful. A zero ATR must be a
    loud exclusion, never a number.
    """
    assert rank.reject_reason(0.0, 1.1483, 0.0) is not None
    assert rank.reject_reason(None, 1.1483, 0.0) is not None


def test_sub_epsilon_atr_is_called_a_stub():
    reason = rank.reject_reason(1e-9, 100.0, 0.0)
    assert reason is not None and "bad-data stub" in reason


def test_stale_h1_history_is_rejected():
    reason = rank.reject_reason(0.5, 100.0, rank.STALE_H1_DAYS + 1)
    assert reason is not None and "H1 history" in reason


def test_a_healthy_instrument_is_not_rejected():
    assert rank.reject_reason(108.81, 29_624.25, 0.5) is None


def test_missing_price_is_rejected():
    assert rank.reject_reason(0.5, 0.0, 0.0) is not None


def test_flat_stub_bars_are_rejected():
    """EURUSD regression pin, second attempt.

    Its ATR cleared the fraction-of-price floor, so the ratio guard alone let it
    rank. The bars themselves are the honest evidence: a stub series is
    open == high == low == close on every bar.
    """
    stub = [{"hour": h, "high": 1.1, "low": 1.1, "prev_close": 1.1} for h in range(6)]
    assert rank.bar_activity(stub) == 0.0
    reason = rank.reject_reason(1.2e-5, 1.15, 0.0, activity=rank.bar_activity(stub))
    assert reason is not None and "flat stub" in reason


def test_real_bars_have_high_activity():
    real = [{"hour": h, "high": 10.0 + h, "low": 9.0 + h, "prev_close": 9.5 + h}
            for h in range(10)]
    assert rank.bar_activity(real) == pytest.approx(1.0)
    assert rank.reject_reason(1.0, 100.0, 0.0, activity=1.0, spread_bps=1.5) is None


def test_implausible_spread_is_rejected():
    """INCUSD.c regression pin: 1067 bps off a 0.09 price is a broken basis."""
    reason = rank.reject_reason(1.0, 0.09, 0.0, activity=1.0, spread_bps=1067.2)
    assert reason is not None and "price basis" in reason


def test_normal_spreads_are_not_rejected():
    assert rank.reject_reason(1.0, 100.0, 0.0, activity=1.0, spread_bps=5.4) is None


# --------------------------------------------------------------------------- #
# The metric this whole script exists to produce
# --------------------------------------------------------------------------- #


def test_crypto_commission_dominates_a_tight_stop():
    """The finding that overturns the spread table.

    BTCUSD.nx has one of the tightest spreads on the venue (~0.35 bps) and is still
    a poor choice: commission at 0.04%/side against a ~0.6%-of-price stop costs far
    more than the spread does. This test pins the *shape* of that result so a future
    change to the commission model cannot quietly reverse it.
    """
    from midas_prop.risk.upcomers_rules import (
        CRYPTO,
        INDICES,
        CommissionSchedule,
        cost_per_r,
    )

    comm = CommissionSchedule()
    price, contract = 81_353.0, 0.1
    atr = price * 0.006  # a 0.6%-of-price stop: 1 ATR
    btc = cost_per_r(
        asset_class=CRYPTO, price=price, contract_size=contract,
        atr_price=atr, spread_price=2.81, stop_mult=1.0, commission=comm,
    )
    # Same volatility, zero commission, Nasdaq-like spread.
    index_like = cost_per_r(
        asset_class=INDICES, price=29_659.0, contract_size=10.0,
        atr_price=29_659.0 * 0.006, spread_price=3.5, stop_mult=1.0, commission=comm,
    )
    assert index_like == pytest.approx(3.5 / (29_659.0 * 0.006))
    assert btc > index_like * 3, "crypto's commission toll must dominate its spread"
    assert btc > 0.10, "a toll this large is the reason BTCUSD.nx is not the pick"
