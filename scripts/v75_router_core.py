"""Shared V75 router primitives.

This module owns the immutable pocket model, geometry payoff calculation, exact
feature matching, chronological non-overlap rule, and frozen-portfolio
execution. Discovery, policy fitting, and report/CLI concerns stay outside it.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

try:
    from clean_slate_v75 import parse_dt
    from v75_transition_policy import allowed as transition_allowed
except ModuleNotFoundError:
    from .clean_slate_v75 import parse_dt
    from .v75_transition_policy import allowed as transition_allowed


# Exit geometries are part of the router contract, not of raw-data ingestion.
# The opportunity map re-exports this tuple for compatibility with its CLI users.
GEOMETRIES = ((0.50, 1.50), (0.75, 1.50), (0.75, 2.00),
              (0.75, 2.50), (1.00, 2.00), (1.00, 2.50))


@dataclass(frozen=True)
class Pocket:
    context: str
    regime: str
    m32_bin: str
    efficiency_bin: str
    distance_bin: str
    direction: int
    horizon: int
    geometry: str
    n: int
    expectancy_r: float
    target_rate: float


def pocket_key(pocket: Pocket) -> tuple:
    return (pocket.context, pocket.regime, pocket.m32_bin, pocket.efficiency_bin,
            pocket.distance_bin, pocket.direction, pocket.horizon, pocket.geometry)


def metric_key(row: dict, geometry: str) -> tuple:
    return (row["context"], row["regime"], row["m32_bin"], row["efficiency_bin"],
            row["distance_bin"], row["direction"], row["horizon"], geometry)


def setup_key(pocket: Pocket) -> tuple:
    """Identify a signal setup while ignoring its exit geometry."""
    return pocket_key(pocket)[:-1]


def family_key(pocket: Pocket) -> str:
    return f"{pocket.context}|{pocket.regime}|{pocket.direction:+d}"


def path_r(row: dict, geometry: str) -> float:
    stop, target = next((stop, target) for stop, target in GEOMETRIES
                        if f"sl{stop:g}_tp{target:g}" == geometry)
    if bool(row["target_before_stop"][geometry]):
        return float(target) / float(stop)
    if float(row["mae_r"]) <= -float(stop):
        return -1.0
    return float(row["horizon_r"]) / float(stop)


def matches(row: dict, pocket: Pocket) -> bool:
    return (row["context"] == pocket.context and row["regime"] == pocket.regime
            and row["m32_bin"] == pocket.m32_bin
            and row["efficiency_bin"] == pocket.efficiency_bin
            and row["distance_bin"] == pocket.distance_bin
            and row["direction"] == pocket.direction and row["horizon"] == pocket.horizon
            and pocket.geometry in row["target_before_stop"])


def sequential_rows(rows: list[dict], horizon: int) -> list[dict]:
    """Keep one opportunity until the prior modeled horizon has elapsed."""
    selected: list[dict] = []
    next_allowed: datetime | None = None
    for row in sorted(rows, key=lambda item: parse_dt(item["timestamp"])):
        timestamp = parse_dt(row["timestamp"])
        if next_allowed is not None and timestamp < next_allowed:
            continue
        selected.append(row)
        next_allowed = timestamp + timedelta(minutes=15 * horizon)
    return selected


def evaluate_pocket(metrics: list[dict], pocket: Pocket,
                    start: datetime, end: datetime) -> dict:
    rows = sequential_rows(
        [row for row in metrics
         if start <= parse_dt(row["timestamp"]) < end and matches(row, pocket)],
        pocket.horizon,
    )
    values = [path_r(row, pocket.geometry) for row in rows]
    equity = np.cumsum(values) if values else np.asarray([], dtype=float)
    drawdown = float(np.max(np.maximum.accumulate(equity) - equity)) if values else 0.0
    return {"n": len(values), "wins": sum(value > 0 for value in values),
            "total_r": round(math.fsum(values), 6),
            "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
            "max_drawdown_r": round(drawdown, 6)}


def row_allowed(row: dict, selected: dict) -> bool:
    allowed_states = selected.get("allowed_transition_states")
    if allowed_states is None:
        return bool(transition_allowed(str(row.get("transition_state", "UNKNOWN"))))
    return bool(row.get("transition_state", "UNKNOWN") in allowed_states)


def _outcome(row: dict, geometry: str) -> str:
    stop = float(geometry.split("_", 1)[0][2:])
    if row["target_before_stop"][geometry]:
        return "TARGET"
    if row["mae_r"] <= -stop:
        return "STOP"
    return "HORIZON"


def _portfolio_summary(values: list[float], used: dict[str, int],
                      invalidated: set[str], health_loss_streak: int) -> dict:
    equity = np.cumsum(values) if values else np.asarray([], dtype=float)
    drawdown = float(np.max(np.maximum.accumulate(equity) - equity)) if values else 0.0
    return {"n": len(values), "wins": sum(value > 0 for value in values),
            "total_r": round(math.fsum(values), 6),
            "mean_r": round(float(np.mean(values)), 6) if values else 0.0,
            "max_drawdown_r": round(drawdown, 6), "hypotheses": dict(used),
            "invalidated_families": sorted(invalidated),
            "health_loss_streak": health_loss_streak}


def _run_frozen_portfolio(metrics: list[dict], selected: list[dict],
                          start: datetime, end: datetime,
                          health_loss_streak: int = 3,
                          collect_events: bool = False) -> tuple[list[dict], dict]:
    """Run the single frozen-portfolio lifecycle used by reports and scoring.

    ``collect_events`` is deliberately opt-in: scoring needs the summary only,
    while shadow replay opts into the presentation trace.
    """
    pockets = [Pocket(**item["pocket"]) for item in selected]
    ranks = {pocket_key(pocket): index for index, pocket in enumerate(pockets)}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in metrics:
        timestamp = parse_dt(row["timestamp"])
        if start <= timestamp < end:
            grouped[row["timestamp"]].append(row)

    events: list[dict] = []
    values: list[float] = []
    used: dict[str, int] = defaultdict(int)
    loss_streaks: dict[str, int] = defaultdict(int)
    invalidated: set[str] = set()
    next_allowed: datetime | None = None
    for timestamp_text in sorted(grouped, key=parse_dt):
        timestamp = parse_dt(timestamp_text)
        rows = grouped[timestamp_text]
        matching: list[tuple[Pocket, dict]] = []
        for row in rows:
            for pocket in pockets:
                selected_item = selected[ranks[pocket_key(pocket)]]
                if row_allowed(row, selected_item) and matches(row, pocket):
                    matching.append((pocket, row))

        if not matching:
            if collect_events:
                events.append({"timestamp": timestamp_text, "action": "NO_TRADE",
                               "reason": "no_validated_pocket"})
            continue

        pocket, row = min(
            matching,
            key=lambda item: (ranks[pocket_key(item[0])], parse_dt(item[1]["timestamp"])),
        )
        family = family_key(pocket)
        common = {"timestamp": timestamp_text, "family": family,
                  "direction": pocket.direction, "horizon": pocket.horizon,
                  "geometry": pocket.geometry, "regime": pocket.regime,
                  "context": pocket.context}
        if family in invalidated:
            if collect_events:
                events.append({**common, "action": "NO_TRADE", "reason": "family_invalidated"})
            continue
        if next_allowed is not None and timestamp < next_allowed:
            if collect_events:
                events.append({**common, "action": "NO_TRADE", "reason": "position_open"})
            continue

        value = path_r(row, pocket.geometry)
        if collect_events:
            events.append({**common, "action": "BUY" if pocket.direction > 0 else "SELL",
                           "reason": "router_accepted", "path_r": float(value),
                           "outcome": _outcome(row, pocket.geometry)})
        values.append(value)
        used[f"{family}|h{pocket.horizon}"] += 1
        if value <= 0:
            loss_streaks[family] += 1
            if loss_streaks[family] >= health_loss_streak:
                invalidated.add(family)
        else:
            loss_streaks[family] = 0
        next_allowed = timestamp + timedelta(minutes=15 * pocket.horizon)

    return events, _portfolio_summary(values, used, invalidated, health_loss_streak)


def replay_frozen_portfolio(metrics: list[dict], selected: list[dict],
                            start: datetime, end: datetime,
                            health_loss_streak: int = 3) -> list[dict]:
    """Trace the shared frozen-portfolio lifecycle for audit presentation."""
    events, _ = _run_frozen_portfolio(
        metrics, selected, start, end, health_loss_streak, collect_events=True,
    )
    return events


def evaluate_frozen_portfolio(metrics: list[dict], selected: list[dict],
                              start: datetime, end: datetime,
                              health_loss_streak: int = 3) -> dict:
    """Evaluate the same frozen lifecycle used by shadow replay."""
    _, summary = _run_frozen_portfolio(
        metrics, selected, start, end, health_loss_streak, collect_events=False,
    )
    return summary
