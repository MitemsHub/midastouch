"""Offline tests for the MIDASTOUCH §13 monthly verdict tool.

Pins the frozen §13/Amendment-4 gate VALUES (docs/MIDASTOUCH_PROTOCOL.md,
2026-09-17 — a change here must fail until the protocol amends), the full
verdict mapping at every boundary, the drawdown math on the CLOSE-veq path,
the structural-abort evidence chain ([3b] preset identity, §12 watchdog
escalation, EA version change, corrupt rows), the BOTH-DIRECTIONS suppression
rule (a polluted window shows CONTINUE-UNPROVEN, never VALIDATED or
REJECTED), tag-driven discovery with loud gaps, and the wiring contracts
(scripts/era.py family rule, the [3b] identity check, paper_weekly [7]).
Synthetic ledgers and sandbox charts only — the live ledgers belong to the
EA, never to a test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import era  # noqa: E402
import midas_verdict as mv  # noqa: E402

ERA_ROW = "ERA,MIDAS1.10,1789651864,pertick-fills"


# --- the frozen gate values are the protocol rulebook --------------------------

def test_frozen_gate_values_are_the_protocol_rulebook() -> None:
    assert mv.MIN_N == 60
    assert mv.DD_MAX == 25.0
    assert mv.DD_ABORT == 30.0
    assert mv.MEAN_R_MIN == 0.05
    assert mv.GATES == {"MIN_N": 60, "DD_MAX": 25.0, "DD_ABORT": 30.0,
                        "MEAN_R_MIN": 0.05}
    assert mv.PROTOCOL_DOC == "docs/MIDASTOUCH_PROTOCOL.md"
    assert set(mv.VERDICTS) == {"VALIDATED", "REJECTED", "CONTINUE-UNPROVEN"}


# --- the verdict mapping, every boundary ---------------------------------------

def _m(n: int, total_r: float, dd: float, mean_r: float | None = None) -> dict:
    return {"n": n, "total_r": total_r, "max_dd_pct": dd,
            "mean_r": mean_r if mean_r is not None else (total_r / n if n else 0.0)}


def test_below_60_trades_is_never_a_verdict_only_continue() -> None:
    assert mv.verdict(**_m(59, +100.0, 0.0)) == mv.CONTINUE
    assert mv.verdict(**_m(0, 0.0, 0.0)) == mv.CONTINUE
    assert mv.verdict(**_m(1, -100.0, 90.0)) == mv.CONTINUE, \
        "the n-gate comes first: nothing judges a young window, even terribly"


def test_validated_requires_every_gate() -> None:
    assert mv.verdict(**_m(60, +3.0, 24.9, 0.05)) == mv.VALIDATED
    assert mv.verdict(**_m(60, +3.0, 25.0, 0.05)) == mv.VALIDATED, "DD<=25% inclusive at the line"
    assert mv.verdict(**_m(60, +3.0, 10.0, 0.06)) == mv.VALIDATED
    # each gate alone fails it
    assert mv.verdict(**_m(60, -3.0, 10.0, 0.05)) == mv.REJECTED, "totalR<0"
    assert mv.verdict(**_m(60, +3.0, 10.0, 0.0)) == mv.REJECTED, "meanR<=0"


def test_meanr_gray_band_is_the_frozen_continue_zone() -> None:
    assert mv.verdict(**_m(60, +3.0, 10.0, 0.049)) == mv.CONTINUE
    assert mv.verdict(**_m(60, +3.0, 10.0, 0.05)) == mv.VALIDATED
    assert mv.verdict(**_m(60, 0.0, 10.0, 0.0)) == mv.REJECTED, \
        "totalR==0 / meanR==0 is the meanR<=0 line, not a gray zone"


def test_dd_gray_band_25_to_30_is_continue() -> None:
    assert mv.verdict(**_m(60, +3.0, 25.1, 0.05)) == mv.CONTINUE
    assert mv.verdict(**_m(60, +3.0, 30.0, 0.05)) == mv.CONTINUE


def test_abort_line_is_30pct_drawdown() -> None:
    assert mv.verdict(**_m(60, +10.0, 30.1, 0.10)) == mv.REJECTED
    assert mv.verdict(**_m(60, +10.0, 30.0, 0.10)) == mv.CONTINUE, "exactly on the line keeps accruing"


# --- ledger statistics ----------------------------------------------------------

def _write(tmp_path: Path, rows: list[str], name: str = "MIDASTOUCH_paper_XAUUSDmicro_M1.csv") -> str:
    p = tmp_path / name
    p.write_text("".join(r + "\n" for r in rows), encoding="utf-8")
    return str(p)


def test_statistics_read_close_rows_and_compute_dd(tmp_path) -> None:
    led = _write(tmp_path, [
        ERA_ROW,
        "EQ,50.00",
        "CLOSE,1000,1,TARGET,4355.00000,+1.00,5.00,55.00",
        "CLOSE,2000,2,SL,4345.00000,-1.00,-5.00,49.40",      # 10% off the 55 peak
        "CLOSE,3000,3,TARGET,4360.00000,+2.00,10.00,60.00",
        "OPEN,3500,9,4354.00000,0,0,0,0,0,0,0,PAPER",        # live trade: ignored
        "EQ,60.00",
    ])
    s = mv.arm_statistics(led)
    assert s["n"] == 3
    assert abs(s["total_r"] - 2.0) < 1e-9
    assert abs(s["mean_r"] - 2.0 / 3) < 1e-4
    assert s["wins"] == 2
    assert abs(s["max_dd_pct"] - (55.0 - 49.4) / 55.0 * 100) < 0.01
    assert s["last_close_epoch"] == 3000
    assert s["problems"] == []
    assert s["era_versions"] == ["MIDAS1.10"]


def test_midastouch_family_is_per_tick_in_all_eras(tmp_path) -> None:
    """The gold engine filled per tick from birth: rows above and below the
    stamp are the same fill regime, so both count (era.py family rule)."""
    led = _write(tmp_path, [
        "CLOSE,100,1,TARGET,1.0,+1.00,5.00,55.00",            # before any stamp
        f"ERA,MIDAS1.10,{era.ERA_EPOCH},pertick-fills",
        "CLOSE,200,2,TARGET,1.0,+1.00,5.00,60.00",            # after the stamp
    ])
    s = mv.arm_statistics(led)
    assert s["n"] == 2
    assert s["era_versions"] == ["MIDAS1.10"]


def test_ea_version_change_is_a_structural_abort(tmp_path) -> None:
    led = _write(tmp_path, [
        "ERA,MIDAS1.09,1789651864,pertick-fills",
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        "ERA,MIDAS1.10,1789652000,pertick-fills",
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
    ])
    s = mv.arm_statistics(led)
    assert any("version change" in p for p in s["problems"])
    assert set(s["era_versions"]) == {"MIDAS1.09", "MIDAS1.10"}


# --- V2 register §1: the telemetry-only exemption, both directions --------------
# (docs/MIDASTOUCH_V2_REGISTER.md §1, 2026-09-17: a build stamped
# telemetry-only-per-V2-register cannot change any CLOSE row's R nor the set
# of trades given identical ticks; the exemption lives on the FIRST ERA row
# of the NEW version, exactly where the v1.13 writer stamps it.)

TELE_ROW = f"ERA,MIDAS1.13,{{epoch}},pertick-fills+telemetry-only-per-V2-register"


def test_exempted_transition_does_not_abort_and_records_evidence(tmp_path) -> None:
    """A cited telemetry-only version change continues the window — and the
    transition still appears in the evidence record (never laundered away)."""
    led = _write(tmp_path, [
        "ERA,MIDAS1.10,1789651864,pertick-fills",
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        TELE_ROW.format(epoch=1789652000),
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
    ])
    s = mv.arm_statistics(led)
    assert s["problems"] == [], "the §1 class is never-abort by the register"
    assert set(s["era_versions"]) == {"MIDAS1.10", "MIDAS1.13"}
    assert s["n"] == 2, "trades from both sides of the transition count"
    t = s["version_transitions"]
    assert t == [{"from": "MIDAS1.10", "to": "MIDAS1.13",
                  "line": 3, "telemetry_exempt": True,
                  "note": "pertick-fills+telemetry-only-per-V2-register"}]


def test_uncited_transition_still_aborts(tmp_path) -> None:
    """The standing rule is a license for the cited class only — a plain
    version change with no citation remains abort-grade, unchanged."""
    led = _write(tmp_path, [
        "ERA,MIDAS1.10,1789651864,pertick-fills",
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        "ERA,MIDAS1.13,1789652000,pertick-fills",
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
    ])
    s = mv.arm_statistics(led)
    assert any("version change" in p and "MIDAS1.10->MIDAS1.13" in p
               for p in s["problems"])
    assert s["version_transitions"][0]["telemetry_exempt"] is False


def test_citation_on_a_non_transition_stamp_is_ignored(tmp_path) -> None:
    """Citing a version that was already running proves nothing about when
    the binary changed: the restart re-stamp below the transition carries the
    citation but the transition stamp does not, so the window aborts."""
    led = _write(tmp_path, [
        "ERA,MIDAS1.10,1789651864,pertick-fills",
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        "ERA,MIDAS1.13,1789652000,pertick-fills",               # transition: UNCITED
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
        TELE_ROW.format(epoch=1789653000),                      # restart re-stamp
        "CLOSE,3000,3,TARGET,1.0,+1.00,5.00,55.00",
    ])
    s = mv.arm_statistics(led)
    assert any("version change" in p for p in s["problems"])
    assert len(s["version_transitions"]) == 1


def test_only_the_uncited_leg_of_a_chain_aborts(tmp_path) -> None:
    """The exemption does not launder a ledger: an exempted 1.10→1.13 and a
    later uncited 1.13→1.14 abort on the 1.13→1.14 leg only."""
    led = _write(tmp_path, [
        "ERA,MIDAS1.10,1789651864,pertick-fills",
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        TELE_ROW.format(epoch=1789652000),
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
        "ERA,MIDAS1.14,1789653000,pertick-fills",               # uncited leg
        "CLOSE,3000,3,TARGET,1.0,+1.00,5.00,55.00",
    ])
    s = mv.arm_statistics(led)
    assert any("version change" in p and "MIDAS1.13->MIDAS1.14" in p
               for p in s["problems"])
    assert not any("MIDAS1.10->MIDAS1.13" in p for p in s["problems"])
    assert len(s["version_transitions"]) == 2
    assert [t["telemetry_exempt"] for t in s["version_transitions"]] == [True, False]


def test_multi_line_note_or_extra_columns_still_exempt(tmp_path) -> None:
    """Substring match on the note field: a future longer note (or extra
    appended columns) keeps the exemption — the writer owns the format."""
    led = _write(tmp_path, [
        "ERA,MIDAS1.10,1789651864,pertick-fills",
        "ERA,MIDAS1.13,1789652000,pertick-fills+telemetry-only-per-V2-register+future",
    ])
    s = mv.arm_statistics(led)
    assert s["problems"] == []
    assert s["version_transitions"][0]["telemetry_exempt"] is True


def test_rollback_aborts_because_the_old_binary_never_cites(tmp_path) -> None:
    """Rollback (1.13 → 1.10) aborts automatically and needs no special rule:
    the v1.10 binary predates the register, its source contains no citation
    string, so its stamp is plain — an uncited transition. Fail-closed by
    construction, not by direction-checking."""
    led = _write(tmp_path, [
        "ERA,MIDAS1.13,1789651864,pertick-fills+telemetry-only-per-V2-register",
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        "ERA,MIDAS1.10,1789652000,pertick-fills",   # what the old binary really stamps
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
    ])
    s = mv.arm_statistics(led)
    assert any("version change" in p and "MIDAS1.13->MIDAS1.10" in p
               for p in s["problems"])
    assert s["version_transitions"][0]["telemetry_exempt"] is False


def test_fresh_ledger_wholly_on_the_telemetry_build_is_a_single_version(tmp_path) -> None:
    """A fresh §13 window started on the telemetry build has one version and
    no transitions — nothing to exempt, nothing to abort (the v1.13 note
    suffix itself must not trip the single-version read)."""
    led = _write(tmp_path, [
        TELE_ROW.format(epoch=era.ERA_EPOCH),
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
    ])
    s = mv.arm_statistics(led)
    assert s["problems"] == []
    assert s["era_versions"] == ["MIDAS1.13"]
    assert s["version_transitions"] == []
    assert s["n"] == 2


def test_malformed_stamp_between_versions_fails_closed(tmp_path) -> None:
    """A truncated stamp (no note field) is not a citation — the transition
    through it aborts rather than guessing provenance it cannot verify."""
    led = _write(tmp_path, [
        "ERA,MIDAS1.10,1789651864,pertick-fills",
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        "ERA,MIDAS1.13,1789652000",                              # note missing
        "CLOSE,2000,2,TARGET,1.0,+1.00,5.00,60.00",
    ])
    s = mv.arm_statistics(led)
    assert any("version change" in p for p in s["problems"])
    assert s["version_transitions"][0]["telemetry_exempt"] is False



def test_corrupt_rows_abort_the_read_never_guess_n(tmp_path) -> None:
    led = _write(tmp_path, [
        ERA_ROW,
        "CLOSE,1000,1,TARGET,1.0",                              # too short
        "CLOSE,1001,2,TARGET,1.0,+1.00,5.00,55.00",
        "CLOSE,notanepoch,3,TARGET,1.0,+1.00,5.00,55.00",       # unparseable
    ])
    s = mv.arm_statistics(led)
    assert len(s["problems"]) == 2
    assert s["n"] == 1


def test_nonpositive_veq_row_is_reported_and_excluded_from_dd(tmp_path) -> None:
    led = _write(tmp_path, [
        ERA_ROW,
        "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00",
        "CLOSE,2000,2,SL,1.0,-1.00,-5.00,49.50",
        "CLOSE,3000,3,SL,1.0,-1.00,-5.00,0.00",                 # blew through the book?
    ])
    s = mv.arm_statistics(led)
    assert any("veq" in p for p in s["problems"])
    assert abs(s["max_dd_pct"] - 10.0) < 1e-9, "the 0 row is a pollution flag, not a DD point"


def test_zero_fills_window_reads_zero(tmp_path) -> None:
    led = _write(tmp_path, [ERA_ROW, "EQ,50.00", "EQ,50.00"])
    s = mv.arm_statistics(led)
    assert s["n"] == 0 and s["total_r"] == 0.0 and s["last_close_epoch"] is None


# --- structural-abort evidence (watchdog §12, [3b] preset identity) -------------

def test_pinned_chart_and_healthy_watchdog_is_no_abort(tmp_path, monkeypatch) -> None:
    preset = tmp_path / "MidastouchAI_M1x_gold.set"
    preset.write_text("InpArmTag=M1x\nInpMode=0\nInpLiveExecution=false\n", encoding="utf-8")
    monkeypatch.setattr(mv, "preset_for_tag", lambda tag: str(preset))
    monkeypatch.setattr(mv, "WATCHDOG_STATE", str(tmp_path / "wd_state.json"))
    monkeypatch.setattr(mv, "WATCHDOG_LAST", str(tmp_path / "wd_last.json"))
    (tmp_path / "wd_state.json").write_text(
        json.dumps({"consecutive_restups": 0, "restups_total": 1}), encoding="utf-8")
    chart = tmp_path / "chart.chr"
    chart.write_text("InpArmTag=M1x\nInpMode=0\nInpLiveExecution=false\n", encoding="utf-16")
    pre = mv.preset_abort(str(chart), "M1x")
    assert pre["verdict"] == "OK" and pre["problems"] == []
    assert mv.watchdog_abort()["problems"] == []


def test_preset_drift_is_abort_grade(tmp_path, monkeypatch) -> None:
    preset = tmp_path / "MidastouchAI_M1x_gold.set"
    preset.write_text("InpMode=0\n", encoding="utf-8")
    monkeypatch.setattr(mv, "preset_for_tag", lambda tag: str(preset))
    chart = tmp_path / "chart.chr"
    chart.write_text("InpMode=2\n", encoding="utf-16")
    pre = mv.preset_abort(str(chart), "M1x")
    assert pre["verdict"] == "DRIFT"
    assert any("InpMode=2" in p for p in pre["problems"])


def test_unverifiable_preset_is_abort_grade(tmp_path) -> None:
    """A sandbox tag with no repo .set: fail closed, never a guessed OK."""
    chart = tmp_path / "chart.chr"
    chart.write_text("InpMode=0\n", encoding="utf-16")
    pre = mv.preset_abort(str(chart), "M1zz")
    assert pre["verdict"] == "UNVERIFIABLE" and pre["problems"]


def test_watchdog_escalation_and_drift_are_abort_grade(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mv, "WATCHDOG_STATE", str(tmp_path / "wd_state.json"))
    monkeypatch.setattr(mv, "WATCHDOG_LAST", str(tmp_path / "wd_last.json"))
    (tmp_path / "wd_state.json").write_text(json.dumps({"consecutive_restups": 3}), encoding="utf-8")
    assert any("escalated" in p for p in mv.watchdog_abort()["problems"])
    (tmp_path / "wd_state.json").write_text(json.dumps({"consecutive_restups": 0}), encoding="utf-8")
    (tmp_path / "wd_last.json").write_text(json.dumps({"action": "DRIFT"}), encoding="utf-8")
    assert any("DRIFT" in p for p in mv.watchdog_abort()["problems"])
    (tmp_path / "wd_last.json").write_text(json.dumps({"action": "RESTUP"}), encoding="utf-8")
    assert mv.watchdog_abort()["problems"] == []
    (tmp_path / "wd_state.json").unlink()
    assert any("missing" in p for p in mv.watchdog_abort()["problems"]), \
        "no §12 artifacts = unverifiable liveness = reported, never guessed"


# --- the suppression rule: a polluted window is never judged (both directions) --

def _closes(r: str, veq_start: int, veq_step: int, count: int = 60) -> list[str]:
    rows = []
    for i in range(count):
        rows.append(f"CLOSE,{1000 + i},{i + 1},TARGET,1.0,{r},"
                    f"{float(r):+.2f},{veq_start + veq_step * i}.00")
    return rows


def _sandbox(tmp_path, monkeypatch, ledger_rows: list[str],
             chart_pairs: dict | None = None, preset_pairs: dict | None = None,
             wd_state: dict | None = None, wd_last: dict | None = None,
             tag: str = "M1x") -> dict:
    tmp_path.mkdir(exist_ok=True)
    chart_pairs = chart_pairs if chart_pairs is not None else \
        {"InpMode": "0", "InpLiveExecution": "false"}
    preset_pairs = preset_pairs if preset_pairs is not None else \
        {"InpMode": "0", "InpLiveExecution": "false"}
    preset = tmp_path / f"MidastouchAI_{tag}_gold.set"
    preset.write_text("".join(f"{k}={v}\n" for k, v in preset_pairs.items()), encoding="utf-8")
    monkeypatch.setattr(mv, "preset_for_tag", lambda t: str(preset))
    monkeypatch.setattr(mv, "WATCHDOG_STATE", str(tmp_path / "wd_state.json"))
    monkeypatch.setattr(mv, "WATCHDOG_LAST", str(tmp_path / "wd_last.json"))
    (tmp_path / "wd_state.json").write_text(
        json.dumps(wd_state if wd_state is not None else {"consecutive_restups": 0}),
        encoding="utf-8")
    if wd_last is not None:
        (tmp_path / "wd_last.json").write_text(json.dumps(wd_last), encoding="utf-8")
    chart = tmp_path / f"{tag}.chr"
    chart.write_text("".join(f"{k}={v}\n" for k, v in chart_pairs.items()), encoding="utf-16")
    led = tmp_path / f"MIDASTOUCH_paper_XAUUSDmicro_{tag}.csv"
    led.write_text("".join(r + "\n" for r in ledger_rows), encoding="utf-8")
    return mv.adjudicate(tag, str(led), str(chart))


GOOD_LEDGER = [ERA_ROW] + _closes("+1.00", 51, 1)     # +60R, meanR 1.0, DD 0 -> VALIDATED
BAD_LEDGER = [ERA_ROW] + _closes("0.00", 50, 0)       # 0R, meanR 0, DD 0  -> REJECTED


def test_clean_windows_adjudicate_normally(tmp_path, monkeypatch) -> None:
    good = _sandbox(tmp_path, monkeypatch, GOOD_LEDGER)
    assert good["abort"] is False and good["verdict"] == mv.VALIDATED
    bad = _sandbox(tmp_path / "b", monkeypatch, BAD_LEDGER)
    assert bad["abort"] is False and bad["verdict"] == mv.REJECTED


def test_abort_suppresses_validated_and_rejected_alike(tmp_path, monkeypatch) -> None:
    """§13: a polluted window is never judged. Preset drift must not let a
    VALIDATED through (evidence-laundering) nor a REJECTED (retirement is
    data-backed only — the family always gets its clean window)."""
    good = _sandbox(tmp_path, monkeypatch, GOOD_LEDGER,
                    chart_pairs={"InpMode": "2", "InpLiveExecution": "false"},
                    preset_pairs={"InpMode": "0", "InpLiveExecution": "false"})
    assert good["abort"] is True and good["verdict"] == mv.CONTINUE
    assert any("InpMode" in r for r in good["abort_reasons"])
    bad = _sandbox(tmp_path / "b", monkeypatch, BAD_LEDGER,
                   chart_pairs={"InpMode": "2", "InpLiveExecution": "false"},
                   preset_pairs={"InpMode": "0", "InpLiveExecution": "false"})
    assert bad["abort"] is True and bad["verdict"] == mv.CONTINUE


def test_version_change_aborts_through_adjudicate(tmp_path, monkeypatch) -> None:
    mixed = [ERA_ROW, "ERA,MIDAS1.09,1789651800,pertick-fills"] + _closes("+1.00", 51, 1)
    a = _sandbox(tmp_path, monkeypatch, mixed)
    assert a["abort"] is True and a["verdict"] == mv.CONTINUE
    assert any("version change" in r for r in a["abort_reasons"])


def test_watchdog_escalation_aborts_through_adjudicate(tmp_path, monkeypatch) -> None:
    a = _sandbox(tmp_path, monkeypatch, GOOD_LEDGER,
                 wd_state={"consecutive_restups": 3, "restups_total": 3})
    assert a["abort"] is True and a["verdict"] == mv.CONTINUE
    assert a["verdict"] != mv.VALIDATED, "escalated §12 state cannot bless a window"


def test_adjudicate_always_returns_the_full_evidence_record(tmp_path, monkeypatch) -> None:
    a = _sandbox(tmp_path, monkeypatch, [ERA_ROW,
                                         "CLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00"])
    assert a["tag"] == "M1x" and a["stats"]["n"] == 1
    assert a["gates"] == mv.GATES and a["doc"] == mv.PROTOCOL_DOC
    assert set(a) >= {"tag", "verdict", "abort", "abort_reasons", "stats",
                      "preset", "watchdog", "gates", "doc"}


# --- discovery: tag-driven, loud about gaps --------------------------------------

def _portfolio(tmp_path: Path) -> str:
    files = tmp_path / "MQL5" / "Files"
    files.mkdir(parents=True)
    charts = tmp_path / "MQL5" / "Profiles" / "Charts" / "Default"
    charts.mkdir(parents=True)
    for tag in ("M1", "M1t", "M1orphan"):
        (files / f"MIDASTOUCH_paper_XAUUSDmicro_{tag}.csv").write_text(
            ERA_ROW + "\n", encoding="utf-8")
    for tag in ("M1", "M1t", "M1s"):
        (charts / f"{tag}.chr").write_text(
            f"expert=MidastouchAI\nsymbol=XAUUSDmicro\nInpArmTag={tag}\n",
            encoding="utf-16")
    return str(tmp_path)


def test_discovery_is_tag_driven_and_reports_gaps(tmp_path, capsys) -> None:
    df = _portfolio(tmp_path)
    found = mv.arms(df)
    assert sorted(a["tag"] for a in found) == ["M1", "M1t"]
    assert all(a["chart"] and a["ledger"] for a in found)
    err = capsys.readouterr().err
    assert "M1s" in err, "chart without a ledger is a loud skip, not silence"
    assert "orphan" in err, "ledger no chart claims is reported, not judged"


def test_run_single_missing_tag_fails_loud(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mv, "arms", lambda df=None: [])
    with pytest.raises(SystemExit):
        mv.run(tag="M1")
    with pytest.raises(SystemExit):
        mv.run()                          # nothing initialized anywhere


# --- wiring contracts -------------------------------------------------------------

def test_era_registry_knows_the_midastouch_family() -> None:
    assert era.era_for_engine("midastouchai", 0) == era.ERA_POST
    assert era.era_for_engine("MidastouchAI", era.ERA_EPOCH - 10**9) == era.ERA_POST
    assert era.era_for_engine("mitemshubai", era.ERA_EPOCH - 1) == era.ERA_PRE, \
        "the sibling family's boundary rule is untouched"


def test_3b_identity_check_is_the_same_function_the_tool_uses() -> None:
    import morning_status
    assert mv.ms.preset_identity is morning_status.preset_identity


def test_paper_weekly_carries_the_monthly_verdict_leg() -> None:
    src = (REPO / "scripts" / "paper_weekly.py").read_text(encoding="utf-8")
    assert "from midas_verdict import run as midas_verdict_run" in src
    assert '"monthly_verdict"' in src
    assert "except SystemExit" in src, \
        "a terminal with no gold ledgers must not kill the weekly leg"


# --- CLI smoke ---------------------------------------------------------------------

def test_cli_json_smoke_reports_full_evidence(tmp_path, monkeypatch, capsys) -> None:
    led = tmp_path / "MIDASTOUCH_paper_XAUUSDmicro_M1.csv"
    led.write_text(ERA_ROW + "\nCLOSE,1000,1,TARGET,1.0,+1.00,5.00,55.00\n", encoding="utf-8")
    monkeypatch.setattr(mv, "arms", lambda df=None: [
        {"tag": "M1", "ledger": str(led),
         "chart": str(tmp_path / "absent.chr")}])   # chart gone: UNVERIFIABLE abort
    monkeypatch.setattr(mv, "WATCHDOG_STATE", str(tmp_path / "wd_state.json"))
    monkeypatch.setattr(mv, "WATCHDOG_LAST", str(tmp_path / "wd_last.json"))
    (tmp_path / "wd_state.json").write_text(json.dumps({"consecutive_restups": 0}),
                                            encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["midas_verdict.py", "--json"])
    mv.main()
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    arm = payload["arms"]["M1"]
    assert arm["stats"]["n"] == 1
    assert arm["preset"]["verdict"] == "UNVERIFIABLE"
    assert arm["abort"] is True and arm["verdict"] == mv.CONTINUE
    assert payload["gates"] == mv.GATES
