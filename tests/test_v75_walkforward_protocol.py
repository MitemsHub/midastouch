"""Offline tests for the two-sample (walk-forward) tester protocol.

These pin the harness's *bookkeeping* -- segment geometry, selection rule,
sample-gate flag, and the completeness of the explicit input sets -- without
running the Strategy Tester. The protocol's numbers come from the opt-in
tester tier; its contract is asserted here.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v75_walkforward as w  # noqa: E402


def _span(seg: tuple[str, str]) -> tuple[date, date]:
    return tuple(date.fromisoformat(s.replace(".", "-")) for s in seg)  # type: ignore[return-value]


def test_segments_are_non_overlapping_and_forward_in_time() -> None:
    for name, seg in w.PRESETS.items():
        train, test = _span(seg["train"]), _span(seg["test"])
        assert train[0] < train[1], f"{name}: train window not ordered"
        assert test[0] <= test[1], f"{name}: test window not ordered"
        assert test[0] > train[1], f"{name}: test must start after train ends"


def test_legacy_preset_is_the_documented_cache_months_1_3_vs_4_6() -> None:
    seg = w.PRESETS["legacy"]
    assert seg["train"] == ("2024.03.01", "2024.05.31")
    assert seg["test"] == ("2024.06.01", "2024.08.31")


def test_powered_preset_is_the_split_the_cache_actually_supports() -> None:
    """Both sides must be big enough to clear the 30-trade gate."""
    train, test = _span(w.PRESETS["powered"]["train"]), _span(w.PRESETS["powered"]["test"])
    assert (train[1] - train[0]).days >= 300          # ~18 months
    assert (test[1] - test[0]).days >= 250            # ~12 months
    # inside the real-tick cache (broker's usable floor 2024.01 -> 2026.09;
    # 2023 Q4 exists but only 384 bars at 60% history quality)
    assert train[0] >= date(2024, 1, 1)
    assert test[1] <= date(2026, 9, 10)
    assert train[0] == date(2024, 1, 1)   # powered train starts at the floor


def test_selection_uses_train_only_and_reports_transfer() -> None:
    cells = {
        "train": {n: {"expectancy_r": e, "pf": 1.0, "fills": 40}
                  for n, e in (("spec", 0.05), ("tp060", 0.01), ("tp090", 0.06))},
        "test": {n: {"expectancy_r": e, "pf": 1.0, "fills": 35}
                 for n, e in (("spec", 0.15), ("tp060", 0.16), ("tp090", 0.14))},
    }
    s = w.transfer_summary(cells)
    assert s["winner"] == "tp090"                    # train expectancy leader
    assert s["winner_train_rank"] == 1
    assert s["winner_test_rank"] == 3                # and it does NOT transfer
    assert s["spearman_expectancy"] == -1.0


def test_partial_run_summary_uses_only_configs_present_in_both_segments() -> None:
    """A mid-flight persist must not blow up while the two sides are uneven.

    Regression: persist() called transfer_summary() as soon as both segments
    had *any* cell, which raised KeyError on the segment-specific name sets.
    """
    cell = lambda e: {"expectancy_r": e, "pf": 1.0, "fills": 40}   # noqa: E731
    uneven = {"train": {"spec": cell(0.05), "tp060": cell(0.01)},
              "test": {"spec": cell(0.10)}}
    s = w.transfer_summary(uneven)
    assert s["winner"] == "spec"
    assert s["n_configs"] == 1                 # only the shared config ranks
    assert s["spearman_expectancy"] is None    # n < 2 shared configs
    with pytest.raises(ValueError):
        w.transfer_summary({"train": {"spec": cell(0.05)}, "test": {}})


def test_sample_gate_flags_underpowered_segments() -> None:
    thin = {"train": {"spec": {"expectancy_r": 0.1, "pf": 1.0, "fills": 5}},
            "test": {"spec": {"expectancy_r": 0.1, "pf": 1.0, "fills": 40}}}
    assert w.transfer_summary(thin)["sample_gate"] is False
    fat = {"train": {"spec": {"expectancy_r": 0.1, "pf": 1.0, "fills": 40}},
           "test": {"spec": {"expectancy_r": 0.1, "pf": 1.0, "fills": 40}}}
    assert w.transfer_summary(fat)["sample_gate"] is True


def test_spearman_handles_reversal_ties_and_degeneracy() -> None:
    assert w.spearman([1, 2, 3], [1, 2, 3]) == 1.0
    assert w.spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert w.spearman([1, 1, 1], [3, 2, 1]) is None   # flat input, undefined
    assert w.spearman([1], [1]) is None               # n < 2


def test_every_pass_sends_a_complete_explicit_input_set() -> None:
    """The input-cache gotcha: a partial set merges with the agent's cached one."""
    for name in w.CONFIGS:
        sent = w.segment_inputs(name)
        assert set(w.BASE_INPUTS) <= set(sent), f"{name}: base inputs incomplete"
        assert set(w.CONFIGS[name]) <= set(sent), f"{name}: overrides incomplete"
        assert sent == {**w.BASE_INPUTS, "InpTPRMultiple": "0.3", **w.CONFIGS[name]}


def test_spec_cell_is_the_spec_contract() -> None:
    assert w.CONFIGS["spec"] == {"InpExitManager": "0", "InpTPMode": "0",
                                 "InpTradeTimeoutHours": "3"}
    spec = w.segment_inputs("spec")
    assert spec["InpTradeTimeoutHours"] == "3"
    assert spec["InpRiskPercent"] == "1.0"
    assert spec["InpRRMultiplier"] == "2.0"          # SL 2xATR / TP 4xATR = 1:2
    assert spec["InpMaxPositionCount"] == "1"


def test_verification_keys_cover_the_gridded_dimension() -> None:
    assert set(w.VERIFY_KEYS) == {"InpExitManager", "InpTPMode",
                                  "InpTPRMultiple", "InpTradeTimeoutHours"}
