"""Tests for scripts/era.py — era classification of the arm paper ledgers.

The frozen rule: pre-v26.38 MitemshubAI trades carry bar-open fills, post-
boundary trades carry per-tick fills, and the two regimes must never share
a statistic. V75MacroEngine is per-tick by design (all eras).
"""
from __future__ import annotations

import pytest

from scripts import era


# ----------------------------------------------------------------- rows ----

def test_parse_era_rows_reads_stamp(tmp_path):
    p = tmp_path / "ledger.csv"
    p.write_text("OPEN,1,1,1,1,1,1,1,1,1,1,PAPER\n"
                 f"ERA,26.39,{era.ERA_EPOCH},pertick-fills\n", encoding="utf-8")
    rows = era.parse_era_rows(str(p))
    assert len(rows) == 1
    assert rows[0]["version"] == "26.39"
    assert rows[0]["boundary"] == era.ERA_EPOCH
    assert rows[0]["era"] == era.ERA_POST
    assert rows[0]["ok"] is True
    assert rows[0]["line"] == 2


def test_parse_era_rows_missing_file_is_empty(tmp_path):
    assert era.parse_era_rows(str(tmp_path / "nope.csv")) == []


def test_parse_era_rows_malformed_and_mismatched_are_not_ok(tmp_path):
    p = tmp_path / "ledger.csv"
    p.write_text("ERA,26.39,not-a-number,pertick-fills\n"          # bad boundary
                 "ERA,26.39,26.39\n"                               # too short
                 f"ERA,26.39,{era.ERA_EPOCH + 7},pertick-fills\n",  # wrong boundary
                 encoding="utf-8")
    rows = era.parse_era_rows(str(p))
    assert len(rows) == 3
    assert all(r["ok"] is False for r in rows)


# ------------------------------------------------------------ fallback ----

def test_boundary_rule_for_mitemshubai():
    assert era.era_for_engine("MitemshubAI", era.ERA_EPOCH - 1) == era.ERA_PRE
    assert era.era_for_engine("MitemshubAI", era.ERA_EPOCH) == era.ERA_POST
    assert era.era_for_engine("mitemshubai", era.ERA_EPOCH + 100) == era.ERA_POST


def test_v75_is_always_postfill():
    assert era.era_for_engine("V75MacroEngine", 0) == era.ERA_POST
    assert era.era_for_engine("V75MacroEngine", era.ERA_EPOCH - 1) == era.ERA_POST


def test_unknown_engine_is_unknown_era():
    assert era.era_for_engine("SomethingElse", 123) == era.ERA_UNKNOWN


# ------------------------------------------------- positional stamps ------

def test_stamp_positions_the_split_not_the_epoch():
    rows = [{"line": 6, "ok": True, "era": era.ERA_POST, "boundary": era.ERA_EPOCH}]
    # Line 3 = written BEFORE the stamp (old build): the frozen epoch rule
    # decides. Line 9 = written AFTER the stamp: the stamp's era applies.
    above_pre = {"epoch": era.ERA_EPOCH - 5000, "line": 3}
    above_post_epoch = {"epoch": era.ERA_EPOCH + 5000, "line": 3}   # clock oddity, epoch rules
    below = {"epoch": era.ERA_EPOCH - 9999, "line": 9}              # stamp wins over epoch
    assert era.era_of_trade("MitemshubAI", above_pre, rows) == era.ERA_PRE
    assert era.era_of_trade("MitemshubAI", above_post_epoch, rows) == era.ERA_POST
    assert era.era_of_trade("MitemshubAI", below, rows) == era.ERA_POST


def test_stamp_below_file_head_does_not_override_fallback_without_position():
    rows = [{"line": 6, "ok": True, "era": era.ERA_POST, "boundary": era.ERA_EPOCH}]
    t = {"epoch": era.ERA_EPOCH - 5000}   # no line: parser without line numbers
    # No position -> frozen epoch rule decides (pre-boundary = PRE).
    assert era.era_of_trade("MitemshubAI", t, rows) == era.ERA_PRE


def test_malformed_stamp_falls_back_to_epoch_rule():
    rows = [{"line": 6, "ok": False, "era": era.ERA_POST, "boundary": 123}]
    t = {"epoch": era.ERA_EPOCH + 5000, "line": 9}
    assert era.era_of_trade("MitemshubAI", t, rows) == era.ERA_POST


def test_bad_boundary_stamp_is_ignored():
    rows = [{"line": 6, "ok": False, "era": era.ERA_POST, "boundary": era.ERA_EPOCH + 7}]
    t = {"epoch": era.ERA_EPOCH - 1, "line": 9}
    assert era.era_of_trade("MitemshubAI", t, rows) == era.ERA_PRE


# ------------------------------------------------------------- filters ----

def test_era_filter_default_is_postfill():
    trades = [
        {"epoch": era.ERA_EPOCH - 10, "line": 2},
        {"epoch": era.ERA_EPOCH + 10, "line": 5},
    ]
    rows = [{"line": 4, "ok": True, "era": era.ERA_POST, "boundary": era.ERA_EPOCH}]
    assert [t["epoch"] for t in era.era_filter(trades, "MitemshubAI", era.ERA_POST, rows)] \
        == [era.ERA_EPOCH + 10]
    assert [t["epoch"] for t in era.era_filter(trades, "MitemshubAI", era.ERA_PRE, rows)] \
        == [era.ERA_EPOCH - 10]


def test_era_filter_unknown_engine_matches_nothing():
    assert era.era_filter([{"epoch": 1}], "Mystery", era.ERA_POST) == []


def test_era_split_counts_every_trade_once():
    trades = [
        {"epoch": era.ERA_EPOCH - 10, "line": 2},
        {"epoch": era.ERA_EPOCH + 10, "line": 5},
        {"epoch": era.ERA_EPOCH + 20, "line": 7},
    ]
    rows = [{"line": 4, "ok": True, "era": era.ERA_POST, "boundary": era.ERA_EPOCH}]
    split = era.era_split(trades, "MitemshubAI", rows)
    assert split == {era.ERA_PRE: 1, era.ERA_POST: 2, era.ERA_UNKNOWN: 0}


def test_v75_split_is_all_post():
    split = era.era_split([{"epoch": 1}, {"epoch": era.ERA_EPOCH + 1}], "V75MacroEngine")
    assert split[era.ERA_POST] == 2 and split[era.ERA_PRE] == 0


def test_idempotent_restamps_first_stamp_wins(tmp_path):
    # Every restart appends another ERA row (idempotent by design). The FIRST
    # stamp is the oldest claim and must own the split; later stamps are
    # ignored regardless of position.
    p = tmp_path / "ledger.csv"
    lines = [
        "OPEN,1,1,1,1,1,1,1,1,1,1,PAPER",                    # 1
        "CLOSE,2,1,TARGET,1.1,2.0,1.0,51.00",                # 2 (pre-stamp)
        f"ERA,26.39,{era.ERA_EPOCH},pertick-fills",           # 3 (first stamp)
        "OPEN,3,2,1,1,1,1,1,1,1,1,PAPER",                    # 4
        "CLOSE,4,2,TARGET,1.1,2.0,1.0,53.00",                # 5 (post-stamp)
        f"ERA,26.39,{era.ERA_EPOCH},pertick-fills",           # 6 (restart restamp)
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = era.parse_era_rows(str(p))
    assert len(rows) == 2
    trades = era.era_filter(
        [{"epoch": 2, "line": 2}, {"epoch": 4, "line": 5}],
        "MitemshubAI", era.ERA_POST, rows)
    assert [t["line"] for t in trades] == [5]   # only the below-first-stamp trade


# ------------------------------------------------------- frozen values ----

def test_boundary_epoch_is_the_documented_instant():
    # 2026-09-15 17:51:40 UTC — the documented, pre-registered boundary.
    import calendar
    assert era.ERA_EPOCH == calendar.timegm((2026, 9, 15, 17, 51, 40, 0, 0, 0))


def test_boundary_sits_inside_the_verified_silence_window():
    # Both engines were verified DOWN between the last pre-deploy ledger
    # activity (17:50:48 UTC) and the first v26.38 init (17:52:35 UTC). The
    # boundary must sit inside that window so no real trade can straddle it:
    # every pre-deploy close < boundary, every post-deploy close > boundary.
    import calendar
    last_activity = calendar.timegm((2026, 9, 15, 17, 50, 48, 0, 0, 0))
    first_init = calendar.timegm((2026, 9, 15, 17, 52, 35, 0, 0, 0))
    assert last_activity < era.ERA_EPOCH < first_init


def test_engine_stamps_carry_the_house_era_format():
    # MIDASTOUCH opens a fresh era at each init (TimeCurrent), not the frozen
    # V75 boundary — but its ERA row must keep the house wire format so
    # era-aware consumers parse gold ledgers unchanged. v1.09: the era_name
    # field is the HONEST exec-model note ("bar-model-parity" in BAR parity
    # passes, "pertick-fills" on the live paper ledger) — era.py reads only
    # fields 1-3, and tester ledgers are throwaway, so either name parses.
    import re
    src = open("mql5/MIDASTOUCH/MidastouchAI.mq5", encoding="utf-8").read()
    assert re.search(r'"ERA,%s,%I64d,%s"', src), (
        "MidastouchAI must stamp the house ERA row wire format (ERA,<ver>,<epoch>,<name>)")
    assert 'era_note = InpBarModel ? "bar-model-parity" : "pertick-fills"' in src, (
        "era_name must reflect the actual execution model (honest provenance, v1.09)")
