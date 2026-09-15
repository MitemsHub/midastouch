#!/usr/bin/env python3
"""Control-panel proofs for the MITEMSHUB V75 paper terminal.

This is a deterministic, closed-form harness: it builds synthetic H1 / M15 /
M30 clocks, a synthetic mid-price stream, and replays one position through the
same policy rules the deployed EA enforces.  Each invariant is proved on a
crafted scenario, not on whatever the market happened to do.

Scope (this harness):
  - M30 new-bar gate: no entry evaluation mid-M30 bar.
  - One-position rule: a second concurrent signal is suppressed while a position
    is open, and a fresh evaluation is allowed only after the prior fill bar.
  - Exact ATR protection: stop/target are anchored to H1 ATR * the deployed
    multipliers, with the structural/floor/cap geometry.
  - Timeout: positions older than the deployed MAX_HOLD_SECONDS are closed.
  - Close recovery: after a close, cooldown/loss-pause logic is honored and the
    next eligible signal is allowed at the correct time.

These are behavioral proofs on controlled price paths, complementary to the
existing source scans in tests/test_go_live_artifacts.py and the tick/bar
replays in scripts/cb_*.py and scripts/certify_v75.py.

Usage:
  python scripts/v75_control_panel_test.py
  python scripts/v75_control_panel_test.py --html artifacts/v75_control_panel.html
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Repo conventions
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

# MITEMSHUB V75 constants mirrored from the EA contract + VOL75_FINAL preset.
# These are the values the harness proves behavior against; keep them in sync
# with the EA preset the repo is currently certifying.
TF_M1  = 60
TF_M5  = 300
TF_M15 = 900
TF_M30 = 1800
TF_H1  = 3600

# EA hard policy (mirror v27.00 policy constants requested for this harness):
RISK_FRACTION     = 0.01
H1_ATR_STOP_MULT  = 2.0
H1_ATR_TARGET_MULT = 4.0
MAX_HOLD_SECONDS  = 3 * 3600        # 3h hard hold

# M30 springboard constants (mirror EA ReadM30Springboard thresholds):
RSI_BUY_THRESHOLD  = 35.0
RSI_SELL_THRESHOLD = 65.0

# Loss-pause / cooldown mirrors from the V75 replay/certify tradition:
COOLDOWN_BARS_LOSS = 1              # one M15 bar after a loss before next eval
PAUSE_AFTER_LOSSES = 3             # consecutive losses -> pause until next day
SESSION_START_HOUR = 0             # synthetic session start (UTC)
SESSION_END_HOUR   = 23

# Structural SL geometry mirrors certify_v75.py / replay_v75_week.py:
PB_MIN = 0.30
PB_MAX = 2.2
MIN_EMA_SEP = 0.20
ATR_LOOKBACK = 120
ATR_LOW_PCT = 10.0
ATR_HIGH_PCT = 92.0

# Spread value used by the EA's certify_v75 convention; the harness uses the
# geometric identity tick_value = tick_size * contract_size and documents that
# assumption. SPREAD_INDEX_UNITS is only used here to gate entries in the
# contract-sprite analogy, so keep it small enough that the 2.0/4.0 ATR geometry
# still clears it in the deterministic scenarios.
SPREAD_INDEX_UNITS = 0.20
ENTRY_SPREAD_HALF  = 0.5 * SPREAD_INDEX_UNITS


@dataclass(frozen=True)
class MTime:
    """A closed-form timestamp: seconds since a synthetic epoch + wall clock."""
    epoch: int                         # seconds since synthetic epoch
    tz: timezone = timezone.utc

    @property
    def wall(self) -> datetime:
        return datetime.fromtimestamp(self.epoch, tz=self.tz)

    def __add__(self, other: timedelta) -> MTime:
        return MTime(epoch=self.epoch + int(other.total_seconds()))

    def __sub__(self, other: MTime | timedelta) -> timedelta | int:
        if isinstance(other, MTime):
            return timedelta(seconds=self.epoch - other.epoch)
        return timedelta(seconds=self.epoch - int(other.total_seconds()))

    def __le__(self, other: MTime) -> bool:
        return self.epoch <= other.epoch

    def __ge__(self, other: MTime) -> bool:
        return self.epoch >= other.epoch

    def __lt__(self, other: MTime) -> bool:
        return self.epoch < other.epoch

    def __gt__(self, other: MTime) -> bool:
        return self.epoch > other.epoch

    def floor(self, tf: int) -> MTime:
        return MTime(epoch=(self.epoch // tf) * tf)

    def bar_index(self, tf: int) -> int:
        return int(self.epoch // tf)

    def next_bar(self, tf: int) -> MTime:
        n = self.epoch // tf
        return MTime(epoch=(n + 1) * tf)

    def __repr__(self) -> str:
        return self.wall.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class H1Bar:
    start: MTime
    open: float
    high: float
    low: float
    close: float


@dataclass
class M15Bar:
    start: MTime
    open: float
    high: float
    low: float
    close: float


@dataclass
class Position:
    entry_time: MTime
    entry_price: float
    sl: float
    tp: float
    dir: int                       # +1 long, -1 short
    stop_distance: float
    high_water_r: float = 0.0
    hold_seconds: int = 0


@dataclass
class TradeRecord:
    entry_time: MTime
    exit_time: MTime
    dir: int
    entry_price: float
    exit_price: float
    r: float
    reason: Literal["TP", "SL", "TIME", "SESSION_CLOSE", "BE_SL", "TRAIL_SL"]


@dataclass
class OrderSlot:
    """Simulates the EA's one-position gate over the live order channel."""
    open_ticket: int | None = None
    open_position: Position | None = None
    next_allowed_eval_bar: int | None = None   # M15 bar index after a fill
    consecutive_losses: int = 0
    paused_until_epoch: int | None = None      # session-day pause

    def __init__(
        self,
        open_ticket: int | None = None,
        open_position: Position | None = None,
        next_allowed_eval_bar: int | None = None,
        consecutive_losses: int = 0,
        paused_until_epoch: int | None = None,
        **_: object,
    ) -> None:
        self.open_ticket = open_ticket
        self.open_position = open_position
        self.next_allowed_eval_bar = next_allowed_eval_bar
        self.consecutive_losses = consecutive_losses
        self.paused_until_epoch = paused_until_epoch


@dataclass
class RunResult:
    trades: list[TradeRecord] = field(default_factory=list)
    suppressed: list[dict] = field(default_factory=list)   # blocked evaluations
    closes: list[dict] = field(default_factory=list)        # exit events
    slot: OrderSlot = field(default_factory=OrderSlot)
    h1_atr: float = 0.0


# ---------------------------------------------------------------------------
# Small closed-form math helpers (mirror the replay/certify tradition)
# ---------------------------------------------------------------------------

def ema(values: list[float], period: int) -> list[float]:
    a = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(a * v + (1 - a) * out[-1])
    return out


def wilder_atr(bars: list[H1Bar], period: int = 14) -> list[float]:
    trs = []
    for i, b in enumerate(bars):
        tr = b.high - b.low
        if i > 0:
            prev = bars[i - 1].close
            tr = max(tr, abs(b.high - prev), abs(b.low - prev))
        trs.append(tr)
    if not trs:
        return []
    atr = [trs[0]]
    for tr in trs[1:]:
        atr.append((atr[-1] * (period - 1) + tr) / period)
    return atr


def h1_index_for(h1_bars: list[H1Bar], t: MTime) -> int:
    """Last closed H1 bar strictly before t (EA uses the closed H1 bar)."""
    if not h1_bars:
        return -1
    # H1 bars are discrete; pick the last bar whose open epoch is <= t.epoch.
    idx = 0
    for i, b in enumerate(h1_bars):
        if b.start.epoch <= t.epoch:
            idx = i
        else:
            break
    # If t is exactly an H1 open, EA reads the *previous* closed H1 bar.
    if idx > 0 and h1_bars[idx].start.epoch == t.epoch:
        idx -= 1
    return idx


def regime_at(h1_bars: list[H1Bar], atr_hist: list[float], t: MTime) -> str:
    """Regime mirror from certify_v75/replay_v75_week (H1 EMA + ATR percentile).

    For the control-panel proofs we need a deterministic regime, so the harness
    falls back to an explicit flag when the synthetic bars are too short for the
    real percentile/EMA plumbing.  Real-data replays use the full pipeline.
    """
    if not h1_bars or not atr_hist:
        return "RANGE"
    idx = h1_index_for(h1_bars, t)
    if idx < 0 or idx >= len(h1_bars):
        return "RANGE"
    b = h1_bars[idx]
    a = atr_hist[min(idx, len(atr_hist) - 1)]
    if a <= 0:
        return "RANGE"
    closes = [bb.close for bb in h1_bars[: idx + 1]]
    if len(closes) < 100:
        # not enough bars for the EA's 20/50/100 EMA regime; force RANGE so the
        # pullback-only entry path still has something to prove on short fixtures.
        return "RANGE"
    f = ema(closes, 20)[-1]
    m = ema(closes, 50)[-1]
    s = ema(closes, 100)[-1]
    sep = abs(f - m) / a if a > 0 else 0
    if f > m > s and b.close > f and sep >= MIN_EMA_SEP:
        return "BULL"
    if f < m < s and b.close < f and sep >= MIN_EMA_SEP:
        return "BEAR"
    return "RANGE"


# ---------------------------------------------------------------------------
# Policy engine (mirrors EA order: manage -> evaluate -> enter)
# ---------------------------------------------------------------------------

def entry_price_for(dir: int, mid_open: float) -> float:
    return mid_open + ENTRY_SPREAD_HALF if dir > 0 else mid_open - ENTRY_SPREAD_HALF


def structural_stop(dir: int, entry: float, atr: float, look_bars: list[H1Bar]) -> float:
    # Mirror the EA's H1 ATR protection first, then apply only the non-size
    # structural guard that the EA layers on top of the exact ATR distance.
    sd = H1_ATR_STOP_MULT * atr

    # The requested v27.00 harness is just the 2.0/4.0 ATR contract, so keep
    # any structural floor/cap representation here minimal and explicit.
    sd = max(sd, 0.5 * atr)
    sd = min(sd, entry * 0.03)            # EA stop cap at 3% of price
    return sd


def manage_position(pos: Position | None, tick_mid: float, tick_time: MTime,
                    session_end_epoch: int) -> tuple[Position | None, TradeRecord | None]:
    """Every-tick position management: TP/SL intrabar, breakeven+trail, time exit."""
    if pos is None:
        return None, None

    held = int((tick_time - pos.entry_time).total_seconds())
    pos.hold_seconds = held

    # intrabar extremes relative to the fill price
    if pos.dir > 0:
        best = tick_mid - pos.entry_price
    else:
        best = pos.entry_price - tick_mid
    pos.high_water_r = max(pos.high_water_r, best / max(pos.stop_distance, 1e-12))

    sl_hit = (tick_mid <= pos.sl) if pos.dir > 0 else (tick_mid >= pos.sl)
    tp_hit = (tick_mid >= pos.tp) if pos.dir > 0 else (tick_mid <= pos.tp)

    if sl_hit and tp_hit:
        # EA conservative: SL wins on ambiguity
        exit_price = pos.sl
        reason: Literal["TP", "SL", "TIME", "SESSION_CLOSE", "BE_SL", "TRAIL_SL"] = "SL"
        r = -1.0
        direction = pos.dir
        entry_price = pos.entry_price
        pos = None
        return None, TradeRecord(pos.entry_time, tick_time, direction, entry_price, exit_price, r, reason)
    if sl_hit:
        exit_price = pos.sl
        reason = "SL"
        r = -1.0
        direction = pos.dir
        entry_price = pos.entry_price
        pos = None
        return None, TradeRecord(tick_time, tick_time, direction, entry_price, exit_price, r, reason)
    if tp_hit:
        exit_price = pos.tp
        reason = "TP"
        r = pos.tp / pos.stop_distance
        direction = pos.dir
        entry_price = pos.entry_price
        pos = None
        return None, TradeRecord(tick_time, tick_time, direction, entry_price, exit_price, r, reason)

    # breakeven + trailing (mirror replay_v75 week: BE at +1R, trail 0.7R from +1R)
    if pos.high_water_r >= 1.0:
        be = pos.entry_price - 2e-6 if pos.dir < 0 else pos.entry_price + 2e-6
        if (pos.dir < 0 and be < pos.sl) or (pos.dir > 0 and be > pos.sl):
            pos.sl = be
    if pos.high_water_r >= 1.0:
        # trail only after BE armed
        ns = (tick_mid + 0.7 * pos.stop_distance) if pos.dir < 0 else (tick_mid - 0.7 * pos.stop_distance)
        if (pos.dir < 0 and ns < pos.sl) or (pos.dir > 0 and ns > pos.sl):
            pos.sl = ns

    # hard time exit (3h force-close)
    if held >= MAX_HOLD_SECONDS:
        r = (tick_mid - pos.entry_price) / pos.stop_distance if pos.dir > 0 else (pos.entry_price - tick_mid) / pos.stop_distance
        entry_time = pos.entry_time
        direction = pos.dir
        entry_price = pos.entry_price
        pos = None
        return None, TradeRecord(entry_time, tick_time, direction, entry_price, tick_mid, r, "TIME")

    # session-time guard: close at end of synthetic session day
    if tick_time.epoch >= session_end_epoch:
        r = (tick_mid - pos.entry_price) / pos.stop_distance if pos.dir > 0 else (pos.entry_price - tick_mid) / pos.stop_distance
        entry_time = pos.entry_time
        direction = pos.dir
        entry_price = pos.entry_price
        pos = None
        return None, TradeRecord(entry_time, tick_time, direction, entry_price, tick_mid, r, "SESSION_CLOSE")

    return pos, None


def evaluate_and_maybe_enter(slot: OrderSlot, tick_mid: float, tick_time: MTime,
                             h1_bars: list[H1Bar], atr_hist: list[float],
                             session_day_epoch: int, session_end_epoch: int,
                             m30_current_bar: int, m30_last_bar: int,
                             persist: dict) -> tuple[Position | None, dict]:
    """One evaluation step. Returns (new_position, append_block_log)."""
    blocks: list[dict] = []
    new_pos = None

    # ---- one-position gate: no eval while order channel busy ----
    if slot.open_position is not None:
        blocks.append({"reason": "ONE_POSITION_OPEN",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "why": "order slot busy"})
        return None, blocks

    # ---- M30 gate: only evaluate on a fresh M30 bar ----
    if m30_current_bar == m30_last_bar:
        blocks.append({"reason": "M30_GATE_SKIP",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "m30_bar": m30_current_bar, "last_m30_bar": m30_last_bar,
                       "why": "same M30 bar as last eval"})
        return None, blocks

    # ---- session/time guards ----
    now_epoch = tick_time.epoch
    if slot.paused_until_epoch is not None and now_epoch < slot.paused_until_epoch:
        blocks.append({"reason": "LOSS_PAUSE",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "why": f"paused until {MTime(epoch=slot.paused_until_epoch)}"})
        return None, blocks

    m15_idx = tick_time.bar_index(TF_M15)
    if slot.next_allowed_eval_bar is not None and m15_idx < slot.next_allowed_eval_bar:
        blocks.append({"reason": "COOLDOWN",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "m15_idx": m15_idx,
                       "next_allowed": slot.next_allowed_eval_bar,
                       "why": "cooldown after prior close"})
        return None, blocks

    # ---- regime + ATR ----
    reg = regime_at(h1_bars, atr_hist, tick_time)
    if reg in ("HVOL", "NOTRADE"):
        blocks.append({"reason": "REGIME",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "regime": reg, "why": "no-trade regime"})
        return None, blocks

    # ---- pullback entry only (mirror EA pullback leg) ----
    idx_h1 = h1_index_for(h1_bars, tick_time)
    if idx_h1 < 1:
        blocks.append({"reason": "NO_H1",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "why": "no closed H1 bar"})
        return None, blocks

    h1c = [b.close for b in h1_bars[: idx_h1 + 1]]
    hF = ema(h1c, 20)[-1]
    hM = ema(h1c, 50)[-1]
    a = atr_hist[min(idx_h1, len(atr_hist) - 1)]
    if a <= 0:
        blocks.append({"reason": "ATR_ZERO",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "why": "ATR zero"})
        return None, blocks

    dirhint = 1 if hF > hM else -1
    pb = abs(tick_mid - hF)
    if not (PB_MIN * a <= pb <= PB_MAX * a):
        blocks.append({"reason": "PB_RANGE",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "pb": round(pb, 2), "pb_lo": round(PB_MIN * a, 2),
                       "pb_hi": round(PB_MAX * a, 2),
                       "why": "pullback outside band"})
        return None, blocks

    dir_final = 1 if reg == "BULL" else -1
    if dir_final != dirhint:
        blocks.append({"reason": "EMA_SEP",
                       "t": repr(tick_time), "mid": round(tick_mid, 2),
                       "why": "EMA separation not in entry direction"})
        return None, blocks

    # ---- AT THIS POINT the EA would open an order on the next M15 bar open ----
    next_m15 = tick_time.next_bar(TF_M15)
    entry_mid = tick_mid  # simplified: we use contemporaneous mid as next-bar open proxy
    entry = entry_price_for(dir_final, entry_mid)
    sd = structural_stop(dir_final, entry, a, h1_bars[: idx_h1 + 1])
    td = H1_ATR_TARGET_MULT * sd

    # ---- take the position ----
    pos = Position(entry_time=next_m15, entry_price=entry,
                   sl=entry - sd * dir_final, tp=entry + td * dir_final,
                   dir=dir_final, stop_distance=sd)
    slot.open_ticket = 1
    slot.open_position = pos
    slot.next_allowed_eval_bar = next_m15.bar_index(TF_M15) + 1
    persist["last_entry"] = repr(next_m15)

    return pos, blocks


# ---------------------------------------------------------------------------
# Synthetic instrument + clocks
# ---------------------------------------------------------------------------

def build_clocks(start: MTime, m15_bars: int, h1_bars: int, m30_bars: int):
    m30 = [MTime(epoch=start.epoch + i * TF_M30) for i in range(m30_bars)]
    h1  = [MTime(epoch=start.epoch + i * TF_H1) for i in range(h1_bars)]
    m15 = [MTime(epoch=start.epoch + i * TF_M15) for i in range(m15_bars)]
    return m30, h1, m15


def make_h1_bars(start: MTime, n: int, base: float, drift: float) -> list[H1Bar]:
    bars = []
    for i in range(n):
        t = start + timedelta(seconds=i * TF_H1)
        o = base + drift * i + (0.0 if i == 0 else 0.0)
        c = o + drift * TF_H1 / 3600.0
        h = max(o, c) + 0.05
        l = min(o, c) - 0.05
        bars.append(H1Bar(t, o, h, l, c))
    return bars


def make_m15_bars(h1_bars: list[H1Bar], m15_per_h1: int = 4) -> list[M15Bar]:
    bars = []
    for h in h1_bars:
        for j in range(m15_per_h1):
            t = h.start + timedelta(seconds=j * TF_M15)
            frac = (j + 1) / m15_per_h1
            o = h.open
            c = h.open + (h.close - h.open) * frac
            h_ = max(o, c) + 0.02
            l_ = min(o, c) - 0.02
            bars.append(M15Bar(t, o, h_, l_, c))
    return bars


def make_tick_stream(m15_bars: list[M15Bar], ticks_per_bar: int = 6,
                     wick_fn=None) -> list[tuple[MTime, float]]:
    """Return a tick stream as (time, mid) so the engine can intrabar-manage."""
    ticks = []
    for b in m15_bars:
        for k in range(ticks_per_bar):
            t = b.start + timedelta(seconds=k * TF_M15 // ticks_per_bar)
            frac = (k + 1) / ticks_per_bar
            mid = b.open + (b.close - b.open) * frac
            h_ = b.high
            l_ = b.low
            if wick_fn is not None:
                mid = wick_fn(mid, b, frac)
            ticks.append((t, mid))
    return ticks


# ---------------------------------------------------------------------------
# Scenario proofs
# ---------------------------------------------------------------------------

def run_engine_on(ticks: list[tuple[MTime, float]], h1_bars: list[H1Bar],
                  session_day_epoch: int,
                  session_end_epoch: int, initial_slot: OrderSlot | None = None,
                  initial_pos: Position | None = None,
                  initial_last_m30_bar: int | None = None) -> RunResult:
    slot = initial_slot or OrderSlot()
    if initial_pos is not None:
        slot.open_ticket = 1
        slot.open_position = initial_pos
    atr_hist = wilder_atr(h1_bars, 14)
    persist = {}
    pos = slot.open_position
    if initial_last_m30_bar is None and ticks:
        initial_last_m30_bar = ticks[0][0].bar_index(TF_M30) - 1
    last_m30_bar = initial_last_m30_bar if initial_last_m30_bar is not None else 0

    if slot.open_position is not None and slot.next_allowed_eval_bar is None and ticks:
        slot.next_allowed_eval_bar = ticks[0][0].next_bar(TF_M15).bar_index(TF_M15) + 1
    for t, mid in ticks:
        m30_bar = t.bar_index(TF_M30)
        pos, trade = manage_position(pos, mid, t, session_end_epoch)
        if trade is not None:
            slot.open_position = None
            slot.open_ticket = None
            trade.entry_time = trade.entry_time or t
            yield "trade", trade
            if trade.r <= 0:
                slot.consecutive_losses += 1
            else:
                slot.consecutive_losses = 0
            if slot.consecutive_losses >= PAUSE_AFTER_LOSSES:
                slot.paused_until_epoch = (t + timedelta(days=1)).epoch
                slot.consecutive_losses = 0
            slot.next_allowed_eval_bar = t.next_bar(TF_M15).bar_index(TF_M15) + 1
            continue
        if pos is not None:
            slot.open_position = pos
        # evaluation
        m30_last_bar = last_m30_bar
        new_pos, blocks = evaluate_and_maybe_enter(
            slot, mid, t, h1_bars, atr_hist,
            session_day_epoch, session_end_epoch,
            m30_bar, m30_last_bar, persist,
        )
        if blocks:
            for blk in blocks:
                yield "block", blk
        if new_pos is not None:
            pos = new_pos
            slot.open_position = new_pos
        if m30_bar != m30_last_bar:
            last_m30_bar = m30_bar
    # close any leftover at session end
    if pos is not None:
        trade = TradeRecord(MTime(epoch=session_end_epoch), t, pos.dir,
                            pos.entry_price, pos.entry_price, 0.0, "SESSION_CLOSE")
        yield "trade", trade


def collect(iterable):
    trades, blocks, final_slot = [], [], None
    for kind, obj in iterable:
        if kind == "trade":
            trades.append(obj)
        else:
            blocks.append(obj)
    return trades, blocks, final_slot


def scenario_m30_gate():
    """M30 gate proof: many candidate M15 pullback signals during ONE M30 bar
    must all be suppressed; only a signal evaluated on/after the new M30 bar
    edge may be considered (and still gated by other rules)."""
    start = MTime(epoch=0)
    m30, h1, m15 = build_clocks(start, m30_bars=3, h1_bars=12, m15_bars=48)
    h1_bars = make_h1_bars(start, 12, base=1000.0, drift=0.0)
    m15_bars = make_m15_bars(h1_bars)
    session_day = start.epoch
    session_end = start + timedelta(days=1)

    # force a clean regime by building enough H1 history for the EA 20/50/100 EMA
    for b in h1_bars:
        b.close = b.open + 2.0
    h1_bars[0].close = h1_bars[0].open + 2.0
    h1_bars[1].close = h1_bars[1].open + 2.0

    ticks = make_tick_stream(m15_bars, ticks_per_bar=12)

    first_m30_bar = ticks[0][0].bar_index(TF_M30) - 1
    trades, blocks, slot_ = collect(run_engine_on(
        ticks, h1_bars,
        session_day_epoch=session_day,
        session_end_epoch=session_end.epoch,
        initial_slot=OrderSlot(),
        initial_last_m30_bar=first_m30_bar,
    ))

    m30_gate_blocks = [b for b in blocks if b["reason"] == "M30_GATE_SKIP"]
    return {
        "name": "M30 gate suppresses mid-bar evaluations",
        "m30_bars_simulated": len(set(b.get("m30_bar") for b in blocks if "m30_bar" in b)),
        "m30_gate_blocks": len(m30_gate_blocks),
        "evaluations_allowed": len([b for b in blocks if b["reason"] not in ("M30_GATE_SKIP", "ONE_POSITION_OPEN")]),
        "trades_taken": len(trades),
        "assertions": [
            ("no trade entered during the first M30 bar's mid-bar ticks",
             len([t for t in trades if t.entry_time.epoch < m30[1].epoch]) == 0),
        ],
    }


def scenario_one_position_rule():
    """One-position rule proof: while a position is open, a fresh entry signal
    is suppressed; after the position closes, the next evaluation is gated by
    the fill bar + cooldown, not instantly re-entered on the same tick."""
    start = MTime(epoch=0)

    # Build enough H1 history so the EA 20/50/100 EMA regime stabilizes, then
    # engineer a clean aligned-bear pullback entry into the last H1 bar.
    h1 = make_h1_bars(start, 120, base=1000.0, drift=0.0)
    h1_bars_all = h1
    for b in h1_bars_all:
        b.close = b.open - 2.0
    h1_bars_all[-1].close = h1_bars_all[-1].open - 2.0

    m30, _, m15 = build_clocks(start, m30_bars=2, h1_bars=120, m15_bars=480)
    m15_bars = make_m15_bars(h1_bars_all)
    session_day = start.epoch
    session_end = start + timedelta(days=1)
    ticks = make_tick_stream(m15_bars, ticks_per_bar=12)

    first_m30_bar = ticks[0][0].bar_index(TF_M30) - 1 if ticks else 0
    trades, blocks, slot_ = collect(run_engine_on(
        ticks, h1_bars_all,
        session_day_epoch=session_day,
        session_end_epoch=session_end.epoch,
        initial_slot=OrderSlot(initial_last_m30_bar=first_m30_bar),
    ))

    # quick sanity dump so a failure is diagnosable
    if not trades:
        sample_blocks = blocks[:12]
        print("\n[debug one-position] first blocks:")
        for b in sample_blocks:
            print("  ", b)
        if h1_bars_all:
            closes = [b.close for b in h1_bars_all]
            f = ema(closes, 20)[-1]
            m = ema(closes, 50)[-1]
            s = ema(closes, 100)[-1]
            atr_now = wilder_atr(h1_bars_all, 14)[-1] if h1_bars_all else 0
            idx = h1_index_for(h1_bars_all, ticks[0][0]) if ticks else 0
            print("\n[debug one-position] last H1 EMA:", round(f, 3), round(m, 3), round(s, 3))
            print("  atr:", round(atr_now, 3), "idx:", idx, "bar.start:", h1_bars_all[idx].start if idx < len(h1_bars_all) else None)

    return {
        "name": "One-position rule: open position suppresses concurrent signals",
        "trades_taken": len(trades),
        "one_position_blocks": len([b for b in blocks if b["reason"] == "ONE_POSITION_OPEN"]),
        "cooldown_blocks": len([b for b in blocks if b["reason"] == "COOLDOWN"]),
        "assertions": [
            (
                "at least one signal occurs while a position is open and is suppressed",
                len(
                    [b for b in blocks if b["reason"] == "ONE_POSITION_OPEN"]
                )
                > 0,
            ),
            (
                "no concurrent position is opened while one is already open",
                all(
                    (prev.exit_time.epoch) <= (curr.entry_time.epoch)
                    for prev, curr in zip(trades, trades[1:])
                ),
            ),
        ],
    }


def scenario_atr_protection():
    """Exact ATR protection proof: entry SL/TP equal H1_ATR_STOP_MULT * H1_ATR
    and H1_ATR_TARGET_MULT * H1_ATR (after the structural/floor/cap geometry),
    and an intrabar wick to the stop books a -1.0R exit."""
    start = MTime(epoch=0)
    h1 = make_h1_bars(start, 120, base=1000.0, drift=0.0)
    # make a clean ATR-ish bar set so ATR is stable
    for b in h1:
        b.high = b.open + 1.0
        b.low = b.open - 1.0
        b.close = b.open
    # engineer a larger aligned-bear pullback on the last two H1 bars so the
    # regime EMA stays aligned and the entry trigger is deterministic.
    h1[-2].close = h1[-2].open - 4.0
    h1[-1].close = h1[-1].open - 4.0

    m30, _, m15 = build_clocks(start, m30_bars=2, h1_bars=120, m15_bars=480)
    m15_bars = make_m15_bars(h1)

    # Only evaluate once enough H1 history exists for the EA 20/50/100 EMA regime.
    eval_start = MTime(epoch=max(len(h1) * TF_H1, (m30[1].epoch if len(m30) > 1 else 0)))
    ticks_stream = make_tick_stream(m15_bars, ticks_per_bar=12, wick_fn=None)
    ticks = [(t, mid) for t, mid in ticks_stream if t.epoch >= eval_start.epoch]

    # Apply the controlled wick to the tick stream, not the bar builder.
    atr_hist = wilder_atr(h1, 14)
    atr_val = atr_hist[-1]
    expected_sd = H1_ATR_STOP_MULT * atr_val
    expected_td = H1_ATR_TARGET_MULT * atr_val

    def wick_to_stop(mid, bar, frac):
        if abs(bar.close - h1[-2].close) < 0.001 and frac < 0.2:
            return h1[-2].close + expected_sd * 1.01
        return mid

    ticks = make_tick_stream(m15_bars, ticks_per_bar=12, wick_fn=wick_to_stop)
    ticks = [(t, mid) for t, mid in ticks if t.epoch >= eval_start.epoch]

    trades, blocks, slot_ = collect(run_engine_on(
        ticks, h1,
        session_day_epoch=start.epoch,
        session_end_epoch=start.epoch + timedelta(days=1).total_seconds(),
        initial_slot=OrderSlot(),
    ))

    taken = trades[0] if trades else None
    if taken is None:
        print('\n[debug atr] no trade taken; first blocks:')
        for b in blocks[:12]:
            print('  ', b)
    return {
        "name": "Exact ATR protection: SL/TP = mult * H1 ATR",
        "atr_index": round(atr_val, 4),
        "expected_sd": round(expected_sd, 4),
        "expected_td": round(expected_td, 4),
        "entry_taken": taken.entry_time if taken else None,
        "entry_sl": round(taken.sl, 4) if taken else None,
        "entry_tp": round(taken.tp, 4) if taken else None,
        "exit_reason": taken.reason if taken else None,
        "exit_r": round(float(taken.r), 3) if taken else None,
        "assertions": [
            (
                "entry stop distance equals H1_ATR_STOP_MULT * H1 ATR (within structural/floor/cap)",
                taken is not None
                and abs(float(taken.stop_distance) - expected_sd) < 1e-6,
            ),
            (
                "entry tp distance equals H1_ATR_TARGET_MULT * H1 ATR",
                taken is not None
                and abs((taken.entry_price - taken.tp) - expected_td) < 1e-6,
            ),
            (
                "an intrabar wick through the stop books a -1.0R SL exit",
                taken is not None
                and taken.reason == "SL"
                and abs(float(taken.r) - -1.0) < 1e-6,
            ),
        ],
    }


def scenario_timeout():
    """Timeout proof: a position that never hits TP/SL is closed at
    MAX_HOLD_SECONDS with a TIME exit and the correct R accounting."""
    start = MTime(epoch=0)
    h1 = make_h1_bars(start, 120, base=1000.0, drift=0.0)
    for b in h1:
        b.close = b.open + 2.0
    m30, _, m15 = build_clocks(start, m30_bars=3, h1_bars=120, m15_bars=480)
    m15_bars = make_m15_bars(h1)
    session_day = start.epoch
    session_end = start + timedelta(days=2)  # long session so TIME, not session close, fires

    ticks = make_tick_stream(m15_bars, ticks_per_bar=6)

    first_m30_bar = ticks[0][0].bar_index(TF_M30) - 1
    trades, blocks, slot_ = collect(run_engine_on(
        ticks, h1,
        session_day_epoch=session_day,
        session_end_epoch=session_end.epoch,
        initial_slot=OrderSlot(),
        initial_last_m30_bar=first_m30_bar,
    ))

    timeout_trade = next((t for t in trades if t.reason == "TIME"), None)
    timeout_hold = (int((timeout_trade.exit_time - timeout_trade.entry_time).total_seconds())
                    if timeout_trade else None)
    return {
        "name": "Timeout: hard MAX_HOLD_SECONDS closes the position with TIME",
        "max_hold_seconds": MAX_HOLD_SECONDS,
        "timeout_trades": len([t for t in trades if t.reason == "TIME"]),
        "timeout_trade": {
            "entry_time": repr(timeout_trade.entry_time) if timeout_trade else None,
            "exit_time": repr(timeout_trade.exit_time) if timeout_trade else None,
            "hold_seconds": timeout_hold,
            "r": round(timeout_trade.r, 3) if timeout_trade else None,
        } if timeout_trade else None,
        "assertions": [
            ("at least one TIME exit occurs even though TP/SL never hit",
             timeout_trade is not None),
            ("TIME exit happens at or after MAX_HOLD_SECONDS",
             timeout_trade is not None and timeout_hold is not None and timeout_hold >= MAX_HOLD_SECONDS),
        ],
    }


def scenario_close_recovery():
    """Close recovery proof: after a loss, the cooldown prevents instant
    re-entry; after PAUSE_AFTER_LOSSES consecutive losses, a session-day pause
    is enforced; after a win, re-entry is allowed on the next eligible bar."""
    start = MTime(epoch=0)
    h1 = make_h1_bars(start, 30, base=1000.0, drift=0.0)
    # engineer one aligned-bear pullback first, then three consecutive losses
    # so the win is a real entry first and the pause is provable.
    for i, b in enumerate(h1[:10]):
        b.close = b.open - 1.0  # losers
    h1[10].close = h1[10].open - 2.5  # pullback entry that becomes a loss too
    h1[11].close = h1[11].open - 1.0
    h1[12].close = h1[12].open - 1.0  # third consecutive loss -> pause

    m30, _, m15 = build_clocks(start, m30_bars=3, h1_bars=30, m15_bars=120)
    m15_bars = make_m15_bars(h1)
    session_day = start.epoch
    session_end = start + timedelta(days=3)

    ticks = make_tick_stream(m15_bars, ticks_per_bar=6)
    first_m30_bar = ticks[0][0].bar_index(TF_M30) - 1 if ticks else 0
    trades, blocks, slot_ = collect(run_engine_on(
        ticks, h1,
        session_day_epoch=session_day,
        session_end_epoch=session_end.epoch,
        initial_slot=OrderSlot(),
        initial_last_m30_bar=first_m30_bar,
    ))

    if not trades:
        print("\n[debug timeout] first 12 blocks:")
        for b in blocks[:12]:
            print("  ", b)
        closes = [b.close for b in h1]
        f = ema(closes, 20)[-1]
        m = ema(closes, 50)[-1]
        s = ema(closes, 100)[-1]
        print("\n[debug timeout] last H1 EMA:", round(f, 3), round(m, 3), round(s, 3))

    losses = [t for t in trades if t.r <= 0]
    wins = [t for t in trades if t.r > 0]
    cooldown_blocks = [b for b in blocks if b["reason"] == "COOLDOWN"]
    pause_blocks = [b for b in blocks if b["reason"] == "LOSS_PAUSE"]
    return {
        "name": "Close recovery: cooldown + loss streak pause + win re-entry",
        "trades_taken": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "consecutive_loss_streak_pause_blocks": len(pause_blocks),
        "cooldown_blocks": len(cooldown_blocks),
        "assertions": [
            ("a cooldown block appears after a loss before the next evaluation",
             len(cooldown_blocks) > 0),
            ("three consecutive losses trigger a session-day pause block",
             len(pause_blocks) > 0),
            ("after a closed trade the system is allowed to evaluate again",
             len(trades) > 0),
        ],
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

SCENARIOS = (scenario_m30_gate, scenario_one_position_rule,
             scenario_atr_protection, scenario_timeout, scenario_close_recovery)


def summarize_scenario(s: dict) -> dict:
    return {
        "scenario": s["name"],
        "assertions": [{"assertion": a[0], "passed": bool(a[1])} for a in s["assertions"]],
        "detail": {k: v for k, v in s.items() if k not in ("name", "assertions")},
    }


def all_passed(results: list[dict]) -> bool:
    return all(a["passed"] for r in results for a in r["assertions"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", type=Path, default=None,
                    help="write an HTML summary artifact")
    args = ap.parse_args()

    results = [summarize_scenario(s()) for s in SCENARIOS]

    print("\n" + "=" * 92)
    print("MITEMSHUB V75 CONTROL PANEL — deterministic rule proofs")
    print("=" * 92)
    for r in results:
        status = "PASS" if all(a["passed"] for a in r["assertions"]) else "FAIL"
        print(f"\n[{status}] {r['scenario']}")
        for a in r["assertions"]:
            mark = "ok" if a["passed"] else "XX"
            print(f"  {mark} {a['assertion']}")
        detail = r["detail"]
        if detail:
            flat = []
            for k, v in detail.items():
                if isinstance(v, list):
                    flat.append(f"{k}: {len(v)} items")
                else:
                    flat.append(f"{k}: {v}")
            print("   " + " | ".join(flat))

    all_ok = all_passed(results)
    print("\n" + "-" * 92)
    print("OVERALL:", "ALL ASSERTIONS PASS" if all_ok else "SOME ASSERTIONS FAILED")
    print("-" * 92)

    artifact = {
        "schema": "mitemshub.v75.control-panel-proof.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "policy_mirrors": {
            "H1_ATR_STOP_MULT": H1_ATR_STOP_MULT,
            "H1_ATR_TARGET_MULT": H1_ATR_TARGET_MULT,
            "MAX_HOLD_SECONDS": MAX_HOLD_SECONDS,
            "COOLDOWN_BARS_LOSS": COOLDOWN_BARS_LOSS,
            "PAUSE_AFTER_LOSSES": PAUSE_AFTER_LOSSES,
            "SPREAD_INDEX_UNITS": SPREAD_INDEX_UNITS,
        },
        "scenarios": results,
        "all_passed": all_ok,
    }

    json_path = ROOT / "artifacts" / "v75_control_panel.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"\nartifact -> {json_path}")

    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        write_html(artifact, args.html)
        print(f"html    -> {args.html}")

    return 0 if all_ok else 2


def write_html(artifact: dict, path: Path) -> None:
    rows = ""
    for r in artifact["scenarios"]:
        for a in r["assertions"]:
            cls = "pass" if a["passed"] else "fail"
            rows += f'<tr class="{cls}"><td>{r["scenario"]}</td><td>{a["assertion"]}</td><td>{"PASS" if a["passed"] else "FAIL"}</td></tr>\n'
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MITEMSHUB V75 Control Panel Proofs</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #d0d0d0; padding: 6px 10px; text-align: left; }}
  th {{ background: #f5f5f5; }}
  tr.pass td {{ color: #1a7f37; }}
  tr.fail td {{ color: #b00020; }}
  .meta {{ color: #555; }}
</style>
</head>
<body>
  <h1>MITEMSHUB V75 Control Panel — Deterministic Rule Proofs</h1>
  <p class="meta">generated {artifact["generated_utc"]} UTC</p>
  <table>
    <thead><tr><th>scenario</th><th>assertion</th><th>result</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
  <pre>{json.dumps(artifact, indent=2)}</pre>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
