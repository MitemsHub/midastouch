"""The 5% target ends the EVALUATION — it must never end the trading.

WHY THIS FILE EXISTS. The EA refused entries once equity passed the target:

    "profit target MET (+X of Y) — stop entering, the shield is the only risk left"

That reads the pass mark as the finish line of the whole exercise. The venue's own rule
table says otherwise — the challenge has a 5% (= $1,250) profit target and the **funded
phase has none** (docs/UPCOMERS_RULES_AUDIT_20260919.md §3) — so passing it is the
*transition* into the funded account, where the strategy is supposed to keep trading. A
veto there throws away the pass it just earned.

The fix is a change of kind, not of number: the target is now REPORTED (`PropPhaseCheck`,
one line, once) and never returned as a block reason by `PropGovernorBlock()`. The survival
guards keep running, because the funded phase's own numbers are still unverified with the
venue and the audit lists them as open items (C2 daily DD %, C3 max single-trade loss %) —
the print says so instead of pretending they were re-declared.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
AUDIT = REPO / "docs" / "UPCOMERS_RULES_AUDIT_20260919.md"
SOURCE = EA.read_text(encoding="utf-8")


def test_the_venue_says_the_target_is_a_challenge_rule_only():
    """The premise, pinned where it can be checked: no target in the funded column."""
    rows = [l for l in AUDIT.read_text(encoding="utf-8").splitlines()
            if l.strip().startswith("| Profit target")]
    assert rows, "the audit's rule table no longer has a Profit target row"
    cells = [c.strip() for c in rows[0].strip("|").split("|")]
    assert "**5%**" in cells[1] and "$1,250" in cells[1], cells
    assert cells[2] == "none", (
        f"the funded column must read 'none' for the EA's fix to be justified; got {cells}")


def test_the_target_is_not_an_entry_veto():
    block = SOURCE[SOURCE.index("string PropGovernorBlock()"):
                   SOURCE.index("bool StopsLevelOK(")]
    code = _code_only(block)
    assert "InpPropTargetPct" not in code, (
        "PropGovernorBlock() reads the target again — if it returns a reason for it, the "
        "EA stops trading at the phase transition")
    assert "target" not in code.lower(), (
        "a target reading inside the governor is how the veto returns; the phase is "
        "reported by PropPhaseCheck(), not here")


def _code_only(text: str) -> str:
    """Drop `//` comment lines: the source QUOTES the retired veto where it explains the
    removal, and a pin that forbids the quotation forbids the documentation."""
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


def test_the_phase_is_reported_once_and_never_blocks():
    assert "void PropPhaseCheck()" in SOURCE
    assert "PropPhaseCheck();" in SOURCE[SOURCE.index("void OnTick()"):], \
        "the milestone must run from OnTick, next to the day anchors"
    assert re.search(r"PROP PHASE: EVALUATION COMPLETE", SOURCE)
    # Once per init, not once per tick.
    assert "g_prop_pass_logged" in SOURCE
    # The funded numbers are named as unverified rather than assumed.
    assert "C2/C3" in SOURCE and "UNVERIFIED" in SOURCE
    # And the guards that stay in force are named, so a reader knows what still runs.
    assert "3%% day cap" in SOURCE and "shield" in SOURCE


def test_the_reasoning_is_recorded_in_the_source():
    """A future reader must find WHY, not just that the veto disappeared."""
    head = SOURCE[SOURCE.index("//| PROP GOVERNOR"):SOURCE.index("double PropShieldFloor()")]
    assert "THE TARGET IS A PHASE, NOT A WALL" in head or "THE TARGET IS NOT A VETO" in SOURCE
    assert "UPCOMERS_RULES_AUDIT_20260919.md" in SOURCE, \
        "the citation that makes this checkable belongs in the source"


#: Only the two phrases that were the target-specific VETO. Not "target MET (+...)" —
#: the phase print legitimately reports that milestone — and not "no new entries until",
#: which is the daily breaker's own (live) wording.
@pytest.mark.parametrize("retired", ["stop entering", "the shield is the only risk left"])
def test_the_retired_wording_cannot_come_back_as_code(retired):
    """It may survive as the comment that records why it left; never as executable text."""
    assert retired not in _code_only(SOURCE), (
        f"the retired target veto is back in code: {retired!r}")
