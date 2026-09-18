"""Tests for the [3b] LV broker view (VPS era).

Pins the rendering contract of _print_lv_broker_view in
scripts/morning_status.py:

  * with no snapshot file, [3b] prints nothing extra (pre-VPS shape);
  * with a snapshot: account header with equity/balance and the
    snapshot age; a snapshot older than 300 s is labeled STALE and the
    header is flagged — staleness is labeled, never hidden;
  * broker positions render as LIVE POSITION (broker) with direction,
    volume, entry, SL/TP and open-age;
  * deals render with entry/exit, side, P/L;
  * balance operations render flagged as non-trading money movement
    (the 2026-09-18 12:25:59Z −$10.14 withdrawal shape).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import morning_status as ms

NOW = 1789737600.0


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch):
    """Write a snapshot and freeze 'now' so age math is deterministic.
    Returns a function(payload) -> path."""
    p = tmp_path / "midas_lv_broker_state.json"
    monkeypatch.setattr(time, "time", lambda: NOW)

    def _write(payload: dict) -> Path:
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    return _write


def test_no_snapshot_prints_nothing(capsys):
    ms._print_lv_broker_view(state_path="/nonexistent/path.json")
    assert capsys.readouterr().out == ""


def test_snapshot_header_with_equity_and_freshness(state_file, capsys):
    p = state_file({"ts_epoch": NOW - 60, "account": 140778269,
                    "equity": 40.08, "balance": 40.08,
                    "positions": [], "deals": [], "balance_ops": [],
                    "problems": []})
    ms._print_lv_broker_view(state_path=str(p))
    out = capsys.readouterr().out
    assert "[LV broker view]" in out
    assert "140778269" in out and "$40.08" in out
    assert "STALE" not in out


def test_stale_snapshot_is_labeled_not_hidden(state_file, capsys):
    p = state_file({"ts_epoch": NOW - 1200, "account": 140778269,
                    "equity": 40.08, "balance": 40.08,
                    "positions": [], "deals": [],
                    "balance_ops": [], "problems": []})
    ms._print_lv_broker_view(state_path=str(p))
    out = capsys.readouterr().out
    assert "STALE" in out


def test_staleness_never_hides_positions(state_file, capsys):
    p = state_file({
        "ts_epoch": NOW - 3600, "account": 140778269,
        "equity": 40.08, "balance": 40.08,
        "positions": [{"ticket": 1, "dir": 1, "volume": 0.01,
                       "entry": 4390.0, "sl": 4370.0, "tp": 4430.0,
                       "epoch": NOW - 1800, "comment": ""}],
        "deals": [], "balance_ops": [], "problems": []})
    ms._print_lv_broker_view(state_path=str(p))
    out = capsys.readouterr().out
    assert "STALE" in out
    assert "LIVE POSITION (broker)" in out
    assert "LONG" in out


def test_broker_position_line_shape(state_file, capsys):
    p = state_file({
        "ts_epoch": NOW - 30, "account": 140778269,
        "equity": 40.08, "balance": 40.08,
        "positions": [{"ticket": 1, "dir": -1, "volume": 0.02,
                       "entry": 4300.0, "sl": 4320.0, "tp": 4260.0,
                       "epoch": NOW - 60, "comment": ""}],
        "deals": [], "balance_ops": [], "problems": []})
    ms._print_lv_broker_view(state_path=str(p))
    out = capsys.readouterr().out
    assert "SHORT" in out and "0.02 lots @ 4300.00" in out
    assert "SL 4320.00 TP 4260.00" in out


def test_flat_book_renders_broker_evidence_line(state_file, capsys):
    p = state_file({"ts_epoch": NOW - 30, "account": 140778269,
                    "equity": 40.08, "balance": 40.08,
                    "positions": [], "deals": [],
                    "balance_ops": [], "problems": []})
    ms._print_lv_broker_view(state_path=str(p))
    out = capsys.readouterr().out
    assert "positions: none (broker evidence)" in out
    # collision-freedom: must never emit the arm-level "live: flat" string
    assert "live: flat" not in out


def test_deals_render_entry_exit_with_profit(state_file, capsys):
    p = state_file({
        "ts_epoch": NOW - 30, "account": 140778269,
        "equity": 40.08, "balance": 40.08,
        "positions": [],
        "deals": [
            {"ticket": 11, "entry": 0, "type": 0, "volume": 0.01,
             "price": 4390.0, "profit": 0.0, "epoch": NOW - 600,
             "comment": ""},
            {"ticket": 12, "entry": 1, "type": 1, "volume": 0.01,
             "price": 4400.0, "profit": 0.88, "epoch": NOW - 300,
             "comment": ""}],
        "balance_ops": [], "problems": []})
    ms._print_lv_broker_view(state_path=str(p))
    out = capsys.readouterr().out
    assert "entry BUY" in out and "exit SELL" in out
    assert "$+0.88" in out


def test_balance_ops_flagged_as_non_trading(state_file, capsys):
    p = state_file({
        "ts_epoch": NOW - 30, "account": 140778269,
        "equity": 40.08, "balance": 40.08, "positions": [], "deals": [],
        "balance_ops": [{"ticket": 9329394820, "amount": -10.14,
                         "epoch": 1789734359.0,
                         "comment": "R-184b8136-9140-4fa3-b184"}],
        "problems": []})
    ms._print_lv_broker_view(state_path=str(p))
    out = capsys.readouterr().out
    assert "balance op" in out and "$-10.14" in out
    assert "non-trading money movement" in out


def test_problems_surfaced(state_file, capsys):
    p = state_file({"ts_epoch": NOW - 30, "account": 140778269,
                    "equity": 40.08, "balance": 40.08,
                    "positions": [], "deals": [],
                    "balance_ops": [],
                    "problems": ["mt5.initialize failed at 12:00:00Z"]})
    ms._print_lv_broker_view(state_path=str(p))
    assert "mt5.initialize failed" in capsys.readouterr().out


def test_unreadable_snapshot_is_flagged(tmp_path, capsys):
    p = tmp_path / "midas_lv_broker_state.json"
    p.write_text("{not json", encoding="utf-8")
    ms._print_lv_broker_view(state_path=str(p))
    assert "unreadable" in capsys.readouterr().out
