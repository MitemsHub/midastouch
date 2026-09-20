"""Pins for the refusal sweep — the class-level test for unreadable-path verdicts.

The load-bearing tests here are:

* ``test_every_resolver_consumer_is_swept`` — the sweep is only worth anything if
  it covers the whole class. This derives the list of scripts that actually read a
  terminal directory and fails when one of them is missing from the sweep, so a
  new consumer cannot quietly escape the check that exists because of it.
* ``test_sweep_catches_every_way_it_could_be_fooled`` — the positive control. A
  sweep that cannot fail is a sweep that reports PASS while running nothing.
* ``test_the_real_sweep_passes`` — runs all cases against an empty terminal root.

The verdict function is pure, so most of this runs without spawning a process.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import refusal_sweep as rs  # noqa: E402

TRACEBACK = rs.TRACEBACK
PROBE = rs.Case("probe.py", marker="cannot resolve", title="probe")


# --------------------------------------------------------------------------- #
# The verdict, one rule at a time
# --------------------------------------------------------------------------- #


def test_exiting_zero_is_a_failure_however_good_the_output_looks():
    ok, reason = rs.verdict(PROBE, exit_code=0, output="all checks PASS")
    assert not ok
    assert "reported SUCCESS" in reason


def test_a_traceback_is_not_a_refusal():
    """Same exit code as a refusal, but the operator gets a crash, not a reason."""
    ok, reason = rs.verdict(PROBE, exit_code=1,
                            output=f"cannot resolve a terminal\n{TRACEBACK}\n  File ...")
    assert not ok
    assert "traceback instead of refusing" in reason


def test_non_zero_without_naming_the_cause_is_a_failure():
    ok, reason = rs.verdict(PROBE, exit_code=2, output="something went wrong")
    assert not ok
    assert "never named what it could not resolve" in reason


def test_a_timeout_is_not_a_refusal():
    ok, reason = rs.verdict(PROBE, exit_code=None, output="", timed_out=True)
    assert not ok
    assert "hung diagnostic" in reason


def test_writing_a_reading_on_refusal_is_a_failure():
    ok, reason = rs.verdict(PROBE, exit_code=2, output="cannot resolve a terminal",
                            wrote=[("artifacts/x.json", '{"verdict": "HOLD"}')])
    assert not ok
    assert "recording a reading is reporting a verdict" in reason


def test_a_clean_refusal_passes():
    ok, reason = rs.verdict(PROBE, exit_code=2,
                            output="cannot resolve an MT5 terminal directory")
    assert ok and "refused cleanly" in reason


def test_a_declared_refusal_record_must_still_identify_itself():
    """The write exemption is narrow: the content has to say it was a refusal."""
    declared = rs.Case("probe.py", marker="cannot resolve", title="probe",
                       records_refusal=True,
                       write_signals=('"available": false',))
    ok, _ = rs.verdict(declared, exit_code=3, output="cannot resolve",
                       wrote=[("a.json", '"available": false')])
    assert ok
    bad, reason = rs.verdict(declared, exit_code=3, output="cannot resolve",
                             wrote=[("a.json", '{"lots": 0.37}')])
    assert not bad
    assert "not identifiable as a refusal" in reason


def test_a_declared_exemption_with_no_signals_cannot_pass():
    """Declaring an exemption without saying what the file must contain fails."""
    hollow = rs.Case("probe.py", marker="cannot resolve", title="probe",
                     records_refusal=True)
    ok, _ = rs.verdict(hollow, exit_code=3, output="cannot resolve",
                       wrote=[("a.json", "{}")])
    assert not ok


# --------------------------------------------------------------------------- #
# The positive control
# --------------------------------------------------------------------------- #


def test_sweep_catches_every_way_it_could_be_fooled():
    ok, lines = rs.self_check()
    assert ok, "the sweep's own verdict logic is wrong:\n" + "\n".join(lines)
    # and it really exercised the failure modes rather than passing trivially
    assert sum(1 for ln in lines if "[OK ]" in ln) == len(lines)
    assert any("exits 0 while blind" in ln for ln in lines)
    assert any("tracebacks" in ln for ln in lines)


# --------------------------------------------------------------------------- #
# Coverage: the sweep must be the whole class, automatically
# --------------------------------------------------------------------------- #

#: Scripts that reference the resolver for reasons other than reading an install.
#: Each needs a reason, because this list is the only way out of the check below.
KNOWN_EXEMPT: dict[str, str] = {}


def _resolver_consumers() -> set[str]:
    consumers: set[str] = set()
    for p in sorted((ROOT / "scripts").glob("*.py")):
        if p.name in {"mt5_terminals.py", "refusal_sweep.py"}:
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bmt5_terminals\b|\bmt5t\.", txt):
            consumers.add(p.name)
    for p in sorted((ROOT / "scripts").glob("*.ps1")):
        if "mt5_terminals" in p.read_text(encoding="utf-8", errors="replace"):
            consumers.add(p.name)
    return consumers


def test_every_resolver_consumer_is_swept():
    """A new script that reads a terminal must not escape the class-level check."""
    swept = {c.name for c in rs.CASES}
    missing = _resolver_consumers() - swept - set(KNOWN_EXEMPT)
    assert not missing, (
        "these scripts read a terminal directory but are not in the refusal "
        f"sweep: {sorted(missing)}. Add them to refusal_sweep.CASES (or record "
        "why they are exempt).")


def test_the_sweep_covers_the_documented_set():
    """§5.2 of the audit names these; the sweep must name them too."""
    swept = {c.name for c in rs.CASES}
    for name in ("confirm-gate-open.ps1", "go_live_rehearsal.py",
                 "demo_watchdog.py", "funnel_diff.py", "atr_drift_monitor.py",
                 "midas_drift_drill.py", "set_chart_preset.py"):
        assert name in swept, name
    # the powershell script must be DERIVED as a consumer, which is only true if
    # it delegates to scripts/mt5_terminals.py rather than scanning installs itself
    assert "confirm-gate-open.ps1" in _resolver_consumers()


def test_every_case_declares_a_marker_and_a_title():
    for c in rs.CASES:
        assert c.marker, f"{c.name} declares no refusal marker"
        assert c.title, f"{c.name} declares no title"


def test_every_marker_comes_from_somewhere_real():
    """A marker that appears in no source file cannot be evidence of anything.

    Honest about its own strength: markers arrive from two places -- the script's
    own text, or the shared resolver's refusal message (most of these scripts
    cannot resolve their terminal at all, so the diagnosis is written in
    `mt5_terminals.py`). This catches a typo or a marker copied from nowhere.

    It would NOT catch the mistake that actually happened here: the ps1 case
    asserted "UNKNOWN, not OPEN", which is real text in that file but belongs to a
    branch an empty root never reaches. The substantive protection against that
    is `test_the_real_sweep_passes`, which runs the case and fails when the marker
    does not appear in the output.
    """
    shared = (ROOT / "scripts" / "mt5_terminals.py").read_text(
        encoding="utf-8", errors="replace")
    for case in rs.CASES:
        src = (ROOT / "scripts" / case.name).read_text(encoding="utf-8",
                                                     errors="replace")
        assert case.marker in src or case.marker in shared, (
            f"{case.name}: the refusal marker {case.marker!r} appears in neither "
            f"the script nor the shared resolver, so it cannot be evidence")


# --------------------------------------------------------------------------- #
# The real thing
# --------------------------------------------------------------------------- #


def test_the_real_sweep_passes():
    """Run every case against an empty terminal root.

    Restores anything a case wrote, so the repo is left exactly as found.
    """
    results = rs.sweep(timeout=120.0)
    assert len(results) == len(rs.CASES)
    failures = [(r.case.name, r.reason, r.output[-400:]) for r in results if not r.ok]
    assert not failures, "the defect class is still present:\n" + "\n\n".join(
        f"{n}: {why}\n{out}" for n, why, out in failures)


def test_the_sweep_restores_what_it_touched():
    """A sweeping tool that pollutes the repo is its own defect class."""
    before = rs._snapshot()
    rs.sweep(timeout=120.0)
    after = rs._snapshot()
    assert before == after, "the sweep changed artifacts and did not restore them"
