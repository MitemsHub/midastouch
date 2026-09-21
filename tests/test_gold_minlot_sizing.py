"""The size the arm really takes, and why no size makes the edge decidable.

Two things are pinned here, and they are different in kind.

The SIZING model is arithmetic that can be checked against a number the venue itself produced:
the EA's journal prints `FLOOR TABLE XAUUSD: stop=33.09 ($33.09) minlot=0.01` — one dollar of
stop distance per dollar of risk at the minimum lot. `dollars_per_r_minlot` must reproduce
that, or the whole min-lot table is measuring a different instrument.

The DECIDABILITY claim is a statement about what lot size can and cannot do, and what makes it
testable is that its numbers reproduce two independent sources: the frozen declaration's 766
(for 80% power from the DISCOVERY set's effect) and the governor's own `power_trades` for the
t-threshold sample. If either stops reproducing, the claim has quietly changed.

The governor hook itself is pinned too: passing `risk_usd_for` a constant must give the SAME
trades as the flat `risk_usd` argument, because the hook was added under a running certified
engine and every number in the frozen artifacts was produced without it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import gold_governed_wfo as gg          # noqa: E402
import gold_minlot_sizing as mls        # noqa: E402

ARTIFACT = REPO / "artifacts" / "gold_minlot_sizing.json"
FROZEN = REPO / "artifacts" / "gold_prereg_no_target.json"


class _Rules:
    account_size = 25000.0
    profit_target_pct = 5.0
    best_day_pct = 20.0
    daily_loss_limit_usd = 750.0

    def drawdown_floor_usd(self, peak: float) -> float:
        return peak * 0.94


def test_the_minlot_model_reproduces_the_eas_own_floor_table() -> None:
    """`stop=33.09 ($33.09) minlot=0.01` — the EA's line, from the venue's settled spec.

    33.09 is 2.0 x ATR(H1) at the moment that line was printed, and the dollars it risked at
    the minimum lot were the same 33.09. If this identity breaks, every dollar in the min-lot
    table is computed off a different instrument than the one that trades.
    """
    assert mls.MIN_LOT == 0.01
    assert mls.SETTLED_VALUE_PER_UNIT_PER_LOT == 100.0
    assert mls.dollars_per_r_minlot(16.545, 2.0) == pytest.approx(33.09, abs=0.01)
    # ...and the same identity on the no-target rule's own convention (1.0 x ATR)
    assert mls.dollars_per_r_minlot(12.0, 1.0) == pytest.approx(12.0)


def test_the_power_arithmetic_reproduces_the_frozen_declaration() -> None:
    """766 is the declared requirement, fixed BEFORE the run from the discovery effect.

    If this ever stops reproducing, the declaration and this arithmetic describe different
    tests — and the smaller number (481, from the primary set's larger effect) would silently
    upgrade a verdict, which is exactly what it must never do.
    """
    assert mls.n_for_power(0.3221, 3.1838) == 766
    assert mls.n_for_power(0.15, 1.10) == 422          # the forward cell's declared MDE
    assert mls.n_for_power(0.0, 1.0) is None
    assert mls.n_for_power(0.1, 0.0) is None


def test_the_threshold_sample_uses_the_frozen_helper() -> None:
    for mean, sd in ((0.4230, 3.3110), (0.3221, 3.1838), (0.15, 1.10)):
        assert mls.n_for_threshold(mean, sd, 1.96) == gg.power_trades(mean, sd, 1.96)


def test_the_per_trade_hook_is_backward_compatible() -> None:
    """The hook was added under a running engine: a constant hook must change NOTHING."""
    trades = [{"entry_i": i, "net_r": r} for i, r in enumerate([1.0, -1.0, 0.5, -1.0, 2.0])]
    epoch = np.array([1789000000 + 3600 * i for i in range(5)], dtype="int64")
    flat = gg.govern(trades, epoch, rules=_Rules(), risk_usd=250.0)
    hooked = gg.govern(trades, epoch, rules=_Rules(), risk_usd=250.0,
                       risk_usd_for=lambda t: 250.0)
    assert flat == hooked


def test_a_per_trade_risk_changes_the_governors_arithmetic() -> None:
    """...and a varying one must actually bite, or the hook is decoration."""
    trades = [{"entry_i": i, "net_r": r} for i, r in enumerate([1.0] * 10 + [-8.0] * 3)]
    epoch = np.array([1789000000 + 3600 * i for i in range(13)], dtype="int64")
    big = gg.govern(trades, epoch, rules=_Rules(), risk_usd=250.0)
    small = gg.govern(trades, epoch, rules=_Rules(), risk_usd_for=lambda t: 12.0)
    assert len(big[0]) != len(small[0]), (
        "the same trades at different dollars-per-R must produce different books; otherwise "
        "the min-lot table is the flat table with a different label")


@pytest.mark.skipif(not ARTIFACT.is_file(), reason="run scripts/gold_minlot_sizing.py")
class TestTheArtifact:
    @staticmethod
    def _a() -> dict:
        return json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_the_flat_rows_reproduce_the_frozen_prereg_artifact(self) -> None:
        """The two tables must be the same machinery, so the only difference is sizing."""
        a = self._a()
        assert a["sizing"]["flat_rows_reproduce_the_frozen_artifact"] is True
        assert a["sizing"]["flat_rows_mismatch"] == []
        if FROZEN.is_file():
            frozen = json.loads(FROZEN.read_text(encoding="utf-8"))["sizing_scan_post_hoc"]
            got = a["sizing"]["flat_rows"]
            assert [(r["risk_pct"], r["worst_day_usd"], r["trades_kept"]) for r in got] == \
                   [(r["risk_pct"], r["worst_day_usd"], r["trades_kept"]) for r in frozen]

    def test_the_min_lot_row_keeps_every_day_inside_the_venue_line(self) -> None:
        row = self._a()["sizing"]["min_lot_row"]
        assert row["days_beyond_daily_limit"] == 0
        assert row["headroom_usd"] > 0
        assert row["worst_day_usd"] > -row["daily_limit_usd"]
        assert row["worst_day_pct_of_account"] < 3.0

    def test_the_decidability_claim_is_recorded_and_does_not_upgrade_the_verdict(self) -> None:
        d = self._a()["decidability"]
        assert d["lot_size_enters_the_arithmetic"] is False
        assert d["n_for_power_80"] and d["n_for_threshold_1_96"]
        assert d["n_for_power_80"] < d["n"] < 766, (
            "the post-hoc requirement must be SMALLER than the declared one — that is the whole "
            "reason it is labelled post-hoc — while the declared 766 stays binding")
        note = d["post_hoc_not_the_declared_requirement"]
        assert "766" in note and "POSITIVE, UNDERPOWERED" in note
        assert "never applied as a decision" in note

    def test_the_caveat_says_which_geometry_the_row_is_not(self) -> None:
        """1.0xATR R on the no-target rule is NOT the armed arm's 2.0xATR R."""
        c = self._a()["caveat"]
        assert "2.0xATR" in c and "minimum lot" in c
