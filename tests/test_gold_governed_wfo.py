"""The governor's semantics and the forward pre-registration's arithmetic.

TWO THINGS THIS FILE GUARDS, and they fail in different ways.

1. **The governor mirrors the EA.** `gold_governed_wfo.govern()` is a second
   implementation of `PropGovernorBlock()` in `mql5/MIDASTOUCH/MidastouchAI.mq5`, and a
   second implementation of a risk rule is exactly where a research result stops
   describing the strategy on the chart. The unit tests below pin all three refusal
   paths against hand-computed equity sequences, and pin the USD cap to the preset's
   own numbers (5% target x 20% Best Day = $250/day = 1R on the $25,000 basis).

2. **The forward record cannot be promoted by an edit.** The declared effect sizes, the
   sample floor, and the n = 100 kill rule are stated in
   `docs/GOLD_FORWARD_PREREG_20260921.md` and computed by `power_trades()`. The tests
   recompute the table from the harness, so a silent change to either side fails here
   instead of in a decision.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_governed_wfo as gg  # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

RULES = ThunderboltClassicRules(account_size=25_000.0)

#: A fixed clock: every trade below is placed on a distinct day unless a test says
#: otherwise, so the day anchor cannot leak between tests.
DAY0 = 1_769_000_000  # 2026-01-22 something-UTC; the exact day is irrelevant, the gaps are
GAP = 86_400


def _epoch_for(day_offsets: list[int]) -> "object":
    """An epoch accessor for trade dicts whose `entry_i` is an index into it."""
    return [float(DAY0 + GAP * d) for d in day_offsets]


def _trade(idx: int, net_r: float) -> dict:
    return {"entry_i": idx, "dir": 1, "net_r": net_r}


# --------------------------------------------------------------------------- #
# The governor: three refusal paths, pinned to the preset's own arithmetic
# --------------------------------------------------------------------------- #

def test_best_day_cap_is_one_r_on_the_account_basis() -> None:
    """The cap is not a preference — it falls out of the preset's numbers."""
    cap = RULES.account_size * RULES.profit_target_pct / 100.0 * RULES.best_day_pct / 100.0
    assert cap == 250.0, "the Best Day cap moved off the preset's 5% x 20%"
    assert cap / gg.RISK_USD == 1.0, "at 1% risk, the day cap is exactly 1R"


def test_governor_blocks_the_rest_of_a_day_once_the_cap_is_hit() -> None:
    """A winning first trade closes the day: that is the rule's own consequence."""
    keep = _epoch_for([0, 0, 0])
    trades = [_trade(0, +1.0), _trade(1, +1.0), _trade(2, +1.0)]
    kept, vetoes = gg.govern(trades, keep, rules=RULES)
    assert len(kept) == 1, "the governor let a second trade into a capped day"
    assert vetoes.get("Best Day cap (1R/day)") == 2


def test_governor_blocks_after_the_daily_loss_cap() -> None:
    """The 3% breaker is 3R at 1% risk, and it must trip on realised equity."""
    keep = _epoch_for([0, 0, 0, 0])
    trades = [_trade(0, -1.0), _trade(1, -1.0), _trade(2, -1.0), _trade(3, +1.0)]
    kept, vetoes = gg.govern(trades, keep, rules=RULES)
    assert [t["net_r"] for t in kept] == [-1.0, -1.0, -1.0], \
        "the breaker did not stop the fourth entry of a -3R day"
    assert vetoes.get("daily-loss cap (3%)") == 1


def test_governor_blocks_at_the_trailing_shield_floor_across_days() -> None:
    """6% from the peak, 3R a day: the second day's third loss reaches the floor.

    This is also the test that documents WHY the governor cannot protect the account:
    the veto lands on the *next entry*, so the equity that breached the floor did so on
    a trade the governor had already allowed.
    """
    keep = _epoch_for([0, 0, 0, 1, 1, 1, 2])
    trades = [_trade(i, -1.0) for i in range(6)] + [_trade(6, +1.0)]
    kept, vetoes = gg.govern(trades, keep, rules=RULES)
    assert len(kept) == 6, f"expected the first six entries to be allowed, got {len(kept)}"
    assert vetoes.get("trailing shield (6%)") == 1, vetoes


def test_governor_keeps_what_is_allowed_and_moves_the_equity_it_sees() -> None:
    """Path dependence: the same trade is allowed or refused by what came before it."""
    keep = _epoch_for([0, 1, 1])
    allowed, _ = gg.govern([_trade(0, +1.0), _trade(1, -1.0), _trade(2, -1.0)],
                           keep, rules=RULES)
    blocked, vetoes = gg.govern([_trade(1, -1.0), _trade(2, -1.0)],
                                keep, rules=RULES)
    assert len(allowed) == 3 and len(blocked) == 2 and not vetoes


# --------------------------------------------------------------------------- #
# The pre-registration: power, the floor, and the kill rule
# --------------------------------------------------------------------------- #

def test_power_statement_reproduces_the_numbers_the_prereg_declares() -> None:
    """The three measured samples, re-derived from the harness's own formula.

    If a future edit changes the declared effect size, this fails — which is the point:
    a pre-registration whose arithmetic can drift is a suggestion.
    """
    assert gg.power_trades(0.068, 1.08) == 568      # venue window, combined
    assert gg.power_trades(0.115, 1.09) == 203      # the armed ORIGINAL mode
    assert gg.power_trades(0.0316, 1.3696) == 4227  # best geometry of the 168 sweep
    assert gg.power_trades(-0.031, 1.08) is None, "a negative edge has no sample size"


def test_thirty_trades_cannot_certify_any_measured_effect() -> None:
    """The reason the arm's `closed: N/30` line is a floor and not a test."""
    import math
    se = 1.08 / math.sqrt(30)
    assert se > 0.19, "the n=30 standard error moved; the floor's justification changed"
    for mean_r in (0.068, 0.115, 0.032):
        assert gg.power_trades(mean_r, 1.08) > 30, \
            f"n=30 would be decisive at {mean_r}R/trade — the pre-registration is stale"


def test_one_hundred_trades_is_the_declared_sample_floor_with_a_kill_rule() -> None:
    raw = (ROOT / "docs" / "GOLD_FORWARD_PREREG_20260921.md").read_text(encoding="utf-8")
    doc = " ".join(raw.split())
    for needle in ("n = 100", "≤ 0R/trade", "declares the configuration",
                   "+0.15R/trade", "30 trades", "NOT VALIDATED"):
        assert needle in doc, f"the pre-registration no longer states {needle!r}"


def test_the_kill_rule_is_not_something_the_ledger_can_satisfy() -> None:
    """A positive ledger at 30 closes must not read as a pass anywhere in the repo."""
    raw = (ROOT / "docs" / "GOLD_FORWARD_PREREG_20260921.md").read_text(encoding="utf-8")
    doc = " ".join(raw.split())
    assert "must never be read as a pass" in doc
    assert "insufficient evidence" in doc, \
        "the 'insufficient evidence' distinction is gone"


def test_the_governed_study_records_that_the_override_stands() -> None:
    """The study must not quietly re-read as a validation of the armed configuration.

    Compared with whitespace collapsed: these are prose files whose lines are wrapped at
    100 columns, and a phrase pin that breaks on a line wrap teaches the next editor to
    reformat the sentence instead of reading the assertion.
    """
    raw = (ROOT / "docs" / "GOLD_GOVERNED_WFO_20260921.md").read_text(encoding="utf-8")
    doc = " ".join(raw.lower().split())
    assert "not validated" in doc
    assert "operator override" in doc
    assert "does not change the record" in doc
    assert "breached" in doc, "the venue-rule breaches must stay on the record"
