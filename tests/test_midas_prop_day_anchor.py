"""Two time-frame guarantees that were measured wrong on 2026-09-20, and are pinned here.

1. THE UTC-DAY ANCHOR IN THE EA. The 3% daily cap and the 20% Best Day ceiling are both
   rules about ONE UTC day, and both took their baseline from "the equity at the moment
   this code was first reached today" — which is the day's first ENTRY ATTEMPT, not
   00:00 UTC. Measured consequences: a 3% loss taken before that first attempt was
   re-anchored away and the breaker never tripped for a day the venue had already
   counted as breached, and a restart forgot the day entirely. The anchor is now taken
   on every tick at the rollover, with the day's opening equity reconstructed from the
   EA's own closed deals when it starts mid-day. The venue's rule does not restart with
   the EA, so the EA's reading of it must not either.

2. THE TICK-COVERED CERTIFICATION WINDOW. Parity's evidence standard is per-tick fills,
   and this venue serves real gold ticks only from 2026-09-04 — every pass reaching
   further back is refused by `mt5_tester_driver.assert_declared_tick_model`. So
   certification is RESTRICTED to windows the venue can serve per-tick, and `tickcov`
   is that window. It is not re-declared as a bar-replay contract on purpose: a bar
   replay decides intrabar order (SL or TP first) by a rule the two engines do not
   share, and declaring that away would move a real disagreement into a constant
   instead of removing it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
sys.path.insert(0, str(REPO / "scripts"))

import midas_parity as P  # noqa: E402


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    return re.sub(r"//[^\n]*", "", s)


# --- 1. the UTC-day anchor -----------------------------------------------------------

def test_the_day_anchor_exists_and_is_taken_on_every_tick():
    s = strip_comments(src())
    assert "void PropDayAnchorCheck()" in s
    tick = re.search(r"void OnTick\(\)\s*\{(.*?)\n\}", s, re.S)
    assert tick, "OnTick not found"
    body = tick.group(1)
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    assert first.startswith("PropDayAnchorCheck()"), (
        "the day baselines must be established before any gate can read them; OnTick's "
        f"first statement is {first!r}. The EA has three tick paths (bar replay, live, "
        "paper) and the anchor has to be upstream of all of them.")


def test_the_two_day_rules_share_the_anchored_baseline():
    """ONE anchor sets both baselines; neither rule derives its own."""
    s = strip_comments(src())
    anchor = s.split("void PropDayAnchorCheck()")[1].split("bool DailyBreakerTripped()")[0]
    assert "g_brk_start_eq" in anchor and "g_prop_day_eq" in anchor, (
        "the anchor must set BOTH day baselines — the 3% cap and the Best Day ceiling")
    breaker = s.split("bool DailyBreakerTripped()")[1][:1200]
    assert "g_brk_start_eq" in breaker and "TimeToStruct" not in breaker, (
        "the breaker must read the anchored baseline rather than re-deriving its day")
    best_day = s.split("double PropDayProfitCapUsd()")[1][:1600]
    assert "g_prop_day_eq" in best_day, "the Best Day ceiling lost its anchored baseline"


def test_the_lazy_day_anchors_are_gone():
    """The defect itself: a baseline captured at the day's first entry attempt."""
    s = strip_comments(src())
    assert not re.search(r"static\s+double\s+s_day_eq", s), (
        "the Best Day baseline is captured lazily again (static s_day_eq)")
    assert not re.search(r"if\(day\s*!=\s*g_brk_day\)\s*\{", s), (
        "the breaker re-anchors on the day it happens to be called again")


def test_the_anchor_uses_a_utc_day_key_not_the_server_clock():
    s = strip_comments(src())
    body = s.split("void PropDayAnchorCheck()")[1].split("bool DailyBreakerTripped()")[0]
    assert "TimeUTCNow()" in body, "the day key must be a TRUE UTC day (venue rules are UTC)"
    assert "TimeCurrent()" not in body, "a server-clock day key would move with the venue's DST"


def test_a_mid_day_start_reconstructs_the_opening_equity_from_deals():
    s = strip_comments(src())
    assert "double PropDayRealisedPnlUtc()" in s
    body = s.split("double PropDayRealisedPnlUtc()")[1].split("void PropDayAnchorCheck()")[0]
    assert "HistorySelect(" in body and "DEAL_ENTRY" in body and "DEAL_PROFIT" in body
    anchor = s.split("void PropDayAnchorCheck()")[1].split("bool DailyBreakerTripped()")[0]
    assert "PropDayRealisedPnlUtc()" in anchor, (
        "a restart mid-day would anchor to current equity and forget the day")
    assert "86400" in body, "the realised-P&L window must start at 00:00 UTC"


# --- 2. the tick-covered certification window -----------------------------------------

def test_the_tick_covered_window_is_declared_and_pinned():
    assert "tickcov" in P.WINDOW_SPECS, "the tick-covered window is not declared"
    spec = P.WINDOW_SPECS["tickcov"]
    import midas_sweep as M
    assert "tickcov" in M.WINDOWS, "the python engine has no window epoch range for it"
    t0 = M.iso_to_ts(M.WINDOWS["tickcov"][0])
    t1 = M.iso_to_ts(M.WINDOWS["tickcov"][1])
    assert t0 < t1 and (t1 - t0) < 90 * 86400, "tickcov is meant to be short"
    assert spec["server_offset_min"] == 120, (
        "September sits on the +120 side of the venue's DST step; a wrong pin would "
        "mis-align every key")


def test_the_window_starts_at_or_after_the_venue_tick_coverage():
    """TICK_COVERAGE_START is the measured fact this whole decision rests on."""
    from mt5_tester_driver import TICK_COVERAGE_START
    import midas_sweep as M
    first = M.iso_to_ts(M.WINDOWS["tickcov"][0])
    start = TICK_COVERAGE_START
    stamp = int(start[:4]) * 10000 + int(start[5:7]) * 100 + int(start[8:10])
    assert stamp == 20260904, (
        "the venue's real gold ticks were measured to begin 2026-09-04; if that date "
        "moves, re-derive this window (and the whole certification question) rather "
        "than trusting a stale constant")
    import datetime as dt
    assert dt.datetime.fromtimestamp(first, dt.timezone.utc).strftime("%Y.%m.%d") <= start, (
        "the tick-covered window starts BEFORE the ticks this venue serves")
