"""The conjunction census must agree with the engine, or it is a lookalike.

`scripts/midas_decision_attribution.py` walks bars independently of `midas_sweep.run_mode`
(occupancy-free, so it can count CANDIDATES where the engine counts FILLS). That independence is
the point of the study and also its risk: a census that disagrees with the engine is a different
program wearing the same numbers. These tests make the disagreement a failure instead of a
footnote — the harness's own cross-check, plus the arithmetic behind its headline columns.

The expensive part is deliberately kept small: three modes on one window, which is enough to
exercise all four (trigger, macro) classes the census defines.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import midas_decision_attribution as DA  # noqa: E402
import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    """The venue's own bars for the window the pinned law is defined on."""
    spec = P._window_spec("wfv")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    yield spec, data
    M._BASIS = prev


def test_the_pinned_venue_corpus_law_is_reproduced(corpus):
    """The law the whole harness refuses to report without (tests/test_midas_minlot_veto.py)."""
    spec, data = corpus
    rr = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    assert len(rr.trades) == 56
    assert abs(sum(t["r"] for t in rr.trades) - 15.9352) < 5e-4


def test_the_census_agrees_with_the_engine_on_every_trade(corpus):
    """Trigger presence, macro state, session hour — for every fill, in three modes.

    REVERSE_DIRECTION and ORIGINAL between them cover both signed trigger classes; TRIGGER_ONLY
    additionally covers the divergent-macro class. A disagreement here means off-by-one indexing,
    a different macro rule, a different trigger rule, or a different clock — i.e. that the study's
    numbers describe something other than the engine of record.
    """
    spec, data = corpus
    census = DA.walk(data, spec["t0"], spec["t1"], M.SESSION_LO, M.SESSION_HI)
    assert census, "the census walked no bars at all"

    seen_classes = set()
    for mode in ("REVERSE_DIRECTION", "ORIGINAL", "TRIGGER_ONLY"):
        rr = M.run_mode(mode, spec["t0"], spec["t1"], data)
        assert rr.trades, f"{mode} took no trades — the cross-check would be vacuous"
        assert DA.check_against_engine(mode, rr.trades, census) == []
        for t in rr.trades:
            seen_classes.add(census[int(t["open_ct"])]["class"])

    # the cross-check exercised the signed classes and the no-macro-gate pool
    assert "trig_macro_anti" in seen_classes
    assert "trig_macro_agree" in seen_classes


def test_a_fill_bar_is_its_signals_close_time(corpus):
    """The identity the cross-check relies on: a trade's `open_ct` IS the signal bar's close.

    MEASURED on this corpus rather than assumed: every fill lands on the bar immediately after
    the signal bar, so its open time equals the signal bar's open + 900 (its close time).
    """
    spec, data = corpus
    for mode in ("REVERSE_DIRECTION", "ORIGINAL", "TRIGGER_ONLY"):
        for t in M.run_mode(mode, spec["t0"], spec["t1"], data).trades:
            assert (int(t["open_ct"]) - 900) % 900 == 0


def test_zero_entry_days_counts_days_never_touched():
    """The column a prop account actually feels: a 0.7/day rule flat on half the days."""
    t0 = 1_700_000_000 - (1_700_000_000 % 86400)
    # three days in the frame; one trade on the second day only
    trades = [{"open_ct": t0 + 86400 + 60}]
    got = DA.day_stats(trades, t0, t0 + 2 * 86400)
    assert got["days"] == 3
    assert got["per_day"] == pytest.approx(0.333, abs=5e-4)
    assert got["zero_day_share"] == pytest.approx(0.667, abs=5e-4)
    assert DA.day_stats([], t0, t0 + 86400)["zero_day_share"] == 1.0


def test_the_required_sample_is_the_number_that_makes_a_cell_decidable():
    """`n_needed_for_t15`: t = mean / (sd / sqrt(n)) => n = (1.5 * sd / mean)^2."""
    import statistics
    rng = [0.5, -1.0, 2.0, -0.5, 1.0, -1.0, 0.25, 1.75]
    n = DA.needed_for_t15(rng)
    sd, mean = statistics.stdev(rng), statistics.mean(rng)
    assert n is not None and n > 1
    # the definition, checked from both sides: at that n the t of this distribution clears 1.5,
    # and at n-1 it does not — so the column is a threshold and not an estimate
    assert mean / (sd / (n ** 0.5)) >= 1.5
    assert mean / (sd / ((n - 1) ** 0.5)) < 1.5
    # a negative mean is never decidable as "better than zero", and must not return a sample
    assert DA.needed_for_t15([-0.5, -1.0, 0.25]) == -1
    assert DA.needed_for_t15([0.5]) is None          # a sample of one decides nothing
    assert DA.t_stat([0.5]) is None
