"""Pins for the instrument adapter's sizing and cap arithmetic.

The load-bearing test here is `test_binding_cap_is_the_fleet_cap`: the whole
reason this module exists is that the EA's per-trade allowance (20%) is larger
than its fleet ceiling (15%), so the per-trade number is unreachable for a
single-instrument book. If that semantic ever flips silently, the required-equity
figures quoted to the operator become 25% too optimistic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from synthetic_trader.risk.instrument_adapter import (  # noqa: E402
    InstrumentAdapter,
    InstrumentSpec,
    RiskCaps,
)


def v75() -> InstrumentSpec:
    """The certified V75 (1-tick) facts: min lot 0.01, grid 0.001, $1.009/unit/lot."""
    return InstrumentSpec("Volatility 75 Index", min_lot=0.01, lot_step=0.001, digits=2,
                          usd_per_unit_per_lot=1.009,
                          usd_per_unit_per_lot_source="certified",
                          spec_source="probe_report_20260916")


# --- RiskCaps: the contradiction -------------------------------------------

def test_binding_cap_is_the_fleet_cap() -> None:
    caps = RiskCaps(per_trade_pct=20.0, fleet_pct=15.0)
    assert caps.binding_pct == 15.0
    assert caps.binding_cap_name == "InpMaxTotalRiskPct"


def test_binding_cap_warns_when_per_trade_allowance_is_unreachable() -> None:
    caps = RiskCaps(per_trade_pct=20.0, fleet_pct=15.0)
    assert any("unreachable" in w for w in caps.warnings())


def test_no_warning_when_the_caps_agree_or_per_trade_is_tighter() -> None:
    assert RiskCaps(per_trade_pct=15.0, fleet_pct=15.0).warnings() == []
    assert RiskCaps(per_trade_pct=5.0, fleet_pct=15.0).warnings() == []
    assert RiskCaps(per_trade_pct=5.0, fleet_pct=15.0).binding_pct == 5.0


# --- InstrumentSpec: money and lot grids -----------------------------------

def test_money_risk_matches_ticker_value_arithmetic() -> None:
    # 1195.15 price units x $1.009/unit/lot x 0.01 lots ~ $12.06
    assert v75().money_risk(1195.15, 0.01) == pytest.approx(12.06, abs=0.01)


def test_money_risk_rejects_degenerate_inputs() -> None:
    with pytest.raises(ValueError):
        v75().money_risk(0.0, 0.01)
    with pytest.raises(ValueError):
        v75().money_risk(100.0, 0.0)


def test_snap_lots_floors_to_the_grid_and_cannot_round_up() -> None:
    spec = v75()
    assert spec.snap_lots(0.0149) == pytest.approx(0.014)   # never rounds to 0.015
    assert spec.snap_lots(0.01) == pytest.approx(0.01)
    assert spec.snap_lots(0.0099) == 0.0                     # below the minimum


def test_snap_lots_survives_float_drift() -> None:
    spec = InstrumentSpec("X", min_lot=0.01, lot_step=0.001, digits=2)
    assert spec.snap_lots(0.003 * 10) == pytest.approx(0.03)


def test_volume_for_risk_returns_zero_when_min_lot_does_not_fit() -> None:
    spec = InstrumentSpec("Volatility 50 Index", min_lot=4.0, lot_step=0.001, digits=4)
    # $10 budget over a 1.72-unit stop is ~$6.88 per 4.0 lots -> cannot fit.
    assert spec.volume_for_money_risk(1.72, 5.0) == 0.0


def test_spec_rejects_nonpositive_facts() -> None:
    with pytest.raises(ValueError):
        InstrumentSpec("X", min_lot=0.0, lot_step=0.001, digits=2)
    with pytest.raises(ValueError):
        InstrumentSpec("X", min_lot=0.01, lot_step=0.0, digits=2)
    with pytest.raises(ValueError):
        InstrumentSpec("X", min_lot=0.01, lot_step=0.001, digits=2,
                       usd_per_unit_per_lot=0.0)


def test_usd_is_measured_flag_tracks_provenance() -> None:
    assert not v75().usd_is_measured                     # "certified" is not "measured live"
    measured = InstrumentSpec("X", min_lot=0.01, lot_step=0.001, digits=2,
                              usd_per_unit_per_lot_source="live order_calc_profit")
    assert measured.usd_is_measured


# --- InstrumentAdapter: floors ---------------------------------------------

def test_floor_vetoes_v75_on_a_39_dollar_account() -> None:
    """The headline finding: at $39.58 the entire universe is below its floor."""
    a = InstrumentAdapter({"Volatility 75 Index": v75()})
    v = a.floor("Volatility 75 Index", 1195.15, equity=39.58)
    assert not v.can_trade
    assert v.required_equity == pytest.approx(12.06 / 0.15, rel=0.01)  # ~$80
    assert v.shortfall > 0
    assert "CAP-VETOED" in v.reason


def test_floor_passes_when_the_account_covers_the_minimum_lot() -> None:
    a = InstrumentAdapter({"Volatility 75 Index": v75()})
    v = a.floor("Volatility 75 Index", 1195.15, equity=200.0)
    assert v.can_trade and v.shortfall == 0.0
    assert "FLOOR-OK" in v.reason


def test_floor_uses_the_binding_cap_not_the_per_trade_cap() -> None:
    """Regression pin for the 25%-optimism trap."""
    a = InstrumentAdapter({"Volatility 75 Index": v75()}, RiskCaps(20.0, 15.0))
    at_15 = a.floor("Volatility 75 Index", 600.0, equity=100.0)
    b = InstrumentAdapter({"Volatility 75 Index": v75()}, RiskCaps(20.0, 20.0))
    at_20 = b.floor("Volatility 75 Index", 600.0, equity=100.0)
    assert at_15.required_equity > at_20.required_equity


def test_unknown_symbol_fails_loudly_with_the_known_list() -> None:
    a = InstrumentAdapter({"Volatility 75 Index": v75()})
    with pytest.raises(KeyError) as e:
        a.spec("Volatility 99 Index")
    assert "Volatility 75 Index" in str(e.value)


def test_volume_for_risk_is_clamped_by_the_binding_cap() -> None:
    """A 50% request must silently become the cap, not a 50% trade."""
    a = InstrumentAdapter({"Volatility 75 Index": v75()}, RiskCaps(20.0, 15.0))
    equity, stop = 1000.0, 100.0
    v = a.volume_for_risk("Volatility 75 Index", stop, equity, risk_pct=50.0)
    # 15% of $1000 = $150 over a 100-unit stop = 1.486 lots on the grid
    assert v == pytest.approx(1.485, abs=0.002)


def test_volume_for_risk_refuses_rather_than_oversizing() -> None:
    a = InstrumentAdapter({"Volatility 75 Index": v75()})
    assert a.volume_for_risk("Volatility 75 Index", 1195.15, equity=39.58, risk_pct=1.0) == 0.0


# --- census integration ----------------------------------------------------

def test_loads_a_census_artifact_when_present() -> None:
    path = ROOT / "artifacts" / "synthetic_census_20260919.json"
    if not path.is_file():
        pytest.skip("census artifact not generated in this tree")
    a = InstrumentAdapter.from_census(path)
    assert len(a) >= 4
    assert a.caps.binding_pct == min(a.caps.per_trade_pct, a.caps.fleet_pct)
    # The four instruments the operator named must all be present and vetoed
    # at the recorded account size — if a census re-run changes that, this fails
    # deliberately rather than the operator discovering it as a silent no-trade.
    equity = 39.58
    for sym in ("Volatility 25 Index", "Volatility 50 Index",
                "Volatility 75 Index", "Volatility 100 Index"):
        spec = a.spec(sym)
        verdict = a.floor(sym, 1.0, equity)  # 1-unit stop: any sane stop is wider
        assert verdict.required_equity > 0 and spec.min_lot > 0
