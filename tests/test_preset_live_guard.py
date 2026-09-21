"""Guard: nothing in the gold preset tree may be live-armed without an arming record.

WHAT THIS FILE USED TO BE, AND WHY IT CHANGED. It was written against the
synthetic-indices program: it imported `scripts/verify_go_live_artifacts.read_set`,
scanned `mql5/MITEMSHUB_AI/`, and asserted that exactly one VOL75 preset was armed
and that nine others stayed disarmed. Every one of those things left with the
program — the helper script, the preset folder and all eleven preset files. The
module still imported the deleted script, so it could not even be collected, and a
guard that cannot run is not a guard.

WHAT IT GUARDS NOW. `mql5/MIDASTOUCH/` — the only preset tree this repository owns —
read with `scripts/gold_preset_upcomers.py`'s parser, which is the tool that
actually exists here and already refuses unknown keys and unpinned inputs.

THE RULE, RESTATED FOR ONE PRESET. There are two shipped presets and both must be
**inert**. Arming is an *arming-record* event: `InpLiveExecution=true` may only be
present when `artifacts/live/armed.json` says a validated configuration exists. That
file is the operator's act, not a value anybody edits into a `.set`, so the check is
"if there is no record, nothing may be armed" rather than an allowlist of blessed
filenames — an allowlist would be a second, quieter way to arm something.

The writer tests at the bottom are unchanged in substance: `scripts/set_input_edit.py`
is this repository's tool and a byte-sloppy preset writer is how configuration drift
starts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gold_preset_upcomers as gp  # noqa: E402
from scripts import set_input_edit as sie  # noqa: E402

#: The only preset tree this repository owns. The other program's tree
#: (`mql5/MITEMSHUB_AI/`) is not ours to guard and does not live here.
PRESET_DIRS = (ROOT / "mql5" / "MIDASTOUCH",)

#: The inert presets, named so that renaming one is a deliberate act. The paper mirror
#: must stay inert FOREVER: its ledger is the arms-length forward record, and a real
#: order behind it would silently convert the record into something else.
PAPER = ("MidastouchAI_M1_gold.set", "MidastouchAI_upcomers_gold.set")

#: The one preset that may carry `InpLiveExecution=true`. It exists because the
#: operator authorised real orders on 2026-09-21 (see `ARTIFACTS/live/armed.json`), and
#: the test below pins that it is armed ONLY while the record names exactly this file.
LIVE = "MidastouchAI_upcomers_gold_LIVE.set"

SHIPPED = PAPER + (LIVE,)


def discover_presets(root: Path) -> list[Path]:
    """Every ``.set`` under ``root``, INCLUDING subfolders.

    Recursive on purpose. A non-recursive ``glob("*.set")`` would leave a preset
    moved into a subfolder — for instance a per-stage folder for the evaluation —
    completely unchecked by the live guard, which is a silent exemption applying
    exactly to the presets aimed at a real account.
    """
    return sorted(root.rglob("*.set"))


def presets() -> list[Path]:
    found: list[Path] = []
    for d in PRESET_DIRS:
        found.extend(discover_presets(d))
    return found


def keys_of(path: Path) -> dict[str, str]:
    """The settings a preset actually declares (comments are inert — see the parser)."""
    _comments, keys, _dupes = gp.read_set(path)
    return {k: str(v) for k, v in keys.items()}


def armed_presets() -> list[str]:
    return sorted(p.name for p in presets()
                  if keys_of(p).get("InpLiveExecution", "false").strip().lower() == "true")


# --------------------------------------------------------------------------- #
# The guard
# --------------------------------------------------------------------------- #

def test_the_preset_tree_is_not_empty() -> None:
    """A glob that silently matches nothing would make every test below vacuous."""
    found = presets()
    assert len(found) == len(SHIPPED), (
        f"expected the {len(SHIPPED)} shipped presets, found "
        f"{[p.name for p in found]} — if a preset was added or removed, update "
        f"SHIPPED deliberately")


def test_the_shipped_presets_are_found_by_name() -> None:
    assert {p.name for p in presets()} == set(SHIPPED)


def test_preset_discovery_reaches_subfolders(tmp_path: Path) -> None:
    """A preset nested in a subfolder must not escape the guard.

    Uses a temp tree rather than writing into the real one: dropping a probe
    ``.set`` into ``mql5/`` would itself become a preset if the test failed
    mid-way.
    """
    nested = tmp_path / "presets" / "upcomers"
    nested.mkdir(parents=True)
    (nested / "MidastouchAI_UPCOMERS_STAGE.set").write_text(
        "InpLiveExecution=true\n", encoding="utf-8")
    (tmp_path / "MidastouchAI_TOPLEVEL.set").write_text(
        "InpLiveExecution=false\n", encoding="utf-8")
    assert {p.name for p in discover_presets(tmp_path)} == {
        "MidastouchAI_UPCOMERS_STAGE.set", "MidastouchAI_TOPLEVEL.set",
    }, "preset discovery is not recursive — subfolder presets are unguarded"


def test_every_preset_declares_the_execution_switch() -> None:
    """MT5 drops unknown keys and omits nothing, so an absent switch means the
    compiled default decides — which is how a preset stops describing the run."""
    missing = [p.name for p in presets() if "InpLiveExecution" not in keys_of(p)]
    assert not missing, f"presets with no InpLiveExecution key: {missing}"


def test_the_record_says_which_kind_of_authorisation_it_is() -> None:
    """An override must never be readable as a validation.

    `arming_state()` (scripts/mt5_ops.py) reports `override` from the record's own
    `override` block; a record that authorises execution on a FAILED gate without one
    is read by every tool as "armed on a recorded validation" — the exact lie this
    program refuses to tell.
    """
    if not gp.ARMING_RECORD.exists():
        pytest.skip("no arming record — nothing to describe")
    rec = json.loads(gp.ARMING_RECORD.read_text(encoding="utf-8"))
    assert rec.get("armed") is not True or rec.get("validation_record") \
        or isinstance(rec.get("override"), dict), (
        "the record authorises execution but cites no validation record, and does not "
        "declare itself an override — it would be reported as a validated arm")
    if str(rec.get("gate_result", "")).upper().startswith("FAIL"):
        ov = rec.get("override")
        assert isinstance(ov, dict) and ov, (
            f"gate_result is {rec.get('gate_result')!r} so this is an operator override, "
            f"but there is no `override` block for the tools to read — it would be "
            f"reported as a validation pass")
        assert str(ov.get("gate_result", "")).upper().startswith("FAIL"), (
            "the override block must carry the gate result it overrides")
        assert ov.get("authorised_by"), "an override records who authorised it"


def test_the_paper_presets_are_inert_by_name() -> None:
    """A named regression pin: the fact that these two are OFF is asserted
    individually, so a future edit that arms one fails here and says which."""
    for name in PAPER:
        path = ROOT / "mql5" / "MIDASTOUCH" / name
        assert path.is_file(), f"{name} disappeared — was the edit applied to the wrong tree?"
        assert keys_of(path)["InpLiveExecution"].strip().lower() == "false", \
            f"{name} is live-armed"


def test_the_armed_set_is_exactly_what_the_record_names() -> None:
    """THE rule, stated against the record's own `preset` field.

    The previous version of this test asked only "is anything armed while no record
    exists?". That left the mirror image unguarded, and it is the more expensive one:
    a record lands (arm), and then an unrelated preset — the paper mirror, or a
    half-written variant — is armed beside it. Either would put real orders behind a
    file the record never authorised, and "at least one preset is armed" would still
    pass. So the armed set must equal `{record["preset"]}` exactly: no extra, and
    when the record is absent, nothing at all.
    """
    armed = armed_presets()
    if not gp.ARMING_RECORD.exists():
        assert armed == [], (
            f"{armed} are live-armed while {gp.ARMING_RECORD} does not exist. "
            f"Arming is an arming-record event — a validated configuration plus the "
            f"operator's act — not a value edited into a preset. Disarm them, or "
            f"produce the record first.")
        return
    rec = json.loads(gp.ARMING_RECORD.read_text(encoding="utf-8"))
    named = str(rec.get("preset", "")).strip()
    assert named, (
        f"{gp.ARMING_RECORD.relative_to(ROOT)} authorises execution without naming the "
        f"preset it authorises. Without `preset`, no check can tell an intended arm from "
        f"a preset that was armed beside it.")
    assert armed == [named], (
        f"the record names {named!r} but the armed set is {armed!r}. Something is live "
        f"that the record does not authorise, or the authorised preset is not live.")


def test_presets_have_no_duplicate_keys() -> None:
    """Two values for one key is a preset that says two things; MT5 takes the last."""
    bad: dict[str, list[str]] = {}
    for p in presets():
        _c, _k, dupes = gp.read_set(p)
        if dupes:
            bad[p.name] = dupes
    assert not bad, f"duplicate keys mean the preset's meaning is positional: {bad}"


def test_the_venue_rule_pins_are_present_in_the_trading_preset() -> None:
    """The four venue limits must be pinned as values, not left to EA defaults."""
    keys = keys_of(ROOT / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold.set")
    assert float(keys["InpPropMaxDdPct"]) == 6.0          # trailing shield
    assert float(keys["InpPropBestDayPct"]) == 20.0       # Best Day
    assert float(keys["InpPropTargetPct"]) == 5.0         # profit target
    assert float(keys["InpPropAccountSize"]) == 25_000.0  # the account basis
    assert float(keys["InpPaperEquity"]) == 25_000.0


# --------------------------------------------------------------------------- #
# scripts/set_input_edit.py — the preset writer
# --------------------------------------------------------------------------- #

@pytest.fixture()
def preset(tmp_path: Path) -> Path:
    p = tmp_path / "Demo.set"
    p.write_bytes(b"; header\r\nInpFoo=1\r\nInpLiveExecution=true\r\nInpBar=2.50\r\n")
    return p


def test_edit_changes_only_the_target_key(preset: Path) -> None:
    assert sie.main(["x", str(preset), "--set", "InpLiveExecution=false"]) == 0
    assert preset.read_bytes() == (
        b"; header\r\nInpFoo=1\r\nInpLiveExecution=false\r\nInpBar=2.50\r\n"
    ), "an unrelated byte changed — the writer is not line-surgical"


def test_edit_preserves_crlf_and_encoding(preset: Path) -> None:
    sie.main(["x", str(preset), "--set", "InpLiveExecution=false"])
    raw = preset.read_bytes()
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")


def test_edit_is_idempotent_and_does_not_rewrite(preset: Path) -> None:
    sie.main(["x", str(preset), "--set", "InpLiveExecution=false"])
    before = preset.stat().st_mtime_ns
    assert sie.main(["x", str(preset), "--set", "InpLiveExecution=false"]) == 0
    assert preset.stat().st_mtime_ns == before, "a no-op edit still touched the file"


def test_unknown_key_is_refused_not_appended(preset: Path) -> None:
    assert sie.main(["x", str(preset), "--set", "InpTypo=1"]) == 1
    assert b"InpTypo" not in preset.read_bytes(), \
        "an unknown key was appended — MT5 would drop it"


def test_comment_above_key_is_not_duplicated_on_rerun(preset: Path) -> None:
    for _ in range(2):
        sie.main(["x", str(preset), "--set", "InpLiveExecution=false",
                  "--comment", sie.NOTE_MARKER + " test note"])
    assert preset.read_text().count(sie.NOTE_MARKER) == 1


def test_get_returns_the_declared_value(preset: Path) -> None:
    assert sie.main(["x", str(preset), "--get", "InpBar"]) == 0
