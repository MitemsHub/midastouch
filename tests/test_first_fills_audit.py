"""The first-fills audit: the arm's first real trade is graded by a rule written before it.

WHY THIS FILE EXISTS. `scripts/midas_first_fills_audit.py` is the tool that decides whether the
arm's first real fill obeyed the frozen rules — protocol discipline says the acceptance rule is
written before the evidence it grades, so trade #1 is audited exactly like trade #150. It had no
test file, and running it on a *correct* two-trade ledger showed why that mattered: it reported two
bogus `EQ snapshot != running veq` problems (the equity path never advanced at a close) and one
VIOLATION on trade #1 (`close veq 25020.00 != prev 50.00 + pnl`, a baseline hardcoded to the RETIRED
micro arm's $50 virtual start while this arm's ledger opens at `EQ,25000.00`). Its session default
was the retired arm's 12-16 UTC gate, so every 06-11 UTC entry of the current arm was a "violation".

So the pins come in two directions, and both are needed: a correct ledger must come out clean, and
each check must still FIRE on the defect it exists to catch. A guard that stops complaining is not
the same as a guard that works.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import midas_first_fills_audit as ffa  # noqa: E402

OPEN_A = "OPEN,1790000200,7,1,4000.00000,3990.00000,4020.00000,0.10,10.00,10.00000,720,U25,10.0,0.2"
CLOSE_A = "CLOSE,1790001000,7,TARGET,4020.00000,2.000,20.00,25020.00,0.20000,0.0,2.0,0,1"
OPEN_B = "OPEN,1790010000,8,-1,4001.00000,4011.00000,3981.00000,0.10,10.00,10.00000,720,U25,10.0,0.2"
CLOSE_B = "CLOSE,1790020000,8,STOP,4011.00000,-1.000,-10.00,25010.00,0.20000,0.0,2.0,0,1"


def _ledger(tmp_path: Path, rows: list[str], name: str = "MIDASTOUCH_paper_XAUUSD_U25.csv") -> Path:
    p = tmp_path / name
    p.write_text("ERA,MIDAS1.19,1789996684,synthetic\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def _correct_rows() -> list[str]:
    """Two closed trades, opening at $25,000, with the heartbeats a real ledger writes."""
    return ["EQ,25000.00", OPEN_A, "EQ,25000.00", CLOSE_A, "EQ,25020.00",
            OPEN_B, "EQ,25020.00", CLOSE_B, "EQ,25010.00"]


def _run(tmp_path: Path, rows: list[str]) -> int:
    return ffa.run(str(_ledger(tmp_path, rows)), None, 2.0, str(ROOT / "data" / "forex" / "xauusd"),
                   False)


def test_a_correct_ledger_comes_out_clean(tmp_path):
    """The regression: a compliant two-trade ledger must produce no problems and no violations."""
    led = ffa.read_ledger(str(_ledger(tmp_path, _correct_rows())))
    assert led["problems"] == []
    assert [t["r"] for t in led["trades"]] == [2.0, -1.0]
    assert _run(tmp_path, _correct_rows()) == 0


def test_the_equity_chain_starts_where_the_ledger_says_it_does(tmp_path):
    """Not at the retired micro arm's $50: at the ledger's own opening row."""
    assert ffa.read_ledger(str(_ledger(tmp_path, _correct_rows())))["veq_start"] == 25000.00
    micro = _ledger(tmp_path, ["EQ,50.00", CLOSE_A], "micro.csv")
    assert ffa.read_ledger(str(micro))["veq_start"] == 50.00
    # a ledger with no EQ row at all falls back to the first trade's own implied previous equity
    bare = _ledger(tmp_path, [OPEN_A, CLOSE_A], "bare.csv")
    assert ffa.read_ledger(str(bare))["veq_start"] == 25000.00


def test_a_close_row_that_breaks_the_equity_chain_is_still_a_violation(tmp_path):
    """The check the baseline fix touched must still fire when the arithmetic is wrong."""
    broken = [r.replace("25010.00", "25310.00") for r in _correct_rows()]
    assert _run(tmp_path, broken) == 1


def test_a_heartbeat_that_disagrees_with_the_trade_path_is_still_a_problem(tmp_path):
    """The check the advance fix touched must still fire on a real disagreement."""
    rows = ["EQ,25000.00", OPEN_A, CLOSE_A, "EQ,25020.00", "EQ,25999.00"]
    problems = ffa.read_ledger(str(_ledger(tmp_path, rows)))["problems"]
    assert any("EQ snapshot 25999.00" in p for p in problems)


def test_the_session_gate_comes_from_the_arm_preset_not_a_retired_amendment():
    """The gate is a property of the preset, and it must belong to the arm the ledger belongs to."""
    gate = ffa.session_from_preset(str(ROOT / ffa.ARM_PRESET))
    assert gate == (6, 20), "the deployed arm runs 06-20 UTC; a stale literal graded against it"
    import set_chart_preset as scp
    vals = scp.parse_preset(str(ROOT / ffa.ARM_PRESET))
    assert gate == (int(vals["InpSessionStartHour"]), int(vals["InpSessionEndHour"]))
    assert vals["InpArmTag"] == "U25"          # the same arm tag the audit discovers
    assert ffa.DEFAULT_SESSION == (12, 16)     # kept only as the retired arm's explicit choice


def test_an_unreadable_preset_leaves_the_session_check_unverifiable(tmp_path):
    """Refuse rather than grade against a rule the arm may not run."""
    assert ffa.session_from_preset(str(tmp_path / "nope.set")) is None
    trade = {"open_ct": 1790001000, "stop_d": 10.0, "side": 1, "entry": 4000.0,
             "exit": 4020.0, "r": 2.0, "reason": "TARGET", "prev_veq": 25000.0,
             "pnl": 20.0, "close_veq": 25020.0, "ticket": "7"}
    v = ffa.audit_trade(trade, None, 2.0, [], [])
    assert not [x for x in v if x.startswith("SESSION")], "no session gate -> no session verdict"
    assert "UNVERIFIABLE" in trade["frame_note"]


def test_live_rows_in_the_paper_ledger_are_still_contamination(tmp_path):
    rows = _correct_rows() + ["LCLOSE,1790030000,9,STOP,3991.00000,-1.000"]
    problems = ffa.read_ledger(str(_ledger(tmp_path, rows)))["problems"]
    assert any("contamination" in p for p in problems)
    assert _run(tmp_path, rows) == 1
