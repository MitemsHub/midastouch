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
import midas_sweep as S  # noqa: E402


# v2 (2026-09-23, measured repair): the fixture's stops are DERIVED from the data of record
# through the audit's own `expected_stop`, not hardcoded. The original literal rows recorded
# stop 10.0 at entries where the corpus of the day measured 2xATR = 5.0; after the 09-23
# corpus refresh the same stamps measure 28.1/33.4 (crash-week volatility), and a fixture
# whose compliance was frozen to one corpus vintage failed as a "violation". Compliance that
# must survive data refreshes is compliance DERIVED from the data: open at the corpus's first
# stamps, stop = 2xATR as the audit itself measures it, TP/exit/PnL/EQ following geometrically
# (risk 0.10/point side × 2.0R), so every invariant the audit grades holds by construction.


def _open_row(open_ct: int, ticket: int, side: int, entry: float, stop_d: float) -> str:
    sl = entry - side * stop_d
    tp = entry + side * 2.0 * stop_d
    return (f"OPEN,{open_ct},{ticket},{side},{entry:.5f},{sl:.5f},{tp:.5f},"
            f"0.10,{stop_d:.5f},{stop_d:.5f},720,U25,10.0,0.2")


def _close_row(close_ct: int, ticket: int, reason: str, exit_px: float, r: float,
               pnl: float, prev_veq: float) -> str:
    return (f"CLOSE,{close_ct},{ticket},{reason},{exit_px:.5f},{r:.3f},{pnl:.2f},"
            f"{prev_veq + pnl:.2f},0.20000,0.0,{r:.1f},0,1")


def _derived_rows() -> tuple[list[str], list[dict]]:
    """The compliant two-trade ledger, derived from the corpus at import time.

    Returns (rows, trades) where `trades` carries the derived numbers later pins assert
    (the OLD pins asserted literal 25020/25010 equities; the derivation keeps the 25,000
    basis, the +2.0/−1.0 R shape and the $10/point risk, so every assertion in this file
    keeps its meaning while its numbers become corpus-proof).
    """
    h1 = S.load_bars(str(ROOT / "data" / "forex" / "xauusd" / f"XAUUSD_H1{ffa.VENUE_SUFFIX}.csv"))
    h1_atr = S.sma_atr(h1)
    # two stamps inside the session gate (06-20 UTC), deep inside the corpus era, a weekday,
    # away from any DST seam (both server months here are +2): 2026-06-10 10:00Z and 12:00Z
    import datetime as _dt
    base = int(_dt.datetime(2026, 6, 10, 10, 0, tzinfo=_dt.timezone.utc).timestamp())
    oa_ct, ob_ct = base + 900, base + 3 * 3600 + 900
    exp_a, _ = ffa.expected_stop(2.0, h1, h1_atr, oa_ct)
    exp_b, _ = ffa.expected_stop(2.0, h1, h1_atr, ob_ct)
    entry_a, entry_b = 4000.0, 4001.0
    rows = ["EQ,25000.00"]
    meta = []
    prev_veq = 25000.0
    for open_ct, ticket, side, entry, stop_d, reason, r in (
            (oa_ct, 7, 1, entry_a, exp_a, "TARGET", 2.0),
            (ob_ct, 8, -1, entry_b, exp_b, "STOP", -1.0)):
        exit_px = entry + side * r * stop_d
        # pnl = r x risk_d — the EA's own arithmetic (risk budget per trade, here $10),
        # so the +20.00/-10.00 shape holds whatever width the corpus's ATR gives the stop.
        pnl = r * 10.0
        rows.append(_open_row(open_ct, ticket, side, entry, stop_d))
        rows.append(f"EQ,{prev_veq:.2f}")
        rows.append(_close_row(open_ct + 800, ticket, reason, exit_px, r, pnl, prev_veq))
        prev_veq += pnl
        meta.append({"open_ct": open_ct, "ticket": ticket, "stop_d": stop_d,
                     "entry": entry, "exit": exit_px, "r": r, "pnl": pnl,
                     "prev_veq": prev_veq - pnl, "close_veq": prev_veq})
    rows.append(f"EQ,{prev_veq:.2f}")
    return rows, meta


_ROWS, _META = _derived_rows()
OPEN_A, CLOSE_A, OPEN_B, CLOSE_B = (_ROWS[1], _ROWS[3], _ROWS[4], _ROWS[6])


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
