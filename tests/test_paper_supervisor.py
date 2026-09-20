"""Pins for the paper supervisor: which conditions alert, and which must stay quiet.

TWO BEHAVIOURS MATTER MOST, and both are the kind that fail silently:

1. **A closed market must NOT alert.** The scheduled task fires every 20 minutes around
   the clock, so if a weekend produced alerts it would produce 72 of them — and an alert
   channel nobody can trust is one nobody reads. Verified: 1437 minutes of tick age
   exits 0 and writes nothing.
2. **A halt MUST alert.** The day ledger stopping entries is the system working, but it
   is also the moment the account stopped doing anything, and that is exactly what an
   operator needs told.

The MT5 bridge is never touched here: `_tick_age` is injected, so the tests do not need a
terminal, a market, or a funded account.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import paper_supervisor as ps  # noqa: E402


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """Redirect every path the supervisor writes to, and control the clock input."""
    monkeypatch.setattr(ps, "LIVE", tmp_path)
    monkeypatch.setattr(ps, "STATE", tmp_path / "paper_state.json")
    monkeypatch.setattr(ps, "LEDGER", tmp_path / "day_ledger.json")
    monkeypatch.setattr(ps, "SUMMARY", tmp_path / "paper_daily.jsonl")
    monkeypatch.setattr(ps, "ALERTS", tmp_path / "alerts.log")
    monkeypatch.setattr(ps, "COSTS", tmp_path / "cost_samples.jsonl")
    return tmp_path


def fake_trader(rc: int = 0, stdout: str = "", stderr: str = ""):
    def _run(*_a, **_kw):
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)
    return _run


class TestMarketState:
    def test_a_closed_market_exits_quietly_and_writes_nothing(self, wired, monkeypatch,
                                                              capsys):
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: 1437 * 60.0)
        rc = ps.main([])
        assert rc == 0
        assert "market closed" in capsys.readouterr().out
        assert not (wired / "alerts.log").exists(), "a closed market is not an alert"
        assert not (wired / "paper_daily.jsonl").exists()

    def test_an_unreadable_tick_alerts_and_fails(self, wired, monkeypatch):
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: None)
        assert ps.main([]) == 2
        log = (wired / "alerts.log").read_text(encoding="utf-8")
        assert "terminal is down" in log

    def test_force_runs_even_when_the_tick_looks_stale(self, wired, monkeypatch):
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: 9999.0)
        monkeypatch.setattr(ps.subprocess, "run", fake_trader())
        assert ps.main(["--force"]) == 0


class TestAlerts:
    def test_a_halted_ledger_alerts_and_is_reported(self, wired, monkeypatch):
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: 5.0)
        monkeypatch.setattr(ps.subprocess, "run", fake_trader())
        monkeypatch.setattr(ps, "_sampled_today", lambda *_a: True)
        (wired / "paper_state.json").write_text(json.dumps({
            "summary": {"armed": False, "utc": ps._utc().isoformat(timespec="seconds"),
                        "ledger": {"realised_usd": -379.28, "entries": 1,
                                   "halted": True, "halt_reason": "daily_loss_stop"},
                        "account": {"balance": 24620.72, "position": None,
                                    "closed": [{}]},
                        "decisions": []}}), encoding="utf-8")
        assert ps.main(["--force"]) == 0
        log = (wired / "alerts.log").read_text(encoding="utf-8")
        assert "HALTED" in log and "daily_loss_stop" in log
        rows = [json.loads(x) for x in
                (wired / "paper_daily.jsonl").read_text(encoding="utf-8").splitlines()]
        assert rows[-1]["halted"] is True
        assert rows[-1]["realised_today_usd"] == pytest.approx(-379.28)

    def test_an_armed_switch_alerts(self, wired, monkeypatch):
        """This program never sends orders, so ARMED means something else may."""
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: 5.0)
        monkeypatch.setattr(ps.subprocess, "run", fake_trader())
        monkeypatch.setattr(ps, "_sampled_today", lambda *_a: True)
        (wired / "paper_state.json").write_text(json.dumps({
            "summary": {"armed": True, "utc": ps._utc().isoformat(timespec="seconds"),
                        "ledger": {}, "account": {}, "decisions": []}}),
            encoding="utf-8")
        ps.main(["--force"])
        assert "ARMED" in (wired / "alerts.log").read_text(encoding="utf-8")

    def test_stale_state_while_open_alerts(self, wired, monkeypatch):
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: 5.0)
        monkeypatch.setattr(ps.subprocess, "run", fake_trader())
        monkeypatch.setattr(ps, "_sampled_today", lambda *_a: True)
        (wired / "paper_state.json").write_text(json.dumps({
            "summary": {"utc": "2020-01-01T00:00:00+00:00", "armed": False,
                        "ledger": {}, "account": {}, "decisions": []}}),
            encoding="utf-8")
        ps.main(["--force"])
        assert "min old" in (wired / "alerts.log").read_text(encoding="utf-8")

    def test_a_failing_trader_alerts_and_propagates_the_code(self, wired, monkeypatch):
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: 5.0)
        monkeypatch.setattr(ps, "_sampled_today", lambda *_a: True)
        monkeypatch.setattr(ps.subprocess, "run",
                            fake_trader(rc=3, stderr="boom"))
        assert ps.main(["--force"]) == 3
        assert "exited 3" in (wired / "alerts.log").read_text(encoding="utf-8")

    def test_a_dry_run_appends_no_summary(self, wired, monkeypatch):
        monkeypatch.setattr(ps, "_tick_age", lambda *a, **k: 5.0)
        monkeypatch.setattr(ps.subprocess, "run", fake_trader())
        ps.main(["--force", "--dry-run"])
        assert not (wired / "paper_daily.jsonl").exists()


class TestCostSamplingIsOncePerDay:
    def test_no_samples_means_sample(self, wired):
        assert ps._sampled_today("2026-09-20") is False

    def test_a_sample_for_today_suppresses_the_next(self, wired):
        (wired / "cost_samples.jsonl").write_text(
            json.dumps({"utc": "2026-09-20T22:10:00+00:00", "ratio": 1.1}) + "\n",
            encoding="utf-8")
        assert ps._sampled_today("2026-09-20") is True
        assert ps._sampled_today("2026-09-21") is False

    def test_a_corrupt_sample_file_does_not_crash_it(self, wired):
        (wired / "cost_samples.jsonl").write_text("{ not json", encoding="utf-8")
        assert ps._sampled_today("2026-09-20") is False


class TestTheInstallerKeepsItsPromises:
    """Static checks: the installer must not nest quotes, and must default to dry run."""

    def test_it_does_not_use_schtasks_with_nested_quotes(self):
        """The measured failure: a space in the path broke schtasks /TR."""
        src = (ROOT / "scripts" / "install_paper_task.ps1").read_text(encoding="utf-8")
        assert "Invoke-Expression $cmd" not in src, (
            "the schtasks path failed with 'Invalid argument/option - ...\\Synthetic' "
            "because the project path contains a space; the ScheduledTasks cmdlets take "
            "-Execute and -Argument separately and need no nesting")
        assert "Register-ScheduledTask" in src

    def test_the_wrapper_resolves_its_own_location(self):
        src = (ROOT / "scripts" / "paper_supervisor.cmd").read_text(encoding="utf-8")
        assert "%~dp0" in src, "a hardcoded path would not survive a folder rename"
        assert "C:\\Users" not in src and "Desktop" not in src

    def test_the_installer_defaults_to_a_dry_run(self):
        src = (ROOT / "scripts" / "install_paper_task.ps1").read_text(encoding="utf-8")
        assert "$Apply" in src
        assert "if (-not $Apply)" in src, "registering must require an explicit switch"
