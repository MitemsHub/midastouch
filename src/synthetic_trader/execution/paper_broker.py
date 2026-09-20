"""A simulated broker: fills, costs and one-position-at-a-time bookkeeping.

WHY THIS IS A SEPARATE MODULE FROM THE RUNNER. The runner's job is I/O — connect to
the terminal, fetch bars, write state. The *decisions* (did the stop or the target
get hit first, what did the round trip cost, is a slot free) are arithmetic, and
arithmetic can be tested without a terminal, without a market and without a funded
account. Putting them here means the paper path is verified by the same kind of
assertion the rules and sizing already are, instead of being trusted because it
"looked right on the chart".

FIDELITY RULE. The exit semantics here are deliberately the SAME as the research
harness (`scripts/gold_wfo_v2._exit_fill`), because the point of paper trading is to
compare live behaviour against a backtest, and a paper fill engine that resolves
ties differently makes that comparison meaningless. Specifically:

* a gap through a barrier fills at the **open**, not at the barrier;
* when stop and target are both inside one bar, the **stop** is assumed first —
  pessimistic, the only reading that cannot flatter the result.

An optimistic paper account is worse than none: it manufactures confidence in a
strategy that has not earned any.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

__all__ = [
    "CostModel",
    "SimPosition",
    "PaperFill",
    "PaperAccount",
]

#: Tolerance for money comparisons, matching the rest of the execution package.
POS_2CM = 1e-8


@dataclass(frozen=True)
class CostModel:
    """What a round trip costs, in the same units the research used.

    ``spread_bps`` is a fraction of price per side (both directions cross it);
    ``commission_per_lot_rt`` is charged per lot per round trip. Keeping both in
    basis-point/lot terms rather than in dollars is what lets the same numbers be
    compared against the walk-forward's cost floor.
    """

    spread_bps: float = 1.073
    commission_per_lot_rt: float = 10.0
    usd_per_unit_per_lot: float = 100.0

    def round_trip_usd(self, *, lots: float, entry: float, exit: float) -> float:
        """Spread on the entry price plus commission — matching the harness.

        The harness charges the spread on the ENTRY price only (``SPREAD_BPS/1e4 *
        entry``). Reproducing that exactly matters more than modelling it better:
        a paper run that costs differently from the backtest cannot confirm or
        refute it.
        """
        if lots <= 0:
            return 0.0
        spread_usd = (self.spread_bps / 1e4) * entry * lots * \
            self.usd_per_unit_per_lot
        comm_usd = self.commission_per_lot_rt * lots
        return spread_usd + comm_usd


@dataclass
class SimPosition:
    """An open simulated position. One at a time, matching the research harness."""

    direction: int              # +1 long, -1 short
    lots: float
    entry: float
    stop: float
    target: float
    risk_usd: float
    opened_utc: str
    entry_bar_ts: int = 0

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError("direction must be +1 or -1")
        if self.lots <= 0 or self.risk_usd <= 0:
            raise ValueError("lots and risk_usd must be positive")


@dataclass(frozen=True)
class PaperFill:
    """A completed round trip, in dollars and in R."""

    direction: int
    lots: float
    entry: float
    exit: float
    entry_utc: str
    exit_utc: str
    exit_reason: str
    gross_usd: float
    cost_usd: float
    net_usd: float
    risk_usd: float

    @property
    def net_r(self) -> float:
        return self.net_usd / self.risk_usd if self.risk_usd else 0.0

    @property
    def is_win(self) -> bool:
        return self.net_usd > 0


@dataclass
class PaperAccount:
    """A simulated account that never touches the venue.

    ``balance`` moves only on a completed fill; ``equity`` marks the open position at
    the current price, because the venue's daily loss limit is measured against
    equity, not balance, and a paper account that conflates them would exercise the
    rules against the wrong number.
    """

    starting_balance: float
    balance: float = 0.0
    cost_model: CostModel = field(default_factory=CostModel)
    position: SimPosition | None = None
    closed: list[PaperFill] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.balance == 0.0:
            self.balance = self.starting_balance

    # -- state ------------------------------------------------------------- #

    @property
    def realised_usd(self) -> float:
        """Today's realised P&L, or the whole run's if the caller filters first.

        The account does not know about days — it knows about fills. Day scoping is
        the ledger's job, so a caller wanting "today" passes ``since_utc``.
        """
        return sum(f.net_usd for f in self.closed)

    def realised_since(self, since_utc: str) -> float:
        return sum(f.net_usd for f in self.closed if f.exit_utc >= since_utc)

    def equity(self, mark_price: float | None = None) -> float:
        eq = self.balance
        if self.position is not None and mark_price:
            eq += (self.open_unrealised_usd(mark_price))
        return eq

    def open_unrealised_usd(self, mark_price: float) -> float:
        p = self.position
        if p is None:
            return 0.0
        return ((mark_price - p.entry) * p.direction * p.lots
                * self.cost_model.usd_per_unit_per_lot)

    def snapshot(self) -> dict:
        return {
            "starting_balance": self.starting_balance,
            "balance": self.balance,
            "position": asdict(self.position) if self.position else None,
            "closed": [asdict(f) for f in self.closed],
        }

    @classmethod
    def restore(cls, raw: dict, cost_model: CostModel | None = None) -> "PaperAccount":
        acc = cls(starting_balance=float(raw["starting_balance"]),
                  balance=float(raw["balance"]),
                  cost_model=cost_model or CostModel())
        pos = raw.get("position")
        acc.position = SimPosition(**pos) if pos else None
        acc.closed = [PaperFill(**f) for f in raw.get("closed", [])]
        return acc

    # -- trading ----------------------------------------------------------- #

    def open(self, pos: SimPosition) -> None:
        """Take a position. Refuses if one is already open — the harness has one slot."""
        if self.position is not None:
            raise RuntimeError(
                "a simulated position is already open; refusing a second one, "
                "because the harness this paper account is measuring allows one "
                "position at a time and a paper run that overlaps is not the same "
                "system")
        self.position = pos

    def on_bar(self, *, high: float, low: float, close: float, open_: float,
               ts: int, ts_utc: str) -> PaperFill | None:
        """Advance one bar. Returns the fill if the position closed on this bar.

        Same tie rule as the research: gap through a barrier fills at the open;
        if both barriers sit inside the bar the STOP is assumed first.
        """
        p = self.position
        if p is None:
            return None
        exit_px: float | None = None
        why = ""
        if p.direction > 0:
            if open_ <= p.stop:
                exit_px, why = open_, "gap_stop"
            elif low <= p.stop:
                exit_px, why = p.stop, "stop"
            elif high >= p.target:
                exit_px, why = p.target, "target"
        else:
            if open_ >= p.stop:
                exit_px, why = open_, "gap_stop"
            elif high >= p.stop:
                exit_px, why = p.stop, "stop"
            elif low <= p.target:
                exit_px, why = p.target, "target"
        if exit_px is None:
            return None

        gross = (exit_px - p.entry) * p.direction * p.lots * \
            self.cost_model.usd_per_unit_per_lot
        cost = self.cost_model.round_trip_usd(lots=p.lots, entry=p.entry,
                                              exit=exit_px)
        fill = PaperFill(
            direction=p.direction, lots=p.lots, entry=p.entry, exit=exit_px,
            entry_utc=p.opened_utc, exit_utc=ts_utc, exit_reason=why,
            gross_usd=round(gross, 4), cost_usd=round(cost, 4),
            net_usd=round(gross - cost, 4), risk_usd=p.risk_usd)
        self.balance = round(self.balance + fill.net_usd, 4)
        self.closed.append(fill)
        self.position = None
        return fill

    def stop_distance(self, point: float) -> float:
        """Distance from the entry to the stop, for the risk arithmetic."""
        if self.position is None:
            return math.nan
        return abs(self.position.entry - self.position.stop)
