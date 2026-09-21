"""The boundary between MIDASTOUCH and the other program, enforced mechanically.

Companion to `scripts/program_boundary.py`. The detector is exercised on synthetic
fixtures here (so it is proven to fire, not merely present), and then run against
*this* checkout, where the assertion is deliberately narrow: **no file that the
other program can compile, attach or load may be present.**

The distinction matters. A foreign *document* is a warning — it misleads a reader
but cannot be built. A foreign `.mq5`/`.ex5`/`.set` is a failure, because loading
the wrong preset or attaching the wrong binary is the concrete harm the
`904fb1c` purge ("Purge all non-MIDASTOUCH content") was performed to prevent. The
sibling checkout is checked by the script, not by this test: another directory's
contents are not this repository's to fail on.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import program_boundary as pb  # noqa: E402

OTHER = pb.PROGRAMS["itemshub"]


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_foreign_program_file_is_a_failure(tmp_path):
    root = _tree(tmp_path, {"mql5/MITEMSHUB_AI/MitemshubAI.mq5": "// other EA",
                            "mql5/MITEMSHUB_AI/presets/upcomers/x.set": "k=v"})
    found = pb.scan(root, OTHER)
    assert found["program"] == ["mql5/MITEMSHUB_AI/MitemshubAI.mq5",
                                "mql5/MITEMSHUB_AI/presets/upcomers/x.set"]
    assert found["document"] == []


def test_a_foreign_document_is_a_warning_not_a_failure(tmp_path):
    """It cannot be compiled or attached, so it is named but does not fail the run."""
    root = _tree(tmp_path, {"mql5/MITEMSHUB_AI/presets/upcomers/README.md": "# doc"})
    found = pb.scan(root, OTHER)
    assert found["program"] == []
    assert found["document"] == ["mql5/MITEMSHUB_AI/presets/upcomers/README.md"]


def test_a_clean_tree_finds_nothing(tmp_path):
    root = _tree(tmp_path, {"mql5/MIDASTOUCH/MidastouchAI.mq5": "// ours",
                            "docs/MIDASTOUCH_HEALTH_GUIDE.md": "# ours"})
    assert pb.scan(root, OTHER) == {"program": [], "document": []}


def test_generated_and_vcs_directories_are_not_scanned(tmp_path):
    """`artifacts/` and `__pycache__/` hold produced files, not either program's source."""
    root = _tree(tmp_path, {"artifacts/MitemshubAI_paper_Volatility_75_Index.csv": "x",
                            "mql5/MITEMSHUB_AI/__pycache__/x.pyc": "x"})
    assert pb.scan(root, OTHER) == {"program": [], "document": []}


def test_the_repo_is_identified_by_its_own_name():
    """A check that cannot say which side it is on cannot say what is foreign."""
    assert pb.program_of(REPO) == "midastouch"


def test_the_sibling_discovery_never_returns_this_repo():
    """The bug this file's tool exists to avoid: comparing a repo with itself and
    reporting 'no divergences found'."""
    sib = pb._find_sibling(None)
    if sib is not None:
        assert sib.resolve() != REPO.resolve()


def test_this_repo_ships_no_other_program_file():
    """The enforcement that matters: nothing loadable from the other program is here.

    A foreign document would be reported (not failed) by the script; a foreign
    program file fails here, because this repository is the one that gets compiled
    and deployed.
    """
    found = pb.scan(REPO, OTHER)
    assert found["program"] == [], (
        "files that the other program compiles/attaches/loads are present in this "
        "repository:\n  " + "\n  ".join(found["program"]))


@pytest.mark.parametrize("name", ["MIDASTOUCH", "Synthetic Indices Bot"])
def test_both_programs_are_named_in_the_mapping(name):
    assert name in pb.REPO_PROGRAM
