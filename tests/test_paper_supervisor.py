"""The scheduled supervisor must exist in THIS repo, and say what it is.

WHY THIS FILE EXISTS. The health guide's documented remedy for a stale supervisor task —
`powershell -File scripts/install_paper_task.ps1 -Apply` — could not run, because the
installer requires `scripts/paper_supervisor.cmd` and this repository did not contain it:

    $ powershell -NoProfile -File scripts/install_paper_task.ps1
    REFUSING: wrapper not found at ...\\MIDASTOUCH\\scripts\\paper_supervisor.cmd

So the scheduled task kept executing the PREDECESSOR checkout's supervisor, and
`scripts/live_readiness.py` read `STALE` on every run — a documented remedy that cannot
work is worse than a missing feature, because it ends the investigation. These tests hold
the three things that have to stay true: the wrapper exists, it resolves an interpreter
WITHOUT reaching into the other checkout, and the exit code distinguishes "nothing to do"
from "a human must act".
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
CMD = SCRIPTS / "paper_supervisor.cmd"
PS1 = SCRIPTS / "install_paper_task.ps1"
sys.path.insert(0, str(SCRIPTS))
import paper_supervisor as ps  # noqa: E402


def test_the_installer_and_its_wrapper_agree():
    """The installer hardcodes the wrapper's name next to itself; both must exist."""
    assert PS1.is_file(), "the installer the health guide names is gone"
    assert "paper_supervisor.cmd" in PS1.read_text(encoding="utf-8")
    assert CMD.is_file(), (
        "scripts/install_paper_task.ps1 refuses without this wrapper, and the scheduled "
        "task then runs the predecessor checkout's supervisor")


def test_the_wrapper_resolves_its_own_interpreter_and_never_the_other_checkout():
    body = CMD.read_text(encoding="utf-8")
    assert "%~dp0" in body, "the wrapper must resolve itself from its own location"
    # A venv fallback is fine; an ABSOLUTE path into the other project is not, because
    # that venv carries the predecessor's src/ on the import path.
    assert "Synthetic Indices Bot" not in body
    assert "if not exist \"%PY%\" set PY=python" in body, \
        "the interpreter must fall back to the system python (this checkout has no .venv)"
    assert "paper_supervisor.py" in body, "the wrapper must call this repo's module"


def test_the_wrapper_logs_where_the_health_guide_says_it_does():
    body = CMD.read_text(encoding="utf-8")
    assert "artifacts\\live\\supervisor.log" in body
    guide = (REPO / "docs" / "MIDASTOUCH_HEALTH_GUIDE.md").read_text(encoding="utf-8")
    assert "supervisor.log" in guide, "the guide must point at the log the wrapper writes"


def test_the_supervisor_delegates_instead_of_reimplementing(monkeypatch):
    """One supervision implementation: the gold watchdog's."""
    assert ps.wd.__name__ == "midas_watchdog"
    assert hasattr(ps.wd, "check") and hasattr(ps.wd, "watchdog_summary")
    # And it supervises rather than trades.
    src = (SCRIPTS / "paper_supervisor.py").read_text(encoding="utf-8")
    for forbidden in ("order_send", "OrderSend", "CTrade", "position_open"):
        assert forbidden not in src, f"a supervisor must contain no order path ({forbidden})"


@pytest.mark.parametrize("record,escalating,expected", [
    # Nothing attached and nothing armed: reported, never red.
    ({"action": "NONE", "problem": "no MidastouchAI chart found on the gold terminal (x)"},
     False, 0),
    # A deliberate tester/parity session owns the terminal.
    ({"action": "PAUSED", "problem": "pause marker present"}, False, 0),
    # The surface moved to hosting; local remediation is meaningless.
    ({"action": "VPS-HOSTING", "problem": "VPS hosting active"}, False, 0),
    # Recovery in progress, still inside the restart budget.
    ({"action": "RESTUP", "problem": "ledger stale"}, False, 0),
    # The budget is spent: this is the one a human has to read.
    ({"action": "RESTUP", "problem": "ledger stale"}, True, 1),
])
def test_the_exit_code_separates_noise_from_an_alert(monkeypatch, record, escalating, expected):
    monkeypatch.setattr(ps.wd, "check", lambda dry_run=False: record)
    monkeypatch.setattr(ps.wd, "watchdog_summary", lambda: ("summary", escalating))
    assert ps.one_pass(dry_run=True) == expected


def test_a_crashing_pass_is_never_a_silent_success(monkeypatch):
    def boom(dry_run=False):
        raise RuntimeError("watchdog import failed")
    monkeypatch.setattr(ps.wd, "check", boom)
    assert ps.one_pass() == 1, "a supervisor that cannot run must not report success"


# --- the coverage record (2026-09-22) ------------------------------------------
#
# Measured that morning: 54 passes in 25.3 h where a 20-minute cadence owes 76, zero
# passes in the 01:00-06:00 UTC hours, one gap of 407 minutes. The passes that DID happen
# recorded nothing about the ones that did not, so these pin the three rules that make a
# night measurable: every real pass is recorded, a dry run is not a pass, and a NEW gap
# is an exit code while a standing one is not.

def _quiet(monkeypatch, alarm_new=False, alarm=None):
    monkeypatch.setattr(ps.wd, "check",
                        lambda dry_run=False: {"action": "NONE", "ledgers": []})
    monkeypatch.setattr(ps.wd, "watchdog_summary", lambda: ("summary", False))
    monkeypatch.setattr(ps.lc, "record_pass",
                        lambda record, verdict="OK": {"alarm": alarm,
                                                      "alarm_new": alarm_new})


def test_a_new_heartbeat_gap_alarm_is_never_a_silent_success(monkeypatch, capsys):
    _quiet(monkeypatch, alarm_new=True,
           alarm={"kind": "supervision-gap", "gap_min": 407.3,
                  "detail": "no supervision pass for 407.3 min"})
    assert ps.one_pass() == 1, "the pass that first sees a hole must go red"
    out = capsys.readouterr().out
    assert "ALARM supervision-gap" in out and "407.3min" in out


def test_a_standing_alarm_does_not_re_red_every_pass(monkeypatch):
    """A task that goes red every 20 minutes is noise that hides the real alerts; the
    standing alarm is carried by the alarm record, alerts.log and [3b] instead."""
    _quiet(monkeypatch, alarm_new=False,
           alarm={"kind": "supervision-gap", "gap_min": 407.3, "detail": "d"})
    assert ps.one_pass() == 0


def test_a_dry_run_records_no_coverage(monkeypatch):
    """'What would have happened' is not a pass that happened."""
    called = []
    monkeypatch.setattr(ps.wd, "check",
                        lambda dry_run=False: {"action": "NONE", "ledgers": []})
    monkeypatch.setattr(ps.lc, "record_pass", lambda *a, **k: called.append(1))
    assert ps.one_pass(dry_run=True) == 0
    assert called == []


def test_every_real_pass_is_recorded_with_its_verdict(monkeypatch):
    seen = {}
    monkeypatch.setattr(ps.wd, "check",
                        lambda dry_run=False: {"action": "RESTUP", "ledgers": [],
                                               "problem": "ledger stale"})
    monkeypatch.setattr(ps.wd, "watchdog_summary", lambda: ("summary", False))
    monkeypatch.setattr(ps.lc, "record_pass",
                        lambda record, verdict="OK": seen.update(record=record,
                                                                  verdict=verdict)
                        or {"alarm": None, "alarm_new": False})
    assert ps.one_pass() == 0
    assert seen["verdict"] == "OK" and seen["record"]["action"] == "RESTUP"


def test_the_supervisor_and_the_readiness_leg_name_one_task():
    """The task the installer registers, the reader verifies and the readiness leg reports
    must be the same string, or a green leg describes a task nobody runs."""
    import live_readiness
    ps1 = PS1.read_text(encoding="utf-8")
    assert f'[string]$TaskName = "{live_readiness.SUPERVISOR_TASK}"' in ps1
    assert live_readiness.SUPERVISOR_TASK in (SCRIPTS / "unattended.py").read_text(
        encoding="utf-8")


def test_the_supervisor_reads_the_standing_alarm_in_status(monkeypatch, capsys):
    monkeypatch.setattr(ps.wd, "watchdog_summary", lambda: ("0 restups", False))
    monkeypatch.setattr(ps.lc, "alarm_line", lambda: "PROBLEM: supervision-gap — 407 min")
    assert ps.main(["--status"]) == 1
    assert "PROBLEM: supervision-gap" in capsys.readouterr().out
