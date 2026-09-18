"""Tests for the P5 adaptive-trigger proposal engine (register row P5).

Pins the engine to its REGISTERED constants and kill rules — the values
below are register-locked (docs/MIDASTOUCH_V2_REGISTER.md §2b, P5 row,
2026-09-18): editing them here must fail until the register amends.
Also pins the safety shape: the engine is pure (no MT5 import, no ledger
writes) and proposes; it never deploys — deploying is the era machinery's
job, outside this module.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import midas_adaptive as ad


# ── register-locked constants ────────────────────────────────────────────────

def test_constants_match_register_row():
    assert ad.CADENCE == 20                       # one step per 20 closed trades
    assert ad.THETA_MIN == 1.0 and ad.THETA_MAX == 4.0
    assert ad.STEP == 0.25
    assert ad.FREEZE_EXPECTANCY == -0.30
    assert ad.FULL_LOSS_R == -0.999


def _trades(n: int, r: float, day0_epoch: int = 1_700_000_000, per_day: int = 10) -> list[dict]:
    """n trades of return r, packed per_day-per-day from day0_epoch."""
    return [{"r": r, "close_epoch": day0_epoch + (i // per_day) * 86400 + (i % per_day) * 900}
            for i in range(n)]


# ── cadence ──────────────────────────────────────────────────────────────────

def test_below_cadence_is_hold_with_reason():
    p = ad.propose({"theta": 2.0}, _trades(19, 0.5))
    assert p["action"] == "HOLD" and "19/20" in p["reason"]
    assert p["expectancy"] == pytest.approx(0.5)


def test_empty_book_holds_at_default_conservative_theta():
    p = ad.propose({}, [])
    assert p["action"] == "HOLD" and p["theta"] == ad.THETA_MAX


# ── the hill-climb ───────────────────────────────────────────────────────────

def test_positive_block_continues_exploration_direction():
    p = ad.propose({"theta": 2.0, "last_direction": -1}, _trades(20, 0.5))
    assert p["action"] == "PROPOSE" and p["theta"] == pytest.approx(1.75)
    assert p["last_direction"] == -1


def test_zero_expectancy_reverses_toward_conservative_end():
    p = ad.propose({"theta": 2.0, "last_direction": -1}, _trades(20, 0.0))
    assert p["action"] == "PROPOSE" and p["theta"] == pytest.approx(2.25)
    assert p["last_direction"] == 1


def test_negative_but_not_frozen_block_reverses():
    p = ad.propose({"theta": 2.0, "last_direction": -1}, _trades(20, -0.1))
    assert p["action"] == "PROPOSE" and p["theta"] == pytest.approx(2.25)


# ── bound law: envelope is the cap, never crossed ───────────────────────────

def test_theta_min_reached_holds_never_crosses():
    p = ad.propose({"theta": ad.THETA_MIN, "last_direction": -1}, _trades(20, 0.5))
    assert p["action"] == "HOLD"
    assert p["theta"] == ad.THETA_MIN
    assert "THETA_MIN" in p["reason"]


def test_theta_max_reached_holds_never_crosses():
    p = ad.propose({"theta": ad.THETA_MAX, "last_direction": 1}, _trades(20, 0.5))
    assert p["action"] == "HOLD" and p["theta"] == ad.THETA_MAX


def test_revert_action_carries_conservative_theta():
    p = ad.propose({"theta": 2.0, "last_direction": -1}, _trades(20, -1.0))
    assert p["action"] in ("REVERT", "FREEZE")  # full-loss days trip REVERT first
    if p["action"] == "REVERT":
        assert p["theta"] == ad.THETA_MAX


# ── kill rules ───────────────────────────────────────────────────────────────

def test_freeze_on_expectancy_below_threshold():
    p = ad.propose({"theta": 2.0, "last_direction": -1}, _trades(20, -0.35))
    assert p["action"] == "FREEZE" and p["theta"] == ad.THETA_MAX
    assert "-0.350" in p["reason"]      # the measured value is named
    assert f"{ad.FREEZE_EXPECTANCY:.2f}" in p["reason"]


def test_revert_on_two_consecutive_full_loss_days():
    trades = _trades(10, -1.0) + _trades(10, -1.0, day0_epoch=1_700_000_000 + 86400)
    p = ad.propose({"theta": 2.0, "last_direction": -1}, trades)
    assert p["action"] == "REVERT" and p["theta"] == ad.THETA_MAX
    assert "full-loss" in p["reason"]


def test_one_full_loss_day_alone_does_not_revert():
    trades = _trades(10, -1.0) + _trades(10, 0.2, day0_epoch=1_700_000_000 + 86400)
    p = ad.propose({"theta": 2.0, "last_direction": -1}, trades)
    assert p["action"] != "REVERT"


def test_frozen_state_never_adapts_again():
    p = ad.propose({"theta": 2.0, "frozen": True}, _trades(40, 0.9))
    assert p["action"] == "HOLD" and "kill rule" in p["reason"]


def test_reverted_state_never_adapts_again():
    p = ad.propose({"theta": 2.0, "reverted": True}, _trades(40, 0.9))
    assert p["action"] == "HOLD"


# ── VOID: envelope-violating STATE voids the experiment ─────────────────────

def test_out_of_bounds_theta_voids():
    for bad in (0.5, 4.5):
        p = ad.propose({"theta": bad}, _trades(20, 0.5))
        assert p["action"] == "VOID" and "re-registration" in p["reason"]


def test_corrupt_direction_voids():
    p = ad.propose({"theta": 2.0, "last_direction": 0}, _trades(20, 0.5))
    assert p["action"] == "VOID"


def test_void_precedes_every_other_rule():
    p = ad.propose({"theta": 9.9, "reverted": True}, [])
    assert p["action"] == "VOID"


# ── trailing window is exactly the last CADENCE trades ──────────────────────

def test_expectancy_uses_only_trailing_window():
    trades = _trades(20, -0.9, day0_epoch=1_700_000_000) + \
             _trades(20, 0.5, day0_epoch=1_700_000_000 + 5 * 86400)
    p = ad.propose({"theta": 2.0, "last_direction": -1}, trades)
    assert p["action"] == "PROPOSE"          # trailing 20 are the winners
    assert p["expectancy"] == pytest.approx(0.5)


def test_full_loss_day_rule_scans_recent_history():
    # full losses 30 days back must NOT trip the revert (scan window is bounded)
    trades = _trades(20, -1.0, day0_epoch=1_700_000_000) + \
             _trades(20, 0.5, day0_epoch=1_700_000_000 + 30 * 86400)
    p = ad.propose({"theta": 2.0, "last_direction": -1}, trades)
    assert p["action"] == "PROPOSE"


# ── purity and artifact shape ───────────────────────────────────────────────

def test_module_is_pure_no_mt5_no_ledger(tmp_path, monkeypatch):
    import ast
    tree = ast.parse(Path(ad.__file__).read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in getattr(n, "names", [])}
    assert "MetaTrader5" not in imported          # proposes; never polls MT5
    src = Path(ad.__file__).read_text(encoding="utf-8")
    assert "positions_get" not in src and "history_deals_get" not in src
    monkeypatch.chdir(tmp_path)
    p = ad.emit({"action": "PROPOSE", "theta": 1.75}, "P5-test", out_dir=tmp_path)
    assert p.exists()
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["proposal"]["theta"] == 1.75
    assert payload["era_note"] == "P5-test"
    assert payload["constants"]["CADENCE"] == 20
    assert sorted(p.parent.iterdir()) == [p]      # emits exactly one file


def test_emit_artifact_records_frozen_constants(tmp_path):
    out = ad.emit({"action": "FREEZE", "theta": 4.0}, "P5-test", out_dir=tmp_path)
    payload = json.loads(out.read_text(encoding="utf-8"))
    c = payload["constants"]
    assert (c["THETA_MIN"], c["THETA_MAX"], c["STEP"]) == (1.0, 4.0, 0.25)
    out.unlink()
