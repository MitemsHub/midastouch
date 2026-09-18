"""Tier 3 — Strategy Tester regression gate for V75MacroEngine (opt-in).

Turns the manual tester validation into a repeatable gate: two headless
real-tick passes on the fully-cached 71-day window, asserting the fill /
exit / R-accounting invariants established by the v1.25 validation.

What the gate pins (evidence: artifacts/v75_macro_engine_tester/, 2026-09-11):
  * exit OFF (spec contract):  13 fills, -176.50 USD, PF 0.35, 13 timeout
    exits, 0 SL modifications, 0 modify failures, R sum -1.79
  * trail opt-in (0.2R / 1.0x ATR): 15 fills, -16.65 USD, PF 0.81, 25 SL
    ratchets, 0 modify failures, R sum -0.17

Both passes must self-identify via the EA's init-time "Exit manager:" print;
fills must land on M30 bar opens; every trade must reconcile exactly once
(one POSITION CLOSED mark per trade).

Run:  V75_TESTER_TESTS=1 pytest tests/test_v75_tester_gate.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ for the runner
from v75_tester_runner import DEPOSIT, run_pass

pytestmark = pytest.mark.skipif(
    not os.environ.get("V75_TESTER_TESTS"),
    reason="tester tier disabled: set V75_TESTER_TESTS=1 (runs the real MT5 "
           "Strategy Tester, ~3 min)",
)

EXPECTED_OFF = {
    "fills": 13, "pnl": -176.50, "pf": 0.35,
    "sl_moves": 0, "modify_fails": 0, "r_sum": -1.79,
    "identity": "OFF (SL/TP + timeout only)",
}
EXPECTED_TRAIL = {
    "fills": 15, "pnl": -16.65, "pf": 0.81,
    "sl_moves": 25, "modify_fails": 0, "r_sum": -0.17,
    "identity": "Breakeven @ 0.20R + ATR trail 1.00x",
}
PNL_TOL = 0.5          # USD; same ticks => near-exact, tolerance absorbs rounding
RSUM_TOL = 0.02
PF_TOL = 0.02


@pytest.fixture(scope="module")
def off_pass() -> dict:
    return run_pass("off", {"InpExitManager": "0", "InpTradeTimeoutHours": "3"})


@pytest.fixture(scope="module")
def trail_pass() -> dict:
    return run_pass(
        "trail",
        {"InpExitManager": "2", "InpBETriggerR": "0.2",
         "InpBEOffsetPoints": "10", "InpTrailATRMult": "1.0",
         "InpTradeTimeoutHours": "3"},
    )


# --- the run is what we think it is -----------------------------------------

def test_off_pass_ran_in_off_mode(off_pass: dict) -> None:
    assert EXPECTED_OFF["identity"] in off_pass["journal"]["identity"]


def test_trail_pass_ran_in_trail_mode(trail_pass: dict) -> None:
    assert EXPECTED_TRAIL["identity"] in trail_pass["journal"]["identity"]


# --- fills: entry layer unchanged --------------------------------------------

def test_off_fill_count(off_pass: dict) -> None:
    assert off_pass["report"]["fills"] == EXPECTED_OFF["fills"]


def test_trail_fill_count(trail_pass: dict) -> None:
    assert trail_pass["report"]["fills"] == EXPECTED_TRAIL["fills"]


def test_entries_fires_on_m30_bar_open(off_pass: dict, trail_pass: dict) -> None:
    for res in (off_pass, trail_pass):
        assert res["report"]["entries_on_bar_open"], "entry deviated from M30 bar open"


# --- exits: geometry + accounting exactly once -------------------------------

def test_off_all_exits_are_timeout_backstop(off_pass: dict) -> None:
    rep = off_pass["report"]
    assert rep["sl_hits"] == 0 and rep["tp_hits"] == 0
    assert rep["exits"] == rep["fills"]          # every fill exited
    assert off_pass["journal"]["timeouts"] == EXPECTED_OFF["fills"]


def test_trail_exit_split(trail_pass: dict) -> None:
    rep = trail_pass["report"]
    assert rep["exits"] == rep["fills"]
    assert trail_pass["journal"]["sl_moves"] == EXPECTED_TRAIL["sl_moves"]
    assert trail_pass["journal"]["modify_fails"] == 0


def test_position_closed_reconciled_exactly_once(off_pass: dict, trail_pass: dict) -> None:
    for res, exp in ((off_pass, EXPECTED_OFF), (trail_pass, EXPECTED_TRAIL)):
        assert res["journal"]["closed_marks"] == exp["fills"], (
            "R accounting must run exactly once per trade (single cleanup path)"
        )


# --- P&L / R ledger -----------------------------------------------------------

def test_off_pnl_and_r(off_pass: dict) -> None:
    rep, jr = off_pass["report"], off_pass["journal"]
    assert rep["pnl"] == pytest.approx(EXPECTED_OFF["pnl"], abs=PNL_TOL)
    assert rep["pf"] == pytest.approx(EXPECTED_OFF["pf"], abs=PF_TOL)
    assert jr["r_sum"] == pytest.approx(EXPECTED_OFF["r_sum"], abs=RSUM_TOL)
    assert jr["final_balance"] == pytest.approx(DEPOSIT + EXPECTED_OFF["pnl"], abs=PNL_TOL)


def test_trail_pnl_and_r(trail_pass: dict) -> None:
    rep, jr = trail_pass["report"], trail_pass["journal"]
    assert rep["pnl"] == pytest.approx(EXPECTED_TRAIL["pnl"], abs=PNL_TOL)
    assert rep["pf"] == pytest.approx(EXPECTED_TRAIL["pf"], abs=PF_TOL)
    assert jr["r_sum"] == pytest.approx(EXPECTED_TRAIL["r_sum"], abs=RSUM_TOL)
