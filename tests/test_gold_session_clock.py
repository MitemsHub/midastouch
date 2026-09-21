"""The venue's clock, and the gold week as this account actually trades it.

WHY THIS FILE EXISTS. Two wrong answers were being printed by `live_readiness.py`, the
tool whose whole job is the go/no-go before a session:

  * the venue stamps epochs on ITS clock, and the raw difference was reported as an age —
    so a **fresh** tick printed as "last tick was -120 min ago";
  * `next_gold_open()` returned the next Sunday unconditionally, so at Sunday 22:27 UTC —
    27 minutes into the trading week — it printed "next gold open in 167.5h".

Both were measured on 2026-09-20 against the running terminal (last tick 00:30:55 server
with UTC 22:30:56 on the wall clock; the account's own M15 bars forming). The offset is
not guessed either: the parity contract measured **+60** through January-March and **+120**
from April on this venue's own bars (docs/DATA_SCOPE_AND_CLOCK_20260920.md), one step at
the EU DST boundary. These tests pin the rule that reproduces those measurements, so the
live checks and the certified windows read one clock.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import live_readiness as lr  # noqa: E402


def utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


# --- the offset rule must reproduce the months the parity contract measured ---------

@pytest.mark.parametrize("when,expected", [
    (utc(2026, 1, 14, 12), 60),      # measured: January-March sit on +60
    (utc(2026, 3, 20, 12), 60),      # still winter, days before the step
    (utc(2026, 4, 2, 12), 120),      # measured: April onward sits on +120
    (utc(2026, 7, 1, 12), 120),
    (utc(2026, 9, 20, 22, 30), 120),  # the value that made a live tick read as -120 min
    # Beyond the measured range (Jan-Sep) the rule keeps EU DST, which is the venue's
    # observed convention one step either side of the boundary. Pinned so the
    # extrapolation is visible rather than buried in the helper.
    (utc(2026, 10, 20, 12), 120),    # still summer time, before Oct 25
    (utc(2026, 10, 27, 12), 60),     # after the October step
])
def test_the_offset_rule_reproduces_the_measured_months(when, expected):
    assert lr.venue_offset_min(when) == expected


@pytest.mark.parametrize("when,expected", [
    # EU DST: 01:00 UTC on the last Sunday of March and of October.
    (utc(2026, 3, 29, 0, 59), 60),
    (utc(2026, 3, 29, 1, 0), 120),
    (utc(2026, 10, 25, 0, 59), 120),
    (utc(2026, 10, 25, 1, 0), 60),
])
def test_the_step_lands_on_the_eu_dst_boundary(when, expected):
    assert lr.venue_offset_min(when) == expected


def test_the_last_sunday_helper_lands_on_a_sunday():
    for month in (3, 10):
        d = lr._last_sunday(2026, month)
        assert d.weekday() == 6 and d.day >= 25, d


# --- the gold week -------------------------------------------------------------------

@pytest.mark.parametrize("when,open_now", [
    (utc(2026, 9, 20, 21, 59), False),   # Sunday before the open
    (utc(2026, 9, 20, 22, 0), True),     # the week begins
    (utc(2026, 9, 20, 22, 27), True),    # the moment the tool used to say "167.5h away"
    (utc(2026, 9, 21, 12, 0), True),     # Monday midday
    (utc(2026, 9, 21, 21, 30), False),   # the daily break
    (utc(2026, 9, 21, 22, 0), True),
    (utc(2026, 9, 25, 20, 59), True),    # Friday before the close
    (utc(2026, 9, 25, 21, 0), False),
    (utc(2026, 9, 26, 12, 0), False),    # Saturday
])
def test_the_week_is_sun_2200_to_fri_2100_utc(when, open_now):
    got, why = lr.gold_session(when)
    assert got is open_now, why
    assert why, "every verdict must name the rule that produced it"


def test_next_open_is_now_when_the_market_is_open():
    """The measured defect: 27 minutes into the week, this returned a date 7 days out."""
    when = utc(2026, 9, 20, 22, 27)
    assert lr.next_gold_open(when) == when


@pytest.mark.parametrize("when,expected", [
    (utc(2026, 9, 20, 21, 0), utc(2026, 9, 20, 22, 0)),    # Sunday, waits for the open
    (utc(2026, 9, 21, 21, 30), utc(2026, 9, 21, 22, 0)),   # inside the daily break
    (utc(2026, 9, 25, 22, 0), utc(2026, 9, 27, 22, 0)),    # Friday night -> Sunday
    (utc(2026, 9, 26, 12, 0), utc(2026, 9, 27, 22, 0)),    # Saturday
])
def test_next_open_when_closed(when, expected):
    assert lr.next_gold_open(when) == expected


def test_a_stale_feed_inside_an_open_week_is_not_an_open_market():
    """The two readings must agree: a live session does not excuse a dead feed.

    The leg is `sched_open and live`, so a tick hours old inside the week fails the check
    even though `gold_session` says open. This pins the conjunction, because either half
    alone can produce a confident wrong answer.
    """
    when = utc(2026, 9, 21, 12, 0)
    sched_open, _ = lr.gold_session(when)
    stale_tick_utc = when - timedelta(hours=3)
    assert sched_open and (when - stale_tick_utc).total_seconds() >= 900


def test_the_tick_age_is_converted_with_the_measured_offset():
    """The exact measured case: tick epoch 00:30:55 server, wall clock 22:30:56 UTC."""
    now = utc(2026, 9, 20, 22, 30, 56)
    off = lr.venue_offset_min(now)
    tick_epoch = utc(2026, 9, 21, 0, 30, 55).timestamp()
    age = (now - (datetime.fromtimestamp(tick_epoch, tz=timezone.utc)
                  - timedelta(minutes=off))).total_seconds()
    assert off == 120
    assert abs(age) <= 60, f"a live tick must read as fresh, got {age:.0f}s"


# --- and the offset the EA ANNOUNCES ---------------------------------------------------

def test_the_ea_refuses_to_announce_an_offset_it_cannot_vouch_for():
    """MEASURED 2026-09-21, twice in one morning, and pinned here because the health guide
    tells an operator to VERIFY this number before the live gate.

    The banner derived the offset from `TimeCurrent()` — the time of the LAST TICK — so for
    minutes after a launch it read a band that had nothing to do with the venue: two
    separate launches announced `offset=-5 h 19 min` and `-5 h 36 min` for a venue that is
    UTC+2, while the terminal's own trade-server clock said `+2 h 00 min`. A confidently
    wrong number is worse than no number, so the banner now cross-checks the two clocks and
    says UNVERIFIED OFFSET rather than pick one.
    """
    src = open(os.path.join(REPO, "mql5", "MIDASTOUCH", "MidastouchAI.mq5"),
               encoding="utf-8", errors="replace").read()
    assert "TimeTradeServer()" in src, \
        "the banner must cross-check against the terminal's own server clock"
    assert "UNVERIFIED OFFSET" in src, "and refuse to state an offset the two clocks dispute"
    assert "the time of the last TICK" in src, "the reason is recorded, not just the guard"
    # The guard must be a comparison, not a constant: a hardcoded offset would hide a
    # venue clock change instead of reporting it.
    assert "off_tick" in src and "off_trd" in src and "off_delta" in src
    # The probe writes the same thing into the calendar's headers, for the same reason.
    probe = open(os.path.join(REPO, "mql5", "MIDASTOUCH", "MidasNewsProbe.mq5"),
                 encoding="utf-8", errors="replace").read()
    assert "datetime trade_server = TimeTradeServer();" in probe, \
        "the calendar's window and offset headers must not come from the last tick"
    assert "server_offset_min_from_last_tick" in probe, \
        "the stale reading is kept beside it, not thrown away"
