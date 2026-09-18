"""Offline tests for the account-guard firing classifier (funnel_diff.py).

The 2026-09-15 drill's blunt rule ("post-deploy firing = DEFECT") mis-flagged
two correct vetoes: the 15% account-budget guard refusing min-lot entries on
shrunken virtual equity — the documented strangulation regime working as
designed. The frozen replacement taxonomy classifies each firing from its own
operands + the host arm's ledger state at the firing instant, and FAILS CLOSED:
anything it cannot prove is DEFECT or UNCLASSIFIED, never silently WORKING.
"""
from __future__ import annotations

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from funnel_diff import (  # noqa: E402
    V37_DEPLOY, classify_guard_firing, ledger_state_at,
)

# ---- the live 2026-09-15/16 firings, verbatim from the journals -------------


def _firing(**kw):
    base = {"build": "26.39", "fleet": 0.0, "new": 5.09, "cap": 4.61,
            "post_deploy": True, "position_open": False, "veq_at_fire": 30.73}
    base.update(kw)
    return base


def test_working_veto_case_matches_live_evidence():
    """The live Sep-15 19:30/20:15 and Sep-16 15:15/15:30 firings: no position,
    fleet $0 truthful, new risk busts the 15% account budget on shrunken veq."""
    for new in (6.10, 4.64, 5.09, 4.95):
        cls, notes = classify_guard_firing(_firing(new=new))
        assert cls.startswith("WORKING"), cls
        assert any("cap = 15.0% of veq" in n for n in notes), notes
        assert any(f"{new / 30.73 * 100:.1f}% of veq" in n for n in notes), notes


def test_pre_deploy_firing_is_closed_class():
    """07:47 on v26.35: before the deploy, the closed $0-basis class."""
    cls, notes = classify_guard_firing(_firing(post_deploy=False, build="26.35"))
    assert cls == "pre-v26.37 (closed $0-basis class)"
    assert notes == []


def test_mirror_blind_is_defect():
    """v26.37's original defect: position open, fleet read $0."""
    cls, _ = classify_guard_firing(_firing(position_open=True, fleet=0.0))
    assert cls.startswith("DEFECT"), cls
    assert "mirror blind" in cls


def test_phantom_fleet_is_defect():
    """No open position but fleet risk read > 0 — the opposite mirror fault."""
    cls, _ = classify_guard_firing(_firing(position_open=False, fleet=6.01))
    assert cls.startswith("DEFECT"), cls
    assert "phantom" in cls


def test_unparseable_time_fails_closed():
    """post_deploy=None (time unparseable) must never silently classify."""
    cls, _ = classify_guard_firing(_firing(post_deploy=None))
    assert cls.startswith("UNCLASSIFIED"), cls


def test_missing_ledger_still_classifies_but_discloses():
    """No ledger evidence: operand shape alone can still prove the designed
    veto (fleet $0 + no position = nothing to mirror), but the veto must
    disclose that equity was unavailable."""
    cls, notes = classify_guard_firing(_firing(veq_at_fire=None))
    assert cls.startswith("WORKING"), cls
    assert any("unavailable" in n for n in notes), notes


def test_v37_deploy_timestamp_is_frozen():
    """The deploy boundary is pinned so a refactor cannot silently move it."""
    assert V37_DEPLOY == datetime(2026, 9, 15, 12, 19, 45)


def test_ledger_state_at_sequence_pairing(tmp_path):
    """OPEN/CLOSE pairing: open inside the window, closed after, veq from the
    last CLOSE before the query instant."""
    csv = tmp_path / "led.csv"
    open_ts = int(datetime(2026, 9, 15, 9, 0, 0).timestamp())
    close_ts = int(datetime(2026, 9, 15, 9, 45, 0).timestamp())
    csv.write_text(
        f"OPEN,{open_ts},SELL,1.0,0.0,0.0,0,50.0,note\n"
        f"CLOSE,{close_ts},SELL,1.0,0.0,0.0,-1.271,30.73,note\n",
        encoding="utf-8")
    # While open (between OPEN and CLOSE): open, no veq yet from that close.
    during = datetime(2026, 9, 15, 9, 30, 0)
    assert ledger_state_at(str(csv), during) == (True, None)
    # After the close: flat, veq = 30.73.
    after = datetime(2026, 9, 15, 19, 30, 0)
    assert ledger_state_at(str(csv), after) == (False, 30.73)
    # Before any row: flat, no veq.
    before = datetime(2026, 9, 15, 8, 0, 0)
    assert ledger_state_at(str(csv), before) == (False, None)
    # Missing ledger: flat, no veq.
    assert ledger_state_at(str(tmp_path / "nope.csv"), after) == (False, None)
