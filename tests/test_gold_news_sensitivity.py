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

... AND THE TWO THINGS THAT MAKE THE ANSWER SURVIVABLE, which the second half of this file
pins. An extended window cannot be checked against the frozen artifact at all, so the
harness must DECLARE the control inapplicable rather than quietly skip it -- and an
amendment that re-selects the grid's configuration is a different strategy, so the
expectation is written down BEFORE the amended leg runs and the run is judged by it.
"""
from __future__ import annotations

import json
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


# --- the pre-registration --------------------------------------------------------------
#
# The veto is applied while the walk-forward SELECTS, so it can change which configuration
# the grid picks -- which the sensitivity run showed it doing in one fold. A strategy change
# cannot be accepted on the strength of the window that certified the unamended strategy,
# so the expectation has to be written down before the amended leg is computed.

def _frozen_artifact(tmp_path, *, name="frozen.json", checks=None, total=1.0, t=0.5,
                     last="2026-09-18T22:45:00+00:00", oos_trades=5,
                     per_fold=(0.5,)) -> Path:
    """A complete frozen artifact, because the harness reads more of it than it reads of
    the legs: the digest hashes its spec and checks, and the declaration quotes its stats."""
    p = tmp_path / name
    p.write_text(json.dumps({
        "data": {"first": "2026-01-12T13:15:00+00:00", "last": last},
        "spec": {"control_reps": 1},
        "checks": {"V1 total>0": True} if checks is None else checks,
        "stats": {"_total": total, "_median": 0.0, "_t": t},
        "oos_trades": oos_trades, "control_total_r": -1.0,
        "oos_r_per_fold": list(per_fold),
    }), encoding="utf-8")
    return p


def test_the_declaration_is_written_before_any_leg_is_computed(tmp_path, capsys):
    """The ordering IS the guarantee. The run below is stopped at the calendar check, one
    step after the declaration and before either leg -- so the file existing now is proof
    it did not depend on the result it will judge."""
    prereg = tmp_path / "prereg.json"
    with pytest.raises(SystemExit) as e:
        G.main(["--frozen", str(_frozen_artifact(tmp_path)),
                "--calendar", str(tmp_path / "nope.csv"),
                "--preregister", str(prereg)])
    assert "no calendar" in str(e.value)
    assert "declaration WRITTEN" in capsys.readouterr().out
    d = json.loads(prereg.read_text(encoding="utf-8"))
    assert set(d["decision_rule"]) >= {"P1", "P2", "P3", "ACCEPT", "REJECT"}
    assert d["protocol_digest"] and "declared_utc" in d
    assert "runs" not in d, "a declaration that carries a result was not declared first"


def test_a_declaration_whose_protocol_moved_is_refused_not_reinterpreted(tmp_path):
    """The failure mode: a standing declaration and a protocol quietly changed under it,
    which would make the declared expectation about a different experiment."""
    prereg = tmp_path / "prereg.json"
    prereg.write_text(json.dumps({"declared_utc": "2026-09-21T00:00:00+00:00",
                                  "protocol_digest": "deadbeef", "runs": []}),
                      encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        G.main(["--frozen", str(_frozen_artifact(tmp_path)),
                "--preregister", str(prereg)])
    assert "REFUSING" in str(e.value) and "protocol moved" in str(e.value)
    assert json.loads(prereg.read_text(encoding="utf-8"))["protocol_digest"] == "deadbeef"


def test_the_digest_pins_the_code_and_the_grid_not_only_the_frozen_file(tmp_path,
                                                                        monkeypatch):
    """A pre-registration is worth nothing if it only covers the artifact: the grid, the
    fold structure and the cost model are what the expectation is about."""
    a = _frozen_artifact(tmp_path, name="a.json", checks={"V1 total>0": True})
    b = _frozen_artifact(tmp_path, name="b.json", checks={"V1 total>0": False})
    fa, fb = json.loads(a.read_text()), json.loads(b.read_text())
    assert G.protocol_digest(fa) == G.protocol_digest(fa), "a reset digest is not a pin"
    assert G.protocol_digest(fa) != G.protocol_digest(fb)
    base = G.protocol_digest(fa)
    monkeypatch.setattr(G.W, "FOLD_DAYS", G.W.FOLD_DAYS + 1)
    assert G.protocol_digest(fa) != base, "the fold structure is part of the protocol"

def test_the_digest_hashes_the_protocol_source(tmp_path, monkeypatch):
    """Changing the harness or the walk-forward it imports must invalidate a declaration,
    or the pin covers the parameters and not the implementation."""
    src = tmp_path / "scripts"
    src.mkdir()
    (src / "gold_walkforward.py").write_text("grid", encoding="utf-8")
    (src / "gold_news_sensitivity.py").write_text("harness", encoding="utf-8")
    monkeypatch.setattr(G, "ROOT", tmp_path)
    frozen = {"spec": {}, "checks": {}}
    before = G.protocol_digest(frozen)
    (src / "gold_news_sensitivity.py").write_text("harness ", encoding="utf-8")
    assert G.protocol_digest(frozen) != before
    assert len(before) == 64      # sha-256 hexdigest


# --- the decision rule, applied to the result -------------------------------------------

def test_p1_fails_when_the_selection_changes():
    """The rule that matters. A pick change means the amendment altered the strategy's own
    search, so the configuration that beat the grid is not the certified one."""
    verdict, failed = G.prereg_verdict(["F04"], {"V1 total>0": True}, {"V1 total>0": True},
                                       +3.36)
    assert verdict == "REJECTED"
    assert failed and failed[0].startswith("P1") and "F04" in failed[0]


def test_all_three_conditions_holding_is_the_only_accept():
    assert G.prereg_verdict([], {"V1 total>0": True}, {"V1 total>0": True}, +3.36) == \
        ("INERT-ACCEPTABLE", [])


def test_p2_refuses_a_lost_leg_and_p3_refuses_a_cost():
    """A rule that removes a pass, or costs R on the window that certified the strategy,
    is not inert. Both are reported separately so the operator can tell which happened."""
    verdict, failed = G.prereg_verdict([], {"V1 total>0": True, "V4 beats control": True},
                                       {"V1 total>0": False, "V4 beats control": True}, +1.0)
    assert verdict == "REJECTED" and any(f.startswith("P2") for f in failed)
    assert "V1 total>0" in " ".join(failed)
    verdict, failed = G.prereg_verdict([], {"V1 total>0": True}, {"V1 total>0": True}, 0.0)
    assert verdict == "REJECTED" and len(failed) == 1 and failed[0].startswith("P3")


def test_the_failures_are_reported_in_the_order_they_are_named():
    verdict, failed = G.prereg_verdict(["F04"], {"V1 total>0": True},
                                       {"V1 total>0": False}, -2.0)
    assert verdict == "REJECTED"
    assert [f[:2] for f in failed] == ["P1", "P2", "P3"]


# --- which folds carry the delta --------------------------------------------------------

def test_fold_attribution_is_exact_and_names_only_the_folds_that_moved():
    """`total - d_i` is exact because the total is the sum of the per-fold R, so this
    separates "the rule moved the window" from "the rule moved one eight-day fold"."""
    picks = [{"fold": "F01", "config": "a"}, {"fold": "F02", "config": "b"},
             {"fold": "F03", "config": "c"}]
    movers = G.fold_attribution(picks, [1.0, 2.0, 3.0], [1.0, 4.0, 2.0], 1.0)
    assert [m["fold"] for m in movers] == ["F02", "F03"]
    assert movers[0]["contribution_r"] == pytest.approx(2.0)
    assert movers[0]["total_without_fold_r"] == pytest.approx(-1.0)
    assert movers[1]["contribution_r"] == pytest.approx(-1.0)
    assert movers[1]["total_without_fold_r"] == pytest.approx(2.0)


def test_a_single_fold_can_carry_more_than_the_whole_delta():
    """The measured shape: drop F04 and the total flips sign. A share above 100% is not a
    bug in the arithmetic, it is the finding -- so it must be representable, not clipped."""
    picks = [{"fold": "F01", "config": "a"}, {"fold": "F02", "config": "b"}]
    movers = G.fold_attribution(picks, [1.0, 2.0], [1.5, 0.5], -1.0)
    share = max(abs(m["contribution_r"]) for m in movers) / abs(-1.0)
    assert share > 1.0
    assert {m["fold"] for m in movers} == {"F01", "F02"}


def test_no_move_is_reported_as_no_move():
    picks = [{"fold": "F01", "config": "a"}]
    assert G.fold_attribution(picks, [2.0], [2.0], 0.0) == []


# --- the extension: a new window, and a control that cannot apply -----------------------

GEN_FAKE = 1_790_000_000
FAKE_LAST = GEN_FAKE - M15          # the corpus's own last bar


def _stub_leg(rs, total, trades, control, configs=("a", "b")):
    return {"folds": [("F01", 0, 1), ("F02", 1, 2)],
            "picks": [{"fold": f"F{i + 1:02d}", "config": c}
                      for i, c in enumerate(configs)],
            "oos_rs": list(rs),
            "checks": {"V1 total>0": total > 0, "_total": total, "_median": 0.0,
                       "_t": 0.5},
            "control_total": control, "oos_trades": trades, "oos_detail": [],
            "trades_by_cfg": [], "all_cfgs": [], "entry_bars": set()}


def _run_extension(tmp_path, monkeypatch, capsys, *, prereg=None, out="a.json"):
    """An end-to-end run on a fake corpus that is NEWER than the frozen artifact.

    Everything below the corpus is stubbed, so what is tested is the harness's own
    bookkeeping: the fold inventory, the control's declared inapplicability, and the
    pre-registered verdict -- not the walk-forward, which is tested by running it.
    """
    frozen = _frozen_artifact(tmp_path, last="2026-01-20T00:00:00+00:00", per_fold=(0.5, 1.0))
    epoch = np.array([FAKE_LAST - (599 - i) * M15 for i in range(600)], dtype=float)
    off = _stub_leg([1.0, 2.0], 3.0, 5, -1.0)
    on = _stub_leg([1.5, 0.5], 2.0, 4, -0.5)
    monkeypatch.setattr(G, "corpus", lambda symbol, last: ({"epoch": epoch}, None, None, None))
    monkeypatch.setattr(G, "leg",
                        lambda B, atr, hours, flags, blackout, reps: off if blackout is None else on)
    monkeypatch.setattr(G, "signal_census",
                        lambda *a, **k: {"signal_bars": 10, "signal_bars_in_blackout": 1})
    cal = _write_calendar(tmp_path / "c.csv", generated=GEN_FAKE, window_to=GEN_FAKE + 86400,
                          declared=1, rows=[(BASE + 60, "HIGH")])
    argv = ["--frozen", str(frozen), "--calendar", str(cal), "--control-reps", "1",
            "--corpus-end", "now", "--out", str(tmp_path / out)]
    if prereg is not None:
        argv += ["--preregister", str(prereg)]
    assert G.main(argv) == 0
    return json.loads((tmp_path / out).read_text(encoding="utf-8")), capsys.readouterr().out


def test_the_extension_declares_the_control_inapplicable_instead_of_skipping_it(
        tmp_path, monkeypatch, capsys):
    """A correlation check against an artifact computed on other bars is impossible, and
    saying so is the point: a silently skipped control is indistinguishable from one that
    passed. The veto-off leg is still the reference -- same code, same bars, one difference."""
    art, out = _run_extension(tmp_path, monkeypatch, capsys)
    assert "CONTROL  : N/A for --corpus-end now" in out
    assert art["spec"]["corpus_end"] == "now"
    assert art["spec"]["reproduced_frozen"] is False
    assert art["spec"]["bars_added_vs_frozen"] == 600
    assert art["spec"]["new_folds"] == 1, "the extension reports whether it added evidence"
    # One fold carries 150% of the delta: the shape the superset window has to be able to
    # report, because it is the shape the frozen one actually has.
    assert art["fold_attribution"]["share_of_delta_in_largest_mover"] == pytest.approx(1.5)
    assert art["delta"]["total_r"] == pytest.approx(-1.0)


def test_the_frozen_run_reproduces_the_artifact_and_claims_no_extension(
        tmp_path, monkeypatch, capsys):
    """The control's positive path, end to end: the veto-off leg matches the artifact on
    every field the harness checks, so the delta is attributable -- and the run does not
    announce a failed extension, because it was never attempting one."""
    frozen_last = int(datetime.fromisoformat("2026-09-18T22:45:00+00:00").timestamp())
    epoch = np.array([frozen_last - (599 - i) * M15 for i in range(600)], dtype=float)
    frozen = _frozen_artifact(tmp_path, total=3.0, per_fold=(1.0, 2.0))
    cal = _write_calendar(tmp_path / "c.csv", generated=GEN_FAKE,
                          window_to=GEN_FAKE + 86400, declared=1,
                          rows=[(BASE + 60, "HIGH")])
    monkeypatch.setattr(G, "corpus", lambda symbol, last: ({"epoch": epoch}, None, None, None))
    monkeypatch.setattr(G, "leg",
                        lambda B, atr, hours, flags, blackout, reps: _stub_leg([1.0, 2.0], 3.0, 5, -1.0))
    monkeypatch.setattr(G, "signal_census",
                        lambda *a, **k: {"signal_bars": 10, "signal_bars_in_blackout": 1})
    assert G.main(["--frozen", str(frozen), "--calendar", str(cal), "--control-reps", "1",
                   "--out", str(tmp_path / "f.json")]) == 0
    out = capsys.readouterr().out
    assert "CONTROL  : veto-off reproduces" in out
    assert "folds: 1" in out
    assert "NO new complete fold" not in out, "the certified window is not an attempt at one"
    art = json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))
    assert art["spec"]["reproduced_frozen"] is True
    assert art["spec"]["corpus_end"] == "frozen"


def test_the_extension_refuses_when_the_corpus_holds_no_newer_bars(tmp_path, monkeypatch):
    """`--corpus-end now` on a corpus that has not advanced is not an extension; it is the
    frozen window wearing a different label, and the harness must not report it as one."""
    frozen_last = int(datetime.fromisoformat("2026-09-18T22:45:00+00:00").timestamp())
    epoch = np.array([frozen_last - (599 - i) * M15 for i in range(600)], dtype=float)
    frozen = _frozen_artifact(tmp_path)
    # A usable calendar, so the refusal under test is the corpus one and not the source one.
    cal = _write_calendar(tmp_path / "c.csv", generated=GEN_FAKE,
                          window_to=GEN_FAKE + 86400, declared=1,
                          rows=[(BASE + 60, "HIGH")])
    monkeypatch.setattr(G, "corpus", lambda symbol, last: ({"epoch": epoch}, None, None, None))
    with pytest.raises(SystemExit) as e:
        G.main(["--frozen", str(frozen), "--calendar", str(cal), "--corpus-end", "now"])
    assert "no newer bars" in str(e.value)


def test_a_run_is_appended_to_the_declaration_and_never_overwrites_it(
        tmp_path, monkeypatch, capsys):
    """Two runs, one declaration: the declared time and digest must survive the second run,
    or the record no longer says what was declared before the first one."""
    prereg = tmp_path / "prereg.json"
    art, out = _run_extension(tmp_path, monkeypatch, capsys, prereg=prereg, out="one.json")
    assert "pre-registered verdict: REJECTED" in out
    assert art["spec"]["preregistration"]["verdict"] == "REJECTED"
    first = json.loads(prereg.read_text(encoding="utf-8"))
    assert len(first["runs"]) == 1 and first["runs"][0]["delta_total_r"] == pytest.approx(-1.0)
    _run_extension(tmp_path, monkeypatch, capsys, prereg=prereg, out="two.json")
    second = json.loads(prereg.read_text(encoding="utf-8"))
    assert len(second["runs"]) == 2
    assert second["declared_utc"] == first["declared_utc"]
    assert second["protocol_digest"] == first["protocol_digest"]
    assert second["runs"][0] == first["runs"][0]
