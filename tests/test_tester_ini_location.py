"""Where the tester driver is allowed to put its /config INI.

WHY THIS FILE EXISTS. On 2026-09-20 the first live parity pass on the Upcomers
install died like this, *after* the harness had already stopped the funded account's
terminal:

    PermissionError: [Errno 13] Permission denied:
      'C:\\\\Program Files\\\\MetaTrader 5\\\\config\\\\v75_regress_midas_wf_rd_rd.ini'

The driver wrote its INI next to the executable. That is fine for a portable install
in a user-writable folder (which is what every previous era used) and impossible for
this venue's terminal, which lives in Program Files. Two things had to change and both
are pinned below: the INI is written to the first location that actually accepts a
write — the per-install DATA folder, which is where the era that did produce parity
artifacts kept its INIs — and the preflight asks whether that is possible BEFORE the
terminal is stopped, not during the pass.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import mt5_tester_driver as T      # noqa: E402


def _blocked_at(path: Path) -> Path:
    """A path that cannot be used as a directory, deterministically.

    A real file where a directory is expected makes ``mkdir``/``write_text`` fail the
    same way a read-only folder does, without depending on chmod semantics that differ
    between Windows and POSIX — the point under test is the fallback, not the ACL.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a directory", encoding="utf-8")
    return path


class TestCandidateOrder:
    def test_the_per_install_data_folder_is_tried_first(self, monkeypatch, tmp_path):
        monkeypatch.setattr(T, "TERMINAL_DATA", tmp_path / "datafolder")
        monkeypatch.setattr(T, "TERMINAL_EXE", tmp_path / "install" / "terminal64.exe")
        assert T.config_dirs() == [
            tmp_path / "datafolder" / "config",
            tmp_path / "install" / "config",
        ]

    def test_a_portable_install_is_one_candidate_not_two(self, monkeypatch, tmp_path):
        """Portable mode collapses data folder and install dir; no duplicate entries."""
        monkeypatch.setattr(T, "TERMINAL_DATA", tmp_path)
        monkeypatch.setattr(T, "TERMINAL_EXE", tmp_path / "terminal64.exe")
        assert T.config_dirs() == [tmp_path / "config"]


class TestWritableFallback:
    def test_the_ini_lands_in_the_data_folder_when_the_install_is_read_only(
            self, monkeypatch, tmp_path):
        """The live failure, replayed: Program Files refuses, the data folder accepts."""
        _blocked_at(tmp_path / "install" / "config")
        monkeypatch.setattr(T, "TERMINAL_DATA", tmp_path / "datafolder")
        monkeypatch.setattr(T, "TERMINAL_EXE", tmp_path / "install" / "terminal64.exe")

        ini = T.write_config_ini("v75_regress_probe.ini", "[Tester]\n")

        assert ini == tmp_path / "datafolder" / "config" / "v75_regress_probe.ini"
        assert ini.read_text(encoding="ascii") == "[Tester]\n"

    def test_a_missing_config_dir_is_created_rather_than_assumed(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(T, "TERMINAL_DATA", tmp_path / "datafolder")
        monkeypatch.setattr(T, "TERMINAL_EXE", tmp_path / "install" / "terminal64.exe")
        assert not (tmp_path / "datafolder").exists()
        ini = T.write_config_ini("x.ini", "[Tester]\n")
        assert ini.is_file()

    def test_the_returned_path_is_absolute(self, monkeypatch, tmp_path):
        """`/config:` is passed straight through, so a relative path would be resolved
        against the INSTALL folder — the read-only one this fallback exists to avoid."""
        monkeypatch.setattr(T, "TERMINAL_DATA", tmp_path / "datafolder")
        monkeypatch.setattr(T, "TERMINAL_EXE", tmp_path / "install" / "terminal64.exe")
        assert T.write_config_ini("x.ini", "[Tester]\n").is_absolute()

    def test_no_writable_location_refuses_and_names_every_candidate(
            self, monkeypatch, tmp_path):
        _blocked_at(tmp_path / "install" / "config")
        _blocked_at(tmp_path / "datafolder" / "config")
        monkeypatch.setattr(T, "TERMINAL_DATA", tmp_path / "datafolder")
        monkeypatch.setattr(T, "TERMINAL_EXE", tmp_path / "install" / "terminal64.exe")
        with pytest.raises(RuntimeError) as exc:
            T.write_config_ini("x.ini", "[Tester]\n")
        msg = str(exc.value)
        assert "cannot write a /config INI" in msg
        assert str(tmp_path / "install" / "config") in msg
        assert str(tmp_path / "datafolder" / "config") in msg


class TestRunPassCannotBypassTheFallback:
    def test_run_pass_writes_its_ini_through_the_helper(self):
        """Pins the fix at the call site: no direct write next to the executable can
        creep back in, which is what silently reintroduces the Program Files failure."""
        body = inspect.getsource(T.run_pass)
        assert "write_config_ini(" in body
        assert "ini_path.write_text" not in body


class TestParityPreflightAsksBeforeStoppingTheTerminal:
    """The harness stops the funded account's terminal before it runs a pass, so a
    condition knowable in advance must be reported in the preflight, not mid-session."""

    @staticmethod
    def _provisioned(tmp_path) -> Path:
        data = tmp_path / "datafolder"
        (data / "MQL5" / "Experts" / "MIDASTOUCH").mkdir(parents=True)
        (data / "MQL5" / "Experts" / "MIDASTOUCH" / "MidastouchAI.ex5").write_bytes(b"x")
        (data / "MQL5" / "Files").mkdir(parents=True)
        (data / "MQL5" / "Files" / "MIDASTOUCH_spread_M15.csv").write_text(
            "time,spread\n", encoding="utf-8")
        return data

    def test_an_unwritable_ini_location_blocks_the_pass(self, monkeypatch, tmp_path):
        import midas_parity as P
        data = self._provisioned(tmp_path)
        monkeypatch.setattr(P.R, "data_folder_for_terminal", lambda: str(data))
        # Both candidates blocked, on the harness's own view of them: the sandbox data
        # folder it was told to use, and the install folder next to the exe.
        monkeypatch.setattr(P.T, "TERMINAL_DATA", data)
        monkeypatch.setattr(P.T, "TERMINAL_EXE", tmp_path / "install" / "terminal64.exe")
        _blocked_at(tmp_path / "install" / "config")
        _blocked_at(data / "config")

        problems, notes = P.preflight(P.EXPERT)

        assert any(p.startswith("no writable /config INI") for p in problems), problems

    def test_a_writable_location_passes_and_leaves_no_probe_behind(
            self, monkeypatch, tmp_path):
        import midas_parity as P
        data = self._provisioned(tmp_path)
        monkeypatch.setattr(P.R, "data_folder_for_terminal", lambda: str(data))
        monkeypatch.setattr(P.T, "TERMINAL_DATA", data)
        monkeypatch.setattr(P.T, "TERMINAL_EXE", tmp_path / "install" / "terminal64.exe")

        problems, notes = P.preflight(P.EXPERT)

        assert not [p for p in problems if "/config INI" in p], problems
        assert not list((data / "config").glob("midas_parity_write_probe.ini"))
        assert notes, "a first pass on a new install must be told the tester root is absent"

    def test_no_terminal_resolving_returns_a_pair_not_a_bare_list(
            self, monkeypatch):
        """The bug this file's preflight work exposed: the early return handed callers
        a list where they unpack `(problems, notes)`, so "no terminal" raised
        ValueError instead of printing its own diagnosis."""
        import midas_parity as P
        monkeypatch.setattr(P.R, "data_folder_for_terminal", lambda: None)
        problems, notes = P.preflight(P.EXPERT)
        assert problems and notes == []
