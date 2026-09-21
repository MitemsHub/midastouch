"""A replay's calendar is the FROZEN one; the arm's rolling file is not a measurement.

WHY THIS FILE EXISTS. The repo already knew a tester pass must not refresh its own calendar
(see `midas_parity`'s `InpNewsRefreshHours=0`, "a refresh would rewrite the very file this
pass is judged against"). What it did not guard was the OTHER writer: the attached EA, whose
live refresh pulls `CalendarValueHistory(now - N days, now + M days)` and rewrites
`<data>\\MQL5\\Files\\MIDASTOUCH_news_calendar.csv`.

Measured 2026-09-21 17:52Z, on this machine: that refresh cut the rolling file down to a
2026-09-09..2026-10-09 window, and the coverage the day's measurements stood on
(2026-01-02..2026-09-24, 2719 events / 369 HIGH) went with it. Every replay of the certified
window was then judged against a calendar with no event in it — the stand-down being measured
became a no-op that could not fire, which reads exactly like a rule with nothing to veto.

The fix is a second file with its own clock, and these tests are its pins: the snapshot is in
the repo and covers the window, the pass names the frozen file, the EA declares it
`#property tester_file` (or the tester never mirrors it), and there is no path here that
falls back to the rolling file when the snapshot is absent.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import midas_parity as P                                            # noqa: E402
from midas_prop.risk import news_calendar as NC                     # noqa: E402

#: The window `_window_spec("veto")` replays: the one parity run whose whole point is that a
#: release stands an entry down, so it is the window that goes silently useless first.
VETO_LO, VETO_HI = 1778457600, 1778975940


def test_the_frozen_snapshot_is_in_the_repo_and_covers_the_corpus() -> None:
    """The snapshot is tracked (unlike `artifacts/`, which is gitignored wholesale), so a
    fresh clone can run a replay. Its numbers are the ones the corpus was measured on."""
    src = P.frozen_news_source()
    assert src.is_file(), f"the data-of-record calendar is missing: {src}"
    assert hashlib.sha256(src.read_bytes()).hexdigest() == (
        "3a41c0b8f7c074c10de037efaf85777d588743989885f6b62c047e54481618e9"), (
        "the snapshot's bytes moved. If that was deliberate, the counts below, the table in "
        "configs/calendars/README.md and every docs/GOLD_NEWS_* measurement move with it")
    assert (src.parent / "README.md").is_file(), "the snapshot's provenance must travel with it"
    assert src.parent == REPO / "configs" / "calendars", (
        "the snapshot must live outside artifacts/: a gitignored calendar cannot be a "
        "replay's data of record")
    cal = NC.read_calendar(src)
    ev = NC.top_tier_events(cal)
    assert (len(cal.events), len(ev)) == (2719, 369), (
        "2719 events / 369 HIGH is the coverage docs/GOLD_NEWS_* measured on; a different "
        "count means the bytes changed and those documents describe something else")
    first = datetime.fromtimestamp(cal.events[0].epoch, timezone.utc)
    last = datetime.fromtimestamp(cal.events[-1].epoch, timezone.utc)
    assert (first, last) == (datetime(2026, 1, 2, 22, 3, tzinfo=timezone.utc),
                             datetime(2026, 9, 24, 0, 18, tzinfo=timezone.utc))
    # the property the file exists for: the veto window still has releases in it
    inw = [e for e in ev if VETO_LO <= e.epoch <= VETO_HI]
    assert inw, "the frozen calendar has no HIGH event in the veto window"
    days = {datetime.fromtimestamp(e.epoch, timezone.utc).strftime('%Y-%m-%d') for e in inw}
    assert "2026-05-14" in days, sorted(days)
    assert NC.source_problem(cal, VETO_HI, max_age_hours=P.NEWS_MAX_AGE_HOURS,
                             cover_hours=P.NEWS_COVER_HOURS) == ""


def test_the_two_calendars_are_two_names() -> None:
    """Distinct filenames, deliberately: one file name cannot be both the arm's rolling
    window and a frozen measurement. The live name is the EA's own default (pinned by
    tests/test_news_calendar.py); the frozen one is what a pass opens."""
    assert P.FROZEN_NEWS_FILE != P.NEWS_FILE
    assert P.FROZEN_NEWS_FILE.endswith(".csv")


def test_a_pass_names_the_frozen_calendar_and_the_ea_mirrors_it() -> None:
    """Two halves of one mechanism. The harness sets InpNewsFile to the frozen name, and the
    EA declares that name `#property tester_file` — without the property the tester never
    copies it into the agent sandbox, the EA fails closed on a missing file, and the pass
    reports a gate that refused everything."""
    inputs = P.build_inputs("REVERSE_DIRECTION", VETO_LO, VETO_HI, news=True)
    assert inputs["InpNewsFile"] == P.FROZEN_NEWS_FILE
    assert inputs["InpUseNewsFilter"] == "true"
    assert inputs["InpNewsRefreshHours"] == "0"
    ea = (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5").read_text(
        encoding="utf-8", errors="replace")
    for name in (P.NEWS_FILE, P.FROZEN_NEWS_FILE):
        assert f'#property tester_file "{name}"' in ea, name


def test_staging_puts_the_tracked_bytes_where_the_tester_mirrors_them(
        tmp_path: Path, monkeypatch) -> None:
    """Staging reads the snapshot, not the folder: whatever is lying in `MQL5\\Files` is not
    the data of record, and the rolling file must survive untouched."""
    files = tmp_path / "MQL5" / "Files"
    files.mkdir(parents=True)
    rolling = files / P.NEWS_FILE
    rolling.write_text("# the arm's rolling file\nevent\n", encoding="utf-8")
    monkeypatch.setattr(P, "R", SimpleNamespace(data_folder_for_terminal=lambda: str(tmp_path)))

    staged = P.stage_frozen_calendar()
    assert staged == files / P.FROZEN_NEWS_FILE
    assert staged.read_bytes() == P.frozen_news_source().read_bytes()
    assert rolling.read_text(encoding="utf-8") == "# the arm's rolling file\nevent\n", \
        "staging rewrote the live arm's rolling calendar"
    # idempotent, and `news_calendar_path` is the same file — one path, both engines
    assert P.stage_frozen_calendar() == staged
    assert P.news_calendar_path() == staged
    assert P.news_calendar_path() != P.live_news_calendar_path()
    # a POSITIONAL drift inside the staged copy is corrected on the next call, so a pass
    # cannot inherit a calendar someone edited under it
    staged.write_text("epoch_utc;time_utc;time_server;currency;country;importance;event\n",
                      encoding="utf-8")
    assert P.stage_frozen_calendar().read_bytes() == P.frozen_news_source().read_bytes()


def test_no_terminal_is_no_path_and_never_a_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(P, "R", SimpleNamespace(data_folder_for_terminal=lambda: None))
    assert P.news_calendar_path() is None
    assert P.live_news_calendar_path() is None


def test_a_missing_snapshot_refuses_instead_of_falling_back(
        tmp_path: Path, monkeypatch) -> None:
    """The whole point: with no data-of-record calendar the pass REFUSES. Standing in the
    rolling file here would restore the defect this file pins — a replay judged against
    whatever the arm last wrote."""
    monkeypatch.setattr(P, "R", SimpleNamespace(data_folder_for_terminal=lambda: str(tmp_path)))
    monkeypatch.setattr(P, "FROZEN_NEWS_SOURCE", tmp_path / "absent.csv")
    with pytest.raises(SystemExit) as e:
        P.news_calendar_path()
    assert "frozen calendar is missing" in str(e.value)
