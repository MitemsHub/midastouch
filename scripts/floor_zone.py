#!/usr/bin/env python3
"""Floor-zone boundary math — the exact equity at which each engine/symbol
pair stops being tradeable, per the floor-mode policy contract.

The boundary chain (all in dollars of virtual equity, per arm engine x symbol):

  min_lot_risk   = (stop_distance / tick_size) * calibrated_tick_value * volume_min
  floor onset    = min_lot_risk / risk_fraction      (below this, sizing floors)
  strangulation  = min_lot_risk / budget_pct         (below this, EVERY entry vetoes)
  halt floor     = window_start_equity * (1 - floor_mode_max_dd_pct)

The calibrated tick value mirrors the EA's DollarPerUnitPerLot(), and the AUTHORITY
ORDER is the whole point of it (2026-09-20):

  1. what the broker SETTLES — order_calc_profit over one price unit per lot;
  2. contract_size x tick_size (geometric);
  3. the raw SYMBOL_TRADE_TICK_VALUE.

Both earlier rules failed on a real venue, in opposite directions. On V75 the raw
value (0.0001) understated the geometric (0.01) by 100x, so the geometric override
was load-bearing. On Upcomers XAUUSD the raw value (0.10) *is* the odd one out — the
contract (100 x 0.01 = 1.00) and order_calc_profit ($100 per 1.0 price unit) agree
with each other and the raw value is 10x low — and a rule that trusted the broker
would have sized 10x the intended risk on a $25,000 prop account. Neither number is
reliable by kind; only the settled one is authoritative.

ATR mirrors the EA's iATR (Wilder smoothing) at the last CLOSED bar of the
engine's anchor timeframe: v28 family and V75MacroEngine = 2.0 x ATR(H1, 14);
the MitemshubAI pullback engines = 1.7 x ATR(M15, 14) BEFORE swing widening
(the widening is entry-relative and only ever RAISES the boundary, which is
disclosed as such, never hidden).

Pure functions only in this module; live MT5 access is injected via
fetch_symbol_data() so every boundary is testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Frozen policy constants (ARM_A2_RESTART §2 amendment 2026-09-16)
BUDGET_PCT = 15.0          # InpMaxTotalRiskPct — the account-budget cap
FLOOR_MODE_MAX_DD_PCT = 30.0   # InpFloorModeMaxDDPct — hard halt floor
TICK_VALUE_TOLERANCE = 0.05    # the EA's 5% identity rule

# Per-engine stop geometry (multiplier x Wilder ATR at the last closed bar)
ENGINES = {
    "v28":       {"tf": "H1",  "period": 14, "sl_mult": 2.0},   # arms D/A2
    "v75macro":  {"tf": "H1",  "period": 14, "sl_mult": 2.0},   # arm C
    "pullback":  {"tf": "M15", "period": 14, "sl_mult": 1.7},   # arms A/B (+swing widening, see disclosure)
}

# Symbols the fleet trades (extensible: a future symbol needs only appear
# here — specs and ATR flow from the same broker connection).
SYMBOLS = ("Volatility 75 Index",)

# Known arm bases (virtual window-start equity; A2 pre-attach is a planning row)
ARM_BASE_EQUITY = {
    "A_tp18": 50.0, "B_tp24": 50.0, "C_v75": 50.0, "D_fwd": 50.0, "A2": 1000.0,
}
ARM_ENGINE = {
    "A_tp18": "pullback", "B_tp24": "pullback", "C_v75": "v75macro",
    "D_fwd": "v28", "A2": "v28",
}


@dataclass
class SymbolData:
    """Live specs + Wilder ATR per timeframe, as the EA sees them."""
    symbol: str
    volume_min: float
    tick_size: float
    tick_value_raw: float
    contract_size: float
    atr: dict = field(default_factory=dict)   # tf -> ATR at last closed bar
    #: $ per 1.0 price-unit move per lot, from order_calc_profit. 0.0 = unknown,
    #: which is a real answer and falls through to the geometric value.
    settled_unit_value: float = 0.0

    @property
    def settled_tick_value(self) -> float:
        """The broker's own settled value, expressed per TICK.

        `settled_unit_value` is dollars per 1.0 price unit per lot and a tick is a
        FRACTION of a price unit, so this multiplies: $100 per unit at a 0.01 tick
        is $1.00 per tick. (Upcomers XAUUSD: contract 100 x 0.01 = $1.00, settled
        $1.00, raw SYMBOL_TRADE_TICK_VALUE 0.10 — the raw field is the odd one.)
        """
        if self.settled_unit_value <= 0.0 or self.tick_size <= 0.0:
            return 0.0
        return self.settled_unit_value * self.tick_size

    @property
    def calibrated_tick_value(self) -> float:
        """$ per tick per lot, from the most authoritative source that exists.

        Authority order: settled > geometric > raw (see the module docstring).
        Returns 0.0 when nothing is usable, so `compute_boundary` fail-closes
        instead of sizing on a guess.
        """
        settled = self.settled_tick_value
        if settled > 0.0:
            return settled
        geo = self.tick_size * self.contract_size
        raw = self.tick_value_raw
        # Below the settled value, the older rules stand: a raw value that agrees
        # with geometry inside TICK_VALUE_TOLERANCE is the venue's real number and
        # is used as-is; a raw value that disagrees is the one not to trust.
        if raw > 0.0 and geo > 0.0 and abs(raw - geo) <= TICK_VALUE_TOLERANCE * geo:
            return raw
        if geo > 0.0:
            return geo
        return raw if raw > 0.0 else 0.0

    @property
    def tick_value_disagreement(self) -> float | None:
        """How far the raw API value sits from the calibrated one, as a ratio.

        Returned rather than acted on: a venue whose own two answers disagree is
        worth reporting (Upcomers XAUUSD reports 0.10 where every other route says
        1.00), but the sizing decision is already made by the authority order.
        """
        cal = self.calibrated_tick_value
        if cal <= 0.0 or self.tick_value_raw <= 0.0 or cal == self.tick_value_raw:
            return None
        return abs(self.tick_value_raw - cal) / cal


@dataclass
class Boundary:
    engine: str
    symbol: str
    stop_distance: float
    min_lot_risk: float
    floor_onset_equity: float      # below: sizing floors to min lot
    strangulation_equity: float    # below: every entry vetoes (budget cap)
    halt_equity: float             # window-start * (1 - 30%)
    disclosure: str = ""


def wilder_atr(closes_highs_lows: list[tuple[float, float, float]], period: int) -> float | None:
    """iATR parity: Wilder smoothing over TRUE ranges of CLOSED bars.
    Input: most-recent-last (high, low, close) of CLOSED bars (>= period + 1
    rows so the first TR has a previous close). Returns None if unusable."""
    if len(closes_highs_lows) < period + 2:
        return None
    trs = []
    for i in range(1, len(closes_highs_lows)):
        h, l, c = closes_highs_lows[i]
        _, pc, _ = closes_highs_lows[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def compute_boundary(engine: str, symbol: str, sd: SymbolData,
                     risk_fraction: float = 0.01,
                     budget_pct: float = BUDGET_PCT,
                     window_start_equity: float | None = None) -> Boundary | None:
    """The full boundary chain for one engine x symbol. None when the symbol
    data is unusable (fail-closed upstream adds a disclosure instead)."""
    geo = ENGINES[engine]
    atr = sd.atr.get(geo["tf"])
    tv = sd.calibrated_tick_value
    if not atr or atr <= 0 or sd.tick_size <= 0 or tv <= 0 or sd.volume_min <= 0:
        return None
    stop_distance = geo["sl_mult"] * atr
    per_lot = (stop_distance / sd.tick_size) * tv
    min_lot_risk = per_lot * sd.volume_min
    disclosure = ""
    if engine == "pullback":
        disclosure = ("1.7x ATR base — swing widening (+0.15 ATR) raises the "
                      "boundary when it binds; treat min-lot risk as a floor "
                      "estimate for the pullback engines")
    halt = (window_start_equity * (1.0 - FLOOR_MODE_MAX_DD_PCT / 100.0)
            if window_start_equity is not None else float("nan"))
    return Boundary(
        engine=engine, symbol=symbol, stop_distance=stop_distance,
        min_lot_risk=min_lot_risk,
        floor_onset_equity=min_lot_risk / risk_fraction,
        strangulation_equity=min_lot_risk / (budget_pct / 100.0),
        halt_equity=halt, disclosure=disclosure)


def classify(veq: float | None, b: Boundary) -> str:
    """Arm verdict against the boundary chain, mechanical and ordered:
    HALTED < STRANGULATED < FLOOR_MODE < TRADING. None veq -> UNKNOWN."""
    if veq is None:
        return "UNKNOWN"
    if veq <= b.halt_equity:
        return "HALTED"
    if veq <= b.strangulation_equity:
        return "STRANGULATED"
    if veq <= b.floor_onset_equity:
        return "FLOOR_MODE"
    return "TRADING"


def fetch_symbol_data(symbol: str, terminal_path: str | None = None) -> SymbolData | None:
    """Live specs + ATRs from a running terminal. Returns None on any
    failure — the caller discloses, never guesses."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    if not mt5.initialize(path=terminal_path) if terminal_path else not mt5.initialize():
        return None
    try:
        si = mt5.symbol_info(symbol)
        if si is None:
            return None
        # The settled value, measured rather than inferred: what the broker says a
        # 1-lot position earns over a one-price-unit move.
        settled = 0.0
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and tick.ask > 0:
            profit = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, 1.0,
                                           tick.ask, tick.ask + 1.0)
            if profit is not None and profit > 0:
                settled = float(profit)
        sd = SymbolData(symbol=symbol, volume_min=float(si.volume_min),
                        tick_size=float(si.trade_tick_size),
                        tick_value_raw=float(si.trade_tick_value),
                        contract_size=float(si.trade_contract_size),
                        settled_unit_value=settled)
        for tf_name, tf in (("H1", mt5.TIMEFRAME_H1), ("M15", mt5.TIMEFRAME_M15)):
            rates = mt5.copy_rates_from_pos(symbol, tf, 1, 140)
            if rates is None or len(rates) < 16:
                continue
            atr = wilder_atr([(float(r["high"]), float(r["low"]),
                               float(r["close"])) for r in rates], 14)
            if atr:
                sd.atr[tf_name] = atr
        return sd if sd.atr else None
    finally:
        mt5.shutdown()
