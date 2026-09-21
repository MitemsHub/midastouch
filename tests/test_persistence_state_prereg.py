"""Pins for the persistence study: the decomposition, the bins, and the refusal to carry a cell.

WHY THIS FILE EXISTS. This study answers "is the decay regime-driven?" in two different ways, and
each needs pinning for a different reason:

* the **descriptive decomposition** is the answer that no selection can corrupt, so its arithmetic
  is tested on synthetic worlds where the answer is known exactly: a pure reweighting of cells must
  come out as ~100% composition, and a pure within-cell decay as ~0%. If that arithmetic is wrong,
  the study's headline claim is wrong in a way no sample size would reveal.
* the **H1 selection** must be able to refuse. The tempting cell in this run has t=+2.06, which
  *looks* significant against the single-test 1.96 and is exactly what the best-of-11 threshold
  (2.828) exists to reject. The artifact therefore has to record that nothing was carried to H2,
  and that has to stay true.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_persistence_state as ps  # noqa: E402
import gold_walkforward as gw  # noqa: E402

ART = ROOT / "artifacts" / "gold_persistence_state.json"
ABSENT = ("artifacts/ is gitignored, so this record is local to the machine that produced it - "
          "regenerate with python scripts/gold_persistence_state.py")


# ------------------------------------------------- the decomposition's arithmetic

def test_a_pure_reweighting_is_attributed_to_composition():
    """Same two cells, same per-cell means, opposite weights: the gap is all composition."""
    h1 = {"A": [1.0] * 90, "B": [0.0] * 10}
    h2 = {"A": [1.0] * 10, "B": [0.0] * 90}
    d = ps.decompose(h1, h2)
    h1_mean, h2_mean = 0.9, 0.1
    assert d["h2_at_h1_mix_mean_r"] == pytest.approx(h1_mean, abs=1e-9)
    gap = h1_mean - h2_mean
    explained = (d["h2_at_h1_mix_mean_r"] - h2_mean) / gap
    assert explained == pytest.approx(1.0, abs=1e-9)
    assert d["total_variation"] == pytest.approx(0.8, abs=1e-9)


def test_a_pure_within_state_change_is_attributed_to_nothing_but_within_state():
    """Identical mixes, both cells decaying: reweighting cannot explain any of it."""
    h1 = {"A": [1.0] * 50, "B": [1.0] * 50}
    h2 = {"A": [-0.5] * 50, "B": [-0.5] * 50}
    d = ps.decompose(h1, h2)
    assert d["total_variation"] == pytest.approx(0.0, abs=1e-9)
    assert d["h2_at_h1_mix_mean_r"] == pytest.approx(-0.5, abs=1e-9)   # == H2's own mean


def test_the_decomposition_reports_the_weight_it_could_not_cover():
    """A cell that vanished between halves must shrink the counterfactual's coverage, not vanish
    silently -- otherwise a 90%-absent cell could be presented as a composition finding."""
    h1 = {"A": [1.0] * 50, "GONE": [1.0] * 50}
    h2 = {"A": [1.0] * 50}
    d = ps.decompose(h1, h2)
    assert d["weight_covered"] == pytest.approx(0.5, abs=1e-9)


# ------------------------------------------------------------------- the declared bins

def test_cell_of_bins_at_the_declared_boundaries():
    ok = {}
    hours = np.array([5.0, 6.0, 12.0, 17.0, 21.0])
    atr = np.array([0.799, 0.800, 1.299, 1.300, 1.000])
    med = np.ones(5)
    labels = [ps.cell_of(i, ok, atr, med, hours, None) for i in range(5)]
    assert labels[0] == "vol=low|sess=00-06"        # 0.799 is below the low/normal line
    assert labels[1] == "vol=normal|sess=06-12"     # 0.800 is on it, and belongs to normal
    assert labels[2] == "vol=normal|sess=12-17"
    assert labels[3] == "vol=high|sess=17-22"       # 1.300 starts high
    assert labels[4] == "vol=normal|sess=17-22"


def test_cell_of_adds_the_news_axis_only_when_a_mask_is_supplied():
    ok = {}
    atr, med, hours = np.array([1.0]), np.ones(1), np.array([8.0])
    mask = np.array([True])
    assert ps.cell_of(0, ok, atr, med, hours, None) == "vol=normal|sess=06-12"
    assert ps.cell_of(0, ok, atr, med, hours, mask) == "vol=normal|sess=06-12|news=IN"


def test_the_news_axis_refuses_with_a_reason_when_the_calendar_is_missing(monkeypatch, tmp_path):
    """The axis must be DROPPED with a reason, never assumed in either direction."""
    import midas_parity
    monkeypatch.setattr(midas_parity, "news_calendar_path",
                        lambda: tmp_path / "not_there.csv")
    mask, note = ps.news_axis(np.linspace(0, 1000, 10), 10)
    assert mask is None
    assert "absent" in note


# ------------------------------------------------------------------------ the artifact

@pytest.mark.skipif(not ART.is_file(), reason=ABSENT)
def test_the_record_says_nothing_was_carried_to_the_second_half():
    art = json.loads(ART.read_text(encoding="utf-8"))
    assert art["h2_test"]["carried_to_h2"] is False
    assert art["h2_test"]["stats"] is None
    assert art["verdict"] == "NO STATE RULE SURVIVES SELECTION"
    # ...and it is the DECLARED rule that refuses it, recomputed from the record's own numbers.
    assert art["h1_selection"]["h1_stats"]["t"] < art["declared"]["t_required_selection"]
    assert art["declared"]["t_required_selection"] == pytest.approx(
        gw.selection_threshold(art["declared"]["cells_present"]), abs=1e-3)


@pytest.mark.skipif(not ART.is_file(), reason=ABSENT)
def test_the_record_labels_its_robustness_line_as_outside_the_declaration():
    """The declaration fixed that a failed selection carries nothing, so the extra observation of
    what happened to the rejected cell is post-hoc and must be marked as such."""
    art = json.loads(ART.read_text(encoding="utf-8"))
    assert art["robustness_is_post_hoc_not_declared"] is True
    assert art["robustness_stop_1_384"]["n"] > 0


@pytest.mark.skipif(not ART.is_file(), reason=ABSENT)
def test_the_decay_is_recorded_as_within_state_not_compositional():
    """The headline finding, pinned as a RELATIONSHIP rather than a literal.

    If the counterfactual (H2 at H1's state mix) ever moved closer to H1's mean than to H2's own,
    the conclusion would flip to "the states changed" -- and that reversal must force this test to
    be revisited deliberately instead of a summary quietly changing its story.
    """
    art = json.loads(ART.read_text(encoding="utf-8"))
    dec = art["descriptive_composition"]
    counter, actual = dec["h2_at_h1_mix_mean_r"], dec["h2_actual_mean_r"]
    h1_mean = art["unfiltered"]["h1"]["mean_r"]
    assert counter is not None
    assert abs(counter - actual) < abs(counter - h1_mean), (counter, actual, h1_mean)
    assert dec["total_variation"] < 0.25, "the state mix must barely have moved to say this"
    assert dec["weight_covered"] > 0.95, "an uncovered weight could fake the result"


@pytest.mark.skipif(not ART.is_file(), reason=ABSENT)
def test_the_news_axis_is_recorded_as_measured_with_its_count():
    art = json.loads(ART.read_text(encoding="utf-8"))
    assert art["news_axis"]["measured"] is True
    assert "top-tier events" in art["news_axis"]["note"]
    assert art["declared"]["axes"]["news"].startswith("+/-15")
