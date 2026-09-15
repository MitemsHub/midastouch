#!/usr/bin/env python3
"""Refresh broker data and run a non-destructive Volatility 75 shadow cycle.

The cycle writes to a dated artifact directory and never edits production EA
files, presets, or existing research archives. It pulls fresh bid/ask ticks and
closed M15/H1 bars, validates quote continuity, then runs the research-only
shadow replay. It is suitable for Windows Task Scheduler or a manual weekly
run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "artifacts" / "data"


def run_command(command: list[str]) -> None:
    print("$", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--end", type=str, default=None,
                        help="UTC end date YYYY-MM-DD, defaults to today")
    parser.add_argument("--train-days", type=int, default=10)
    parser.add_argument("--validation-days", type=int, default=5)
    parser.add_argument("--test-days", type=int, default=5)
    parser.add_argument("--min-samples", type=int, default=12)
    parser.add_argument("--portfolio-size", type=int, default=8)
    parser.add_argument("--recent-weight", type=float, default=0.65)
    parser.add_argument("--review-min-trades", type=int, default=10)
    parser.add_argument("--review-max-drawdown-r", type=float, default=5.0)
    args = parser.parse_args()

    end_date = datetime.fromisoformat(args.end).date() if args.end else datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=args.days)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cycle_dir = ROOT / "artifacts" / "v75_shadow_cycles" / tag
    cycle_dir.mkdir(parents=True, exist_ok=False)
    tick_path = cycle_dir / "v75_ticks.csv"
    m15_path = cycle_dir / "m15.csv"
    h1_path = cycle_dir / "h1.csv"
    validation_path = cycle_dir / "tick_validation.json"
    shadow_path = cycle_dir / "shadow_replay.json"

    run_command([
        sys.executable, str(SCRIPTS / "pull_v75_ticks.py"),
        "--from", start_date.isoformat(), "--to", end_date.isoformat(),
        "--out", str(tick_path),
    ])
    run_command([
        sys.executable, str(SCRIPTS / "fetch_market_data.py"),
        "--symbol", "Volatility 75 Index", "--bars", "M15", "--count", "40000",
        "--out", str(m15_path),
    ])
    run_command([
        sys.executable, str(SCRIPTS / "fetch_market_data.py"),
        "--symbol", "Volatility 75 Index", "--bars", "H1", "--count", "10000",
        "--out", str(h1_path),
    ])
    run_command([
        sys.executable, str(SCRIPTS / "validate_v75_tick_corpus.py"),
        "--ticks", str(tick_path), "--output", str(validation_path),
    ])

    window_end = datetime.combine(end_date, datetime.min.time(), tzinfo=timezone.utc)
    window_start = window_end - timedelta(days=args.days)
    run_command([
        sys.executable, str(SCRIPTS / "v75_shadow_replay.py"),
        "--data-dir", str(cycle_dir), "--ticks", str(tick_path),
        "--output", str(shadow_path),
        "--start", window_start.isoformat(), "--end", window_end.isoformat(),
        "--train-days", str(args.train_days),
        "--validation-days", str(args.validation_days),
        "--test-days", str(args.test_days),
        "--portfolio-size", str(args.portfolio_size),
        "--min-samples", str(args.min_samples),
        "--recent-weight", str(args.recent_weight),
    ])

    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
    summary = {
        "schema": "mitemshub.v75.shadow-cycle.v1",
        "cycle_dir": str(cycle_dir),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "order_submission": False,
        "tick_verdict": validation["verdict"],
        "tick_corpus": validation["corpus"],
        "shadow_summary": {
            key: shadow["summary"][key]
            for key in ("decisions", "no_trade", "trades", "wins", "total_r", "trade_records")
        },
        "parameters": {
            "days": args.days, "train_days": args.train_days,
            "validation_days": args.validation_days, "test_days": args.test_days,
            "min_samples": args.min_samples, "portfolio_size": args.portfolio_size,
            "recent_weight": args.recent_weight,
        },
    }
    summary_path = cycle_dir / "review_summary.json"
    summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    from review_v75_shadow_cycle import review
    gate = review(summary, args.review_min_trades, args.review_max_drawdown_r)
    gate_path = cycle_dir / "review_gate.json"
    gate_path.write_text(json.dumps(gate, indent=1), encoding="utf-8")
    print(json.dumps(summary["shadow_summary"], indent=1))
    print("review:", summary_path)
    print("gate:", gate_path, gate["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
