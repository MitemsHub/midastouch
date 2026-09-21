"""A tester pass must be refused when it ran on different ticks than it declared.

WHY THIS EXISTS. On 2026-09-20 the parity harness ran the `wf` window and the tester
answered, in passing:

    Ticks: XAUUSD : 2026.01.14 - 2026.04.03  no real ticks, every tick generation used

The INI had asked for `Model=4` — "every tick based on real ticks" — and the report's
own header read `History Quality: 0% real ticks`. Nothing failed. The pass was parsed,
compared, and written to an artifact as though it were the real-tick evidence the
program's per-tick parity model needs.

THE SAME DAY, THE SAME DEFECT IN A SHARPER FORM. The `oos` pass (2026.04.01 →
2026.09.18) declared `Model=4` and the agent answered:

    Ticks: XAUUSD : real ticks begin from 2026.09.04 00:00:00

Five of that window's five and a half months were fabricated, and the guard did NOT
refuse it: the evidence regex `\\breal ticks\\b` matched the words "real ticks" inside
a line whose meaning is the opposite of full coverage. The guard returned REAL for a
pass that was ~96% generated. That is the hole these tests now close — a
partial-coverage statement is judged against the window the pass itself declared, and
without that window it is not a certification.

The terminal is entitled to downgrade the request: it does so when the local tick
cache does not cover the window. What is not acceptable is the downgrade going
unnoticed, because it silently changes what the run *proves*. These tests pin the
refusal, the window comparison, and the belt-and-braces rule that a comparison cannot
be RECORDED as a pass on anything but the ticks it declared.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import mt5_tester_driver as T  # noqa: E402
import midas_parity as P  # noqa: E402

#: The real journal line, 2026-09-20 (`wf` pass). Kept verbatim: this is the failure
#: being fixed.
REAL_DOWNGRADE_LINE = (
    "Ticks: XAUUSD : 2026.01.14 - 2026.04.03  no real ticks, every tick generation used"
)
#: The real journal line, 2026-09-20 (`oos` pass) — the one that got through, because
#: "real ticks" appears in a sentence about where coverage BEGINS.
REAL_PARTIAL_LINE = "Ticks: XAUUSD : real ticks begin from 2026.09.04 00:00:00"
#: The window that pass declared (the harness's FromDate for the `oos` window).
OOS_WINDOW_FROM = "2026.04.01"
#: A day-level gap statement: real ticks existed, but not for these bars.
REAL_ABSENT_LINE = (
    "Ticks: Volatility 75 Index : 2026.01.14- real ticks absent for 20 minutes of "
    "128138 total minute bars, every tick generation used"
)
#: The tester's module line. Written for a covered run AND for a partial one.
GENERATING_FROM_REAL_LINE = "Tester: XAUUSD,M15 (Upcomers-Server): generating based on real ticks"
REAL_TICKS_LINE = "Ticks: XAUUSD : 2026.04.01 - 2026.09.18  real ticks"


class TestDetection:
    def test_the_real_downgrade_line_is_read_as_generated(self):
        verdict, why = T.detect_tick_model(REAL_DOWNGRADE_LINE, "")
        assert verdict == "generated"
        assert "journal" in why

    def test_the_real_partial_coverage_line_is_read_as_generated(self):
        """The 2026-09-20 `oos` line: coverage began 150 days into the window."""
        verdict, why = T.detect_tick_model(REAL_PARTIAL_LINE, "", OOS_WINDOW_FROM)
        assert verdict == "generated", (
            "a window whose ticks begin 2026.09.04 was certified on generated ticks")
        assert "2026.09.04" in why and OOS_WINDOW_FROM in why
        assert "generated" in why

    def test_partial_coverage_of_a_window_that_starts_later_is_real(self):
        """If the cache reaches the window's own start, the pass did get its ticks."""
        verdict, why = T.detect_tick_model(REAL_PARTIAL_LINE, "", "2026.09.04")
        assert verdict == "real"
        assert "at or before the window start" in why

    def test_partial_coverage_without_a_declared_window_is_never_a_pass(self):
        """Fail closed: an uncompared partial statement cannot be shown to cover it."""
        verdict, why = T.detect_tick_model(REAL_PARTIAL_LINE, "")
        assert verdict == "generated"
        assert "no window start was declared" in why

    def test_a_day_level_absence_is_generated(self):
        assert T.detect_tick_model(REAL_ABSENT_LINE, "", OOS_WINDOW_FROM)[0] == "generated"

    def test_generation_used_alone_is_generated(self):
        """The phrase can appear without "no real ticks" (the minutes-absent shape)."""
        verdict, _ = T.detect_tick_model(
            "XAUUSD : 2026.01.14 - 2026.04.03 real ticks absent for 20 minutes, "
            "every tick generation used", "", OOS_WINDOW_FROM)
        assert verdict == "generated"

    def test_the_tester_module_line_is_not_a_certification(self):
        """"generating based on real ticks" states the tester's SOURCE, not coverage."""
        verdict, why = T.detect_tick_model(GENERATING_FROM_REAL_LINE, "")
        assert verdict != "real", "the module line was read as proof this window had ticks"
        assert verdict == "unknown"

    def test_a_real_tick_line_is_read_as_real(self):
        verdict, _ = T.detect_tick_model(REAL_TICKS_LINE, "")
        assert verdict == "real"

    def test_the_report_is_the_fallback_when_the_journal_is_quiet(self):
        """'no real ticks' must win over a bare 'real ticks' match inside it."""
        assert T.detect_tick_model("", "History Quality: 0% real ticks")[0] == "generated"
        assert T.detect_tick_model("", "History Quality: 100% real ticks")[0] == "real"

    def test_a_partial_real_tick_coverage_is_generated_not_a_pass(self):
        """99% is not 100%: a per-tick comparison on 1% fabricated ticks is not equal."""
        assert T.detect_tick_model("", "History Quality: 99% real ticks")[0] == "generated"

    def test_silence_is_unknown_never_real(self):
        """Not knowing is not the same as knowing it was fine."""
        verdict, why = T.detect_tick_model("", "")
        assert verdict == "unknown"
        assert "no tick-model statement" in why

    def test_the_downgrade_is_preferred_over_a_quality_column(self):
        """When the journal states the substitution, that is the verdict."""
        verdict, why = T.detect_tick_model(REAL_DOWNGRADE_LINE, "History Quality: 100% real ticks")
        assert verdict == "generated"
        assert "journal" in why

    def test_the_partial_line_is_preferred_over_the_report_column_too(self):
        """A journal that says where coverage starts outranks a summary percentage."""
        verdict, _ = T.detect_tick_model(REAL_PARTIAL_LINE, "History Quality: 100% real ticks",
                                         OOS_WINDOW_FROM)
        assert verdict == "generated"


class TestRefusal:
    """The check is about a REQUEST BEING HONOURED, not about which model is best."""

    @staticmethod
    def _stub(monkeypatch, journal: str, report: str) -> None:
        monkeypatch.setattr(T, "appended_text", lambda snaps: journal)
        monkeypatch.setattr(T, "report_text", lambda tag: report)

    def test_a_declared_real_tick_pass_that_ran_generated_is_refused(self, monkeypatch):
        self._stub(monkeypatch, REAL_DOWNGRADE_LINE, "History Quality: 0% real ticks")
        with pytest.raises(T.TickModelMismatch) as exc:
            T.assert_declared_tick_model({}, "midas_wf_rd_rd", "4")
        msg = str(exc.value)
        assert "declared Model=4" in msg
        assert "GENERATED" in msg
        assert "refused rather than recorded" in msg

    def test_the_oos_pass_of_2026_09_20_would_now_be_refused(self, monkeypatch):
        """The exact bytes, the exact window — this is the pass that was let through."""
        self._stub(monkeypatch, REAL_PARTIAL_LINE, "")
        with pytest.raises(T.TickModelMismatch) as exc:
            T.assert_declared_tick_model({}, "midas_oos_rd_rd", "4",
                                         window_from=OOS_WINDOW_FROM)
        msg = str(exc.value)
        assert "GENERATED" in msg and "2026.09.04" in msg
        assert "populate the local tick cache" in msg

    def test_an_unknown_model_is_refused_too(self, monkeypatch):
        self._stub(monkeypatch, "", "")
        with pytest.raises(T.TickModelMismatch):
            T.assert_declared_tick_model({}, "tag", "4")

    def test_a_declared_real_tick_pass_that_ran_real_is_accepted(self, monkeypatch):
        self._stub(monkeypatch, REAL_TICKS_LINE, "History Quality: 100% real ticks")
        used, why = T.assert_declared_tick_model({}, "tag", "4")
        assert used == "real"

    def test_a_model_that_never_asked_for_real_ticks_is_unaffected(self, monkeypatch):
        """`Model=1` (1-minute OHLC) is a legitimate declaration; it is not refused
        for failing to be something it never requested."""
        self._stub(monkeypatch, "", "History Quality: 0% real ticks")
        used, _ = T.assert_declared_tick_model({}, "tag", "1")
        assert used == "generated"

    def test_the_passs_own_fromdate_is_what_partial_coverage_is_judged_against(self):
        """Wiring pin: a partial statement is only decidable against the window the
        pass declared, so `run_pass` must hand the guard its own FromDate."""
        src = inspect.getsource(T.run_pass)
        assert "assert_declared_tick_model(" in src, (
            "run_pass no longer asks which ticks the pass ran on")
        assert 'window_from=base["FromDate"]' in src, (
            "the guard is being called without the pass's window, so MT5's "
            "partial-coverage statement cannot be judged against it")


class TestAPassCannotBeRecordedOnTheWrongTicks:
    """`recorded_verdict` is the belt to the driver's braces.

    The driver raises, so a downgraded pass never reaches a comparison. These pin the
    second lock: even a perfectly key-matched comparison cannot be written to an
    artifact as a PASS on ticks the pass did not declare.
    """

    PASSING = {"verdict": "PASS", "count_match": True, "max_abs_dR": 0.0005}
    REAL = {"declared": "4", "used": "real", "evidence": "report: History Quality 100% real ticks"}
    GENERATED = {"declared": "4", "used": "generated",
                 "evidence": "journal: real ticks begin from 2026.09.04"}

    def test_a_key_matched_pass_on_declared_ticks_is_recorded(self):
        verdict, refused = P.recorded_verdict(self.PASSING, self.REAL)
        assert (verdict, refused) == ("PASS", "")

    def test_a_key_matched_pass_on_generated_ticks_is_refused_not_recorded(self):
        verdict, refused = P.recorded_verdict(self.PASSING, self.GENERATED)
        assert verdict == "REFUSED"
        assert "declared Model=4" in refused and "generated" in refused

    def test_an_unreported_tick_model_is_refused_not_recorded(self):
        """A future driver that stops reporting is a downgrade, not a pass."""
        verdict, refused = P.recorded_verdict(self.PASSING, {})
        assert verdict == "REFUSED"
        assert "unstated" in refused

    def test_a_failing_comparison_is_never_promoted(self):
        """The demotion runs one way only."""
        cmp = {"verdict": "FAIL"}
        assert P.recorded_verdict(cmp, self.REAL)[0] == "FAIL"
        assert P.recorded_verdict(cmp, self.GENERATED)[0] == "FAIL"


class TestTheRepoActuallyEngagesTheGuard:
    def test_the_house_tester_contract_declares_real_ticks(self):
        """If this pin changes, the refusal above stops applying to our own passes."""
        assert T._BASE_TESTER_INI["Model"] == "4", (
            "the tester contract no longer requests real ticks, so the tick-model "
            "refusal is no longer protecting the runs that use it")

    def test_the_declared_model_is_one_the_refusal_understands(self):
        for code in T.REAL_TICK_MODEL_CODES:
            assert code in T.TICK_MODEL_NAMES, (
                f"declared model {code} has no description — the refusal message would "
                f"be unreadable")

    def test_the_parity_artifact_carries_the_tick_model(self):
        """A parity number is only evidence next to the ticks that produced it."""
        src = inspect.getsource(P.main)
        assert '"tick_model"' in src, "the artifact would not say which ticks it used"
