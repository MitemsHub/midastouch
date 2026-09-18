"""Offline tests for the floor-zone boundary math (scripts/floor_zone.py).

The pins that matter: the EA-faithful tick-value calibration (the geometric
override is load-bearing — the raw broker value understated V75 risk 100x on
2026-09-16), Wilder-ATR parity with iATR, the exact boundary chain including
the arm-A historical anchor ($4.64 min-lot risk -> $30.93 strangulation
equity), the ordered verdict classification with boundary-equality semantics,
and fail-closed behavior when the terminal is unreachable.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import floor_zone as fz  # noqa: E402


# --- fixtures -----------------------------------------------------------------

def _sd(atr_h1: float = 545.38, atr_m15: float | None = 130.0,
        tick_value_raw: float = 0.0001, tick_size: float = 0.01,
        contract: float = 1.0, volume_min: float = 0.01) -> fz.SymbolData:
    atr = {"H1": atr_h1}
    if atr_m15 is not None:
        atr["M15"] = atr_m15
    return fz.SymbolData(symbol="Volatility 75 Index", volume_min=volume_min,
                         tick_size=tick_size, tick_value_raw=tick_value_raw,
                         contract_size=contract, atr=atr)


# --- tick-value calibration ------------------------------------------------------

def test_geometric_override_is_load_bearing() -> None:
    """Live 2026-09-16 values: broker tick value 0.0001 vs geometric 0.01 —
    the calibration must take the geometric value (100x apart, well outside
    the 5% identity rule)."""
    sd = _sd()
    assert sd.calibrated_tick_value == pytest.approx(0.01)
    # and a broker value inside tolerance is trusted as-is
    sd2 = _sd(tick_value_raw=0.0103)
    assert sd2.calibrated_tick_value == pytest.approx(0.0103)


def test_calibration_zero_broker_value_overrides() -> None:
    sd = _sd(tick_value_raw=0.0)
    assert sd.calibrated_tick_value == pytest.approx(0.01)


# --- Wilder ATR parity --------------------------------------------------------------

def test_wilder_atr_matches_iatr_semantics() -> None:
    """iATR seeds with the simple mean of the first `period` TRs, then applies
    Wilder smoothing — not a simple moving average of the window."""
    bars = [(10 + i * 0.1, 10 - i * 0.1, 10.0 + (i % 5) * 0.2) for i in range(30)]
    got = fz.wilder_atr(bars, 14)
    # manual computation of the same recursion
    trs = []
    for i in range(1, len(bars)):
        h, l, c = bars[i]
        _, pc, _ = bars[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:14]) / 14
    for tr in trs[14:]:
        atr = (atr * 13 + tr) / 14
    assert got == pytest.approx(atr)


def test_wilder_atr_needs_enough_closed_bars() -> None:
    bars = [(10, 9, 10.0)] * 10
    assert fz.wilder_atr(bars, 14) is None
    assert fz.wilder_atr(bars[:5], 3) is not None


# --- boundary chain (the arm-A anchor lives here) --------------------------------------

def test_boundary_chain_arm_a_anchor() -> None:
    """Sep-15 ground truth: pullback stop at that day's ATR gave min-lot risk
    $4.64 -> strangulation equity $30.93 = 4.64 / 0.15. The formula must
    reproduce the anchor exactly."""
    atr = 4.64 / (1.7 * 0.01 / 0.01 * 0.01 * 0.01 * 100.0)  # inverted below instead
    # direct: per_lot = (1.7*atr / 0.01) * 0.01 * 1.0 ... use the anchor form:
    # min_lot_risk = (stop/tick_size)*tv*vol = (1.7*atr/0.01)*0.01*0.01
    atr = 4.64 / (1.7 * 0.01 * 100.0)  # (stop/0.01)*0.01*0.01 = stop*0.01... see test below
    b = fz.compute_boundary("pullback", "Volatility 75 Index",
                            _sd(atr_h1=500.0, atr_m15=273.0),
                            window_start_equity=50.0)
    assert b is not None
    assert b.min_lot_risk == pytest.approx(1.7 * 273.0 * 0.01, rel=1e-9)
    assert b.strangulation_equity == pytest.approx(b.min_lot_risk / 0.15, rel=1e-9)
    assert b.floor_onset_equity == pytest.approx(b.min_lot_risk / 0.01, rel=1e-9)
    assert b.halt_equity == pytest.approx(35.0, rel=1e-9)


def test_boundary_anchor_exact_observed_numbers() -> None:
    """The exact anchor: min-lot risk $4.64 must map to strangulation $30.93
    (the value the arm-A post-mortem computed)."""
    b = fz.compute_boundary("pullback", "V", _sd(atr_m15=(4.64 / 0.0169) / 100.0 * 100.0 / 100.0))
    # simpler: construct symbol data so that min_lot_risk == 4.64 exactly:
    # min_lot_risk = (1.7*atr / tick_size) * tv * vol = (1.7*atr/0.01)*0.01*0.01
    #              = 1.7*atr*0.01  ->  atr = 4.64 / 0.017 = 272.941...
    atr = 4.64 / (1.7 * 0.01)
    b = fz.compute_boundary("pullback", "V", _sd(atr_m15=atr))
    assert b.min_lot_risk == pytest.approx(4.64, abs=1e-9)
    assert b.strangulation_equity == pytest.approx(30.93, abs=0.005)


def test_boundary_v28_uses_h1_geometry() -> None:
    b = fz.compute_boundary("v28", "V", _sd(atr_h1=545.38, atr_m15=None))
    assert b.stop_distance == pytest.approx(2.0 * 545.38)
    assert b.min_lot_risk == pytest.approx((2.0 * 545.38 / 0.01) * 0.01 * 0.01)
    assert b.disclosure == ""


def test_boundary_pullback_carries_disclosure() -> None:
    b = fz.compute_boundary("pullback", "V", _sd())
    assert "swing widening" in b.disclosure


def test_boundary_fails_closed_on_unusable_data() -> None:
    assert fz.compute_boundary("v28", "V", _sd(atr_h1=0.0)) is None
    assert fz.compute_boundary("v28", "V", _sd(atr_h1=545.38, atr_m15=None,
                                               tick_size=0.0)) is None


# --- classification -----------------------------------------------------------------

def test_classify_is_ordered_with_boundary_equality() -> None:
    """Controlled boundaries: halt $20 < strangulation $33.33 < onset $500.
    Equality belongs to the stricter class (<= comparisons)."""
    from dataclasses import replace
    b = fz.compute_boundary("pullback", "V", _sd(atr_m15=5.0))
    b = replace(b, floor_onset_equity=500.0, strangulation_equity=100.0 / 3,
                halt_equity=20.0)
    assert fz.classify(15.0, b) == "HALTED"
    assert fz.classify(b.halt_equity, b) == "HALTED"
    assert fz.classify(25.0, b) == "STRANGULATED"
    assert fz.classify(b.strangulation_equity, b) == "STRANGULATED"
    assert fz.classify(300.0, b) == "FLOOR_MODE"
    assert fz.classify(b.floor_onset_equity, b) == "FLOOR_MODE"
    assert fz.classify(b.floor_onset_equity + 0.01, b) == "TRADING"
    assert fz.classify(None, b) == "UNKNOWN"


def test_halt_fires_before_strangulation_for_small_books() -> None:
    """For a $50-start pullback arm the halt floor ($35) sits ABOVE the
    strangulation crossover ($33.82 at Sep-16 ATR): the structural-abort halt
    fires before the slow strangle completes — restart on a fresh ledger
    instead of dying locked out. That ordering IS the policy intent."""
    b = fz.compute_boundary("pullback", "V", _sd(atr_m15=4.64 / (1.7 * 0.01)),
                            window_start_equity=50.0)
    assert b.strangulation_equity == pytest.approx(30.93, abs=0.01)
    assert b.halt_equity == pytest.approx(35.0)
    assert b.halt_equity > b.strangulation_equity
    # descending book: FLOOR_MODE at $40, then HALTED at $35 —
    # STRANGULATED is never reached because the halt pre-empts it
    assert fz.classify(40.0, b) == "FLOOR_MODE"
    assert fz.classify(35.0, b) == "HALTED"
    assert fz.classify(31.0, b) == "HALTED"


def test_classify_halt_is_per_arm_not_per_engine() -> None:
    """A2 at a $1,000 start halts at $700 while a $50-start arm halts at $35 —
    same engine, different halt floors."""
    b = fz.compute_boundary("v28", "V", _sd(atr_m15=None))
    from dataclasses import replace
    b_a2 = replace(b, halt_equity=1000.0 * 0.70)
    b_d = replace(b, halt_equity=50.0 * 0.70)
    veq = 650.0
    assert fz.classify(veq, b_a2) == "HALTED"
    # $650 on a $50-start arm is above ITS halt ($35) but below the v28
    # floor-onset (~$1,275 at Sep-16 ATR) -> FLOOR_MODE, not TRADING
    assert fz.classify(veq, b_d) == "FLOOR_MODE"
    assert fz.classify(1_300.0, b_d) == "TRADING"
    # and a boundary without a window start classifies on the other two
    # boundaries, never HALTED (NaN halt comparisons are False)
    veq2 = b.strangulation_equity / 2.0
    assert fz.classify(veq2, b) == "STRANGULATED"


# --- frozen constants + live access fail-closed ------------------------------------------

def test_policy_constants_are_frozen() -> None:
    assert fz.BUDGET_PCT == 15.0
    assert fz.FLOOR_MODE_MAX_DD_PCT == 30.0
    assert fz.TICK_VALUE_TOLERANCE == 0.05
    assert fz.ENGINES["v28"]["sl_mult"] == 2.0
    assert fz.ENGINES["pullback"]["sl_mult"] == 1.7
    assert fz.ARM_BASE_EQUITY["A2"] == 1000.0


def test_fetch_symbol_data_fails_closed_without_terminal(monkeypatch) -> None:
    """No terminal reachable -> None (the report prints an UNKNOWN disclosure;
    it never guesses a boundary)."""
    calls = {"n": 0}

    class FakeMT5:
        def initialize(self, path=None):
            calls["n"] += 1
            return False

    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeMT5())
    assert fz.fetch_symbol_data("Volatility 75 Index") is None
    assert calls["n"] == 1
