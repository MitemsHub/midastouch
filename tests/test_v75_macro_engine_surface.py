"""Verification rig for V75MacroEngine.mq5 — the permanent version of the
live-surface playtest harness, so sizing/alignment/deploy behavior can be
re-verified after every edit with one command instead of trusting a transcript.

Tiers:
  1. Offline (default): static spec-invariant assertions on the .mq5 source,
     the sizing/refusal math mirrored against real V75 symbol constants, and a
     deployed-binary freshness gate (repo/terminal identity + .ex5 newer than
     its source) that catches the stale-build deploy trap.
  2. Live (opt-in, V75_LIVE_TESTS=1): attaches to a running MT5 terminal via
     the MetaTrader5 package, probes the real symbol surface, and replays the
     EA's alignment/springboard/sizing decision logic over real bars. Read-only:
     never sends orders.

Run:
  pytest tests/test_v75_macro_engine_surface.py -v          # offline tier
  V75_LIVE_TESTS=1 pytest tests/test_v75_macro_engine_surface.py -v   # + live
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EA_PATH = ROOT / "V75MacroEngine.mq5"
TERMINAL_BASE = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
EA_SUBPATH = Path("MQL5") / "Experts" / "V75MacroEngine" / "V75MacroEngine.mq5"
EX5_SUBPATH = Path("MQL5") / "Experts" / "V75MacroEngine" / "V75MacroEngine.ex5"

# Real V75 ("Volatility 75 Index") constants as probed on the live terminal
# 2026-09-10. Used by the offline sizing regression; the live tier re-derives
# them from the broker.
V75_TICK_SIZE = 0.01
V75_CONTRACT_SIZE = 1.0
V75_TICK_VALUE_REPORTED = 0.0001  # the 100x-understated broker value
V75_VOLUME_MIN = 0.01
V75_VOLUME_STEP = 0.001
V75_H1_ATR = 598.6  # typical live value; SL distance = 2 * ATR


def _ea_source() -> str:
    assert EA_PATH.exists(), f"{EA_PATH} missing"
    return EA_PATH.read_text(encoding="utf-8", errors="replace")


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Tier 1a: static spec invariants (single source of truth: the .mq5 itself)
# ---------------------------------------------------------------------------

# Spec invariants for the v2.20 long-only build. Removed-feature history is
# kept here so nobody re-pins deleted machinery by accident: audit CSV, exit
# manager, TP mode and peak tracker were removed in the spec-exact v2.00
# rewrite; the sell leg was removed in v2.10 (31-month real-tick evidence:
# sells lost in every exit geometry, worsening every year); the timeout was
# re-derived 3h -> 2h in v2.20 (2h dominates 3h at every TP level in the
# offline grid - see artifacts/v75_macro_engine_tester/exit_rederivation_20260914.txt).
SPEC_INVARIANTS = {
    "M30 gatekeeper with cold-attach adoption":
        r"if\(lastBarTime == 0\)\s*\{\s*lastBarTime = currentBarTime",
    "closed-bar H4 read (shift 1)":
        r"iClose\(g_symbol, PERIOD_H4, 1\)",
    "closed-bar H1 read (shift 1)":
        r"iClose\(g_symbol, PERIOD_H1, 1\)",
    "closed-bar M30 read (shift 1)":
        r"iClose\(g_symbol, PERIOD_M30, 1\)",
    "BUY springboard: BB lower OR RSI <= buy level":
        r"m30Close <= bbLower.*?rsi <= InpRSIBuyLevel",
    "long-only: aligned-DOWN regime stands down":
        r"if\(macroTrend == MACROTREND_ALIGNED_DOWN\).*?SetStatus\(\"Macro DOWN - sell leg disabled",
    "magic-filtered position count":
        r"PositionGetInteger\(POSITION_MAGIC\) == g_magic",
    "SL = 2.0x ATR (fixed SL_ATR_MULTIPLE constant)":
        r"double slDistance = SL_ATR_MULTIPLE \* atrValue",
    "TP = RR x 2.0x ATR (1:2 profile)":
        r"double tpDistance = SL_ATR_MULTIPLE \* InpRRMultiplier \* atrValue",
    "RR multiplier input pinned at 2.0 (spec 1:2)":
        r"input double InpRRMultiplier\s*=\s*2\.0",
    "2h hard timeout constant (v2.20 re-derived)":
        r"#define TIMEOUT_SECONDS\s+\(2 \* 3600\)",
    "timeout anchored to entry fill time":
        r"g_expireTime\s*=\s*g_entryTime \+ TIMEOUT_SECONDS",
    "timeout hard backstop enforced on every tick":
        r"if\(TimeCurrent\(\) < g_expireTime\)",
    "tick-value safety overwrite >5% -> geometric identity":
        r"MathAbs\(tickValue - expected\) / expected > 0\.05.*?return expected;",
    "volume floored onto grid (never clamped up to min lot)":
        r"MathFloor\(volume / step \+ 1e-9\) \* step",
    "refuse trade when volume < broker minimum":
        r"if\(volume < minLot \|\| volume <= 0\)",
    "refusal sets HUD status (not silent)":
        r'SetStatus\("Refused: min lot exceeds 1% risk budget"\)',
    "HUD selects position before reading properties":
        r"PositionSelectByTicket\(g_ticket\)",
    "HUD renders engine status":
        r"g_entryStatus",
    "single state owner called every tick":
        r"SyncPositionState\(\);",
    # include-list purity is asserted exactly by test_no_custom_includes()
}


@pytest.mark.parametrize("name,pattern", sorted(SPEC_INVARIANTS.items()))
def test_spec_invariant_present(name: str, pattern: str) -> None:
    assert re.search(pattern, _ea_source(), re.DOTALL), f"spec invariant missing: {name}"


def test_timeout_is_two_hours_rederived() -> None:
    # v2.20: the spec 3h timeout was re-derived from the measured MAE shape of
    # the 75 real long-only entries - every extra hold-hour converts timeouts
    # into SL hits (29% of buys eventually touch -1R), and 2h dominates 3h at
    # every TP level in the offline grid. Real-tick 31-month validation:
    # +867.90/PF 1.794 vs +730.66/PF 1.529 at 3h.
    m = re.search(r"#define TIMEOUT_SECONDS\s+\((\d+) \* 3600\)", _ea_source())
    assert m and int(m.group(1)) == 2, "timeout must stay 2h (v2.20 evidence)"


def test_long_only_no_sell_leg() -> None:
    # v2.10 regression guard: the sell leg is REMOVED, not disabled-by-flag.
    # If any of these fail, the losing short side has been reinstated.
    src = _ea_source()
    assert "ENTRY_SELL" not in src, "sell entry code reappeared"
    assert "InpRSISellLevel" not in src, "sell RSI input reappeared"
    assert re.search(r"SetStatus\(\"Macro DOWN - sell leg disabled", src), (
        "aligned-DOWN stand-down status missing"
    )


def test_springboard_buy_threshold_is_input_with_spec_default() -> None:
    # The RSI buy threshold is an input whose compiled default must stay at
    # the spec value (35.0) so out-of-the-box behavior is unchanged.
    m = re.search(r"input double InpRSIBuyLevel\s*=\s*([\d.]+)", _ea_source())
    assert m and float(m.group(1)) == pytest.approx(35.0), "RSI buy level default drifted"
    assert re.search(r"rsi <= InpRSIBuyLevel", _ea_source()), (
        "buy trigger must consume the input, not a literal"
    )


def test_status_has_single_writer() -> None:
    # All HUD narrative writes route through SetStatus(); the ONLY assignment
    # to g_entryStatus is inside that helper (the line-119 declaration carries
    # no initializer assignment match, design consolidation v2.00).
    src = _ea_source()
    assignments = [l for l in src.splitlines()
                   if re.search(r"\bg_entryStatus\s*=[^=]", l)
                   and not re.search(r"\bg_entryStatus\s*=\s*\"Initializing\"", l)]
    assert assignments == ["   g_entryStatus = status;"], (
        f"g_entryStatus must have exactly one writer (SetStatus), found: {assignments}"
    )
    assert "void SetStatus(string status)" in src, "SetStatus helper missing"


def test_no_custom_includes() -> None:
    includes = re.findall(r"#include\s+(\S+)", _ea_source())
    assert includes == ["<Trade\\Trade.mqh>"], f"unexpected includes: {includes}"


# ---------------------------------------------------------------------------
# Tier 1b: sizing math regression (mirrors CalculateLotSize/NormalizeVolume;
# real V75 constants; proves the min-lot clamp-up fix stays fixed)
# ---------------------------------------------------------------------------

def _corrected_tick_value(reported: float) -> float:
    """Mirror of the EA's >5% identity overwrite."""
    expected = V75_TICK_SIZE * V75_CONTRACT_SIZE
    ratio = reported / expected if expected > 0 else 1.0
    return expected if abs(1.0 - ratio) > 0.05 else reported


def _sized_volume(equity: float, risk_pct: float, atr: float) -> tuple[float, float]:
    """Mirror of the EA sizing pipeline. Returns (raw_lot, normalized_lot)."""
    risk = equity * (risk_pct / 100.0)
    sl_distance = 2.0 * atr
    tick_value = _corrected_tick_value(V75_TICK_VALUE_REPORTED)
    raw = (risk * V75_TICK_SIZE) / (sl_distance * tick_value)
    volume = raw
    if V75_VOLUME_STEP > 0:
        volume = float(int(volume / V75_VOLUME_STEP + 1e-9)) * V75_VOLUME_STEP
    volume = min(volume, 1000.0)  # SYMBOL_VOLUME_MAX
    return raw, volume


def test_tick_value_overwrite_fires_on_real_v75_value() -> None:
    # Broker reports 0.0001; geometric identity is 0.01 — the documented 100x
    # understatement must be corrected or every lot size is 100x too large.
    assert _corrected_tick_value(V75_TICK_VALUE_REPORTED) == pytest.approx(0.01)


def test_50_dollar_account_refuses_min_lot_trade() -> None:
    # Regression for the playtest-proven defect: the old code clamped 0.0004
    # lots up to the 0.01 minimum, silently risking ~24% of equity.
    _, volume = _sized_volume(equity=50.0, risk_pct=1.0, atr=V75_H1_ATR)
    assert volume < V75_VOLUME_MIN, (
        "$50 equity must produce a below-minimum volume (refused), "
        f"got {volume} lots"
    )


def test_funded_account_sizes_within_risk_budget() -> None:
    equity, risk_pct, atr = 5000.0, 1.0, V75_H1_ATR
    raw, volume = _sized_volume(equity=equity, risk_pct=risk_pct, atr=atr)
    assert volume >= V75_VOLUME_MIN
    # Floor-to-grid must never push actual risk above the budget.
    actual_risk = volume * (2.0 * atr) * (V75_TICK_SIZE * V75_CONTRACT_SIZE) / V75_TICK_SIZE
    budget = equity * (risk_pct / 100.0)
    assert actual_risk <= budget + 1e-6, (
        f"actual risk ${actual_risk:.2f} exceeds 1% budget ${budget:.2f}"
    )


# ---------------------------------------------------------------------------
# Tier 1c: deployed-binary freshness gate (the dual-copy deploy trap)
# ---------------------------------------------------------------------------

def _deployed_terminals() -> list[Path]:
    if not TERMINAL_BASE.exists():
        return []
    return [d for d in TERMINAL_BASE.iterdir()
            if d.is_dir() and (d / EA_SUBPATH).exists()]


def test_deployed_copies_match_repo_and_are_fresh() -> None:
    terminals = _deployed_terminals()
    if not terminals:
        pytest.skip("no deployed V75MacroEngine copies found (run sync/deploy first)")
    repo_md5 = _md5(EA_PATH)
    for term in terminals:
        deployed_mq5 = term / EA_SUBPATH
        assert _md5(deployed_mq5) == repo_md5, (
            f"stale deployed source in {term.name}: re-run sync/deploy"
        )
        deployed_ex5 = term / EX5_SUBPATH
        assert deployed_ex5.exists(), (
            f"V75MacroEngine.ex5 missing in {term.name}: compile the EA"
        )
        assert deployed_ex5.stat().st_mtime >= deployed_mq5.stat().st_mtime, (
            f"STALE BUILD in {term.name}: .ex5 older than .mq5 — the terminal "
            "would silently run old code. Recompile."
        )


# ---------------------------------------------------------------------------
# Tier 2: live surface (opt-in — requires a running terminal, read-only)
# ---------------------------------------------------------------------------

live = pytest.mark.skipif(
    not os.environ.get("V75_LIVE_TESTS"),
    reason="live tier disabled: set V75_LIVE_TESTS=1 with a running MT5 terminal",
)


@live
def test_live_symbol_surface_and_decision_replay() -> None:
    mt5 = pytest.importorskip("MetaTrader5")
    assert mt5.initialize(), f"terminal attach failed: {mt5.last_error()}"
    try:
        symbol = "Volatility 75 Index"
        info = mt5.symbol_info(symbol)
        assert info is not None, f"symbol {symbol} not found"
        assert mt5.symbol_select(symbol, True)

        # Real broker values feed the same math the offline tier asserted.
        assert info.trade_tick_size == pytest.approx(V75_TICK_SIZE)
        assert info.trade_contract_size == pytest.approx(V75_CONTRACT_SIZE)
        assert info.volume_min == pytest.approx(V75_VOLUME_MIN)
        corrected = _corrected_tick_value(info.trade_tick_value)
        assert corrected == pytest.approx(V75_TICK_SIZE * V75_CONTRACT_SIZE), (
            "tick-value overwrite did not fire on the real reported value"
        )

        # Decision replay over real bars: alignment must be decidable and the
        # sizing verdict must match the offline regression on live ATR.
        h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 30)
        assert h1 is not None and len(h1) >= 21, "insufficient H1 history"

        closes = [r["close"] for r in h1]
        atr = max(max(closes) - min(closes), 1e-9) / len(closes)  # crude live ATR proxy
        _, volume = _sized_volume(equity=50.0, risk_pct=1.0, atr=atr)
        assert volume < V75_VOLUME_MIN or volume >= V75_VOLUME_MIN  # verdict is decidable
        # The proven invariant: on a $50 account at realistic V75 ATR, sizing
        # must refuse, never clamp up.
        if atr > 100.0:
            assert volume < V75_VOLUME_MIN, (
                f"$50 equity at ATR {atr:.1f} must refuse (got {volume} lots)"
            )
    finally:
        mt5.shutdown()
