"""Pins for the Upcomers gold preset tooling (`scripts/gold_preset_upcomers.py`).

WHY THESE TESTS EXIST. Three of the presets in `mql5/MIDASTOUCH/` enabled live
execution for the Deriv account. Neutralising them is a change to files that can send
real orders, so the operation has to be provably correct rather than eyeballed — and the
first two attempts at it were wrong in ways that looked fine:

1. **The comment trap.** These headers DOCUMENT the live key in prose —
   `;   InpLiveExecution=true` — so replacing the text rewrote a comment and injected a
   real key line into a comment block. A preset parser that reads a documented example as
   a setting would do the same thing to a human reading it. Comments must be inert.
2. **Non-idempotency.** The inserted note contained the string it was searching for, so a
   second run rewrote the note and produced duplicate keys that had never existed. An
   operation that is unsafe to run twice is unsafe, because "was it already run?" is not
   answerable from the outside.

Both are pinned here against temporary files, so a regression fails the suite instead of
quietly editing presets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gold_preset_upcomers as gp  # noqa: E402


@pytest.fixture()
def preset(tmp_path: Path):
    def _make(text: str) -> Path:
        p = tmp_path / "probe.set"
        p.write_text(text, encoding="utf-8")
        return p
    return _make


def test_ea_declares_the_prop_governor_inputs():
    """Guards the EA, not the parser: the rules must exist as inputs to be pinnable."""
    declared = gp.ea_inputs(gp.EA.read_text(encoding="utf-8", errors="replace"))
    for key in ("InpPropGuard", "InpPropAccountSize", "InpPropTargetPct",
                "InpPropMaxDdPct", "InpPropBestDayPct", "InpPropPeakOverride"):
        assert key in declared, f"{key} missing from the EA's inputs"
    assert len(declared) >= 30


def test_input_group_labels_are_not_counted_as_parameters():
    """`input group "..."` is a label; counting it would make every preset look short."""
    declared = gp.ea_inputs('input group "=== x ==="\ninput int InpA = 1;\n')
    assert declared == {"InpA": "1"}


def test_comments_that_look_like_settings_are_inert(preset):
    """The exact trap: a documented example must not parse as the setting."""
    p = preset(";   InpLiveExecution=true\nInpLiveExecution=false\nInpMagic=7\n")
    _comments, keys, dupes = gp.read_set(p)
    assert keys["InpLiveExecution"] == "false"
    assert dupes == [], "a commented example is not a duplicate"


def test_neutralise_is_idempotent_and_leaves_comments_alone(preset):
    p = preset(';   InpLiveExecution=true\nInpArmTag=LV\nInpLiveExecution=true\n')
    first = gp.neutralise(p)
    assert "true -> false" in first
    after_one = p.read_text(encoding="utf-8")
    assert ";   InpLiveExecution=true" in after_one, "the comment was rewritten"
    second = gp.neutralise(p)
    assert second.endswith("already inert")
    assert p.read_text(encoding="utf-8") == after_one, "second run changed the file"
    _c, keys, dupes = gp.read_set(p)
    assert keys["InpLiveExecution"] == "false" and dupes == []


def test_classify_flags_an_unknown_key_because_mt5_ignores_it_silently():
    errs, _warn = gp.classify({"InpNotARealInput": "1"}, {"InpA": "1"}, armed=False)
    assert any("not an input of the EA" in e for e in errs)


def test_classify_refuses_live_execution_without_an_arming_record():
    errs, warns = gp.classify({"InpLiveExecution": "true"}, {"InpLiveExecution": "false"},
                              armed=False)
    assert any("frozen-gate event" in e for e in errs)
    assert warns == []
    errs_armed, _ = gp.classify({"InpLiveExecution": "true"},
                                {"InpLiveExecution": "false"}, armed=True)
    assert errs_armed == []


def test_unpinned_inputs_are_a_warning_not_an_error():
    """History must not have to be rewritten: a preset predating an input is a warning."""
    errs, warns = gp.classify({"InpA": "1"}, {"InpA": "1", "InpNew": "0"}, armed=False)
    assert errs == []
    assert any("InpNew" in w for w in warns)


def test_shipped_upcomers_preset_pins_every_input_and_is_paper_only():
    declared = gp.ea_inputs(gp.EA.read_text(encoding="utf-8", errors="replace"))
    _c, keys, dupes = gp.read_set(gp.TARGET)
    assert dupes == []
    assert set(keys) == set(declared), "the preset is not the complete key set"
    assert keys["InpLiveExecution"].lower() == "false"
    assert float(keys["InpPaperEquity"]) == gp.ACCOUNT_SIZE
    assert keys["InpPropMaxDdPct"] == "6.0"
    assert keys["InpPropBestDayPct"] == "20.0"


def test_collapse_removes_agreeing_duplicates_and_refuses_disagreeing_ones(preset):
    p = preset("InpA=1\nInpA=1\nInpB=2\n")
    assert "collapsed 1" in gp.collapse_duplicate_keys(p)
    _c, keys, dupes = gp.read_set(p)
    assert keys["InpA"] == "1" and dupes == []

    bad = preset("InpA=1\nInpA=2\n")
    with pytest.raises(ValueError, match="DIFFERENT values"):
        gp.collapse_duplicate_keys(bad)


def test_only_the_preset_the_arming_record_names_may_be_live():
    """Nothing on disk may send real orders without the record naming exactly that file.

    This used to assert that NO shipped preset was live, which was the right rule while
    nothing was armed. It is now the stronger, still-falsifiable form: a live-enabling
    preset is allowed only when `artifacts/live/armed.json` names it, and the inert ones
    (the paper mirror's own file and the frozen baseline) must stay inert regardless —
    their ledgers are the arms-length forward record, so real orders behind them would
    change what that record is.
    """
    record = None
    if gp.ARMING_RECORD.exists():
        record = json.loads(gp.ARMING_RECORD.read_text(encoding="utf-8"))
    named = str((record or {}).get("preset", "")).strip()
    live = [p.name for p in sorted(gp.PRESET_DIR.glob("*.set"))
            if str(gp.read_set(p)[1].get("InpLiveExecution", "false")).lower() == "true"]
    if record is None:
        assert live == [], f"{live} are live with no arming record on disk"
        return
    assert live == [named], (
        f"the arming record names {named!r} but the live presets are {live!r} — a preset "
        f"is armed that the record does not authorise, or the authorised one is not live")
    assert gp.TARGET.name != named, (
        f"{gp.TARGET.name} is the paper mirror's pin and must never be the live one")

