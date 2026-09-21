#!/usr/bin/env python3
"""The exit-family walk-forward, and what a hard 3% daily switch costs.

TWO MEASUREMENTS, one harness.

**`--mode exitfamily`** — the frozen walk-forward re-run with the EXIT as a declared grid
axis instead of a constant. The certified grid holds the exit at stop 1.0 x ATR / target
2.0R (1.5-3.0R across configs) and sweeps entries; the exit study measured that the target
captures 2.6% of the post-signal excursion while an uncapped exit captures 28.6%
(`docs/GOLD_EXIT_CAPTURE_AND_FILTERS_20260921.md`). This asks the question that follows:
with the exit free, does any fold selection clear the frozen gate? Declaration, with the
grid and the pass criteria fixed before the run:
`docs/GOLD_PREREG_EXIT_FAMILY_20260921.md`.

**`--mode hardday`** — a governor that behaves the way a prop desk actually does at the
line: when the day's loss reaches the 3% floor, the open position is FLATTENED at that
mark and the arm stands down for the rest of the UTC day. The entry-only governor (the one
on the chart) only refuses new entries, and the path governor in
`scripts/gold_governed_wfo.py` marks the same exit but keeps trading. This measures what
standing down costs in R and whether the daily rule then stops being breached.

Both modes are exploration unless the walk-forward's own OOS folds say otherwise: the folds
are the protocol's out-of-sample unit (selected on fold k, scored on fold k+1), so
`--mode exitfamily` is a genuine test of the declared grid, while `--mode hardday` is a
measurement of a risk rule on the same window and is labelled as such.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_governed_wfo as gg  # noqa: E402
import gold_walkforward as gw  # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

ACCOUNT_SIZE = 25_000.0
RISK_USD = 250.0
EA_TIMEOUT_BARS = 48          # InpTimeoutMinutes = 720

#: The declared exit arms (see the pre-registration). `tp_mult=None` is the no-target arm,
#: and it appears BOTH ways on purpose: the engine's own convention (hold to stop or the
#: 22:00 flat) and the EA's (720-minute timeout = 48 bars).
EXIT_ARMS = (
    ("tp1.5", {"tp_mult": 1.5}),
    ("tp2.0", {"tp_mult": 2.0}),
    ("tp3.0", {"tp_mult": 3.0}),
    ("noTarget-hold", {"tp_mult": None}),
    ("noTarget-48b", {"tp_mult": None, "max_bars": EA_TIMEOUT_BARS}),
    ("trail1.0/0.5-48b", {"tp_mult": None, "trail": (1.0, 0.5),
                          "max_bars": EA_TIMEOUT_BARS}),
)


def exit_grid() -> list[dict]:
    """The declared grid: 2 trend sets x 2 sessions x 2 stops x 6 exit arms = 48."""
    out = []
    for emas in gw.EMA_SETS:
        for (lo, hi) in gw.WINDOWS:
            for sm in gw.STOP_MULTS:
                for name, rule in EXIT_ARMS:
                    out.append({"emas": emas, "stop_mult": sm, "win_lo": lo, "win_hi": hi,
                                "exit_arm": name, "exit_rule": rule})
    return out


def run_one(B, hours, ok, atr, cfg: dict, n: int) -> list[dict]:
    return gw.simulate(B, hours, ok["h1_long"], ok["h1_short"], ok["h4_long"],
                       ok["h4_short"], atr, cfg, start=gw.WARMUP_BARS, end=n,
                       exit_rule=cfg.get("exit_rule"))


def exit_family(args, B, epoch, n, atr, hours, ok, rules) -> dict:
    folds = gw.build_folds(epoch)
    grid = exit_grid()
    governed: list[dict[int, float]] = [dict() for _ in grid]
    counts: list[dict[int, int]] = [dict() for _ in grid]
    raw_by_cfg: list[list[dict]] = []
    for k, cfg in enumerate(grid):
        raw = run_one(B, hours, ok, atr, cfg, n)
        raw_by_cfg.append(raw)
        for fi, (_nm, lo, hi) in enumerate(folds):
            inside = [t for t in raw if lo <= t["entry_i"] < hi]
            kept, _v = gg.govern(inside, epoch, rules=rules)
            governed[k][fi] = sum(t["net_r"] for t in kept)
            counts[k][fi] = len(kept)

    oos_rs: list[float] = []
    picks: list[dict] = []
    prev = max(range(len(grid)),
               key=lambda k: sum(t["net_r"] for t in raw_by_cfg[k]))
    for fi in range(1, len(folds)):
        scored = []
        for k in range(len(grid)):
            c = grid[k]
            # Tie-breaks declared in the pre-registration: worse-case stop first, then the
            # exit arm's declared order, then the grid index.
            arm_rank = next(i for i, (nm, _r) in enumerate(EXIT_ARMS)
                            if nm == c["exit_arm"])
            scored.append((governed[k][fi - 1], -c["stop_mult"], -arm_rank, -k, k))
        scored.sort(reverse=True)
        if scored[0][0] != 0.0:
            prev = scored[0][4]
        pick = prev
        oos_rs.append(governed[pick][fi])
        picks.append({"fold": folds[fi][0], "selected_on": folds[fi - 1][0],
                      "config": {kk: v for kk, v in grid[pick].items()
                                 if kk != "exit_rule"},
                      "oos_r": round(governed[pick][fi], 4),
                      "oos_trades": counts[pick][fi]})

    n_oos = sum(p["oos_trades"] for p in picks)
    oos_detail: list[dict] = []
    for fi in range(1, len(folds)):
        _nm, nlo, nhi = folds[fi]
        k = next(i for i, c in enumerate(grid)
                 if all(c.get(kk) == vv for kk, vv in picks[fi - 1]["config"].items()))
        inside = [t for t in raw_by_cfg[k] if nlo <= t["entry_i"] < nhi]
        kept, _v = gg.govern(inside, epoch, rules=rules)
        for t in kept:
            oos_detail.append({"fold": folds[fi][0], "entry_i": t["entry_i"],
                               "dir": t["dir"], "net_r": t["net_r"]})

    totals = []
    for rep in range(args.control_reps):
        tot = 0.0
        for fi in range(1, len(folds)):
            k = next(i for i, c in enumerate(grid)
                     if all(c.get(kk) == vv for kk, vv in picks[fi - 1]["config"].items()))
            _nm, nlo, nhi = folds[fi]
            tot += sum(t["net_r"] for t in gw.random_control(
                B, hours, atr, counts[k][fi], grid[k], start=nlo, end=nhi,
                seed=gw.CONTROL_SEED + rep * 1000 + fi,
                exit_rule=grid[k].get("exit_rule")))
        totals.append(tot)
    control_total = float(np.mean(totals)) if totals else 0.0
    checks = gw.criteria(oos_rs, control_total)
    prop = gw.prop_compat(oos_detail, epoch, rules, RISK_USD)
    flags = " ".join(f"[{'P' if v else 'F'}]{k.split()[0]}"
                     for k, v in checks.items() if k.startswith("V"))
    ok_all = all(v for k, v in checks.items() if k.startswith("V"))

    print(f"\n== exit-family walk-forward: {len(grid)} configs, {len(oos_rs)} OOS folds ==")
    for p in picks[:12]:
        c = p["config"]
        print(f"  {p['fold']} (picked on {p['selected_on']}): {c['exit_arm']:<17} "
              f"stop={c['stop_mult']} emas={c['emas']} win={c['win_lo']}-{c['win_hi']}"
              f"  -> {p['oos_r']:+7.2f}R  ({p['oos_trades']})")
    if len(picks) > 12:
        print(f"  ... {len(picks) - 12} more folds")
    arm_use: dict[str, int] = {}
    for p in picks:
        arm_use[p["config"]["exit_arm"]] = arm_use.get(p["config"]["exit_arm"], 0) + 1
    print(f"\nwhich exit arm the selection chose, by fold count: {arm_use}")
    print(f"OOS trades={n_oos} total={sum(oos_rs):+.2f}R mean={np.mean(oos_rs):+.3f}R/fold "
          f"t={checks['_t']:+.2f} control={control_total:+.2f}R")
    print(f"  {flags}  -> {'PROVISIONAL EDGE' if ok_all else 'NOT VALIDATED'} "
          f"(fails: {[k for k, v in checks.items() if k.startswith('V') and not v]})")
    print(f"  venue rules: worst day {prop['worst_day_r']:+.2f}R "
          f"({prop['worst_day_usd']:+,.0f} vs ${prop['daily_limit_usd']:,.0f}) | shield/daily "
          f"breaches {len(prop['shield_breaches'])}/{len(prop['daily_breaches'])} -> "
          f"{'SURVIVED' if prop['survived'] else 'BREACHED'}")
    return {"grid_size": len(grid), "exit_arms": [nm for nm, _r in EXIT_ARMS],
            "oos_r_per_fold": [round(x, 4) for x in oos_rs], "picks": picks,
            "arm_use": arm_use, "oos_trades": n_oos,
            "checks": {k: bool(v) for k, v in checks.items() if k.startswith("V")},
            "stats": {k: checks[k] for k in checks if k.startswith("_")},
            "control_total_r": round(control_total, 4), "prop_compat": prop,
            "verdict": "PROVISIONAL EDGE" if ok_all else "NOT VALIDATED"}


# --------------------------------------------------------------------------- #
# The hard daily switch: flatten at the line, then stand down for the day
# --------------------------------------------------------------------------- #

def govern_hardday(trades: list[dict], epoch: np.ndarray, *, rules, bars: dict,
                   risk_usd: float = RISK_USD) -> tuple[list[dict], dict]:
    """Flatten the open trade AT the 3% line and stop trading until the next UTC day.

    Differences from every other governor measured here, and they are the point:

      * `govern()` (on the chart) refuses a new entry once the day's loss is realised;
      * `govern_path()` (`gold_governed_wfo.py`) exits the open trade when the mark crosses
        the line but may enter again the same day;
      * this one exits AND stands down for the rest of the UTC day, which is the behaviour
        a prop desk actually implements.
    """
    close = bars["close"]
    daily_limit = rules.daily_loss_limit_usd
    equity = rules.account_size
    peak = rules.account_size
    day = None
    day_pnl = 0.0
    stood_down = False
    kept: list[dict] = []
    stats = {"switch_fires": 0, "days_stood_down": 0, "entries_refused": 0}
    seen_days: set = set()
    entry_fill = close

    for t in sorted(trades, key=lambda x: x["entry_i"]):
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()
        if d != day:
            day = d
            day_pnl = 0.0
            stood_down = False
        if stood_down:
            stats["entries_refused"] += 1
            continue
        if (day_pnl - 1.0) * risk_usd <= -daily_limit:
            stats["entries_refused"] += 1
            continue
        if equity <= rules.drawdown_floor_usd(peak):
            stats["entries_refused"] += 1
            continue

        r = t["net_r"]
        # Walk the trade's own bars: the moment the DAY's marked result touches the line,
        # flatten at that bar's close and stand down.
        risk_price = gg._risk_price(t)
        if risk_price:
            for j in range(t["entry_i"] + 1, int(t["exit_i"]) + 1):
                floating = t["dir"] * (float(entry_fill[j]) - t["entry"]) / risk_price
                if (day_pnl + floating) * risk_usd <= -daily_limit:
                    r = floating
                    stood_down = True
                    stats["switch_fires"] += 1
                    seen_days.add(str(d))
                    break
        kept.append(dict(t, net_r=r, stood_down=stood_down))
        day_pnl += r
        equity += r * risk_usd
        peak = max(peak, equity)
    stats["days_stood_down"] = len(seen_days)
    return kept, stats


def hardday(args, B, epoch, n, atr, hours, ok, rules) -> dict:
    """Compare the three governor policies on the CERTIFIED 24-config grid, fold by fold."""
    folds = gw.build_folds(epoch)
    grid = gw.configs()
    policies = [("entry-only (on the chart)", gg.govern),
                ("path (mark + keep trading)", functools.partial(gg.govern_path, bars=B)),
                ("hard 3% (flatten + stand down)", functools.partial(govern_hardday, bars=B))]
    out: dict = {}
    for label, gov in policies:
        oos_rs: list[float] = []
        detail: list[dict] = []
        stats_all: dict[str, int] = {}
        trades_by_cfg = [run_one(B, hours, ok, atr, c, n) for c in grid]
        for fi in range(1, len(folds)):
            _nm, nlo, nhi = folds[fi]
            best_r, best_k = None, None
            for k, raw in enumerate(trades_by_cfg):
                _pn, plo, phi = folds[fi - 1]
                prev_inside = [t for t in raw if plo <= t["entry_i"] < phi]
                got, st = gov(prev_inside, epoch, rules=rules)
                for kk, vv in st.items():
                    if isinstance(vv, int):
                        stats_all[kk] = stats_all.get(kk, 0) + vv
                tot = sum(t["net_r"] for t in got)
                if best_r is None or tot > best_r:
                    best_r, best_k = tot, k
            inside = [t for t in trades_by_cfg[best_k] if nlo <= t["entry_i"] < nhi]
            kept, st = gov(inside, epoch, rules=rules)
            for kk, vv in st.items():
                if isinstance(vv, int):
                    stats_all[kk] = stats_all.get(kk, 0) + vv
            oos_rs.append(sum(t["net_r"] for t in kept))
            detail.extend({"fold": folds[fi][0], "entry_i": t["entry_i"],
                           "dir": t["dir"], "net_r": t["net_r"]} for t in kept)
        prop = gw.prop_compat(detail, epoch, rules, RISK_USD)
        st = gg.trade_stats(detail)
        out[label] = {"total_r": round(sum(oos_rs), 2), "folds_positive":
                      sum(1 for x in oos_rs if x > 0), "folds": len(oos_rs),
                      "trades": st["n"], "mean_r": st["mean_r"], "t": st["t"],
                      "prop_compat": prop, "switch_stats": stats_all}
        print(f"\n  {label}:")
        print(f"    total {out[label]['total_r']:+.2f}R over {st['n']} OOS trades | "
              f"folds positive {out[label]['folds_positive']}/{out[label]['folds']} | "
              f"final equity ${prop['final_equity']:,.2f}")
        print(f"    worst day {prop['worst_day_r']:+.2f}R = ${prop['worst_day_usd']:,.0f} vs "
              f"${prop['daily_limit_usd']:,.0f} | shield/daily breaches "
              f"{len(prop['shield_breaches'])}/{len(prop['daily_breaches'])} -> "
              f"{'SURVIVED' if prop['survived'] else 'BREACHED'}")
        if stats_all:
            print(f"    switch: {stats_all}")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--mode", choices=("exitfamily", "hardday", "both"), default="both")
    ap.add_argument("--control-reps", type=int, default=200)
    ap.add_argument("--out", default="artifacts/gold_exit_family_wfo.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT_SIZE)
    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    print(f"{a.symbol} {gw.EXEC_TF} {n} bars (the venue's served window) | "
          f"1R = ${RISK_USD:.0f} on ${ACCOUNT_SIZE:,.0f} | "
          f"governor: the entry-only mirror of PropGovernorBlock() unless stated")

    out: dict = {"spec": {"symbol": a.symbol, "bars": n,
                          "window": [str(datetime.fromtimestamp(epoch[0], timezone.utc)),
                                     str(datetime.fromtimestamp(epoch[-1], timezone.utc))],
                          "account_size": ACCOUNT_SIZE, "risk_usd": RISK_USD,
                          "exit_arms": [{"name": nm, "rule": {k: str(v) for k, v in r.items()}}
                                        for nm, r in EXIT_ARMS],
                          "declaration": "docs/GOLD_PREREG_EXIT_FAMILY_20260921.md",
                          "exit_engine": "gold_walkforward.simulate(..., exit_rule=...)"}}
    if a.mode in ("exitfamily", "both"):
        out["exit_family"] = exit_family(a, B, epoch, n, atr, hours, ok, rules)
    if a.mode in ("hardday", "both"):
        out["hard_day"] = hardday(a, B, epoch, n, atr, hours, ok, rules)
    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    # MERGE, don't overwrite: the two modes are separate runs (the sweep is minutes each)
    # and a second invocation must not erase the first one's evidence.
    if dest.exists():
        try:
            prior = json.loads(dest.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                prior.update(out)
                out = prior
        except (OSError, ValueError):
            pass
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nartifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
