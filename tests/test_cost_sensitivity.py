"""Pins for the cost-sensitivity study (`docs/GOLD_COST_SENSITIVITY_PROTOCOL.md`).

WHY THESE TESTS EXIST. The study's whole output is a table of "what happens as cost
rises", and there is one way to produce that table that looks perfect and is entirely
wrong: **patching a constant in one module while the trade pricer reads a different
module's copy.** `SPREAD_BPS` is defined in `gold_walkforward`, imported into
`gold_wfo_v2`, and imported again into `gold_daily_one`. `gold_wfo_v2._trade` reads its
own namespace at call time, so patching only the defining module leaves the pipeline
trading at `m = 1` — a flat table that still prints, still passes its fidelity control at
`m = 1`, and quietly reports that cost does not matter.

Two failure modes are therefore pinned here:

1. **A patch that does not reach the pricer.** `set_spread_mult` must move every module
   that holds the constant, and the change must be *observable in a trade's net R*, not
   just in a module attribute. The second half is the one that matters: an attribute-only
   assertion would pass even if `_trade` had cached the value.
2. **Cost that moves the wrong amount.** The cost delta between two multipliers must equal
   `bps/1e4 * entry / risk` exactly. A study reporting break-even in bps is worthless if
   the bps it swept is not the bps it charged.

The trade used in test 2 is built from constant bars, so its gross R is 0 *by
construction* and every R in its net is cost. That makes the arithmetic check exact
rather than approximate, and it means a failure here cannot be blamed on the market data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import gold_cost_sensitivity as gcs  # noqa: E402
import gold_daily_one as d1  # noqa: E402
import gold_walkforward as wf  # noqa: E402
import gold_wfo_v2 as w2  # noqa: E402

BASE = 1.073  # gold_walkforward.SPREAD_BPS at the time of the study


@pytest.fixture(autouse=True)
def _restore_spread():
    """Every test leaves the model where it found it, whatever it did to it."""
    before = (wf.SPREAD_BPS, w2.SPREAD_BPS, d1.SPREAD_BPS)
    yield
    wf.SPREAD_BPS, w2.SPREAD_BPS, d1.SPREAD_BPS = before


def _one_day_session() -> dict:
    """~3 days of flat M15 bars at $4,000, enough to clear the warmup and trade.

    Constant OHLC means the stop and target are never touched and the session flatten
    exits at the entry price, so gross R is exactly 0 and net R is exactly -(cost).
    """
    n = 700
    px = np.full(n, 4000.0)
    start = 1_700_000_000 - (1_700_000_000 % 900)
    epoch = start + np.arange(n) * 900
    return {
        "B": {"open": px, "high": px, "low": px, "close": px, "epoch": epoch},
        "hours": ((epoch // 3600) % 24).astype(int),
        "h4_ok_long": np.ones(n, dtype=bool),
        "h4_ok_short": np.zeros(n, dtype=bool),
        "atr": np.ones(n),
    }


def _net_r_at(m: float) -> dict:
    """The single trade's R, plus the entry price and risk the cost formula needs.

    `gold_wfo_v2._trade` returns only R and indices — it does not echo `entry` or
    `risk` — so they are read back off the fixture's own arrays at the entry bar rather
    than asked of the trade. Deriving them here (instead of typing 4000.0 and 2.0)
    keeps the check honest if the fixture's geometry is ever changed.
    """
    P = _one_day_session()
    gcs.set_spread_mult(m)
    cfg = {"stop_mult": 2.0, "rr": 1.5}
    trades = d1.simulate(P["B"], P["hours"], P["h4_ok_long"], P["h4_ok_short"],
                         P["atr"], cfg, start=w2.WARMUP_BARS, end=len(P["atr"]))
    assert trades, "fixture produced no trade; the test would pass vacuously"
    tr = trades[0]
    i = tr["entry_i"]
    return {"net_r": tr["net_r"], "gross_r": tr["gross_r"],
            "entry": float(P["B"]["close"][i]),
            "risk": cfg["stop_mult"] * float(P["atr"][i])}


def test_set_spread_mult_reaches_every_module_that_holds_it():
    gcs.set_spread_mult(2.0)
    assert wf.SPREAD_BPS == pytest.approx(BASE * 2.0)
    assert w2.SPREAD_BPS == pytest.approx(BASE * 2.0), "pricer would still use m=1"
    assert d1.SPREAD_BPS == pytest.approx(BASE * 2.0)
    gcs.set_spread_mult(0.0)
    assert (wf.SPREAD_BPS, w2.SPREAD_BPS, d1.SPREAD_BPS) == (0.0, 0.0, 0.0)


def test_spread_multiplier_reaches_the_trade_pricer_and_not_just_an_attribute():
    """The attribute test above is necessary; this is the sufficient one."""
    free = _net_r_at(0.0)
    charged = _net_r_at(1.0)
    spread_r = BASE / 1e4 * charged["entry"] / charged["risk"]
    assert charged["net_r"] - free["net_r"] == pytest.approx(-spread_r, rel=1e-9)


def test_cost_delta_is_exactly_proportional_to_the_multiplier():
    """`break-even in bps` is only meaningful if bps is what gets charged."""
    a = _net_r_at(1.0)
    b = _net_r_at(3.0)
    unit = BASE / 1e4 * a["entry"] / a["risk"]
    assert a["net_r"] - b["net_r"] == pytest.approx(2 * unit, rel=1e-9)


def test_gross_r_is_zero_in_the_fixture_so_every_r_in_net_is_cost():
    """Guards the fixture itself: if this drifts, the exactness above is lost."""
    free = _net_r_at(0.0)
    assert free["gross_r"] == pytest.approx(0.0, abs=1e-12)
    assert free["net_r"] < 0, "commission is charged even at m=0"


def test_zero_multiplier_zeroes_the_spread_but_not_the_commission():
    free = _net_r_at(0.0)
    comm_r = wf.COMMISSION_PER_LOT_RT / (free["risk"] * wf.USD_PER_UNIT_PER_LOT)
    assert free["net_r"] == pytest.approx(free["gross_r"] - comm_r, abs=1e-12)
