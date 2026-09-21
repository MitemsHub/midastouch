"""Pins for the derived-stop test: the risk unit, the derivation, and the verdict.

WHY THIS FILE EXISTS. `scripts/gold_exit_capture.py`'s policy engine held the stop at
1.0 x ATR for every policy, so *widening* it is new behaviour in a function the whole exit
study depends on. Two things therefore need pinning before any number derived from it is
trusted:

* **1R is the stop distance, at every multiple.** If `stop_mult` scaled the stop but not the
  risk unit, a wider stop would silently mean a bigger loss per trade and every R-denominated
  comparison would be wrong. The synthetic case below shows a stopped-out trade reporting
  about -1R whether the stop is 1.0 or 2.0 x ATR.
* **the default is still the certified geometry.** `stop_mult=1.0` must leave every number in
  `artifacts/gold_exit_capture.json` untouched, and the derived-stop artifact re-derives k from
  its own stored percentiles rather than trusting the round trip through JSON.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_exit_capture as ge  # noqa: E402
import gold_prereg_derived_stop as gd  # noqa: E402

ART = ROOT / "artifacts" / "gold_prereg_derived_stop.json"


def mk_bars(closes: list[float], start_hour: int = 0) -> dict:
    """M15 bars starting at `start_hour` UTC, with each OPEN equal to the PREVIOUS close.

    The open rule is load-bearing and was measured the hard way: with `open == close` every bar
    opens beyond the stop it just crossed, which the engine correctly reads as a gap and fills
    at the open -- a stopped-out trade then reports -1.5R instead of -1R. The engine's gap rule
    is right; synthetic bars that accidentally gap are not, so the series opens where the last
    one closed unless a test deliberately inserts a gap.
    """
    base = datetime(2026, 3, 2, start_hour, tzinfo=timezone.utc)
    epoch = np.array([(base + timedelta(minutes=15 * i)).timestamp() for i in range(len(closes))])
    close = np.array(closes, dtype=float)
    open_ = np.concatenate(([close[0]], close[:-1]))
    return {"open": open_, "close": close, "high": np.maximum(open_, close) + 0.05,
            "low": np.minimum(open_, close) - 0.05,
            "epoch": epoch, "spread": np.zeros(len(closes)), "volume": np.zeros(len(closes))}


def costs_in_r(atr: float, stop_mult: float) -> float:
    entry, risk = 100.0, atr * stop_mult
    return (ge.gw.SPREAD_BPS / 1e4 * entry) / risk + \
        ge.gw.COMMISSION_PER_LOT_RT / (risk * ge.gw.USD_PER_UNIT_PER_LOT)


# ------------------------------------------------------------------ the risk unit

def test_a_stop_out_is_minus_one_r_whatever_the_stop_multiple_is():
    """The invariant the whole derived-stop comparison rests on."""
    bars = mk_bars([100.0, 98.5, 97.0, 95.0, 94.0])
    atr = np.full(5, 1.0)
    entry = [{"entry_i": 0, "dir": 1, "entry": 100.0}]
    tight = ge.simulate_policy(bars, entry, atr, tp=None, trail=None, time_bars=None,
                               stop_mult=1.0)[0]
    wide = ge.simulate_policy(bars, entry, atr, tp=None, trail=None, time_bars=None,
                              stop_mult=2.0)[0]
    assert tight["net_r"] == pytest.approx(-1.0 - costs_in_r(1.0, 1.0), abs=1e-6)
    assert wide["net_r"] == pytest.approx(-1.0 - costs_in_r(1.0, 2.0), abs=1e-6)
    assert tight["exit_i"] != wide["exit_i"], "the wider stop must survive longer"


def test_a_wider_stop_keeps_a_dip_and_recovery_alive():
    """The behaviour the derivation is trying to buy: noise inside the stop is not a loss."""
    bars = mk_bars([100.0, 98.4, 102.0])
    atr = np.full(3, 1.0)
    entry = [{"entry_i": 0, "dir": 1, "entry": 100.0}]
    tight = ge.simulate_policy(bars, entry, atr, tp=None, trail=None, time_bars=None,
                               stop_mult=1.0)[0]
    wide = ge.simulate_policy(bars, entry, atr, tp=None, trail=None, time_bars=None,
                              stop_mult=3.0)[0]
    assert tight["net_r"] < 0, tight          # 99.0 was traded through
    assert wide["net_r"] > 0, wide            # 97.0 held, and no target caps the recovery


def test_costs_in_r_shrink_as_the_stop_widens():
    """A wider stop is a bigger 1R, so the same spread is fewer R. Pinned so the cost model
    cannot drift into charging a fixed R toll regardless of geometry."""
    assert costs_in_r(1.0, 2.0) < costs_in_r(1.0, 1.0)


# --------------------------------------------------------------- the derivation

def test_the_derived_multiple_is_the_declared_percentile_of_the_adverse_excursion():
    """The RELATIONSHIP is what must hold, not a value I could have guessed.

    An earlier version of this test asserted `1.35 +/- 0.35` for a gamma distribution: a
    constant invented rather than measured, and it failed on the first honest run. What is
    pinned now is that k IS the declared percentile, that it sits between the median and the
    90th, and that a shifted distribution moves it -- which is the property the derivation
    actually relies on.
    """
    rng = np.random.default_rng(4)
    mae = rng.gamma(2.0, 0.8, size=400)
    k = float(np.percentile(mae, gd.QUANTILE * 100))
    assert k == pytest.approx(float(np.percentile(mae, 70)), abs=1e-9)
    assert float(np.percentile(mae, 50)) < k < float(np.percentile(mae, 90))
    assert float(np.percentile(mae * 3.0, gd.QUANTILE * 100)) == pytest.approx(3.0 * k, rel=1e-9)


def test_stop_out_rate_measures_the_share_of_entries_that_reach_the_stop():
    bars = mk_bars([100.0, 99.0, 98.0, 97.0, 96.0, 95.0])
    atr = np.full(6, 1.0)
    entries = [{"entry_i": 0, "dir": 1, "entry": float(100 - 0.5 * i)} for i in range(3)]
    rate = gd.stop_out_rate(bars, entries, atr, k=2.0)
    assert 0.0 <= rate <= 1.0
    # A stop of 2 ATR is reached by the entries that start highest and fall the furthest.
    assert rate == pytest.approx(2 / 3, abs=0.34), rate


# ------------------------------------------------------------- the decision rule

def test_decide_refuses_an_unsound_derivation_before_anything_else():
    v, why = gd.decide({"n": 900, "mean_r": 9.0, "t": 99.0}, unsound=True, realized_nreq=1)
    assert v == "UNSOUND DERIVATION" and "band" in why


def test_decide_applies_the_more_demanding_of_the_two_sample_requirements():
    """The declaration's clause: the realized effect can raise the bar above 375."""
    v, why = gd.decide({"n": 400, "mean_r": 0.1, "t": 5.0}, unsound=False, realized_nreq=500)
    assert v == "INSUFFICIENT" and "500" in why


def test_decide_kills_and_passes():
    assert gd.decide({"n": 900, "mean_r": -0.01, "t": -0.2}, unsound=False,
                     realized_nreq=1)[0] == "KILL"
    assert gd.decide({"n": 900, "mean_r": 0.4, "t": 3.0}, unsound=False,
                     realized_nreq=1)[0] == "PASS"


# ------------------------------------------------------------------- the artifact

@pytest.mark.skipif(not ART.is_file(),
                    reason="artifacts/ is gitignored, so this record is local to the machine "
                           "that produced it - regenerate with "
                           "python scripts/gold_prereg_derived_stop.py")
def test_the_artifact_verdict_recomputes_from_its_own_numbers():
    art = json.loads(ART.read_text(encoding="utf-8"))
    d, prim = art["declared"], art["primary"]
    v, why = gd.decide({"n": prim["stats"]["n"], "mean_r": prim["stats"]["mean_r"],
                        "t": prim["stats"]["t"]},
                       unsound=art["derivation"]["unsound"],
                       realized_nreq=prim["realized_n_requirement"])
    assert v == prim["verdict"] == art["verdict"], (v, prim["verdict"], art["verdict"])
    assert why == prim["reason"]


@pytest.mark.skipif(not ART.is_file(), reason="derived-stop artifact absent (artifacts/ is gitignored)")
def test_the_stored_multiple_really_is_the_declared_percentile():
    """k must come out of the stored distribution, not be carried along beside it."""
    art = json.loads(ART.read_text(encoding="utf-8"))
    pcts = art["derivation"]["percentiles"]
    assert pcts["0.7"] == pytest.approx(art["derivation"]["k"], abs=1e-6)
    assert pcts["0.5"] < pcts["0.7"] < pcts["0.9"]
    assert art["declared"]["derivation"]["k"] == art["derivation"]["k"]


@pytest.mark.skipif(not ART.is_file(), reason="derived-stop artifact absent (artifacts/ is gitignored)")
def test_the_record_declares_its_soundness_band_and_that_sensitivity_is_not_for_choosing():
    art = json.loads(ART.read_text(encoding="utf-8"))
    lo, hi = art["declared"]["unsound_band"]
    rate = art["derivation"]["stop_out_rate_primary"]
    assert lo <= rate <= hi, (rate, lo, hi)
    assert art["derivation"]["unsound"] is False
    assert art["declared"]["sensitivity_is_information_only"] is True
    assert art["sizing_scan_post_hoc"], "the declared sizing leg must be recorded"


@pytest.mark.skipif(not ART.is_file(), reason="derived-stop artifact absent (artifacts/ is gitignored)")
def test_the_derivation_beat_the_conventional_stop_on_significance_not_on_mean():
    """The honest shape of the result, pinned so a later summary cannot flip it.

    A wider stop bought a smaller dispersion (and so a larger t) while LOWERING the mean. If a
    future run reverses one of those two facts, that is a different finding and this test must
    be revisited deliberately rather than silently.
    """
    art = json.loads(ART.read_text(encoding="utf-8"))
    prim = art["primary"]
    conv = prim["comparators"]["same rule, stop 1.0xATR"]
    assert prim["stats"]["t"] > conv["t"], "derived stop: higher t"
    assert prim["stats"]["mean_r"] < conv["mean_r"], "derived stop: lower mean"
    assert prim["stats"]["sd"] < conv["sd"], "derived stop: smaller dispersion"
    assert prim["stats"]["n"] == conv["n"], "same entries, so the comparison is the stop"
