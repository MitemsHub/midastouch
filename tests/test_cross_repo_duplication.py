"""Pins for the cross-repo divergence check.

THE CLASSIFICATION IS THE CONTRACT, and the reason it is three-way rather than two is
measured: all eight gold `.set` presets exist in both repos and are semantically identical
while differing in line endings, so a two-way check reports a difference on every preset
every time. A check that always cries wolf trains the operator to ignore it, which is the
state in which a REAL divergence is missed. So LINE-ENDINGS ONLY must not fail, and
DIVERGED must.
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


class TestTheToolItself:
    def test_it_refuses_rather_than_passing_when_the_other_repo_is_absent(self, tmp_path):
        """Exit 3, not 0: 'no divergences' from an unreadable side is a false green."""
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cross_repo_duplication.py"),
             "--other", str(tmp_path / "does-not-exist")],
            capture_output=True, text=True, cwd=str(ROOT))
        assert r.returncode == 3
        assert "REFUSING" in r.stderr

    @pytest.mark.skipif(not (ROOT.parent / "MIDASTOUCH").is_dir(),
                        reason="sibling midastouch checkout not present")
    def test_the_real_pair_passes_with_no_divergence(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cross_repo_duplication.py")],
            capture_output=True, text=True, cwd=str(ROOT))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no shared asset has diverged" in r.stdout

    @pytest.mark.skipif(not (ROOT.parent / "MIDASTOUCH").is_dir(),
                        reason="sibling midastouch checkout not present")
    def test_the_real_pair_reports_line_ending_differences_without_failing(self):
        """The measured reality: presets differ in bytes, not content."""
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cross_repo_duplication.py")],
            capture_output=True, text=True, cwd=str(ROOT))
        assert crd.LINE_ENDINGS_ONLY in r.stdout
        assert "DIVERGED" not in r.stdout
