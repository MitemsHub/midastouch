"""Offline tests for the build-parity shadow-window harness.

Pins the frozen verdict taxonomy, the trade-normalization alignment contract
(report deals <-> journal R prints), the §3 input pins, and the pre-terminal
refuses (oos never, research==forward never, unknown window never). The live
terminal is never touched by a test: run_shadow's terminal work is behind
these guards, and the discipline itself is exercised only on real runs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_parity as bp  # noqa: E402


# --- fixtures -----------------------------------------------------------------

def _deal(time: str, side: str, kind: str, price: float, pnl: float = 0.0) -> list[str]:
    """One synthetic report deal row, column-compatible with pair_trades."""
    return [time, "1", "", side, kind, "", f"{price:.2f}", "", "", "", f"{pnl:.2f}"]


def _trades_spec(n: int, r: float = 1.0, jitter: float = 0.0) -> tuple[list[list[str]], list[float]]:
    """n synthetic trades: buy/sell alternating, hourly entries, journal R."""
    deals: list[list[str]] = []
    r_values: list[float] = []
    for i in range(n):
        side = "buy" if i % 2 == 0 else "sell"
        out_side = "sell" if side == "buy" else "buy"
        hour = (i % 24)
        deals.append(_deal(f"2026.01.{i % 28 + 1:02d} {hour:02d}:00:00",
                           side, "in", 100.0 + i))
        deals.append(_deal(f"2026.01.{i % 28 + 1:02d} {hour:02d}:45:00",
                           out_side, "out", 100.0 + i, 10.0 * (1 if i % 2 == 0 else -0.5)))
        r_values.append(round(r + jitter * (1 if i % 2 == 0 else -1), 4))
    return deals, r_values


def _norm(n: int, r: float = 1.0, jitter: float = 0.0) -> list[dict]:
    deals, r_values = _trades_spec(n, r, jitter)
    trades, err = bp.normalize_trades(deals, r_values)
    assert err is None, err
    return trades


# --- normalization contract ----------------------------------------------------

def test_normalize_pairs_deals_and_aligns_journal_r() -> None:
    deals, r_values = _trades_spec(3)
    trades, err = bp.normalize_trades(deals, r_values)
    assert err is None
    assert len(trades) == 3
    assert trades[0]["side"] == "buy"
    assert trades[0]["entry_time"].endswith(":00:00")
    assert trades[0]["r"] == 1.0


def test_normalize_refuses_on_report_journal_disagreement() -> None:
    deals, _ = _trades_spec(3)
    trades, err = bp.normalize_trades(deals, [1.0, 1.0])   # one R short
    assert trades is None and err is not None
    assert "disagreement" in err


# --- the frozen verdict taxonomy ----------------------------------------------

def test_pass_when_trade_sets_match_within_tolerances() -> None:
    a = _norm(12, r=1.0)
    b = _norm(12, r=1.0, jitter=0.01)          # per-trade |dR| = 0.01 <= 0.02
    d = bp.diff_trade_sets(a, b)
    assert d["verdict"] == bp.PASS, d["evidence"]
    assert any("max |dR|" in e for e in d["evidence"])


def test_fail_trade_set_on_count_mismatch() -> None:
    d = bp.diff_trade_sets(_norm(11), _norm(10))
    assert d["verdict"] == bp.FAIL_TRADE_SET
    assert any("counts differ" in e for e in d["evidence"])


def test_fail_trade_set_on_side_mismatch() -> None:
    a, b = _norm(12), _norm(12)
    b[3]["side"] = "buy" if b[3]["side"] == "sell" else "sell"
    d = bp.diff_trade_sets(a, b)
    assert d["verdict"] == bp.FAIL_TRADE_SET
    assert any("divergence at index 3" in e for e in d["evidence"])


def test_fail_trade_set_on_entry_time_mismatch() -> None:
    a, b = _norm(12), _norm(12)
    b[5]["entry_time"] = "1999.01.01 00:00:00"
    d = bp.diff_trade_sets(a, b)
    assert d["verdict"] == bp.FAIL_TRADE_SET
    assert any("divergence at index 5" in e for e in d["evidence"])


def test_fail_r_sequence_on_per_trade_drift() -> None:
    a, b = _norm(12, r=1.0), _norm(12, r=1.05)     # |dR| = 0.05 > 0.02
    d = bp.diff_trade_sets(a, b)
    assert d["verdict"] == bp.FAIL_R_SEQUENCE
    assert any("per-trade R divergence" in e for e in d["evidence"])


def test_fail_r_sequence_on_cumulative_drift() -> None:
    """Each per-trade delta inside tolerance, but 12 x 0.01 accumulates past
    the separate cumulative bound — laundering tolerance across many trades
    is exactly what this class forbids."""
    a = _norm(12, r=1.0)
    b = _norm(12, r=1.0)
    for i, t in enumerate(b):                      # +0.01 on every trade, one side
        t["r"] = round(t["r"] + (0.01 if i % 2 == 0 else -0.0), 4)
    d = bp.diff_trade_sets(a, b)
    assert d["verdict"] == bp.FAIL_R_SEQUENCE
    assert any("cumulative" in e for e in d["evidence"])


def test_inconclusive_zero_trades_fails_closed() -> None:
    for a, b in ((_norm(10), []), ([], _norm(10))):
        d = bp.diff_trade_sets(a, b)
        assert d["verdict"] == bp.INC_ZERO


def test_inconclusive_low_trades_even_when_identical() -> None:
    d = bp.diff_trade_sets(_norm(5, r=1.0), _norm(5, r=1.0))
    assert d["verdict"] == bp.INC_LOW
    assert any("n=5" in e for e in d["evidence"])


# --- §3 input pins --------------------------------------------------------------

def test_input_pins_pass_on_exact_and_numeric_equivalent() -> None:
    ok, problems = bp.check_input_pins({
        "research": dict(bp.INPUT_PINS),
        "forward": {"InpStrategyMode": "3", "InpStopATRMultiplier": "2",
                    "InpTargetATRMultiplier": "2.0", "InpMaxHoldMinutes": "180",
                    "InpRiskFraction": "0.01"},
    })
    assert ok and problems == []


def test_input_pins_fail_on_drift_or_missing_key() -> None:
    ok, problems = bp.check_input_pins({
        "research": {**bp.INPUT_PINS, "InpTargetATRMultiplier": "4.0"},
        "forward": {},                                # report omitted everything
    })
    assert not ok
    assert any("research: InpTargetATRMultiplier=4.0" in p for p in problems)
    assert any("forward: InpStrategyMode=?" in p for p in problems)


# --- pre-terminal refuses (before any terminal contact) -------------------------

def test_oos_window_refused_outright() -> None:
    try:
        bp.run_shadow("oos", "A", "B")
        raised = False
    except SystemExit as e:
        raised, msg = True, str(e)
    assert raised
    assert "oos" in msg and "closed" in msg


def test_identical_experts_refused() -> None:
    try:
        bp.run_shadow("wf", "MITEMSHUB_AI\\X", "MITEMSHUB_AI\\X")
        raised = False
    except SystemExit as e:
        raised, msg = True, str(e)
    assert raised
    assert "certify nothing" in msg


def test_unknown_window_refused() -> None:
    try:
        bp.run_shadow("nope", "A", "B")
        raised = False
    except SystemExit:
        raised = True
    assert raised


# --- journal-evidence parsing (contracts earned in the first live run) ---------

def test_trade_r_regex_accepts_explicit_sign() -> None:
    """The forward build prints Trade R with %+.4f — a leading '+' is the
    common case. The first live run's original regex (-? only) silently
    parsed nothing; this pin keeps the sign class closed."""
    assert bp.SEG_TRADE_R.search("[v28.10] Trade R: +0.6153").group(1) == "+0.6153"
    assert bp.SEG_TRADE_R.search("[v28.10] Trade R: -0.2537").group(1) == "-0.2537"
    assert float(bp.SEG_TRADE_R.search("[v28.10] Trade R: +0.6153").group(1)) > 0


def test_close_r_regex_is_the_research_fallback() -> None:
    """The research build prints no Trade R line; its per-trade R evidence is
    the CLOSE line's R= operand, which carries an explicit sign."""
    line = ("[v28.00] CLOSE BUY ticket=42 pnl=+12.34 R=+1.0029 risk=8.14 "
            "peak_r=1.31")
    assert bp.SEG_CLOSE_R.search(line).group(1) == "+1.0029"
    line = ("[v28.00] CLOSE SELL ticket=43 pnl=-3.10 R=-0.4769 risk=6.50 "
            "peak_r=0.12")
    assert float(bp.SEG_CLOSE_R.search(line).group(1)) < 0


def test_identity_extracted_from_banner() -> None:
    seg = ["2026.09.16 18:12:19.101\t[v28.10] MITEMSHUB V75 MACRO started | "
           "mode=3 | experiment=parity_forward_x | gate=M30 | r=1.0%"]
    ident = bp._identity(seg)
    assert ident.startswith("[v28.10]")
    assert "experiment=parity_forward_x" in ident
    assert bp._identity(["noise only"]) == ""


def test_pass_segment_is_tag_addressed(monkeypatch) -> None:
    """The segment is bounded by the pass's own experiment tag, so a second
    banner in the log can never contaminate the first pass's evidence."""
    ours = ["[v28.00] MITEMSHUB V75 MACRO started | experiment=tag_A | x",
            "[v28.00] CLOSE BUY ticket=1 pnl=+1.00 R=+0.5000 risk=1.00",
            "[v28.10] MITEMSHUB V75 MACRO started | experiment=tag_B | x"]
    monkeypatch.setattr(bp, "agent_lines_today", lambda: ours)
    monkeypatch.setattr(bp, "FLUSH_WAIT_S", 0.0)
    got = bp.pass_segment("tag_A")
    assert got["identity"].startswith("[v28.00]")
    assert got["r_values"] == [0.5]          # tag_B's banner bounds the segment


def test_pass_segment_stability_loop_stops_on_stable_count(monkeypatch) -> None:
    """The read stops once the R count is stable across two reads even when
    the flush wait has not elapsed (no fixed two-minute stall per pass)."""
    lines = ["[v28.00] MITEMSHUB V75 MACRO started | experiment=t | x",
             "[v28.00] CLOSE BUY ticket=1 pnl=+1.00 R=+1.0000 risk=1.00"]
    calls = {"n": 0}

    def fake_lines() -> list[str]:
        calls["n"] += 1
        return lines

    monkeypatch.setattr(bp, "agent_lines_today", fake_lines)
    monkeypatch.setattr(bp, "FLUSH_WAIT_S", 60.0)
    got = bp.pass_segment("t")
    assert got["r_values"] == [1.0]
    assert calls["n"] == 2                    # two identical reads, then stop


def test_pass_segment_fails_closed_on_missing_banner(monkeypatch) -> None:
    monkeypatch.setattr(bp, "agent_lines_today", lambda: ["unrelated"])
    monkeypatch.setattr(bp, "FLUSH_WAIT_S", 0.0)
    got = bp.pass_segment("ghost")
    assert got["identity"] == "" and got["r_values"] == []


# --- artifact + exit-code contract ----------------------------------------------

def test_exit_codes_are_frozen_by_class() -> None:
    assert bp.EXIT_CODES[bp.PASS] == 0
    for c in (bp.FAIL_TRADE_SET, bp.FAIL_R_SEQUENCE):
        assert bp.EXIT_CODES[c] == 10
    for c in (bp.INC_ZERO, bp.INC_LOW, bp.INC_EVIDENCE):
        assert bp.EXIT_CODES[c] == 11


def test_artifact_path_carries_the_receipt_naming() -> None:
    p = bp.artifact_path("20260916_120000Z")
    assert p.name == "armE_parity_20260916_120000Z.json"
    assert "armE_parity_" in p.name and str(p).replace("\\", "/").endswith(
        "artifacts/v28_research/armE_parity_20260916_120000Z.json")
