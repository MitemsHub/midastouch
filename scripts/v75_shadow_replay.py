#!/usr/bin/env python3
"""Research-only shadow replay for frozen adaptive-router selections."""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from clean_slate_v75 import parse_dt  # noqa: E402
from v75_adaptive_router import discover, score_candidates  # noqa: E402
from v75_opportunity_map import build_map  # noqa: E402
from v75_router_core import replay_frozen_portfolio  # noqa: E402


@dataclass(frozen=True)
class ShadowDecision:
    timestamp: str
    action: str
    reason: str
    fold: int
    family: str = ""
    direction: int = 0
    horizon: int = 0
    geometry: str = ""
    regime: str = ""
    context: str = ""
    path_r: float = 0.0
    outcome: str = ""


def replay_window(metrics: list[dict], selected: list[dict], start: datetime,
                  end: datetime, fold: int, health_loss_streak: int = 3) -> list[ShadowDecision]:
    """Render the shared lifecycle trace as typed shadow decisions."""
    return [ShadowDecision(fold=fold, **event)
            for event in replay_frozen_portfolio(metrics, selected, start, end,
                                                 health_loss_streak)]


def run(metrics: list[dict], start: datetime, end: datetime, train_days: int,
        validation_days: int, test_days: int, portfolio_size: int,
        min_samples: int, recent_weight: float,
        health_loss_streak: int = 3) -> dict:
    folds: list[dict] = []
    decisions: list[ShadowDecision] = []
    cursor = start
    fold = 0
    while cursor + timedelta(days=train_days + validation_days + test_days) <= end:
        fold += 1
        train_end = cursor + timedelta(days=train_days)
        validation_start = train_end
        validation_end = validation_start + timedelta(days=validation_days)
        test_end = validation_end + timedelta(days=test_days)
        discovered = discover(metrics, cursor, train_end, min_samples)
        scored = score_candidates(metrics, discovered, cursor, validation_start,
                                  validation_end, recent_weight)
        selected = scored[:portfolio_size]
        fold_decisions = replay_window(metrics, selected, validation_end, test_end,
                                       fold, health_loss_streak)
        decisions.extend(fold_decisions)
        folds.append({"fold": fold,
                      "train_window": [cursor.isoformat(), train_end.isoformat()],
                      "validation_window": [validation_start.isoformat(), validation_end.isoformat()],
                      "test_window": [validation_end.isoformat(), test_end.isoformat()],
                      "discovered": len(discovered), "selected": selected,
                      "decisions": len(fold_decisions),
                      "trades": sum(item.action in {"BUY", "SELL"} for item in fold_decisions),
                      "total_r": round(sum(item.path_r for item in fold_decisions), 6)})
        cursor += timedelta(days=test_days)
    trade_records = [asdict(item) for item in decisions if item.action in {"BUY", "SELL"}]
    return {"schema": "mitemshub.v75.shadow-replay.v2", "research_only": True,
            "order_submission": False,
            "selection": "training discovery + recency-weighted validation; untouched test",
            "health_loss_streak": health_loss_streak,
            "folds": folds,
            "summary": {"decisions": len(decisions),
                        "no_trade": sum(item.action == "NO_TRADE" for item in decisions),
                        "trades": len(trade_records),
                        "wins": sum(item["path_r"] > 0 for item in trade_records),
                        "total_r": round(math.fsum(item["path_r"] for item in trade_records), 6),
                        "trade_records": trade_records},
            "decisions": [asdict(item) for item in decisions]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--ticks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=parse_dt, required=True)
    parser.add_argument("--end", type=parse_dt, required=True)
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--validation-days", type=int, default=10)
    parser.add_argument("--test-days", type=int, default=10)
    parser.add_argument("--portfolio-size", type=int, default=8)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--recent-weight", type=float, default=0.65)
    parser.add_argument("--health-loss-streak", type=int, default=3)
    args = parser.parse_args()
    report = build_map(args.data_dir, args.ticks, args.start, args.end)
    result = run(report["metrics"], args.start, args.end, args.train_days,
                 args.validation_days, args.test_days, args.portfolio_size,
                 args.min_samples, args.recent_weight, args.health_loss_streak)
    result["map_source"] = {"metrics": report["metrics_count"], "tick_file": str(args.ticks)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("decisions:", result["summary"]["decisions"],
          "no_trade:", result["summary"]["no_trade"],
          "trades:", result["summary"]["trades"],
          "total_R:", f"{result['summary']['total_r']:+.3f}")
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
