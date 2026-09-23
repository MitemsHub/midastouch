"""Prop-account execution layer: sizing, legality and the arming switch.

WHY THIS EXISTS. `upcomers_rules.py` states the venue's rules as arithmetic —
what may be risked, what breaches the account, what an instrument costs. This
module is the layer that *acts* on them: it turns a risk budget into a lot size
the broker will accept, refuses a trade that would breach a limit, and holds a
single switch that keeps the whole thing inert until a validated configuration
exists.

Three facts from this program's own history shape every decision here.

1. **A risk budget is not a position size until the broker's arithmetic agrees.**
   On 2026-09-19 the spec fields for XAUUSD said ``contract_size=100`` with
   ``trade_tick_value=0.1`` — two mutually inconsistent claims about the same
   instrument, a 10x disagreement. The terminal's own ``order_calc_profit``
   settled it at $100 per $1.00 move per lot. Sizing off the spec would have been
   wrong by an order of magnitude in one direction or the other. So
   :class:`ContractSpec` records *which basis* its dollar figure came from, and
   :func:`verify_against_broker` exists to make the disagreement loud.
2. **The broker's minimum lot can make correct sizing arithmetically
   impossible.** MIDASTOUCH went live on a $39.58 account where the minimum lot
   risked more than the entire allowable budget; it closed its only trade at
   −$0.50. That is not a bug to be worked around — it is a *refusal* condition,
   and :func:`size_position` returns an explicit impossible-with-reasons result
   rather than a smaller-but-wrong lot size.
3. **The Best Day rule is a profit cap, not a loss cap**, and it is the least
   understood rule on the account. It says no single day may exceed 20% of total
   profit. Rearranged, that is a *hard ceiling on how much a day may earn*:
   with ``R`` banked on other days, today may take at most ``f*R/(1-f)``. On the
   first profitable day of an evaluation that ceiling is **zero dollars**, because
   any profit at all is 100% of total profit. Nobody sizes for this and it is why
   :func:`best_day_budget_usd` exists.

Everything in this module is pure arithmetic — no MT5, no network, no clock of
its own (``now`` is always passed in). That is what makes the refusal conditions
assertable in tests instead of discovered on a funded account.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from midas_prop.risk.upcomers_rules import (
    ThunderboltClassicRules,
    risk_budget_usd,
)

__all__ = [
    "ContractSpec",
    "AccountState",
    "Sizing",
    "size_position",
    "best_day_budget_usd",
    "best_day_days_required",
    "TradeDecision",
    "evaluate_trade",
    "BlockCode",
    "EaSizing",
    "size_like_ea",
    "BEST_DAY_HEADROOM",
    "BEST_DAY_CAP_REACHED",
    "BEST_DAY_NO_PROFIT_YET",
    "ValidationRecord",
    "GateCriteria",
    "ArmingDecision",
    "ArmingGate",
    "HaltReason",
    "DailyStopConfig",
    "DayLedger",
    "DEFAULT_LEDGER_PATH",
    "reconcile_realised",
    "resolve_day_ledger",
    "trade_would_breach_day_stop",
    "order_calc_profit_lots",
    "verify_against_broker",
]

#: Tolerance for float comparisons on money, matching ``upcomers_rules``.
POS_2CM = 1e-8

#: The venue's ``min_hold_seconds`` is 120: a close inside two minutes is
#: flagged as tick scalping. Enforced here rather than in the strategy because
#: it is a property of the venue, not of the signal.
MIN_HOLD_SECONDS = 120


# --------------------------------------------------------------------------- #
# Contract facts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ContractSpec:
    """Broker-side trading facts for one symbol.

    ``usd_per_unit_per_lot`` is the dollar value of a 1.0 price-unit move on 1.0
    lot, and it is the ONLY number sizing may use. ``basis`` records where it
    came from, because this program has already been burned by trusting the
    equivalent spec field:

    * ``"order_calc_profit"`` — measured with the terminal's own P&L calculator.
      The only basis that may size a live order.
    * ``"spec_tick_value"`` — derived from ``trade_tick_value``. Retained so a
      disagreement can be *reported*; never used to size.
    * ``"assumed"`` — a typed-in convention. Research only.

    The field is not metadata. :meth:`may_size_live` reads it, and
    :func:`size_position` refuses to produce a live-sizable result on any basis
    other than a measurement.
    """

    symbol: str
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 100.0
    digits: int = 2
    usd_per_unit_per_lot: float = 1.0
    basis: str = "assumed"
    tick_value_field: float | None = None
    """``trade_tick_value`` as reported, kept only to quantify a disagreement."""

    def __post_init__(self) -> None:
        if self.min_lot <= 0:
            raise ValueError("min_lot must be positive")
        if self.lot_step <= 0:
            raise ValueError("lot_step must be positive")
        if self.max_lot < self.min_lot:
            raise ValueError("max_lot must be >= min_lot")
        if self.usd_per_unit_per_lot <= 0:
            raise ValueError("usd_per_unit_per_lot must be positive")

    @property
    def may_size_live(self) -> bool:
        """True only when the dollar basis is a measurement, not a convention."""
        return self.basis == "order_calc_profit"

    def spec_implied_usd_per_unit_per_lot(self) -> float | None:
        """What the spec fields alone would imply, for comparison.

        ``trade_tick_value`` is the value of one *tick* on one lot, so the value
        of a whole price unit is that divided by the tick size — which this
        module does not carry. Callers that have the tick size pass it to
        :func:`verify_against_broker` instead, which does the division. Kept
        here so the field is not silently ignored.
        """
        return self.tick_value_field

    def floor_lots(self, lots: float) -> float:
        """Round DOWN to a broker-acceptable volume.

        Down, never to nearest: rounding up would exceed the risk budget the
        caller just computed, and the whole point of a budget is that exceeding
        it is the failure mode. Floats are floored via a tick count rather than
        ``//`` so that ``0.3`` does not become ``0.29`` under binary
        representation.
        """
        if lots <= 0:
            return 0.0
        ticks = math.floor(round(lots / self.lot_step, 9))
        return round(ticks * self.lot_step, max(self.digits, 2))

    def is_tradeable_volume(self, lots: float) -> bool:
        return self.min_lot - POS_2CM <= lots <= self.max_lot + POS_2CM


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Sizing:
    """The outcome of asking "how big can this trade be?".

    ``ok`` is False for a *refusal*, never for a small number. A caller must
    treat ``ok=False`` as "do not place this order" and not as "place the
    minimum", because the minimum is frequently the thing that breaches.
    """

    ok: bool
    lots: float
    risk_usd: float
    budget_usd: float
    budget_note: str
    stop_distance_price: float
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def refused(self) -> bool:
        return not self.ok

    @property
    def risk_pct_of_budget(self) -> float:
        if self.budget_usd <= 0:
            return float("nan")
        return self.risk_usd / self.budget_usd


def _refusal(*reasons: str, budget_usd: float = 0.0, budget_note: str = "",
             stop: float = 0.0, warnings: Sequence[str] = ()) -> Sizing:
    return Sizing(ok=False, lots=0.0, risk_usd=0.0, budget_usd=budget_usd,
                  budget_note=budget_note, stop_distance_price=stop,
                  reasons=tuple(reasons), warnings=tuple(warnings))


def size_position(
    rules: ThunderboltClassicRules,
    spec: ContractSpec,
    *,
    equity: float,
    balance: float,
    stop_distance_price: float,
    safety_fraction: float = 0.5,
    single_trade_cap_pct: float | None = None,
    sequence_ceiling_usd: float | None = None,
    allow_unverified_basis: bool = False,
) -> Sizing:
    """Turn a rule-derived risk budget into a broker-legal lot size.

    ``safety_fraction`` defaults to **0.5**, not 1.0, and that default is a
    deliberate risk decision rather than a convenience. At 1.0 a single trade is
    allowed to consume the entire 3% daily allowance, so one loss ends the day
    and two end the evaluation — the trap ``risk_budget_usd`` documents. At 0.5 a
    trade risks 1.5% of the account, giving two full-size losses before the daily
    limit and four before the shield, which is the smallest number of attempts
    that still admits a losing streak longer than one.

    ``allow_unverified_basis`` exists so research and dry runs can size off an
    assumed dollar basis. It must never be set on a path that places an order;
    that is what :attr:`ContractSpec.may_size_live` and this flag together mean.

    ``sequence_ceiling_usd`` is the prospective trailing-shield ceiling from
    :func:`sequence_risk_ceiling_usd`, and passing it makes the shield a BINDING
    input rather than a post-hoc check. Without it, sizing knows only the day it is
    in: the per-day budget cannot see that the shield trails the high-water mark, so
    it can authorise a size that a measured run of losing days would breach. Omit it
    and the size is bounded by the single-day rule alone -- which the DAILY-ONE
    measurement showed is optimistic by about 3x ($716.85 allowed, $233.99 survived).
    """
    if stop_distance_price <= 0:
        return _refusal(
            f"stop_distance_price must be positive, got {stop_distance_price!r}",
            stop=stop_distance_price)

    budget, note = risk_budget_usd(
        rules, equity=equity, balance=balance,
        single_trade_cap_pct=single_trade_cap_pct,
        safety_fraction=safety_fraction)

    if sequence_ceiling_usd is not None:
        if sequence_ceiling_usd <= POS_2CM:
            return _refusal(
                f"{spec.symbol}: the measured worst loss run cannot be absorbed at "
                f"ANY size that also reaches the profit target (sequence ceiling "
                f"${sequence_ceiling_usd:,.2f}). No position size fixes a trailing "
                f"drawdown -- refusing rather than sizing down to a trade that "
                f"cannot help.",
                budget_usd=budget, budget_note=note, stop=stop_distance_price)
        if sequence_ceiling_usd < budget:
            note = (f"{note}; budget cut ${budget:,.2f} -> "
                    f"${sequence_ceiling_usd:,.2f} by the measured loss run "
                    f"(prospective trail-shield reserve)")
            budget = sequence_ceiling_usd

    warnings: list[str] = []
    if not spec.may_size_live and not allow_unverified_basis:
        return _refusal(
            f"{spec.symbol}: dollar basis is {spec.basis!r}, not a measured "
            f"order_calc_profit value. Refusing to size an order from a "
            f"convention -- the spec fields disagreed with the broker by 10x on "
            f"XAUUSD on 2026-09-19.",
            budget_usd=budget, budget_note=note, stop=stop_distance_price)
    if not spec.may_size_live:
        warnings.append(
            f"{spec.symbol}: sized on an UNVERIFIED basis ({spec.basis!r}); "
            f"research/dry-run only")

    # The broker's minimum lot is a veto, not a floor to round up to.
    min_risk = spec.min_lot * stop_distance_price * spec.usd_per_unit_per_lot
    if min_risk > budget + POS_2CM:
        return _refusal(
            f"{spec.symbol}: minimum lot {spec.min_lot:g} risks ${min_risk:,.2f} "
            f"against a ${budget:,.2f} budget ({min_risk / budget:.1f}x over). "
            f"This is arithmetically impossible to trade correctly -- it is the "
            f"condition MIDASTOUCH went live on and lost its only trade to. "
            f"Either widen the account, widen the stop, or do not trade this "
            f"symbol.",
            budget_usd=budget, budget_note=note, stop=stop_distance_price,
            warnings=warnings)

    raw_lots = budget / (stop_distance_price * spec.usd_per_unit_per_lot)
    lots = spec.floor_lots(raw_lots)

    if lots < spec.min_lot - POS_2CM:
        # Only reachable when flooring pushed us under the minimum, which for a
        # step <= min_lot cannot happen after the veto above. Kept as a refusal
        # rather than an assert: a silent zero here would be a skipped trade the
        # operator never sees.
        return _refusal(
            f"{spec.symbol}: floored volume {lots:g} is below the minimum "
            f"{spec.min_lot:g} (raw {raw_lots:.6g})",
            budget_usd=budget, budget_note=note, stop=stop_distance_price,
            warnings=warnings)

    if lots > spec.max_lot + POS_2CM:
        lots = spec.max_lot
        warnings.append(
            f"{spec.symbol}: volume capped at max_lot {spec.max_lot:g}; the "
            f"budget would have allowed {raw_lots:.4g} lots")

    risk = lots * stop_distance_price * spec.usd_per_unit_per_lot
    if risk > budget + POS_2CM:
        # Flooring cannot overshoot, so this is a programming error rather than
        # a market condition -- and one that would quietly break the budget.
        raise AssertionError(
            f"{spec.symbol}: realized risk ${risk:.4f} exceeds budget "
            f"${budget:.4f} after flooring -- sizing logic is inconsistent")

    if risk < 0.5 * budget:
        warnings.append(
            f"{spec.symbol}: lot step {spec.lot_step:g} quantised the size down "
            f"to {risk / budget:.0%} of the ${budget:,.2f} budget "
            f"(unused ${budget - risk:,.2f})")

    return Sizing(ok=True, lots=lots, risk_usd=risk, budget_usd=budget,
                  budget_note=note, stop_distance_price=stop_distance_price,
                  warnings=tuple(warnings))


# --------------------------------------------------------------------------- #
# What the EA will actually send
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EaSizing:
    """What the deployed EA's OWN sizing site would send, mirrored step for step.

    WHY THIS IS NOT :class:`Sizing`. The two answer different questions, and on
    2026-09-21 an operator read one as the other: `size_position` sizes to the PROP
    RULES (a fraction of the 3% daily limit), while the EA sizes to ``InpRiskPercent``
    of account equity. On the U25 arm those are 0.11 lots and 0.01 lots for the same
    stop width — a ten-fold difference, printed under one heading.

    Mirrored from ``MidastouchAI.mq5`` → ``LiveSendOrder()`` (the only path that can
    reach the venue; the paper path at ``OpenPaperPosition()`` is the same arithmetic
    on ``PaperEquity()`` instead of ``ACCOUNT_EQUITY``):

    1. ``risk_usd = equity * InpRiskPercent / 100.0``
    2. ``lots = risk_usd / (stop_price_distance * usd_per_unit_per_lot)``
    3. if below the venue minimum, VETO when
       ``stop * dpu * min_lot > equity * InpMaxRiskPct / 100.0`` (amendment 6 — the
       min lot is a veto, never a floor to round up to), else take the minimum
    4. floor to the venue's lot step, then re-apply the minimum

    ``tests/test_ea_sizing_mirror.py`` pins every one of those steps against the MQL5
    source text, so this mirror cannot drift from the EA without a test failing.
    """

    lots: float
    risk_usd: float
    budget_usd: float
    """``equity * risk_percent / 100`` — the risk the EA intended, before lot quantisation."""
    equity: float
    risk_percent: float
    max_risk_pct: float
    stop_distance_price: float
    floored: bool = False
    """The EA's own flag: the raw size fell below the venue minimum, so it took the
    minimum. Note it does NOT mark a size floored down to the lot step — the EA's
    ``MathFloor(lots / vstep)`` branch sets no flag (measured against the source)."""
    vetoed: bool = False
    veto_reason: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """False only when the EA would refuse the order. A small number is not a refusal."""
        return not self.vetoed

    @property
    def risk_pct_of_equity(self) -> float:
        if self.equity <= 0:
            return float("nan")
        return self.risk_usd / self.equity

    @property
    def quantised_down(self) -> bool:
        """True when the venue's lot step left the configured budget unspent.

        Derived from the numbers rather than from ``floored``, because the case that
        matters most is invisible to that flag: on the U25 arm the 0.25% budget is
        $62.50 and the venue's 0.01 step gives $31.84 — the arm trades HALF its
        configured risk, and the EA's log says nothing about it.
        """
        return not self.vetoed and self.risk_usd < self.budget_usd - POS_2CM

    @property
    def over_budget(self) -> bool:
        """The venue's minimum lot forces MORE risk than the configured percentage.

        The mirror image of :attr:`quantised_down`, and the one that matters for
        survival: on a small arm the minimum lot is the smallest order the venue
        accepts, so ``InpRiskPercent`` is not a setting the EA can honour. It is not
        the amendment-6 veto (that is when even this is above ``InpMaxRiskPct``).
        """
        return not self.vetoed and self.risk_usd > self.budget_usd + POS_2CM

    def note(self) -> str:
        """One sentence saying what the numbers mean — never left to the reader."""
        if self.vetoed:
            return self.veto_reason
        head = (f"{self.risk_percent:g}% of ${self.equity:,.2f} equity = "
                f"${self.budget_usd:,.2f} budget; {self.lots:g} lots risks "
                f"${self.risk_usd:,.2f} ({self.risk_pct_of_equity:.3%} of equity)")
        if self.over_budget:
            return (f"{head} — OVER BUDGET: {self.lots:g} lots is the smallest order "
                    f"the venue accepts, and it risks "
                    f"{self.risk_usd / self.budget_usd:.2f}x the configured budget — "
                    f"InpRiskPercent {self.risk_percent:g}% cannot be honoured here")
        if not self.quantised_down:
            return head
        return (f"{head} — QUANTISED DOWN: the venue's lot step cannot express the "
                f"${self.budget_usd:,.2f} budget at this stop width, leaving "
                f"${self.budget_usd - self.risk_usd:,.2f} of it unspent"
                + (" (the size is the venue's minimum lot)" if self.floored else ""))


def size_like_ea(
    spec: ContractSpec,
    *,
    equity: float,
    risk_percent: float,
    max_risk_pct: float,
    stop_distance_price: float,
) -> EaSizing:
    """Mirror the EA's live sizing arithmetic. See :class:`EaSizing` for the steps.

    Malformed inputs raise rather than returning a refusal: a non-positive stop or
    equity is a caller asking a question the EA's code path cannot be reached with,
    not the EA declining a trade. The EA's own refusals are reported as ``vetoed``.
    """
    if equity <= 0:
        raise ValueError("equity must be positive")
    if risk_percent <= 0:
        raise ValueError("risk_percent must be positive")
    if max_risk_pct <= 0:
        raise ValueError("max_risk_pct must be positive")
    if stop_distance_price <= 0:
        raise ValueError("stop_distance_price must be positive")

    dpu = spec.usd_per_unit_per_lot
    budget = equity * risk_percent / 100.0
    raw = budget / (stop_distance_price * dpu)
    min_risk = stop_distance_price * dpu * spec.min_lot
    cap = equity * max_risk_pct / 100.0

    if raw < spec.min_lot and min_risk > cap + POS_2CM:
        return EaSizing(
            lots=0.0, risk_usd=0.0, budget_usd=budget, equity=equity,
            risk_percent=risk_percent, max_risk_pct=max_risk_pct,
            stop_distance_price=stop_distance_price, vetoed=True,
            veto_reason=(f"the EA REFUSES this order: the venue's {spec.min_lot:g} "
                         f"minimum risks ${min_risk:,.2f}, above InpMaxRiskPct "
                         f"{max_risk_pct:g}% of equity (${cap:,.2f}) — amendment 6"))

    lots = raw
    floored = False
    if lots < spec.min_lot:
        lots, floored = spec.min_lot, True
    lots = spec.floor_lots(lots)
    if lots < spec.min_lot - POS_2CM:
        lots, floored = spec.min_lot, True

    warnings: list[str] = []
    if lots > spec.max_lot + POS_2CM:
        # The EA does NOT clamp here (it never reads volume_max), so this is not
        # corrected — it is reported, because the venue would reject the order.
        warnings.append(
            f"the EA does not clamp to max_lot: {lots:g} exceeds the symbol's "
            f"{spec.max_lot:g} — the venue would reject this order")

    return EaSizing(
        lots=lots, risk_usd=stop_distance_price * dpu * lots, budget_usd=budget,
        equity=equity, risk_percent=risk_percent, max_risk_pct=max_risk_pct,
        stop_distance_price=stop_distance_price, floored=floored,
        warnings=tuple(warnings))


# --------------------------------------------------------------------------- #
# Best Day: a profit ceiling, not a loss limit
# --------------------------------------------------------------------------- #


def best_day_budget_usd(
    rules: ThunderboltClassicRules,
    *,
    today_profit: float,
    other_days_profit: Sequence[float],
) -> float:
    """How much MORE this day may earn before the Best Day rule is breached.

    The rule is ``max_day <= f * total_profit``. Writing ``R`` for the sum of
    other days' positive profits and ``T`` for today's, the constraint is
    ``T <= f * (R + T)``, i.e.::

        T <= f * R / (1 - f)

    which at the venue's ``f = 0.20`` is simply ``T <= R / 4``. Returns the
    remaining allowance ``f*R/(1-f) - T``, floored at zero.

    **The consequence worth internalising:** when ``R = 0`` the allowance is
    exactly ``$0.00``. On the first profitable day of an evaluation, *any* profit
    is 100% of total profit and therefore breaches. This is not a modelling
    artefact — it is the rule as written, and it means the rule is only
    satisfiable by spreading profit across several days. See
    :func:`best_day_days_required`.

    Only *positive* other-day results count toward ``R``: a losing day adds
    nothing to the profit denominator, so it cannot buy today more headroom.
    """
    if not 0 < rules.best_day_pct < 100:
        raise ValueError("best_day_pct must be strictly between 0 and 100")
    f = rules.best_day_pct / 100.0
    rest = sum(p for p in other_days_profit if p > 0)
    ceiling = f * rest / (1.0 - f)
    return max(0.0, ceiling - max(today_profit, 0.0))


def best_day_days_required(rules: ThunderboltClassicRules,
                           target_usd: float | None = None) -> int:
    """Fewest EQUAL profitable days that can bank the target without breaching.

    With the cap at ``f``, ``n`` equal days each earn ``target/n`` and the rule
    requires ``1/n <= f``, so ``n >= 1/f``. At 20% that is 5, and it cannot be
    fewer however good any individual day is — which is why a 5% target and a
    20% Best Day cap together fix a *minimum* number of profitable days rather
    than a minimum number of trades.
    """
    if not 0 < rules.best_day_pct < 100:
        raise ValueError("best_day_pct must be strictly between 0 and 100")
    return int(math.ceil(100.0 / rules.best_day_pct))


#: WHY an allowance reads what it reads. The number alone is ambiguous, and the
#: ambiguity has already been misread once by an operator tool: the allowance is
#: ``$0.00`` both when today's ceiling is REACHED (a refusal, ``cap_reached``) and
#: when no profit exists yet to take a share of (``no_profit_yet`` — the day's
#: first trade is always allowed). Only the basis separates them, so it travels
#: with the number everywhere the number is printed.
BEST_DAY_HEADROOM = "headroom"
BEST_DAY_CAP_REACHED = "cap_reached"
BEST_DAY_NO_PROFIT_YET = "no_profit_yet"


# --------------------------------------------------------------------------- #
# Pre-trade legality
# --------------------------------------------------------------------------- #


class BlockCode:
    """Machine-readable reasons a trade was refused.

    Strings rather than an enum so they survive JSON into the journal and the
    operator-facing report without a lookup table.
    """

    DAILY_LOSS_FLOOR = "daily_loss_floor"
    SHIELD_FLOOR = "shield_floor"
    BEST_DAY_EXHAUSTED = "best_day_exhausted"
    MIN_HOLD = "min_hold_seconds"
    SIZING_REFUSED = "sizing_refused"
    NOT_ARMED = "not_armed"
    UNVERIFIED_BASIS = "unverified_dollar_basis"


@dataclass(frozen=True)
class AccountState:
    """Everything the rules need to know about the account right now.

    ``peak_equity`` is the high-water mark for the trailing shield. It is passed
    in rather than derived from history here, because the correct source is the
    broker's own recorded peaks, and recomputing it from a partial local series
    would silently reset the shield to something more forgiving than reality.
    """

    equity: float
    balance: float
    peak_equity: float
    today_profit: float = 0.0
    other_days_profit: tuple[float, ...] = ()
    seconds_since_last_close: float | None = None
    open_positions: int = 0

    def __post_init__(self) -> None:
        if self.peak_equity < self.equity - POS_2CM:
            raise ValueError(
                "peak_equity is below current equity; the shield high-water "
                "mark must include the present, or the floor is wrong")


@dataclass(frozen=True)
class TradeDecision:
    """The verdict on one prospective trade, with its full reasoning."""

    allowed: bool
    sizing: Sizing | None
    block_codes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    best_day_allowance_usd: float = 0.0
    day_profit_cap_usd: float = 0.0
    """Most today may earn in total before today exceeds the Best Day share."""

    best_day_basis: str = BEST_DAY_HEADROOM
    """One of the ``BEST_DAY_*`` constants: why the allowance reads what it reads.

    ``$0.00`` under :data:`BEST_DAY_CAP_REACHED` is a refusal; ``$0.00`` under
    :data:`BEST_DAY_NO_PROFIT_YET` is not one. Both are ``$0.00``.
    """

    best_day_note: str = ""
    """That basis as a sentence, so no renderer has to infer a refusal from a number."""

    def explain(self) -> str:
        # The header names the block CODES, not just the word BLOCK. "BLOCK" on its
        # own is what let an operator read the Best Day allowance line as the cause
        # when the cause was the arming switch three lines further down.
        head = "ALLOW" if self.allowed else "BLOCK (" + ", ".join(self.block_codes) + ")"
        lines = [f"{head}"]
        if self.sizing is not None and self.sizing.ok:
            lines.append(f"  lots={self.sizing.lots:g} "
                         f"risk=${self.sizing.risk_usd:,.2f} "
                         f"budget=${self.sizing.budget_usd:,.2f} "
                         f"({self.sizing.budget_note})")
        lines.append(f"  Best Day: today's cap ${self.day_profit_cap_usd:,.2f}, "
                     f"remaining allowance ${self.best_day_allowance_usd:,.2f}"
                     + (f" [{self.best_day_basis}]" if self.best_day_basis
                        != BEST_DAY_HEADROOM else ""))
        if self.best_day_note:
            lines.append(f"    {self.best_day_note}")
        for r in self.reasons:
            lines.append(f"  BLOCKED: {r}")
        for w in self.warnings:
            lines.append(f"  warn: {w}")
        return "\n".join(lines)


def evaluate_trade(
    rules: ThunderboltClassicRules,
    spec: ContractSpec,
    state: AccountState,
    *,
    stop_distance_price: float,
    safety_fraction: float = 0.5,
    single_trade_cap_pct: float | None = None,
    allow_unverified_basis: bool = False,
    arming: "ArmingDecision | None" = None,
    best_day_mode: str = "cap",
    ledger: "DayLedger | None" = None,
    daily_stops: "DailyStopConfig | None" = None,
) -> TradeDecision:
    """Decide whether one trade may be placed, and how big.

    ``ledger`` is today's realised result and halt state (see
    :func:`resolve_day_ledger`). When supplied, a day already stopped for loss or
    profit blocks the trade, and a trade whose own risk would carry the day past
    the loss stop is refused BEFORE it is placed — a stop that acts only after the
    crossing trade has been taken is not a stop.

    Every limit is evaluated even after one has already blocked, so the operator
    sees the whole picture rather than the first objection — a trade that trips
    three limits is a different problem from one that trips one.

    ``arming`` is checked FIRST and is not optional in spirit: when supplied and
    not armed, the decision is blocked regardless of how attractive the trade
    looks. Passing ``None`` means the caller has taken responsibility for the
    switch elsewhere; every live path in this repo passes a real decision.

    ``best_day_mode`` controls how the Best Day rule binds, and the choice matters
    because the rule is a *profit distribution* constraint rather than a loss
    limit:

    * ``"cap"`` (default) — refuse new entries once today's realised profit has
      reached today's cap. Strict, and it has a consequence worth stating plainly:
      with nothing banked on other days the cap is ``$0.00``, so the first
      profitable close of an evaluation ends that day's trading. That is the rule
      as written — any single profitable day is 100% of total profit — and it is
      why a 5% target needs at least five profitable days rather than one big one.
    * ``"advise"`` — never block on it; report the cap and let the strategy own
      the day's target.

    Note what ``"cap"`` deliberately does NOT do: it does not refuse the day's
    FIRST trade. Before any profit exists today there is no breach to deepen, and
    a rule that forbids starting is not a constraint, it is a deadlock.

    Because of that, ``best_day_allowance_usd`` is ``$0.00`` in two states that
    mean opposite things, and the decision carries :attr:`TradeDecision.best_day_basis`
    and :attr:`TradeDecision.best_day_note` to say WHICH — a caller that prints the
    bare number next to a verdict is printing an ambiguity (that is what
    ``scripts/verify_sizing_live.py`` did, and why it looked like the venue was
    refusing trades on a flat account).
    """
    if best_day_mode not in ("cap", "advise"):
        raise ValueError("best_day_mode must be 'cap' or 'advise'")
    blocks: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []

    if arming is not None and not arming.armed:
        blocks.append(BlockCode.NOT_ARMED)
        reasons.append("arming switch is OFF: " + "; ".join(arming.reasons))

    # --- the day stops, checked first because they outrank everything else --- #
    stop_cfg = daily_stops or DailyStopConfig()
    if ledger is not None and ledger.halted:
        blocks.append(ledger.halt_reason or HaltReason.UNKNOWN_STATE)
        reasons.append(
            f"entries are stopped for the rest of the day "
            f"({ledger.halt_reason or 'unspecified'})"
            + (" — this halt came from the ledger on disk, so a restart did not "
               "clear it" if ledger.halted_by_disk else ""))

    # --- the two loss floors ------------------------------------------------ #
    daily_floor = rules.daily_loss_floor_usd(state.equity, state.balance)
    if state.equity <= daily_floor + POS_2CM:
        blocks.append(BlockCode.DAILY_LOSS_FLOOR)
        reasons.append(
            f"equity ${state.equity:,.2f} is at or below the "
            f"{rules.daily_dd_pct:g}% daily floor ${daily_floor:,.2f}")

    shield_floor = rules.drawdown_floor_usd(state.peak_equity)
    if state.equity <= shield_floor + POS_2CM:
        blocks.append(BlockCode.SHIELD_FLOOR)
        reasons.append(
            f"equity ${state.equity:,.2f} is at or below the "
            f"{rules.max_dd_pct:g}% shield floor ${shield_floor:,.2f} "
            f"(trailing from peak ${state.peak_equity:,.2f})")

    # --- Best Day: a profit ceiling ---------------------------------------- #
    allowance = best_day_budget_usd(
        rules, today_profit=state.today_profit,
        other_days_profit=state.other_days_profit)
    cap_today = allowance + max(state.today_profit, 0.0)
    rest = sum(p for p in state.other_days_profit if p > 0)
    if allowance <= POS_2CM and state.today_profit > POS_2CM:
        basis = BEST_DAY_CAP_REACHED
        note = (f"today has reached its ${cap_today:,.2f} ceiling, so no further "
                f"profit may be carried today"
                + ("" if best_day_mode == "cap"
                   else " — 'advise' mode, so this does not block"))
        if best_day_mode == "cap":
            blocks.append(BlockCode.BEST_DAY_EXHAUSTED)
            reasons.append(
                f"Best Day cap reached: today ${state.today_profit:,.2f} of a "
                f"${cap_today:,.2f} ceiling (further profit today holds today "
                f"above {rules.best_day_pct:g}% of the ${rest:,.2f} banked on "
                f"other days)")
        else:
            warnings.append(
                f"Best Day cap reached (today ${state.today_profit:,.2f} of "
                f"${cap_today:,.2f}) — 'advise' mode, not blocking")
    elif allowance <= POS_2CM:
        # The $0.00 that looks like a refusal and is not one. Nothing is banked, so
        # the share is undefined at zero and the rule cannot bind on an entry at
        # all — it binds on the first profitable CLOSE (see best_day_budget_usd).
        basis = BEST_DAY_NO_PROFIT_YET
        note = (f"no profit is banked yet, so the {rules.best_day_pct:g}% share is "
                f"undefined at zero and the allowance reads $0.00 — NOT a refusal: "
                f"the day's FIRST trade is always allowed, and this rule binds on "
                f"the first profitable close, not on the entry")
        warnings.append(
            f"Best Day: nothing banked on other days, so today's cap is "
            f"${cap_today:,.2f} — any profit today is 100% of total profit, so "
            f"the first profitable close ends the day. The "
            f"{rules.profit_target_pct:g}% target needs >= "
            f"{best_day_days_required(rules)} profitable days.")
    else:
        basis = BEST_DAY_HEADROOM
        note = (f"${allowance:,.2f} of today's ${cap_today:,.2f} ceiling remains; "
                f"the ceiling is {rules.best_day_pct:g}% of total profit and it takes "
                f">= {best_day_days_required(rules)} profitable days to bank the "
                f"{rules.profit_target_pct:g}% target without breaching it")

    # --- venue minimum hold ------------------------------------------------ #
    since = state.seconds_since_last_close
    if since is not None and since < MIN_HOLD_SECONDS:
        blocks.append(BlockCode.MIN_HOLD)
        reasons.append(
            f"last close was {since:.0f}s ago; the venue flags sub-"
            f"{MIN_HOLD_SECONDS}s closes as tick scalping")

    # --- size ---------------------------------------------------------------#
    sizing = size_position(
        rules, spec, equity=state.equity, balance=state.balance,
        stop_distance_price=stop_distance_price,
        safety_fraction=safety_fraction,
        single_trade_cap_pct=single_trade_cap_pct,
        allow_unverified_basis=allow_unverified_basis)

    if sizing.refused:
        blocks.append(BlockCode.SIZING_REFUSED)
        reasons.extend(sizing.reasons)
        if not spec.may_size_live and not allow_unverified_basis:
            blocks.append(BlockCode.UNVERIFIED_BASIS)
    warnings.extend(sizing.warnings)

    # The stop must bind on the PROSPECTIVE trade, not on the last one.
    if ledger is not None and not ledger.halted and sizing.ok:
        breach = trade_would_breach_day_stop(
            rules, ledger, prospective_risk_usd=sizing.risk_usd, cfg=stop_cfg)
        if breach:
            blocks.append(HaltReason.DAILY_LOSS_STOP)
            reasons.append(breach)

    # A trade whose target exceeds the day's allowance cannot be carried at full
    # size: the exit, not the entry, is what would breach the rule.
    if allowance > POS_2CM and sizing.ok and state.open_positions == 0:
        warnings.append(
            f"Best Day headroom today is ${allowance:,.2f}; a winner larger than "
            f"that must be flattened early, not carried")

    return TradeDecision(
        allowed=not blocks,
        sizing=sizing,
        block_codes=tuple(blocks),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        best_day_allowance_usd=allowance,
        day_profit_cap_usd=cap_today,
        best_day_basis=basis,
        best_day_note=note)


# --------------------------------------------------------------------------- #
# Broker verification
# --------------------------------------------------------------------------- #


def order_calc_profit_lots(
    profit_usd: float,
    *,
    price_move: float,
    lot_basis: float = 1.0,
) -> float:
    """Invert an ``order_calc_profit`` result into USD per price unit per lot.

    ``profit_usd`` is the terminal's answer for moving ``price_move`` on
    ``lot_basis`` lots. Pure arithmetic so that the *interpretation* of the
    broker's number can be pinned in a test without a terminal; the call itself
    lives in :func:`verify_against_broker` and
    ``scripts/verify_sizing_live.py``.
    """
    if price_move <= 0:
        raise ValueError("price_move must be positive")
    if lot_basis <= 0:
        raise ValueError("lot_basis must be positive")
    return abs(profit_usd) / (price_move * lot_basis)


@dataclass(frozen=True)
class BasisCheck:
    """Whether a spec's dollar basis agrees with the broker's own arithmetic."""

    symbol: str
    spec_basis_usd: float
    broker_usd: float
    agrees: bool
    ratio: float
    detail: str

    @property
    def disagreement_factor(self) -> float:
        return max(self.ratio, 1.0 / self.ratio) if self.ratio > 0 else float("inf")


def verify_against_broker(
    spec: ContractSpec,
    *,
    broker_usd_per_unit_per_lot: float,
    tolerance: float = 0.01,
) -> BasisCheck:
    """Compare a spec's dollar basis with the broker's, and say how far off it is.

    A tolerance of 1% rather than exact equality: the two numbers arrive by
    different routes (a measured P&L versus a documented figure), and a
    disagreement smaller than a tick is not a disagreement. Anything larger is
    a size, and the caller must treat it as one — the 10x XAUUSD case was found
    exactly this way.
    """
    if broker_usd_per_unit_per_lot <= 0:
        raise ValueError("broker_usd_per_unit_per_lot must be positive")
    ratio = spec.usd_per_unit_per_lot / broker_usd_per_unit_per_lot
    agrees = abs(ratio - 1.0) <= tolerance
    if agrees:
        detail = (f"{spec.symbol}: {spec.basis} basis ${spec.usd_per_unit_per_lot:,.4f} "
                  f"matches the broker's ${broker_usd_per_unit_per_lot:,.4f}")
    else:
        detail = (
            f"{spec.symbol}: {spec.basis} basis ${spec.usd_per_unit_per_lot:,.4f} "
            f"vs broker ${broker_usd_per_unit_per_lot:,.4f} — off by "
            f"{max(ratio, 1 / ratio):.2f}x. Sizing on the spec would misstate "
            f"risk by that factor.")
    return BasisCheck(symbol=spec.symbol,
                      spec_basis_usd=spec.usd_per_unit_per_lot,
                      broker_usd=broker_usd_per_unit_per_lot,
                      agrees=agrees, ratio=ratio, detail=detail)


# --------------------------------------------------------------------------- #
# The day ledger: stops that survive a restart
# --------------------------------------------------------------------------- #


class HaltReason:
    """Why entries are stopped for the rest of the day.

    Strings, like :class:`BlockCode`, so they survive JSON into the journal and the
    operator report without a lookup table.
    """

    DAILY_LOSS_STOP = "daily_loss_stop"
    DAY_PROFIT_STOP = "day_profit_stop"
    UNKNOWN_STATE = "unknown_day_state"
    LEDGER_DIVERGED = "ledger_diverged"


@dataclass(frozen=True)
class DailyStopConfig:
    """The two intraday stops, as fractions of limits the venue already imposes.

    Both are DERIVED from the account's own rules rather than typed in, because a
    stop invented by the strategy and a limit imposed by the venue are different
    things and only one of them can end the account:

    * ``loss_stop_fraction`` of the 3% daily limit. At 0.5 that is **$375**: half
      the room the venue allows, so a stop-out still leaves half the day's
      allowance and a single catastrophic fill cannot reach the limit.
    * ``profit_stop_usd`` defaults to ``best_day_pct`` of the target — **$250**.
      That is not a coincidence: it is exactly the per-day profit ceiling that
      :func:`best_day_days_required` proves is *sufficient* for Best Day
      compliance at any total at or above the target. Applying it live is what
      turns the study's arithmetic into a trading rule.
    """

    loss_stop_fraction: float = 0.5
    profit_stop_usd: float | None = None

    def loss_stop_usd(self, rules: ThunderboltClassicRules) -> float:
        if not 0 < self.loss_stop_fraction <= 1.0:
            raise ValueError("loss_stop_fraction must be in (0, 1]")
        return rules.daily_loss_limit_usd * self.loss_stop_fraction

    def profit_stop_for(self, rules: ThunderboltClassicRules) -> float:
        if self.profit_stop_usd is not None:
            return self.profit_stop_usd
        return rules.profit_target_usd * rules.best_day_pct / 100.0

    def attempts_allowed(self, rules: ThunderboltClassicRules,
                         risk_per_trade_usd: float) -> float:
        """How many full-size losing trades fit before the day stops.

        THIS IS THE NUMBER THAT MATTERS, and it is easy to get wrong by setting the
        stop as a fraction of the venue limit in isolation. Measured on the first
        real run of the paper trader: the venue limit is $750, ``safety_fraction``
        already splits that into ~$375 a trade, and ``loss_stop_fraction=0.5`` gives
        a $375 day stop — so the defaults permitted **1.02 losing trades per day**.
        That silently undoes the reason ``size_position`` defaults
        ``safety_fraction`` to 0.5 in the first place, which was to admit a losing
        streak longer than one. A day stop below one trade's risk is not a stop, it
        is a coin flip on the first idea of the day.
        """
        if risk_per_trade_usd <= 0:
            raise ValueError("risk_per_trade_usd must be positive")
        return self.loss_stop_usd(rules) / risk_per_trade_usd


@dataclass
class DayLedger:
    """Today's realised result and whether a stop has already been hit.

    WHY THIS IS A FILE AND NOT A VARIABLE. A stop held only in memory is exactly
    the stop a restart defeats: the process comes back, today's realised P&L is
    zero as far as it knows, and it re-enters a day it should have stopped
    trading hours ago. So the halt is persisted, and — more importantly — **a
    halt already on disk is honoured on the next start**, whatever anything else
    says.

    Two sources disagree about today by construction: this file (what the EA saw)
    and the broker (what actually happened). :func:`reconcile_realised` takes the
    WORSE of the two, so a deal closed while the EA was off still counts. A loss
    the EA never observed must not be forgotten, and a profit the EA overstates
    must not buy entries.
    """

    utc_date: str
    realised_usd: float = 0.0
    entries: int = 0
    halted: bool = False
    halt_reason: str = ""
    halted_at_utc: str = ""
    starting_equity: float = 0.0
    starting_balance: float = 0.0
    risk_per_r_usd: float = 0.0
    written_utc: str = ""
    halted_by_disk: bool = False
    """True when the halt came from the file rather than this run's arithmetic."""

    @property
    def realised_r(self) -> float:
        if self.risk_per_r_usd <= 0:
            return 0.0
        return self.realised_usd / self.risk_per_r_usd

    def save(self, path: str | os.PathLike) -> None:
        """Atomic write: a half-written ledger is a forgotten stop.

        ``tmp`` then ``os.replace``, matching the emitter in the call-file
        protocol. A crash between the two leaves the previous ledger intact and
        readable, which is the fail-safe direction.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.written_utc = _utc_now()
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, p)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "DayLedger":
        """Read a ledger, refusing anything malformed. Absence is not a ledger."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        missing = [f.name for f in cls.__dataclass_fields__.values()
                   if f.name not in raw and f.name != "halted_by_disk"]
        if missing:
            raise ValueError(f"day ledger {path} is missing "
                             f"{', '.join(missing)} — a partial ledger cannot "
                             f"tell us whether today was stopped")
        return cls(**{k: v for k, v in raw.items()
                      if k in cls.__dataclass_fields__})


DEFAULT_LEDGER_PATH = "artifacts/live/day_ledger.json"


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reconcile_realised(disk_usd: float, broker_usd: float | None) -> tuple[float, str]:
    """The realised figure to act on, and a note when the two sources disagree.

    ``min`` rather than either source alone: the broker knows about deals the EA
    did not see (closed while it was not running), and the EA may know about a
    fill the broker has not reported yet. Taking the lower number means a stop
    triggers on the pessimistic reading of both, which is the only direction that
    cannot silently resume a day that should be over.
    """
    if broker_usd is None:
        return disk_usd, ""
    if abs(disk_usd - broker_usd) < 0.01:
        return disk_usd, ""
    return min(disk_usd, broker_usd), (
        f"day ledger says ${disk_usd:,.2f} realised today, the broker reports "
        f"${broker_usd:,.2f} — acting on the worse of the two, because a deal "
        f"closed while the EA was off is still a deal")


def resolve_day_ledger(
    rules: ThunderboltClassicRules,
    *,
    ledger_path: str | os.PathLike = DEFAULT_LEDGER_PATH,
    today: str | None = None,
    broker_realised_usd: float | None = None,
    starting_equity: float = 0.0,
    starting_balance: float = 0.0,
    stops: DailyStopConfig | None = None,
) -> tuple[DayLedger, list[str]]:
    """Decide the day's stop state, fail-closed on anything unreadable.

    Five cases, and the interesting ones are the refusals:

    * **No ledger file and no broker figure** -> ``UNKNOWN_STATE``. We cannot know
      what today has already done, so we do not trade on the assumption that it
      has done nothing. This is the case a naive restart falls into.
    * **No ledger file, but the broker reports today's realised P&L** -> derive a
      fresh ledger from the broker, which is authoritative and restart-proof.
    * **Ledger from an earlier date** -> a new day; the previous day's halt does
      not carry over (it should not — these are intraday stops).
    * **Ledger for today marked halted** -> stays halted, no matter what else
      changed. ``halted_by_disk`` records that this was the file's decision.
    * **Ledger for today, not halted** -> recompute from the reconciled figure, so
      the two stops bind even if they were never written.
    """
    cfg = stops or DailyStopConfig()
    if today is None:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()

    ledger: DayLedger | None = None
    notes: list[str] = []
    p = Path(ledger_path)
    if p.is_file():
        try:
            ledger = DayLedger.load(p)
        except (OSError, ValueError, TypeError) as exc:
            notes.append(f"day ledger at {p} is unusable ({exc}) — treating the "
                         f"day as unknown rather than as fresh")
            ledger = None

    fresh = DayLedger(utc_date=today, starting_equity=starting_equity,
                      starting_balance=starting_balance)
    if ledger is not None and ledger.utc_date == today:
        fresh = ledger
        fresh.starting_equity = starting_equity or ledger.starting_equity
        fresh.starting_balance = starting_balance or ledger.starting_balance
    elif ledger is not None:
        notes.append(f"day ledger was for {ledger.utc_date}; today is {today}. "
                     f"Intraday stops reset — the daily loss limit and the shield "
                     f"are still enforced by the venue rules.")
    elif broker_realised_usd is None:
        notes.append(f"no day ledger at {p} and no broker-reported realised P&L "
                     f"for today: cannot tell whether this day was already "
                     f"stopped. Refusing rather than assuming a fresh day.")
        return (DayLedger(utc_date=today, halted=True,
                          halt_reason=HaltReason.UNKNOWN_STATE,
                          halted_at_utc=_utc_now()),
                notes)

    # Reconcile only when BOTH sources have a figure for today. With no record for
    # today there is nothing to reconcile against, and the broker's figure is the
    # authoritative one -- taking a minimum against an absent zero would silently
    # discard the day's PROFIT, which would stop the profit-stop ever binding at a
    # restart. (Taking the minimum is right for a loss; it is wrong for a profit.)
    disk_is_today = ledger is not None and ledger.utc_date == today
    if broker_realised_usd is not None and not disk_is_today:
        fresh.realised_usd = broker_realised_usd
        notes.append(f"no day ledger for today: taking today's realised "
                     f"${broker_realised_usd:,.2f} from the broker, which is the "
                     f"authoritative source and is not defeated by a restart")
    else:
        realised, note = reconcile_realised(fresh.realised_usd, broker_realised_usd)
        if note:
            notes.append(note)
        fresh.realised_usd = realised

    realised = fresh.realised_usd  # whichever source won above
    loss_stop = cfg.loss_stop_usd(rules)
    profit_stop = cfg.profit_stop_for(rules)
    if fresh.halted:
        fresh.halted_by_disk = True
        why = fresh.halt_reason or "no reason recorded"
        notes.append(f"day ledger already halted ({why}) — a restart does not "
                     f"resume a stopped day")
        return fresh, notes
    if realised <= -loss_stop + POS_2CM:
        fresh.halted = True
        fresh.halt_reason = HaltReason.DAILY_LOSS_STOP
        fresh.halted_at_utc = _utc_now()
        notes.append(f"daily loss stop: ${realised:,.2f} realised today is at or "
                     f"beyond the ${loss_stop:,.2f} stop "
                     f"({cfg.loss_stop_fraction:g} of the "
                     f"${rules.daily_loss_limit_usd:,.2f} venue limit)")
    elif realised >= profit_stop - POS_2CM:
        fresh.halted = True
        fresh.halt_reason = HaltReason.DAY_PROFIT_STOP
        fresh.halted_at_utc = _utc_now()
        notes.append(f"day profit stop: ${realised:,.2f} realised today has "
                     f"reached the ${profit_stop:,.2f} ceiling — the Best Day "
                     f"share as a live rule, not just a backtest constraint")
    return fresh, notes


def trade_would_breach_day_stop(
    rules: ThunderboltClassicRules,
    ledger: DayLedger,
    *,
    prospective_risk_usd: float,
    cfg: DailyStopConfig | None = None,
) -> str:
    """The last trade before a stop is the one that crosses it.

    Halting *after* a loss is too late to be a stop: the trade that takes the day
    past its allowance has already been placed. So the prospective risk is checked
    against the remaining allowance BEFORE the order, and a trade that would cross
    the stop is refused rather than placed and then mourned.
    """
    c = cfg or DailyStopConfig()
    loss_stop = c.loss_stop_usd(rules)
    if ledger.realised_usd - prospective_risk_usd <= -loss_stop + POS_2CM:
        return (f"this trade risks ${prospective_risk_usd:,.2f}; today is at "
                f"${ledger.realised_usd:,.2f} against a ${loss_stop:,.2f} stop, so "
                f"taking it would cross the day's loss stop. Refusing it rather "
                f"than placing it and stopping afterwards.")
    return ""


# --------------------------------------------------------------------------- #
# The arming switch
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskWindow:
    """The interval of per-trade risk that satisfies the target AND the daily limit.

    ``exists`` is the answer to a different question from ``hi_usd``, and conflating
    them cost a real result on 2026-09-19: a gate leg asking *"does a legal size
    exist?"* was implemented as *"does the largest size the single-day bound implies
    survive?"*, which reported FAIL where the truth was PASS. A bound answers "how big
    can this be"; existence answers "can this be at all". Both are needed, and they are
    not interchangeable.

    ``hi_usd`` is set by the worst DAY. That is NOT the true ceiling for an account
    with a trailing shield: measured on DAILY-ONE, the window's upper end allowed
    $716.85 while only $233.99 survived, because a trailing drawdown is a property of
    the *sequence* of days. So ``hi_usd`` is an optimistic bound and ``note`` says so
    rather than letting a caller mistake it for a survivable size.
    """

    exists: bool
    lo_usd: float
    hi_usd: float
    worst_day_r: float
    total_r: float
    note: str = ""

    @property
    def width_usd(self) -> float:
        return max(0.0, self.hi_usd - self.lo_usd)


#: Emitted whenever a window's upper bound comes from a single day, so no caller can
#: read `hi_usd` as a survivable size without meeting the caveat.
SINGLE_DAY_BOUND_CAVEAT = (
    "hi_usd is bounded by the worst single day, which is an OPTIMISTIC ceiling: the "
    "trailing shield floors equity below its high-water mark, so a run of losing days "
    "can breach at a size no single-day bound forbids. Bisect for the largest "
    "surviving size before sizing from this window.")


def feasible_risk_window(
    rules: ThunderboltClassicRules,
    day_pnl_r: Sequence[float] | Mapping,
) -> RiskWindow:
    """The closed-form feasible risk-per-trade interval, from day-level results in R.

    From ``profit_target <= r * sum(d)`` and ``r * |min(d)| <= daily_limit``::

        r >= target / sum(d)          and          r <= limit / |min(d)|

    The interval is empty exactly when the worst day is larger than
    ``limit / target`` times the whole window's profit — that is, when no position size
    can both reach the target and stay inside the day. Best Day contributes no bound at
    all, because it is scale-invariant; that absence is itself the finding recorded in
    `docs/GOLD_BEST_DAY_STUDY_20260919.md`.

    Pure arithmetic: no MT5, no simulation, no clock. The survival test that accounts
    for the trailing shield needs the trade sequence and lives in the research scripts.
    """
    days = list(day_pnl_r.values()) if isinstance(day_pnl_r, Mapping) else list(day_pnl_r)
    if not days:
        return RiskWindow(exists=False, lo_usd=float("inf"), hi_usd=0.0,
                          worst_day_r=0.0, total_r=0.0,
                          note="no day-level results to derive a window from")
    total_r = sum(days)
    worst_day_r = min(days)
    if total_r <= POS_2CM:
        return RiskWindow(exists=False, lo_usd=float("inf"), hi_usd=0.0,
                          worst_day_r=worst_day_r, total_r=total_r,
                          note=f"no profit in the window ({total_r:+.2f}R), so no "
                               f"size reaches the target")
    lo = rules.profit_target_usd / total_r
    hi = (rules.daily_loss_limit_usd / abs(worst_day_r)
          if worst_day_r < 0 else float("inf"))
    note = SINGLE_DAY_BOUND_CAVEAT
    if lo > hi:
        return RiskWindow(exists=False, lo_usd=lo, hi_usd=hi,
                          worst_day_r=worst_day_r, total_r=total_r,
                          note=f"window is EMPTY: the worst day ({worst_day_r:+.2f}R) "
                               f"exceeds {rules.daily_loss_limit_usd /
                               rules.profit_target_usd:.2f}x the whole window's "
                               f"profit, so no size satisfies both constraints. "
                               + note)
    return RiskWindow(exists=True, lo_usd=lo, hi_usd=hi, worst_day_r=worst_day_r,
                      total_r=total_r, note=note)


# --------------------------------------------------------------------------- #
# The trailing shield, addressed PROSPECTIVELY
# --------------------------------------------------------------------------- #


def worst_loss_run(day_pnl_r: Sequence[float] | Mapping) -> tuple[int, float]:
    """(longest run of consecutive losing days, that run's total in R).

    Exists because the shield is a property of the sequence, and a run is the unit the
    rule actually punishes. Measured on DAILY-ONE: the worst run is 5 days for -5.13R
    against the window's 6.41R peak-to-trough and +12.83R total -- half the window's
    entire profit sits in one losing sequence.
    """
    days = list(day_pnl_r.values()) if isinstance(day_pnl_r, Mapping) else list(day_pnl_r)
    best_k, best_depth, k, depth = 0, 0.0, 0, 0.0
    for d in days:
        if d < 0:
            k += 1
            depth += d
            if k > best_k:
                best_k, best_depth = k, depth
        else:
            k, depth = 0, 0.0
    return best_k, best_depth


@dataclass(frozen=True)
class SequenceRiskCeiling:
    """Largest per-trade risk at which the measured worst run cannot breach the shield.

    PROSPECTIVE BY CONSTRUCTION, and that is the whole point. The DAILY-SEQ run tested
    the reactive alternative -- a brake that skips the days after a losing day -- and
    measured it as a dead end: the losing run shortened (5 -> 4 days) but the drawdown
    did NOT fall (6.41 -> 6.66R), the survivable size collapsed to **$0**, and Best Day
    compliance broke (9.6% -> 29.8%), because trading fewer days re-clusters the winners.
    A post-loss rule acts after the damage is taken and then removes profitable days.

    The prospective rule reserves the room BEFORE the run arrives. With the shield
    flooring equity at ``peak * (1 - max_dd_pct)``::

        risk <= (peak - floor) / (k * |worst_day_r|)

    ``run_days`` and ``worst_day_r`` come from measurement (:func:`worst_loss_run`), not
    from a chosen risk appetite, so the ceiling tightens exactly when the market gets
    worse rather than when the operator feels worse.

    **THIS IS A PRE-FILTER, NOT AN AUTHORITY, AND THE MEASUREMENT SAYS WHY.** The first
    implementation of this function multiplied ``peak_equity`` by ``rules.max_dd_pct``,
    which is **6.0 — a percentage, not a fraction** — and returned $28,673.80 where only
    $233.99 survives. Corrected it returns $285.71, and that is *still* above the
    bisected survivable size, because the shield TRAILS: room computed at one instant
    assumes a peak that the run itself moves. So the authoritative size is always the
    sequence simulation (:func:`max_surviving_risk` in the research harness); use this
    closed form only to reject a size cheaply, and only when it sits BELOW the
    simulation's answer.
    """

    exists: bool
    risk_usd: float
    run_days: int
    worst_day_r: float
    room_usd: float
    note: str = ""


def sequence_risk_ceiling_usd(
    rules: ThunderboltClassicRules,
    *,
    peak_equity: float,
    worst_day_r: float,
    run_days: int,
    equity: float | None = None,
) -> SequenceRiskCeiling:
    """Prospective trail-shield ceiling from a measured losing run.

    ``equity`` is the CURRENT equity and defaults to ``peak_equity``, which is the most
    permissive case (a fresh account at its high-water mark). The room that matters is
    the distance from *current* equity down to a floor that is anchored to the *peak*::

        room = equity - drawdown_floor_usd(peak_equity)

    Passing the peak here was the second half of the same mistake as the percent/fraction
    error: it measured the room from a level the account is not standing on. Measured on
    DAILY-ONE, that alone left the closed form 22.5% above the bisected survable size
    ($286.74 vs $233.99) even after the units were fixed. Recompute this every day from
    live equity, and treat the sequence simulation as the authority regardless.

    Returns ``exists=False`` with ``risk_usd=0.0`` when no positive size can absorb the
    run, so a caller must handle "cannot trade this" as its own outcome instead of
    reading a zero as a small size.
    """
    if run_days < 1:
        return SequenceRiskCeiling(
            exists=False, risk_usd=0.0, run_days=run_days, worst_day_r=worst_day_r,
            room_usd=0.0,
            note="run_days must be >= 1; there is always at least the day in hand")
    room = (equity if equity is not None else peak_equity) \
        - rules.drawdown_floor_usd(peak_equity)
    if room <= POS_2CM:
        return SequenceRiskCeiling(
            exists=False, risk_usd=0.0, run_days=run_days, worst_day_r=worst_day_r,
            room_usd=max(0.0, room),
            note=(f"no shield room left: current equity is within ${POS_2CM:.2f} of the "
                  f"trailing floor for a peak of ${peak_equity:,.2f}. There is no size "
                  f"to compute and none to trade."))
    if worst_day_r >= 0:
        # No losing day measured in the window. That is NOT a licence to size freely:
        # it means the run estimate is absent, and an absent estimate must not be read
        # as an infinite ceiling. Report no ceiling rather than a fabricated one.
        return SequenceRiskCeiling(
            exists=False, risk_usd=0.0, run_days=run_days, worst_day_r=worst_day_r,
            room_usd=room,
            note=(f"no losing day measured (worst {worst_day_r:+.2f}R), so this window "
                  f"cannot bound a loss run. Refusing to infer a ceiling from an "
                  f"absent measurement -- size from the day-level window instead and "
                  f"say so."))
    risk = room / (run_days * abs(worst_day_r))
    return SequenceRiskCeiling(
        exists=risk > POS_2CM, risk_usd=max(0.0, risk), run_days=run_days,
        worst_day_r=worst_day_r, room_usd=room,
        note=(f"${room:,.2f} of trailing room reserved for a {run_days}-day run at "
              f"{worst_day_r:+.2f}R/day"))


@dataclass(frozen=True)
class GateCriteria:
    """The frozen walk-forward criteria a configuration must clear to be armed.

    Provenance: ``docs/SYNTHETIC_GATE_V2.md`` (the original certified gate) and
    the pre-registered protocol in ``docs/GOLD_WFO_PROTOCOL.md``. These numbers
    are NOT tunable here — changing one changes what "validated" means, so they
    are pinned in tests and in the gate document they come from.
    """

    min_t_stat: float = 1.5
    min_positive_fold_pct: float = 60.0
    min_oos_trades: int = 100
    require_beats_null: bool = True
    require_cost_included: bool = True


@dataclass(frozen=True)
class ValidationRecord:
    """A walk-forward result, as evidence rather than as a claim.

    ``artifact_path`` and ``sha256`` are required so the record points at a file
    that can be re-read, instead of being a JSON blob asserting its own verdict.
    A record whose artifact is missing, or whose hash does not match, is not
    evidence and the gate refuses it.
    """

    symbol: str
    config_id: str
    verdict: str
    t_stat: float
    positive_fold_pct: float
    oos_trades: int
    beats_null: bool
    cost_included: bool
    artifact_path: str
    sha256: str
    recorded_utc: str

    @classmethod
    def load(cls, path: str | os.PathLike) -> "ValidationRecord":
        """Read a record from disk, refusing anything malformed.

        Every field is required. A validator that defaults a missing ``t_stat``
        to zero would be safe, but one that defaults a missing ``verdict`` to
        ``"PASS"`` would arm a strategy on a truncated file — so absence is an
        error, not a default.
        """
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        missing = [f.name for f in cls.__dataclass_fields__.values()
                   if f.name not in raw]
        if missing:
            raise ValueError(
                f"validation record {path} is missing {', '.join(missing)} — "
                f"a partial record is not evidence and will not arm anything")
        return cls(**{k: raw[k] for k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ArmingDecision:
    """Whether the system may trade, and what specifically is missing."""

    armed: bool
    reasons: tuple[str, ...] = ()
    symbol: str = ""
    config_id: str = ""

    def __bool__(self) -> bool:  # allows `if arming:`
        return self.armed


DEFAULT_ARM_PATH = "artifacts/live/armed.json"
DEFAULT_VALIDATION_PATH = "artifacts/live/validation_record.json"


class ArmingGate:
    """The single switch that keeps execution inert until a config is validated.

    DESIGN: **fail-closed on every axis, and OFF by default.**

    Three independent things must all be true before this returns armed:

    1. A :class:`ValidationRecord` exists on disk and its artifact is present
       with a matching sha256.
    2. That record clears every :class:`GateCriteria` threshold.
    3. An operator arming file exists **naming the same config_id**.

    (1) and (2) are the strategy's business; (3) is the human's. They are
    separate files on purpose so that neither can be satisfied by editing the
    other — a gate that one file can satisfy is a gate that one mistake can
    satisfy.

    The switch is OFF when a file is absent, unreadable, malformed, expired, or
    names a different configuration. Every one of those paths returns
    ``armed=False`` with a reason; none of them raises into a default-allow.
    """

    def __init__(
        self,
        *,
        arm_path: str | os.PathLike = DEFAULT_ARM_PATH,
        validation_path: str | os.PathLike = DEFAULT_VALIDATION_PATH,
        criteria: GateCriteria | None = None,
        max_age_days: float | None = 90.0,
        now_utc: str | None = None,
    ) -> None:
        self.arm_path = Path(arm_path)
        self.validation_path = Path(validation_path)
        self.criteria = criteria or GateCriteria()
        self.max_age_days = max_age_days
        self.now_utc = now_utc

    # -- helpers ----------------------------------------------------------- #

    def _fail(self, *reasons: str, symbol: str = "", config_id: str = "") -> ArmingDecision:
        return ArmingDecision(armed=False, reasons=tuple(reasons),
                              symbol=symbol, config_id=config_id)

    def read_arm_file(self) -> Mapping:
        if not self.arm_path.is_file():
            raise FileNotFoundError(
                f"no operator arming file at {self.arm_path} — execution is OFF. "
                f"Create it (naming the validated config_id) only when you "
                f"intend to trade.")
        return json.loads(self.arm_path.read_text(encoding="utf-8"))

    # -- the decision ------------------------------------------------------- #

    def evaluate(self) -> ArmingDecision:
        """Return the arming decision. Never raises on a missing file."""
        # 1. operator switch
        if not self.arm_path.is_file():
            return self._fail(
                f"operator arming file absent ({self.arm_path}) — the switch "
                f"defaults to OFF")
        try:
            arm = self.read_arm_file()
        except (OSError, ValueError) as exc:
            return self._fail(f"operator arming file unreadable: {exc}")

        if arm.get("armed") is not True:
            return self._fail(
                f"operator arming file does not set \"armed\": true")

        armed_config = str(arm.get("config_id", "")).strip()
        symbol = str(arm.get("symbol", "")).strip()
        if not armed_config:
            return self._fail(
                "operator arming file names no config_id — refusing to arm "
                "against an unspecified configuration", symbol=symbol)

        # 2. validation evidence
        if not self.validation_path.is_file():
            return self._fail(
                f"no validation record at {self.validation_path} — nothing has "
                f"cleared the walk-forward gate, so there is nothing to arm",
                symbol=symbol, config_id=armed_config)

        try:
            record = ValidationRecord.load(self.validation_path)
        except (OSError, ValueError, TypeError) as exc:
            return self._fail(f"validation record unusable: {exc}",
                              symbol=symbol, config_id=armed_config)

        # 3. the two files must agree on WHAT is being armed
        if record.config_id != armed_config:
            return self._fail(
                f"config mismatch: the switch names {armed_config!r} but the "
                f"validation record is for {record.config_id!r} — arming one "
                f"strategy on another's evidence is how an unvalidated system "
                f"goes live",
                symbol=symbol, config_id=armed_config)

        bad = self._threshold_failures(record)
        if bad:
            return self._fail(*bad, symbol=symbol, config_id=armed_config)

        # evidence must point at a real, unmodified artifact
        art = Path(record.artifact_path)
        if not art.is_file():
            return self._fail(
                f"validation record cites {record.artifact_path}, which does "
                f"not exist — a verdict whose evidence is missing is a claim, "
                f"not a result",
                symbol=symbol, config_id=armed_config)
        if record.sha256:
            import hashlib
            got = hashlib.sha256(art.read_bytes()).hexdigest()
            if got != record.sha256:
                return self._fail(
                    f"validation artifact {record.artifact_path} has changed "
                    f"since it was certified (sha256 {got[:12]}… vs recorded "
                    f"{record.sha256[:12]}…) — re-run the walk-forward",
                    symbol=symbol, config_id=armed_config)

        if self.max_age_days is not None and self.now_utc:
            stale = self._age_days(record.recorded_utc)
            if stale is not None and stale > self.max_age_days:
                return self._fail(
                    f"validation is {stale:.0f} days old (limit "
                    f"{self.max_age_days:g}) — a stale certificate is not a "
                    f"live one",
                    symbol=symbol, config_id=armed_config)

        return ArmingDecision(
            armed=True, symbol=symbol, config_id=armed_config,
            reasons=(f"armed: {record.config_id} cleared the gate "
                     f"(t={record.t_stat:+.2f}, "
                     f"{record.positive_fold_pct:.0f}% folds positive, "
                     f"{record.oos_trades} OOS trades)",))

    def _threshold_failures(self, record: ValidationRecord) -> list[str]:
        c = self.criteria
        out: list[str] = []
        if record.verdict.strip().upper() != "PASS":
            out.append(f"validation verdict is {record.verdict!r}, not PASS")
        if record.t_stat < c.min_t_stat:
            out.append(
                f"t-stat {record.t_stat:+.2f} is below the required "
                f"{c.min_t_stat:g} — indistinguishable from zero")
        if record.positive_fold_pct < c.min_positive_fold_pct:
            out.append(
                f"{record.positive_fold_pct:.0f}% of folds positive, below the "
                f"required {c.min_positive_fold_pct:g}% — the result is carried "
                f"by a minority of the window")
        if record.oos_trades < c.min_oos_trades:
            out.append(
                f"{record.oos_trades} out-of-sample trades is below the "
                f"required {c.min_oos_trades} — too few to distinguish from "
                f"noise")
        if c.require_beats_null and not record.beats_null:
            out.append("result does not beat its matched random-entry null")
        if c.require_cost_included and not record.cost_included:
            out.append("cost was not included in the result")
        return out

    def _age_days(self, recorded_utc: str) -> float | None:
        from datetime import datetime, timezone
        try:
            then = datetime.fromisoformat(recorded_utc.replace("Z", "+00:00"))
            now = datetime.fromisoformat(self.now_utc.replace("Z", "+00:00"))
        except ValueError:
            return None
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return (now - then).total_seconds() / 86400.0

    def evidence_family(self, ea_source: str | os.PathLike | None = None) -> dict:
        """Does the evidence the arming record cites describe THIS strategy?

        THE DEFECT THIS CLOSES (measured 2026-09-21). ``artifacts/live/armed.json`` cites
        ``artifacts/gold_wfo.json`` in its ``gate_detail``, and that artifact is a walk-forward
        of an **M15 EMA stack** (its only trigger axis is ``spec.grid.ema_sets``, and neither
        Bollinger nor RSI appears anywhere in the engine that wrote it). The EA's trigger is
        BB(20, 2.0) touch-back-inside or RSI(14) 70/30. Measured on the same 174 days of M15
        bars the two rules agree on the same bar AND the same direction 258 times — **3.4%** of
        the gate engine's 7,606 signals. So the verdict the record cites is a statement about a
        different strategy, and nothing in the record said so.

        A disagreement is a REFUSAL unless the arming record says so in words
        (``gate_family_mismatch``), because what is being prevented is a verdict about one
        strategy being *presented* as the evidence for another — not an operator who knows and
        says so. A declaration that cannot be read on either side is also a refusal: "we could
        not tell" is not agreement, and defaulting it to one would make this check decorative.
        """
        root = Path(__file__).resolve().parents[3]
        src = Path(ea_source) if ea_source else root / DEFAULT_EA_SOURCE
        try:
            ea = ea_strategy_family(src)
        except OSError as exc:
            return {"state": "unknown", "ea": None, "artifact": None, "disclosed": False,
                    "reason": f"cannot read the EA source {src}: {exc}"}
        try:
            arm = self.read_arm_file()
        except (FileNotFoundError, ValueError) as exc:
            return {"state": "no-arm-record", "ea": ea, "artifact": None,
                    "disclosed": False,
                    "reason": f"no readable arming record ({exc}) — nothing cites any evidence"}
        detail = arm.get("gate_detail") or {}
        cited = detail.get("artifact") or detail.get("artifact_path")
        disclosed = bool(arm.get("gate_family_mismatch"))
        if not cited:
            return {"state": "unknown", "ea": ea, "artifact": None, "disclosed": disclosed,
                    "reason": "the arming record cites no validation artifact, so there is no "
                              "declared strategy family to compare"}
        art_path = Path(cited)
        if not art_path.is_absolute():
            art_path = root / cited
        try:
            art = artifact_strategy_family(art_path)
        except (OSError, ValueError) as exc:
            return {"state": "unknown", "ea": ea, "artifact": None, "disclosed": disclosed,
                    "reason": f"cannot read the cited artifact {cited}: {exc}"}
        base = {"ea": ea, "artifact": art, "disclosed": disclosed}
        if ea["family"] == FAMILY_UNKNOWN or art["family"] == FAMILY_UNKNOWN:
            return {**base, "state": "unknown",
                    "reason": "a strategy family is not declared on both sides and cannot be "
                              f"established — EA: {ea['evidence']}; artifact: {art['evidence']}"}
        if ea["family"] == art["family"]:
            return {**base, "state": "match",
                    "reason": f"both sides declare {ea['family']} — EA: {ea['evidence']}; "
                              f"artifact: {art['evidence']}"}
        reason = (f"the cited artifact measured {art['family']} ({art['evidence']}), while the "
                  f"EA implements {ea['family']} ({ea['evidence']}) — a verdict about a "
                  f"different strategy, presented as this arm's evidence")
        return {**base, "state": "disclosed-mismatch" if disclosed else "mismatch",
                "reason": reason + (" [the arming record discloses this]" if disclosed
                                    else " [the arming record does NOT say so]")}


# --------------------------------------------------------------------------- #
# Strategy families: which rule did a result measure?
# --------------------------------------------------------------------------- #

#: The EA whose behaviour every certification has to describe.
DEFAULT_EA_SOURCE = "mql5/MIDASTOUCH/MidastouchAI.mq5"

FAMILY_UNKNOWN = "undeclared"
FAMILY_BB_RSI = "bb_rsi_trigger"
FAMILY_EMA_STACK = "ema_stack_trigger"


def ea_strategy_family(source_path: str | os.PathLike) -> dict:
    """What entry rule does this EA source implement? Read from the source, not asserted.

    Reads the trigger the source actually builds (``iBands``/``iRSI`` handles and the inputs
    that parameterise them) rather than a comment or a version string, because the whole
    failure this guards against is a *label* that disagrees with the code.
    """
    import re
    text = Path(source_path).read_text(encoding="utf-8", errors="replace")

    def num(name: str, cast=float):
        m = re.search(rf"input\s+\w+\s+{name}\s*=\s*([0-9.]+)", text)
        return cast(m.group(1)) if m else None

    bb, dev = num("InpBBPeriod", int), num("InpBBDev")
    rsi = num("InpRSIPeriod", int)
    lo, up = num("InpRSILower"), num("InpRSIUpper")
    macro = num("InpMacroEmaPeriod", int)
    if "iBands(" in text and "iRSI(" in text and bb and rsi:
        return {"family": FAMILY_BB_RSI, "declared": True,
                "evidence": f"iBands + iRSI handles: BB({bb}, {dev}), RSI({rsi}) "
                            f"{lo:g}/{up:g}, regime EMA{macro} on H1+H4"}
    if "EMA_FAST" in text or re.search(r"\be_f\b\s*[<>]\s*\be_m\b", text):
        return {"family": FAMILY_EMA_STACK, "declared": True,
                "evidence": "an EMA-stack trigger in the source"}
    return {"family": FAMILY_UNKNOWN, "declared": False,
            "evidence": "no Bollinger/RSI handles and no EMA-stack trigger found"}


def artifact_strategy_family(artifact_path: str | os.PathLike) -> dict:
    """What entry rule did this validation artifact measure? Read, then refuse if unreadable.

    Two shapes are recognised, both of them by their own declaration rather than by guessing:
    an artifact carrying a ``rule.trigger`` in words (``rule.trigger``), and one whose only
    trigger axis is an EMA grid (``spec.grid.ema_sets`` — the shape
    ``scripts/gold_walkforward.py`` writes). Anything else is ``FAMILY_UNKNOWN``, which the
    gate treats as a refusal: an artifact that does not say what it measured cannot be shown
    to describe the arm.
    """
    import json
    raw = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"family": FAMILY_UNKNOWN, "declared": False,
                "evidence": "the artifact is not a JSON object"}
    rule = raw.get("rule") if isinstance(raw.get("rule"), dict) else {}
    trigger = str(rule.get("trigger", "")).strip()
    if trigger:
        upp = trigger.upper()
        if "BB(" in upp and "RSI" in upp:
            fam = FAMILY_BB_RSI
        elif "EMA" in upp:
            fam = FAMILY_EMA_STACK
        else:
            fam = FAMILY_UNKNOWN
        return {"family": fam, "declared": True, "evidence": f"rule.trigger = {trigger!r}"}
    spec = raw.get("spec") if isinstance(raw.get("spec"), dict) else {}
    grid = spec.get("grid") if isinstance(spec.get("grid"), dict) else {}
    if "ema_sets" in grid:
        return {"family": FAMILY_EMA_STACK, "declared": True,
                "evidence": "spec.grid.ema_sets — the grid's trigger axis is an EMA stack"}
    return {"family": FAMILY_UNKNOWN, "declared": False,
            "evidence": ("no rule.trigger and no spec.grid.ema_sets — this artifact does not "
                         "declare which rule it measured")}
