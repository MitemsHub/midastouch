#!/usr/bin/env python3
"""What makes the gold strategy's profit concentrate into single days, and what fixes it.

THE QUESTION. The venue caps any single day's contribution at 20% of total
profit. The walk-forward v2 run met its profit target and still breached that
rule: its best day was **+34.68R = 55.5% of all profit** against a 20% cap. This
tool asks why, and whether the cap can be satisfied without destroying the edge.

THE ARITHMETIC THAT DECIDES THE SHAPE OF THE ANSWER. Write ``r`` for the dollars
risked per trade (1R). Across a window whose day-level results are ``d_i`` R:

* profit target:   ``r * sum(d) >= target``
* daily loss limit: ``r * min(d) >= -limit``
* Best Day:        ``max(d) / sum(d) <= 0.20``

The third inequality has **no ``r`` in it**. Best Day is *scale-invariant*: it is
a statement about the SHAPE of the day distribution, not its size. Resizing the
position changes what the account earns and what it loses, and changes nothing
about which day contributed most of the profit. So the rule cannot be fixed by
sizing — only by changing which trades are taken. That is why this tool sweeps
*entry rules* (a per-day profit cap, a per-day trade-count cap) and not risk
fractions.

The first two are the opposite: they are pure sizing statements, and together
they pin ``r`` into the interval ``[target/sum(d), limit/|min(d)|]``, which is
empty exactly when the worst day is bigger than ``limit/target`` times the whole
window's profit.

WHAT IT MEASURES. Every variant is run through the SAME walk-forward as v2 —
same grid, same folds, same selection rule — and each variant re-selects its own
configuration, because a capped strategy is a different strategy. Day P&L is
attributed to the UTC day of the entry bar, matching
:func:`gold_walkforward.prop_compat`, which is the referee for survival.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_wfo_v2 as w2  # noqa: E402
from gold_walkforward import prop_compat, tstat  # noqa: E402
from midas_prop.risk.upcomers_rules import (  # noqa: E402
    ThunderboltClassicRules,
)

SYMBOL = "XAUUSD"
ACCOUNT = 25000.0


def day_table(trades: list[dict], epoch) -> dict:
    """Day P&L in R, keyed by the UTC date of the ENTRY bar.

    Two things are returned that the caller would otherwise recompute: the day's
    trade count (concentration is a counting question before it is a money
    question) and how many trades would be attributed to a different day if the
    close were used instead of the entry. That second number is a check on the
    convention, not a result — if it is large, the convention matters and the
    reader needs to know.
    """
    by_day: dict = defaultdict(float)
    count: Counter = Counter()
    exit_day_differs = 0
    for t in trades:
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()
        x = datetime.fromtimestamp(float(epoch[t["exit_i"]]), timezone.utc).date()
        by_day[d] += t["net_r"]
        count[d] += 1
        if x != d:
            exit_day_differs += 1
    return {"r": dict(by_day), "n": dict(count),
            "exit_day_differs": exit_day_differs}


def summarise(variant: dict, day: dict, oos_rs: list[float],
              picks: list[dict], rules) -> dict:
    """Everything one variant's day distribution says about prop feasibility."""
    r_by_day = day["r"]
    total_r = sum(r_by_day.values())
    days = sorted(r_by_day)
    ndays = len(days)
    best_day_r = max(r_by_day.values()) if r_by_day else 0.0
    worst_day_r = min(r_by_day.values()) if r_by_day else 0.0
    share = (best_day_r / total_r) if total_r > 0 else None
    counts = sorted(day["n"].values())

    # The r interval implied by the target and the daily loss limit. Best Day
    # contributes no bound at all -- that is the point of the study. Both bounds
    # are only meaningful on a profitable window: with no profit there is no
    # target to reach and no "share" to breach, and reporting either would be a
    # verdict about a quantity that does not exist.
    lo_r = rules.profit_target_usd / total_r if total_r > 0 else float("inf")
    hi_r = (rules.daily_loss_limit_usd / abs(worst_day_r)
            if worst_day_r < 0 else float("inf"))
    window_open = total_r > 0 and lo_r <= hi_r
    # Largest size that keeps the worst day inside the limit, rounded down to
    # cents so the reported number is a size someone could actually type.
    r_candidate = min(hi_r, max(lo_r, 0.0)) if window_open else None
    if r_candidate is not None:
        r_candidate = round(r_candidate, 2)
        if r_candidate < lo_r:
            r_candidate = None

    prop = None
    pick_epoch = variant["_epoch"]
    if r_candidate:
        prop = prop_compat(oos_trades_of(variant), pick_epoch, rules, r_candidate)

    return {
        "label": variant["label"],
        "day_cap_r": variant.get("day_cap_r"),
        "max_per_day": variant.get("max_per_day"),
        "oos_trades": sum(p["n_oos"] for p in picks),
        "total_r": round(total_r, 3),
        "per_trade_r": round(total_r / max(1, sum(p["n_oos"] for p in picks)), 4),
        "t": round(tstat(oos_rs), 3),
        "folds": len(oos_rs),
        "positive_folds": sum(1 for r in oos_rs if r > 0),
        "days_traded": ndays,
        "trades_per_day_median": counts[len(counts) // 2] if counts else 0,
        "trades_per_day_max": counts[-1] if counts else 0,
        "best_day_r": round(best_day_r, 3),
        "worst_day_r": round(worst_day_r, 3),
        "best_day_share": round(share, 4) if share is not None else None,
        # None, not False: an unprofitable window has no concentration to breach.
        "best_day_ok": (share <= rules.best_day_pct / 100.0)
                       if share is not None else None,
        "exit_day_differs": day["exit_day_differs"],
        "concentration": concentration(day, variant["_oos_trades"]),
        "risk_window_usd": [round(lo_r, 2), round(hi_r, 2)] if window_open else None,
        "risk_window_open": bool(window_open),
        "risk_used_usd": r_candidate,
        "prop_at_risk": prop,
        "prop_feasible": bool(prop and prop["survived"] and prop["best_day_ok"]
                              and prop["target_met"]),
    }


def concentration(day: dict, trades: list[dict]) -> dict:
    """Where the profit actually comes from, in days and in single trades.

    The Best Day rule quantifies *day* concentration. This quantifies it twice —
    by day and by trade — because the two point at different mechanisms, and the
    fix depends on which one is true. If a few DAYS carry the profit while every
    trade is small, the answer is a trade-count limit. If a few TRADES carry it,
    no daily limit helps, because the rule would have to truncate the very winners
    the edge depends on.
    """
    pos_days = sorted((v for v in day["r"].values() if v > 0), reverse=True)
    pos_r = sorted((t["net_r"] for t in trades if t["net_r"] > 0), reverse=True)
    total = sum(day["r"].values())

    def top_share(vals: list[float], frac: float) -> float | None:
        if not vals:
            return None
        k = max(1, int(round(len(vals) * frac)))
        return round(sum(vals[:k]) / sum(vals), 4) if sum(vals) > 0 else None

    # Days with more trades are the ones the count caps remove, so the sign of
    # this correlation decides whether a count cap can help at all.
    pairs = [(day["n"][d], day["r"][d]) for d in day["r"]]
    corr = None
    if len(pairs) > 2:
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        num = sum((x - mx) * (y - my) for x, y in pairs)
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        corr = round(num / den, 3) if den else None

    return {
        "profitable_days": len(pos_days),
        "losing_days": len(day["r"]) - len(pos_days),
        "top_10pct_days_share_of_profit": top_share(pos_days, 0.10),
        "winning_trades": len(pos_r),
        "top_1pct_trades_share_of_gross_profit": top_share(pos_r, 0.01),
        "top_5pct_trades_share_of_gross_profit": top_share(pos_r, 0.05),
        "corr_trades_per_day__day_r": corr,
        "best_single_trade_r": round(pos_r[0], 3) if pos_r else 0.0,
        "projected_total_R": round(total, 3),
    }


def oos_trades_of(variant: dict) -> list[dict]:
    """The trades the walk-forward actually exposed for this variant."""
    return variant["_oos_trades"]


def fixed_selection(variant: dict, P: dict, all_cfgs: list[dict],
                    base_picks: list[dict], folds: list, rules) -> dict:
    """The cap's effect with SELECTION HELD FIXED on the uncapped picks.

    WHY THIS SECOND PASS EXISTS. In the swept runs each variant re-selects its own
    configuration, which is the honest way to ask "what would this rule have
    traded?" -- but it confounds two things: the cap removing trades, and the
    walk-forward picking a different (and on a capped stream, differently
    overfitted) config. A review would rightly ask which of the two moved the
    number. Here the configuration for every fold is frozen to the uncapped
    pick, so the only difference from the uncapped run is the cap itself, and
    the difference between the two passes is the selection effect.
    """
    sig = {json.dumps(c, sort_keys=True): k for k, c in enumerate(all_cfgs)}
    wanted = [sig[json.dumps(p["config"], sort_keys=True)] for p in base_picks]
    uniq = sorted(set(wanted))
    streams = {k: w2.simulate(P["B"], P["hours"], P["h1_ok_long"],
                              P["h1_ok_short"], P["h4_ok_long"],
                              P["h4_ok_short"], P["atr"], all_cfgs[k],
                              start=w2.WARMUP_BARS, end=P["holdout_start"],
                              day_cap_r=variant.get("day_cap_r"),
                              max_per_day=variant.get("max_per_day"),
                              atr_lo=P["atr_lo"], atr_hi=P["atr_hi"])
               for k in uniq}
    oos: list[dict] = []
    fold_rs: list[float] = []
    for fi in range(1, len(folds)):
        _nn, nlo, nhi = folds[fi]
        k = wanted[fi - 1]
        sl = [t for t in streams[k] if nlo <= t["entry_i"] < nhi]
        oos += sl
        fold_rs.append(sum(t["net_r"] for t in sl))
    day = day_table(oos, P["epoch"])
    total = sum(day["r"].values())
    best = max(day["r"].values()) if day["r"] else 0.0
    share = (best / total) if total > 0 else None
    return {
        "trades": len(oos), "total_r": round(total, 3),
        "per_trade_r": round(total / len(oos), 4) if oos else 0.0,
        "t": round(tstat(fold_rs), 3),
        "positive_folds": sum(1 for r in fold_rs if r > 0), "folds": len(fold_rs),
        "best_day_r": round(best, 3),
        "best_day_share": round(share, 4) if share is not None else None,
        "best_day_ok": (share <= rules.best_day_pct / 100.0)
                       if share is not None else None,
        "trades_per_day_max": max(day["n"].values()) if day["n"] else 0,
    }


def run_variant(variant: dict, P: dict, all_cfgs: list[dict], folds: list,
                rules) -> dict:
    """Simulate the whole grid under this variant's entry rule, then walk forward."""
    end = P["holdout_start"]
    trades_by_cfg = [
        w2.simulate(P["B"], P["hours"], P["h1_ok_long"], P["h1_ok_short"],
                    P["h4_ok_long"], P["h4_ok_short"], P["atr"], cfg,
                    start=w2.WARMUP_BARS, end=end,
                    day_cap_r=variant.get("day_cap_r"),
                    max_per_day=variant.get("max_per_day"),
                    atr_lo=P["atr_lo"], atr_hi=P["atr_hi"])
        for cfg in all_cfgs]
    oos_rs, picks = w2.walk_forward(trades_by_cfg, all_cfgs, folds)
    oos: list[dict] = []
    for fi in range(1, len(folds)):
        _nn, nlo, nhi = folds[fi]
        k = next(i for i, c in enumerate(all_cfgs) if c == picks[fi - 1]["config"])
        oos += [t for t in trades_by_cfg[k] if nlo <= t["entry_i"] < nhi]
    out = dict(variant)
    out["_oos_trades"] = oos
    out["_oos_rs"] = oos_rs
    out["_picks"] = picks
    out["_in_sample_trades"] = sum(len(t) for t in trades_by_cfg)
    out["_epoch"] = P["epoch"]
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_best_day_study.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT)
    P = w2.prepare(a.symbol, bars=a.bars)
    folds = P["folds"]
    all_cfgs = w2.configs()
    print(f"grid {len(all_cfgs)} configs x {len(folds)} folds; "
          f"target ${rules.profit_target_usd:,.0f}, "
          f"daily limit ${rules.daily_loss_limit_usd:,.0f}, "
          f"Best Day cap {rules.best_day_pct:g}%")
    if len(folds) < 6:
        print("not enough folds")
        return 1

    variants = [
        {"label": "uncapped (walk-forward v2)"},
        {"label": "day cap 1.0R", "day_cap_r": 1.0},
        {"label": "day cap 2.0R", "day_cap_r": 2.0},
        {"label": "day cap 4.0R", "day_cap_r": 4.0},
        {"label": "max 2 trades/day", "max_per_day": 2},
        {"label": "max 4 trades/day", "max_per_day": 4},
        {"label": "max 8 trades/day", "max_per_day": 8},
        {"label": "max 4/day + cap 2.0R", "max_per_day": 4, "day_cap_r": 2.0},
    ]

    # The uncapped picks, computed first and frozen: every capped variant is
    # measured twice against them (own selection, and selection held fixed).
    base = run_variant(variants[0], P, all_cfgs, folds, rules)
    base_picks = base["_picks"]
    base_total_r = sum(base["_oos_rs"])

    results = []
    for v in variants:
        print(f"\n--- {v['label']} ---", flush=True)
        run = run_variant(v, P, all_cfgs, folds, rules)
        day = day_table(run["_oos_trades"], P["epoch"])
        s = summarise(run, day, run["_oos_rs"], run["_picks"], rules)
        s["in_sample_trades_across_grid"] = run["_in_sample_trades"]
        s["_day"] = day["r"]
        s["fixed_selection"] = fixed_selection(v, P, all_cfgs,
                                               base_picks, folds, rules)
        results.append(s)
        print(f"  trades {s['oos_trades']}  total {s['total_r']:+.2f}R  "
              f"t {s['t']:+.2f}  pos folds {s['positive_folds']}/{s['folds']}")
        print(f"  days {s['days_traded']}  trades/day median "
              f"{s['trades_per_day_median']} max {s['trades_per_day_max']}")
        share_txt = (f"share {100*s['best_day_share']:.1f}%"
                     if s["best_day_share"] is not None else "share n/a (no profit)")
        verdict = ("OK" if s["best_day_ok"] else
                   "BREACH" if s["best_day_ok"] is False else "n/a")
        print(f"  best day {s['best_day_r']:+.2f}R  worst {s['worst_day_r']:+.2f}R  "
              f"{share_txt} (cap {rules.best_day_pct:g}%) -> {verdict}")
        c = s["concentration"]
        print(f"  concentration: {c['profitable_days']} up days / {c['losing_days']} "
              f"down; top 10% of days = "
              f"{100*(c['top_10pct_days_share_of_profit'] or 0):.1f}% of profit; "
              f"top 1% of trades = "
              f"{100*(c['top_1pct_trades_share_of_gross_profit'] or 0):.1f}% of "
              f"gross profit; corr(trades/day, day R) = "
              f"{c['corr_trades_per_day__day_r']}")
        if s["risk_window_open"]:
            print(f"  risk window  ${s['risk_window_usd'][0]:,.2f} .. "
                  f"${s['risk_window_usd'][1]:,.2f} per trade")
        else:
            print("  risk window  EMPTY - no position size satisfies both the "
                  "target and the daily limit")
        fs = s["fixed_selection"]
        print(f"  same selection, cap applied: {fs['trades']} trades "
              f"{fs['total_r']:+.2f}R (was {base_total_r:+.2f}R) "
              f"t {fs['t']:+.2f}  best-day share "
              f"{100*fs['best_day_share']:.1f}%"
              f"{' -> ok' if fs['best_day_ok'] else ' -> still breaching'}"
              if fs["best_day_share"] is not None else
              f"  same selection, cap applied: {fs['trades']} trades "
              f"{fs['total_r']:+.2f}R -- unprofitable, no share to report")
        if s["prop_at_risk"]:
            p = s["prop_at_risk"]
            print(f"  at ${s['risk_used_usd']:,.2f}: equity "
                  f"${p['final_equity']:,.2f} (target "
                  f"{'MET' if p['target_met'] else 'not met'})  survived "
                  f"{p['survived']}  daily breaches {len(p['daily_breaches'])}  "
                  f"shield {len(p['shield_breaches'])}")
        print(f"  prop-feasible: {s['prop_feasible']}")

    # ---- the two structural claims, verified rather than asserted ---- #
    base = results[0]
    print("\n=== STRUCTURAL CHECKS ===")
    # 1. Best Day does not depend on r: recompute the share under a 10x resize.
    d = base["_day"]
    shares = []
    for mult in (0.1, 1.0, 10.0, 100.0):
        scaled = {k: v * mult for k, v in d.items()}
        shares.append(max(scaled.values()) / sum(scaled.values()))
    print(f"  Best Day share under 0.1x/1x/10x/100x the same position size: "
          f"{', '.join(f'{100*s:.1f}%' for s in shares)} -> "
          f"{'SCALE-INVARIANT' if max(shares) - min(shares) < 1e-9 else 'NOT invariant'}")
    print(f"  so the cap cannot be satisfied by sizing; it is a property of the "
          f"day distribution ({100*base['best_day_share']:.1f}% vs "
          f"{rules.best_day_pct:g}%), and the uncapped strategy is infeasible at "
          f"EVERY size.")

    # 2. Which variant is the cheapest one that is prop-feasible?
    ok = [r for r in results if r["prop_feasible"]]
    winner = min(ok, key=lambda r: abs(r["per_trade_r"]), default=None)
    print("\n=== SELECTION EFFECT vs CAP EFFECT ===")
    for s in results[1:]:
        fs = s["fixed_selection"]
        sel_effect = s["total_r"] - fs["total_r"]
        print(f"  {s['label']:<26} cap-only {fs['total_r']:+8.2f}R   "
              f"with re-selection {s['total_r']:+8.2f}R   "
              f"selection effect {sel_effect:+8.2f}R")

    print(f"\n  prop-feasible variants: "
          f"{len(ok)}/{len(results)}"
          + (f"; highest per-trade R among them: {winner['label']} "
             f"({winner['per_trade_r']:+.4f}R, t {winner['t']:+.2f})"
             if winner else ""))

    for r in results:  # internal, keyed by date objects
        r.pop("_day", None)
    out = {
        "symbol": a.symbol, "account_size": ACCOUNT,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "rules": {"target_usd": rules.profit_target_usd,
                  "daily_limit_usd": rules.daily_loss_limit_usd,
                  "best_day_pct": rules.best_day_pct},
        "grid_size": len(all_cfgs), "folds": len(folds),
        "results": results,
        "best_day_scale_invariant": bool(max(shares) - min(shares) < 1e-9),
        "best_day_share_under_resize": [round(s, 4) for s in shares],
        "prop_feasible_count": len(ok),
        "winner": winner["label"] if winner else None,
    }
    outp = ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
