"""Pins for the cross-repo divergence check.

THE CLASSIFICATION IS THE CONTRACT, and the reason it is three-way rather than two is
measured: shared files exist in both checkouts and are semantically identical while
differing in line endings, so a two-way check reports a difference on every one of
them every time. A check that always cries wolf trains the operator to ignore it,
which is the state in which a REAL divergence is missed. So LINE-ENDINGS ONLY must
not fail, and DIVERGED must.

THE POLICY IS THE OTHER HALF. A *vendored* file (copied into this repo from the
sibling) must stay identical — divergence is a failure, because a copy nobody
re-checks is two files pretending to be one. A *forked* file is one both programs
keep on purpose while trading different venues: divergence there is the honest state
and must NOT fail. And the check must refuse two things outright rather than report a
green: an unreadable sibling, and a sibling that resolves to this repository itself —
comparing a checkout with itself passes forever and proves nothing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cross_repo_duplication as crd  # noqa: E402

LF = b"InpMagic=7801001\nInpMode=0\n"
CRLF = b"InpMagic=7801001\r\nInpMode=0\r\n"
BOM_LF = b"\xef\xbb\xbfInpMagic=7801001\nInpMode=0\n"

#: The pair that matters most: this repo's vendored copy, and the sibling's original.
VENDORED_MINE, VENDORED_THEIRS = crd.VENDORED[0]

SIBLING = crd.resolve_sibling(None)[0]
needs_sibling = pytest.mark.skipif(SIBLING is None,
                                   reason="sibling checkout not present on this machine")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cross_repo_duplication.py"), *args],
        capture_output=True, text=True, cwd=str(ROOT))


def fake_sibling(tmp_path: Path, **files: bytes) -> Path:
    """A minimal checkout-lookalike holding only the named files."""
    other = tmp_path / "Synthetic Indices Bot"
    for rel, blob in files.items():
        p = other / Path(*rel.split("__"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    other.mkdir(exist_ok=True)
    return other


class TestClassification:
    def test_byte_identical_is_identical(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(CRLF)
        b.write_bytes(CRLF)
        cls, _ = crd.classify(a, b)
        assert cls == crd.IDENTICAL

    def test_line_endings_are_not_a_divergence(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(LF)
        b.write_bytes(CRLF)
        cls, detail = crd.classify(a, b)
        assert cls == crd.LINE_ENDINGS_ONLY
        assert detail["mine_ends"] == "LF" and detail["their_ends"] == "CRLF"

    def test_a_bom_is_not_a_divergence(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(LF)
        b.write_bytes(BOM_LF)
        assert crd.classify(a, b)[0] == crd.LINE_ENDINGS_ONLY

    def test_a_real_edit_is_a_divergence_and_counts_lines(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(LF)
        b.write_bytes(b"InpMagic=7801001\nInpMode=2\n")
        cls, detail = crd.classify(a, b)
        assert cls == crd.DIVERGED
        assert detail["differing_lines"] == 1

    def test_an_extra_line_is_a_divergence(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(LF)
        b.write_bytes(LF + b"InpExtra=1\n")
        cls, detail = crd.classify(a, b)
        assert cls == crd.DIVERGED
        assert detail["differing_lines"] == 1

    def test_absence_is_reported_not_treated_as_agreement(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(LF)
        cls, _ = crd.classify(a, b)
        assert cls == crd.MISSING_THERE
        cls, _ = crd.classify(b, a)
        assert cls == crd.MISSING_HERE

    def test_cr_only_files_normalise(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(LF)
        b.write_bytes(b"InpMagic=7801001\rInpMode=0\r")
        assert crd.classify(a, b)[0] == crd.LINE_ENDINGS_ONLY


class TestPairing:
    """A basename alone is not an identity — the bug this class exists for."""

    def test_a_same_basename_at_a_different_depth_is_not_a_match(self, tmp_path):
        tree = tmp_path / "theirs"
        (tree / "risk").mkdir(parents=True)
        (tree / "backtest").mkdir(parents=True)
        (tree / "risk" / "__init__.py").write_text("risk\n")
        (tree / "backtest" / "__init__.py").write_text("backtest\n")
        rels, by_name = crd.tree_index(tree)
        # No same-relative-path file, and the basename is ambiguous -> not decidable.
        assert crd.counterpart(tree, "execution/__init__.py", by_name) is None

    def test_the_same_relative_path_is_a_match(self, tmp_path):
        tree = tmp_path / "theirs"
        (tree / "risk").mkdir(parents=True)
        (tree / "risk" / "__init__.py").write_text("risk\n")
        _, by_name = crd.tree_index(tree)
        assert crd.counterpart(tree, "risk/__init__.py", by_name) == tree / "risk" / "__init__.py"

    def test_an_unambiguous_single_basename_is_still_matched(self, tmp_path):
        """A shared file that moved layout is still comparable."""
        tree = tmp_path / "theirs"
        (tree / "elsewhere").mkdir(parents=True)
        (tree / "elsewhere" / "paper_broker.py").write_text("x\n")
        _, by_name = crd.tree_index(tree)
        assert crd.counterpart(tree, "execution/paper_broker.py", by_name) == \
            tree / "elsewhere" / "paper_broker.py"

    def test_the_vendored_pair_maps_across_the_two_package_names(self):
        """The packages are named differently now; the pair must still be explicit."""
        assert VENDORED_MINE.startswith("src/midas_prop/")
        assert VENDORED_THEIRS.startswith("src/synthetic_trader/")
        assert VENDORED_MINE.endswith("execution/paper_broker.py")


class TestTheToolItself:
    def test_it_refuses_rather_than_passing_when_the_other_repo_is_absent(self, tmp_path):
        """Exit 3, not 0: 'no divergences' from an unreadable side is a false green."""
        r = run("--other", str(tmp_path / "does-not-exist"))
        assert r.returncode == 3
        assert "REFUSING" in r.stderr

    def test_it_refuses_to_compare_this_repo_with_itself(self):
        """The old default did exactly this, so it passed forever and proved nothing."""
        r = run("--other", str(ROOT))
        assert r.returncode == 3
        assert "with itself" in r.stderr

    def test_a_vendored_divergence_is_a_failure(self, tmp_path):
        """The whole point: a copied file that has drifted must not pass."""
        other = fake_sibling(
            tmp_path, **{f"{VENDORED_THEIRS}".replace("/", "__"): b"# a different broker\n"})
        r = run("--other", str(other))
        assert r.returncode == 1, r.stdout + r.stderr
        assert "DIVERGED" in r.stdout
        assert VENDORED_MINE in r.stdout

    def test_a_forked_difference_is_not_a_failure(self, tmp_path):
        """Both programs keep these on purpose; differing is the honest state."""
        files = {VENDORED_THEIRS.replace("/", "__"): (ROOT / VENDORED_MINE).read_bytes()}
        rel_mine, rel_theirs = crd.FORKED[0]
        files[rel_theirs.replace("/", "__")] = b"# this program's own paper chain\n"
        other = fake_sibling(tmp_path, **files)
        r = run("--other", str(other))
        assert r.returncode == 0, r.stdout + r.stderr
        assert crd.FORKED_EXPECTED in r.stdout
        assert "expected" in r.stdout

    def test_the_sweep_names_a_same_named_file_it_did_not_declare(self, tmp_path):
        """New shares must not join the unchecked set quietly."""
        tree = tmp_path / "other" / "src" / "synthetic_trader" / "risk"
        tree.mkdir(parents=True)
        (tree / "upcomers_rules.py").write_text("# the sibling's own copy\n")
        ours = ROOT / "src" / "midas_prop" / "risk" / "upcomers_rules.py"
        assert ours.is_file(), "fixture assumption: this file exists on our side"
        r = run("--other", str(tmp_path / "other"))
        assert "upcomers_rules.py" in r.stdout
        assert "NOT declared as vendored" in r.stdout
        assert r.returncode == 0, "an undeclared same-name file is a REVIEW, not a failure"

    def test_the_sibling_is_resolved_by_name_not_guessed(self):
        path, tried = crd.resolve_sibling(None)
        assert tried, "resolution must report what it looked for when it fails"
        if path is not None:
            assert path.name in crd.SIBLING_DIR_NAMES


class TestTheRealPair:
    @needs_sibling
    def test_the_real_pair_passes_and_actually_compares_the_vendored_broker(self):
        r = run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "paper_broker.py" in r.stdout, (
            "the vendored pair was not compared — a check that skips its subject is "
            "the failure mode this tool exists to prevent")
        assert "no vendored asset has diverged" in r.stdout

    @needs_sibling
    def test_the_real_pair_reports_its_forked_files_as_expected(self):
        r = run()
        assert crd.FORKED_EXPECTED in r.stdout
        assert "DIVERGED" not in r.stdout.split("-- forked")[0], (
            "a vendored file diverged on the real pair")

    @needs_sibling
    def test_the_packages_are_named_differently_on_the_two_sides(self):
        """If this stops being true, the explicit pair mapping is hiding a collision."""
        assert (ROOT / "src" / "midas_prop").is_dir()
        assert (ROOT / "src" / "synthetic_trader").is_dir() is False
        assert (SIBLING / "src" / "synthetic_trader").is_dir()
