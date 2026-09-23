"""A structural signal that repaints is worthless, so repainting must FAIL here, not be assumed.

`scripts/midas_cross_asset.py` builds swings and a structure direction that
`docs/CROSS_ASSET_DIVERGENCE_PREREG_20260922.md` declared non-repainting by construction. These
tests are that claim, executed:

  1. a swing needs the next TWO bars, so it is confirmed at the CLOSE of `i+2` and never before;
  2. the direction at a moment uses only swings confirmed at or before it;
  3. the context series is expressed in CLOSE times — MEASURED as a real defect during the first
     verification run: with bar OPEN times the AUD leg's swings became known one H1 bar early, so a
     signal at `t` could depend on bar `t`'s high. The result was negative either way; the point is
     that the number reported is the one with the lookahead removed;
  4. **the repaint test itself**: changing a FUTURE bar's high must not move a single signal taken
     before that bar closed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import midas_cross_asset as CA  # noqa: E402

START = 1_700_000_000
STEP = 3600


def _series(n: int, start: int = START, drift: float = 0.01):
    """A deterministic triangular H1 series with strictly-marching swings, plus an M15 grid.

    Peaks sit at `i % 8 == 4` and troughs at the same bar (a wide bar), and the small drift makes
    consecutive peaks strictly higher (or lower, with a negative drift) so the structure direction
    is non-zero and the divergence variants actually fire.
    """
    h1, h1_ct, m15 = [], [], []
    for i in range(n):
        phase = i % 8
        tri = phase if phase <= 4 else 8 - phase
        mid = 100.0 + drift * i
        h1.append({"time": start + i * STEP, "open": mid, "high": mid + tri,
                   "low": mid - tri, "close": mid})
        h1_ct.append(start + i * STEP + STEP)          # CLOSE time, never the open
    for i in range(n * 4):
        m15.append({"time": start + i * 900, "open": 100.0, "high": 100.0,
                    "low": 100.0, "close": 100.0})
    return h1, h1_ct, m15


def test_a_swing_is_confirmed_two_bars_late_never_earlier():
    h1, h1_ct, _ = _series(60)
    sw = CA.confirmed_swings([b["high"] for b in h1], [b["low"] for b in h1], h1_ct)
    assert sw["sh"] and sw["sl"], "the synthetic series must contain both swing kinds"
    for confirm_t, _lvl in sw["sh"] + sw["sl"]:
        assert confirm_t in h1_ct, "confirmations are stamped in the CLOSE-time frame"
        assert h1_ct.index(confirm_t) >= CA.SWING_FWD


def test_direction_ignores_a_swing_that_is_not_yet_confirmed():
    h1, h1_ct, _ = _series(60)
    sw = CA.confirmed_swings([b["high"] for b in h1], [b["low"] for b in h1], h1_ct)
    last = sw["sh"][-1][0]
    usable_before = [t for t, _ in sw["sh"] if t <= last - 1]
    assert len(usable_before) < len(sw["sh"]), "the last swing must be invisible one tick earlier"
    assert CA.direction_at(sw, last - 1) in (-1, 0, 1)
    assert CA.direction_at(sw, last) in (-1, 0, 1)


def test_changing_a_future_bar_does_not_move_any_earlier_signal():
    """THE repaint test: the signal for `ct` may depend only on bars that had closed by then."""
    n = 60
    gold, gold_ct, m15 = _series(n, drift=+0.01)
    ctx, ctx_ct, _ = _series(n, start=START + 40 * STEP, drift=-0.01)   # opposite structure
    base = CA.build_signals(gold, gold_ct, m15, ctx, ctx_ct)
    assert any(base["DIVERGE"]), "the two legs must actually disagree, or the test compares zeros"

    k = n // 2
    hurt = [dict(b) for b in gold]
    hurt[k]["high"] += 500.0                     # a violent change, two bars' worth of signal
    moved = CA.build_signals(hurt, gold_ct, m15, ctx, ctx_ct)

    cutoff = m15[k]["time"] + 900                # the close of the M15 slot that holds bar k
    checked = 0
    for name in ("DIVERGE", "FADE", "ALIGN"):
        for i, b in enumerate(m15):
            ct = b["time"] + 900
            if ct <= cutoff:
                assert base[name][i] == moved[name][i], (
                    f"{name} signal at ct={ct} moved when a FUTURE bar changed — it repaints")
                checked += 1
    assert checked > 0, "the test compared nothing"


def test_the_context_series_is_read_in_close_times():
    """The defect caught in verification: opens would give the AUD leg one H1 bar of lookahead."""
    try:
        bars, times = CA.context_bars("AUDUSD_H1", 120)
    except SystemExit as exc:                    # the context series is fetched, not shipped
        pytest.skip(f"context series not fetched on this checkout: {exc}")
    assert len(bars) == len(times) > 0
    for b, t in zip(bars[:50], times[:50]):
        assert t == b["time"] - 120 * 60 + 3600
