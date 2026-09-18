"""Source + structure tests: the parity harness's two expert load paths.

The hazard being pinned (V2 register §2, discovered 2026-09-17): the live
gold charts load ``Experts\\MITEMSHUB_AI\\MidastouchAI.ex5`` — the same path
the parity harness used by default for its tester passes. A re-cert launched
at the live path swaps the binary under the running §13 arms at relaunch (a
mid-window deploy). The shadow-path mechanism exists precisely so an
un-deployed build is certified without ever touching the live load path.

These pins make the separation structural, not procedural:
  * the harness carries BOTH paths as named module constants, and they are
    never equal;
  * the deployed-path default and the --expert-path override are wired to
    the right constants;
  * the register documents the hazard and its two-path mechanism, and the
    register's certification command names the shadow path — so a future
    register edit that re-points the command at the live path fails here.

Comment-stripped source, per the test_midas_time.py convention.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PARITY = REPO / "scripts" / "midas_parity.py"
REGISTER = REPO / "docs" / "MIDASTOUCH_V2_REGISTER.md"


def src(path: Path) -> str:
    """Source with comments stripped (naive /* */ and // removal)."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


# --- the two paths exist as constants, distinct ------------------------------

def test_both_path_constants_exist() -> None:
    s = src(PARITY)
    assert re.search(r'^EXPERT\s*=\s*r?"', s, re.M), (
        "harness must carry the DEPLOYED expert path as module constant EXPERT")
    assert re.search(r'^SHADOW_EXPERT\s*=\s*r?"', s, re.M), (
        "harness must carry the SHADOW certification path as module constant "
        "SHADOW_EXPERT — a shadow path that lives only in CLI strings is not "
        "pinnable and invites a live-path relaunch")


def test_paths_are_distinct() -> None:
    s = src(PARITY)
    live = re.search(r'^EXPERT\s*=\s*r?"([^"]+)"', s, re.M)
    shadow = re.search(r'^SHADOW_EXPERT\s*=\s*r?"([^"]+)"', s, re.M)
    assert live and shadow
    assert live.group(1) != shadow.group(1), (
        "deployed and shadow expert paths must differ — if they ever converge, "
        "a parity re-cert swaps the binary under the live §13 charts")


def test_shadow_path_is_the_registered_parity_folder() -> None:
    s = src(PARITY)
    shadow = re.search(r'^SHADOW_EXPERT\s*=\s*r?"([^"]+)"', s, re.M)
    assert shadow and shadow.group(1) == r"MIDASTOUCH_parity\MidastouchAI", (
        "shadow path must stay the registered MIDASTOUCH_parity folder — "
        "renaming it orphans the register's §2 baseline certification")


# --- the wiring: default = deployed, override = shadow ------------------------

def test_run_one_mode_defaults_to_the_deployed_path() -> None:
    s = src(PARITY)
    m = re.search(r"def run_one_mode\(([^)]*)\)", s, re.S)
    assert m, "run_one_mode must exist"
    assert re.search(r"expert(\s*:\s*str)?\s*=\s*EXPERT\b", m.group(1)), (
        "run_one_mode's default expert must be the DEPLOYED path constant "
        "(the certified re-cert semantics), never the shadow path")


def test_expert_path_override_is_wired_to_the_shadow_constant() -> None:
    s = src(PARITY)
    m = re.search(r'add_argument\(\s*"--expert-path"(.*?)\)', s, re.S)
    assert m, "--expert-path must exist (the shadow-path certification flag)"
    flag = m.group(1)
    assert re.search(r"\bdefault\s*=\s*EXPERT\b", flag), (
        "--expert-path's default must be the deployed EXPERT constant, so the "
        "bare command keeps the certified deployed-path semantics")
    assert re.search(r'\bdest\s*=\s*"expert_path"', flag), (
        "--expert-path must dest into expert_path")


# --- the register side: hazard documented, command shadow-safe ----------------

def test_register_documents_the_load_path_hazard() -> None:
    reg = REGISTER.read_text(encoding="utf-8")
    assert re.search(r"Live-load-path hazard", reg), (
        "register §2 must keep the load-path hazard note — it is the only "
        "written record of why the shadow mechanism exists")


def test_register_certification_command_names_the_shadow_path() -> None:
    reg = REGISTER.read_text(encoding="utf-8")
    code_blocks = re.findall(r"```[a-z]*\n(.*?)```", reg, re.S)
    assert any("midas_parity.py" in b and "--expert-path" in b
               and "MIDASTOUCH_parity" in b for b in code_blocks), (
        "the register's certification command must name the shadow path "
        "(MIDASTOUCH_parity) via --expert-path — a register edit that "
        "re-points the command at the deployed path fails this pin")


def test_harness_selftest_prints_the_shadow_banner() -> None:
    s = src(PARITY)
    assert re.search(r"SHADOW-PATH certification", s), (
        "an --expert-path run must announce the shadow banner so the operator "
        "sees the live load path is not touched")
