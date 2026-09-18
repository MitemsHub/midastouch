"""Offline tests for the forward-test accrual tracker (all arms).

Pins the pre-registered verdict mapping (docs/ARM_D_FORWARD_TEST.md, frozen
2026-09-16; arm E freezes the same values verbatim per its pre-draft §4), the
ARMS registry itself, the idempotent one-row-per-day-per-arm contract, the
drawdown math, the arm-E pre-start fail-closed path, and the paper_weekly
wiring. Synthetic ledgers only — the live ledger belongs to the EA, never to
a test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import armd_accrual as acc  # noqa: E402


# --- verdict mapping (frozen; changing these values is an amendment) ----------

def _metrics(n: int, total_r: float, dd: float, mean_r: float | None = None) -> dict:
    return {"n": n, "total_r": total_r, "mean_r": (mean_r if mean_r is not None
                                                   else (total_r / n if n else 0.0)),
            "wins": 0, "max_dd_pct": dd, "last_close_epoch": None}


def test_below_60_trades_is_never_a_verdict_only_continue() -> None:
    assert acc.verdict(_metrics(59, +100.0, 0.0)) == "CONTINUE"
    assert acc.verdict(_metrics(0, 0.0, 0.0)) == "CONTINUE"


def test_validated_requires_every_gate() -> None:
    assert acc.verdict(_metrics(60, +3.0, 24.9, 0.05)) == "VALIDATED"
    # each gate alone fails it
    assert acc.verdict(_metrics(60, -3.0, 10.0, 0.05)) == "REJECTED"   # totalR<0
    assert acc.verdict(_metrics(60, +3.0, 10.0, 0.0)) == "REJECTED"    # meanR<=0
    # meanR in (0, 0.05) with positive totalR and calm DD is the second frozen
    # CONTINUE band: positive but not proven, so the window keeps accruing.
    assert acc.verdict(_metrics(60, +3.0, 10.0, 0.049)) == "CONTINUE"


def test_dd_between_25_and_30_with_positive_r_is_the_frozen_continue_zone() -> None:
    """The frozen mapping leaves (25%, 30%] drawdown with positive R ambiguous:
    not VALIDATED (DD over the line) yet not REJECTED (abort line is 30%). It
    keeps accruing until DD resolves to one side — pinned verbatim."""
    assert acc.verdict(_metrics(60, +3.0, 25.1, 0.05)) == "CONTINUE"
    assert acc.verdict(_metrics(60, +3.0, 30.0, 0.05)) == "CONTINUE"


def test_abort_line_is_the_30pct_drawdown() -> None:
    assert acc.verdict(_metrics(60, +10.0, 30.1, 0.10)) == "REJECTED"
    assert acc.verdict(_metrics(60, +10.0, 30.0, 0.10)) == "CONTINUE"  # exactly on line


# --- parsing and drawdown math ------------------------------------------------

def test_parse_reads_only_close_rows_and_computes_dd(tmp_path, monkeypatch) -> None:
    ledger = tmp_path / "ledger.csv"
    # veq path: 50 -> 55 (peak) -> 49.4 (10% dd off peak) -> 60
    ledger.write_text(
        "ERA,26.40,1789494700,pertick-fills\n"
        "CLOSE,1000,1,0,0,+1.00,x,50.0\n"
        "OPEN,900,1,0,0\n"
        "CLOSE,2000,1,0,0,+1.00,x,55.0\n"
        "CLOSE,3000,1,0,0,-1.20,x,49.4\n"
        "CLOSE,4000,1,0,0,+2.00,x,60.0\n")
    m = acc.parse(str(ledger))
    assert m["n"] == 4
    assert abs(m["total_r"] - 2.80) < 1e-9
    assert abs(m["mean_r"] - 0.70) < 1e-9
    assert abs(m["max_dd_pct"] - 10.1818) < 0.01   # (55 - 49.4) / 55
    assert m["last_close_epoch"] == 4000


def test_empty_ledger_gives_a_zero_continue_row(tmp_path) -> None:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("ERA,26.40,1789494700,pertick-fills\n")
    m = acc.parse(str(ledger))
    assert m["n"] == 0 and m["total_r"] == 0 and m["last_close_epoch"] is None
    assert acc.verdict(m) == "CONTINUE"


# --- accrue(): idempotency and artifact shape ---------------------------------

def test_accrue_appends_once_per_day_then_keeps_the_first_row(tmp_path, monkeypatch) -> None:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("CLOSE,1000,1,0,0,+1.00,x,50.0\n")
    monkeypatch.setattr(acc, "ledger_path", lambda arm="D": str(ledger))
    monkeypatch.setitem(acc.ARMS, "D", {**acc.ARMS["D"],
                                         "artifact": str(tmp_path / "accrual.jsonl"),
                                         "start": "2026-01-01"})

    first = acc.accrue(append=True)
    assert first["appended"] is True and first["row"]["n"] == 1
    second = acc.accrue(append=True)          # same day: no new write
    assert second["appended"] is False
    rows = [json.loads(l) for l in (tmp_path / "accrual.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["n"] == 1

    ledger.write_text(ledger.read_text() + "CLOSE,2000,1,0,0,+1.00,x,51.0\n")
    forced = acc.accrue(append=True, force=True)   # --force replaces today's row
    assert forced["appended"] is True and forced["row"]["n"] == 2
    rows = [json.loads(l) for l in (tmp_path / "accrual.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["n"] == 2


def test_accrue_projects_eta_from_the_accrual_rate(tmp_path, monkeypatch) -> None:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("CLOSE,1000,1,0,0,+1.00,x,50.0\n" * 10)
    monkeypatch.setattr(acc, "ledger_path", lambda arm="D": str(ledger))
    monkeypatch.setitem(acc.ARMS, "D", {**acc.ARMS["D"],
                                         "artifact": str(tmp_path / "accrual.jsonl"),
                                         "start": "2026-01-01"})
    a = acc.accrue(append=False)
    assert a["days"] >= 1 and a["eta_days"] > 0    # 10 trades banked, 50 to go


def test_missing_ledger_raises_systemexit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(acc, "ledger_path",
                        lambda arm="D": (_ for _ in ()).throw(SystemExit("no arm-D ledger")))
    raised = False
    try:
        acc.accrue(append=False)
    except SystemExit:
        raised = True
    assert raised, "a missing ledger must fail loudly, never as a zero row"


# --- the ARMS registry: frozen citations and the arm-E pre-start state --------

def test_arms_registry_is_frozen() -> None:
    """The registry is an amendment surface: values pinned verbatim."""
    assert set(acc.ARMS) == {"D", "A2"}
    d, a2 = acc.ARMS["D"], acc.ARMS["A2"]
    assert d["doc"] == "docs/ARM_D_FORWARD_TEST.md"
    assert d["start"] == "2026-09-16"
    assert a2["start"] is None, "arm A2 must not open its window from the registry"
    assert a2["doc"] == "docs/ARM_A2_RESTART.md"
    assert a2["gates"] == d["gates"], "A2 freezes arm-D's gate values verbatim"
    assert a2["gates"] is not d["gates"], "each arm amends its own gates only"
    assert "_A2.csv" in a2["ledger_glob"] and "_D.csv" in d["ledger_glob"]
    assert d["artifact"].endswith("ARMD_ACCRUAL.jsonl")
    assert a2["artifact"].endswith("ARMA2_ACCRUAL.jsonl")


def test_arm_a2_pre_start_fails_closed_on_missing_ledger(tmp_path, monkeypatch) -> None:
    """Before start day, arm A2's ledger cannot exist; the accrual must refuse
    loudly (SystemExit), never emit a zero row or start the clock."""
    monkeypatch.setitem(acc.ARMS, "A2", {**acc.ARMS["A2"],
                                          "ledger_glob": str(tmp_path / "no_ledger_A2.csv"),
                                          "artifact": str(tmp_path / "arma2.jsonl")})
    raised = False
    try:
        acc.accrue(append=True, arm="A2")
    except SystemExit:
        raised = True
    assert raised
    assert not (tmp_path / "arma2.jsonl").exists(), "no artifact row before start day"


def test_arm_a2_first_accrual_opens_the_window_and_stamps_it(tmp_path, monkeypatch) -> None:
    """Start day (per ARM_A2_RESTART §2): the first ledger's first accrual
    records window_start=today in-row and the clock runs from that day."""
    ledger = tmp_path / "MitemshubAI_paper_Volatility_75_Index_A2.csv"
    ledger.write_text("CLOSE,1000,1,0,0,+1.00,x,50.0\n")
    monkeypatch.setitem(acc.ARMS, "A2", {**acc.ARMS["A2"],
                                          "ledger_glob": str(ledger),
                                          "artifact": str(tmp_path / "arma2.jsonl")})
    a = acc.accrue(append=True, arm="A2")
    assert a["arm"] == "A2" and a["row"]["arm"] == "A2"
    assert a["row"]["window_start"] == a["row"]["date"]
    assert a["days"] == 1 and a["row"]["n"] == 1
    # same-day re-read: idempotent, prior row (with window_start) retained
    b = acc.accrue(append=True, arm="A2")
    assert b["appended"] is False and b["row"]["window_start"] == a["row"]["date"]


def test_arms_write_separate_artifacts_and_stamp_rows(tmp_path, monkeypatch) -> None:
    """Independent windows must never blend: one artifact per arm, arm tag in
    every row."""
    led_d = tmp_path / "led_D.csv"
    led_a2 = tmp_path / "led_A2.csv"
    led_d.write_text("CLOSE,1000,1,0,0,+1.00,x,50.0\nCLOSE,2000,1,0,0,+1.00,x,51.0\n")
    led_a2.write_text("CLOSE,1000,1,0,0,-0.50,x,50.0\n")
    monkeypatch.setattr(acc, "ledger_path",
                        lambda arm="D": str(led_d if arm == "D" else led_a2))
    art_d = tmp_path / "ARMD.jsonl"
    art_a2 = tmp_path / "ARMA2.jsonl"
    monkeypatch.setitem(acc.ARMS, "D", {**acc.ARMS["D"], "artifact": str(art_d),
                                         "start": "2026-01-01"})
    monkeypatch.setitem(acc.ARMS, "A2", {**acc.ARMS["A2"], "artifact": str(art_a2)})
    d = acc.accrue(append=True, arm="D")
    e = acc.accrue(append=True, arm="A2")
    assert d["row"]["arm"] == "D" and e["row"]["arm"] == "A2"
    assert d["row"]["n"] == 2 and e["row"]["n"] == 1
    assert art_d.exists() and art_a2.exists()
    rows_d = [json.loads(l) for l in art_d.read_text().splitlines()]
    rows_e = [json.loads(l) for l in art_a2.read_text().splitlines()]
    assert all(r["arm"] == "D" for r in rows_d)
    assert all(r["arm"] == "A2" for r in rows_e)


# --- the weekly wiring ---------------------------------------------------------

def test_paper_weekly_has_the_accrual_leg_and_survival_catch() -> None:
    src = (REPO / "scripts" / "paper_weekly.py").read_text(encoding="utf-8")
    assert "from armd_accrual import ARMS, accrue" in src, \
        "the weekly leg must iterate the registry, not a hardcoded arm"
    assert "for arm in sorted(ARMS)" in src
    assert "except SystemExit" in src, "a pre-start arm must not kill the weekly leg"
    assert 'report["sections"]["accrual"]' in src, \
        "section renamed to accrual (per-arm); armd_accrual key retired"
    assert "armd_accrual\"] = sec6" not in src
    assert "VALIDATED" in src and "REJECTED" in src, \
        "the verdict must propagate into NEXT ACTIONS"
    assert "arm-{arm} forward test" in src, \
        "NEXT ACTIONS must name the arm the verdict belongs to"
