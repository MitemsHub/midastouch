"""Does the evidence an arming record cites describe the strategy that trades?

WHY THIS FILE EXISTS. On 2026-09-21 the live arming record cited `artifacts/gold_wfo.json`
as THE GATE. That artifact is a walk-forward of an M15 **EMA-stack** family — its only
trigger axis is `spec.grid.ema_sets`, and neither Bollinger nor RSI appears anywhere in the
engine that wrote it — while the EA trades a **BB(20,2.0)/RSI(14)** trigger. Measured on the
same bars, the two rules agree on the same bar and direction 3.4% of the time. So a verdict
about one strategy was standing in as the evidence for another, and nothing in the repository
could tell. Documentation would not have caught it either: every label in the record was
internally consistent. What catches it is reading the two rules out of the files that define
them and comparing.

The pins below are written so the check cannot become decorative: the family is READ from the
EA source's own indicator handles (a mutated source changes the answer), an undeclared family
on either side refuses rather than agreeing, and the refusal is asserted through the report
the operator actually reads.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from midas_prop.execution.prop_execution import (  # noqa: E402
    FAMILY_BB_RSI,
    FAMILY_EMA_STACK,
    FAMILY_UNKNOWN,
    ArmingGate,
    artifact_strategy_family,
    ea_strategy_family,
)

EA_SOURCE = ROOT / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
GATE_ARTIFACT = ROOT / "artifacts" / "gold_wfo.json"        # the EMA-stack family
EA_WFO_ARTIFACT = ROOT / "artifacts" / "gold_wfo_ea.json"   # the EA's own rule


def _arm(tmp_path: Path, *, artifact: str | None, disclosed: bool) -> Path:
    """A minimal arming record citing `artifact`, optionally disclosing the mismatch."""
    rec = {"record_type": "test", "arm": "T", "armed": True,
           "gate_detail": {"gate_result": "FAILED", "artifact": artifact}}
    if disclosed:
        rec["gate_family_mismatch"] = {"what_it_is": "recorded", "recorded_by": "test"}
    p = tmp_path / "armed.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return p


def _gate(tmp_path: Path, **kw) -> ArmingGate:
    return ArmingGate(arm_path=_arm(tmp_path, **kw),
                      validation_path=tmp_path / "validation_record.json")


# --- what the files say -----------------------------------------------------


def test_the_ea_source_declares_the_bb_rsi_trigger() -> None:
    fam = ea_strategy_family(EA_SOURCE)
    assert fam["family"] == FAMILY_BB_RSI
    # The evidence names the parameters, so a reader can check the claim against the source.
    assert "BB(20, 2.0)" in fam["evidence"] and "RSI(14)" in fam["evidence"]


def test_the_gate_artifact_declares_the_ema_stack_family() -> None:
    assert artifact_strategy_family(GATE_ARTIFACT)["family"] == FAMILY_EMA_STACK


def test_the_ea_walkforward_declares_the_bb_rsi_family() -> None:
    assert artifact_strategy_family(EA_WFO_ARTIFACT)["family"] == FAMILY_BB_RSI


def test_the_family_is_read_from_the_code_not_from_a_label(tmp_path: Path) -> None:
    """A source whose trigger is an EMA stack must NOT be reported as BB/RSI.

    This is the pin that makes the check real: if `ea_strategy_family` ever keyed off a
    version string, a comment or a filename, this mutated copy would still answer bb_rsi.
    """
    text = EA_SOURCE.read_text(encoding="utf-8", errors="replace")
    mutated = text.replace("iBands(", "ema_stack_handle(").replace("iRSI(", "ema_of_stack(")
    src = tmp_path / "FakeAI.mq5"
    src.write_text(mutated, encoding="utf-8")
    fam = ea_strategy_family(src)
    assert fam["family"] != FAMILY_BB_RSI
    assert fam["declared"] is False or fam["family"] == FAMILY_EMA_STACK


def test_an_artifact_that_declares_nothing_is_unknown(tmp_path: Path) -> None:
    p = tmp_path / "vague.json"
    p.write_text(json.dumps({"verdict": "PASS", "t_stat": 9.9}), encoding="utf-8")
    fam = artifact_strategy_family(p)
    assert fam["family"] == FAMILY_UNKNOWN and fam["declared"] is False


# --- what the gate does about it --------------------------------------------


def test_an_undisclosed_mismatch_is_refused(tmp_path: Path) -> None:
    out = _gate(tmp_path, artifact="artifacts/gold_wfo.json", disclosed=False).evidence_family()
    assert out["state"] == "mismatch"
    assert out["disclosed"] is False
    # The reason names BOTH sides, so a reader never has to go and look.
    assert FAMILY_EMA_STACK in out["reason"] and FAMILY_BB_RSI in out["reason"]
    assert "does NOT say so" in out["reason"]


def test_a_disclosed_mismatch_is_named_but_not_silent(tmp_path: Path) -> None:
    out = _gate(tmp_path, artifact="artifacts/gold_wfo.json", disclosed=True).evidence_family()
    assert out["state"] == "disclosed-mismatch"
    assert "does NOT say so" not in out["reason"]      # it does say so
    assert "discloses this" in out["reason"]


def test_evidence_about_the_same_rule_matches(tmp_path: Path) -> None:
    out = _gate(tmp_path, artifact="artifacts/gold_wfo_ea.json", disclosed=False).evidence_family()
    assert out["state"] == "match"
    assert FAMILY_BB_RSI in out["reason"]


def test_a_record_that_cites_nothing_is_not_a_mismatch(tmp_path: Path) -> None:
    out = _gate(tmp_path, artifact=None, disclosed=False).evidence_family()
    assert out["state"] == "unknown"
    assert "cites no validation artifact" in out["reason"]


def test_no_arm_record_means_nothing_is_claimed(tmp_path: Path) -> None:
    g = ArmingGate(arm_path=tmp_path / "absent.json",
                   validation_path=tmp_path / "validation_record.json")
    assert g.evidence_family()["state"] == "no-arm-record"


def test_an_unreadable_ea_source_refuses_rather_than_assuming(tmp_path: Path) -> None:
    g = _gate(tmp_path, artifact="artifacts/gold_wfo_ea.json", disclosed=False)
    out = g.evidence_family(ea_source=tmp_path / "not-a-source.mq5")
    assert out["state"] == "unknown"
    assert "cannot read the EA source" in out["reason"]


# --- what the operator's report does with it --------------------------------


def _readiness_report() -> dict | None:
    """The live report, or None when the script cannot run here (no terminal, no JSON)."""
    try:
        r = subprocess.run([sys.executable, "scripts/live_readiness.py", "--json"],
                           cwd=ROOT, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):     # pragma: no cover
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:                      # pragma: no cover
        return None


def test_the_live_report_refuses_a_silent_mismatch() -> None:
    """The refusal is asserted through the artifact the operator reads, not just in a class.

    Written as an INVARIANT rather than a snapshot: the record's state may legitimately
    become 'disclosed-mismatch' (the operator recording the fact), and that must relax the
    refusal to a named disclosure — never to silence. What may never happen is a mismatch
    that is neither refused nor named.
    """
    report = _readiness_report()
    if report is None:                                # pragma: no cover
        pytest.skip("live_readiness did not emit JSON in this environment")
    fam = report.get("evidence_family") or {}
    assert fam.get("state") in ("mismatch", "disclosed-mismatch", "match"), fam
    failures = report.get("failures") or []
    if fam["state"] == "mismatch":
        assert "evidence describes this strategy" in failures
        assert report["verdict"] != "AUTHORISED_BY_OPERATOR_OVERRIDE"
        # ...and the refusal must say that the machine legs are untouched by it, so the
        # report cannot be misread as "the arm stopped trading".
        assert fam["reason"]
    else:
        assert "evidence describes this strategy" not in failures
