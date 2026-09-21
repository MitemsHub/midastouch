#!/usr/bin/env python3
"""Governed walk-forward and geometry sweep — the EA's own refusals inside the test.

WHY THIS EXISTS. `docs/GOLD_ARMING_DECISION_20260921.md` recorded the live arm on an
operator override and named the one number nobody had measured: *"the replay that reaches
the 5% target puts 80.6% of the profit in one day, against the venue's 20% Best Day cap.
The governor gates ENTRIES to prevent exactly that; its effect on that window has NOT been
measured."* This measures it, and it answers the sharper question the override left open:
**does any configuration still clear the frozen gate once the EA's own refusals are part
of the strategy rather than a post-hoc badge on top of it?**

THE GOVERNOR IS THE EA'S, NOT A RESTATEMENT. `govern()` mirrors `PropGovernorBlock()` in
`mql5/MIDASTOUCH/MidastouchAI.mq5` line for line: the 3% daily-loss breaker, the 6%
trailing shield via `drawdown_floor_usd` (the clamped floor, not a raw drawdown), and the
Best Day cap `target_pct * best_day_pct = 0.05 * 0.20 = 1% of size = 1R per UTC day`. A
walk-forward that invents its own risk rule measures a different strategy than the one on
the chart, which is the failure this repository keeps paying for.

TWO DECLARED APPROXIMATIONS, stated because they are the only places the replay is not the
EA. (1) The EA evaluates the governor against **floating** equity on every tick; the
replay evaluates it against **realised** equity at the entry bar. (2) The EA's day anchor
is a per-tick equity snapshot; the replay re-anchors at the first entry of each UTC day.
Both make the replay's governor slightly *laxer* than the EA's on a winning day, so the
governed numbers here are an upper bound on what the chart would have taken.

WHAT IS EXPLORATION AND WHAT IS A TEST, kept apart on purpose:

  * `--mode governed` — the pre-registered amendment: the frozen 24-configuration grid,
    the frozen folds, selection on the GOVERNED prior fold, scored on the governed next
    fold, evaluated against the frozen V1-V6 block. Decidable, and this is a test.
  * `--mode sweep` — 168 session/stop/target geometries scored on the SAME window. That is
    **exploration**: it re-uses the data the gate is judged on, so a winner here is a
    hypothesis, never a pass. It exists to answer "is there even a candidate big enough to
    be decidable?" and to size what a pre-registered test of it would need.
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

import gold_walkforward as gw  # noqa: E402 — the frozen engine and its grid
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402
from mt5_data import load_m5  # noqa: E402

ACCOUNT_SIZE = 25_000.0
RISK_USD = 250.0          # 1% of the account: the preset's declared risk
RISK_PCT = RISK_USD / ACCOUNT_SIZE

#: Exploration grid — session windows x stop geometry x target geometry x trend sets.
#: The frozen grid's own axes are a subset of this, which is deliberate: the sweep must be
#: able to reproduce the certified configurations, or a "better" variant would be an
#: artefact of a different simulator.
SWEEP_SESSIONS = ((5, 21), (6, 20), (7, 20), (8, 18), (12, 16), (13, 18), (14, 20))
SWEEP_STOPS = (1.0, 1.5, 2.0)
SWEEP_TPS = (1.5, 2.0, 2.5, 3.0)

#: The floor below which a "candidate" is not even worth a pre-registered test: the
#: decision says the armed configuration has to reach roughly +0.15R/trade to be
#: decidable at the gate's t >= 1.5 within a plausible forward record.
DECIDABLE_R = 0.15
DECIDABLE_N = 100


# --------------------------------------------------------------------------- #
# The governor (mirror of PropGovernorBlock; see the module docstring)
# --------------------------------------------------------------------------- #

def govern(trades: list[dict], epoch: np.ndarray, *, rules,
           risk_usd: float = RISK_USD) -> tuple[list[dict], dict]:
    """Apply the EA's governor to a trade list. Returns (kept, veto counts).

    Path-dependent by construction: whether an entry is allowed depends on the equity the
    account has accumulated, so the trades are walked in entry order and each accepted
    trade moves the equity the next decision sees.
    """
    cap_usd = rules.account_size * rules.profit_target_pct / 100.0 * rules.best_day_pct / 100.0
    equity = rules.account_size
    peak = rules.account_size
    day = None
    day_anchor = equity
    day_floor = equity - rules.daily_loss_limit_usd
    kept: list[dict] = []
    vetoes: dict[str, int] = {}

    def veto(reason: str) -> None:
        vetoes[reason] = vetoes.get(reason, 0) + 1

    for t in sorted(trades, key=lambda x: x["entry_i"]):
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()
        if d != day:
            day = d
            day_anchor = equity
            day_floor = equity - rules.daily_loss_limit_usd
        if equity <= day_floor:
            veto("daily-loss cap (3%)")
            continue
        if equity <= rules.drawdown_floor_usd(peak):
            veto("trailing shield (6%)")
            continue
        if (equity - day_anchor) >= cap_usd:
            veto("Best Day cap (1R/day)")
            continue
        kept.append(t)
        equity += t["net_r"] * risk_usd
        peak = max(peak, equity)
    return kept, vetoes


#: The soft-stop ladder: (band_lo, band_hi, risk_scale) in drawdown-from-peak terms.
#: Risk is RE-DERIVED from the band, so a worsening account gets smaller before it gets
#: near the shield floor instead of arriving there at full size.
LADDER = ((0.00, 0.02, 1.00), (0.02, 0.04, 0.50), (0.04, 0.06, 0.25), (0.06, 9.99, 0.00))


def ladder_scale(dd_frac: float) -> float:
    for lo, hi, scale in LADDER:
        if lo <= dd_frac < hi:
            return scale
    return 0.0


def govern_path(trades: list[dict], epoch: np.ndarray, *, rules, bars: dict | None = None,
                risk_usd: float = RISK_USD) -> tuple[list[dict], dict]:
    """A governor that protects the EQUITY PATH, not just the entry.

    The measured problem with the EA's `PropGovernorBlock()` is not that it is wrong, it
    is that it is one-sided: it can refuse to open a position and nothing else, so the
    equity that breached the daily floor or the shield floor was breached by a trade it
    had already allowed (`docs/GOLD_GOVERNED_WFO_20260921.md` section 3 — five daily and
    five shield breaches on the governed sequence). This models the other half:

      1. **Day-loss kill switch.** An entry is refused when one more full loss would reach
         the 3% line (`day_pnl - risk <= -daily_limit`), i.e. pre-empted rather than
         reacted to; and a position already OPEN when the day's loss touches the line is
         closed at that bar, with the remainder of its move charged to the day.
      2. **Soft-stop ladder.** The risk for each new entry is scaled by the drawdown band
         (`LADDER`), so the sequence de-risks as the account worsens instead of arriving at
         the shield at full size. Scaled risk is applied to the trade's R, which is exact
         for position sizing (R is size-independent) — no price path is needed for it.
      3. The trailing-shield floor and Best Day cap still apply, and the floor now also
         **exits** an open position that touches it rather than only blocking the next one.

    DECLARED APPROXIMATION: marks are bar CLOSES, so an intra-bar touch of the day line or
    the floor is detected one bar late. That makes this governor look slightly WORSE than
    an EA that checks every tick, which is the direction a risk study should err.
    """
    if bars is None:
        return govern(trades, epoch, rules=rules, risk_usd=risk_usd)
    close = bars["close"]
    cap_usd = rules.account_size * rules.profit_target_pct / 100.0 * rules.best_day_pct / 100.0
    daily_limit = rules.daily_loss_limit_usd
    equity = rules.account_size
    peak = rules.account_size
    day = None
    day_pnl = 0.0
    day_anchor = equity
    kept: list[dict] = []
    vetoes: dict[str, int] = {}
    path_exits = 0

    def veto(reason: str) -> None:
        vetoes[reason] = vetoes.get(reason, 0) + 1

    for t in sorted(trades, key=lambda x: x["entry_i"]):
        d = datetime.fromtimestamp(float(epoch[t["entry_i"]]), timezone.utc).date()
        if d != day:
            day = d
            day_pnl = 0.0
            day_anchor = equity
        scale = ladder_scale((peak - equity) / rules.account_size)
        if scale <= 0.0:
            veto("ladder: flat at >= 6% drawdown")
            continue
        if equity <= rules.drawdown_floor_usd(peak):
            veto("trailing shield (6%)")
            continue
        # UNITS: `day_pnl` is in R and `daily_limit` is in USD, so the comparison has to
        # pass through `risk_usd`. Comparing R to dollars silently disables the switch (-2
        # against -750 is never true), which is how a risk rule ends up measuring nothing.
        if (day_pnl - scale) * risk_usd <= -daily_limit:
            veto("day kill switch (3%, pre-empted)")
            continue
        if (equity - day_anchor) >= cap_usd:
            veto("Best Day cap (1R/day)")
            continue

        # Walk the bars this position was open for, marking it to each CLOSE, so the day
        # line and the shield floor can be enforced INSIDE the trade.
        risk_price = _risk_price(t)
        r = t["net_r"] * scale
        if risk_price is not None and bars is not None:
            for j in range(t["entry_i"] + 1, int(t["exit_i"]) + 1):
                floating = t["dir"] * (float(close[j]) - t["entry"]) / risk_price
                # `equity` already carries the day's realised P&L, so marking the open
                # position to this close is one addition, not a re-derivation of the day.
                marked = equity + floating * scale * risk_usd
                if day_pnl + floating * scale < -daily_limit / risk_usd:
                    r = floating * scale
                    path_exits += 1
                    break
                if marked <= rules.drawdown_floor_usd(peak):
                    r = floating * scale
                    path_exits += 1
                    break
        kept.append(dict(t, net_r=r, risk_scale=scale))
        day_pnl += r
        equity += r * risk_usd
        peak = max(peak, equity)
    return kept, dict(vetoes, **({"path exits": path_exits} if path_exits else {}))


def _risk_price(t: dict) -> float | None:
    """The trade's risk in price units, recovered from its own R bookkeeping.

    `gross_r = dir * (exit - entry) / risk`, so `risk = dir * (exit - entry) / gross_r`.
    Returns None for the degenerate case (gross_r == 0), where no mark can be recovered and
    the trade is scored by its own net_r instead of by a path.
    """
    gross = t.get("gross_r")
    if not gross:
        return None
    span = t["dir"] * (t["exit"] - t["entry"])
    risk = span / gross
    return risk if risk > 0 else None


def trade_stats(trades: list[dict]) -> dict:
    """Trade-level statistics: n, mean R, sd, t, and the per-day distribution."""
    rs = [t["net_r"] for t in trades]
    n = len(rs)
    if n == 0:
        return {"n": 0, "mean_r": None, "sd": None, "t": None, "total_r": 0.0}
    mean = sum(rs) / n
    var = sum((x - mean) ** 2 for x in rs) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "mean_r": round(mean, 4), "sd": round(sd, 4),
            "t": round(t, 2), "total_r": round(sum(rs), 2)}


def power_trades(mean_r: float, sd: float, t_target: float = 1.5) -> int | None:
    """Trades needed for a one-sample t >= t_target at this effect size.

    The number that turns "wait for more trades" into an answer: at 0.068R/trade it is
    ~27,657 (99 years at the observed rate); at 0.15R it is ~120.
    """
    if not sd or mean_r is None or mean_r <= 0:
        return None
    return int(math.ceil((t_target * sd / mean_r) ** 2))


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def venue_data(symbol: str, bars: int):
    """The venue's own served history, exactly as the frozen walk-forward reads it."""
    m15 = load_m5(symbol, timeframe=gw.EXEC_TF, bars=bars)
    h1 = load_m5(symbol, timeframe="H1", bars=bars // 4 + 100)
    h4 = load_m5(symbol, timeframe="H4", bars=bars // 16 + 100)
    B = {k: m15.array[k].astype(float) for k in
         ("epoch", "open", "high", "low", "close", "spread", "volume")}
    epoch = B["epoch"]
    n = len(epoch)
    atr = gw.wilder_atr(B["high"], B["low"], B["close"], gw.ATR_PERIOD)

    h1e = h1.array["epoch"].astype(float)
    h1c = h1.array["close"].astype(float)
    h1_ef, h1_em, h1_es = (gw.ema(h1c, k) for k in (8, 21, 50))
    h4e = h4.array["epoch"].astype(float)
    h4c = h4.array["close"].astype(float)
    h4_ef = gw.ema(h4c, 20)

    ok = {k: np.zeros(n, dtype=bool) for k in
          ("h1_long", "h1_short", "h4_long", "h4_short")}
    for i in range(n):
        tt = float(epoch[i])
        k = gw.last_closed_index(h1e, tt, gw.H1_TF_SEC)
        if k >= 0:
            ok["h1_long"][i] = h1_ef[k] > h1_em[k] > h1_es[k]
            ok["h1_short"][i] = h1_ef[k] < h1_em[k] < h1_es[k]
        m = gw.last_closed_index(h4e, tt, gw.H4_TF_SEC)
        if m >= 0:
            ok["h4_long"][i] = h4c[m] > h4_ef[m]
            ok["h4_short"][i] = h4c[m] < h4_ef[m]
    hours = np.array([datetime.fromtimestamp(float(e), timezone.utc).hour
                      for e in epoch], dtype=int)
    return B, epoch, n, atr, hours, ok


def low_vol_mask(atr: np.ndarray, n: int, threshold: float = 0.8) -> np.ndarray:
    """False on bars whose ATR is below `threshold` x its trailing median.

    Built with the engine's OWN median (`trailing_percentile`, ATR_LOOKBACK / 0.5) so the
    filter is the same statistic the trigger study called a cell, not a new one. Passed as
    a signal mask into `simulate`, so a suppressed signal frees its slot exactly as it
    would live — filtering the finished trade list would report a sequence the EA could
    not have traded.
    """
    med = gw.trailing_percentile(atr, gw.ATR_LOOKBACK, 0.5)
    mask = np.ones(n, dtype=bool)
    for i in range(n):
        a, m = float(atr[i]), float(med[i])
        mask[i] = bool(a > 0 and m > 0 and a / m >= threshold)
    return mask


def run_grid(B, hours, ok, atr, cfg: dict, n: int,
             signal_mask: np.ndarray | None = None) -> list[dict]:
    return gw.simulate(B, hours, ok["h1_long"], ok["h1_short"],
                       ok["h4_long"], ok["h4_short"], atr, cfg,
                       start=gw.WARMUP_BARS, end=n, signal_mask=signal_mask)


def sweep_grid() -> list[dict]:
    out = []
    for (lo, hi) in SWEEP_SESSIONS:
        for sm in SWEEP_STOPS:
            for tp in SWEEP_TPS:
                for emas in gw.EMA_SETS:
                    out.append({"emas": emas, "stop_mult": sm, "tp_mult": tp,
                                "win_lo": lo, "win_hi": hi})
    return out


# --------------------------------------------------------------------------- #
# Mode A: the sweep (exploration — a hypothesis, never a pass)
# --------------------------------------------------------------------------- #

def sweep(args, B, epoch, n, atr, hours, ok, rules) -> dict:
    grid = sweep_grid()
    if args.slice:
        k, of = args.slice
        # Deterministic partition (stride, not contiguous blocks) so every slice spans the
        # whole grid and a partial sweep is still comparable to a full one.
        grid = [c for i, c in enumerate(grid) if i % of == k]
    rows = []
    for cfg in grid:
        raw = run_grid(B, hours, ok, atr, cfg, n)
        kept, vetoes = govern(raw, epoch, rules=rules)
        st = trade_stats(kept)
        st_raw = trade_stats(raw)
        rows.append({
            "config": cfg,
            "governed": st,
            "ungoverned": st_raw,
            "vetoes": vetoes,
            "needed_for_t15": power_trades(st["mean_r"] or 0.0, st["sd"] or 0.0),
        })
    rows.sort(key=lambda r: -(r["governed"]["mean_r"] or -9))
    decidable = [r for r in rows if (r["governed"]["n"] or 0) >= DECIDABLE_N
                 and (r["governed"]["mean_r"] or 0) >= DECIDABLE_R]
    frozen = {tuple(c.items()) for c in gw.configs()}
    print(f"\n== sweep: {len(rows)} geometries on the venue's served window "
          f"(EXPLORATION — the gate window is reused, so nothing here is a pass) ==")
    print(f"{'win':>8} {'stop':>5} {'tp':>4} {'emas':>12} | "
          f"{'n':>4} {'meanR':>8} {'t':>6} {'total':>8} | {'unG.meanR':>9} {'vetoes':>16}")
    for r in rows[:15]:
        c, g = r["config"], r["governed"]
        vt = ",".join(f"{k.split()[0]}={v}" for k, v in r["vetoes"].items()) or "-"
        print(f"{c['win_lo']:>3}-{c['win_hi']:<3} {c['stop_mult']:>5} {c['tp_mult']:>4} "
              f"{str(c['emas']):>12} | {g['n']:>4} {g['mean_r']:>8.4f} {g['t']:>6.2f} "
              f"{g['total_r']:>8.1f} | {r['ungoverned']['mean_r']:>9.4f} {vt:>16}")
    print(f"\ncandidates at >= {DECIDABLE_R:+.2f}R/trade over >= {DECIDABLE_N} trades: "
          f"{len(decidable)}")
    for r in decidable[:5]:
        print(f"  {r['config']}  n={r['governed']['n']} mean={r['governed']['mean_r']:+.4f} "
              f"t={r['governed']['t']} needs {r['needed_for_t15']} trades for t>=1.5")
    return {"rows": rows, "decidable": decidable}


# --------------------------------------------------------------------------- #
# Mode B: the governed walk-forward (a test, pre-registered by this file)
# --------------------------------------------------------------------------- #

def walk_forward(args, B, epoch, n, atr, hours, ok, rules,
                 governor=govern, label: str = "entry-only governor") -> dict:
    folds = gw.build_folds(epoch)
    all_cfgs = gw.configs()
    # Governor applied INSIDE each fold: a fold is a stand-alone run of the strategy, so
    # its equity path is walked from the account size, not carried in from the fold before
    # it. Declared here, before any number was seen.
    governed: list[dict[int, float]] = [dict() for _ in all_cfgs]
    kept_counts: list[dict[int, int]] = [dict() for _ in all_cfgs]
    mask = low_vol_mask(atr, n) if getattr(args, "exclude_lowvol", False) else None
    trades_by_cfg: list[list[dict]] = []
    for k, cfg in enumerate(all_cfgs):
        raw = run_grid(B, hours, ok, atr, cfg, n, signal_mask=mask)
        trades_by_cfg.append(raw)
        for fi, (_nm, lo, hi) in enumerate(folds):
            inside = [t for t in raw if lo <= t["entry_i"] < hi]
            kept, _v = governor(inside, epoch, rules=rules)
            governed[k][fi] = sum(t["net_r"] for t in kept)
            kept_counts[k][fi] = len(kept)

    oos_rs: list[float] = []
    picks: list[dict] = []
    prev = max(range(len(all_cfgs)),
               key=lambda k: sum(t["net_r"] for t in trades_by_cfg[k]))
    for fi in range(1, len(folds)):
        scored = []
        for k in range(len(all_cfgs)):
            cfgd = all_cfgs[k]
            scored.append((governed[k][fi - 1], -cfgd["stop_mult"], -cfgd["tp_mult"],
                           -k, k))
        scored.sort(reverse=True)
        if scored[0][0] != 0.0:
            prev = scored[0][4]
        pick = prev
        oos_rs.append(governed[pick][fi])
        picks.append({"fold": folds[fi][0], "selected_on": folds[fi - 1][0],
                      "config": all_cfgs[pick], "oos_r": round(governed[pick][fi], 4),
                      "oos_trades": kept_counts[pick][fi]})

    n_oos = sum(p["oos_trades"] for p in picks)
    oos_detail: list[dict] = []
    for fi in range(1, len(folds)):
        _nm, nlo, nhi = folds[fi]
        k = gw._pick_index(all_cfgs, picks[fi - 1]["config"])
        inside = [t for t in trades_by_cfg[k] if nlo <= t["entry_i"] < nhi]
        kept, _v = governor(inside, epoch, rules=rules)
        for t in kept:
            oos_detail.append({"fold": folds[fi][0], "entry_i": t["entry_i"],
                               "dir": t["dir"], "net_r": t["net_r"]})

    control_total = 0.0
    if n_oos:
        totals = []
        for rep in range(args.control_reps):
            tot = 0.0
            for fi in range(1, len(folds)):
                k = gw._pick_index(all_cfgs, picks[fi - 1]["config"])
                _nm, nlo, nhi = folds[fi]
                tot += sum(t["net_r"] for t in gw.random_control(
                    B, hours, atr, kept_counts[k][fi], picks[fi - 1]["config"],
                    start=nlo, end=nhi, seed=gw.CONTROL_SEED + rep * 1000 + fi))
            totals.append(tot)
        control_total = float(np.mean(totals))

    checks = gw.criteria(oos_rs, control_total)
    ok_all = all(v for kk, v in checks.items() if kk.startswith("V"))
    prop = gw.prop_compat(oos_detail, epoch, rules, RISK_USD)

    print(f"\n== governed walk-forward: {len(oos_rs)} OOS folds, governor inside "
          f"({label}) ==")
    for p in picks:
        print(f"  {p['fold']} (picked on {p['selected_on']}): "
              f"stop={p['config']['stop_mult']} tp={p['config']['tp_mult']} "
              f"emas={p['config']['emas']} win={p['config']['win_lo']}-{p['config']['win_hi']}"
              f"  -> {p['oos_r']:+7.2f}R  ({p['oos_trades']} trades)")
    flags = " ".join(f"[{'P' if v else 'F'}]{kk.split()[0]}"
                     for kk, v in checks.items() if kk.startswith("V"))
    print(f"\nOOS trades={n_oos} total={sum(oos_rs):+.2f}R "
          f"mean={np.mean(oos_rs) if oos_rs else 0:+.3f}R/fold "
          f"t={checks['_t']:+.2f}")
    print(f"random-entry control (mean of {args.control_reps}) = {control_total:+.2f}R")
    print(f"  {flags}  -> {'PROVISIONAL EDGE' if ok_all else 'NOT VALIDATED'} "
          f"(fails: {[kk for kk, v in checks.items() if kk.startswith('V') and not v]})")
    print(f"\n== venue rules on the GOVERNED OOS sequence (1R = ${RISK_USD:.0f}) ==")
    print(f"  {prop['days']} trading days, final equity ${prop['final_equity']:,.2f} "
          f"({prop['total_usd']:+,.2f}; target {prop['target_usd']:,.0f} -> "
          f"{'MET' if prop['target_met'] else 'not met'})")
    print(f"  worst day {prop['worst_day_r']:+.2f}R = ${prop['worst_day_usd']:,.0f} vs "
          f"3% daily limit ${prop['daily_limit_usd']:,.0f}")
    # `best_day_share` is undefined when there is no profit to take a share of. Printing
    # 0% there would read as "the cap is safe", which is the opposite of true: the run
    # lost money, and the Best Day rule is a constraint on profit.
    share = ("undefined (no profit)" if prop["best_day_share"] is None
             else f"{prop['best_day_share']:.1%} of total")
    print(f"  best day  {prop['best_day_r']:+.2f}R = ${prop['best_day_usd']:,.0f} = "
          f"{share} vs 20% limit -> "
          f"{'OK' if prop['best_day_ok'] else 'BREACH/N-A'}")
    print(f"  shield/daily violations: {prop['shield_breaches']} {prop['daily_breaches']} "
          f"-> {'SURVIVED' if prop['survived'] else 'BREACHED'}")
    return {"folds": [f[0] for f in folds], "oos_r_per_fold": [round(x, 4) for x in oos_rs],
            "picks": picks, "checks": {k: bool(v) for k, v in checks.items()
                                       if k.startswith("V")},
            "stats": {k: checks[k] for k in checks if k.startswith("_")},
            "control_total_r": round(control_total, 4), "oos_trades": n_oos,
            "prop_compat": prop}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--mode", choices=("governed", "sweep", "both"), default="both")
    ap.add_argument("--control-reps", type=int, default=200)
    ap.add_argument("--exclude-lowvol", action="store_true",
                    help="suppress signals whose H1 ATR is below 0.8x its trailing median "
                         "(the -0.35R/trade cell of the trigger study), in-engine")
    ap.add_argument("--governor", choices=("entry", "path"), default="entry",
                    help="entry = mirror PropGovernorBlock() exactly (gates ENTRIES); "
                         "path = the same rules PLUS a day-loss kill switch and a "
                         "soft-stop ladder that act INSIDE the trade")
    ap.add_argument("--slice", type=int, nargs=2, metavar=("K", "N"),
                    help="run only slice K of N of the sweep grid (the sweep is the "
                         "expensive half; slices are stride-based so each spans the grid)")
    ap.add_argument("--out", default="artifacts/gold_governed_wfo.json")
    a = ap.parse_args(argv)

    rules = ThunderboltClassicRules(account_size=ACCOUNT_SIZE)
    B, epoch, n, atr, hours, ok = venue_data(a.symbol, a.bars)
    first = datetime.fromtimestamp(epoch[0], timezone.utc)
    last = datetime.fromtimestamp(epoch[-1], timezone.utc)
    print(f"{a.symbol} {gw.EXEC_TF}: {n} bars {first:%Y-%m-%d} .. {last:%Y-%m-%d} "
          f"(the venue's served window) | governor ON: 3% day / 6% shield / "
          f"Best Day {rules.best_day_pct:.0f}% of {rules.profit_target_pct:.0f}% = "
          f"{rules.account_size * rules.profit_target_pct / 100 * rules.best_day_pct / 100:.0f} USD/day")

    out: dict = {"spec": {"symbol": a.symbol, "bars": n,
                          "window": [first.isoformat(), last.isoformat()],
                          "account_size": ACCOUNT_SIZE, "risk_usd": RISK_USD,
                          "risk_pct": RISK_PCT,
                          "governor": "mirror of PropGovernorBlock() in MidastouchAI.mq5",
                          "governor_approximations": [
                              "floating equity (EA) vs realised equity (replay) at the entry bar",
                              "per-tick day anchor (EA) vs first entry of the UTC day (replay)"],
                          "decidable_threshold": {"mean_r": DECIDABLE_R,
                                                  "trades": DECIDABLE_N}},
                  "data": {"first_bar": str(first), "last_bar": str(last)}}
    if a.mode in ("sweep", "both"):
        sw = sweep(a, B, epoch, n, atr, hours, ok, rules)
        sw["grid_size"] = len(sweep_grid())
        sw["slice"] = a.slice
        out["sweep"] = sw
    if a.mode in ("governed", "both"):
        if a.governor == "path":
            # `bars` is bound here so the governor callable keeps the same shape as the
            # entry-only one — one selection/scoring path, two risk policies.
            gov = functools.partial(govern_path, bars=B)
            label = ("PATH governor: day kill switch (pre-empted) + soft-stop ladder "
                     "+ shield-floor exit")
        else:
            gov, label = govern, "entry-only: mirror of PropGovernorBlock()"
        out["spec"]["governor_mode"] = a.governor
        out["spec"]["low_vol_filter"] = bool(a.exclude_lowvol)
        out["governed_wfo"] = walk_forward(a, B, epoch, n, atr, hours, ok, rules,
                                           governor=gov, label=label)

    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nartifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
