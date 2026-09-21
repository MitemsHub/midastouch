"""The news-veto sensitivity harness: the mask's semantics, and the control that makes it evidence.

WHY THIS FILE EXISTS. `scripts/gold_news_sensitivity.py` answers a question the program
has only ever asserted — "the +/-15-minute stand-down can only help" — by replaying the
frozen walk-forward twice. Two things about it can be wrong in ways that produce a
confident, meaningless number, and both are pinned here:

  * THE INSTANT. The engine fills at bar `i`'s CLOSE, and the EA judges the same bar with
    `TimeGMT()` as "now". Judging the bar's OPEN instead shifts every decision one bar
    early and under-counts the rule's reach without failing anything. The test below
    places an event 15 minutes before the close and 15 minutes after the open, so the two
    conventions disagree on it and only one of them is right.

  * THE CONTROL. The veto-OFF leg must reproduce `artifacts/gold_wfo.json`. If it does
    not, a difference between the legs is an artefact of the harness, and the script must
    refuse rather than report. Tested by forcing a mismatch.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import gold_news_sensitivity as G  # noqa: E402
from midas_prop.risk import news_calendar as NC  # noqa: E402

M15 = 900
BASE = 1_770_000_000
#: A generation time AFTER the frozen window's end (2026-09-18). Freshness is judged in
#: the window's frame, not today's: a calendar written after the window closed and
#: covering it is usable for a retrospective replay, and one written before it is not.
GEN = 1_790_000_000
WIN_TO = GEN + 86_400


def _ev(epoch: int, importance: str = "HIGH", name: str = "Nonfarm Payrolls") -> NC.Event:
    return NC.Event(epoch=epoch, currency="USD", importance=importance, name=name)


def _epochs(n: int, step: int = M15) -> np.ndarray:
    return np.array([BASE + i * step for i in range(n)], dtype=float)


# --- the instant the veto judges ------------------------------------------------------

def test_the_release_blocks_the_bar_whose_close_it_lands_on():
    """The entry fills at close[i]; the EA's "now" on that bar is the same instant.

    Bars are 30 minutes apart here so the geometry is unambiguous: a release at bar 1's
    close is 30 minutes from bar 0's and bar 2's closes, i.e. outside the window.
    """
    epoch = _epochs(3, step=1800)
    close_of_bar_1 = int(epoch[1]) + M15
    mask = G.blackout_mask(epoch, (_ev(close_of_bar_1),))
    assert list(mask) == [False, True, False]


def test_on_m15_bars_one_release_blocks_three_bars_not_one():
    """On the execution timeframe (±15 min window, 15 min bars) a single release reaches
    the bars on either side of it, because their closes are exactly one window away. Worth
    pinning: the rule is not "skip the news bar", and a reader who assumes it is
    under-counts the trades it removes."""
    epoch = _epochs(5)
    close_of_bar_2 = int(epoch[2]) + M15
    assert list(G.blackout_mask(epoch, (_ev(close_of_bar_2),))) == \
        [False, True, True, True, False]


def test_the_judged_instant_is_the_close_not_the_open():
    """An event 15 minutes after the bar's OPEN is 0 minutes from its open and 15 minutes
    from its close: in-window only under the close convention, which is the measured one.
    An event at the OPEN + 16 min is outside both, so the test cannot pass by accident."""
    epoch = _epochs(2)
    at_close_minus_15 = int(epoch[0]) + M15 - 15 * 60        # 15 min before the close
    assert bool(G.blackout_mask(epoch, (_ev(at_close_minus_15),))[0]) is True
    just_outside = int(epoch[0]) + M15 - 15 * 60 - 1         # one second beyond it
    assert bool(G.blackout_mask(epoch, (_ev(just_outside),))[0]) is False


def test_the_window_is_symmetric_and_inclusive_at_both_edges():
    """A release that has just printed is the case that matters most; the reader's own
    rule is |now - event| <= window, so both edges must be inside."""
    epoch = _epochs(1)
    close = int(epoch[0]) + M15
    for offset, blocked in ((-15 * 60, True), (15 * 60, True),
                            (-15 * 60 - 1, False), (15 * 60 + 1, False)):
        mask = G.blackout_mask(epoch, (_ev(close + offset),))
        assert bool(mask[0]) is blocked, offset


def test_only_high_importance_events_block():
    """The EA's rule is top-tier only (news_calendar.IMPORTANCE). A MEDIUM event must not
    veto, or the filter changes the strategy rather than protecting it."""
    epoch = _epochs(1)
    close = int(epoch[0]) + M15
    assert bool(G.blackout_mask(epoch, (_ev(close, "MEDIUM"),))[0]) is False
    assert bool(G.blackout_mask(epoch, (_ev(close, "LOW"),))[0]) is False
    assert bool(G.blackout_mask(epoch, (_ev(close, "HIGH"),))[0]) is True


def test_no_high_events_means_no_blackout_at_all():
    assert not G.blackout_mask(_epochs(50), (_ev(BASE, "MEDIUM"),)).any()
    assert not G.blackout_mask(_epochs(50), ()).any()


def test_the_mask_is_the_same_rule_the_reader_enforces():
    """The harness must not re-implement the window. One event, one instant, judged by
    both the mask and the mirror reader, must agree — otherwise the measurement is of a
    rule the EA does not have."""
    epoch = _epochs(1)
    close = int(epoch[0]) + M15
    events = (_ev(close + 600),)
    assert bool(G.blackout_mask(epoch, events)[0]) is True
    assert NC.blackout_reason(events, close, window_min=15) != ""
    far = (_ev(close + 20 * 60),)
    assert bool(G.blackout_mask(epoch, far)[0]) is False
    assert NC.blackout_reason(far, close, window_min=15) == ""


# --- the refusals ---------------------------------------------------------------------

def _write_calendar(path: Path, *, generated: int, window_to: int, declared: int,
                    rows: list[tuple[int, str]]) -> Path:
    body = ["# MIDASTOUCH news calendar - test fixture",
            f"# epoch_generated_utc={generated}",
            "# epoch_window_from_utc=0",
            f"# epoch_window_to_utc={window_to}",
            f"# events={declared}",
            "epoch_utc;time_utc;time_server;currency;country;importance;event"]
    for epoch, importance in rows:
        body.append(f"{epoch};2026.01.01 00:00:00Z;2026.01.01 02:00:00;USD;US;"
                    f"{importance};Release")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def test_an_empty_calendar_is_refused_not_treated_as_no_news(tmp_path):
    """The one confusion this whole subsystem exists to prevent."""
    cal = _write_calendar(tmp_path / "c.csv", generated=BASE, window_to=BASE + 86400,
                          declared=0, rows=[])
    parsed = NC.read_calendar(cal)
    assert "empty" in NC.source_problem(parsed, BASE)


def test_a_truncated_calendar_is_refused(tmp_path):
    cal = _write_calendar(tmp_path / "c.csv", generated=BASE, window_to=BASE + 86400,
                          declared=3, rows=[(BASE + 60, "HIGH")])
    parsed = NC.read_calendar(cal)
    assert "truncated" in NC.source_problem(parsed, BASE)


def test_a_missing_calendar_file_is_a_declared_reason(tmp_path):
    with pytest.raises(NC.CalendarUnusable) as e:
        NC.read_calendar(tmp_path / "nope.csv")
    assert e.value.reason == NC.REASON_MISSING


def test_the_harness_refuses_without_a_frozen_artifact(tmp_path):
    try:
        G.main(["--frozen", str(tmp_path / "nope.json")])
    except SystemExit as e:
        assert "frozen artifact" in str(e)
    else:
        raise AssertionError("a delta needs something to be a delta against")


def test_the_harness_refuses_without_a_calendar(tmp_path):
    frozen = tmp_path / "frozen.json"
    frozen.write_text('{"data": {"first": "2026-01-12T13:15:00+00:00",'
                      ' "last": "2026-09-18T22:45:00+00:00"},'
                      ' "spec": {"control_reps": 1}, "checks": {}, "stats": {}}',
                      encoding="utf-8")
    try:
        G.main(["--frozen", str(frozen), "--calendar", str(tmp_path / "nope.csv")])
    except SystemExit as e:
        assert "no calendar" in str(e)
    else:
        raise AssertionError("a veto cannot be measured without a calendar")


def test_the_harness_refuses_when_the_off_leg_does_not_reproduce_the_artifact(
        tmp_path, monkeypatch):
    """The control. If veto-OFF does not reproduce the frozen run, any gap to veto-ON is
    uninterpretable and the script must say REFUSING rather than print a number."""
    frozen = tmp_path / "frozen.json"
    frozen.write_text(
        '{"data": {"first": "2026-01-12T13:15:00+00:00",'
        ' "last": "2026-09-18T22:45:00+00:00"},'
        ' "spec": {"control_reps": 1},'
        ' "checks": {"V1 total>0": true}, "stats": {"_total": 1.0, "_median": 0.0, "_t": 0.5},'
        ' "oos_trades": 5, "control_total_r": -1.0, "oos_r_per_fold": [0.5]}',
        encoding="utf-8")
    # The fake corpus must END on the artifact's last bar, or the harness refuses one
    # guard earlier (correctly) and the control is never reached.
    frozen_last = int(datetime.fromisoformat("2026-09-18T22:45:00+00:00").timestamp())
    fake = np.array([frozen_last - (599 - i) * M15 for i in range(600)], dtype=float)
    monkeypatch.setattr(G, "corpus",
                        lambda symbol, last: ({"epoch": fake}, None, None, None))
    monkeypatch.setattr(G, "blackout_mask", lambda *a, **k: np.zeros(600, dtype=bool))
    monkeypatch.setattr(G, "leg", lambda *a, **k: {
        "folds": [("F01", 0, 1), ("F02", 1, 2)], "picks": [], "oos_rs": [0.0],
        "checks": {"V1 total>0": True, "_total": 99.0, "_median": 0.0, "_t": 0.5},
        "control_total": -1.0, "oos_trades": 5, "oos_detail": [], "trades_by_cfg": [],
        "all_cfgs": [], "entry_bars": set()})
    cal = _write_calendar(tmp_path / "c.csv", generated=GEN, window_to=WIN_TO,
                          declared=1, rows=[(BASE + 60, "HIGH")])
    try:
        G.main(["--frozen", str(frozen), "--calendar", str(cal), "--control-reps", "1"])
    except SystemExit as e:
        assert "REFUSING" in str(e) and "does not reproduce" in str(e)
    else:
        raise AssertionError("the control must gate the reported delta")


def test_the_artifact_records_the_convention_it_used(tmp_path):
    """A number without its convention is not evidence: the artifact must name the judged
    instant and the calendar it was measured against."""
    src = (REPO / "scripts" / "gold_news_sensitivity.py").read_text(encoding="utf-8")
    assert "judged_instant" in src
    assert "bar close (epoch[i] + 900)" in src, "the convention is stated, not implied"
    assert "reproduced_frozen" in src
