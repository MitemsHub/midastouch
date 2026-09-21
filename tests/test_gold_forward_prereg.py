"""Pins for the arm-level forward pre-registration — the arithmetic it declares, and its kill rule.

WHY THIS FILE EXISTS. `docs/GOLD_FORWARD_PREREG_20260921.md` is the document that makes the live
operator override **bounded**: it names the sample that could confirm the arm, the number that kills
it, and the fact that neither exists yet. Its §5 names this file as the thing that enforces the
arithmetic. Until now that claim was false — the file did not exist, so a sentence in a live
document pointed at an enforcing mechanism that was not there. Creating it is the correction; the
tests below are what the sentence promised.

The numbers pinned here are the document's own, and the engine's `power_trades()` is the function
they must agree with, so a future edit that quietly changes the declared effect size, the
dispersion, or the threshold fails the suite rather than the operator's expectations.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_governed_wfo as gg  # noqa: E402

DOC = ROOT / "docs" / "GOLD_FORWARD_PREREG_20260921.md"

#: §1's table: (mean R/trade, sd R, SE at n=30, the effect 30 trades can distinguish at 1.96).
MEASURED = ((0.068, 1.08, 0.197, 0.40), (0.115, 1.09, 0.199, 0.40), (0.032, 1.37, 0.250, 0.50))


@pytest.mark.parametrize("mean_r,sd,se,resolvable", MEASURED)
def test_thirty_trades_cannot_distinguish_anything_this_program_has_measured(
        mean_r: float, sd: float, se: float, resolvable: float):
    """The reason the document exists: at n=30 the resolvable effect dwarfs every measured one."""
    assert sd / (30 ** 0.5) == pytest.approx(se, abs=5e-4)
    # the document rounds to the nearest 0.01R: 0.386/0.390 -> 0.40, 0.490 -> 0.50
    assert 1.96 * (sd / (30 ** 0.5)) == pytest.approx(resolvable, abs=0.02)
    # The multiple is 3.4x (armed mode), 5.7x (window combined) and 15x (sweep best) — so the
    # document's "three to fifteen times" is the claim, and a wider one would be an overstatement.
    ratio = (1.96 * sd / (30 ** 0.5)) / abs(mean_r)      # exact, not from the rounded column
    assert 3.0 <= ratio <= 16.0
    assert ratio == pytest.approx({0.068: 5.68, 0.115: 3.39, 0.032: 15.32}[mean_r], abs=0.05)


def test_the_hundred_trade_sample_and_the_gate_threshold_agree_with_the_document():
    """§2's substitution rate, and the ~120 trades it says a +0.15R edge needs at t>=1.5."""
    sd = 1.09
    assert sd / 10.0 == pytest.approx(0.109, abs=1e-3)          # SE at n=100
    assert 0.15 / 0.109 == pytest.approx(1.38, abs=0.01)        # t at the 100-trade sample
    assert gg.power_trades(0.15, sd, 1.5) == 119                # the document says "≈ 120"
    assert gg.power_trades(0.15, sd, 1.5) == pytest.approx(120, abs=1)


def test_the_engine_quotes_only_reproducible_sample_arithmetic():
    """The docstring's figures must come out of the function's own formula.

    It used to quote "~27,657" labelled as the figure for 0.068R/trade (sd 1.09). No sd reproduces
    that: 0.068R at sd 1.09 is 579, and the mean 27,657 belongs to is 0.0098R — the arm's deployed
    exit, not the window's combined edge. Both are pinned here so the pairing cannot drift again.
    """
    assert gg.power_trades(0.068, 1.09, 1.5) == 579
    assert gg.power_trades(0.010, 1.09, 1.5) == 26_733
    text = (ROOT / "scripts" / "gold_governed_wfo.py").read_text(encoding="utf-8")
    assert "0.068R/trade it is 579" in text, (
        "the power_trades docstring must quote the figure its own formula produces for 0.068R")
    assert "0.010R/trade it is 26,733" in text
    assert "~27,657 (99 years" not in text, (
        "that sentence paired 27,657 with 0.068R, which no sd reaches; the figure belongs to "
        "~0.0098R")


def test_the_document_states_the_pass_conditions_and_the_kill_rule():
    """A pre-registration without its kill rule is a wish; both have to stay in the text."""
    text = DOC.read_text(encoding="utf-8")
    for needle in ("**100** closed trades", "t ≥ 1.5", "mean of **≤ 0R/trade**",
                   "**dead**", "No re-specification after seeing the sample"):
        assert needle in text, f"the arm-level pre-registration no longer states {needle!r}"
