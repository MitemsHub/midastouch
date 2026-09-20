"""Upcomers Thunderbolt Classic: the venue's rules and costs as arithmetic.

WHY THIS EXISTS. On 2026-09-19 the program moved from Deriv synthetic indices to a
$25,000 Upcomers Thunderbolt Classic prop account on MT5. Two things changed that
invalidate every earlier sizing assumption:

1. The risk budget is now **fixed by rule**, not chosen by us. A 3%/day loss limit
   and a 6% trailing Dynamic Risk Shield mean the account dies long before any
   conviction-based sizing matters. Breaching either ends the account, and a
   breach is not recoverable by being right afterwards.
2. Cost is no longer uniform. Upcomers charges **$5/lot on forex and metals, 0.04%
   of notional on crypto, and zero on indices, stocks and energies**. On a
   notional basis that is roughly 0.5 bps for forex, ~0.2 bps for gold, and
   **4.0 bps for crypto** — an 8x spread between the cheapest and dearest class on
   the same account, before any spread is paid.

That second point is the whole reason this module exists. Our own pre-registered
geometry/cost study (`docs/GEOMETRY_COST_STUDY_20260919.md`) found that spread
cost consumed 100.5% of V75's gross edge at tight geometry, and that widening the
stop halved the toll while collapsing the edge. The lesson generalises: **net
expectancy is decided by cost-to-volatility ratio, not by signal quality.** Which
instrument is "best" is therefore a measurable cost question, and it should be
answered by arithmetic rather than by preference.

Everything here is pure: no MT5, no network, no I/O. That makes the numbers
assertable in tests and reusable by the screen script.

Provenance of the constants (see `docs/UPCOMERS_INSTRUMENT_SELECTION_20260919.md`):
  * commissions / leverage / swap-free / drawdown systems -- Upcomers Help Center
    plus thegodfunded.com broker profile (cross-checked, 2026-09-19)
  * daily reset at 00:00 UTC, Best Day 20% -- Upcomers Help Center
  * 3% daily + 6% Dynamic Risk Shield on Thunderbolt Classic -- Upcomers Help
    Center program table

WHERE THE NUMBERS ARE SOFT. `per_side` vs `round_turn` quoting is not stated
explicitly by the venue, so :class:`CommissionSchedule` carries the multiplier as
data and :meth:`CommissionSchedule.round_trip_usd` doubles it by default. A
single-trade loss cap is widely reported but was not re-confirmed against the
current rulebook in this pass; it is modelled as an optional explicit parameter
rather than baked in as a fact, and :func:`risk_budget_usd` says so when it is
absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

# Re-exported below in __all__; defined after COMMISSION constants so the
# classifier can reference the class names without a forward reference.

__all__ = [
    "ASSET_CLASSES",
    "PATH_KEYWORDS",
    "SUFFIX_RULES",
    "CommissionSchedule",
    "DecayBudget",
    "InstrumentCandidate",
    "ThunderboltClassicRules",
    "classify_symbol",
    "cost_per_r",
    "documented_commission_bps",
    "max_consecutive_losses",
    "rank_candidates",
    "risk_budget_usd",
]

POS_2CM = 1e-8
"""Tolerance for float comparisons on money."""


# --------------------------------------------------------------------------- #
# Asset classes
# --------------------------------------------------------------------------- #

FOREX = "forex"
METALS = "metals"
INDICES = "indices"
STOCKS = "stocks"
ENERGIES = "energies"
CRYPTO = "crypto"

ASSET_CLASSES: tuple[str, ...] = (FOREX, METALS, INDICES, STOCKS, ENERGIES, CRYPTO)

#: Which classes can plausibly trade a weekend on this venue. Only crypto is
#: claimed to. NOTE: this is a *documented claim*, not a measurement -- the
#: third-party broker profile lists "Crypto Weekend Trading: yes" while Upcomers'
#: own 24/7 article describes the Perpetuals product, not MT5 CFDs. The MT5
#: session table (captured by ``scripts/venue_probe.py``) is the only thing that
#: settles it.
WEEKEND_CLAIMED: frozenset[str] = frozenset({CRYPTO})

#: Symbol suffix -> asset class. Upcomers' crypto CFDs are all ``*.nx``, its
#: Hong Kong single stocks ``*.xhkg``, and its cash indices ``*.c``. Used only
#: when the broker's own category path is unavailable.
SUFFIX_RULES: tuple[tuple[str, str], ...] = (
    (".nx", CRYPTO),
    (".xhkg", STOCKS),
    (".c", INDICES),
)

#: Keywords in the broker's category path or description. Ordered so a specific
#: class wins over a general one: "commodities (metals)" must resolve to metals.
PATH_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("energy", ENERGIES),
    ("energies", ENERGIES),
    ("metal", METALS),
    ("commodit", METALS),
    ("crypto", CRYPTO),
    ("forex", FOREX),
    ("indices", INDICES),
    ("index", INDICES),
    ("stock", STOCKS),
    ("share", STOCKS),
)


def classify_symbol(symbol: str, path: str = "", description: str = "") -> str | None:
    """Map one symbol to an asset class, or None when it cannot be classified.

    The broker's own category path wins over name suffixes because categories are
    authoritative and suffixes are conventions that drift. Returning None rather
    than guessing is deliberate: the cheapest classes on this venue are the
    zero-commission ones, so a classifier that invents a class for an unknown
    symbol would silently promote it into the free band.
    """
    haystack = f"{path} {description}".lower()
    for keyword, cls in PATH_KEYWORDS:
        if keyword in haystack:
            return cls
    low = symbol.lower()
    for suffix, cls in SUFFIX_RULES:
        if low.endswith(suffix):
            return cls
    return None


# --------------------------------------------------------------------------- #
# Commission
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CommissionSchedule:
    """Published Upcomers commission, expressed as a cost in USD.

    The schedule is *mixed-unit* by design -- per lot for forex and metals, a
    percentage of notional for crypto, and free for indices, stocks and energies --
    which is exactly why it must be converted to a common unit before any two
    instruments can be compared. :meth:`bps_per_notional` does that conversion and
    is the number that should be quoted when arguing about instrument choice.
    """

    forex_per_lot: float = 5.0
    metals_per_lot: float = 5.0
    crypto_pct_of_notional: float = 0.0004  # 0.04%
    free_classes: frozenset[str] = field(
        default_factory=lambda: frozenset({INDICES, STOCKS, ENERGIES})
    )
    #: Multiply per-side cost by this to get round-trip cost. 2.0 assumes the
    #: published figures are per side (the usual broker convention); set to 1.0
    #: if a statement shows the figure already covers both legs.
    round_trip_multiplier: float = 2.0

    def cost_per_side_usd(
        self,
        asset_class: str,
        *,
        lots: float,
        price: float,
        contract_size: float,
    ) -> float:
        """Commission for ONE leg, in USD."""
        if asset_class in self.free_classes:
            return 0.0
        if asset_class == CRYPTO:
            notional = abs(price) * abs(contract_size) * abs(lots)
            return self.crypto_pct_of_notional * notional
        if asset_class == FOREX:
            return self.forex_per_lot * abs(lots)
        if asset_class == METALS:
            return self.metals_per_lot * abs(lots)
        raise ValueError(f"unknown asset_class {asset_class!r}")

    def round_trip_usd(
        self,
        asset_class: str,
        *,
        lots: float,
        price: float,
        contract_size: float,
    ) -> float:
        """Commission for BOTH legs (entry + exit), in USD."""
        return self.round_trip_multiplier * self.cost_per_side_usd(
            asset_class, lots=lots, price=price, contract_size=contract_size
        )

    def bps_per_notional(
        self,
        asset_class: str,
        *,
        price: float,
        contract_size: float,
        round_trip: bool = True,
    ) -> float:
        """Commission in basis points of traded notional.

        Lot-independent *except* for the per-lot classes, where the notional of
        one lot depends on the instrument's own contract size -- which is the
        honest caveat: forex and metals pin to a lot, so their bps figure moves
        with price, while crypto's bps figure is exact by construction.
        """
        notional = abs(price) * abs(contract_size)
        if notional <= 0:
            return float("nan")
        leg = self.cost_per_side_usd(
            asset_class, lots=1.0, price=price, contract_size=contract_size
        )
        total = self.round_trip_multiplier * leg if round_trip else leg
        return (total / notional) * 1e4


# --------------------------------------------------------------------------- #
# Program rules
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ThunderboltClassicRules:
    """The Thunderbolt Classic (CFD, MT5) rule set for one account.

    Modelled as an immutable value object so a test can pin the arithmetic that
    decides whether a trade is legal.
    """

    account_size: float = 25_000.0
    profit_target_pct: float = 5.0
    daily_dd_pct: float = 3.0
    max_dd_pct: float = 6.0  # "Dynamic Risk Shield": trails the equity HWM
    best_day_pct: float = 20.0
    min_hold_seconds: int = 120  # sub-2-minute closes are flagged as tick scalping
    daily_reset_utc_hour: int = 0

    #: Reported by the venue's rulebook as a hard termination, but not
    #: re-confirmed in the 2026-09-19 pass. Left as an explicit opt-in so no
    #: sizing decision silently depends on an unverified number.
    single_trade_loss_pct: float | None = None

    # ---- derived levels -------------------------------------------------- #

    @property
    def profit_target_usd(self) -> float:
        return self.account_size * self.profit_target_pct / 100.0

    @property
    def daily_loss_limit_usd(self) -> float:
        """Loss allowed against the 00:00 UTC reference, in USD."""
        return self.account_size * self.daily_dd_pct / 100.0

    @property
    def max_drawdown_usd(self) -> float:
        return self.account_size * self.max_dd_pct / 100.0

    def daily_reference_equity(self, equity: float, balance: float) -> float:
        """The 00:00 UTC reference: whichever of equity/balance is HIGHER.

        Taking the higher value is the conservative reading and the one the venue
        documents, so a profitable day raises tomorrow's floor even if the profit
        is still floating.
        """
        return max(equity, balance)

    def daily_loss_floor_usd(self, equity: float, balance: float) -> float:
        """Equity level that breaches the daily limit."""
        return self.daily_reference_equity(equity, balance) - self.daily_loss_limit_usd

    def drawdown_floor_usd(self, peak_equity: float) -> float:
        """Equity level that breaches the trailing Dynamic Risk Shield.

        Starts ``max_dd_pct`` below the account size, trails the equity
        high-water mark upward, and **locks at the initial balance** -- once the
        account is ``max_dd_pct`` in profit the floor stops rising, so the initial
        balance itself becomes unreachable-to-lose. That lock is the single most
        useful asymmetry in the whole rule set and is why scaling into profit is
        worth more here than on a static-drawdown account.
        """
        initial = self.account_size
        trailing = peak_equity - self.max_drawdown_usd
        return max(initial - self.max_drawdown_usd, min(trailing, initial))

    def shield_room_usd(self, peak_equity: float) -> float:
        """How far equity can fall from ``peak_equity`` before the shield breaches.

        Exists as a named accessor because computing it by hand is how the prospective
        sequence ceiling came out **100x too high** on 2026-09-20: ``max_dd_pct`` is
        ``6.0``, a PERCENTAGE, so ``peak_equity * max_dd_pct`` is $150,000 on a $25,000
        account rather than the $1,500 the rule actually allows. Deriving the room from
        :meth:`drawdown_floor_usd` keeps the venue's own arithmetic in one place --
        including the lock at the initial balance, which makes the room grow with profit
        above 6% rather than staying fixed.
        """
        return peak_equity - self.drawdown_floor_usd(peak_equity)

    def best_day_share(self, daily_profits: Sequence[float]) -> float:
        """Largest single day as a fraction of total profit (0 when not in profit)."""
        total = sum(p for p in daily_profits if p > 0)
        if total <= 0:
            return 0.0
        return max(daily_profits, default=0.0) / total

    def best_day_ok(self, daily_profits: Sequence[float]) -> bool:
        return self.best_day_share(daily_profits) <= self.best_day_pct / 100.0


# --------------------------------------------------------------------------- #
# Sizing / budget
# --------------------------------------------------------------------------- #


def risk_budget_usd(
    rules: ThunderboltClassicRules,
    *,
    equity: float,
    balance: float,
    single_trade_cap_pct: float | None = None,
    safety_fraction: float = 1.0,
) -> tuple[float, str]:
    """Max USD risk for ONE trade, plus a note naming which limit bound it.

    Returns the minimum of every applicable ceiling rather than the most
    convenient one -- the failure mode this guards against is an operator reading
    the *daily* allowance and sizing a single position to consume all of it, so
    that one loss ends the day and two end the account.

    THE REFERENCE EQUITY IS WHY ``equity`` AND ``balance`` ARE ARGUMENTS. The
    daily limit is 3% of the 00:00 UTC reference, not 3% of the account's nominal
    size, so the allowance is derived from
    ``min(account_size, max(equity, balance))``. The ``min`` is the conservative
    reading of an unknown midnight reference in *both* directions: when the
    account has fallen, the true reference was at least as high as now, so the
    proxy is tight; when it has risen, the true reference may be higher, so the
    proxy understates the allowance rather than overstating it.

    Sizing from ``account_size`` alone -- which this function did until
    2026-09-19 -- silently ignores the account's actual state. That is the
    MIDASTOUCH condition in arithmetic: on a $39.58 account it would have
    reported a $750 daily allowance, permitted a lot size ~17x too large, and
    every downstream guard would have agreed because they all read the same
    wrong number.
    """
    reference = min(rules.account_size, max(equity, balance))
    ceiling = reference * rules.daily_dd_pct / 100.0
    note = f"daily {rules.daily_dd_pct:g}% limit"
    if reference < rules.account_size:
        note += (f" (on ${reference:,.2f} reference equity, not the nominal "
                 f"${rules.account_size:,.2f})")
    cap = single_trade_cap_pct if single_trade_cap_pct is not None else rules.single_trade_loss_pct
    if cap is not None:
        from_cap = reference * cap / 100.0
        if from_cap < ceiling:
            ceiling, note = from_cap, f"single-trade {cap:g}% cap"
    if not 0 < safety_fraction <= 1.0:
        raise ValueError("safety_fraction must be in (0, 1]")
    budget = ceiling * safety_fraction
    if cap is None and rules.single_trade_loss_pct is None:
        note += " (single-trade cap not modelled -- verify the current rulebook)"
    return budget, note


def max_consecutive_losses(budget_or_limit: float, per_trade_risk: float) -> int:
    """How many full-size losses fit inside a budget before it is exhausted."""
    if per_trade_risk <= 0:
        raise ValueError("per_trade_risk must be positive")
    return int(budget_or_limit // per_trade_risk)


@dataclass(frozen=True)
class DecayBudget:
    """The account's risk decay stated plainly, for the operator-facing report."""

    daily_loss_limit_usd: float
    per_trade_risk_usd: float
    losses_before_daily_breach: int
    losses_before_account_breach: int


# --------------------------------------------------------------------------- #
# Cost per R -- the metric that actually ranks instruments
# --------------------------------------------------------------------------- #


def cost_per_r(
    *,
    asset_class: str,
    price: float,
    contract_size: float,
    atr_price: float,
    spread_price: float,
    stop_mult: float,
    commission: CommissionSchedule,
    quote_to_usd: float = 1.0,
) -> float:
    """Round-trip cost expressed in R, where 1R is the stop distance.

    ``stop_mult`` is the stop distance in ATR units (stop = ``stop_mult`` x ATR).
    Cost is charged over the same move the stop sits at, which is why this ratio
    is lot-independent: both the cost and the stop scale linearly with size.

    The interpretation that matters: a result of 0.22 means the instrument must
    produce +0.22R of gross edge per trade merely to break even. Our measured V75
    gross edge was +0.027R/trade. No instrument on any venue survives a toll an
    order of magnitude larger than its edge, which is why this number, not the
    spread, is the one to screen on.

    ``quote_to_usd`` is the value of ONE unit of the instrument's quote currency in
    account currency, and it is NOT optional bookkeeping. On a USDJPY position the
    spread and the stop are both denominated in JPY, so they cancel -- but the
    commission is a flat **USD** $5/lot, and adding USD to JPY understates the toll
    by the FX rate. Worked through: a USDJPY stop is 100,000 x 0.16 JPY = 16,000 JPY
    = $102, so $10 of commission is 0.098R, not the 0.0006R the naive ratio gives.
    Ignoring the conversion made USDJPY rank 6th of 20 at a fictional 0.034R when
    its real toll is ~0.13R -- a full rank inversion, from a unit slip.

    The spread and stop terms are immune (the factor cancels), so this only bites
    the per-lot commission classes whose quote is not the account currency.
    """
    if atr_price <= 0 or stop_mult <= 0:
        raise ValueError("atr_price and stop_mult must be positive")
    if quote_to_usd <= 0:
        raise ValueError("quote_to_usd must be positive")
    units = abs(contract_size) * quote_to_usd
    spread_usd = abs(spread_price) * units
    commission_usd = commission.round_trip_usd(
        asset_class, lots=1.0, price=price, contract_size=contract_size
    )
    stop_usd = stop_mult * atr_price * units
    return (spread_usd + commission_usd) / stop_usd


@dataclass(frozen=True)
class InstrumentCandidate:
    """One symbol, with just enough data to be ranked on cost."""

    symbol: str
    asset_class: str
    price: float
    contract_size: float
    atr_price: float
    spread_price: float
    min_lot: float = 0.01
    weekend_capable: bool | None = None
    notes: str = ""
    #: Value of one quote-currency unit in account currency. 1.0 only for
    #: USD-quoted instruments -- see :func:`cost_per_r` for why it matters.
    quote_to_usd: float = 1.0


@dataclass(frozen=True)
class RankedCandidate:
    candidate: InstrumentCandidate
    cost_r: float
    commission_bps: float
    spread_bps: float


def rank_candidates(
    candidates: Iterable[InstrumentCandidate],
    *,
    stop_mult: float,
    commission: CommissionSchedule | None = None,
) -> list[RankedCandidate]:
    """Rank instruments by round-trip cost in R, cheapest first."""
    comm = commission or CommissionSchedule()
    out: list[RankedCandidate] = []
    for c in candidates:
        out.append(RankedCandidate(
            candidate=c,
            cost_r=cost_per_r(
                asset_class=c.asset_class,
                price=c.price,
                contract_size=c.contract_size,
                atr_price=c.atr_price,
                spread_price=c.spread_price,
                stop_mult=stop_mult,
                commission=comm,
                quote_to_usd=c.quote_to_usd,
            ),
            commission_bps=comm.bps_per_notional(
                c.asset_class, price=c.price, contract_size=c.contract_size
            ),
            spread_bps=(
                (abs(c.spread_price) / abs(c.price)) * 1e4 if c.price else float("nan")
            ),
        ))
    return sorted(out, key=lambda r: r.cost_r)


def documented_commission_bps(commission: CommissionSchedule | None = None,
                             ) -> Mapping[str, float]:
    """Round-trip commission in bps of notional for each class, at representative prices.

    Representative prices are *assumptions* (labelled as such) and are used only
    for the per-lot classes; crypto's figure is exact because it is a percentage
    of notional by construction. Indices, stocks and energies are zero by rule.

    The point of this table is that instrument choice on this venue is dominated
    by a fixed, published cost difference of more than 8x between classes -- a
    larger gap than any plausible signal-quality difference between them.
    """
    comm = commission or CommissionSchedule()
    return {
        FOREX: comm.bps_per_notional(FOREX, price=1.10, contract_size=100_000.0),
        METALS: comm.bps_per_notional(METALS, price=2_650.0, contract_size=100.0),
        INDICES: 0.0,
        STOCKS: 0.0,
        ENERGIES: 0.0,
        CRYPTO: comm.bps_per_notional(CRYPTO, price=100_000.0, contract_size=1.0),
    }
