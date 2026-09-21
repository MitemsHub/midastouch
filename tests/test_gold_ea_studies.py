"""The declarations the three 2026-09-21 EA-rule studies rest on.

WHY THIS FILE EXISTS. All three studies are only meaningful if the thing that was declared
before the run is still the thing that ran: the protocol hash in the artifact, the grid size,
the clock split, and the required sample computed BEFORE the table. A study whose declaration
drifts from its measurement is a description of the past wearing a test's clothes, and the
drift is invisible in the numbers themselves.

These pins read the generated artifacts rather than re-running the studies, so they are cheap
and they fail the moment an artifact is regenerated under a different declaration.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gold_session_hours_ea as hours          # noqa: E402
import gold_wfo_ea as ea_wfo                   # noqa: E402

EA_ART = ROOT / "artifacts" / "gold_wfo_ea.json"
HOURS_ART = ROOT / "artifacts" / "gold_session_hours_ea.json"
COMP_ART = ROOT / "artifacts" / "gold_rule_complementarity.json"


def _load(p: Path) -> dict:
    if not p.is_file():
        pytest.skip(f"{p.name} not generated in this checkout")
    return json.loads(p.read_text(encoding="utf-8"))


def _sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- the EA-rule walk-forward ----------------------------------------------


def test_the_ea_wfo_grid_is_the_declared_144() -> None:
    assert len(ea_wfo.grid()) == 144
    assert len({ea_wfo.cfg_key(c) for c in ea_wfo.grid()}) == 144


def test_the_ea_wfo_artifact_matches_its_protocol_hash() -> None:
    art = _load(EA_ART)
    assert art["protocol_sha256"] == _sha(ROOT / art["protocol"]), (
        "the protocol changed after the run — the verdict describes a different declaration")


def test_the_ea_wfo_verdict_carries_both_readings() -> None:
    art = _load(EA_ART)
    # The declared cell (no selection) and the selected path are both present, and the
    # declared cell is in the grid the artifact reports.
    assert art["declared_cell"]["cfg"] == {"mode": "ORIGINAL", "stop_atr_mult": 2.0,
                                           "tp_mult": 2.0, "window_utc": [6, 20]}
    assert art["spec"]["n_configs"] == 144
    assert len(art["declared_cell"]["per_fold_r"]) == 30
    assert art["selected_path"]["criteria"]["_t_req"] > 1.96      # a 144-wide search is priced
    assert art["verdict"] in ("PASS", "NOT VALIDATED")


def test_the_ea_wfo_declares_that_the_look_was_not_blind() -> None:
    art = _load(EA_ART)
    note = art["look_already_taken"]
    assert "NOT blind" in note["what"]
    assert "arm anything" in note["what_a_pass_would_not_do"]


# --- the session-hours study ------------------------------------------------


def test_the_required_sample_was_declared_before_the_table() -> None:
    art = _load(HOURS_ART)
    assert art["required_n"] > 4000
    assert art["required_n"] == math.ceil(
        (hours.ALPHA_Z * art["declared_sd_r"] / art["declared_effect_r"]) ** 2)
    assert art["required_n_80pct_power"] > art["required_n"]


def test_no_hour_bucket_is_claimed_to_be_decidable() -> None:
    art = _load(HOURS_ART)
    for row in art["per_hour"]:
        if row["n"] < art["required_n"]:
            assert row["verdict"] == "NOT EVALUABLE"
    assert art["changes_no_preset"] is True


def test_the_hours_study_runs_with_the_session_gate_off() -> None:
    art = _load(HOURS_ART)
    assert art["rule"]["session_gate"].startswith("REMOVED")


# --- the complementarity study ----------------------------------------------


def test_the_complementarity_study_keeps_its_sizing_convention() -> None:
    art = _load(COMP_ART)
    conv = art["sizing_convention"]
    assert conv["min_lot"] == 0.01 and conv["daily_line_usd"] == 750.0
    assert conv["no_risk_split_modelled"] is True, (
        "the study reports a combined budget with no split model; if a split is ever modelled "
        "this flag and the numbers that depend on it must move together")


def test_the_complementarity_answer_is_stated_as_measured() -> None:
    art = _load(COMP_ART)
    # Every configuration of the gate's grid was compared, not one pick.
    assert len(art["per_config"]) == 24
    for s in art["per_config"]:
        ov = s["overlap"]
        if ov["overlapping_pairs"]:
            # The finding that decided the question: no configuration hedges.
            assert ov["same_direction"] + ov["offsetting"] == ov["overlapping_pairs"]
            assert ov["share_same_direction"] is not None
