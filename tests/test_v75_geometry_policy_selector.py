from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.v75_geometry_policy_selector import (
    POLICY_CALIBRATED,
    POLICY_ORIGINAL,
    SnapshotIntegrityError,
    choose_policy,
    deterministic_fingerprint,
    fit_calibrated,
    run,
    validate_map_snapshot,
)


def _row(timestamp: str, geometry: str, positive: bool, r: float) -> dict:
    geometries = {
        "sl0.50_tp1.5": False,
        "sl0.75_tp1.5": False,
        "sl0.75_tp2": False,
        "sl0.75_tp2.5": False,
        "sl1_tp2": False,
        "sl1_tp2.5": False,
    }
    geometries[geometry] = positive
    return {
        "timestamp": timestamp,
        "context": "REVERSAL",
        "regime": "RANGE",
        "m32_bin": "0.15..0.75",
        "efficiency_bin": "0.35..0.50",
        "distance_bin": "0.45..0.75",
        "direction": -1,
        "horizon": 8,
        "target_before_stop": geometries,
        "target_reachable": geometries.copy(),
        "mfe_r": 2.0 if positive else 0.1,
        "mae_r": -0.2 if positive else -1.0,
        "horizon_r": r,
        "spread": 10.0,
        "atr": 100.0,
    }


def _snapshot(rows: list[dict], multiplier: float = 1.0) -> dict:
    return {
        "schema": "mitemshub.v75.opportunity-map.v1",
        "windows": {
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-01-05T00:00:00+00:00",
        },
        "parameters": {"spread_multiplier": multiplier},
        "fingerprints": {"ticks_sha256": "tick-fixture"},
        "metrics": rows,
        "metrics_count": len(rows),
    }


def test_snapshot_fingerprint_is_deterministic_for_mapping_order() -> None:
    assert deterministic_fingerprint({"b": 2, "a": [1, 2]}) == deterministic_fingerprint(
        {"a": [1, 2], "b": 2}
    )


def test_snapshot_mismatch_is_rejected() -> None:
    rows = [_row("2026-01-01T00:00:00+00:00", "sl0.75_tp1.5", True, 1.0)]
    snapshot = _snapshot(rows, multiplier=1.5)

    with pytest.raises(SnapshotIntegrityError, match="spread multiplier"):
        validate_map_snapshot(snapshot, expected_multiplier=1.0, expected_metrics=rows)

    changed = [dict(rows[0], horizon_r=-99.0)]
    with pytest.raises(SnapshotIntegrityError, match="metrics"):
        validate_map_snapshot(snapshot, expected_multiplier=1.5, expected_metrics=changed)


def test_run_records_snapshot_provenance_and_lineage() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 5, tzinfo=timezone.utc)
    rows = [_row(f"2026-01-{day:02d}T00:00:00+00:00", "sl0.75_tp1.5", True, 1.0)
            for day in range(1, 5)]
    base = _snapshot(rows)
    stress = _snapshot(rows, multiplier=1.5)

    result = run(rows, start, end, train_days=1, validation_days=1, test_days=1,
                 portfolio_size=1, min_samples=2, min_validation_trades=1,
                 map_snapshot=base, stress_snapshots={1.5: stress},
                 stress_metrics={1.5: rows})

    fingerprints = result["provenance"]["fingerprints"]
    assert fingerprints["ticks_sha256"] == "tick-fixture"
    assert fingerprints["map_sha256"]
    assert fingerprints["code_sha256"]
    assert fingerprints["config_sha256"]
    assert fingerprints["fold_parameters_sha256"]
    assert fingerprints["stress_parameters_sha256"]
    assert result["provenance"]["map_lineage"]["base"]["spread_multiplier"] == 1.0
    assert result["provenance"]["map_lineage"]["stress"]["1.5"]["spread_multiplier"] == 1.5


def test_run_rejects_snapshot_before_fitting() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 4, tzinfo=timezone.utc)
    rows = [_row(f"2026-01-{day:02d}T00:00:00+00:00", "sl0.75_tp1.5", True, 1.0)
            for day in range(1, 4)]
    bad_snapshot = _snapshot(rows, multiplier=2.0)

    with pytest.raises(SnapshotIntegrityError, match="spread multiplier"):
        run(rows, start, end, train_days=1, validation_days=1, test_days=1,
            portfolio_size=1, min_samples=1, min_validation_trades=1,
            map_snapshot=bad_snapshot)


def test_policy_selection_uses_validation_only_and_keeps_original_on_tie() -> None:
    validation = {
        POLICY_ORIGINAL: {"n": 4, "mean_r": 0.20, "max_drawdown_r": 1.0},
        POLICY_CALIBRATED: {"n": 4, "mean_r": 0.20, "max_drawdown_r": 1.0},
    }

    winner, details = choose_policy(validation, min_validation_trades=3)

    assert winner == POLICY_ORIGINAL
    assert details["reason"] == "selected-from-prior-validation-only"
    assert details["scores"][POLICY_ORIGINAL] == details["scores"][POLICY_CALIBRATED]


def test_policy_selection_rejects_candidate_that_fails_prior_spread_stress() -> None:
    validation = {
        POLICY_ORIGINAL: {"n": 4, "mean_r": 0.20, "max_drawdown_r": 1.0},
        POLICY_CALIBRATED: {"n": 4, "mean_r": 0.40, "max_drawdown_r": 1.0},
    }
    validation_stress = {
        POLICY_ORIGINAL: [
            {"n": 4, "mean_r": 0.10, "max_drawdown_r": 1.0},
            {"n": 4, "mean_r": 0.05, "max_drawdown_r": 1.0},
        ],
        POLICY_CALIBRATED: [
            {"n": 4, "mean_r": 0.10, "max_drawdown_r": 1.0},
            {"n": 4, "mean_r": -0.05, "max_drawdown_r": 2.0},
        ],
    }

    winner, details = choose_policy(
        validation, min_validation_trades=3, validation_stress=validation_stress,
    )

    assert winner == POLICY_ORIGINAL
    assert details["scores"][POLICY_CALIBRATED][0] == float("-inf")

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [
        _row(f"2026-01-01T{hour:02d}:00:00+00:00", "sl0.75_tp2.5", True, 3.0)
        for hour in range(0, 24, 2)
    ]

    fitted = fit_calibrated(rows, start, end, min_samples=2, portfolio_size=1)

    assert fitted
    assert fitted[0]["pocket"]["geometry"] == "sl0.75_tp2.5"
    assert fitted[0]["fit"]["geometry_source"] == "prior-only-wilson-calibration"
    assert fitted[0]["fit"]["target_lower_bound"] > fitted[0]["fit"]["break_even_rate"]


def test_run_keeps_test_outcomes_out_of_policy_fit() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 5, tzinfo=timezone.utc)
    rows = []
    for day in range(4):
        for hour in range(0, 24, 2):
            positive = day < 3
            rows.append(_row(
                f"2026-01-{day + 1:02d}T{hour:02d}:00:00+00:00",
                "sl0.75_tp1.5", positive, 1.0 if positive else -1.0,
            ))

    result = run(rows, start, end, train_days=1, validation_days=1,
                 test_days=1, portfolio_size=1, min_samples=2,
                 min_validation_trades=1)

    assert result["folds"]
    for fold in result["folds"]:
        train_end = datetime.fromisoformat(fold["train_window"][1])
        validation_start = datetime.fromisoformat(fold["validation_window"][0])
        test_start = datetime.fromisoformat(fold["test_window"][0])
        assert train_end == validation_start
        assert validation_start == test_start - timedelta(days=1)
        for policy in (POLICY_ORIGINAL, POLICY_CALIBRATED):
            assert "discovered" in fold["policy_fit"][policy]
            assert "gated" in fold["policy_fit"][policy]
            for item in fold["policy_fit"][policy]["portfolio"]:
                assert item["pocket"]["geometry"]
        assert fold["selection"]["winner"] in {POLICY_ORIGINAL, POLICY_CALIBRATED, None}
        assert set(fold["test_by_policy"]) == {POLICY_ORIGINAL, POLICY_CALIBRATED}
        if fold["selection"]["winner"] is not None:
            winner = fold["selection"]["winner"]
            assert fold["test"] == fold["test_by_policy"][winner]
