#!/usr/bin/env python3
"""Validate Volatility 75 broker tick archives before blind replay.

The validator is intentionally independent of any strategy.  It treats a
quote gap over ``--max-gap-sec`` as a hard boundary: no backtest may carry a
position across that boundary.  Files are sorted by timestamp for analysis,
but overlaps and conflicting duplicate timestamps are reported rather than
hidden.

Supported CSV schemas:
* ``epoch_ms,bid,ask``
* ``ts,bid,ask,mid`` where ``ts`` is epoch seconds or milliseconds.

Example:
  python scripts/validate_v75_tick_corpus.py \
      --ticks artifacts/data/volatility_75_index_ticks_*.csv \
      --output artifacts/data/v75_tick_corpus_validation.json \
      --min-segment-hours 24
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DEFAULT_PATTERN = "artifacts/data/volatility_75_index_ticks_*.csv"
DEFAULT_OUTPUT = Path("artifacts/data/v75_tick_corpus_validation.json")
DEFAULT_MAX_GAP_SEC = 120.0
DEFAULT_MIN_SEGMENT_HOURS = 24.0


@dataclass(frozen=True)
class FileStats:
    path: str
    rows: int
    first: str | None
    last: str | None
    invalid_quotes: int
    duplicate_rows: int
    out_of_order_rows: int
    median_spread: float | None
    p99_spread: float | None
    gaps_over_limit: int
    max_gap_sec: float


@dataclass(frozen=True)
class Segment:
    first: str
    last: str
    ticks: int
    duration_hours: float
    max_gap_sec: float
    median_spread: float
    p99_spread: float
    usable: bool


def _timestamp(value: str, key: str) -> int:
    number = float(value)
    if key == "ts" and number < 1e11:
        number *= 1000.0
    return int(number)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).isoformat()


def _read_file(path: Path) -> tuple[FileStats, list[tuple[int, float, float]]]:
    values: list[tuple[int, float, float]] = []
    invalid = duplicates = out_of_order = 0
    previous_timestamp: int | None = None
    seen: set[tuple[int, float, float]] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        time_key = "epoch_ms" if "epoch_ms" in fields else "ts" if "ts" in fields else ""
        if not time_key or not {"bid", "ask"}.issubset(fields):
            raise ValueError(f"{path}: expected epoch_ms/ts,bid,ask columns")
        for row in reader:
            try:
                timestamp = _timestamp(row[time_key], time_key)
                bid, ask = float(row["bid"]), float(row["ask"])
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            if previous_timestamp is not None and timestamp < previous_timestamp:
                out_of_order += 1
            previous_timestamp = timestamp
            if timestamp <= 0 or not (math.isfinite(bid) and math.isfinite(ask)) or bid <= 0 or ask <= bid:
                invalid += 1
                continue
            item = (timestamp, bid, ask)
            if item in seen:
                duplicates += 1
            seen.add(item)
            values.append(item)
    values.sort(key=lambda item: item[0])
    spreads = np.asarray([ask - bid for _, bid, ask in values], dtype=float)
    gaps = np.diff(np.asarray([timestamp for timestamp, _, _ in values], dtype=np.int64)) / 1000.0
    stats = FileStats(
        path=str(path), rows=len(values),
        first=_iso(values[0][0]) if values else None,
        last=_iso(values[-1][0]) if values else None,
        invalid_quotes=int(invalid), duplicate_rows=int(duplicates),
        out_of_order_rows=int(out_of_order),
        median_spread=float(np.median(spreads)) if len(spreads) else None,
        p99_spread=float(np.quantile(spreads, 0.99)) if len(spreads) else None,
        gaps_over_limit=0, max_gap_sec=float(np.max(gaps)) if len(gaps) else 0.0,
    )
    return stats, values


def _segments(values: list[tuple[int, float, float]], max_gap_sec: float,
              min_segment_hours: float) -> list[Segment]:
    if not values:
        return []
    segments: list[list[tuple[int, float, float]]] = [[]]
    for item in values:
        if segments[-1] and (item[0] - segments[-1][-1][0]) / 1000.0 > max_gap_sec:
            segments.append([])
        segments[-1].append(item)
    result: list[Segment] = []
    for segment in segments:
        timestamps = np.asarray([item[0] for item in segment], dtype=np.int64)
        spreads = np.asarray([item[2] - item[1] for item in segment], dtype=float)
        gaps = np.diff(timestamps) / 1000.0
        duration = (timestamps[-1] - timestamps[0]) / 3_600_000.0
        result.append(Segment(
            first=_iso(int(timestamps[0])), last=_iso(int(timestamps[-1])),
            ticks=int(len(segment)), duration_hours=float(duration),
            max_gap_sec=float(np.max(gaps)) if len(gaps) else 0.0,
            median_spread=float(np.median(spreads)),
            p99_spread=float(np.quantile(spreads, 0.99)),
            usable=bool(duration >= min_segment_hours),
        ))
    return result


def validate(paths: list[Path], max_gap_sec: float = DEFAULT_MAX_GAP_SEC,
             min_segment_hours: float = DEFAULT_MIN_SEGMENT_HOURS) -> dict:
    if not paths:
        raise ValueError("no tick files supplied")
    file_stats: list[FileStats] = []
    all_values: list[tuple[int, float, float]] = []
    for path in paths:
        stats, values = _read_file(path)
        file_stats.append(stats)
        all_values.extend(values)
    all_values.sort(key=lambda item: item[0])
    if not all_values:
        raise ValueError("no valid quotes found")

    timestamps = np.asarray([item[0] for item in all_values], dtype=np.int64)
    gaps = np.diff(timestamps) / 1000.0
    duplicate_timestamps = int(np.sum(gaps == 0))
    exact_duplicate_rows = 0
    conflicting_duplicate_timestamps = 0
    for previous, current in zip(all_values, all_values[1:]):
        if previous[0] != current[0]:
            continue
        if previous[1:] == current[1:]:
            exact_duplicate_rows += 1
        else:
            # Multiple quote updates can legitimately share the same broker
            # millisecond.  Preserve and report them; they are not corruption.
            conflicting_duplicate_timestamps += 1
    large_gap_indices = np.where(gaps > max_gap_sec)[0]
    spreads = np.asarray([item[2] - item[1] for item in all_values], dtype=float)
    segments = _segments(all_values, max_gap_sec, min_segment_hours)
    usable = [segment for segment in segments if segment.usable]
    span_hours = (timestamps[-1] - timestamps[0]) / 3_600_000.0
    gap_time_hours = float(np.sum(gaps[large_gap_indices]) / 3600.0) if len(large_gap_indices) else 0.0
    result = {
        "schema": "mitemshub.v75.tick-corpus-validation.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "parameters": {"max_gap_sec": max_gap_sec, "min_segment_hours": min_segment_hours},
        "corpus": {
            "files": [str(path) for path in paths], "ticks": len(all_values),
            "first": _iso(int(timestamps[0])), "last": _iso(int(timestamps[-1])),
            "span_hours": round(float(span_hours), 6),
            "median_spread": round(float(np.median(spreads)), 6),
            "p99_spread": round(float(np.quantile(spreads, 0.99)), 6),
            "duplicate_timestamps": duplicate_timestamps,
            "exact_duplicate_rows": exact_duplicate_rows,
            "same_timestamp_quote_updates": conflicting_duplicate_timestamps,
            "conflicting_duplicate_timestamps": conflicting_duplicate_timestamps,
            "gaps_over_limit": len(large_gap_indices),
            "gap_time_hours_over_limit": round(gap_time_hours, 6),
            "max_gap_sec": round(float(np.max(gaps)) if len(gaps) else 0.0, 6),
        },
        "files": [asdict(stats) for stats in file_stats],
        "segments": [asdict(segment) for segment in segments],
        "usable_segments": [asdict(segment) for segment in usable],
        "verdict": "PASS" if usable and exact_duplicate_rows == 0 else "REJECT",
        "replay_rule": "Only score trades fully contained within one usable segment; never carry a position across a reported gap.",
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", nargs="+", default=None, help="tick CSV files or glob patterns")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-gap-sec", type=float, default=DEFAULT_MAX_GAP_SEC)
    parser.add_argument("--min-segment-hours", type=float, default=DEFAULT_MIN_SEGMENT_HOURS)
    args = parser.parse_args(argv)
    raw_paths = args.ticks or [DEFAULT_PATTERN]
    paths: list[Path] = []
    for raw in raw_paths:
        matches = [Path(item) for item in glob.glob(raw)]
        paths.extend(matches or [Path(raw)])
    paths = sorted(set(paths))
    missing = [path for path in paths if not path.exists()]
    if missing:
        parser.error("missing tick file(s): " + ", ".join(map(str, missing)))
    result = validate(paths, args.max_gap_sec, args.min_segment_hours)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"files={len(paths)} ticks={result['corpus']['ticks']:,} span={result['corpus']['span_hours']:.2f}h")
    print(f"gaps>{args.max_gap_sec:g}s={result['corpus']['gaps_over_limit']} "
          f"duplicates={result['corpus']['duplicate_timestamps']} "
          f"conflicts={result['corpus']['conflicting_duplicate_timestamps']}")
    for index, segment in enumerate(result["segments"], start=1):
        print(f"segment={index} {segment['first']} -> {segment['last']} "
              f"hours={segment['duration_hours']:.2f} ticks={segment['ticks']:,} "
              f"usable={segment['usable']}")
    print("VERDICT:", result["verdict"])
    print("wrote", args.output)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
