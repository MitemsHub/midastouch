"""Per-instrument specs, risk caps and minimum-equity floors — one arithmetic home.

WHY THIS EXISTS. The 2026-09-19 revival found that the whole "which instrument
can this account trade?" question lived in a spreadsheet, while the live EA
decided it independently inside `MitemshubAI.mq5`. Two implementations of the
same arithmetic is how the operator ends up believing an instrument is tradeable
when the broker's minimum lot vetoes every signal.

The concrete trap this module closes: the EA gates every entry twice —

    eff_risk > InpMaxEffectiveRiskPct % of equity      (per-trade)
    fleet_risk + eff_risk > InpMaxTotalRiskPct % of equity   (fleet)

With defaults of 20% and 15%, a single-instrument book can NEVER use the 20%
allowance: the fleet guard refuses anything above 15% first. An operator
reasoning from the 20% number computes a required equity ~25% too low and sees
"unexplained" vetoes. :attr:`RiskCaps.binding_pct` is the only number that may
be used to decide whether an instrument fits, and :meth:`RiskCaps.warnings`
makes the contradiction loud instead of silent.

Everything here is pure arithmetic over an :class:`InstrumentSpec` — no MT5, no
I/O beyond the optional census loader — so the same numbers can be asserted in
tests and reused by research scripts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "InstrumentSpec",
    "RiskCaps",
    "FloorVerdict",
    "InstrumentAdapter",
]


@dataclass(frozen=True)
class InstrumentSpec:
    """Broker-side facts about one symbol. Frozen: these are measured, not tuned."""

    symbol: str
    min_lot: float
    lot_step: float
    digits: int
    usd_per_unit_per_lot: float = 1.0
    usd_per_unit_per_lot_source: str = "assumed-family-convention-1.0"
    spec_source: str = "unknown"

    def __post_init__(self) -> None:
        if self.min_lot <= 0:
            raise ValueError(f"{self.symbol}: min_lot must be > 0, got {self.min_lot}")
        if self.lot_step <= 0:
            raise ValueError(f"{self.symbol}: lot_step must be > 0, got {self.lot_step}")
        if self.usd_per_unit_per_lot <= 0:
            raise ValueError(
                f"{self.symbol}: usd_per_unit_per_lot must be > 0, got {self.usd_per_unit_per_lot}")

    @property
    def usd_is_measured(self) -> bool:
        """False when the dollar-per-unit figure is an assumption, not a measurement."""
        return self.usd_per_unit_per_lot_source.startswith("live")

    def money_risk(self, stop_price_distance: float, lots: float) -> float:
        """Dollar risk of `lots` over a stop `stop_price_distance` price units wide.

        Ticker-value calibrated exactly as the EA does it: price distance x
        dollars-per-price-unit-per-lot x lots. The broker's own
        `tick_value/step` ratio is deliberately NOT used — the EA source records
        the broker understating V75's tick value, which is why the census stores
        a measured/assumed `usd_per_unit_per_lot` instead.
        """
        if stop_price_distance <= 0:
            raise ValueError("stop_price_distance must be > 0")
        if lots <= 0:
            raise ValueError("lots must be > 0")
        return stop_price_distance * self.usd_per_unit_per_lot * lots

    def snap_lots(self, lots: float) -> float:
        """Floor to the broker's lot grid; 0.0 when below the minimum lot."""
        if lots < self.min_lot:
            return 0.0
        steps = int(lots / self.lot_step)
        snapped = steps * self.lot_step
        # Guard float drift so 3 x 0.001 does not land on 0.0029999999.
        return round(snapped, 8) if snapped >= self.min_lot else 0.0

    def volume_for_money_risk(self, stop_price_distance: float,
                              risk_money: float) -> float:
        """Largest grid-legal volume whose money risk does not exceed `risk_money`.

        Returns 0.0 when even the minimum lot would exceed the budget — the
        "CANNOT FIT" case the EA reports as a cap veto.
        """
        if risk_money <= 0:
            return 0.0
        per_lot = self.money_risk(stop_price_distance, 1.0)
        return self.snap_lots(risk_money / per_lot)


@dataclass(frozen=True)
class RiskCaps:
    """The EA's two risk ceilings, with the binding one derived rather than assumed."""

    per_trade_pct: float = 20.0
    fleet_pct: float = 15.0

    @property
    def binding_pct(self) -> float:
        """The ceiling that actually applies. min(), because the fleet guard runs last."""
        return min(self.per_trade_pct, self.fleet_pct)

    @property
    def binding_cap_name(self) -> str:
        return ("InpMaxTotalRiskPct" if self.fleet_pct <= self.per_trade_pct
                else "InpMaxEffectiveRiskPct")

    def warnings(self) -> list[str]:
        out: list[str] = []
        if self.per_trade_pct > self.fleet_pct:
            out.append(
                f"per-trade cap {self.per_trade_pct:.1f}% exceeds fleet cap "
                f"{self.fleet_pct:.1f}% — the larger allowance is unreachable; "
                f"{self.binding_pct:.1f}% is the real ceiling")
        return out


@dataclass(frozen=True)
class FloorVerdict:
    """Whether an instrument clears the account's floor at a given stop width."""

    symbol: str
    stop_price_distance: float
    min_lot_risk: float
    pct_of_equity: float
    required_equity: float
    equity: float
    can_trade: bool

    @property
    def shortfall(self) -> float:
        """Dollars short of the floor; 0.0 when tradeable."""
        return max(0.0, self.required_equity - self.equity)

    @property
    def reason(self) -> str:
        if self.can_trade:
            return (f"FLOOR-OK: min-lot risk ${self.min_lot_risk:.2f} = "
                    f"{self.pct_of_equity:.1f}% of ${self.equity:.2f}")
        return (f"CAP-VETOED: min-lot risk ${self.min_lot_risk:.2f} = "
                f"{self.pct_of_equity:.1f}% of ${self.equity:.2f}; "
                f"needs ${self.required_equity:.0f} (short ${self.shortfall:.2f})")


class InstrumentAdapter:
    """Lookup + arithmetic for a set of instruments under one set of caps."""

    def __init__(self, specs: dict[str, InstrumentSpec], caps: RiskCaps | None = None):
        self._specs = dict(specs)
        self.caps = caps or RiskCaps()

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def spec(self, symbol: str) -> InstrumentSpec:
        try:
            return self._specs[symbol]
        except KeyError:
            known = ", ".join(sorted(self._specs)) or "(none)"
            raise KeyError(f"unknown symbol {symbol!r}; known: {known}") from None

    def floor(self, symbol: str, stop_price_distance: float, equity: float) -> FloorVerdict:
        """Whether the minimum lot fits inside the binding cap at this stop width."""
        spec = self.spec(symbol)
        risk = spec.money_risk(stop_price_distance, spec.min_lot)
        cap_fraction = self.caps.binding_pct / 100.0
        required = risk / cap_fraction
        return FloorVerdict(
            symbol=symbol,
            stop_price_distance=stop_price_distance,
            min_lot_risk=risk,
            pct_of_equity=risk / equity * 100.0 if equity > 0 else float("inf"),
            required_equity=required,
            equity=equity,
            can_trade=required <= equity,
        )

    def volume_for_risk(self, symbol: str, stop_price_distance: float,
                        equity: float, risk_pct: float) -> float:
        """Grid-legal volume sized to risk `risk_pct` of equity, clamped by the cap.

        Returns 0.0 when the budget cannot cover the minimum lot — callers must
        treat that as a refusal, never as "trade the minimum anyway".
        """
        if risk_pct <= 0:
            raise ValueError("risk_pct must be > 0")
        spec = self.spec(symbol)
        budget = equity * risk_pct / 100.0
        capped = min(budget, equity * self.caps.binding_pct / 100.0)
        return spec.volume_for_money_risk(stop_price_distance, capped)

    @classmethod
    def from_census(cls, path: str | Path) -> "InstrumentAdapter":
        """Build the adapter from a `scripts/instrument_census.py` artifact.

        The census is the measurement of record: it carries the broker spec, the
        dollar basis and its provenance per symbol, so nothing here has to guess.
        """
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        caps = RiskCaps(
            per_trade_pct=float(doc.get("caps", {}).get("per_trade_pct", 20.0)),
            fleet_pct=float(doc.get("caps", {}).get("fleet_pct", 15.0)),
        )
        specs: dict[str, InstrumentSpec] = {}
        for row in doc.get("symbols", []):
            if "error" in row or "spec" not in row:
                continue
            s = row["spec"]
            specs[row["symbol"]] = InstrumentSpec(
                symbol=row["symbol"],
                min_lot=float(s["min_lot"]),
                lot_step=float(s["lot_step"]),
                digits=int(s["digits"]),
                usd_per_unit_per_lot=float(s["usd_per_unit_per_lot"]),
                usd_per_unit_per_lot_source=str(s["usd_per_unit_per_lot_source"]),
                spec_source=str(s["spec_source"]),
            )
        return cls(specs, caps)
