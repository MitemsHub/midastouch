"""Pins for the v2 gold tooling: the window plumbing, the exit resolver, and the
two invariants the v2 conclusion rests on.

These guard the corrections recorded in docs/GOLD_V2_RESEARCH_20260919.md. The
load-bearing claims are:

  * `window_matrix` looks strictly FORWARD in index and NaN-fills a truncated
    window, so a horizon cannot be silently scored short;
  * the exit resolver is pessimistic — a gap fills at the open and a same-bar tie
    goes to the stop — because that is the only reading that cannot flatter a
    result;
  * the drift-neutral coin flip really is drift-neutral: mirroring the price path
    flips the sign of gross R, so E_dir removes the sample's direction and leaves
    the geometry's bias.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gold_geometry_study as gs  # noqa: E402
import gold_wfo_v2 as w2  # noqa: E402


# --------------------------------------------------------------------------- #
# window plumbing
# --------------------------------------------------------------------------- #

class TestWindowMatrix:
    def test_shifts_forward_by_k(self):
        arr = np.array([1.0, 2.0, 3.0, 4.0])
        m = gs.window_matrix(arr, 3)
        assert m[0, 1] == 2.0 and m[0, 2] == 3.0 and m[0, 3] == 4.0
        assert m[1, 1] == 3.0 and m[1, 2] == 4.0

    def test_truncated_window_is_nan_not_wrapped(self):
        """A row without a full horizon must not borrow bars from the past."""
        arr = np.array([1.0, 2.0, 3.0])
        m = gs.window_matrix(arr, 2)
        assert m[1, 1] == 3.0
        assert np.isnan(m[1, 2]), "row 1 has no second future bar"
        assert np.isnan(m[2, 1])

    def test_column_zero_is_unused(self):
        """Column 0 exists only to keep k indexable as k = 1..horizon."""
        arr = np.array([5.0, 6.0, 7.0])
        assert np.isnan(gs.window_matrix(arr, 2)[:, 0]).all()


# --------------------------------------------------------------------------- #
# the exit resolver
# --------------------------------------------------------------------------- #

def _bars(closes, pad=0.5):
    c = np.array(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    return o, c + pad, c - pad, c


class TestExitFill:
    def test_same_bar_tie_goes_to_the_stop(self):
        """Bar 1 spans both barriers. Pessimistic = the stop wins. This single
        choice is worth +/-0.073R at a 0.5-ATR stop, so it is pinned."""
        o, h, l, c = _bars([100.0, 100.0, 100.0, 100.0], pad=1.5)
        hours = np.zeros(4, dtype=int)
        px, j, why = w2._exit_fill(1, 98.5, 101.5, o, h, l, c, hours, 0, 5, 4)
        assert why == "stop" and px == pytest.approx(98.5) and j == 1

    def test_gap_through_stop_fills_at_the_open(self):
        """A stop cannot fill at its own price when the bar OPENS beyond it.
        Arrays are written out by hand because a gap is precisely what `_bars`
        cannot produce (it sets open = previous close)."""
        o = np.array([100.0, 95.0, 95.0])
        h = np.array([100.5, 95.5, 95.5])
        l = np.array([99.5, 94.5, 94.5])
        c = np.array([100.0, 95.0, 95.0])
        hours = np.zeros(3, dtype=int)
        px, j, why = w2._exit_fill(1, 98.0, 120.0, o, h, l, c, hours, 0, 5, 3)
        assert why == "gap_stop" and px == pytest.approx(95.0) and j == 1

    def test_short_gap_through_stop_fills_at_the_open(self):
        o = np.array([100.0, 108.0, 108.0])
        h = np.array([100.5, 108.5, 108.5])
        l = np.array([99.5, 107.5, 107.5])
        c = np.array([100.0, 108.0, 108.0])
        hours = np.zeros(3, dtype=int)
        px, j, why = w2._exit_fill(-1, 102.0, 80.0, o, h, l, c, hours, 0, 5, 3)
        assert why == "gap_stop" and px == pytest.approx(108.0) and j == 1

    def test_target_reached_cleanly(self):
        o, h, l, c = _bars([100.0, 103.0, 106.0, 109.0], pad=0.5)
        hours = np.zeros(4, dtype=int)
        px, j, why = w2._exit_fill(1, 95.0, 102.0, o, h, l, c, hours, 0, 5, 4)
        assert why == "target" and px == pytest.approx(102.0) and j == 1

    def test_time_stop_closes_at_the_horizon(self):
        o, h, l, c = _bars([100.0] * 6, pad=0.5)
        hours = np.zeros(6, dtype=int)
        px, j, why = w2._exit_fill(1, 90.0, 120.0, o, h, l, c, hours, 0, 2, 6)
        assert why == "time" and j == 2 and px == pytest.approx(100.0)

    def test_session_flatten_preempts_the_time_stop(self):
        o, h, l, c = _bars([100.0] * 6, pad=0.5)
        hours = np.zeros(6, dtype=int)
        hours[1] = gs.FLAT_BY_UTC_HOUR
        px, j, why = w2._exit_fill(1, 90.0, 120.0, o, h, l, c, hours, 0, 5, 6)
        assert why == "flatten" and j == 1

    def test_unclosed_position_returns_none(self):
        """End of data inside the horizon: no exit to book, not a free win."""
        o, h, l, c = _bars([100.0] * 3, pad=0.5)
        hours = np.zeros(3, dtype=int)
        px, j, why = w2._exit_fill(1, 90.0, 120.0, o, h, l, c, hours, 0, 10, 3)
        assert px is None


# --------------------------------------------------------------------------- #
# the two invariants the v2 argument rests on
# --------------------------------------------------------------------------- #

class TestBracketInvariants:
    def _win(self, closes, pad=0.5, horizon=3):
        o, h, l, c = _bars(closes, pad)
        idx = np.array([0])
        return gs.build_windows(idx, o, h, l, c, horizon), c[idx], np.ones(1)

    def test_long_into_a_rising_path_collects_the_target(self):
        """stop = 2.0 ATR below the entry, target = 1.5 ATR ABOVE it (the target
        is tp_mult x ATR, not x risk), so R = 1.5 / 2.0 = +0.75."""
        win, entry, atr = self._win([100.0, 103.0, 106.0, 109.0], pad=0.5)
        r = gs.bracket_outcomes(entry, atr, win, 2.0, 1.5, 3,
                                direction=1, optimistic=False)
        assert r["gross"][0] == pytest.approx(0.75, abs=1e-9)

    def test_long_into_a_falling_path_pays_the_stop(self):
        win, entry, atr = self._win([100.0, 96.0, 94.0, 90.0], pad=0.5)
        r = gs.bracket_outcomes(entry, atr, win, 2.0, 1.5, 3,
                                direction=1, optimistic=False)
        assert r["gross"][0] == pytest.approx(-1.0, abs=1e-9)

    def test_long_on_the_path_equals_short_on_the_mirror(self):
        """THE invariant behind E_dir. Reflecting prices about the entry (and
        swapping highs with lows) turns a long into a short: the same barriers are
        touched in the same bars, so gross R must match EXACTLY.

        Note this is long-vs-short, not long-vs-long. A long on the mirrored path
        is a different trade (its bracket points the other way); what is symmetric
        is the RULE. Drift is precisely what breaks the symmetry between the two
        REAL directions, which is why (E_long + E_short)/2 cancels it and leaves
        only the geometry's bias."""
        e = 100.0
        o, h, l, c = _bars([100.0, 103.0, 99.0, 106.0, 95.0], pad=0.5)
        o2, h2, l2, c2 = 2 * e - o, 2 * e - l, 2 * e - h, 2 * e - c
        idx = np.array([0])
        atr = np.ones(1)
        w_long = gs.build_windows(idx, o, h, l, c, 4)
        w_mirror = gs.build_windows(idx, o2, h2, l2, c2, 4)
        gl = gs.bracket_outcomes(c[idx], atr, w_long, 2.0, 1.5, 4,
                                 direction=1, optimistic=False)["gross"][0]
        sh = gs.bracket_outcomes(c2[idx], atr, w_mirror, 2.0, 1.5, 4,
                                 direction=-1, optimistic=False)["gross"][0]
        assert gl == pytest.approx(sh, abs=1e-9)

    def test_pessimistic_never_beats_optimistic(self):
        rng = np.random.default_rng(7)
        closes = 100 + np.cumsum(rng.normal(0, 1.2, 400))
        o, h, l, c = _bars(closes, pad=1.0)
        idx = np.arange(50, 350)
        win = gs.build_windows(idx, o, h, l, c, 8)
        entry, atr = c[idx], np.ones(len(idx))
        pes = gs.bracket_outcomes(entry, atr, win, 1.0, 2.0, 8,
                                  direction=1, optimistic=False)
        opt = gs.bracket_outcomes(entry, atr, win, 1.0, 2.0, 8,
                                  direction=1, optimistic=True)
        assert pes["gross"].mean() <= opt["gross"].mean()
        assert np.all(pes["gross"] <= opt["gross"] + 1e-9)

    def test_every_entry_gets_exactly_one_exit_reason(self):
        rng = np.random.default_rng(11)
        closes = 100 + np.cumsum(rng.normal(0, 1.5, 300))
        o, h, l, c = _bars(closes, pad=1.0)
        idx = np.arange(40, 260)
        win = gs.build_windows(idx, o, h, l, c, 12)
        entry, atr = c[idx], np.ones(len(idx))
        for optim in (False, True):
            r = gs.bracket_outcomes(entry, atr, win, 1.5, 1.5, 12,
                                    direction=1, optimistic=optim)
            assert r["n_stop"] + r["n_tp"] + r["n_time"] == r["n"]


class TestCostModel:
    def test_toll_falls_as_the_stop_widens(self):
        """The measured correction: the quoted 0.0247R floor is a WIDE-stop figure.
        A 1-ATR M15 stop pays ~2.3x that."""
        entry = np.array([4377.66])
        narrow = gs.cost_r(entry, np.array([9.89]))[0]
        wide = gs.cost_r(entry, np.array([23.0]))[0]
        assert narrow == pytest.approx(0.0576, abs=5e-4)
        assert wide == pytest.approx(0.0248, abs=5e-4)
        assert narrow / wide > 2.0

    def test_stops_below_the_declared_floor_are_not_searched(self):
        """The 1.5-ATR floor is a constraint justified by the assumption band, and
        the grid must not silently breach it."""
        for cfg in w2.configs():
            assert cfg["stop_mult"] >= 1.5
