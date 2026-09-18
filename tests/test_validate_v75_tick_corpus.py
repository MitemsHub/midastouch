from __future__ import annotations

import csv
from pathlib import Path

from scripts.validate_v75_tick_corpus import validate


def _write(path: Path, rows: list[tuple[int, float, float]], schema: str = "epoch_ms") -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([schema, "bid", "ask"])
        for timestamp, bid, ask in rows:
            writer.writerow([timestamp, bid, ask])


def test_large_gap_creates_two_segments(tmp_path: Path) -> None:
    path = tmp_path / "ticks.csv"
    start = 1_700_000_000_000
    rows = [(start + i * 1_000, 100.0 + i, 100.5 + i) for i in range(3)]
    rows += [(start + 3 * 3_600_000 + i * 1_000, 200.0 + i, 200.5 + i) for i in range(3)]
    _write(path, rows)

    report = validate([path], max_gap_sec=120, min_segment_hours=0.0)

    assert report["corpus"]["gaps_over_limit"] == 1
    assert len(report["segments"]) == 2
    assert all(segment["usable"] for segment in report["segments"])
    assert report["verdict"] == "PASS"


def test_short_segments_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ticks.csv"
    _write(path, [(1_700_000_000_000 + i * 1_000, 100.0, 100.5) for i in range(3)])

    report = validate([path], max_gap_sec=120, min_segment_hours=1.0)

    assert report["usable_segments"] == []
    assert report["verdict"] == "REJECT"


def test_invalid_quotes_are_counted_and_excluded(tmp_path: Path) -> None:
    path = tmp_path / "ticks.csv"
    _write(path, [
        (1_700_000_000_000, 100.0, 100.5),
        (1_700_000_001_000, 101.0, 100.0),
        (1_700_000_002_000, -1.0, 100.5),
        (1_700_000_003_000, 102.0, 102.5),
    ])

    report = validate([path], max_gap_sec=120, min_segment_hours=0.0)

    assert report["files"][0]["invalid_quotes"] == 2
    assert report["corpus"]["ticks"] == 2


def test_duplicate_timestamps_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "ticks.csv"
    _write(path, [
        (1_700_000_000_000, 100.0, 100.5),
        (1_700_000_000_000, 100.0, 100.5),
        (1_700_000_001_000, 101.0, 101.5),
    ])

    report = validate([path], max_gap_sec=120, min_segment_hours=0.0)

    assert report["corpus"]["duplicate_timestamps"] == 1
    assert report["verdict"] == "REJECT"


def test_epoch_seconds_schema_is_normalized(tmp_path: Path) -> None:
    path = tmp_path / "ticks.csv"
    _write(path, [
        (1_700_000_000, 100.0, 100.5),
        (1_700_000_001, 101.0, 101.5),
    ], schema="ts")

    report = validate([path], max_gap_sec=120, min_segment_hours=0.0)

    assert report["corpus"]["first"].startswith("2023-11-14T22:13:20")
