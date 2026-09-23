"""The spread-flatness harness: the corpus premise vs the arm's own measurement.

WHY THIS FILE EXISTS. v1.27 gave the arm a live per-hour spread measurement; this file
pins the harness that will one day let it falsify the session finding's flatness
premise. The pins hold the two properties that make the harness trustworthy: the corpus
side reads hours from the file's own `iso` declaration (no era-pin inheritance), and the
verdict rule is applied exactly as the module states it — in SESSION hours, because
rollover hours at five-figure samples are the reason a session gate exists, and letting
them drive the verdict would test a claim nobody made.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_spread_flatness as sf


def hours_from_means(means: dict[int, float], n: int = 100) -> dict:
    return {h: {"n": n, "mean": m, "max": m} for h, m in means.items()}


# --- the corpus side ------------------------------------------------------------------

def test_corpus_hours_come_from_the_iso_declaration(tmp_path):
    """The `time` epoch is server-stamped; `iso` is the file's own UTC declaration.
    A server-stamped epoch read as UTC would shift every hour by the offset."""
    p = tmp_path / "corpus.csv"
    # 23:45 SERVER (+120) == 21:45 UTC: the row belongs to hour 21, not 23.
    p.write_text("time,iso,open,high,low,close,tick_volume,spread\n"
                 "1768223700,2026-01-12T21:45:00+00:00,1,1,1,1,1,4\n",
                 encoding="utf-8")
    out = sf.corpus_hourly_spread(str(p))
    assert 21 in out["hours"] and 23 not in out["hours"], out


def test_corpus_spread_is_in_points_and_averaged_per_hour(tmp_path):
    p = tmp_path / "corpus.csv"
    p.write_text("time,iso,open,high,low,close,tick_volume,spread\n"
                 "0,2026-01-12T10:00:00+00:00,1,1,1,1,1,4\n"
                 "0,2026-01-12T10:15:00+00:00,1,1,1,1,1,6\n",
                 encoding="utf-8")
    out = sf.corpus_hourly_spread(str(p))
    assert out["hours"][10]["mean"] == 5.0 and out["hours"][10]["max"] == 6.0


# --- the verdict rule, as stated ------------------------------------------------------

def test_the_premise_is_judged_in_session_hours_not_rollover():
    """An all-hours ratio of ~9 (rollover) must not fail a flat SESSION premise."""
    corpus = {"source": "x", "hours": hours_from_means(
        {**{h: 25.0 for h in range(4, 18)}, 21: 100.0, 22: 200.0, 23: 150.0})}
    live = {"epoch": 1, "day": 1, "hours": hours_from_means(
        {h: 50.0 for h in range(4, 18)}, n=500)}
    out = sf.verdict_for(live, corpus)
    assert out["verdict"] in ("FLATNESS HOLDS", "PREMISE MISALIGNED"), out
    assert "FLATNESS VIOLATED" != out["verdict"]


def test_flatness_violated_names_the_ratio():
    corpus = {"source": "x", "hours": hours_from_means({h: 25.0 for h in range(4, 18)})}
    # hour 05 ten times wider than hour 10: the premise is false on the live venue
    live = {"epoch": 1, "day": 1, "hours": hours_from_means(
        {**{h: 25.0 for h in range(4, 18)}, 5: 250.0}, n=500)}
    out = sf.verdict_for(live, corpus)
    assert out["verdict"] == "FLATNESS VIOLATED", out
    assert "false on the live venue" in out["note"]


def test_premise_misaligned_when_flat_but_at_a_different_level():
    corpus = {"source": "x", "hours": hours_from_means({h: 25.0 for h in range(4, 18)})}
    live = {"epoch": 1, "day": 1, "hours": hours_from_means(
        {h: 80.0 for h in range(4, 18)}, n=500)}   # flat, but > 2x the corpus level
    out = sf.verdict_for(live, corpus)
    assert out["verdict"] == "PREMISE MISALIGNED", out


def test_pending_until_enough_hours_speak():
    corpus = {"source": "x", "hours": hours_from_means({h: 25.0 for h in range(4, 18)})}
    live = {"epoch": 1, "day": 1, "hours": hours_from_means({h: 25.0 for h in range(4, 9)})}
    out = sf.verdict_for(live, corpus)
    assert out["verdict"] == "PENDING", out


def test_pending_when_there_are_no_live_rows_at_all():
    corpus = {"source": "x", "hours": hours_from_means({h: 25.0 for h in range(4, 18)})}
    out = sf.verdict_for(None, corpus)
    assert out["verdict"] == "PENDING"
    assert out["live"]["hours"] == {}


def test_the_rule_rides_the_artifact():
    corpus = {"source": "x", "hours": hours_from_means({h: 25.0 for h in range(4, 18)})}
    out = sf.verdict_for(None, corpus)
    for key in ("min_live_hours", "min_live_samples", "live_flat_ratio",
                "corpus_live_tolerance"):
        assert key in out["rule"], f"the stated rule must name {key}"


# --- the parser is one definition -----------------------------------------------------

def test_the_ledger_side_uses_morning_status_spread_hours():
    """One SPREADHOUR parser: the harness reuses the morning report's, it does not
    re-implement the row layout a third time."""
    src = (REPO / "scripts" / "midas_spread_flatness.py").read_text(encoding="utf-8")
    assert "from morning_status import spread_hours" in src


def test_the_premise_doc_names_the_study_that_owns_it():
    src = (REPO / "scripts" / "midas_spread_flatness.py").read_text(encoding="utf-8")
    assert "FREQUENCY_AXES_PREREG_20260922.md" in src, \
        "the harness must name the pre-registration the premise comes from"
