"""Pins for the two things that decide whether this program's selection can be trusted.

WHY THIS FILE EXISTS. Two gaps were named on 2026-09-21 and are closed here, each with the
failure it would otherwise hide:

* **PBO (CSCV).** `docs/GOLD_DECIDABILITY_AUDIT_20260921.md` could not compute the
  Probability of Backtest Overfitting because no artifact held a config x fold matrix. It is
  now computed, and the property that matters is the one tested first: the estimator must
  report a HIGH probability on a matrix of pure noise and a LOW one when a configuration is
  genuinely dominant. An estimator that returns a small number either way would report
  "no overfitting risk" about a coin flip.
* **The pre-registered decision rule.** `scripts/gold_prereg_no_target.py` writes a verdict
  into `artifacts/gold_prereg_no_target.json`. That verdict must be reproducible from the
  artifact's OWN stored statistics — otherwise a record can drift away from the declaration
  it claims to obey, which is the failure `tests/test_operator_docs.py` and the corpus
  manifest exist to prevent in their own domains.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gold_prereg_no_target as pn  # noqa: E402
import gold_walkforward as gw  # noqa: E402

#: `artifacts/` is gitignored, so every measurement the repo cites lives on the machine that
#: produced it and NOT in the clone. Tests that read one therefore skip when it is absent --
#: the same guard `tests/test_best_day_cap.py` uses -- rather than failing a fresh checkout
#: for a file git was never asked to carry. Each reason names its generator.
PBO_ART = ROOT / "artifacts" / "gold_pbo.json"
PREREG_ART = ROOT / "artifacts" / "gold_prereg_no_target.json"
EXIT_ART = ROOT / "artifacts" / "gold_exit_capture.json"
ABSENT_PBO = "gold_pbo.json absent (artifacts/ is gitignored) - regenerate: "
ABSENT_PRE = "gold_prereg_no_target.json absent (artifacts/ is gitignored) - regenerate: "


# --------------------------------------------------------------------------- PBO / CSCV

def test_pbo_is_unbiased_when_the_matrix_is_pure_noise():
    """The property that makes the number worth having: no configuration is better, so the
    in-sample winner should land at or below the out-of-sample median about half the time.

    AVERAGED, not per-draw. With S=8 groups there are only C(8,4)=70 symmetric splits, so
    CSCV's estimate is noisy in any single realisation -- measured here, one seed returns
    0.186 and another 0.771 while the mean sits at 0.48. A test that pinned one seed would be
    pinning the seed rather than the estimator, and would break on the next re-run.
    """
    pbos = [gw.probability_of_backtest_overfitting(
        np.random.default_rng(seed).standard_normal((24, 31)))["pbo"] for seed in range(12)]
    assert 0.35 <= sum(pbos) / len(pbos) <= 0.65, pbos
    assert max(pbos) - min(pbos) > 0.1, pbos          # an estimate, not a constant
    first = gw.probability_of_backtest_overfitting(
        np.random.default_rng(0).standard_normal((24, 31)))
    assert first["n_combos"] == 70                    # C(8, 4)
    assert first["splits"] == 8 and first["windows"] == 31


def test_pbo_is_low_when_one_configuration_really_dominates():
    rng = np.random.default_rng(7)
    M = rng.standard_normal((12, 24)) * 0.5
    M[3, :] += 10.0                            # config 3 wins in every window
    res = gw.probability_of_backtest_overfitting(M)
    assert res["pbo"] == 0.0, res
    assert res["full_sample_best_config"] == 3
    assert res["is_winner_distinct"] == 1


def test_pbo_refuses_a_matrix_it_cannot_split_symmetrically():
    res = gw.probability_of_backtest_overfitting(np.zeros((4, 3)))
    assert res["pbo"] is None and "windows" in res["reason"]


def test_pbo_refuses_a_single_configuration():
    res = gw.probability_of_backtest_overfitting(np.zeros((1, 30)))
    assert res["pbo"] is None and "configurations" in res["reason"]


@pytest.mark.skipif(not PBO_ART.is_file(),
                    reason=ABSENT_PBO + "python scripts/gold_governed_wfo.py --mode pbo")
def test_the_committed_pbo_artifact_matches_the_shipped_harness():
    """The artifact must be the output of the code that is in the tree.

    Only the shape and the run's own declared split count are pinned here; the PBO value
    itself is a measured number and is quoted in the doc, not asserted to a literal, so a
    future re-run on a longer window does not silently turn this test into a lie.
    """
    art = json.loads(PBO_ART.read_text(encoding="utf-8"))
    gov = art["pbo"]["governed"]
    assert art["pbo"]["matrix_shape"] == [art["pbo"]["frozen_grid"], art["pbo"]["folds"]]
    assert gov["configs"] == art["pbo"]["frozen_grid"]
    assert gov["windows"] == art["pbo"]["folds"]
    assert gov["n_combos"] == 70               # the shipped default: S=8 -> C(8,4)
    assert 0.0 <= gov["pbo"] <= 1.0
    assert art["pbo"]["raw"]["pbo"] is not None, "the ungoverned comparison must be recorded too"


# --------------------------------------------------------------- the declared decision rule

def test_decide_retires_the_family_on_a_non_positive_mean():
    v, why = pn.decide({"n": 900, "mean_r": -0.01, "t": -0.3})
    assert v == "KILL" and "retired" in why


def test_decide_is_insufficient_below_the_declared_required_sample():
    """A big t on a small sample is not a pass: the declaration fixed n >= 375 first."""
    v, why = pn.decide({"n": 100, "mean_r": 0.5, "t": 4.0})
    assert v == "INSUFFICIENT" and "100" in why


def test_decide_reports_positive_but_underpowered_between_the_two_requirements():
    v, why = pn.decide({"n": 658, "mean_r": 0.42, "t": 3.28})
    assert v == "POSITIVE, UNDERPOWERED" and "not validated" in why


def test_decide_passes_only_at_the_power_requirement():
    v, _ = pn.decide({"n": 766, "mean_r": 0.42, "t": 3.28})
    assert v == "PASS"


def test_decide_fails_a_real_but_insignificant_effect():
    v, why = pn.decide({"n": 900, "mean_r": 0.05, "t": 1.2})
    assert v == "FAIL" and "1.96" in why


@pytest.mark.skipif(not PREREG_ART.is_file(),
                    reason=ABSENT_PRE + "python scripts/gold_prereg_no_target.py")
def test_the_prereg_artifact_matches_its_own_declaration():
    """Re-apply the declared rule to the artifact's stored numbers.

    This is what stops a verdict from being an opinion attached to a file: it must be
    computable from the file. If the rule or the threshold ever changes, this fails until the
    artifact is regenerated and the document re-declared.
    """
    art = json.loads(PREREG_ART.read_text(encoding="utf-8"))
    d = art["declared"]
    prim = art["results"]["primary"]
    v, why = pn.decide(prim["stats"], t_req=d["t_required"], n_for_t=d["n_required_for_t"],
                       n_for_power=d["n_required_for_power"])
    assert v == prim["verdict"] == art["verdict"], (v, prim["verdict"], art["verdict"])
    assert why == prim["reason"]
    # The declaration fixed the threshold at the N=1 value, not at the search-cost one.
    # The artifact stores the threshold rounded to 4 dp, so compare at that precision.
    assert d["t_required"] == pytest.approx(gw.selection_threshold(1), abs=5e-5)
    assert d["n_required_for_t"] == 375 and d["n_required_for_power"] == 766


@pytest.mark.skipif(not PREREG_ART.is_file(),
                    reason=ABSENT_PRE + "python scripts/gold_prereg_no_target.py")
def test_the_prereg_artifact_records_its_contamination():
    """A pre-registered record that does not say what was already known is not one."""
    art = json.loads(PREREG_ART.read_text(encoding="utf-8"))
    assert "selected by a 14-policy comparison" in art["declared"]["contamination"]
    assert art["declared"]["kill_rule"]
    assert art["results"]["discovery"]["stats"]["n"] > art["results"]["primary"]["stats"]["n"]


@pytest.mark.skipif(not (PREREG_ART.is_file() and EXIT_ART.is_file()),
                    reason="one of the two artifacts this cross-check needs is absent "
                           "(artifacts/ is gitignored)")
def test_the_replication_leg_reproduces_the_discovery_effect():
    """The harness must agree with its own earlier artifact, or the primary means nothing."""
    art = json.loads(PREREG_ART.read_text(encoding="utf-8"))
    rep = art["results"]["discovery"]["stats"]
    disc = json.loads(EXIT_ART.read_text(encoding="utf-8"))
    best = next(p for p in disc["policies"] if p["policy"] == "fixed stop 1.0 only")
    assert rep["n"] == best["n"]
    assert rep["mean_r"] == pytest.approx(best["mean_r"], abs=1e-4)
