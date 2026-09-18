"""Offline tests for the go-live rehearsal tool.

The rehearsal must stay read-only and must stay honest: markers are evaluated
across ALL of the day's banner blocks (a late reload can truncate the newest
banner mid-sequence), the version check reads the NEWEST banner against the
repo's APP_VERSION, and the LIVE-preset check must refuse a stub. Journals and
presets here are synthetic files in tmp_path — the live terminals are never
touched by a test.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import go_live_rehearsal as glr  # noqa: E402


def _utf16_journal(path: Path, lines: list[str]) -> None:
    """MT5 Experts journals are UTF-16LE with a BOM; write one like the EA does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe" + "\n".join(lines).encode("utf-16-le"))


def _banner(version: str, *, complete: bool = True) -> list[str]:
    lines = [
        f"AA\t0\t10:00:00.000\tMitemshubAI (Volatility 75 Index,M15)\t"
        f"[v{version}] MITEMSHUB AI v{version} started, build 5830, Standard Mode",
    ]
    if complete:
        lines += [
            f"AB\t0\t10:00:00.001\tMitemshubAI\t[v{version}] PAPER ledger era stamp: {version}",
            f"AC\t0\t10:00:00.002\tMitemshubAI\t[v{version}] FIT ROUTER: Volatility 75 Index "
            f"min-lot stop-risk $4.72 exceeds the 0.50% plan ($0.15) but sits inside the "
            f"20% cap - TOLERATED",
            f"AD\t0\t10:00:00.003\tMitemshubAI\t[v{version}] RiskCap=20%",
            f"AE\t0\t10:00:00.004\tMitemshubAI\t[v{version}] WARNING: risk cap > 10% — tiny-account mode.",
            f"AF\t0\t10:00:00.005\tMitemshubAI\t[v{version}] [SELFTEST] fixed arrays OK: strat 6/0 p=+5.0",
            f"AG\t0\t10:00:00.006\tMitemshubAI\t[v{version}] GARCH ready: 200 observations, sigma=0.00421",
            f"AH\t0\t10:00:00.007\tMitemshubAI\t[v{version}] Telemetry -> MQL5\\Files\\telemetry.csv",
            f"AI\t0\t10:00:00.008\tMitemshubAI\t[v{version}] Cold-start catch-up: 200 bars replayed",
            f"AJ\t0\t10:00:00.009\tMitemshubAI\t[v{version}] PAPER MODE: virtual equity $50.00",
        ]
    return lines


def test_markers_survive_a_truncated_newest_banner(tmp_path, monkeypatch) -> None:
    # Day with two inits; the NEWEST is truncated (header only — the terminal
    # stopped before the warmup lines). Marker existence must still PASS,
    # because the earlier complete banner proves the build prints them.
    lines = (["noise from arm C", "more noise"]
             + _banner("26.39", complete=True)
             + ["interleaved arm C line"]
             + _banner("26.39", complete=False))          # newest, truncated
    _utf16_journal(tmp_path / "MQL5" / "Logs" / "20260916.log", lines)
    monkeypatch.setattr(glr, "FB9A", str(tmp_path))
    monkeypatch.setattr(glr, "_repo_app_version", lambda: "26.39")
    block, where = glr.latest_banner()
    assert "2 init banner(s) that day" in where
    result = glr.check_banner_strings()
    assert all(not e.startswith("MISS") for e in result["evidence"]), result["evidence"]
    assert result["status"] == "PASS", result["evidence"]


def test_version_check_reads_the_newest_banner(tmp_path, monkeypatch) -> None:
    lines = _banner("26.39", complete=True) + _banner("26.35", complete=True)
    _utf16_journal(tmp_path / "MQL5" / "Logs" / "20260916.log", lines)
    monkeypatch.setattr(glr, "FB9A", str(tmp_path))
    # repo says 26.40 -> the NEWEST banner (26.35) must fail the version check
    monkeypatch.setattr(glr, "_repo_app_version", lambda: "26.40")
    result = glr.check_banner_strings()
    assert result["status"] == "FAIL"
    assert any("banner v26.35" in e and "MISMATCH" in e
               for e in result["evidence"]), result["evidence"]


def test_version_check_passes_when_newest_matches_repo(tmp_path, monkeypatch) -> None:
    _utf16_journal(tmp_path / "MQL5" / "Logs" / "20260916.log",
                   _banner("26.40", complete=True))
    monkeypatch.setattr(glr, "FB9A", str(tmp_path))
    monkeypatch.setattr(glr, "_repo_app_version", lambda: "26.40")
    result = glr.check_banner_strings()
    assert result["status"] == "PASS", result["evidence"]
    assert any("banner v26.40" in e and "OK match" in e for e in result["evidence"])


def test_discriminator_must_be_present_in_paper_banner(tmp_path, monkeypatch) -> None:
    # A paper banner without PAPER MODE: means the live absence-check would
    # prove nothing — the rehearsal must refuse to bless it.
    lines = [l for l in _banner("26.40", complete=True) if "PAPER MODE:" not in l]
    _utf16_journal(tmp_path / "MQL5" / "Logs" / "20260916.log", lines)
    monkeypatch.setattr(glr, "FB9A", str(tmp_path))
    monkeypatch.setattr(glr, "_repo_app_version", lambda: "26.40")
    result = glr.check_banner_strings()
    assert result["status"] == "FAIL"
    assert any("absence-check would prove nothing" in e for e in result["evidence"])


def test_no_journals_and_no_banner_fail_loudly(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(glr, "FB9A", str(tmp_path))
    assert glr.latest_banner()[0] is None
    assert glr.check_banner_strings()["status"] == "FAIL"
    _utf16_journal(tmp_path / "MQL5" / "Logs" / "20260916.log", ["only arm C noise here"])
    assert glr.check_banner_strings()["status"] == "FAIL"


def test_repo_preset_check_refuses_a_stub(tmp_path, monkeypatch) -> None:
    stub = tmp_path / "MitemshubAI_VOL75_LIVE.set"
    stub.write_text("; stub\nInpLiveExecution=true\nInpMagic=7788075\n")
    monkeypatch.setattr(glr, "REPO_LIVE_SET", str(stub))
    result = glr.check_repo_preset()
    assert result["status"] == "FAIL"
    assert any("InpTpMult" in e and "MISMATCH" in e for e in result["evidence"])


def test_repo_preset_check_passes_on_the_real_certified_set() -> None:
    # The real repo LIVE preset must carry the certified tp18 geometry —
    # the rehearsal's whole reason for existing (2026-09-16 stub finding).
    result = glr.check_repo_preset()
    assert result["status"] == "PASS", result["evidence"]


def test_rehearsal_never_mutates_a_terminal() -> None:
    # Structural pin on the read-only contract: enumerate every subprocess the
    # tool executes and allow exactly the two read-only ones (the process
    # query and the artifacts verifier). Mentioning sync-mt5.ps1 inside an
    # operator remediation MESSAGE is fine — running it is not.
    import re as _re
    src = (REPO / "scripts" / "go_live_rehearsal.py").read_text(encoding="utf-8")
    for forbidden in ("taskkill", "Stop-Process", "Unregister",
                      "Register-ScheduledTask", "sync-mt5.ps1",
                      "terminal64.exe /config", "Restart-Service"):
        # forbidden only as an EXECUTED command, never inside f-string prose
        for m in _re.finditer(r"subprocess\.(?:run|Popen|check_output)\(([^)]*)\)", src,
                              _re.S):
            assert forbidden not in m.group(1), f"subprocess executes {forbidden}"
    executed = _re.findall(r"subprocess\.run\(\s*\[?([^\]]+)\]?,?\s*capture_output", src, _re.S)
    assert any("Get-CimInstance" in c for c in executed), "process query expected"
    assert any("verify_go_live_artifacts.py" in c for c in executed), "verifier call expected"
    assert len(executed) == 2, f"unexpected extra subprocesses: {executed}"
