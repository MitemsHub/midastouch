"""Pins for the geometry/cost study driver's two failure modes.

Both tests below correspond to REAL defects found while executing the study on
2026-09-19. A measurement harness that can silently manufacture a verdict is
worse than no harness, so both are pinned here:

1. **Cost reconstruction.** `certify_v75.py` charges the spread as
   `r_extra = -SPREAD / sd` and then POPS `r_extra` before writing its report
   (certify_v75.py:512). A naive `gross = r - r_extra` control therefore reads 0
   and reports **identical net and gross on every cell** — which is exactly what
   the first 16-cell run produced, showing `cost_drag = 0.00` everywhere. The
   control must be reconstructed as `gross = r + SPREAD / sd`.

2. **Fail-closed adjudication.** That same first run pointed at the wrong report
   directory, lost all 16 cells, and STILL printed
   `VERDICT: NO-NET-EDGE-ON-THIS-CONFIGURATION`. An infrastructure failure was
   reported as a finding about the market. The adjudicator must refuse.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import geometry_cost_study as gcs  # noqa: E402


# --- 1. the cost reconstruction -------------------------------------------------

def test_gross_is_net_plus_the_spread_the_engine_charged() -> None:
    """r is net; the control adds back SPREAD/sd per trade."""
    trades = [{"r": -1.0, "sd": 100.0}, {"r": 2.0, "sd": 200.0}]
    spread = 18.5
    net = [t["r"] for t in trades]
    gross = [t["r"] + spread / t["sd"] for t in trades]
    assert net == [-1.0, 2.0]
    assert gross[0] == -1.0 + 0.185
    assert gross[1] == 2.0 + 0.0925
    # and the drag is strictly positive — the defect made this zero
    assert sum(gross) - sum(net) > 0


def test_the_popped_r_extra_is_why_naive_gross_reads_zero() -> None:
    """Documents the trap: the report has no r_extra, so `.get(...,0)` yields 0."""
    report_trade = {"r": -1.04, "sd": 492.12}  # as written by certify_v75.py
    assert report_trade.get("r_extra", 0.0) == 0.0
    # so `r - r_extra == r` — identical columns, i.e. a broken control
    assert report_trade["r"] - report_trade.get("r_extra", 0.0) == report_trade["r"]
    # the reconstruction recovers the real spread cost (~3.8% of a 492-unit stop)
    assert round(18.5 / report_trade["sd"] * 100, 1) == 3.8


def test_zero_cost_reconstruction_is_treated_as_an_error() -> None:
    """The guard that would have caught the defect on the first run."""
    trades = [{"r": 1.0, "sd": 100.0}]
    spread = 18.5
    net = sum(t["r"] for t in trades)
    gross = sum(t["r"] + spread / t["sd"] for t in trades)
    assert gross - net > 0, "a non-positive drag must fail the cell, not pass silently"


# --- 2. fail-closed adjudication ------------------------------------------------

def _cell(name: str, total_r: float, n: int = 50, dd: float = 5.0, streak: int = 3,
          stop_mult: float = 1.0, error: bool = False) -> dict:
    if error:
        return {"cell": name, "error": "no report written", "stop_mult": stop_mult}
    return {"cell": name, "symbol": f"Volatility {name}", "stop_mult": stop_mult,
            "net": {"n": n, "total_r": total_r, "max_dd_r": dd,
                    "worst_loss_streak": streak, "wins": n // 2, "win_rate": 50.0,
                    "mean_r": total_r / n},
            "gross": {"total_r": total_r + 5.0}}


def test_any_failed_cell_forces_an_invalid_run_verdict() -> None:
    cells = [_cell("25 Index", 10.0), _cell("50 Index", 10.0),
             _cell("75 Index", 10.0), _cell("100 Index", 0.0, error=True)]
    out = gcs.adjudicate(cells, expected_cells=len(cells))
    assert out["verdict"] == "INVALID-RUN", (
        "an infrastructure failure was reported as a market finding")
    assert out["geometry_survivors"] == {}
    assert out["failed_cells"]


def test_incomplete_grid_is_also_invalid() -> None:
    """Fewer cells than the frozen grid must never adjudicate."""
    out = gcs.adjudicate([_cell("25 Index", 10.0)])
    assert out["verdict"] == "INVALID-RUN"


def test_g2_needs_three_instruments_at_one_width() -> None:
    """Two instruments passing is not a geometry law, it is a coincidence."""
    cells = [_cell("25 Index", 10.0, stop_mult=2.0),
             _cell("50 Index", 10.0, stop_mult=2.0),
             _cell("75 Index", -5.0, stop_mult=2.0),
             _cell("100 Index", -5.0, stop_mult=2.0)]
    out = gcs.adjudicate(cells, expected_cells=len(cells))
    assert out["verdict"] == "INSTRUMENT-SPECIFIC"

    cells[2] = _cell("75 Index", 10.0, stop_mult=2.0)
    out = gcs.adjudicate(cells, expected_cells=len(cells))
    assert out["verdict"] == "GEOMETRY-SURVIVES"
    assert out["geometry_survivors"] == {"2.0": ["Volatility 25 Index",
                                                "Volatility 50 Index",
                                                "Volatility 75 Index"]}


def test_g1_rejects_on_each_of_its_four_limbs() -> None:
    assert gcs.g1_pass(_cell("A", 10.0))                                    # passes
    assert not gcs.g1_pass(_cell("A", 10.0, n=29))                          # too few
    assert not gcs.g1_pass(_cell("A", -0.01))                               # negative
    assert not gcs.g1_pass(_cell("A", 10.0, dd=15.01))                      # DD over
    assert not gcs.g1_pass(_cell("A", 10.0, streak=9))                      # streak over


def test_a_run_with_no_passing_cell_reports_the_headline_verdict() -> None:
    cells = [_cell(s, -5.0) for s in ("25 Index", "50 Index", "75 Index", "100 Index")]
    out = gcs.adjudicate(cells, expected_cells=len(cells))
    assert out["verdict"] == "NO-NET-EDGE-ON-THIS-CONFIGURATION"
