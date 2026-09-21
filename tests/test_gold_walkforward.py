"""Pins for the pre-registered XAUUSD walk-forward.

The load-bearing tests are:

* ``test_trailing_percentile_ignores_the_future`` -- if the ATR band ever saw the
  whole series, the filter would select bars using information that did not exist at
  decision time. That is the single most likely way this harness could manufacture an
  edge, so it is pinned directly.
* ``test_last_closed_index_requires_the_bar_to_have_closed`` -- comparing a bar's OPEN
  time against the decision time lets a still-forming H1 bar inform an M15 signal.
* ``test_stop_is_assumed_first_when_both_sides_are_touched`` -- the pessimistic
  reading. If the harness assumed the target won that tie, every result would be
  overstated and nothing downstream would reveal it.
* ``test_gap_through_stop_fills_at_the_open`` -- a stop cannot fill at its own price
  when the market opens beyond it, and gold's gapX is 3.10.
* ``test_forced_flat_at_the_session_end`` -- the protocol forbids overnight holds
  because gold's swap mode is unverified; the harness must actually enforce it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gold_walkforward as gw  # noqa: E402


# --------------------------------------------------------------------------- #
# Synthetic bar construction
# --------------------------------------------------------------------------- #


def mk_bars(n: int = 700, *, atr_val: float = 10.0, hours: np.ndarray | None = None,
            start_hour: int = 12, trend: float = 1.0, vary_atr: bool = True):
    """Bars with a steady uptrend so the EMA alignment fires, plus a varying ATR.

    The ATR must VARY: with a constant ATR the trailing p20 equals p95, the band
    test ``p20 < atr <= p95`` can never pass, and every simulate() test would
    silently pass by producing no trades at all.
    """
    epoch = np.arange(n, dtype=float) * 900.0 + 1_767_000_000.0
    close = 2000.0 + trend * np.arange(n, dtype=float)
    atr = (atr_val + 2.0 * np.sin(np.arange(n, dtype=float) / 30.0)
           if vary_atr else np.full(n, atr_val))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + atr * 0.25
    low = np.minimum(open_, close) - atr * 0.25
    if hours is None:
        hours = np.full(n, start_hour, dtype=int)
    return ({"epoch": epoch, "open": open_, "high": high, "low": low,
             "close": close, "spread": np.full(n, 21.0), "volume": np.ones(n)},
            hours, atr)


def all_true(n: int, value: bool = True) -> np.ndarray:
    return np.full(n, value, dtype=bool)


def run(bars, hours, atr, cfg, *, start=0, end=None):
    n = len(bars["close"])
    return gw.simulate(bars, hours, all_true(n), all_true(n, False),
                       all_true(n), all_true(n, False), atr, cfg,
                       start=start, end=n if end is None else end)


# --------------------------------------------------------------------------- #
# Indicators and the two look-ahead traps
# --------------------------------------------------------------------------- #


def test_ema_of_a_constant_series_is_that_constant():
    out = gw.ema(np.full(50, 7.0), 10)
    assert out[-1] == pytest.approx(7.0)


def test_atr_is_nan_before_it_has_enough_bars():
    h = np.full(30, 2.0)
    l = np.full(30, 1.0)
    c = np.full(30, 1.5)
    out = gw.wilder_atr(h, l, c, 14)
    assert np.isnan(out[:14]).all()
    assert not np.isnan(out[14])


def test_trailing_percentile_ignores_the_future():
    """A future value must not be able to change a past output."""
    v = np.linspace(1.0, 100.0, 300)
    a = gw.trailing_percentile(v, window=50, pct=0.5)
    v2 = v.copy()
    v2[250:] *= 1000.0  # only the FUTURE is perturbed
    b = gw.trailing_percentile(v2, window=50, pct=0.5)
    assert np.allclose(a[:250], b[:250], equal_nan=True)


def test_last_closed_index_requires_the_bar_to_have_closed():
    """The bar at t=1000 opening at 1000 with a 3600s period is NOT closed at 1000."""
    epochs = np.array([0.0, 3600.0, 7200.0])
    assert gw.last_closed_index(epochs, 1000.0, 3600) == 0 - 1  # nothing closed yet
    assert gw.last_closed_index(epochs, 3600.0, 3600) == 0     # bar 0 just closed
    assert gw.last_closed_index(epochs, 7199.0, 3600) == 0     # bar 1 still forming
    assert gw.last_closed_index(epochs, 7200.0, 3600) == 1


# --------------------------------------------------------------------------- #
# Grid and folds
# --------------------------------------------------------------------------- #


def test_the_grid_is_exactly_twenty_four_configurations():
    """The protocol declares 24; a bigger closed grid must be a protocol change."""
    assert len(gw.configs()) == 24


def test_folds_are_contiguous_and_cover_the_usable_span():
    epochs = np.arange(2000, dtype=float) * 900.0 + 1_767_000_000.0
    folds = gw.build_folds(epochs, fold_days=8, warmup=480)
    assert len(folds) >= 2
    for (_n1, _s1, e1), (_n2, s2, _e2) in zip(folds, folds[1:]):
        assert e1 == s2, "folds must tile without a gap or an overlap"
    assert folds[0][1] == 0


def test_tstat_matches_a_hand_computed_value():
    # mean 2.5, sample sd sqrt(5/3)=1.2910, sem 1.2910/sqrt(4)=0.6455, t=3.8730
    assert gw.tstat([1.0, 2.0, 3.0, 4.0]) == pytest.approx(3.8729833)
    assert gw.tstat([2.0, 2.0, 2.0]) == 0.0  # zero variance -> 0.0, not a division error
    assert gw.tstat([1.0]) == 0.0             # one fold has no dispersion to test


def test_fold_r_attributes_a_trade_to_its_ENTRY_fold():
    trades = [{"entry_i": 5, "net_r": 1.0}, {"entry_i": 25, "net_r": -2.0}]
    folds = [("F01", 0, 20), ("F02", 20, 40)]
    assert gw.fold_r(trades, folds) == [1.0, -2.0]


# --------------------------------------------------------------------------- #
# Criteria
# --------------------------------------------------------------------------- #


def test_one_failed_leg_is_not_validated():
    rs = [1.0, -0.1, 1.0, 0.5, 1.0, 0.2, 1.0, 0.4]
    good = gw.criteria(rs, control_total=-5.0)
    assert all(v for k, v in good.items() if k.startswith("V"))
    # Same folds, but the control now beats them: V4 alone fails.
    bad = gw.criteria(rs, control_total=999.0)
    assert bad["V4 beats control"] is False
    assert sum(1 for k, v in bad.items() if k.startswith("V") and not v) == 1


def test_v3_rejects_a_single_catastrophic_fold():
    rs = [1.0] * 10 + [-4.0]
    assert gw.criteria(rs, control_total=-99.0)["V3 worst>-3"] is False


def test_criteria_on_a_negative_series_fails_v1():
    assert gw.criteria([-1.0, -2.0, -1.0], control_total=-99.0)["V1 total>0"] is False


# --------------------------------------------------------------------------- #
# Simulation behaviour
# --------------------------------------------------------------------------- #


def test_the_ema_trend_family_does_trade_on_a_clean_uptrend():
    bars, hours, atr = mk_bars()
    cfg = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 1.5,
           "win_lo": 7, "win_hi": 20}
    trades = run(bars, hours, atr, cfg)
    assert trades, "an uptrend with aligned EMAs must produce at least one trade"
    assert all(t["dir"] == 1 for t in trades)


def test_every_trade_pays_the_spread_and_the_commission():
    bars, hours, atr = mk_bars()
    cfg = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 1.5,
           "win_lo": 7, "win_hi": 20}
    for t in run(bars, hours, atr, cfg):
        assert t["spread_r"] > 0 and t["comm_r"] > 0
        assert t["net_r"] == pytest.approx(
            t["gross_r"] - t["spread_r"] - t["comm_r"])


def test_stop_is_assumed_first_when_both_sides_are_touched():
    """Pessimistic tie-break: a bar containing both stop and target counts as a loss."""
    bars, hours, atr = mk_bars()
    cfg = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 1.5,
           "win_lo": 7, "win_hi": 20}
    # Widen every bar so it spans the stop and the target of any open trade. The
    # gap check fires on the OPEN, so the open must stay inside the range.
    bars = dict(bars)
    bars["high"] = bars["high"] + 500.0
    bars["low"] = bars["low"] - 500.0
    trades = run(bars, hours, atr, cfg)
    assert trades, "the test needs at least one trade to say anything"
    assert all(t["exit"] <= t["entry"] for t in trades), \
        "with both sides touched, the exit must be the stop (a loss), never the target"


def test_gap_through_stop_fills_at_the_open_not_at_the_stop():
    bars, hours, atr = mk_bars()
    cfg = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 3.0,
           "win_lo": 7, "win_hi": 20}
    trades = run(bars, hours, atr, cfg)
    assert trades
    b = dict(bars)
    first = trades[0]
    # Force the bar AFTER entry to open 50 below the entry: straight through the stop.
    j = first["entry_i"] + 1
    b["open"] = bars["open"].copy()
    b["open"][j] = bars["close"][first["entry_i"]] - 50.0
    b["low"] = np.minimum(bars["low"], b["open"] - 1.0)
    b["high"] = np.maximum(bars["high"], b["open"] + 1.0)
    tous = run(b, hours, atr, cfg)
    assert tous
    gapped = [t for t in tous if t["entry_i"] == first["entry_i"]]
    assert gapped, "the entry bar should still produce a trade"
    assert gapped[0]["exit"] == pytest.approx(b["open"][j])


def test_forced_flat_at_the_session_end():
    """A position still open at 22:00 UTC must be closed, not carried overnight."""
    bars, hours, atr = mk_bars()
    hours = hours.copy()
    hours[600:] = 22  # session ends partway through the sample
    cfg = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 500.0,
           "win_lo": 7, "win_hi": 20}
    trades = run(bars, hours, atr, cfg)
    assert trades
    forced = [t for t in trades if t["forced"]]
    assert forced, "a wide target must force a session-end exit"
    for t in trades:
        # The fill happens at the OPEN of the first bar at/after the flat hour, so the
        # exit bar's own hour is 22. What must never happen is an exit LATER than that.
        assert hours[t["exit_i"]] <= 22, "no exit may sit past the flat hour"
    for t in forced:
        assert hours[t["exit_i"]] == 22
        assert hours[t["exit_i"] - 1] < 22, \
            "the forced exit must be the FIRST bar past the flat hour"


def test_random_control_is_deterministic_and_pays_the_same_costs():
    bars, hours, atr = mk_bars()
    cfg = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 1.5,
           "win_lo": 7, "win_hi": 20}
    a = gw.random_control(bars, hours, atr, 15, cfg, start=0, end=700, seed=1234)
    b = gw.random_control(bars, hours, atr, 15, cfg, start=0, end=700, seed=1234)
    c = gw.random_control(bars, hours, atr, 15, cfg, start=0, end=700, seed=9999)
    assert [t["net_r"] for t in a] == [t["net_r"] for t in b]
    assert [t["net_r"] for t in a] != [t["net_r"] for t in c]
    assert len(a) <= 15
