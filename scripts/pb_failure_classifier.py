"""Small, frozen entry-time classifier for the Vol75 PB-family failure study.

The classifier deliberately uses only fields emitted by ``certify_v75`` at the
entry decision: strategy composition and the contemporaneous absolute z
extension.  It has at most one clause for PB and one for MOM+PB, so a promoted
rule can be mirrored in the EA without a model runtime or hidden state.

Rules are selected from the training segment only.  Holdout code must consume a
``FailureRule`` returned by :func:`derive_rule` without fitting again.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from statistics import mean
from typing import Iterable

PB_FAMILY = frozenset(("PB", "MOM+PB"))


@dataclass(frozen=True)
class FailureRule:
    """Frozen two-clause rule; thresholds are absolute z values."""

    pb_max_abs_z: float | None = None
    mom_pb_max_abs_z: float | None = None

    @property
    def name(self) -> str:
        clauses = []
        if self.pb_max_abs_z is not None:
            clauses.append(f"PB|z|<={self.pb_max_abs_z:g}")
        if self.mom_pb_max_abs_z is not None:
            clauses.append(f"MOM+PB|z|<={self.mom_pb_max_abs_z:g}")
        return "v1:" + (" OR ".join(clauses) if clauses else "no-op")

    def blocks(self, entry: dict) -> bool:
        strat = entry.get("strat")
        z_abs = abs(float(entry.get("z", 0.0)))
        if strat == "PB" and self.pb_max_abs_z is not None:
            return z_abs <= self.pb_max_abs_z
        if strat == "MOM+PB" and self.mom_pb_max_abs_z is not None:
            return z_abs <= self.mom_pb_max_abs_z
        return False

    def to_dict(self) -> dict:
        return {"name": self.name, **asdict(self)}


def _family(trades: Iterable[dict]) -> list[dict]:
    return [trade for trade in trades if trade.get("strat") in PB_FAMILY]


def _stats(trades: list[dict]) -> dict:
    rs = [float(t["r"]) for t in trades]
    return {
        "n": len(rs),
        "total_r": round(sum(rs), 3),
        "mean_r": round(mean(rs), 4) if rs else 0.0,
    }


def _blocked(training: list[dict], rule: FailureRule) -> list[dict]:
    return [trade for trade in _family(training) if rule.blocks(trade)]


def _candidate_thresholds(training: list[dict], strat: str) -> list[float | None]:
    """Use fixed interpretable cut points, retaining only train-observed ranges."""
    observed = [abs(float(t["z"])) for t in _family(training) if t.get("strat") == strat]
    if not observed:
        return [None]
    upper = max(observed)
    # The grid is fixed before holdout inspection.  Thresholds are deliberately
    # coarse; this is a failure bucket, not a fitted probability model.
    return [None] + [x for x in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0) if x < upper]


def derive_rule(training: Iterable[dict], *, min_kept_family: int = 45) -> tuple[FailureRule, dict]:
    """Select one shallow rule from training outcomes and return its audit.

    Selection is deliberately conservative: a rule must leave at least
    ``min_kept_family`` PB-family trades, block at least 10 trades, and have a
    worse blocked mean R than the kept mean R.  Among those rules, it maximizes
    the training R recovered by vetoing the failure bucket, then prefers fewer
    blocked trades and simpler clauses.  No holdout values are read here.
    """
    train = list(training)
    family = _family(train)
    candidates = [
        FailureRule(pb, mom)
        for pb, mom in product(
            _candidate_thresholds(train, "PB"),
            _candidate_thresholds(train, "MOM+PB"),
        )
        if pb is not None or mom is not None
    ]
    eligible = []
    for rule in candidates:
        blocked = _blocked(family, rule)
        kept = [trade for trade in family if not rule.blocks(trade)]
        if len(blocked) < 10 or len(kept) < min_kept_family:
            continue
        blocked_stats = _stats(blocked)
        kept_stats = _stats(kept)
        if blocked_stats["mean_r"] >= kept_stats["mean_r"]:
            continue
        eligible.append({
            "rule": rule,
            "blocked": blocked_stats,
            "kept": kept_stats,
            "recovered_r": round(-blocked_stats["total_r"], 3),
            "clauses": sum(value is not None for value in (rule.pb_max_abs_z, rule.mom_pb_max_abs_z)),
        })
    if not eligible:
        raise ValueError("no training rule met the minimum sample and separation gates")
    selected = max(
        eligible,
        key=lambda row: (
            row["recovered_r"],
            -row["blocked"]["n"],
            -row["clauses"],
        ),
    )
    rule = selected["rule"]
    audit = {
        "rule": rule.to_dict(),
        "training_family": _stats(family),
        "blocked_training": selected["blocked"],
        "kept_training": selected["kept"],
        "recovered_training_r": selected["recovered_r"],
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "selection": "max recovered training R; min blocked n; min clauses",
        "min_blocked_family": 10,
        "min_kept_family": min_kept_family,
        "features": ["strat", "abs(z)"],
        "holdout_used": False,
    }
    return rule, audit


def summarize_filtered(trades: Iterable[dict], rule: FailureRule) -> dict:
    """Summarize a frozen rule's decisions for audit/debug output."""
    rows = list(trades)
    blocked = [trade for trade in rows if rule.blocks(trade)]
    kept = [trade for trade in rows if not rule.blocks(trade)]
    return {"all": _stats(rows), "blocked": _stats(blocked), "kept": _stats(kept)}
