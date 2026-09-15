#!/usr/bin/env python3
"""Classify a completed Volatility 75 shadow cycle without enabling trading."""
from __future__ import annotations

import argparse
import json
from itertools import accumulate
from pathlib import Path


def review(summary: dict, min_trades: int = 10, max_drawdown_r: float = 5.0) -> dict:
    """Return a conservative operational classification for one cycle."""
    reasons: list[str] = []
    shadow = summary["shadow_summary"]
    if summary.get("order_submission") is not False:
        reasons.append("order-submission-contract-missing")
    if summary.get("tick_verdict") != "PASS":
        reasons.append("tick-corpus-failed-validation")
    trades = int(shadow.get("trades", 0))
    total_r = float(shadow.get("total_r", 0.0))
    if trades < min_trades:
        reasons.append(f"insufficient-trades:{trades}<{min_trades}")
    records = shadow.get("trade_records", [])
    values = [float(record["path_r"]) for record in records]
    equity = list(accumulate(values))
    peak = 0.0
    drawdown = 0.0
    for value in equity:
        drawdown = max(drawdown, peak - value)
        peak = max(peak, value)
    if drawdown > max_drawdown_r:
        reasons.append(f"drawdown-exceeded:{drawdown:.3f}R>{max_drawdown_r:g}R")
    if total_r <= 0:
        reasons.append(f"negative-or-flat-result:{total_r:+.3f}R")
    if summary.get("order_submission") is not False or summary.get("tick_verdict") != "PASS":
        status = "PAUSE_AND_INVESTIGATE"
    elif trades < min_trades:
        status = "CONTINUE_SHADOW"
    elif total_r > 0 and drawdown <= max_drawdown_r:
        status = "ELIGIBLE_FOR_REVIEW"
    else:
        status = "PAUSE_AND_INVESTIGATE"
    return {
        "schema": "mitemshub.v75.shadow-review.v1",
        "status": status,
        "reasons": reasons,
        "order_submission": False,
        "trades": trades,
        "total_r": total_r,
        "max_drawdown_r": round(drawdown, 6),
        "min_trades": min_trades,
        "max_drawdown_limit_r": max_drawdown_r,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("summary", type=Path)
    parser.add_argument("--min-trades", type=int, default=10)
    parser.add_argument("--max-drawdown-r", type=float, default=5.0)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if "trade_records" not in summary.get("shadow_summary", {}):
        shadow_path = args.summary.with_name("shadow_replay.json")
        if shadow_path.exists():
            shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
            summary.setdefault("shadow_summary", {})["trade_records"] = shadow["summary"].get(
                "trade_records", []
            )
    result = review(summary, args.min_trades, args.max_drawdown_r)
    output = args.summary.with_name("review_gate.json")
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    print("wrote", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
