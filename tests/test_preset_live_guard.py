"""Guard: no preset may be live-armed unless it is the certified, gate-gated one.

WHY. On 2026-09-19 the revival audit found **nine** presets shipping with
`InpLiveExecution=true` while their own headers declared them "UNVALIDATED
starting tune" or "Measurement rig only - NOT a deploy config". A profile that
is live-armed and unvalidated is one drag-and-drop away from trading real money
on a configuration that never passed a gate — and the MIDASTOUCH program had
already been burned by exactly this configuration-leak class twice in one day
(2026-09-17).

The rule this file enforces:

    exactly ONE preset in the synthetic-indices tree may be armed
    (MitemshubAI_VOL75_LIVE.set), and it is the gate-gated live opt-in.

Anything else armed is a failure, not a warning.

Also covers the tool that performs preset edits (scripts/set_input_edit.py),
because a byte-sloppy writer is how preset drift starts: encoding must survive,
untouched keys must survive, an unknown key must be refused, and re-running with
the same value must not write at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.verify_go_live_artifacts import read_set  # noqa: E402

PRESET_DIRS = (ROOT / "mql5" / "MITEMSHUB_AI",)
ARMED_ALLOWLIST = {"MitemshubAI_VOL75_LIVE.set"}


def discover_presets(root: Path) -> list[Path]:
    """Every ``.set`` under ``root``, INCLUDING subfolders.

    Recursive on purpose. ``mql5/MITEMSHUB_AI/presets/upcomers/`` was added on
    2026-09-19 for the Upcomers prop account, and the original non-recursive
    ``glob("*.set")`` would have left every preset in that subfolder completely
    unchecked by the live-trading guard below — a silent exemption applying
    specifically to the presets aimed at a real money account.
    """
    return sorted(root.rglob("*.set"))


def presets() -> list[Path]:
    found: list[Path] = []
    for d in PRESET_DIRS:
        found.extend(discover_presets(d))
    return found


def test_the_preset_tree_is_not_empty() -> None:
    """A glob that silently matches nothing would make every test below vacuous."""
    assert len(presets()) >= 10, "preset discovery regressed — guard is now a no-op"


def test_preset_discovery_reaches_subfolders(tmp_path: Path) -> None:
    """A preset nested in a subfolder must not escape the live guard.

    Uses a temp tree rather than writing into the real one: dropping a probe
    ``.set`` into ``mql5/`` would itself become a preset if the test failed
    mid-way.
    """
    nested = tmp_path / "presets" / "upcomers"
    nested.mkdir(parents=True)
    (nested / "MitemshubAI_UPCOMERS_NACUSD_LIVE.set").write_text(
        "InpLiveExecution=true\n", encoding="utf-8"
    )
    (tmp_path / "MitemshubAI_TOPLEVEL.set").write_text(
        "InpLiveExecution=false\n", encoding="utf-8"
    )
    found = {p.name for p in discover_presets(tmp_path)}
    assert found == {
        "MitemshubAI_UPCOMERS_NACUSD_LIVE.set",
        "MitemshubAI_TOPLEVEL.set",
    }, "preset discovery is not recursive — subfolder presets are unguarded"


def test_every_preset_declares_the_execution_switch() -> None:
    """MT5 drops unknown keys, so an absent switch means code defaults decide."""
    missing = [p.name for p in presets() if "InpLiveExecution" not in read_set(p)]
    assert not missing, f"presets with no InpLiveExecution key (silent code defaults): {missing}"


def test_only_the_certified_live_preset_may_be_armed() -> None:
    armed = {p.name for p in presets() if read_set(p).get("InpLiveExecution") == "true"}
    unexpected = armed - ARMED_ALLOWLIST
    assert not unexpected, (
        "these presets are live-armed but not certified/gate-gated — disarm them "
        f"or add a deliberate allowlist entry with a reason: {sorted(unexpected)}"
    )


def test_the_certified_live_preset_is_still_armed() -> None:
    """The converse failure: disarming everything would quietly kill the only
    legitimate go-live surface and the operator would not notice."""
    live = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_LIVE.set"
    assert read_set(live)["InpLiveExecution"] == "true"


def test_the_previously_armed_unvalidated_presets_stay_disarmed() -> None:
    """Named regression pin — these nine were the actual defects found on
    2026-09-19. A future edit that re-arms one of them fails here by name."""
    offenders = [
        "MitemshubAI_VOL25_FINAL.set",
        "MitemshubAI_VOL50_FINAL.set",
        "MitemshubAI_VOL10_FINAL.set",
        "MitemshubAI_V100_M5.set",
        "MitemshubAI_V100_H1.set",
        "MitemshubAI_VOL100_AGGRO.set",
        "MitemshubAI_VOL75_AGGRO.set",
        "MitemshubAI_TESTER_BFONLY_VOL100.set",
        "MitemshubAI_TESTER_BFONLY_VOL75.set",
    ]
    for name in offenders:
        path = ROOT / "mql5" / "MITEMSHUB_AI" / name
        assert path.is_file(), f"{name} disappeared — was the disarm applied to the wrong tree?"
        assert read_set(path)["InpLiveExecution"] == "false", f"{name} is armed again"


def test_gold_live_presets_are_out_of_scope_but_still_present() -> None:
    """The MIDASTOUCH presets are the parked gold program's certified pin set.

    This guard deliberately does NOT rewrite them (that would fork the gold pin
    set from the program preserved in the MIDASTOUCH repo). It only records that
    they exist and are armed, so the fact is never discovered by surprise.
    """
    gold = ROOT / "mql5" / "MIDASTOUCH"
    if not gold.is_dir():
        pytest.skip("MIDASTOUCH presets not present in this tree")
    armed_gold = sorted(p.name for p in gold.glob("*.set")
                        if read_set(p).get("InpLiveExecution") == "true")
    assert armed_gold == [
        "MidastouchAI_LV_TP15_M15_gold.set",
        "MidastouchAI_LV_TP15_M5_gold.set",
        "MidastouchAI_LV_gold.set",
    ], ("gold live-armed preset set changed — if the gold program was retired or "
        f"re-armed, update this pin deliberately: {armed_gold}")


# ---------------------------------------------------------------------------
# scripts/set_input_edit.py — the preset writer
# ---------------------------------------------------------------------------
from scripts import set_input_edit as sie  # noqa: E402


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
    assert b"InpTypo" not in preset.read_bytes(), "an unknown key was appended — MT5 would drop it"


def test_comment_above_key_is_not_duplicated_on_rerun(preset: Path) -> None:
    for _ in range(2):
        sie.main(["x", str(preset), "--set", "InpLiveExecution=false",
                  "--comment", sie.NOTE_MARKER + " test note"])
    assert preset.read_text().count(sie.NOTE_MARKER) == 1


def test_get_returns_the_declared_value(preset: Path) -> None:
    assert sie.main(["x", str(preset), "--get", "InpBar"]) == 0
