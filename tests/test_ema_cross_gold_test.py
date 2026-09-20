"""Pins for the externally-specified 20/50 EMA cross evaluation.

The load-bearing tests are:

* ``test_cost_r_matches_the_measured_venue_toll`` -- the assessment's whole conclusion turns
  on the toll being priced correctly. Gold's lot is worth $100 per $1.00 move (verified with
  mt5.order_calc_profit); using the spec's `trade_tick_value` would be 10x wrong.
* ``test_cost_r_doubles_when_the_stop_halves`` -- cost per R scales as 1/stop, which is why a
  tighter stop makes a system worse, and why the carousel's omission of cost is not cosmetic.
* ``test_crosses_fire_once_per_actual_cross`` -- an off-by-one on the crossing test would
  either double-count or miss every signal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ema_cross_gold_test as em  # noqa: E402


def test_cost_r_matches_the_measured_venue_toll():
    """At a 1-ATR stop on ~$4,376 gold the toll is the documented 0.0247R."""
    atr = 23.04
    cost = em.cost_r_per_trade(entry_price=4376.26, stop_distance=atr)
    assert cost == pytest.approx(0.0247, abs=0.0005)


def test_cost_r_doubles_when_the_stop_halves():
    wide = em.cost_r_per_trade(4376.26, 23.04)
    tight = em.cost_r_per_trade(4376.26, 11.52)
    # The spread term doubles exactly; the commission term doubles too, so the ratio is
    # slightly above 2 because the fixed commission is a larger share of a tighter stop.
    assert tight / wide == pytest.approx(2.0, abs=0.02)
    assert tight < 0.13


def test_cost_is_never_negative_or_free():
    assert em.cost_r_per_trade(4376.26, 100.0) > 0


def test_crosses_fire_once_per_actual_cross():
    # Equality is NOT a cross: index 5 in the naive series [.,2.0] would read as ``2.0 > 2.0``
    # = False and silently drop the signal, so the fixture ends on a strict exceedance.
    fast = np.array([1.0, 2.0, 3.0, 2.0, 1.0, 3.0])
    slow = np.array([2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
    up, dn = em.crosses(fast, slow)
    assert list(up) == [False, False, True, False, False, True]
    assert list(dn) == [False, False, False, False, True, False]


def test_touching_the_slow_line_is_not_a_cross():
    fast = np.array([1.0, 2.0, 3.0])
    slow = np.array([2.0, 2.0, 2.0])
    up, dn = em.crosses(fast, slow)
    assert list(up) == [False, False, True]
    assert not dn.any()


def test_a_constant_series_never_crosses():
    flat = np.full(50, 5.0)
    up, dn = em.crosses(flat, flat)
    assert not up.any() and not dn.any()


def test_break_even_win_rate_is_the_inverse_of_1_plus_rr():
    """The one piece of the carousel's arithmetic that is correct, pinned as such."""
    assert 1.0 / (1.0 + em.REWARD_RISK) == pytest.approx(0.2857, abs=0.0001)


def test_the_system_constants_are_theirs_not_ours():
    assert (em.EMA_FAST, em.EMA_SLOW, em.REWARD_RISK) == (20, 50, 2.5)
