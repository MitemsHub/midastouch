"""The morning status report must not speak in the retired program's voice.

WHY THIS FILE EXISTS. `scripts/morning_status.py` was written for the predecessor
program's V75 paper A/B: sections [1]-[3] inventory magics (`A2_fwd`, `B_tp24`,
`C_v75`, `D_fwd`) that belong to the Deriv-era terminals, and the gate reminder
used to be attributed to them — ">= 30 closed arm-A trades ... (A/B are the gate
inputs; C_v75 is the V75MacroEngine paper arm ...)". A section [3b] for the gold
arm was added later, so the tool *is* part of this program's operator surface
(the health guide's one-minute routine runs it), and that is exactly why the
residue was dangerous: an operator reading the tail of the report would take a
retired program's arm attribution, and a retired program's gate, as the gate
this account answers to.

The 30-closed-trade clock itself is live and correct (the health guide states
it) — it governs promotion out of paper. What this file pins is that the report
(a) no longer attributes that clock to predecessor arms, and (b) names the two
things that actually govern gold: the frozen walk-forward pass criteria and the
arming record. The names are asserted to exist, so the pointer cannot rot.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import morning_status as ms  # noqa: E402

SOURCE = (REPO / "scripts" / "morning_status.py").read_text(encoding="utf-8")

#: Attribution that belonged to the retired V75 paper program. Their reappearance
#: in the printed report is the failure this file exists to catch.
RETIRED_ATTRIBUTION = ("arm-A", "C_v75", "D_fwd", "B_tp24")

#: The sentences that used to carry that attribution, as source text. Tokens alone are
#: not enough to search for: the script legitimately still *inventories* those magics
#: (MAGICS, the per-EA file names), and an inventory entry is not a claim about this
#: program's gate. What must be gone is the claim.
RETIRED_SENTENCES = (
    "closed arm-A trades",
    "A/B are the gate inputs",
    "C_v75 is the V75MacroEngine paper arm",
    "D_fwd is the forward test of the",
)

#: What the report must name instead, and what those names must resolve to.
VALIDATION_GATE_DOC = "docs/GOLD_WFO_PROTOCOL.md"
ARMING_RECORD = "artifacts/live/armed.json"
GOLD_STATUS_ENTRYPOINT = "scripts/live_readiness.py"


def _report() -> str:
    """The report as printed on a gold-only machine: no V75 terminals inventoried.

    The inventory is stubbed empty rather than read from disk so the pin holds on
    any machine — an operator's box with a live V75 terminal is not this repo's
    concern, and a test that only passes on one workstation is not evidence.
    """
    real_inventory = ms.terminal_inventory
    ms.terminal_inventory = lambda: []
    sys.argv = ["morning_status.py"]
    try:
        from io import StringIO
        buf = StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            ms.main()
        except SystemExit:
            pass  # main() ends with sys.exit(0): a status report, not a check
        finally:
            sys.stdout = real_stdout
        return buf.getvalue()
    finally:
        ms.terminal_inventory = real_inventory


@pytest.fixture(scope="module")
def report() -> str:
    return _report()


def test_the_report_does_not_claim_the_retired_arms(report: str):
    hits = [token for token in RETIRED_ATTRIBUTION if token in report]
    assert not hits, (
        f"the status report still speaks in the retired V75 paper A/B's voice: {hits}. "
        f"Those arms do not exist in this program; the account answers to the gold gate.")


def test_the_retired_attribution_is_gone_from_the_source_too():
    """The report is one code path; the source pin catches the branch it missed."""
    bad = [s for s in RETIRED_SENTENCES if s in SOURCE]
    assert not bad, (
        f"scripts/morning_status.py still carries the retired gate attribution: {bad}. "
        f"The magics may stay in the inventory; the claim about what binds this "
        f"account may not.")


def test_the_report_names_the_gate_that_actually_binds(report: str):
    assert VALIDATION_GATE_DOC in report, (
        "the report must name the frozen walk-forward pass criteria, not only the "
        "paper clock — the clock measures paper progress, it does not validate a strategy")
    assert ARMING_RECORD in report, (
        "the report must name the arming record, because arming is a record event "
        "rather than an input edit")
    assert GOLD_STATUS_ENTRYPOINT in report, (
        "with no V75 terminals inventoried the report must send the operator to the "
        "gold go/no-go check")


def test_the_named_authorities_exist():
    """A pointer that rots is worse than no pointer — the same rule as the doc guard."""
    assert (REPO / VALIDATION_GATE_DOC).is_file()
    assert (REPO / GOLD_STATUS_ENTRYPOINT).is_file()
    guide = (REPO / "docs" / "MIDASTOUCH_HEALTH_GUIDE.md").read_text(encoding="utf-8")
    assert ARMING_RECORD.replace("/", "\\") in guide or ARMING_RECORD in guide, (
        f"{ARMING_RECORD} is named by the report but documented nowhere in the health guide")


def test_the_source_scopes_the_retained_inventory():
    """The label itself is the fix: [1]-[3] are predecessor history, [3b] is gold."""
    head = SOURCE[:1200]
    assert "retired V75 paper A/B" in head, (
        "the module docstring must say which sections are retained predecessor "
        "inventory, or the next reader will take them for this program's own")
    assert "[3b]" in head, "the docstring must point at the gold section"
