"""Data integrity and provenance for the research-only V75 policy selector."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


class SnapshotIntegrityError(ValueError):
    """Raised before selection when a supplied map is not the data being scored."""


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def deterministic_fingerprint(value: Any) -> str:
    """Hash JSON with stable key ordering and separators."""
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_snapshot(snapshot: Mapping[str, Any] | Path | str) -> dict:
    """Load and type-check a JSON snapshot or mapping."""
    if isinstance(snapshot, (Path, str)):
        loaded = json.loads(Path(snapshot).read_text(encoding="utf-8"))
    elif isinstance(snapshot, Mapping):
        loaded = dict(snapshot)
    else:
        raise TypeError("map snapshots must be mappings or JSON paths")
    if not isinstance(loaded, dict):
        raise SnapshotIntegrityError("map snapshot root must be an object")
    return loaded


def _snapshot_fingerprints(snapshot: dict) -> Mapping[str, Any]:
    fingerprints = snapshot.get("fingerprints", {})
    if not isinstance(fingerprints, Mapping):
        raise SnapshotIntegrityError("snapshot fingerprints must be an object")
    return fingerprints


def _metric_fingerprint(metrics: list[dict]) -> str:
    return deterministic_fingerprint({"metrics": metrics})


def _snapshot_multiplier(snapshot: dict) -> float:
    try:
        return float(snapshot["parameters"]["spread_multiplier"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotIntegrityError("snapshot is missing its spread multiplier") from exc


def _snapshot_tick_fingerprint(snapshot: dict) -> str:
    supplied = _snapshot_fingerprints(snapshot).get("ticks_sha256")
    if supplied:
        return str(supplied)
    tick_file = snapshot.get("tick_file")
    if tick_file:
        path = Path(str(tick_file))
        if path.exists():
            return _file_fingerprint(path)
    return deterministic_fingerprint({
        "tick_file": tick_file,
        "tick_coverage": snapshot.get("tick_coverage", {}),
    })


def snapshot_map_fingerprint(snapshot: dict) -> str:
    """Fingerprint map contents and parameters, excluding self-referential metadata."""
    payload = {key: value for key, value in snapshot.items()
               if key not in {"fingerprints", "provenance"}}
    return deterministic_fingerprint(payload)


def validate_map_snapshot(
    snapshot: Mapping[str, Any] | Path | str,
    expected_multiplier: float,
    expected_metrics: list[dict],
    start: datetime | None = None,
    end: datetime | None = None,
    expected_tick_file: Path | None = None,
) -> dict:
    """Validate a supplied snapshot against the exact data and cost in use."""
    loaded = load_snapshot(snapshot)
    if loaded.get("schema") not in (None, "mitemshub.v75.opportunity-map.v1"):
        raise SnapshotIntegrityError("snapshot schema is not an opportunity-map snapshot")
    actual_metrics = loaded.get("metrics")
    if not isinstance(actual_metrics, list):
        raise SnapshotIntegrityError("snapshot is missing metrics data")
    actual_multiplier = _snapshot_multiplier(loaded)
    if actual_multiplier != float(expected_multiplier):
        raise SnapshotIntegrityError(
            f"snapshot spread multiplier {actual_multiplier:g} does not match "
            f"the multiplier actually used {float(expected_multiplier):g}"
        )
    if loaded.get("metrics_count", len(actual_metrics)) != len(actual_metrics):
        raise SnapshotIntegrityError("snapshot metrics_count does not match metrics data")
    expected_hash = _metric_fingerprint(expected_metrics)
    actual_hash = _metric_fingerprint(actual_metrics)
    if actual_hash != expected_hash:
        raise SnapshotIntegrityError("snapshot metrics do not match the data actually used")
    fingerprints = _snapshot_fingerprints(loaded)
    recorded_hash = fingerprints.get("metrics_sha256")
    if recorded_hash is not None and str(recorded_hash) != actual_hash:
        raise SnapshotIntegrityError("snapshot metrics fingerprint does not match metrics data")
    recorded_map_hash = fingerprints.get("map_sha256")
    if recorded_map_hash is not None and str(recorded_map_hash) != snapshot_map_fingerprint(loaded):
        raise SnapshotIntegrityError("snapshot map fingerprint does not match map data")
    if expected_tick_file is not None and expected_tick_file.exists():
        expected_ticks = _file_fingerprint(expected_tick_file)
        actual_ticks = _snapshot_tick_fingerprint(loaded)
        if actual_ticks != expected_ticks:
            raise SnapshotIntegrityError("snapshot ticks do not match the data actually used")
        if loaded.get("tick_file") is None and "ticks_sha256" not in fingerprints:
            raise SnapshotIntegrityError("snapshot has no tick lineage for the data actually used")
    windows = loaded.get("windows", {})
    if not isinstance(windows, Mapping):
        raise SnapshotIntegrityError("snapshot windows must be an object")
    if start is not None and "start" in windows and datetime.fromisoformat(
            str(windows["start"]).replace("Z", "+00:00")) != start:
        raise SnapshotIntegrityError("snapshot window does not match the data actually used")
    if end is not None and "end" in windows and datetime.fromisoformat(
            str(windows["end"]).replace("Z", "+00:00")) != end:
        raise SnapshotIntegrityError("snapshot window does not match the data actually used")
    return loaded


def _synthetic_snapshot(metrics: list[dict], multiplier: float) -> dict:
    return {
        "schema": "mitemshub.v75.opportunity-map.v1",
        "windows": {},
        "parameters": {"spread_multiplier": float(multiplier)},
        "metrics_count": len(metrics),
        "metrics": metrics,
    }


@dataclass(frozen=True)
class PreparedSnapshots:
    """The immutable data views consumed by the fold engine."""

    metrics: list[dict]
    stress_metrics: dict[float, list[dict]]
    base_snapshot: dict
    stress_snapshots: dict[float, dict]
    base_source: str


class CachedOpportunityMaps:
    """Own one lazily-built map per spread multiplier."""

    def __init__(self, builder: Callable[[float], dict]) -> None:
        self._builder = builder
        self._reports: dict[float, dict] = {}

    def get(self, multiplier: float) -> dict:
        key = float(multiplier)
        if key not in self._reports:
            self._reports[key] = self._builder(key)
        return self._reports[key]


def resolve_cli_snapshots(
    data_dir: Path,
    tick_file: Path,
    start: datetime,
    end: datetime,
    map_snapshot: Mapping[str, Any] | Path | str | None,
    stress_specs: list[tuple[float, Mapping[str, Any] | Path | str]],
    builder: Callable[[Path, Path, datetime, datetime, float], dict],
) -> tuple[dict, dict[float, dict]]:
    """Resolve CLI inputs while building each missing map at most once."""
    cache = CachedOpportunityMaps(
        lambda multiplier: builder(data_dir, tick_file, start, end, multiplier)
    )
    if map_snapshot is None:
        base = cache.get(1.0)
    else:
        base = load_snapshot(map_snapshot)
        validate_map_snapshot(base, 1.0, cache.get(1.0)["metrics"], start, end, tick_file)

    stress: dict[float, dict] = {}
    for multiplier, snapshot_input in stress_specs:
        if multiplier in stress:
            raise SnapshotIntegrityError(f"duplicate stress multiplier {multiplier:g}")
        snapshot = load_snapshot(snapshot_input)
        validate_map_snapshot(
            snapshot, multiplier, cache.get(multiplier)["metrics"], start, end, tick_file,
        )
        stress[multiplier] = snapshot
    if not stress_specs:
        for multiplier in (1.5, 2.0):
            stress[multiplier] = cache.get(multiplier)
    return base, stress


def _lineage_entry(
    snapshot: dict | None,
    metrics: list[dict],
    multiplier: float,
    source: str,
    tick_file: Path | None = None,
    parent_map_sha256: str | None = None,
) -> dict:
    snapshot = snapshot or _synthetic_snapshot(metrics, multiplier)
    return {
        "source": source,
        "spread_multiplier": _snapshot_multiplier(snapshot),
        "metrics_sha256": _metric_fingerprint(snapshot["metrics"]),
        "map_sha256": snapshot_map_fingerprint(snapshot),
        "ticks_sha256": _snapshot_tick_fingerprint(snapshot),
        "tick_file": snapshot.get("tick_file"),
        "windows": snapshot.get("windows"),
        "parent_map_sha256": parent_map_sha256,
    }


def _code_fingerprint() -> str:
    names = (
        "v75_geometry_policy_snapshot.py",
        "v75_geometry_policy_engine.py",
        "v75_geometry_policy_selector.py",
        "v75_geometry_policy.py",
        "v75_opportunity_map.py",
        "v75_router_core.py",
    )
    return deterministic_fingerprint([
        {"name": name, "sha256": _file_fingerprint(HERE / name)} for name in names
    ])


def build_provenance(
    metrics: list[dict],
    stress_metrics: dict[float, list[dict]],
    base: dict,
    stress_snapshots: dict[float, dict],
    start: datetime,
    end: datetime,
    train_days: int,
    validation_days: int,
    test_days: int,
    portfolio_size: int,
    min_samples: int,
    min_validation_trades: int,
    health_loss_streak: int,
    tick_file: Path | None,
    base_source: str,
) -> dict:
    selector_parameters = {
        "train_days": train_days,
        "validation_days": validation_days,
        "test_days": test_days,
        "portfolio_size": portfolio_size,
        "min_samples": min_samples,
        "min_validation_trades": min_validation_trades,
        "health_loss_streak": health_loss_streak,
    }
    fold_windows: list[dict[str, list[str]]] = []
    cursor = start
    while cursor + timedelta(days=train_days + validation_days + test_days) <= end:
        train_end = cursor + timedelta(days=train_days)
        validation_end = train_end + timedelta(days=validation_days)
        test_end = validation_end + timedelta(days=test_days)
        fold_windows.append({
            "train": [cursor.isoformat(), train_end.isoformat()],
            "validation": [train_end.isoformat(), validation_end.isoformat()],
            "test": [validation_end.isoformat(), test_end.isoformat()],
        })
        cursor += timedelta(days=test_days)
    fold_parameters = {"windows": fold_windows, "parameters": selector_parameters}
    stress_parameters = {
        "multipliers": sorted(stress_metrics),
        "metrics_sha256": {
            str(multiplier): _metric_fingerprint(rows)
            for multiplier, rows in sorted(stress_metrics.items())
        },
        "snapshots": {
            str(multiplier): snapshot.get("parameters", {})
            for multiplier, snapshot in sorted(stress_snapshots.items())
        },
    }
    base_lineage = _lineage_entry(base, metrics, 1.0, base_source, tick_file)
    stress_lineage = {
        str(multiplier): _lineage_entry(
            stress_snapshots.get(multiplier), rows, multiplier,
            "supplied-snapshot" if multiplier in stress_snapshots else "in-memory-input",
            tick_file, base_lineage["map_sha256"],
        )
        for multiplier, rows in sorted(stress_metrics.items())
    }
    config_parameters = {
        "selector_schema": "mitemshub.v75.geometry-policy-selector.v2",
        "policies": ["original", "calibrated"],
        "parameters": selector_parameters,
        "map_parameters": base.get("parameters", {}),
    }
    return {
        "fingerprints": {
            "ticks_sha256": base_lineage["ticks_sha256"],
            "stress_ticks_sha256": {
                key: value["ticks_sha256"] for key, value in stress_lineage.items()
            },
            "map_sha256": base_lineage["map_sha256"],
            "stress_map_sha256": {
                key: value["map_sha256"] for key, value in stress_lineage.items()
            },
            "code_sha256": _code_fingerprint(),
            "config_sha256": deterministic_fingerprint(config_parameters),
            "fold_parameters_sha256": deterministic_fingerprint(fold_parameters),
            "stress_parameters_sha256": deterministic_fingerprint(stress_parameters),
        },
        "parameters": {
            "config": config_parameters,
            "fold": fold_parameters,
            "stress": stress_parameters,
        },
        "map_lineage": {"base": base_lineage, "stress": stress_lineage},
        "snapshot_integrity": {
            "base_validated": True,
            "stress_validated": sorted(stress_snapshots),
            "stress_derived": sorted(set(stress_metrics) - set(stress_snapshots)),
        },
    }


def prepare_snapshot_inputs(
    metrics: list[dict],
    start: datetime,
    end: datetime,
    stress_metrics: dict[float, list[dict]] | None,
    map_snapshot: Mapping[str, Any] | Path | str | None,
    stress_snapshots: Mapping[float | str, Mapping[str, Any] | Path | str] | None,
    tick_file: Path | None,
) -> PreparedSnapshots:
    """Normalize legacy in-memory inputs and validate supplied snapshots."""
    base = load_snapshot(map_snapshot) if map_snapshot is not None else _synthetic_snapshot(metrics, 1.0)
    if map_snapshot is not None:
        validate_map_snapshot(base, 1.0, metrics, start, end, tick_file)

    normalized_stress: dict[float, dict] = {}
    for multiplier, snapshot in (stress_snapshots or {}).items():
        key = float(multiplier)
        if key in normalized_stress:
            raise SnapshotIntegrityError(f"duplicate stress multiplier {key:g}")
        normalized_stress[key] = load_snapshot(snapshot)
    supplied_metrics = {float(key): value for key, value in (stress_metrics or {}).items()}
    if normalized_stress:
        missing = sorted(set(supplied_metrics) - set(normalized_stress))
        if missing:
            labels = ", ".join(f"{item:g}" for item in missing)
            raise SnapshotIntegrityError(f"missing stress snapshot(s) for multiplier(s): {labels}")
        for multiplier, snapshot in normalized_stress.items():
            expected = supplied_metrics.get(multiplier, snapshot["metrics"])
            validate_map_snapshot(snapshot, multiplier, expected, start, end, tick_file)
            supplied_metrics[multiplier] = snapshot["metrics"]
    return PreparedSnapshots(
        metrics=metrics,
        stress_metrics={multiplier: supplied_metrics[multiplier]
                        for multiplier in sorted(supplied_metrics)},
        base_snapshot=base,
        stress_snapshots=normalized_stress,
        base_source="supplied-snapshot" if map_snapshot is not None else "in-memory-input",
    )


__all__ = [
    "CachedOpportunityMaps",
    "PreparedSnapshots",
    "SnapshotIntegrityError",
    "build_provenance",
    "deterministic_fingerprint",
    "load_snapshot",
    "prepare_snapshot_inputs",
    "resolve_cli_snapshots",
    "snapshot_map_fingerprint",
    "validate_map_snapshot",
]
