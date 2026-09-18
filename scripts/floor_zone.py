#!/usr/bin/env python3
"""Floor-zone boundary math — the exact equity at which each engine/symbol
pair stops being tradeable, per the floor-mode policy contract.

The boundary chain (all in dollars of virtual equity, per arm engine x symbol):

  min_lot_risk   = (stop_distance / tick_size) * calibrated_tick_value * volume_min
  floor onset    = min_lot_risk / risk_fraction      (below this, sizing floors)
  strangulation  = min_lot_risk / budget_pct         (below this, EVERY entry vetoes)
  halt floor     = window_start_equity * (1 - floor_mode_max_dd_pct)

The calibrated tick value mirrors the EA's CalibratedTickValue(): the broker's
SYMBOL_TRADE_TICK_VALUE is only trusted within TICK_VALUE_TOLERANCE of the
geometric value (tick_size * contract_size); otherwise the geometric value
overrides (2026-09-16 live check: broker 0.0001 vs geometric 0.01 on V75 —
the override is load-bearing; using the raw API value understates risk 100x).

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

    @property
    def calibrated_tick_value(self) -> float:
        """Mirror of CalibratedTickValue(): geometric override outside 5%."""
        geo = self.tick_size * self.contract_size
        if (self.tick_value_raw <= 0.0 or self.tick_size <= 0.0
                or abs(self.tick_value_raw - geo) > TICK_VALUE_TOLERANCE * geo):
            return geo
        return self.tick_value_raw


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
        sd = SymbolData(symbol=symbol, volume_min=float(si.volume_min),
                        tick_size=float(si.trade_tick_size),
                        tick_value_raw=float(si.trade_tick_value),
                        contract_size=float(si.trade_contract_size))
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
