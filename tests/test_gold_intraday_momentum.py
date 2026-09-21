"""The momentum study's declaration, and the artifact's agreement with its own rule.

WHY THIS FILE EXISTS. `docs/GOLD_INTRADAY_MOMENTUM_PROTOCOL.md` was written before the run, and
its only value is that it still describes the run: the window, the sign, the cost model and —
most of all — the three-way decision rule. A pre-registration whose decision rule can be read
after the fact to mean whatever the numbers happen to support is a description of the past.

These pins are cheap: they read the declaration and the generated artifact rather than
re-running the study, so they fail the moment either drifts. The harness's own arithmetic is
pinned separately and offline by `gold_intraday_momentum.selftest()`.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gold_intraday_momentum as gim  # noqa: E402

PROTOCOL = ROOT / "docs" / "GOLD_INTRADAY_MOMENTUM_PROTOCOL.md"
VERDICT = ROOT / "docs" / "GOLD_INTRADAY_MOMENTUM_VERDICT_20260921.md"
ART = ROOT / "artifacts" / "gold_intraday_momentum.json"


def _load(p: Path) -> dict:
    if not p.is_file():
        pytest.skip(f"{p.name} not generated in this checkout")
    return json.loads(p.read_text(encoding="utf-8"))


# --- the harness's own arithmetic --------------------------------------------------------

def test_selftest_passes(capsys) -> None:
    """Direction, cost, the $0.10 floor, the skips, the ATR causality and the decision rule."""
    assert gim.selftest() == 0
    out = capsys.readouterr().out
    assert "12/12 passed" in out


# --- the declaration --------------------------------------------------------------------

def test_the_protocol_declares_the_sign_before_any_number() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "b > 0" in text
    assert re.search(r"rejects.*momentum", text, re.I), "a negative slope must be a rejection"


def test_the_protocol_declares_all_three_verdicts_not_just_pass_and_fail() -> None:
    """The UNDECIDED branch is the one that stops a sample this size from being reported as
    'no edge'. It has to be in the declaration, not invented after seeing the numbers."""
    text = PROTOCOL.read_text(encoding="utf-8")
    for token in ("PASS", "FAIL", "UNDECIDED AT THIS N"):
        assert token in text
    assert "minimum detectable effect" in text.lower()
    assert "1.96" in text


def test_the_protocol_declares_the_window_in_stamps_and_the_era_mapping() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    for stamp in ("22:15", "22:30", "00:00", "23:00"):
        assert stamp in text
    assert "21:15–21:45 UTC" in text and "20:15–20:45 UTC" in text


def test_the_declared_window_is_what_the_code_uses() -> None:
    assert gim.STAMPS_REQUIRED == ("00:00", "22:00", "22:15", "22:30")
    assert (gim.ROD_OPEN, gim.LH_OPEN, gim.LH_CLOSE) == ("00:00", "22:15", "22:30")
    assert gim.STOP_ATR_MULT == 2.0 and gim.T_CRIT == 1.96


# --- the artifact agrees with its own rule -----------------------------------------------

def test_the_recorded_pooled_numbers_recompute_from_the_rows() -> None:
    art = _load(ART)
    rows = art["rows"]
    n = len(rows)
    assert n == art["pooled"]["n"] == art["coverage"]["qualifying_days"]
    mean = sum(r["net_r"] for r in rows) / n
    sd = math.sqrt(sum((r["net_r"] - mean) ** 2 for r in rows) / (n - 1))
    assert abs(mean - art["pooled"]["mean"]) < 5e-4
    assert abs(sd - art["pooled"]["sd"]) < 5e-4
    assert abs(mean / (sd / math.sqrt(n)) - art["pooled"]["t"]) < 0.02


def test_the_minimum_detectable_effect_is_the_declared_formula() -> None:
    art = _load(ART)
    p = art["pooled"]
    assert abs(p["mde"] - (1.96 + 0.8416) * p["sd"] / math.sqrt(p["n"])) < 5e-4


def test_the_recorded_verdict_is_the_declared_rule_applied_to_the_recorded_numbers() -> None:
    """This is the pin that matters: the verdict cannot drift from the numbers, and the
    numbers cannot be replaced while keeping the verdict."""
    art = _load(ART)
    eras = [e for e in art["per_era"] if e["n"] >= 2]
    assert gim.verdict(art["pooled"], eras)[0] == art["verdict"]


def test_an_undecided_verdict_must_say_its_effect_is_inside_the_mde() -> None:
    art = _load(ART)
    if art["verdict"] == "UNDECIDED AT THIS N":
        p = art["pooled"]
        assert abs(p["mean"]) < p["mde"]
        assert "minimum detectable" in art["why"]


def test_the_verdict_uses_the_venue_series_and_not_a_retired_one() -> None:
    art = _load(ART)
    joined = " ".join(art["data_of_record"])
    assert "upcomers" in joined
    assert "frozen_corpus" not in joined and "synthetic" not in joined


def test_each_era_reports_the_utc_hour_the_protocol_predicts() -> None:
    """+60 era: the 22:15 stamp is 21:15 UTC. +120 era: it is 20:15 UTC. If the clock
    translation ever moves, the review document's claim about which window this arm misses has
    moved with it and must be rewritten."""
    art = _load(ART)
    want = {60: "21:15", 120: "20:15"}
    seen = set()
    for era in art["per_era"]:
        off = era["era_offset_min"]
        rows = [r for r in art["rows"] if r["era_offset_min"] == off]
        assert rows, "every recorded era has rows"
        assert rows[0]["entry_utc"].endswith(want[off]), (
            f"era +{off} should enter at {want[off]} UTC, artifact says {rows[0]['entry_utc']}")
        seen.add(off)
    assert seen == {60, 120}


def test_missing_stamps_are_reported_rather_than_silently_dropped() -> None:
    art = _load(ART)
    cov = art["coverage"]
    assert cov["stamped_days"] >= cov["qualifying_days"]
    # a run that quietly dropped most of the window is void by the protocol's own limits
    assert cov["qualifying_days"] / cov["stamped_days"] >= 0.5


def test_the_cost_model_is_the_repo_s_model() -> None:
    from midas_sweep import SPREAD_FLOOR

    art = _load(ART)
    assert f"${SPREAD_FLOOR:.2f}" in art["window"]["cost"]
    for r in art["rows"][:25]:
        assert r["cost_usd"] >= SPREAD_FLOOR          # at least one whole spread, round trip
        assert r["net_usd"] == pytest.approx(r["gross_usd"] - r["cost_usd"], abs=1e-9)


def test_the_verdict_document_exists_when_the_artifact_does() -> None:
    _load(ART)
    assert VERDICT.is_file(), "a measured artifact without its verdict document is a raw number"
