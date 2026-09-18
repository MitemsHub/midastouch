"""Tests for the broker-evidence-only LV monitor (VPS era).

Pins the attribution rules of scripts/midas_lv_broker_monitor.py — the
2026-09-18 registered answer to MT5 Virtual Hosting: while the LV EA
executes on the VPS, the LOCAL ledger is frozen and the only evidence
surface is the MT5 API. The monitor must:

  * filter positions and trade deals to magic 7801601 (the LV arm) —
    a paper arm's or another EA's positions must never appear here;
  * capture balance operations REGARDLESS of magic (money movement like
    the 2026-09-18 12:25:59Z −$10.14 withdrawal is account evidence);
  * dedup deals by ticket across polls (no re-logged deals);
  * set first_fill_seen on the first ENTRY deal and never unset it;
  * never write to the LV ledger (the EA owns that file).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import midas_lv_broker_monitor as mon

LV = mon.LV_MAGIC
OTHER = 7801001  # the paper arms' magic


def _deal(ticket, magic, dtype=0, entry=0, profit=0.0, price=4300.0,
          volume=0.01, time=1789734000.0, comment=""):
    return SimpleNamespace(ticket=ticket, magic=magic, type=dtype,
                           entry=entry, profit=profit, price=price,
                           volume=volume, time=time, comment=comment,
                           position_id=9001, commission=0.0)


def _pos(ticket, magic, ptype=0, price_open=4390.0, sl=4370.0, tp=4430.0,
         volume=0.01, time=1789734000.0):
    return SimpleNamespace(ticket=ticket, magic=magic, type=ptype,
                           price_open=price_open, sl=sl, tp=tp,
                           volume=volume, time=time, comment="",
                           price_current=4391.0)


def _acct(equity=40.08, balance=40.08):
    return SimpleNamespace(login=140778269, equity=equity, balance=balance,
                           margin=0.0)


def test_positions_and_trade_deals_filtered_to_lv_magic():
    state = mon.build_state(
        _acct(),
        [_pos(1, LV), _pos(2, OTHER), _pos(3, 0)],
        [_deal(11, LV), _deal(12, OTHER), _deal(13, 0)],
        {}, now_epoch=1789734100.0)
    assert [p["ticket"] for p in state["positions"]] == [1]
    assert [d["ticket"] for d in state["deals"]] == [11]


def test_balance_op_captured_regardless_of_magic():
    """The withdrawal shape: type 2 (balance op), magic 0, profit −10.14."""
    withdrawal = _deal(9329394820, magic=0, dtype=2, profit=-10.14,
                       time=1789734359.0, comment="R-184b8136")
    state = mon.build_state(_acct(), [], [withdrawal], {},
                            now_epoch=1789734400.0)
    assert state["balance_ops"] == [{
        "ticket": 9329394820, "amount": -10.14,
        "epoch": 1789734359.0, "comment": "R-184b8136"}]
    assert state["deals"] == []  # a balance op is never a trade deal


def test_balance_op_not_duplicated_across_polls():
    balop = _deal(9329394820, magic=0, dtype=2, profit=-10.14)
    s1 = mon.build_state(_acct(), [], [balop], {}, now_epoch=1.0)
    s2 = mon.build_state(_acct(), [], [balop], s1, now_epoch=2.0)
    assert len(s2["balance_ops"]) == 1


def test_deals_deduped_by_ticket_across_polls():
    d = _deal(11, LV)
    s1 = mon.build_state(_acct(), [], [d], {}, now_epoch=1.0)
    s2 = mon.build_state(_acct(), [], [d], s1, now_epoch=2.0)
    assert len(s2["deals"]) == 1
    newer = _deal(12, LV, time=2.0)
    s3 = mon.build_state(_acct(), [], [d, newer], s2, now_epoch=3.0)
    assert [x["ticket"] for x in s3["deals"]] == [11, 12]


def test_deal_ring_is_bounded():
    deals = [_deal(i, LV) for i in range(mon.DEAL_RING + 10)]
    state = mon.build_state(_acct(), [], deals, {}, now_epoch=1.0)
    assert len(state["deals"]) == mon.DEAL_RING


def test_first_fill_seen_set_on_first_entry_and_never_unset():
    entry = _deal(11, LV, entry=0, time=1789734000.0)
    s1 = mon.build_state(_acct(), [], [entry], {}, now_epoch=1.0)
    assert s1["first_fill_seen"] == 1789734000.0
    # a later poll with NO new deals keeps the stamp
    s2 = mon.build_state(_acct(), [], [entry], s1, now_epoch=2.0)
    assert s2["first_fill_seen"] == 1789734000.0
    # an exit-only deal does NOT set it
    exit_only = _deal(13, LV, entry=1)
    s3 = mon.build_state(_acct(), [], [exit_only], {}, now_epoch=3.0)
    assert s3["first_fill_seen"] is None


def test_position_fields_shape_dir_and_levels():
    state = mon.build_state(_acct(), [_pos(1, LV)], [], {}, now_epoch=1.0)
    p = state["positions"][0]
    assert p["dir"] == 1 and p["entry"] == 4390.0
    assert p["sl"] == 4370.0 and p["tp"] == 4430.0
    short = mon.build_state(
        _acct(), [_pos(2, LV, ptype=1, price_open=4300.0)], [], {},
        now_epoch=1.0)
    assert short["positions"][0]["dir"] == -1


def test_account_carried_into_state():
    state = mon.build_state(_acct(equity=41.5, balance=40.08), [], [], {},
                            now_epoch=1.0)
    assert state["account"] == 140778269
    assert state["equity"] == 41.5 and state["balance"] == 40.08


def test_monitor_never_writes_lv_ledger(tmp_path: Path, monkeypatch):
    """The monitor's only output is its own snapshot file — the LV ledger
    is the EA's artifact and must not be touched (registered rule)."""
    monkeypatch.setattr(mon, "ART", tmp_path)
    monkeypatch.setattr(mon, "STATE_PATH", tmp_path / "midas_lv_broker_state.json")
    fake_mt5 = SimpleNamespace(
        initialize=lambda: True, shutdown=lambda: None,
        account_info=lambda: _acct(),
        positions_get=lambda symbol=None: [],
        history_deals_get=lambda *a, **k: [])
    with patch.dict(sys.modules, {"MetaTrader5": fake_mt5}):
        mon.poll_once()
    written = {p.name for p in tmp_path.iterdir()}
    assert written == {"midas_lv_broker_state.json"}
    snap = json.loads((tmp_path / "midas_lv_broker_state.json").read_text())
    assert snap["account"] == 140778269


def test_poll_keeps_prior_snapshot_on_init_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mon, "ART", tmp_path)
    monkeypatch.setattr(mon, "STATE_PATH", tmp_path / "midas_lv_broker_state.json")
    (tmp_path / "midas_lv_broker_state.json").write_text(
        json.dumps({"equity": 40.08, "positions": [], "deals": [],
                    "balance_ops": [], "problems": []}), encoding="utf-8")
    fake_mt5 = SimpleNamespace(initialize=lambda: False, shutdown=lambda: None)
    with patch.dict(sys.modules, {"MetaTrader5": fake_mt5}):
        state = mon.poll_once()
    assert state["equity"] == 40.08
    assert any("initialize failed" in p for p in state["problems"])
