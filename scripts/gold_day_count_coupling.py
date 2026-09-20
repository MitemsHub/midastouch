#!/usr/bin/env python3
"""Map the trade-count region where the drawdown AND Best Day constraints both hold.

WHY THIS EXISTS. DAILY-SEQ found something neither earlier study had looked for: a rule
aimed at the trailing drawdown (sitting out days after a loss) made the *Best Day* share
much worse — 9.6% to 29.8% — because trading fewer days re-clusters the winners into
fewer days. Two constraints that had been treated as independent turned out to be coupled
through the trade count.

This measures that coupling directly instead of inferring it from two points. Holding the
signal fixed (DAILY-ONE's H4 regime bit, one entry per day, its 4-vector geometry), it
varies only the brake — the one knob that moves the number of trading days — and reports
BOTH constraints for each setting, so the question "is there a trade count where both are
satisfied?" is answered from a curve rather than from an argument.

The quantity that matters for each point is not the total R (which everyone expects to
fall) but the pair:
  * **Best Day share** — must be <= 20%, and it is which constraint DAILY-SEQ broke.
  * **peak-to-trough / total profit** — the ratio the trailing shield actually polices,
    since the shield floors equity below its high-water mark and the target must still
    be reachable below it.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_daily_one as d1  # noqa: E402
import gold_daily_two as d2  # noqa: E402
import gold_wfo_v2 as w2  # noqa: E402
from gold_walkforward import tstat  # noqa: E402
from synthetic_trader.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

ACCOUNT = 25_000.0
BRAKES = (0, 1, 2, 3, 4, 6)


def cfgs_at(brake: int) -> list[dict]:
    """DAILY-ONE's geometry AT one brake setting — always exactly 4 configurations.

    THE FIRST VERSION OF THIS FILE GOT THIS WRONG, and the mistake is worth keeping on
    the record because it produced a flattering and false result. It let each row
    include every brake up to its own value, so the row for k was selected from
    ``4 x (k+1)`` configurations. The curve then showed the survivable size RISING with
    the brake ($194.92 at brake 0, $301.86 at brake 2) — which reads as the brake
    helping, but is simply best-of-12 selection beating best-of-4. Multiplicity, not
    mechanism.

    Holding the grid at 4 per row makes the brake the ONLY thing that varies, which is
    the one-variable comparison the question needs. It also makes every row directly
    comparable with the DAILY-SEQ run, whose control was this same grid.
    """
    return [{"stop_mult": s, "rr": r, "brake": brake}
            for s in d1.STOP_MULTS for r in d1.RR_MULTS]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_day_count_coupling.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT)
    P = w2.prepare(a.symbol, bars=a.bars)
    folds, epoch = P["folds"], P["epoch"]

    print(f"=== TRADE-COUNT COUPLING — {a.symbol}, brakes {BRAKES} ===")
    print(f"  {'max brake':>9} {'grid':>5} {'days':>5} {'total R':>9} {'t':>7} "
          f"{'best-day':>9} {'V7':>5} {'peak/trough':>12} {'R/tot':>7} "
          f"{'survive $':>10} {'V8':>5}")

    rows = []
    for brake in BRAKES:
        cfs = cfgs_at(brake)
        rs, trades = d2.run(P, cfs, folds)
        st = d2.loss_stats(trades, epoch)
        total = st["total_r"]
        share = st["best_day_share"] if total > 0 else None
        ratio = (st["worst_peak_to_trough_r"] / total) if total > 0 else float("inf")
        # The largest size the trailing shield tolerates, which is the point of V8.
        lo = rules.profit_target_usd / total if total > 0 else math.inf
        hi = (rules.daily_loss_limit_usd / abs(st["worst_loss_run_r"])
              if st["worst_loss_run_r"] < 0 else math.inf)
        r_ok = 0.0
        if total > 0 and lo <= max(hi, lo * 2):
            r_ok, _ = d1.max_surviving_risk(rules, trades, epoch, lo, max(hi, lo * 2))
        v7 = bool(share is not None and share <= 0.20)
        v8 = r_ok > 0
        row = {"max_brake": brake, "grid": len(cfs), "trades": len(trades),
               "days": st["days"], "total_r": total, "t": round(tstat(rs), 3),
               "positive_folds": sum(1 for x in rs if x > 0), "folds": len(rs),
               "best_day_share": round(share, 4) if share else None,
               "worst_loss_run_days": st["worst_loss_run_days"],
               "worst_peak_to_trough_r": st["worst_peak_to_trough_r"],
               "peak_trough_over_profit": round(ratio, 3) if math.isfinite(ratio)
               else None,
               "survivable_usd": round(r_ok, 2), "V7_best_day": v7, "V8_legal_size": v8}
        rows.append(row)
        print(f"  {brake:>9} {len(cfs):>5} {st['days']:>5} {total:>+9.2f} "
              f"{tstat(rs):>+7.2f} "
              f"{100 * share if share else float('nan'):>8.1f}% "
              f"{'PASS' if v7 else 'FAIL':>5} "
              f"{st['worst_peak_to_trough_r']:>12.2f} "
              f"{ratio if math.isfinite(ratio) else float('nan'):>7.2f} "
              f"{r_ok:>10,.2f} {'PASS' if v8 else 'FAIL':>5}")

    # ---- the question: does a trade count exist where BOTH hold? ------------- #
    both = [r for r in rows if r["V7_best_day"] and r["V8_legal_size"]]
    print("\n=== WHERE BOTH CONSTRAINTS HOLD ===")
    if both:
        best = max(both, key=lambda r: r["days"])
        print(f"  YES, at max brake {best['max_brake']}: {best['days']} days, "
              f"best-day {100 * best['best_day_share']:.1f}%, survivable "
              f"${best['survivable_usd']:,.2f}")
    else:
        print("  NO brake setting satisfies Best Day AND a legal size at once.")

    # Monotonicity, reported rather than assumed: if both measures worsen together as
    # days fall, the constraints are CO-MONOTONE in the trade count, which is the
    # opposite of the trade-off the sweep was looking for.
    ok = [r for r in rows if r["best_day_share"] and r["peak_trough_over_profit"]]
    if len(ok) >= 3:
        by_days = sorted(ok, key=lambda r: r["days"])
        shares = [r["best_day_share"] for r in by_days]
        ratios = [r["peak_trough_over_profit"] for r in by_days]
        share_rises = all(b >= a for a, b in zip(shares, shares[1:]))
        ratio_rises = all(b >= a for a, b in zip(ratios, ratios[1:]))
        print(f"\n  as trading days fall, the best-day share "
              f"{'RISES monotonically' if share_rises else 'does not rise monotonically'} "
              f"and drawdown-over-profit "
              f"{'RISES monotonically' if ratio_rises else 'does not rise monotonically'}.")
        if share_rises and ratio_rises:
            print("  -> the two constraints are CO-MONOTONE in the trade count: cutting "
                  "days makes BOTH worse. There is no trade-off to trade against, which "
                  "means the trade count can only be reduced at a cost to both, and any "
                  "rule that reduces it must justify itself on some other axis.")
    print(f"\n  (caveat: {len(rows)} brake points on ONE window is a thin curve, and each "
          f"row is a best-of-4 selection on the SAME folds, so cross-row differences "
          f"share the window's noise. This characterises a direction, not a curve fit.)")

    out = {"symbol": a.symbol, "brakes": list(BRAKES), "rows": rows,
           "both_hold": bool(both),
           "generated_utc": datetime.now(timezone.utc).isoformat()}
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
