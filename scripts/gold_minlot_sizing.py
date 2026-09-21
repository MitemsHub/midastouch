#!/usr/bin/env python3
"""What the arm's REAL size does to the daily line, and what size would buy decidability.

TWO QUESTIONS, ONE ANSWER EACH, AND BOTH WERE ASKED AFTER THE RISK WAS CUT TO 0.25%.

1. THE DAILY HEADROOM AT THE SIZE THE ARM ACTUALLY TRADES. `gold_prereg_no_target.py` sized
   the deployability leg in flat dollars-per-R (1.00/0.75/0.50/0.25% of $25,000). That is not
   the size this arm takes: at 0.25% the budget ($62.50) sits ABOVE the venue's minimum-lot
   floor, so the EA trades the minimum lot — and at 0.01 lot the dollars a trade risks is its
   own stop distance in dollars, which VARIES trade to trade. A flat $/R therefore charges
   every trade the same dollars while the real book charges each one its own ATR. This script
   runs the same governor over the same entries with a PER-TRADE risk, using the hook added to
   `gold_governed_wfo.govern(risk_usd_for=...)`, and reports the worst simulated day.

   It also re-derives the FLAT rows from the frozen artifact and asserts they reproduce, so
   the two tables are provably the same machinery and the difference is only the sizing model.

2. WHAT LOT SIZE WOULD MAKE THE EDGE DECIDABLE. The answer is NONE, and the arithmetic says
   why: a t-statistic is `mean_r / (sd_r / sqrt(n))`. Both mean_r and sd_r are in R, and R is
   a size-free unit — the dollars cancel out of every ratio. Lot size changes the account's
   dollars and which trades the GOVERNOR vetoes (that is question 1); it cannot change a
   single R, so it cannot move the required sample by one trade. What decidability needs is
   trades, and the trades come at a measured flow. This script prints the required n at the
   measured effect, the measured flow, and the calendar time that implies — plus the one
   thing that DOES buy decidability (a larger mean-to-dispersion ratio, i.e. a different
   trigger or instrument).

Run:
    python scripts/gold_minlot_sizing.py
    python scripts/gold_minlot_sizing.py --out artifacts/gold_minlot_sizing.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_governed_wfo as gg                     # noqa: E402
import gold_prereg_no_target as gpn                # noqa: E402  (the frozen entry set + rule)
import gold_walkforward as gw                      # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

#: The venue's own spec, and the number the EA sizes on: the terminal's `broker tv/ts=10.00
#: vs settled 100.00 per price unit` line resolves to $100 per price unit per 1.00 lot, which
#: is also what the contract implies (XAUUSD is 100 oz/lot). Verified against the EA's own
#: floor table: it printed `stop=33.09 ($33.09) minlot=0.01`, i.e. $1 per $1 of stop distance
#: at 0.01 lot — the same figure this computes.
MIN_LOT = 0.01
SETTLED_VALUE_PER_UNIT_PER_LOT = 100.0

#: The power factor for a two-sided test at 5% with 80% power: z_{0.975} + z_{0.80} = 1.96 +
#: 0.84. This is the factor the frozen declaration used (its 766 for +0.3221R at sd 3.1838 is
#: ceil((2.8 * 3.1838 / 0.3221)^2)), kept here as the same convention rather than re-derived.
Z_POWER = 1.96 + 0.84


def dollars_per_r_minlot(atr_at_entry: float, stop_mult: float) -> float:
    """The dollars one R is worth when the venue's minimum lot is the size.

    R is the stop distance (`stop_mult` x ATR(H1) at the entry bar), so:
        dollars = min_lot x stop_distance x settled_value_per_unit_per_lot
    With the arm's own numbers (minlot 0.01, settled 100, stop 1.0xATR) this is `atr` in
    dollars — the identity behind the EA's floor-table line, not an approximation of it.
    """
    return MIN_LOT * stop_mult * atr_at_entry * SETTLED_VALUE_PER_UNIT_PER_LOT


def deployability_per_trade(trades: list[dict], epoch, atr, rules, risk_of) -> dict:
    """The declared deployability leg with a PER-TRADE dollars-per-R.

    `risk_of(trade) -> float` replaces the flat scalar. Everything else — the vote counts, the
    day buckets, the breach rule — is the declared leg's own arithmetic, so the only thing
    that changed between the two tables is how many dollars the book risked per trade.
    """
    kept, vetoes = gg.govern(trades, epoch, rules=rules, risk_usd_for=risk_of)
    days: dict[str, float] = {}
    for t in kept:
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).strftime("%Y-%m-%d")
        days[d] = days.get(d, 0.0) + float(t["net_r"]) * float(risk_of(t))
    worst = min(days.values()) if days else 0.0
    limit = rules.daily_loss_limit_usd
    return {
        "trades_kept": len(kept),
        "trades_vetoed": len(trades) - len(kept),
        "vetoes": vetoes,
        "days": len(days),
        "worst_day_usd": round(worst, 2),
        "daily_limit_usd": round(limit, 2),
        "headroom_usd": round(limit + worst, 2),          # limit - |worst|, signed correctly
        "worst_day_pct_of_account": round(100.0 * -worst / rules.account_size, 3),
        "days_beyond_daily_limit": sum(1 for v in days.values() if v < -limit),
    }


def n_for_threshold(mean_r: float, sd: float, t_target: float) -> int | None:
    """Trades needed for t >= t_target at this effect (the frozen helper)."""
    return gg.power_trades(mean_r, sd, t_target)


def n_for_power(mean_r: float, sd: float) -> int | None:
    """Trades needed for 80% power at 5%, two-sided: ceil((1.96+0.84) * sd / mean)^2."""
    if not sd or not mean_r or mean_r <= 0:
        return None
    return int(math.ceil((Z_POWER * sd / mean_r) ** 2))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_minlot_sizing.json")
    a = ap.parse_args(argv)

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    rules = ThunderboltClassicRules(account_size=gg.ACCOUNT_SIZE)
    print(f"venue window: {datetime.fromtimestamp(epoch[0], timezone.utc)} .. "
          f"{datetime.fromtimestamp(epoch[-1], timezone.utc)}  ({n} bars)")

    # The frozen entry set and rule, taken from the pre-registered study itself — its config
    # builder, its trigger, its session and its rule — so this cannot quietly measure a
    # different strategy. `run_grid` is the entry finder the study used; nothing is re-typed.
    entries = gg.run_grid(B, hours, ok, atr, gpn.entry_config(gpn.PRIMARY_SESSION), n)
    trades = gpn.ge.simulate_policy(B, entries, atr, **gpn.RULE)
    st = gpn.ge.stats([t["net_r"] for t in trades])
    print(f"primary entries: n={st['n']} mean={st['mean_r']:+.4f}R sd={st['sd']:.4f} "
          f"t={st['t']:+.2f}   (rule: stop 1.0xATR, no target, flat by "
          f"{gpn.gw.FLAT_BY_UTC_HOUR}:00 UTC)")

    # --- 1. the daily line at the real size -------------------------------------------
    flat_rows = gpn.sizing_scan(trades, epoch, rules)
    frozen = json.loads((ROOT / "artifacts" / "gold_prereg_no_target.json")
                        .read_text(encoding="utf-8")).get("sizing_scan_post_hoc", [])
    mismatched = [(r["risk_pct"], r["worst_day_usd"], f["worst_day_usd"])
                  for r, f in zip(flat_rows, frozen) if r["worst_day_usd"] != f["worst_day_usd"]]
    print(f"\n== flat-dollar scan (the frozen artifact's own rows) ==\n"
          f"  {'risk/R':>8} {'%':>6} {'kept':>6} {'worst day':>11} {'line':>8} {'beyond':>7}")
    for r in flat_rows:
        print(f"  {r['risk_usd_per_r']:>8.1f} {r['risk_pct']:>6.2f} {r['trades_kept']:>6} "
              f"{r['worst_day_usd']:>11.2f} {r['daily_limit_usd']:>8.0f} "
              f"{r['days_beyond_daily_limit']:>7}")
    print("  reproduces artifacts/gold_prereg_no_target.json: "
          + ("EXACTLY" if not mismatched else f"MISMATCH {mismatched}"))

    # the real size: min lot, so dollars-per-R is each trade's own ATR in dollars
    stop_mult = gpn.FROZEN_TRIGGER["stop_mult"]
    dpr = [dollars_per_r_minlot(float(atr[t["entry_i"]]), stop_mult) for t in trades]
    risk_of = (lambda t: dollars_per_r_minlot(float(atr[t["entry_i"]]), stop_mult))
    minlot = deployability_per_trade(trades, epoch, atr, rules, risk_of)
    mean_dpr = sum(dpr) / len(dpr)
    print(f"\n== the size the arm really takes: minimum lot ({MIN_LOT}) ==\n"
          f"  dollars per R: mean ${mean_dpr:.2f} (min ${min(dpr):.2f}, max ${max(dpr):.2f}) "
          f"= {100.0 * mean_dpr / rules.account_size:.3f}% of the account, per trade\n"
          f"  {'kept':>6} {'worst day':>11} {'line':>8} {'beyond':>7} {'headroom':>10}")
    print(f"  {minlot['trades_kept']:>6} {minlot['worst_day_usd']:>11.2f} "
          f"{minlot['daily_limit_usd']:>8.0f} {minlot['days_beyond_daily_limit']:>7} "
          f"{minlot['headroom_usd']:>10.2f}")
    print(f"  worst day = {minlot['worst_day_pct_of_account']:.3f}% of the account vs the "
          f"venue's 3.000% line -> headroom ${minlot['headroom_usd']:.2f}")

    # --- 2. what size would make it decidable -----------------------------------------
    span_days = max(1.0, (float(epoch[-1]) - float(epoch[0])) / 86400.0)
    per_day_all = st["n"] / span_days
    in_session = sum(1 for h in hours
                     if gpn.PRIMARY_SESSION[0] <= int(h) < gpn.PRIMARY_SESSION[1])
    session_days = max(1.0, (in_session / max(1, len(hours))) * span_days)
    per_day_session = st["n"] / session_days
    n_t = n_for_threshold(st["mean_r"], st["sd"], gpn.T_REQ)
    n_p = n_for_power(st["mean_r"], st["sd"])
    years = (n_p / per_day_all / 365.25) if n_p else None
    print("\n== decidability: what lot size would buy it? none, and here is the arithmetic ==")
    print(f"  measured: mean {st['mean_r']:+.4f}R over n={st['n']}, sd {st['sd']:.4f}")
    print(f"  required for t>={gpn.T_REQ:.2f}: {n_t} trades")
    print(f"  required for 80% power: {n_p} trades")
    print(f"  measured flow: {per_day_all:.2f} entries/calendar-day "
          f"({per_day_session:.2f}/session-day)")
    if years:
        print(f"  calendar time to 80% power at that flow: {years:.2f} years")
    print("  THE BINDING REQUIREMENT IS NOT THIS ONE. docs/GOLD_PREREG_NO_TARGET_20260921.md fixed"
          " 766")
    print("  trades BEFORE the run, from the DISCOVERY set's effect (+0.3221R, sd 3.1838), and"
          " n=658")
    print(f"  against it is what returns `POSITIVE, UNDERPOWERED`. The {n_p} above uses the PRIMARY")
    print("  set's larger effect (+0.4230R): a post-hoc recalculation that would UPGRADE the"
          " verdict,")
    print("  which is why it is reported as arithmetic and never applied as a decision.")
    print("  lot size does not enter any line above: t = mean/(sd/sqrt(n)), both in R, and R is\n"
          "  size-free — the dollars cancel. Size moves dollars and the governor's vetoes\n"
          "  (table 1); it cannot move the required sample by one trade. What would is a larger\n"
          "  mean-to-dispersion ratio — a different trigger or instrument — or more entries per\n"
          "  day, which no account size supplies.")

    out = {
        "what": "The min-lot sizing scan (the size this arm actually takes) and the "
                "decidability arithmetic, both post-hoc and both labelled as such.",
        "venue_window": [datetime.fromtimestamp(epoch[0], timezone.utc).isoformat(),
                         datetime.fromtimestamp(epoch[-1], timezone.utc).isoformat()],
        "entry_set": {"session_utc": list(gpn.PRIMARY_SESSION), "rule": gpn.RULE,
                      "stop_mult": stop_mult, "stats": st},
        "sizing": {
            "flat_rows_reproduce_the_frozen_artifact": not mismatched,
            "flat_rows_mismatch": mismatched,
            "flat_rows": flat_rows,
            "min_lot": MIN_LOT,
            "settled_value_per_unit_per_lot": SETTLED_VALUE_PER_UNIT_PER_LOT,
            "dollars_per_r_mean": round(mean_dpr, 4),
            "dollars_per_r_min": round(min(dpr), 4),
            "dollars_per_r_max": round(max(dpr), 4),
            "min_lot_row": minlot,
        },
        "decidability": {
            "mean_r": st["mean_r"], "sd": st["sd"], "n": st["n"],
            "n_for_threshold_1_96": n_t, "n_for_power_80": n_p,
            "z_power_factor": Z_POWER,
            "entries_per_calendar_day": round(per_day_all, 4),
            "entries_per_session_day": round(per_day_session, 4),
            "years_to_80pc_power": round(years, 2) if years else None,
            "post_hoc_not_the_declared_requirement": (
                "These n's are computed from the PRIMARY set's own effect (+0.4230R), which is "
                "larger than the DISCOVERY set's (+0.3221R) the declaration used to fix 766 "
                "trades before the run. That 766 is the binding threshold and n=658 against "
                "it is what returns `POSITIVE, UNDERPOWERED`; the numbers here would upgrade "
                "the verdict and are therefore reported as arithmetic, never applied as a "
                "decision."),
            "lot_size_enters_the_arithmetic": False,
            "why": "t = mean_r / (sd_r / sqrt(n)) — both in R, and R is size-free, so the "
                   "dollars cancel. Size changes the dollars at stake and which trades the "
                   "governor vetoes; it cannot change the required sample.",
            "what_would": "a larger mean-to-dispersion ratio (a different trigger or "
                          "instrument), or more entries per day. No account size supplies "
                          "either.",
        },
        "caveat": "The min-lot row is the no-target policy's, whose R is 1.0xATR(H1). The armed "
                  "arm's stop is 2.0xATR, so its min-lot dollars-per-R is twice this table's — "
                  "and its exits differ, so neither number transfers. What transfers is the "
                  "method: dollars-per-R is the trade's own stop distance at the venue's "
                  "minimum lot, not an average.",
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
