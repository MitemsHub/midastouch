"""The news gate: the window, the refusals, the size, and the two engines agreeing.

WHY THIS FILE EXISTS. The playbook carried a news policy for months that no code could
honour, and the repository's answer was to refuse the label rather than fake the
protection (V2 register R6). That refusal is now replaced by a real source, and a real
source brings the failure mode this file exists to prevent: **a filter that silently does
nothing when its source is absent**. The journal would still say protection is ON while
every release traded straight through it.

So the refusals are pinned one at a time, in the EA's own words: missing, unreadable, no
generation time, stale, no coverage, no declared count, truncated, empty. "Empty" is
deliberately its own case — a zero count is evidence that we cannot see the calendar, not
evidence that nothing is scheduled — and it is the one a naive implementation treats as
"no news, proceed". The repository already paid for that mistake once: the EA's row count
matched the column header, so an EMPTY calendar looked like a covered, non-empty one in
the EA while the python mirror refused the very same file. `test_the_header_is_not_an_event`
is that defect, pinned.

The events come from a file because the calendar is unreachable from both other
directions: MetaTrader5 5.0.5735 has no calendar function at all, and the strategy tester
returns `GetLastError() = 4014` for `CalendarValueHistory` (measured 2026-09-20). One rule
two engines read is a rule that can be replayed; that is why the file is the contract —
and why the EA refreshes it itself rather than waiting for someone to run the probe.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from midas_prop.risk import news_calendar as nc  # noqa: E402

EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
PROBE = REPO / "mql5" / "MIDASTOUCH" / "MidasNewsProbe.mq5"
MIRROR = REPO / "src" / "midas_prop" / "risk" / "news_calendar.py"

EA_SRC = EA.read_text(encoding="utf-8")
PROBE_SRC = PROBE.read_text(encoding="utf-8")
MIRROR_SRC = MIRROR.read_text(encoding="utf-8")
#: Comment-stripped: a phrase in a comment is a claim ABOUT the code, not the code.
EA_CODE = re.sub(r"//[^\n]*", "", EA_SRC)

NOW = 1789000000  # 2026-09-13 22:26:40 UTC — arbitrary but fixed
COLUMN_LINE = ";".join(nc.COLUMNS)
WRITERS = ("MidastouchAI.mq5", "MidasNewsProbe.mq5")


def calendar_text(generated: int = NOW, window_to: int = NOW + 21 * 86400,
                  events: list[tuple[int, str]] | None = None,
                  declared: int | None = None, writer: str = WRITERS[0]) -> str:
    """A writer-shaped file: numeric epochs, the declared columns, header metadata."""
    events = events if events is not None else [(NOW + 3600, "Nonfarm Payrolls")]
    n = len(events) if declared is None else declared
    lines = [
        f"# MIDASTOUCH news calendar — written by {writer}",
        f"# epoch_generated_utc={generated}",
        f"# epoch_window_to_utc={window_to}",
        f"# events={n}",
        COLUMN_LINE,
    ]
    for epoch, name in events:
        lines.append(f"{epoch};2026.09.14 00:00:00;2026.09.14 02:00:00;USD;US;HIGH;{name}")
    return "\r\n".join(lines) + "\r\n"


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "MIDASTOUCH_news_calendar.csv"
    p.write_bytes(text.encode("utf-8"))
    return p


# --- the wire format, on both writers ------------------------------------------------

@pytest.mark.parametrize("path", [PROBE, EA], ids=["probe", "ea"])
def test_both_writers_emit_the_columns_and_epochs_the_readers_parse(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for column in nc.COLUMNS:
        assert column in text, f"a writer must emit the {column!r} column"
    for key in ("epoch_generated_utc", "epoch_window_to_utc", "events"):
        assert f"# {key}=" in text or f"# {key}=" in text.replace("# ", "# "), key
    assert "# epoch_generated_utc=" in text and "# epoch_window_to_utc=" in text
    # Numeric epochs, never a parsed date: one clock mistake was enough for this program.
    assert "(long)now_gmt" in text


def test_the_header_is_not_an_event() -> None:
    """The defect: the EA counted the column header as a release.

    Its skip tested `startsWith("time_utc")`, but the header line begins with
    `epoch_utc`, so a zero-event calendar counted one row — non-empty here while the
    mirror refused the same file. Two engines, one file, one count.
    """
    empty = nc.parse(calendar_text(events=[]))
    assert empty.events == () and empty.declared_events == 0
    assert nc.source_problem(empty, NOW) == nc.REASON_EMPTY
    assert "if(StringSplit(line, (ushort)';', first) < 7) continue;" in EA_CODE
    assert 'if((long)StringToInteger(first[0]) <= 0) continue;' in EA_CODE
    assert "startswith(COLUMNS[0])" in MIRROR_SRC


def test_a_well_formed_calendar_parses(tmp_path: Path) -> None:
    cal = nc.read_calendar(write(tmp_path, calendar_text()))
    assert cal.generated_utc == NOW and cal.window_to_utc == NOW + 21 * 86400
    assert len(cal.events) == 1 and cal.events[0].is_top_tier
    assert nc.source_problem(cal, NOW) == ""


def test_a_file_written_by_the_ea_reads_the_same_as_one_written_by_the_probe(tmp_path: Path) -> None:
    for writer in WRITERS:
        cal = nc.read_calendar(write(tmp_path, calendar_text(writer=writer)))
        assert nc.source_problem(cal, NOW) == "", writer
        assert nc.blackout_reason(cal.events, NOW + 3600) != "", writer


# --- the refusals, one at a time -----------------------------------------------------

def test_a_missing_file_refuses_with_its_own_phrase(tmp_path: Path) -> None:
    with pytest.raises(nc.CalendarUnusable) as e:
        nc.read_calendar(tmp_path / "nope.csv")
    assert nc.REASON_MISSING in str(e.value)
    assert nc.veto_reason(None, NOW).startswith(nc.REASON_MISSING)


def test_a_file_without_a_generation_time_cannot_be_judged() -> None:
    cal = nc.parse(calendar_text(generated=0))
    assert nc.source_problem(cal, NOW).startswith(nc.REASON_NO_GENERATION_TIME)


def test_a_stale_calendar_refuses() -> None:
    """Past the budget: provenance we cannot date is provenance we drop."""
    cal = nc.parse(calendar_text(generated=NOW - 25 * 3600))
    reason = nc.source_problem(cal, NOW)
    assert reason.startswith(nc.REASON_STALE) and "25.0h" in reason


def test_a_calendar_that_does_not_cover_now_refuses() -> None:
    cal = nc.parse(calendar_text(window_to=NOW + 3600))
    assert nc.source_problem(cal, NOW).startswith(nc.REASON_NO_COVERAGE)


def test_a_calendar_with_no_declared_count_cannot_be_checked_for_completeness() -> None:
    text = "\n".join(l for l in calendar_text().splitlines() if not l.startswith("# events="))
    cal = nc.parse(text)
    assert cal.declared_events is None
    assert nc.source_problem(cal, NOW) == nc.REASON_NO_DECLARED_COUNT


def test_a_truncated_calendar_refuses_instead_of_looking_quiet() -> None:
    """The declared count is a truncation detector: a half-written file is not a quiet
    news week, and the two are indistinguishable without it."""
    cal = nc.parse(calendar_text(declared=4))
    reason = nc.source_problem(cal, NOW)
    assert reason.startswith(nc.REASON_TRUNCATED) and "holds 1" in reason


def test_an_empty_calendar_is_a_refusal_and_not_an_all_clear() -> None:
    cal = nc.parse(calendar_text(events=[]))
    assert nc.source_problem(cal, NOW) == nc.REASON_EMPTY
    assert nc.veto_reason(cal, NOW) == nc.REASON_EMPTY


def test_the_window_end_must_be_declared() -> None:
    cal = nc.parse(calendar_text(window_to=0))
    assert nc.source_problem(cal, NOW).startswith(nc.REASON_NO_WINDOW)


# --- the window itself ---------------------------------------------------------------

@pytest.mark.parametrize("offset,blackout", [
    (0, True),          # on the release
    (15 * 60, True),    # the declared edge, inclusive
    (-15 * 60, True),   # the past edge — exactly when the tape is least like the fit
    (15 * 60 + 1, False),
    (-15 * 60 - 1, False),
    (3600, False),
])
def test_the_window_is_symmetric_and_inclusive_at_the_edge(offset: int, blackout: bool) -> None:
    events = (nc.Event(epoch=NOW + 600, currency="USD", importance="HIGH",
                       name="CPI m/m"),)
    reason = nc.blackout_reason(events, NOW + 600 + offset, window_min=15)
    assert bool(reason) is blackout, reason


@pytest.mark.parametrize("importance", ["LOW", "MEDIUM"])
def test_non_top_tier_events_do_not_veto(importance: str) -> None:
    """The policy is about releases that move gold, not about the calendar in general."""
    events = (nc.Event(epoch=NOW, currency="USD", importance=importance, name="Wholesale"),)
    assert nc.blackout_reason(events, NOW) == ""


def test_the_window_is_configurable_and_defaults_to_fifteen() -> None:
    events = (nc.Event(epoch=NOW, currency="USD", importance="HIGH", name="FOMC"),)
    assert nc.blackout_reason(events, NOW + 20 * 60, window_min=15) == ""
    assert nc.blackout_reason(events, NOW + 20 * 60, window_min=30) != ""


def test_malformed_rows_are_skipped_not_guessed(tmp_path: Path) -> None:
    extra = "\n".join([
        "not-a-row",
        ";",
        ";;;",
        f"{NOW - 60};x;y;USD;US;HIGH;Edge",
    ])
    cal = nc.read_calendar(write(tmp_path, calendar_text(declared=2) + extra))
    assert [e.name for e in cal.events] == ["Nonfarm Payrolls", "Edge"]


def test_a_veto_names_the_event_the_operator_needs_to_see() -> None:
    events = (nc.Event(epoch=NOW + 60, currency="USD", importance="HIGH",
                       name="Nonfarm Payrolls"),)
    reason = nc.blackout_reason(events, NOW)
    assert "Nonfarm Payrolls" in reason and "15" in reason


# --- the source has to repair itself --------------------------------------------------

def test_the_ea_refreshes_the_calendar_it_reads() -> None:
    """A fail-closed gate over a source nobody refreshes is a permanent stand-down."""
    assert "bool NewsRefreshIfDue(datetime now_gmt)" in EA_CODE
    assert "bool NewsWriteCalendar(datetime now_gmt)" in EA_CODE
    assert "CalendarValueHistory(values, from, to, NULL, \"USD\")" in EA_CODE
    # called at init (before the source is judged) and on the heartbeat
    init = EA_CODE[EA_CODE.index("int OnInit()"):]
    assert init.index("NewsRefreshIfDue(TimeGMT())") < init.index("NewsSourceProblem()")
    timer = EA_CODE[EA_CODE.index("void OnTimer()"):EA_CODE.index("void OnTimer()") + 900]
    assert "NewsRefreshIfDue(TimeGMT())" in timer


def test_the_refresh_cannot_run_where_the_calendar_is_unreadable() -> None:
    """4014 is the platform's rule, not a preference: the tester must not even try."""
    fn = EA_CODE[EA_CODE.index("bool NewsRefreshIfDue"):EA_CODE.index("void TrackFreshM15Bar")]
    assert "if(MQLInfoInteger(MQL_TESTER)) return false;" in fn
    # 2026-09-21: the STATE STAMP reads the same file, so a recording-only arm (gate OFF,
    # InpRecordStateLabel ON) keeps the source alive too — otherwise it would stamp `na`
    # forever, and `na` is not evidence of no news.
    assert "if(!InpUseNewsFilter && !InpRecordStateLabel) return false;" in fn
    assert "g_news_refresh_at" in fn, "the API must not be hammered every tick"
    assert "InpNewsRefreshHours" in fn


def test_an_empty_answer_never_overwrites_a_usable_calendar() -> None:
    """A call that returns nothing is a failure to MEASURE, not news — and destroying a
    good file with it would manufacture the stand-down the gate exists to express."""
    fn = EA_CODE[EA_CODE.index("bool NewsWriteCalendar"):EA_CODE.index("bool NewsRefreshIfDue")]
    guard = fn.index("if(written <= 0)")
    assert guard < fn.index("FileOpen(InpNewsFile, FILE_WRITE"), \
        "the write must be guarded before the file is opened for writing"


def test_the_bar_replay_no_longer_refuses_a_gate_the_other_engine_now_applies() -> None:
    """v1.19c refused `InpBarModel + InpUseNewsFilter` at init because the python engine of
    record could not apply the veto: a rule the other engine cannot see is a silent no-op.

    v1.19d removed that refusal — but only because the condition it named went away. The
    engine of record applies the same veto now (`scripts/midas_sweep.py` `use_news`), and
    the test below is what keeps the removal honest: if the mirror is ever dropped, the
    refusal must come back, because this combination would be a lie again.
    """
    init = EA_CODE[EA_CODE.index("int OnInit()"):]
    block = init[init.index("if(InpBarModel && InpUseNewsFilter)"):][:900]
    assert "INIT_FAILED" not in block, (
        "the sole reason for that refusal — the other engine cannot apply the rule — is "
        "gone; refusing now would forbid a comparison the harness can make")
    assert "AMENDMENT" in block, \
        "but it is still not a reproduction, and the init line must say so"
    mirror = (REPO / "scripts" / "midas_sweep.py").read_text(encoding="utf-8")
    assert "def use_news(" in mirror and "news_veto_reason(" in mirror, (
        "the EA may only drop that refusal while the engine of record really applies the "
        "veto — this assertion is the pair to the one above")
    engine = (REPO / "scripts" / "midas_parity.py").read_text(encoding="utf-8")
    assert "use_news(events if news else None)" in engine, (
        "and the harness must arm it on both sides in one stance")


def test_a_bar_pass_with_the_gate_on_is_stamped_as_an_amendment() -> None:
    """A pass certifying a stance the corpus never ran must not look identical to one that
    reproduced it. The ledger's era note is where that survives the pass."""
    b = EA_CODE
    assert 'if(InpBarModel && InpUseNewsFilter)\r\n      era_note += "+news-amendment";' \
        in b or 'if(InpBarModel && InpUseNewsFilter)\n      era_note += "+news-amendment";' in b, \
        "the BAR+news pass must say so in its own ledger"
    assert 'era_note = InpBarModel ? "bar-model-parity"' in b, (
        "and the gate-OFF BAR note must stay byte-for-byte as certified")


# --- and the two engines must not drift ----------------------------------------------

def test_the_ea_declares_the_same_window_and_budgets_as_the_mirror() -> None:
    for line in (
        "input int                  InpNewsWindowMin    = 15;",
        "input int                  InpNewsMaxAgeHours  = 24;",
        "input int                  InpNewsCoverHours   = 24;",
        "input int                  InpNewsRefreshHours = 6;",
        "input string               InpNewsFile         = \"MIDASTOUCH_news_calendar.csv\";",
    ):
        assert line in EA_SRC, line


def test_both_engines_speak_the_same_refusal_vocabulary() -> None:
    """An operator must not have to learn two vocabularies to read two engines."""
    for phrase in (
        nc.REASON_MISSING,
        nc.REASON_UNREADABLE,
        nc.REASON_NO_GENERATION_TIME,
        nc.REASON_STALE,
        nc.REASON_NO_WINDOW,
        nc.REASON_NO_COVERAGE,
        nc.REASON_NO_DECLARED_COUNT,
        nc.REASON_TRUNCATED,
        nc.REASON_EMPTY,
    ):
        # The EA is C: a quoted tail inside a refusal is written with escaped quotes, so
        # the comparison normalises those rather than demanding byte-identical literals.
        assert phrase in EA_SRC.replace('\\"', '"'), f"the EA no longer says {phrase!r}"
        assert phrase in MIRROR_SRC, f"the mirror no longer says {phrase!r}"


def test_the_ea_parses_the_header_keys_the_writers_actually_emit() -> None:
    """MEASURED 2026-09-21, on the COMPILED EA, by scripts/news_gate_rehearsal.py.

    The writers emit `# epoch_generated_utc=<n>` — a '#' and a SPACE. The EA took
    `StringSubstr(line, 1, eq - 1)` for the key, which leaves that space in place, and
    trimmed only the right side, so the key was `" epoch_generated_utc"`, no comparison
    ever matched, and EVERY calendar was judged "carries no generation time". The gate
    could not once see a usable source: it stood the arm down permanently and the fixture
    with eight events in it produced refusal after refusal. The python mirror parsed the
    same file fine (`line.lstrip("# ")`), so the two engines disagreed about one file in
    the worst direction. No source-text pin here could see this; the rehearsal caught it
    by running the thing, and these assertions exist so the fix cannot be undone.
    """
    fn = EA_CODE[EA_CODE.index("string NewsSourceProblem"):EA_CODE.index("string NewsVetoReason")]
    substr = fn.index("StringSubstr(line, 1, eq - 1)")
    assert "StringTrimLeft(key);" in fn[substr:substr + 120], \
        "the key must be trimmed on BOTH sides: the writers put a space after the '#'"
    assert fn.index("StringTrimLeft(val);") > substr
    assert 'line.lstrip("# ")' in MIRROR_SRC, "the mirror's own trim is the other half"


def test_the_rehearsal_that_found_it_stays_runnable() -> None:
    """The rehearsal is the only thing here that runs the compiled Expert, so its own
    safety properties are pinned: it must state its fixtures in the PASS'S clock (the
    tester's `TimeGMT()` is the simulated window time, and a host-clock 'stale' fixture
    reads as the future — measured, one run), and it must not leave a synthetic calendar
    on a machine that may later run this gate for real."""
    script = REPO / "scripts" / "news_gate_rehearsal.py"
    src = script.read_text(encoding="utf-8")
    assert "WINDOW_ANCHOR" in src and "simulated" in src
    for state in ("usable", "stale", "truncated", "empty", "missing"):
        assert f'"{state}":' in src or f'"{state}",' in src, state
    assert "cal_path.unlink(missing_ok=True)" in src
    assert "midas_watchdog_paused" in src, "a tester session must pause the watchdog"


def test_the_ea_gate_is_entry_only_and_sits_with_the_time_gates() -> None:
    # Reached from the signal path, never from an exit path: a rule that could trap a
    # position through a release would breach the shield it claims to protect.
    assert EA_CODE.count("NewsVetoReason(") == 2, "one definition, one gate call"
    signal = EA_CODE[EA_CODE.index("void TrackFreshM15Bar()"):][:6000]
    assert "NewsVetoReason(TimeUTCNow())" in signal
    for exit_fn in ("void LiveCheckExits()", "void LiveClosePosition(string reason)",
                    "void PaperClose(string reason, double exit_price)"):
        window = EA_CODE[EA_CODE.index(exit_fn):][:2500]
        assert "NewsVetoReason" not in window, f"{exit_fn} must not run the news gate"


def test_the_old_false_label_is_gone_and_the_reason_is_recorded() -> None:
    """R6's INIT_FAILED was right when no engine existed; it would be a lie now."""
    assert "INIT FAILED: InpUseNewsFilter=true names a calendar" not in EA_SRC
    assert "4014" in EA_SRC, "the EA must record why the tester cannot read the calendar"
    assert "NEWS FILTER ON — source %s: %s" in EA_SRC, \
        "init must report whether the source is usable, not just ON/OFF"


def test_the_no_fill_census_counts_news_vetoes() -> None:
    assert "g_nofill_news" in EA_CODE
    # v1.27 appended `nodata` after `news`, so the row's tail is now `...,g_nofill_news,\n    # g_nofill_nodata));`. The pin is written against the APPEND-ONLY property rather than the
    # exact tail text, because the counter list is documented as append-only and a literal
    # pin makes every future append look like a regression of the news count it is not.
    m = re.search(r"g_nofill_brk,\s*g_nofill_notr,\s*g_nofill_news,?\s*(g_nofill_nodata)?\s*\)\)",
                  EA_CODE)
    assert m, "the daily NOFILL row must carry the news count, appended so old readers keep working"
    assert "g_nofill_news" in EA_CODE[
        EA_CODE.index("void DiagRollIfNewDay")::][:2000], \
        "the census row is what carries it"
