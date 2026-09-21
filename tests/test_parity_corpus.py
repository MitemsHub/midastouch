"""One market for both legs — the defect that made a data gap look like a clock fault.

WHY THIS FILE EXISTS. The parity harness compares the EA's ledger against the engine of
record, key by key. That comparison is only meaningful if both sides were walked through the
SAME BARS, and until 2026-09-21 they were not: `python_build_data` read `XAUUSD_M15.csv` (a
separately fetched series) while the tester ran the EA on the terminal's own history. The two
disagree about 21 bars inside the tick-covered window.

The symptom was diagnosed as a clock problem for a day, because the first divergent trade
closed exactly 7,200 s apart — the venue's own +120 min offset — while its entry agreed to
the second. It is not a clock problem. Python's series stops for the venue's daily break at
18:15 UTC and resumes at 00:00; the venue's own series holds 22:00-23:45 on the same evening.
A 12-hour timeout opened at 08:45 can therefore fire at 22:15 on one side and only at 00:15
on the other. On the venue's series the same window matches 6 of 9 keys instead of 2.

Pinned here: the disagreement itself (as a measurement, not a claim), the shift that turns
the venue's clock into UTC, the refusal that stops a cross-market comparison from ever being
run, and the `veto` window's reason for existing — including the fact that a pass on it can
never be recorded as a certificate.

AND, since 2026-09-21, the retirement itself. Having two series both answer to "the gold
bars" cost a day of misdiagnosis and one wrong cost model, so the duplicate was not
documented away — the legacy series was moved out of the data of record into
`archive/frozen_corpus/`, where `midas_sweep.frozen_bars()` is the ONLY reader, checks the
file's SHA-256 against `configs/frozen_corpus.json`, and raises SystemExit on a hash or a
path it does not recognise. The last section here pins that boundary: the hash really is
checked, no default reaches it, and the venue's series is what the data of record holds.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import midas_parity as P  # noqa: E402
import midas_sweep as M  # noqa: E402
import mt5_tester_driver as T  # noqa: E402
from midas_prop.risk import news_calendar as NC  # noqa: E402

OFFSET = 120                      # the venue's offset from UTC, asserted for both windows
TICKCOV = P._window_spec("tickcov")


def _needs_data() -> None:
    """The VENUE's own series — the data of record, and the only corpus any window needs."""
    for name in ("XAUUSD_M15_upcomers.csv", "XAUUSD_H1_upcomers.csv"):
        if not os.path.exists(os.path.join(M.DATA_DIR, name)):
            pytest.skip(f"corpus {name} not present on this checkout")


def _needs_frozen() -> None:
    """The research series, which was DELETED on 2026-09-21 and is optional on a checkout.

    Tests that still compare against the actual bytes skip here rather than failing, because
    their absence is the intended state and not a fault of the machine running them — but they
    say how to restore it, so a skip can be turned into a real check in one command.
    """
    try:
        M.frozen_bars("XAUUSD_M15")
    except SystemExit as exc:
        pytest.skip(f"the research series is deleted (this is intended): {exc}")


def _bar_times(bars) -> set[int]:
    return {int(b["time"]) for b in bars}


def _legacy_venue_counts(offset_min: int, t0: int, t1: int):
    frozen = {int(b["time"]) for b in M.frozen_bars("XAUUSD_M15")}
    venue = _bar_times(P.venue_bars_utc("XAUUSD_M15", offset_min))
    return ({t for t in frozen if t0 <= t <= t1}, {t for t in venue if t0 <= t <= t1})


# --- the measured disagreement ----------------------------------------------------------

def test_the_two_corpora_disagree_about_bars_inside_the_tick_covered_window():
    """Not rounding: a real bar-set difference, and it is where the first divergence closed."""
    _needs_data()
    _needs_frozen()
    audit = P.corpus_alignment(OFFSET, TICKCOV["t0"], TICKCOV["t1"])
    assert audit["only_python"] > 0 and audit["only_venue"] > 0
    assert audit["python_bars"] != audit["venue_bars"]


def test_the_bar_that_explains_the_first_divergent_trade():
    """Python's series breaks at 18:15 and resumes at 00:00 on 2026-09-07; the venue's own
    holds the whole 22:00-23:45 evening. A 12-hour timeout opened at 08:45 therefore fires at
    22:15 on the venue's bars and at 00:15 on the other — 7,200 s apart, which is why the gap
    was read as the server offset rather than as two different markets."""
    _needs_data()
    _needs_frozen()
    legacy, venue = _legacy_venue_counts(OFFSET, TICKCOV["t0"], TICKCOV["t1"])

    def ts(y, m, d, hh, mm):
        return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp())

    even_2200 = ts(2026, 9, 7, 22, 0)
    assert even_2200 in venue and even_2200 not in legacy
    assert ts(2026, 9, 7, 22, 45) in venue, "the venue trades through the break python's file has"
    for hh, mm in ((18, 0), (18, 15)):
        assert ts(2026, 9, 7, hh, mm) in legacy and ts(2026, 9, 7, hh, mm) not in venue


def test_reading_the_venue_series_as_utc_needs_the_asserted_offset():
    """The shift is the corpus's clock, and the data is otherwise in the venue's frame."""
    _needs_data()
    raw = M.load_bars(os.path.join(M.DATA_DIR, "XAUUSD_M15_upcomers.csv"))
    shifted = P.venue_bars_utc("XAUUSD_M15", OFFSET)
    assert len(shifted) == len(raw)
    assert _bar_times(shifted) == {int(b["time"]) - OFFSET * 60 for b in raw}
    assert P.venue_bars_utc("XAUUSD_M15", 0)[0]["time"] - raw[0]["time"] == 0
    assert shifted[0]["time"] - raw[0]["time"] == -OFFSET * 60
    assert [b["close"] for b in shifted] == [b["close"] for b in raw], "prices are untouched"


def test_a_venue_corpus_without_an_offset_refuses():
    """Reading the venue's bars as UTC without the offset would mis-date every bar, which is
    the whole reason the corpus is the comparable one."""
    with pytest.raises(SystemExit) as e:
        P.python_build_data(corpus="venue")
    assert "needs the server offset" in str(e.value)
    with pytest.raises(SystemExit) as e:
        P.python_build_data(offset_min=OFFSET, corpus="nonsense")
    assert "unknown corpus" in str(e.value)
    with pytest.raises(TypeError):
        P.python_build_data(offset_min=OFFSET)      # no corpus and no default: it must refuse
        # (a default would hand a caller who merely forgot a silently different market)


def test_both_corpora_build_and_differ():
    """`legacy` is untouched — the certified numbers on it stay reproducible — and `venue` is
    a different series."""
    _needs_data()
    _needs_frozen()
    legacy = P.python_build_data(corpus="frozen")
    venue = P.python_build_data(offset_min=OFFSET, corpus="venue")
    assert len(legacy["m15"]) != len(venue["m15"])
    assert legacy["m15"][0]["time"] < venue["m15"][0]["time"]


# --- the refusal that keeps a cross-market comparison from being run ---------------------

def test_a_pass_whose_python_leg_is_on_another_market_is_refused(monkeypatch):
    """The guard, exercised where it matters: BEFORE the terminal is stopped, so the refusal
    costs nothing but is not skippable by a caller in a hurry.

    `corpus='frozen'` is passed EXPLICITLY because this window now declares `venue` itself:
    the case under test is the declaration being overridden, which is the shape a hurried
    re-run takes. The refusal has to fire on the override, not on the window name.
    """
    _needs_data()

    def _no_terminal(*a, **k):        # anything past the audit is a failure, not a pass
        raise AssertionError("the pass touched the terminal before the corpus audit")

    monkeypatch.setattr(P, "rotate_sandbox_ledgers", _no_terminal)
    monkeypatch.setattr(P.T, "run_pass", _no_terminal)
    with pytest.raises(SystemExit) as e:
        P.run_one_mode("REVERSE_DIRECTION", TICKCOV, "tickcov", {}, corpus="frozen")
    msg = str(e.value)
    assert "--corpus venue" in msg and "different market" in msg


def test_the_venue_corpus_is_accepted_for_the_same_window(monkeypatch):
    """The same window passes the audit once python reads the venue's own bars — the refusal
    is about the mismatch, not about the window."""
    _needs_data()
    reached = {}

    def _stop_here(tag, inputs, **k):
        reached["tag"] = tag
        raise RuntimeError("stop after the audit")

    monkeypatch.setattr(P.T, "run_pass", _stop_here)
    monkeypatch.setattr(P, "rotate_sandbox_ledgers", lambda: [])
    monkeypatch.setattr(P.T, "journal_snapshots", lambda: {})
    with pytest.raises(RuntimeError):
        P.run_one_mode("REVERSE_DIRECTION", TICKCOV, "tickcov", {}, corpus="venue")
    assert reached.get("tag") == f"{TICKCOV['tag']}_rd"


# --- the wf era: what this venue can and cannot serve -----------------------------------

def test_wf_as_declared_cannot_be_compared_and_says_so():
    """`wf` spans 2025-09-15..2026-03-31 and the venue's own history BEGINS 2026-01-12 (read
    from the terminal: first M15 bar 11:15 UTC, H1 11:00, H4 10:00). 7,752 of `wf`'s bars
    exist only in the legacy file, so there is no EA side to be walked through that span.
    The window is wrong to run, and it is refused rather than quietly mis-aligned."""
    _needs_data()
    wf = P._window_spec("wf")
    first = P.venue_bars_utc("XAUUSD_M15", wf["server_offset_min"])[0]["time"]
    assert first > wf["t0"], "the gap this test is about has closed — re-read the window"
    assert (first - wf["t0"]) / 86400 > 100
    _needs_frozen()
    audit = P.corpus_alignment(wf["server_offset_min"], wf["t0"], wf["t1"])
    assert audit["only_python"] > 7000, audit
    assert wf["corpus"] == "frozen", \
        "its evidence source is the retired archive, and it says so rather than defaulting"


def test_the_long_windows_are_declared_on_the_tick_model_they_can_run():
    """Both long windows reach back past 2026-09-04, so a `Model=4` declaration is not
    runnable — measured: the oos pass aborted with "declared Model=4 ... but ran on GENERATED
    ticks ... 156 day(s) of it ran on generated ticks". They declare `Model=1` instead, which
    makes them comparison-only: `recorded_verdict` demotes a key-matched PASS to REFUSED."""
    assert "1" not in T.REAL_TICK_MODEL_CODES
    for name in ("wfv", "oosc"):
        s = P._window_spec(name)
        assert s["model"] == "1" and s["corpus"] == "venue", name
        assert s["t0"] < int(datetime(2026, 9, 4, tzinfo=timezone.utc).timestamp()), name
        verdict, why = P.recorded_verdict(
            {"verdict": "PASS"}, {"declared": "1", "used": "generated", "evidence": "test"})
        assert verdict == "REFUSED" and "generated ticks" in why, name


def test_the_venue_covered_remainder_of_that_era_is_declared():
    """`wfv` is the same era restricted to what BOTH engines can be walked through: inside the
    venue's history, and on one side of the April DST step that makes anything longer
    un-clockable (Jan/Feb/Mar +60, April unresolvable)."""
    _needs_data()
    s = P._window_spec("wfv")
    assert s["corpus"] == "venue" and s["server_offset_min"] == 60
    assert P.assert_server_offset(s) == 60
    assert P.venue_bars_utc("XAUUSD_M15", 60)[0]["time"] <= s["t0"] + 86400, \
        "the window must start inside the venue's own history"
    off, stats = P.measure_server_offset_min(s["t0"], s["t1"])
    assert off == 60, (off, stats)
    assert set(stats) <= {"2026-01", "2026-02", "2026-03"}, stats
    assert "wfv" not in M.WINDOWS, \
        "it carries `iso` so the certified sweep's window list and G6 count do not move"
    assert P.corpus_alignment(60, s["t0"], s["t1"])["venue_bars"] > 5000


# --- the veto window ---------------------------------------------------------------------

def test_the_veto_window_is_declared_as_a_bar_comparison_not_a_certificate():
    """`Model=1` is a deliberate re-declaration: the venue's real ticks begin 2026-09-04, so a
    Model=4 pass over May is downgraded and refused. This window exists to compare the VETOED
    PATH at bar level, and `recorded_verdict` keeps it from ever being recorded as a pass."""
    spec = P._window_spec("veto")
    assert spec["model"] == "1" and "1" not in T.REAL_TICK_MODEL_CODES
    assert spec["corpus"] == "venue", "the window's whole point needs one market"
    assert spec["server_offset_min"] == 120
    assert T._tick_date(spec["dates"][0]) < T._tick_date("2026.09.04"), \
        "the re-declaration is required because the venue has no real ticks there"
    verdict, why = P.recorded_verdict(
        {"verdict": "PASS"},
        {"declared": "1", "used": "generated", "evidence": "test"})
    assert verdict == "REFUSED" and "generated ticks" in why


# --- one COST MODEL for both legs, from the same corpus ---------------------------------
#
# The corpus audit above makes both legs walk the same BARS. These pin the other half of the
# same contract: both legs must be charged the same COSTS on them. Measured 2026-09-21 — the
# file staged for the tester still held the legacy series' spreads (flat $0.15) while python
# charged the venue's recorded spread ($0.42) for the same bars, and `preflight` only ever
# asked whether the file existed. A $0.135 half-spread difference put a long's stop $0.136
# further from its fill, moved that stop's touch by 105 minutes, and pushed one TIMEOUT trade
# to |dR| 0.0102 — over the comparison's tolerance.

def test_the_staged_series_is_the_corpus_of_record_in_the_eas_own_frame(tmp_path):
    """The file's bar set IS the EA's BAR-mode membership filter, and its values ARE the cost
    model. Both come from the corpus this pass declared, keyed in the SERVER frame the EA
    looks a bar up in — `SpreadAt(iTime(...))`, where every epoch is the venue's."""
    _needs_data()
    bars = P.corpus_bars("venue", OFFSET)
    rows = P.spread_rows(bars, OFFSET)
    path = P.stage_spread_file(tmp_path, rows)
    assert path == tmp_path / "MQL5" / "Files" / P.SPREAD_FILE
    text = path.read_text(encoding="ascii")
    assert text.splitlines()[0] == "time,spread", "the EA's loader reads a header first"
    # one row per corpus bar, in server time, at the corpus's own dollar value (floored)
    assert {t for t, _ in rows} == {int(b["time"]) + OFFSET * 60 for b in bars}
    assert dict(rows) == {int(b["time"]) + OFFSET * 60:
                          round(max(float(b["spread"]), M.SPREAD_FLOOR), 5) for b in bars}
    assert P.verify_spread_file(tmp_path, rows) == []
    # and the frame is not cosmetic: the same bars read as UTC would be one offset out
    utc_rows = P.spread_rows(bars, 0)
    assert utc_rows != rows


def test_a_file_from_the_wrong_series_is_refused_bar_by_bar(tmp_path):
    """The exact defect, pinned: stage the LEGACY series' spreads, ask whether they are the
    VENUE corpus. They are not, and the blocker names the first bar that differs rather than
    reporting a general mismatch."""
    _needs_data()
    _needs_frozen()
    legacy = P.spread_rows(P.corpus_bars("frozen", OFFSET), OFFSET)
    venue = P.spread_rows(P.corpus_bars("venue", OFFSET), OFFSET)
    P.stage_spread_file(tmp_path, legacy)
    blockers = P.verify_spread_file(tmp_path, venue)
    assert blockers, "a file dumped from the other series must never pass as the corpus"
    assert "NOT the corpus of record" in blockers[0]
    assert "value(s) differ" in blockers[0] and "bar(s) missing" in blockers[0]
    assert "half-spreads" in blockers[0], "the blocker says which job the file does"
    # the two series really are different costs on the same window — that is the whole point
    assert dict(legacy) != dict(venue)
    shared = set(dict(legacy)) & set(dict(venue))
    assert shared and any(abs(dict(legacy)[t] - dict(venue)[t]) > 1e-9 for t in shared)


def test_ensure_restages_a_stale_file_and_then_verifies(tmp_path, capsys):
    """Derived, never trusted: a stale file is replaced from the declared corpus, and the
    harness says so instead of certifying whatever was on disk."""
    _needs_data()
    _needs_frozen()
    P.stage_spread_file(tmp_path, P.spread_rows(P.corpus_bars("frozen", OFFSET), OFFSET))
    assert P.ensure_spread_file(tmp_path, "venue", OFFSET) == []
    assert P.verify_spread_file(tmp_path, P.spread_rows(P.corpus_bars("venue", OFFSET), OFFSET)) == []
    out = capsys.readouterr().out
    assert "restaged" in out and "venue" in out
    # a second call finds it already correct: the fix is idempotent, not a rewrite each pass
    assert P.ensure_spread_file(tmp_path, "venue", OFFSET) == []
    assert "verified" in capsys.readouterr().out


def test_an_absent_spread_file_is_a_blocker_not_an_empty_series(tmp_path):
    """Absent must refuse. An empty file would read as "no bar exists here" — the EA skips
    every fill — which is a quietly different pass, not a missing file."""
    blockers = P.verify_spread_file(tmp_path, P.spread_rows([{"time": 1, "spread": 0.42}], OFFSET))
    assert len(blockers) == 1 and "no recorded spread file" in blockers[0]
    P.stage_spread_file(tmp_path, [])
    blockers = P.verify_spread_file(tmp_path, P.spread_rows([{"time": 1, "spread": 0.42}], OFFSET))
    assert blockers and "bar(s) missing" in blockers[0], "an empty series is not a pass"


def test_the_file_charges_exactly_what_the_engine_of_record_charges():
    """The identity the refusal protects, measured on the tick-covered window: for every
    trade the engine of record takes, the half-spread it charged equals the value the staged
    file hands the EA for that same bar. Two series would break this; one source satisfies it
    to the engine's own 4-dp rounding."""
    _needs_data()
    rows = dict(P.spread_rows(P.corpus_bars("venue", OFFSET), OFFSET))
    data = P.python_build_data(offset_min=OFFSET, corpus="venue")
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        res = M.run_mode(TICKCOV["mode"], TICKCOV["t0"], TICKCOV["t1"], data)
    finally:
        M._BASIS = prev
    assert res.trades, "no trades in this window — the identity would be untested"
    for t in res.trades:
        stop_d = t["risk_d"] / (t["lots"] * M.TICK_VALUE_PER_LOT)
        charged = t["spread_cost_r"] * stop_d          # recovered from the engine's own record
        assert rows[t["open_ct"] + OFFSET * 60] == pytest.approx(charged, abs=5e-3), t


def test_the_veto_window_contains_entries_the_stand_down_removes():
    """The reason the window exists: an entry the +/-15-minute stand-down takes away. If this
    ever stops being true the window is no longer a veto path and must be re-chosen.

    RE-MEASURED 2026-09-21, because two corrections moved this window's entry set: it is now
    declared on the `venue` corpus, and the H4 derivation follows the venue's own grid. On
    that contract the stand-down refuses 2 signals and removes exactly one entry, 2026-05-14
    19:45 UTC. The earlier pin (05-12 20:00 among the removals) was measured on the legacy
    corpus and no longer describes what this window runs; pinning a stale instant as if it
    were the rule is how a passing test stops meaning anything.

    Nothing is ADDED by switching the gate on — a refused entry must not move the strategy to
    different bars, which is what would make this a different bet rather than a veto.
    """
    _needs_data()
    spec = P._window_spec("veto")
    data = P.python_build_data(offset_min=P.assert_server_offset(spec), corpus="venue")
    # The FROZEN snapshot, which is what the pass itself reads. It used to read
    # `news_calendar_path()` — the LIVE rolling file the attached EA refreshes — so this
    # pin was quietly testing whatever the arm's last refresh happened to cover. Measured
    # 2026-09-21 17:52Z: that refresh narrowed the live file to 2026-09-09..2026-10-09 and
    # this test (and every replay of the window) lost its news events entirely.
    cal = NC.read_calendar(P.frozen_news_source())
    events = NC.top_tier_events(cal)
    prev_basis, prev_news = M._BASIS, M._NEWS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        M.use_news(None)
        off = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
        M.use_news(events)
        on = M.run_mode(spec["mode"], spec["t0"], spec["t1"], data)
    finally:
        M._BASIS = prev_basis          # the module global, restored as it was found
        M.use_news(prev_news)
    _f = lambda ct: datetime.fromtimestamp(ct, timezone.utc).strftime("%Y-%m-%d %H:%M")
    a = {t["open_ct"] for t in off.trades}
    b = {t["open_ct"] for t in on.trades}
    removed = {_f(ct) for ct in a - b}
    added = {_f(ct) for ct in b - a}
    assert on.news_vetoed > 0, "the stand-down refused nothing — the window is not a veto path"
    assert removed == {"2026-05-14 19:45"}, sorted(removed)
    assert not added, f"the gate changed which bars are traded, not just how many: {sorted(added)}"


# --- the retirement of the duplicate series ---------------------------------------------

def test_the_data_of_record_holds_the_venue_series_and_not_the_retired_one():
    """The duplicate is gone from where forward-looking code reads, not just relabelled.

    This is the whole point of the retirement: `data/forex/xauusd/` held a series that was
    fetched from a terminal whose account no longer trades this symbol, next to the venue's
    own, both named `XAUUSD_M15.csv`-style, and a caller that picked the wrong one produced a
    pass that looked plausible for a day. Now there is one series there and it is the one the
    EA trades.
    """
    _needs_data()
    for name in ("XAUUSD_M15.csv", "XAUUSD_H1.csv", "XAUUSD_D1.csv"):
        assert not os.path.exists(os.path.join(M.DATA_DIR, name)), (
            f"{name} is back in the data of record — the retired series must only be read "
            f"through frozen_bars() from {M.FROZEN_DIR}")
    for name in ("XAUUSD_M15_upcomers.csv", "XAUUSD_H1_upcomers.csv"):
        assert os.path.exists(os.path.join(M.DATA_DIR, name)), (
            f"the venue's own series {name} is the data of record and is missing")


def test_the_archive_lives_where_nothing_reads_it_by_default():
    """The archive is a separate directory, and it is not the one any default points at."""
    assert Path(M.FROZEN_DIR).resolve() != Path(M.DATA_DIR).resolve()
    assert not Path(M.FROZEN_DIR).resolve().is_relative_to(Path(M.DATA_DIR).resolve())
    assert M.DATA_DIR not in M.FROZEN_DIR, (
        "the archive must not sit under the data of record, or a directory walk of the data "
        "of record finds it again")


def _fake_series(tmp_path, monkeypatch, body: bytes = None):
    """A miniature archive + manifest of our own, so the hash pin is tested without the bytes.

    The mechanism (verify SHA-256 against the manifest, refuse on mismatch, refuse on absence)
    is the thing that has to keep working now that the real series is deleted — and it is the
    same mechanism a restore depends on. Building the fixture here means these tests never skip.
    """
    body = body if body is not None else (b"time,iso,open,high,low,close,tick_volume,spread\n"
                                         b"1,1970-01-01T00:00:01+00:00,1,1,1,1,1,1\n")
    d = tmp_path / "frozen_corpus"
    d.mkdir(parents=True, exist_ok=True)
    (d / "XAUUSD_M15.csv").write_bytes(body)
    manifest = {"status": "deleted", "files": {"XAUUSD_M15.csv": {
        "sha256": hashlib.sha256(body).hexdigest(), "bars": 1, "first_utc": "x",
        "last_utc": "x", "fetched_from": "test fixture"}}}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(M, "FROZEN_DIR", str(d))
    monkeypatch.setattr(M, "FROZEN_MANIFEST", str(mp))
    return d / "XAUUSD_M15.csv"


def test_the_hash_pin_refuses_an_edited_restore_and_accepts_an_exact_one(tmp_path, monkeypatch):
    """A hash pin, exercised by really tampering with bytes rather than asserted about.

    This is what makes a restore from git trustworthy: the bytes either are the ones the
    numbers were computed on or the loader refuses them. A series that can be edited silently
    is not a pinned series, and a citation from an edited file describes something else.
    """
    src = _fake_series(tmp_path, monkeypatch)
    raw = src.read_bytes()
    cut = len(raw) - 3                      # one traded byte: the smallest edit that is an edit
    src.write_bytes(raw[:cut] + bytes([raw[cut] ^ 0x01]) + raw[cut + 1:])
    with pytest.raises(SystemExit) as exc:
        M.frozen_bars("XAUUSD_M15")
    msg = str(exc.value)
    assert "pinned hash" in msg and "pinned" in msg and "found" in msg
    src.write_bytes(raw)                     # the exact bytes load again
    assert M.frozen_bars("XAUUSD_M15")[0]["spread"] == 0.01


def test_the_reader_says_the_series_was_deleted_and_how_to_restore_it(tmp_path, monkeypatch):
    """Absent must refuse with a map that exists: the deletion, a commit to restore from, the
    restore command itself, and the document that lists what stopped being checkable."""
    monkeypatch.setattr(M, "FROZEN_DIR", str(tmp_path / "nope"))
    with pytest.raises(SystemExit) as exc:
        M.frozen_bars("XAUUSD_M15")
    msg = str(exc.value)
    assert "NOT PRESENT" in msg and M.FROZEN_DIR in msg
    assert "DELETED" in msg and "intended state" in msg, (
        "a missing archive must read as a decision, not as a fault to be fixed by fetching")
    assert "git checkout 248db66" in msg, "the restore is one command and it must be in the message"
    doc = "docs/FROZEN_CORPUS_20260921.md"
    assert doc in msg and os.path.exists(os.path.join(REPO, doc)), (
        f"the refusal points at {doc}, which must exist")
    assert "is NOT the data of record" in msg, "and it must say what IS"


def test_the_deletion_is_recorded_and_verifiable_without_the_bytes():
    """The bytes are gone on purpose; the RECORD of them is not. A deletion that cannot be
    checked against anything is just an absence, so the manifest keeps every file's hash,
    size, span and provenance, names the commit it last existed in, lists what stopped being
    checkable, and the working tree really is empty."""
    with open(os.path.join(REPO, M.FROZEN_MANIFEST)) as fh:
        manifest = json.load(fh)
    assert manifest["status"] == "deleted", "the manifest still claims the series is kept"
    assert manifest["deleted_on"] == "2026-09-21"
    assert manifest["last_existed_in_commit"], "a restore needs a commit to restore from"
    assert manifest["why_deleted"], "a deletion without its reason is an accident"
    assert manifest["citations_that_stop_being_checkable"], (
        "the whole point of recording this: name what can no longer be re-checked")
    for name, rec in manifest["files"].items():
        for key in ("sha256", "bytes", "bars", "first_utc", "last_utc", "fetched_from"):
            assert rec.get(key), f"{name} has no {key} — a restore could not be verified"
        assert len(rec["sha256"]) == 64
    # the reason this retirement happened at all, kept as a number rather than as a story
    assert manifest["measured_disagreement"]["only_research_series"] == 3
    assert manifest["measured_disagreement"]["only_venue"] == 18
    for name in manifest["files"]:
        assert not os.path.exists(os.path.join(M.FROZEN_DIR, name)), (
            f"{name} is back in {M.FROZEN_DIR} — if that was a restore, say so in the manifest "
            f"(status must go back to a kept state and the hashes must verify)")
    on_disk = {n for n in os.listdir(M.FROZEN_DIR) if n.endswith(".csv")} if os.path.isdir(M.FROZEN_DIR) else set()
    assert on_disk == set(), f"the archive directory still holds {sorted(on_disk)}"
    # and the venue series — the one that must still be here — is described as the replacement
    assert manifest["superseded_by"].startswith("data/")
    assert manifest["what_it_is_not"], "the disqualifiers stay: a reader will still want to trade it"


def test_no_window_runs_on_the_archive_unless_it_declares_it(monkeypatch):
    """Two properties at once, both about defaults.

    Every window declares its corpus — there is no implicit one to inherit — and the venue
    path never touches the archive at all, so a forward-looking pass cannot be silently fed
    the retired series by a broken lookup. The archive is made to raise here: if `venue` needs
    it, this test fails instead of the pass quietly changing market.
    """
    _needs_data()
    for name, spec in P.WINDOW_SPECS.items():
        assert spec.get("corpus") in ("frozen", "venue"), (
            f"window {name} declares no corpus — there is no default to inherit: {spec!r}")

    def _boom(_stem):
        raise SystemExit("the venue path must not read the archive")
    monkeypatch.setattr(M, "frozen_bars", _boom)
    bars = P.corpus_bars("venue", OFFSET)
    assert bars and bars[0]["time"] < bars[-1]["time"]
    # and an undeclared corpus is refused rather than defaulted
    with pytest.raises(SystemExit) as exc:
        P.corpus_bars("anything-else", OFFSET)
    assert "unknown corpus" in str(exc.value)


def test_the_walk_forward_verdict_never_depended_on_the_archive():
    """A claim that was made wrongly once, so it is pinned to the code rather than to a memory.

    The natural reading of "the frozen artifact" is `artifacts/gold_wfo.json` and the verdict
    in docs/GOLD_WFO_VERDICT_20260919.md, and the first draft of
    docs/FROZEN_CORPUS_20260921.md listed both as computed on the retired series. They are not:
    `gold_walkforward.py` loads its bars from the terminal (`mt5_data.load_m5`) at run time, so
    the walk-forward numbers are VENUE-corpus numbers. This test fails if that ever stops being
    true (the file starts reading the archive) or if the manifest starts claiming it.
    """
    src = (REPO / "scripts" / "gold_walkforward.py").read_text(encoding="utf-8")
    assert "frozen_bars" not in src and "FROZEN_DIR" not in src, (
        "gold_walkforward.py started reading the research series — the walk-forward verdict "
        "is a venue-corpus number and every citation of it assumes that")
    assert "load_m5" in src, "it must be reading the terminal's own history"
    with open(os.path.join(REPO, M.FROZEN_MANIFEST)) as fh:
        manifest = json.load(fh)
    cited = json.dumps(manifest["citations_that_stop_being_checkable"])
    assert "gold_wfo" not in cited and "GOLD_WFO_VERDICT" not in cited, (
        "the manifest lists the walk-forward verdict as depending on the deleted series; it "
        "does not — it reads the terminal")
    assert "gold_wfo" in manifest["not_affected_note"], (
        "the manifest must NAME the non-dependency explicitly, or the next reader re-makes "
        "the same inference")
    assert "midas_sweep" in cited, "and it must name what really did come from the series"


def test_the_sweep_says_which_series_it_is_defined_on():
    """The sweep still runs on the archive — its arithmetic is defined there — so its own
    docstring must say so instead of pointing at the data of record it no longer reads."""
    with open(os.path.join(REPO, "scripts", "midas_sweep.py"), encoding="utf-8") as fh:
        head = fh.read(4000)
    assert "data/forex/xauusd/XAUUSD_{H1,M15}.csv" not in head, (
        "the sweep's header still names the retired paths as the data of record")
    assert "frozen_bars" in head and "archive" in head
    assert "data of record" in head.lower(), (
        "the sweep's header must say which series it reads as the input of record, and which "
        "one its own arithmetic is defined on")
    assert "_upcomers" in head, "and it must name the venue series it now reads"
