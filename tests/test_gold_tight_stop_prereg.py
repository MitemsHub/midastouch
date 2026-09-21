"""Pins for the tight-stop evaluation: the priced verdict, the trial count, and its facts.

WHY THIS FILE EXISTS. This candidate is the first one in the program whose numbers were KNOWN
before its test — it is the mean-maximising row of a table the same program printed. Two things
therefore need pinning harder than usual:

* **the selection price is measured, not asserted.** The threshold comes from the number of
  distinct stops the parent record actually compared (`trials_from_parent`), so the evaluation
  cannot quietly treat a best-of-8 as a single hypothesis;
* **the uncomfortable facts stay uncomfortable.** Its advantage over the conventional stop is
  +0.1801R with t=+2.46, which is BELOW the 2.725 its own selection requires, and the record must
  keep saying so. A later summary that quotes `t=+3.53` for the stop and omits that the geometry
  effect is not itself significant would be making a claim this program has already measured to be
  false.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gold_prereg_tight_stop as gt  # noqa: E402
import gold_walkforward as gw  # noqa: E402

ART = ROOT / "artifacts" / "gold_prereg_tight_stop.json"
PARENT_ART = ROOT / "artifacts" / "gold_prereg_derived_stop.json"
ABSENT = ("artifacts/ is gitignored, so this record is local to the machine that produced it - "
          "regenerate with python scripts/gold_prereg_tight_stop.py")


# ------------------------------------------------- the trial count is measured, not assumed

def test_the_trial_count_comes_out_of_the_parent_record(tmp_path):
    p = tmp_path / "parent.json"
    p.write_text(json.dumps({"sensitivity_information_only": [
        {"stop_mult": 0.5}, {"stop_mult": 1.0}, {"stop_mult": 1.0}, {"stop_mult": 2.0}]}),
        encoding="utf-8")
    assert gt.trials_from_parent(p) == 3      # distinct multiples, duplicates collapsed


def test_an_unreadable_parent_record_is_unknown_rather_than_zero(tmp_path):
    """Zero trials would make the threshold 1.96 and silently un-price the selection."""
    assert gt.trials_from_parent(tmp_path / "nope.json") is None


@pytest.mark.skipif(not PARENT_ART.is_file(), reason="parent artifact absent (artifacts/ is gitignored)")
def test_the_declared_count_matches_what_the_parent_record_compared():
    """This is the number the declared threshold rests on."""
    assert gt.trials_from_parent() == gt.DECLARED_TRIALS_OWN == 8


def test_the_declared_threshold_is_the_priced_one_not_the_single_test():
    assert gt.gw.selection_threshold(gt.DECLARED_TRIALS_OWN) == pytest.approx(2.725, abs=0.01)
    assert gt.gw.selection_threshold(gt.PROGRAM_TRIALS) == pytest.approx(3.612, abs=0.01)
    assert gt.gw.selection_threshold(1) < gt.gw.selection_threshold(gt.DECLARED_TRIALS_OWN)


# --------------------------------------------------------------------- the two-hurdle verdict

def _decide(t, n, mean=0.6):
    return gt.decide({"n": n, "mean_r": mean, "t": t}, unsound=False, t_own=2.725, t_prog=3.612,
                     n_own=393, n_power=673)


def test_a_candidate_passing_its_own_search_but_not_the_program_hurdle_says_exactly_that():
    v, why = _decide(3.53, 658)
    assert v == "POSITIVE, UNDERPOWERED | does not clear the program-wide hurdle"
    assert "3.61" in why and "673" in why


def test_a_candidate_clearing_both_hurdles_says_so():
    v, _ = _decide(4.10, 900)
    assert v == "PASS | clears the program-wide hurdle too"


def test_below_its_own_threshold_is_a_failure():
    v, why = _decide(2.10, 658)
    assert v == "FAIL" and "does not clear the search that produced it" in why


def test_below_the_required_sample_is_insufficient_whatever_t_says():
    assert _decide(9.9, 100)[0] == "INSUFFICIENT"


def test_unsound_and_kill_outrank_everything():
    assert gt.decide({"n": 900, "mean_r": 9.0, "t": 99.0}, unsound=True, t_own=2.725,
                     t_prog=3.612, n_own=1, n_power=1)[0] == "UNSOUND DERIVATION"
    assert gt.decide({"n": 900, "mean_r": -0.01, "t": -0.2}, unsound=False, t_own=2.725,
                     t_prog=3.612, n_own=1, n_power=1)[0] == "KILL"


def test_required_n_grows_with_the_threshold_and_with_power():
    base = gt.required_n(0.6, 4.38, 2.725)
    assert gt.required_n(0.6, 4.38, 3.612) > base
    assert gt.required_n(0.6, 4.38, 2.725, power=True) > base
    assert gt.required_n(-0.1, 4.38, 2.725) is None


# ------------------------------------------------------------------------------- the artifact

@pytest.mark.skipif(not ART.is_file(), reason=ABSENT)
def test_the_artifact_verdict_recomputes_from_its_own_numbers():
    art = json.loads(ART.read_text(encoding="utf-8"))
    d, prim = art["declared"], art["primary"]
    v, why = gt.decide({"n": prim["stats"]["n"], "mean_r": prim["stats"]["mean_r"],
                        "t": prim["stats"]["t"]}, unsound=art["candidate"]["unsound"],
                       t_own=d["t_required_own"], t_prog=d["t_required_program"],
                       n_own=d["n_required_own"], n_power=d["n_required_power"])
    assert v == prim["verdict"] == art["verdict"]
    assert why == prim["reason"]


@pytest.mark.skipif(not ART.is_file(), reason=ABSENT)
def test_the_geometry_advantage_is_recorded_and_is_below_its_own_threshold():
    """The uncomfortable fact, pinned.

    The candidate's mean is +0.6031R and its t clears the priced threshold; the PAIRED advantage
    over the conventional stop is +0.1801R at t=+2.46, which does not. Both live in the record, and
    this test fails if the second is ever dropped or restated.
    """
    art = json.loads(ART.read_text(encoding="utf-8"))
    paired = art["primary"]["paired_vs_1_0atr"]
    assert paired["mean_r"] == pytest.approx(0.1801, abs=1e-3)
    assert paired["t"] < art["declared"]["t_required_own"]
    conv = art["primary"]["comparators"]["conventional 1.0xATR"]
    assert art["primary"]["stats"]["n"] == conv["n"], "same entries, or the pairing is void"
    assert art["primary"]["stats"]["sd"] > conv["sd"], "the tight stop is the higher-variance one"


@pytest.mark.skipif(not ART.is_file(), reason=ABSENT)
def test_the_record_states_that_its_own_numbers_came_from_the_run_that_suggested_it():
    art = json.loads(ART.read_text(encoding="utf-8"))
    assert "produced by the run that suggested it" in art["declared"]["contamination"]
    assert art["declared"]["trials_measured_in_parent_record"] == gt.DECLARED_TRIALS_OWN
    assert art["candidate"]["unsound"] is False
    assert art["sizing_scan_post_hoc"], "the declared sizing leg must be recorded"
