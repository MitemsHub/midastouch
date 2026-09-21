"""Every tool an operator document names must exist in this repository.

WHY THIS FILE EXISTS. A document is a tool's only advertisement: an operator who
reads "run `scripts/verify_go_live_artifacts.py`" will try, and find nothing. That
had already happened here — four operator documents named scripts that this repo
does not contain, because the program they belonged to closed and the docs came
with it. A stale instruction is worse than no instruction: it costs the operator
the time to discover the tool is gone, and it implies the surface is still live.

So the rule is mechanical and applies to the whole `docs/` tree, not just a
curated list: an operator document may name only scripts that exist. The one way
out is to move the file into `RETIRED_DOCS`, which is not an escape hatch because
a retired document must then say so itself (asserted below). Unretired history
keeps its authority; that is the failure mode being closed.

The curated `OPERATOR_DOCS` list exists for the second half of the rule — those
documents additionally must not send an operator into the abandoned copy of this
project (`...\\Projects\\Synthetic Indices Bot`), which is a *different*
repository that still holds a full, stale working tree.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Documents an operator is expected to follow today, curated deliberately (the same
#: discipline as `scripts/rename_project.py`'s LIVE_REFERENCE_FILES): live
#: instructions only, never dated reports.
OPERATOR_DOCS = (
    "docs/MIDASTOUCH_HEALTH_GUIDE.md",
    "docs/MIDASTOUCH_GOLD_PLAYBOOK.md",
    "docs/MIDASTOUCH_PROTOCOL.md",
    "docs/GOLD_WFO_PROTOCOL.md",
    "mql5/MIDASTOUCH/PRESETS.md",
)

#: Documents allowed to name deleted tooling because they declare themselves records.
#: Each must carry a retirement banner AND still contain a dead reference — an
#: exemption that has outlived its reason is how a trap gets left behind.
RETIRED_DOCS = (
    "docs/GO_LIVE_CHECKLIST.md",
    "docs/ARM_A2_RESTART.md",
    "docs/ARM_E_TP20_FORWARD_PROPOSAL.md",
)

#: A reference to a script from inside the markdown. Extensions are limited to things
#: that are actually runnable, so prose like "scripts/ directory" does not match.
_SCRIPT_REF = re.compile(r"scripts[\\/]([A-Za-z0-9_.\-]+\.(?:py|ps1|cmd|bat))")

#: A reference to a virtualenv interpreter. A named script and a named interpreter are
#: the same kind of promise -- "run this" -- and this checkout shipped without a `.venv`
#: while four operator commands opened with `.venv\Scripts\python.exe`. The only venv on
#: the machine belongs to the predecessor checkout, and using it puts *that* project's
#: `src/` on the import path, which is the cross-repository load
#: `tests/test_local_imports.py` exists to prevent. So the rule is symmetric: a document
#: may name a venv interpreter only while that venv exists. Create one and the doc becomes
#: legal again; the doc never has to be trusted, only checked.
_INTERP_REF = re.compile(r"(?<![\w.\-/\\])(\.venv|venv|env)[\\/]Scripts[\\/]python\.exe", re.I)
_RETIRED_MARK = re.compile(r"RETIRED|SUPERSEDED|record, not as instructions", re.I)
_RETIRED_PATH = re.compile(r"Desktop[\\/]Projects[\\/]Synthetic Indices Bot", re.I)


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


def _dangling(text: str) -> list[str]:
    """Named scripts that do not exist, deduped and sorted (stable failure output)."""
    return sorted({m for m in _SCRIPT_REF.findall(text) if not (REPO / "scripts" / m).is_file()})


def test_the_curated_list_is_real():
    for rel in OPERATOR_DOCS + RETIRED_DOCS + ("README.md",):
        assert (REPO / rel).is_file(), f"{rel} is listed in {__file__} but does not exist"


@pytest.mark.parametrize("rel", OPERATOR_DOCS)
def test_an_operator_doc_names_only_scripts_that_exist(rel: str):
    bad = _dangling(_read(rel))
    assert not bad, (
        f"{rel} tells an operator to run a script this repository does not contain: {bad}. "
        f"Either the tool was deleted (update the doc) or the document is obsolete "
        f"(retire it, and add it to RETIRED_DOCS).")


@pytest.mark.parametrize("rel", OPERATOR_DOCS)
def test_an_operator_doc_does_not_point_into_the_abandoned_project(rel: str):
    hit = _RETIRED_PATH.search(_read(rel))
    assert not hit, (
        f"{rel} sends the operator into the abandoned copy of this project "
        f"({hit.group(0)!r}) — a different repository holding a stale working tree, "
        f"which is exactly the mistake the rename was meant to prevent")


def test_no_document_outside_the_retired_list_names_a_dead_script():
    """The whole docs/ tree plus README: a NEW stale reference fails here.

    Deliberately not limited to OPERATOR_DOCS — a fresh dangling path in a document
    nobody thought to curate is precisely the case this guards, and the only exemption
    is the explicit, self-declaring RETIRED_DOCS list.
    """
    offenders: list[str] = []
    for path in sorted((REPO / "docs").glob("*.md")) + [REPO / "README.md"]:
        rel = path.relative_to(REPO).as_posix()
        bad = _dangling(path.read_text(encoding="utf-8", errors="replace"))
        if bad and rel not in RETIRED_DOCS:
            offenders.append(f"{rel}: {bad}")
    assert not offenders, (
        "these documents name scripts that do not exist and are not marked as records:\n  "
        + "\n  ".join(offenders))


@pytest.mark.parametrize("rel", OPERATOR_DOCS + ("README.md",))
def test_a_document_names_only_interpreters_that_exist(rel: str):
    """Deliberately NOT the tree-wide sweep: a dated record is allowed to show the
    command that was actually run on that day, interpreter path and all. The live
    documents, which an operator follows today, are not."""
    named = [m.group(0) for m in _INTERP_REF.finditer(_read(rel))]
    missing = [n for n in named if not (REPO / n.replace("\\", "/")).is_file()]
    assert not missing, (
        f"{rel} tells an operator to run an interpreter that does not exist here: {missing}. "
        f"This checkout has no venv of its own; use `python`, or create the venv.")


@pytest.mark.parametrize("rel", RETIRED_DOCS)
def test_a_retired_doc_declares_itself_retired(rel: str):
    text = _read(rel)
    assert _RETIRED_MARK.search(text), (
        f"{rel} is exempt from the live-script rule but never says it is a record — an "
        f"unmarked obsolete document is a live instruction with a stale path")
    assert _dangling(text), (
        f"{rel} no longer names a missing script, so it no longer needs its exemption; "
        f"remove it from RETIRED_DOCS so the live rule applies to it again")
