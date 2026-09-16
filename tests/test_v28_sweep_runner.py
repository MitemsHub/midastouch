"""Offline tests for the V28 sweep runner (the graduated _tmp orchestrator).

These pin the discipline that must never silently drift: exact terminal-path
identity, the ledger-flat gate that mirrors the EA's own restore rule
(a dangling OPEN would be adopted as a live virtual position), fail-closed
behavior on unreadable ledgers, and the artifact record. Nothing here touches
a real terminal: process calls, the sweep subprocess, and paths are faked.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import v28_sweep_runner as sr  # noqa: E402


# --- ledger flatness ----------------------------------------------------------

def _ledger(tmp_path: Path, rows: list[str]) -> str:
    p = tmp_path / "ledger.csv"
    p.write_text("\n".join(rows) + "\n")
    return str(p)


def test_flat_ledger_with_closed_trades_and_era_rows() -> None:
    path = _ledger(Path(str(tmp_path := __import__("tempfile").mkdtemp())), [
        "OPEN,1789500000,111,1,100.0,95.0,110.0,0.10,5.0,5.0,30,PAPER",
        "CLOSE,1789500600,111,TP,110.0,2.000,10.00,105.00",
        "ERA,2.24,1789494700,pertick-fills",
        "EQ,105.00",
    ])
    f = sr.ledger_flatness(path)
    assert f["flat"] is True and f["closed"] == 1 and f["era_stamps"] == 1
    assert f["open_positions"] == []


def test_dangling_open_is_not_flat_the_ea_would_restore_it() -> None:
    tmp = Path(__import__("tempfile").mkdtemp())
    path = _ledger(tmp, [
        "OPEN,1789500000,222,-1,200.0,205.0,190.0,0.10,5.0,5.0,30,PAPER",
    ])
    f = sr.ledger_flatness(path)
    assert f["flat"] is False
    assert f["open_positions"] == [{"ticket": "222", "epoch": "1789500000",
                                    "line": 1}]


def test_open_close_pairing_is_by_ticket() -> None:
    tmp = Path(__import__("tempfile").mkdtemp())
    path = _ledger(tmp, [
        "OPEN,1789500000,333,1,100.0,95.0,110.0,0.10,5.0,5.0,30,PAPER",
        "OPEN,1789500100,444,1,100.0,95.0,110.0,0.10,5.0,5.0,30,PAPER",
        "CLOSE,1789500600,333,TP,110.0,2.000,10.00,105.00",
    ])
    f = sr.ledger_flatness(path)
    assert f["flat"] is False
    assert [o["ticket"] for o in f["open_positions"]] == ["444"]


def test_missing_ledger_fails_closed() -> None:
    f = sr.ledger_flatness(str(Path(__import__("tempfile").mkdtemp()) / "nope.csv"))
    assert f["flat"] is False and f["problems"]


def test_corrupt_rows_fails_closed() -> None:
    tmp = Path(__import__("tempfile").mkdtemp())
    path = tmp / "ledger.csv"
    path.write_bytes(b"\x00\x01\x02 not a ledger \xff\xfe")
    f = sr.ledger_flatness(str(path))
    assert f["flat"] is False
    # UnicodeDecodeError surfaces as OSError on some platforms; either way
    # the gate must refuse, never report a book it could not read as flat.
    assert f["problems"]


# --- terminal identity + inventory --------------------------------------------

def test_data_folder_match_is_on_the_install_dir_and_case_insensitive(tmp_path) -> None:
    data_dir = tmp_path / "DATAFOLDER123"
    data_dir.mkdir()
    (data_dir / "origin.txt").write_bytes(
        ("C:\\Installs\\TestTerminal\r\n").encode("utf-16"))
    sr.TERM_ROOT = str(tmp_path)
    sr.TERM_EXE = r"c:\installs\testterminal\terminal64.exe"
    assert sr.data_folder_for_terminal() == str(data_dir)

    (data_dir / "origin.txt").write_bytes("C:\\Elsewhere\r\n".encode("utf-16"))
    assert sr.data_folder_for_terminal() is None


def test_inventory_reads_magic_and_tag_from_chart_profiles(tmp_path) -> None:
    charts = tmp_path / "MQL5" / "Profiles" / "Charts" / "Default"
    charts.mkdir(parents=True)
    (charts / "armd.chr").write_text(
        "symbol=Volatility 75 Index\nInpMagic=7788150\nInpArmTag=D\n",
        encoding="utf-16")
    (charts / "untagged.chr").write_text(
        "symbol=Volatility 75 Index\nInpMagic=7788100\n", encoding="utf-16")
    (charts / "unknown.chr").write_text(
        "symbol=Volatility 75 Index\nInpMagic=7788999\n", encoding="utf-16")
    (charts / "other.chr").write_text(
        "symbol=Boom 1000 Index\nInpMagic=7788100\n", encoding="utf-16")

    arms = sr.inventory_arms(str(tmp_path))
    by_name = {a["name"]: a for a in arms}
    assert set(by_name) == {"D_fwd", "B_tp24", "unknown_7788999"}
    assert by_name["D_fwd"]["tag"] == "D"
    assert by_name["D_fwd"]["ledger"].endswith(
        f"MitemshubAI_paper_Volatility_75_Index_D.csv")
    assert by_name["B_tp24"]["tag"] is None
    assert by_name["B_tp24"]["ledger"].endswith(
        f"MitemshubAI_paper_Volatility_75_Index.csv")


def test_verify_all_flat_fails_when_one_arm_has_an_open_position(tmp_path) -> None:
    charts = tmp_path / "MQL5" / "Profiles" / "Charts" / "Default"
    charts.mkdir(parents=True)
    (charts / "a.chr").write_text(
        "symbol=Volatility 75 Index\nInpMagic=7788075\n", encoding="utf-16")
    (tmp_path / "MQL5" / "Files").mkdir(parents=True)
    (tmp_path / "MQL5" / "Files" / "MitemshubAI_paper_Volatility_75_Index.csv") \
        .write_text("OPEN,1789500000,555,1,100.0,95.0,110.0,0.10,5.0,5.0,30,PAPER\n")
    (tmp_path / "MQL5" / "Files" / "MitemshubAI_paper_Volatility_75_Index_missing.csv") \
        .write_text("")   # not referenced by any chart; must be ignored

    arms = sr.inventory_arms(str(tmp_path))
    all_flat, evidence = sr.verify_all_flat(arms)
    assert all_flat is False
    assert evidence[0]["open_positions"][0]["ticket"] == "555"


# --- CLI pass-through ---------------------------------------------------------

def test_subcommand_flags_pass_through_to_v28_research() -> None:
    """REMAINDER pass-through: `exit-sweep --survivors X --window wf` must reach
    the subprocess intact. A plain nargs='*' made the top parser reject
    --survivors (caught live 2026-09-16, cost one wasted invocation)."""
    argv = ["exit-sweep", "--survivors", "V28_REVERSE_BOTH", "--window", "wf"]
    args = sr.build_parser().parse_args(argv)
    assert args.v28_command == argv
    assert args.i_have_verified_flat is False


def test_status_shorthand_and_override_flag_parse() -> None:
    assert sr.build_parser().parse_args([]).v28_command == []
    argv = ["--i-have-verified-flat", "matrix", "--windows", "wf"]
    args = sr.build_parser().parse_args(argv)
    assert args.i_have_verified_flat is True
    assert args.v28_command == ["matrix", "--windows", "wf"]


# --- the guarded run ----------------------------------------------------------

class _Fake:
    """Capture monkeypatched calls without touching the real machine."""

    def __init__(self, monkeypatch, tmp_path, flat=True, pids=None, sweep_rc=0):
        self.calls: list[str] = []
        monkeypatch.setattr(sr, "terminal_pids_exact", lambda: pids or [])
        monkeypatch.setattr(sr, "stop_terminal", lambda p: self.calls.append("stop") or True)
        monkeypatch.setattr(sr, "relaunch_terminal", lambda: self.calls.append("relaunch"))
        monkeypatch.setattr(sr.subprocess, "call",
                            lambda *a, **k: self.calls.append("sweep") or sweep_rc)
        monkeypatch.setattr(sr, "ARTIFACT", tmp_path / "last_run.json")
        # one V75 chart whose ledger is flat or not, per the test's need
        charts = tmp_path / "MQL5" / "Profiles" / "Charts" / "Default"
        charts.mkdir(parents=True, exist_ok=True)
        (charts / "arm.chr").write_text(
            "symbol=Volatility 75 Index\nInpMagic=7788150\nInpArmTag=D\n",
            encoding="utf-16")
        files = tmp_path / "MQL5" / "Files"
        files.mkdir(exist_ok=True)
        ledger = files / "MitemshubAI_paper_Volatility_75_Index_D.csv"
        ledger.write_text(
            "OPEN,1789500000,999,1,100.0,95.0,110.0,0.10,5.0,5.0,30,PAPER\n"
            if not flat else "ERA,26.40,1789494700,pertick-fills\n")
        monkeypatch.setattr(sr, "data_folder_for_terminal", lambda: str(tmp_path))


def test_run_guarded_refuses_a_non_flat_ledger_without_stopping_anything(
        monkeypatch, tmp_path) -> None:
    fake = _Fake(monkeypatch, tmp_path, flat=False, pids=[4242])
    with pytest.raises(SystemExit) as exc:
        sr.run_guarded(["exit-sweep", "--survivors", "V28_REVERSE_BOTH",
                        "--window", "wf"], override=False)
    assert exc.value.code == 2
    assert fake.calls == [], "no stop, no sweep, no relaunch on refusal"
    rec = json.loads((tmp_path / "last_run.json").read_text())
    assert rec["override"] is False
    assert rec["flatness"][0]["flat"] is False


def test_run_guarded_stops_sweeps_relaunches_in_order_on_a_flat_book(
        monkeypatch, tmp_path) -> None:
    fake = _Fake(monkeypatch, tmp_path, flat=True, pids=[4242], sweep_rc=0)
    with pytest.raises(SystemExit) as exc:
        sr.run_guarded(["exit-sweep", "--survivors", "V28_REVERSE_BOTH",
                        "--window", "wf"], override=False)
    assert exc.value.code == 0
    assert fake.calls == ["stop", "sweep", "relaunch"]
    rec = json.loads((tmp_path / "last_run.json").read_text())
    assert rec["arms"] == [{"name": "D_fwd", "magic": "7788150", "tag": "D",
                            "chart": "arm.chr",
                            "ledger": "MitemshubAI_paper_Volatility_75_Index_D.csv"}]
    assert rec["sweep_rc"] == 0 and rec["relaunched"] is True


def test_run_guarded_relaunches_even_when_the_sweep_subprocess_raises(
        monkeypatch, tmp_path) -> None:
    fake = _Fake(monkeypatch, tmp_path, flat=True, pids=[4242])
    def _boom(*a, **k):
        fake.calls.append("sweep")
        raise RuntimeError("tester exploded")
    monkeypatch.setattr(sr.subprocess, "call", _boom)
    with pytest.raises(SystemExit) as exc:
        sr.run_guarded(["matrix", "--windows", "wf"], override=False)
    assert exc.value.code == 4
    assert fake.calls == ["stop", "sweep", "relaunch"]
    rec = json.loads((tmp_path / "last_run.json").read_text())
    assert "tester exploded" in rec["sweep_error"]


def test_run_guarded_records_the_override(monkeypatch, tmp_path) -> None:
    fake = _Fake(monkeypatch, tmp_path, flat=False, pids=[])
    with pytest.raises(SystemExit) as exc:
        sr.run_guarded(["exit-sweep", "--survivors", "V28_REVERSE_BOTH",
                        "--window", "wf"], override=True)
    assert exc.value.code == 0
    assert fake.calls == ["sweep", "relaunch"]   # nothing to stop (no pids)
    rec = json.loads((tmp_path / "last_run.json").read_text())
    assert rec["override"] is True and rec["override_reason"]
