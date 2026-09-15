from __future__ import annotations

from scripts.pb_failure_classifier import FailureRule, derive_rule, summarize_filtered


def trade(strat: str, z: float, r: float) -> dict:
    return {"strat": strat, "z": z, "r": r}


def test_failure_rule_blocks_only_configured_entry_buckets() -> None:
    rule = FailureRule(pb_max_abs_z=0.5, mom_pb_max_abs_z=2.5)

    assert rule.blocks(trade("PB", 0.5, -1.0))
    assert not rule.blocks(trade("PB", 0.51, -1.0))
    assert rule.blocks(trade("MOM+PB", -2.5, -1.0))
    assert not rule.blocks(trade("MOM+PB", 2.51, -1.0))
    assert not rule.blocks(trade("MOM+MR", 0.1, -1.0))


def test_rule_is_selected_from_training_with_retained_sample_gate() -> None:
    training = [
        *[trade("PB", 0.2, -1.0) for _ in range(40)],
        *[trade("PB", 1.5, 0.8) for _ in range(50)],
        *[trade("MOM+PB", 1.0, -1.0) for _ in range(30)],
        *[trade("MOM+PB", 4.0, 0.8) for _ in range(50)],
    ]

    rule, audit = derive_rule(training, min_kept_family=45)

    assert rule.pb_max_abs_z is not None or rule.mom_pb_max_abs_z is not None
    assert audit["holdout_used"] is False
    assert audit["blocked_training"]["n"] >= 10
    assert audit["kept_training"]["n"] >= 45
    assert audit["blocked_training"]["mean_r"] < audit["kept_training"]["mean_r"]


def test_filtered_summary_reports_frozen_decisions_without_refitting() -> None:
    rule = FailureRule(pb_max_abs_z=0.5, mom_pb_max_abs_z=2.5)
    rows = [
        trade("PB", 0.2, -1.0),
        trade("PB", 1.2, 0.5),
        trade("MOM+PB", 1.0, -1.0),
        trade("MOM+MR", 0.1, 0.2),
    ]

    summary = summarize_filtered(rows, rule)

    assert summary["all"]["n"] == 4
    assert summary["blocked"]["n"] == 2
    assert summary["kept"]["n"] == 2
    assert summary["blocked"]["total_r"] == -2.0
    assert summary["kept"]["total_r"] == 0.7
