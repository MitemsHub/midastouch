"""The EA's own sizing, mirrored — and pinned against the MQL5 it is mirrored from.

WHY THIS FILE EXISTS. `scripts/verify_sizing_live.py` prints two sizes: the one it
computes from the venue's daily loss limit, and the one the deployed EA would actually
send. The second is a *mirror* of MQL5 code, and a mirror that is not pinned is a
second source of truth waiting to disagree with the first — the exact failure this
repository keeps paying for (the spec fields vs the broker, the two bar series, the
chart timeframe vs the entry timeframe).

So the arithmetic is tested twice over:

1. against the numbers the U25 arm really has (0.25% of $25,000 = $62.50 budget, a
   31.84 stop, a 0.01 lot step, which lands on the venue's minimum lot and HALF the
   configured risk); and
2. against the text of `MidastouchAI.mq5` → `LiveSendOrder()`, which must still
   contain every step this module performs. Prose is not matched here: the pins are
   the actual arithmetic lines, so a re-sorted or re-derived sizing site fails.

The tests are pure: no terminal, no MT5, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from midas_prop.execution.prop_execution import (  # noqa: E402
    BEST_DAY_HEADROOM,
    ContractSpec,
    EaSizing,
    size_like_ea,
)

MQ5 = ROOT / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"

#: The instrument as the venue measures it: $100 per 1.0 price-unit move per lot
#: (`order_calc_profit`, 2026-09-21 — the spec fields claim $10 and are wrong).
SPEC = ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01, max_lot=100.0,
                    digits=2, usd_per_unit_per_lot=100.0,
                    basis="order_calc_profit")

#: The U25 arm: equity, InpRiskPercent, InpMaxRiskPct, and the stop width the EA's
#: 2.0 x ATR(H1,14) produced on 2026-09-21.
U25 = dict(equity=25_000.0, risk_percent=0.25, max_risk_pct=15.0,
           stop_distance_price=31.84)


def _ea(**kw) -> EaSizing:
    return size_like_ea(SPEC, **{**U25, **kw})


# --------------------------------------------------------------------------- #
# The U25 numbers
# --------------------------------------------------------------------------- #


def test_the_u25_arm_is_quantised_down_to_half_its_configured_risk():
    """The measurement that motivated the two-size report.

    `InpRiskPercent=0.25` of $25,000 is a $62.50 budget. At a 31.84 stop the venue's
    0.01 step gives 0.01 lots = $31.84, so the arm trades 0.127% of equity while its
    preset says 0.25%. The EA's log cannot express this (its FLOORED flag only marks
    the min-lot branch), so it is derived from the numbers here.
    """
    ea = _ea()
    assert ea.ok and not ea.vetoed
    assert ea.budget_usd == pytest.approx(62.50)
    assert ea.lots == pytest.approx(0.01)
    assert ea.risk_usd == pytest.approx(31.84)
    assert ea.risk_pct_of_equity == pytest.approx(0.0012736, rel=1e-3)
    assert ea.quantised_down, ea.note()
    assert "QUANTISED DOWN" in ea.note()
    assert "$30.66" in ea.note(), "the unspent budget is the number that explains it"


def test_the_budget_is_the_configured_percentage_of_equity():
    ea = _ea(risk_percent=1.0)
    assert ea.budget_usd == pytest.approx(250.0)
    # 250 / (31.84 * 100) = 0.0785... -> floors to 0.07 lots
    assert ea.lots == pytest.approx(0.07)
    assert ea.risk_usd == pytest.approx(0.07 * 31.84 * 100)
    assert ea.quantised_down


def test_a_size_that_matches_the_budget_exactly_is_not_flagged():
    """A stop of 25.00 makes 0.10 lots land exactly on a 1.0% budget of $250."""
    ea = _ea(risk_percent=1.0, stop_distance_price=25.0)
    assert ea.lots == pytest.approx(0.10)
    assert ea.risk_usd == pytest.approx(250.0)
    assert not ea.quantised_down
    assert "QUANTISED DOWN" not in ea.note()


def test_a_raw_size_below_the_minimum_takes_the_minimum_and_says_it_is_over_budget():
    """A $3,000 arm's 0.25% is $7.50, which buys 0.0024 lots — below the venue's
    minimum, so the EA takes 0.01 lots. That order risks $31.84 against a $7.50 budget:
    four times the configured percentage, which is the fact that matters for survival.
    Amendment 6 does not catch it (the cap here is 15% of equity)."""
    ea = _ea(equity=3_000.0)
    assert ea.lots == pytest.approx(0.01)
    assert ea.floored
    assert ea.over_budget and not ea.quantised_down
    assert not ea.vetoed
    assert "OVER BUDGET" in ea.note()
    assert "4.25x" in ea.note(), ea.note()


def test_the_min_lot_is_a_veto_when_it_would_breach_the_risk_cap():
    """Amendment 6: a $150 arm sized at 0.25% cannot take a 0.01 lot that risks
    $31.84 against a 15% cap of $22.50. The EA refuses; it does not round up."""
    ea = _ea(equity=150.0)
    assert ea.vetoed and not ea.ok
    assert ea.lots == 0.0 and ea.risk_usd == 0.0
    assert "REFUSES" in ea.note() and "amendment 6" in ea.note()


def test_exactly_at_the_cap_is_not_a_veto():
    """The predicate is strict (`>`), as in the MQL5: a min-lot risk exactly at the
    cap is allowed, one cent over is refused."""
    # equity 212.2667 -> 15% = 31.84 exactly
    at = _ea(equity=31.84 / 0.15)
    assert not at.vetoed and at.lots == pytest.approx(0.01)
    over = _ea(equity=31.84 / 0.15 - 0.01)
    assert over.vetoed


def test_a_size_above_max_lot_is_reported_not_clamped():
    """The EA never reads volume_max, so the mirror must not silently clamp — it
    reports what the venue would reject."""
    small = ContractSpec(symbol="XAUUSD", min_lot=0.01, lot_step=0.01, max_lot=10.0,
                         digits=2, usd_per_unit_per_lot=100.0,
                         basis="order_calc_profit")
    ea = size_like_ea(small, equity=25_000.0, risk_percent=0.25, max_risk_pct=15.0,
                      stop_distance_price=0.01)
    assert ea.lots == pytest.approx(62.5)
    assert any("max_lot" in w for w in ea.warnings), ea.warnings


def test_malformed_inputs_raise_rather_than_returning_a_refusal():
    for kw in ({"equity": 0.0}, {"risk_percent": 0.0}, {"max_risk_pct": 0.0},
               {"stop_distance_price": 0.0}, {"stop_distance_price": -1.0}):
        with pytest.raises(ValueError):
            _ea(**kw)


# --------------------------------------------------------------------------- #
# The mirror against the source it mirrors
# --------------------------------------------------------------------------- #


def _mql_function(name: str) -> str:
    """The body of one MQL5 function, from its signature to its closing brace.

    The close is the first `}` at column 0, because the EA indents every statement
    inside a function; a nested brace lands indented.
    """
    text = MQ5.read_text(encoding="utf-8", errors="replace")
    start = text.index(f"bool {name}(")
    end = text.index("\n}\n", start)
    return text[start:end]


#: Each step of EaSizing, as the line that must still be in the EA.
LIVE_STEPS = (
    "double equity = AccountInfoDouble(ACCOUNT_EQUITY);",
    "double risk_d = equity * InpRiskPercent / 100.0;",
    "double lots = risk_d / (stop_d * dpu);",
    "if(lots < vmin)",
    "if(stop_d * dpu * vmin > equity * InpMaxRiskPct / 100.0)",
    "lots = vmin; floored = true;",
    "if(vstep > 0) lots = MathFloor(lots / vstep) * vstep;",
    "if(lots < vmin) { lots = vmin; floored = true; }",
)

#: The paper path must stay the same arithmetic on a different basis — if the two
#: drift, the paper ledger stops describing what the live arm would have done.
PAPER_STEPS = (
    "double risk_d = PaperEquity() * InpRiskPercent / 100.0;",
    "stop_d * dpu * vmin > PaperEquity() * InpMaxRiskPct / 100.0",
)

#: The BAR-replay path (the tester mirror), which sizes on the paper book and spells
#: the minimum lot out longhand. Same arithmetic, so the same mirror covers it.
BAR_STEPS = (
    "double risk_d = PaperEquity() * InpRiskPercent / 100.0;",
    "double lots = risk_d / (stop_d * dpu);",
    "stop_d * dpu * SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)",
    "InpMaxRiskPct",
)


def test_the_live_sizing_steps_are_all_still_in_the_ea():
    body = _mql_function("LiveSendOrder")
    for step in LIVE_STEPS:
        assert step in body, (
            f"LiveSendOrder no longer contains {step!r} — EaSizing mirrors this site "
            f"and would now be a second, disagreeing source of truth")


def test_the_paper_sizing_site_still_matches_on_its_own_basis():
    body = _mql_function("OpenPaperPosition")
    for step in PAPER_STEPS:
        assert step in body, (
            f"OpenPaperPosition no longer contains {step!r} — the paper book sizes on "
            f"a different basis than the mirror assumes")


def test_the_bar_replay_sizing_site_is_pinned_too():
    body = _mql_function("BarFillAndManage")
    for step in BAR_STEPS:
        assert step in body, (
            f"BarFillAndManage no longer contains {step!r} — the BAR replay would size "
            f"differently from the live site the mirror is built on")


def test_the_min_lot_veto_exists_at_every_sizing_site():
    """A veto present at only one site is a rule the other sites can breach."""
    for fn in ("LiveSendOrder", "OpenPaperPosition", "BarFillAndManage"):
        body = _mql_function(fn)
        assert "InpMaxRiskPct" in body, fn


def test_no_third_sizing_site_has_appeared():
    """Three sites size a position; every one is pinned above. A fourth would not be."""
    text = MQ5.read_text(encoding="utf-8", errors="replace")
    sites = [ln.strip() for ln in text.splitlines()
             if "risk_d / (stop_d * dpu)" in ln]
    assert len(sites) == 3, (
        f"found {len(sites)} sizing sites computing lots from risk_d/dpu; EaSizing and "
        f"this file pin exactly three (live + paper + BAR replay): {sites}")


# --------------------------------------------------------------------------- #
# It is a mirror of the EA, not of the prop layer
# --------------------------------------------------------------------------- #


def test_the_mirror_ignores_the_prop_daily_budget_entirely():
    """`size_position` sizes to the daily limit; this sizes to InpRiskPercent. Given
    the same inputs they must disagree, or the two-size report would be printing one
    number twice."""
    from midas_prop.execution.prop_execution import evaluate_trade, AccountState
    from midas_prop.risk.upcomers_rules import ThunderboltClassicRules

    rules = ThunderboltClassicRules(account_size=25_000.0)
    state = AccountState(equity=25_000.0, balance=25_000.0, peak_equity=25_000.0)
    d = evaluate_trade(rules, SPEC, state, stop_distance_price=31.84,
                       safety_fraction=0.5, arming=None)
    assert d.sizing is not None and d.sizing.ok
    ea = _ea()
    assert d.sizing.lots > ea.lots * 5, (
        f"the two sizers now agree ({d.sizing.lots} vs {ea.lots}) — the two-size "
        f"report is printing one number twice")
    assert d.best_day_basis == BEST_DAY_HEADROOM or d.best_day_basis
