#!/usr/bin/env python3
"""Cost sensitivity of the gold verdicts: how wrong may the 1.073 bps model be?

Pre-registered in `docs/GOLD_COST_SENSITIVITY_PROTOCOL.md`, which was written and frozen
BEFORE this file existed. The grid, the decision rule and the interpretation are all
declared there; this script only executes them.

WHAT IT DOES. Runs the frozen DAILY-ONE pipeline (4 configs, 22 folds, one entry per UTC
day at 08:00, direction from the H4 regime bit) at spread multipliers
m in {0, 0.5, 1, 1.5, 2, 3, 5, 10}, re-running the matched null at every level, and
records which of the 8 gate legs survive each m.

WHY THE NULL IS RE-RUN PER LEVEL. V4 compares the actual total to the null's p95. The
null's own total also shrinks as cost rises, so reusing the m=1 null at m=10 would
compare an expensive strategy against a cheap bar. The nulls are seeded identically at
every level (NULL_SEED), so the same direction stream is drawn each time: that makes the
comparison PAIRED and removes null-sampling noise from the differences between levels.

WHY m=0 IS INCLUDED. It answers whether the entry rule has a gross edge at all. If the
strategy only clears zero cost by a hair, the entire result is a statement about cost.

WHY THERE IS A BISECTION. Total R is very nearly linear in m (the spread term is
proportional to m and the commission term is constant), so the break-even spread can be
located far more precisely than the grid spacing. The bisection is run on total R only —
no null — because no leg other than V4 consumes a null, and V4's answer is already
reported per grid point.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_daily_one as d1  # noqa: E402
import gold_walkforward as wf  # noqa: E402
import gold_wfo_v2 as w2  # noqa: E402
from gold_walkforward import prop_compat, tstat  # noqa: E402
from synthetic_trader.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

BASE_SPREAD_BPS = wf.SPREAD_BPS            # 1.073 — the model under test
MULTS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)
NULL_REPS = 200
NULL_SEED = d1.NULL_SEED
ACCOUNT = d1.ACCOUNT


def set_spread_mult(m: float) -> None:
    """Point every module that prices cost at the same swept value.

    Three modules hold the constant: `gold_walkforward` defines it, `gold_wfo_v2`
    imports a copy into its own namespace, and `gold_daily_one` imports a third. The
    trade pricer (`gold_wfo_v2._trade`) reads its module globals at call time, so
    patching only the defining module would silently leave the pipeline at m=1 — which
    is exactly the class of bug that produces a flat, believable, wrong table.
    """
    for mod in (wf, w2, d1):
        if hasattr(mod, "SPREAD_BPS"):
            mod.SPREAD_BPS = BASE_SPREAD_BPS * m


def run_arm(P: dict, cfgs: list[dict], rng: np.random.Generator | None = None):
    """One pass of the frozen pipeline. `rng` swaps in the matched null's direction."""
    end = P["holdout_start"]
    tb = [d1.simulate(P["B"], P["hours"], P["h4_ok_long"], P["h4_ok_short"], P["atr"],
                      c, start=w2.WARMUP_BARS, end=end, rng=rng) for c in cfgs]
    return d1.walk_forward(tb, cfgs, P["folds"])


def legs_for(P: dict, rules, oos_rs: list[float], oos_trades: list[dict],
             p95: float) -> tuple[dict, dict, float]:
    """The 8 pre-registered legs, defined exactly as DAILY-ONE defines them."""
    total = sum(oos_rs)
    n_oos = len(oos_trades)
    pos_folds = sum(1 for r in oos_rs if r > 0)
    t = tstat(oos_rs)
    best, day_total, share, ndays = d1.day_share(oos_trades, P["epoch"])

    prop = None
    if total > 0 and oos_trades:
        byday: dict = defaultdict(float)
        for tr in oos_trades:
            d = datetime.fromtimestamp(float(P["epoch"][tr["entry_i"]]),
                                       timezone.utc).date()
            byday[d] += tr["net_r"]
        worst_day = min(byday.values())
        lo = rules.profit_target_usd / total
        hi = (rules.daily_loss_limit_usd / abs(worst_day)) if worst_day < 0 else math.inf
        if lo <= hi:
            r_survive, prop_ok = d1.max_surviving_risk(rules, oos_trades,
                                                       P["epoch"], lo,
                                                       max(hi, lo * 2))
            # max_surviving_risk returns the SIZE, not the report; the report carries
            # no risk field, and reading one from it silently yielded 0.00 for every
            # level, which is indistinguishable from "no legal size" at a glance.
            prop = prop_ok if r_survive > 0 else None
            if prop:
                prop["risk_per_trade"] = round(r_survive, 2)

    srt = sorted(oos_rs)
    median = (srt[len(srt) // 2] if len(srt) % 2
              else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2) if srt else 0.0
    legs = {
        "V1 total>0": total > 0,
        "V2 pos>=60%": pos_folds >= 0.6 * len(oos_rs),
        "V3 worst>-3": (min(oos_rs) > -3.0) if oos_rs else False,
        "V4 beats null p95": total > p95,
        "V5 median>0": median > 0,
        "V6 t>=1.5": t >= 1.5,
        "V7 best-day<=20%": bool(share <= 0.20),
        "V8 legal size exists": bool(prop and prop["survived"] and prop["target_met"]),
    }
    facts = {"total_r": total, "n_trades": n_oos, "t": t, "pos_folds": pos_folds,
             "best_day_share": share, "days": ndays, "median": median,
             "worst_fold": min(oos_rs) if oos_rs else 0.0,
             "null_p95": p95, "v4_margin": total - p95,
             "surviving_risk": (prop or {}).get("risk_per_trade", 0.0)}
    return legs, facts, share


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--reps", type=int, default=NULL_REPS)
    ap.add_argument("--out", default="artifacts/gold_cost_sensitivity.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT)
    P = w2.prepare(a.symbol, bars=a.bars)
    cfgs = d1.configs()
    end = P["holdout_start"]
    print(f"COST SENSITIVITY: base spread {BASE_SPREAD_BPS} bps, {len(MULTS)} levels "
          f"x {len(cfgs)} configs x {len(P['folds'])} folds, null {a.reps} reps")
    print(f"data {P['B']['close'].shape[0]} bars, holdout starts {end}\n")
    print(f"{'m':>5} {'bps':>7} {'totalR':>9} {'t':>7} {'pos':>5} {'v4marg':>8} "
          f"{'bestday':>8} {'size$':>8} {'legs':>5}")

    rows = []
    # The null is generated ONCE per level, from the same seed, so the direction stream
    # is identical across levels and the level-to-level differences are cost alone.
    for m in MULTS:
        set_spread_mult(m)
        rng = np.random.default_rng(NULL_SEED)
        null_totals: list[float] = []
        for _rep in range(a.reps):
            nrs, _ = run_arm(P, cfgs, rng=rng)
            null_totals.append(sum(nrs))
        null_totals.sort()
        p95 = null_totals[int(0.95 * len(null_totals)) - 1]

        oos_rs, picks = run_arm(P, cfgs)
        oos_trades = [t for p in picks for t in p["trades"]]
        legs, facts, share = legs_for(P, rules, oos_rs, oos_trades, p95)
        npass = sum(1 for v in legs.values() if v)
        rows.append({"m": m, "bps": BASE_SPREAD_BPS * m, "legs": legs, **facts,
                     "n_pass": npass,
                     "null_median": null_totals[len(null_totals) // 2],
                     "null_max": null_totals[-1]})
        print(f"{m:>5.1f} {BASE_SPREAD_BPS * m:>7.3f} {facts['total_r']:>+9.2f} "
              f"{facts['t']:>+7.2f} {facts['pos_folds']:>2}/{len(oos_rs)} "
              f"{facts['v4_margin']:>+8.2f} {100 * share:>7.1f}% "
              f"{facts['surviving_risk']:>8.2f} {npass:>2}/8")

    # ---- fidelity control: m=1 must reproduce the published DAILY-ONE numbers ------ #
    ref = next(r for r in rows if r["m"] == 1.0)
    fid = (abs(ref["total_r"] - 12.83) < 0.01 and ref["n_trades"] == 119
           and abs(ref["t"] - 1.33) < 0.01 and abs(ref["null_p95"] - 13.02) < 0.01)
    print(f"\nfidelity at m=1.0: {ref['total_r']:+.2f}R / {ref['n_trades']} trades / "
          f"t {ref['t']:+.2f} / null p95 {ref['null_p95']:+.2f} -> "
          f"{'MATCHES published DAILY-ONE' if fid else 'MISMATCH — RUN VOID'}")

    # ---- break-even spread, by bisection on total R (no null needed) --------------- #
    set_spread_mult(MULTS[0])
    lo, hi = 0.0, 32.0
    for _ in range(18):
        mid = (lo + hi) / 2
        set_spread_mult(mid)
        rs, _ = run_arm(P, cfgs)
        if sum(rs) > 0:
            lo = mid
        else:
            hi = mid
    set_spread_mult(1.0)
    rs, _ = run_arm(P, cfgs)
    print(f"\nbreak-even spread: m = {lo:.3f} ({BASE_SPREAD_BPS * lo:.2f} bps) — "
          f"the spread at which the edge is fully consumed")

    # ---- per-leg flip points ------------------------------------------------------- #
    print(f"\nper-leg robustness (largest m at which the leg still PASSES):")
    flip = {}
    for name in rows[0]["legs"]:
        ok = [r["m"] for r in rows if r["legs"][name]]
        flip[name] = max(ok) if ok else None
        print(f"  {name:<22} {'none' if not ok else f'm <= {max(ok):.1f}'}"
              f"{'   (robust to 10x)' if ok and max(ok) >= 10.0 else ''}")

    out = {"base_spread_bps": BASE_SPREAD_BPS, "null_reps": a.reps,
           "null_seed": NULL_SEED, "fidelity_ok": fid,
           "break_even_m": lo, "break_even_bps": BASE_SPREAD_BPS * lo,
           "m_at_m1_total": sum(rs), "flip": flip,
           "rows": [{k: v for k, v in r.items() if k != "legs"} |
                    {"legs": r["legs"]} for r in rows],
           "generated": datetime.now(timezone.utc).isoformat()}
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {p.relative_to(ROOT)}")
    return 0 if fid else 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
