"""Hostile-regime vs overfit study — executes docs/HOSTILE_VS_OVERFIT_20260916.md.

Stage A: rolling regime features on price alone (every ~92d window) + OOS extremity.
Stage B: fresh per-trade batch (shipped / rebuilt / gated, IS+OOS).
Stage C: anatomy (monthly-R cross-config correlation, loser decomposition,
         IS->OOS overfit gradient from today's recorded configs).
Stage D: benchmarks (random-entry control; V100 same-window simultaneity).
Writes artifacts/train/REGIME_FEATURES.json, HOSTILE_VS_OVERFIT_TRADES.json,
HOSTILE_VS_OVERFIT_RESULTS.json and prints the tables.

Usage: python scripts/hostile_vs_overfit.py [features|trades|analyze|all]
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["CERT_DATA_DIR"] = os.path.join(ROOT, "artifacts", "train")
os.environ["CERT_SPREAD"] = "18.5"
os.environ["CERT_USD_PER_UNIT_PER_LOT"] = "1.009"
os.environ["CERT_MIN_LOT"] = "0.01"
os.environ["CERT_LOT_STEP"] = "0.001"
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import entry_lab as lab  # noqa: E402  (env set first)

ART = os.path.join(ROOT, "artifacts", "train")
IS_START, IS_END = "2025-08-01", "2026-06-01"
# canonical OOS end per sprint/tuning code constants (exclusive)
OOS_START, OOS_END = "2026-06-01", "2026-09-03"
WINDOW_DAYS = 92


def d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def bar_date(t) -> date:
    """Lab bars carry datetime objects; accept strings too."""
    return t.date() if isinstance(t, datetime) else datetime.strptime(str(t), "%Y-%m-%d %H:%M").date()


def pct_rank(vals: list[float], x: float) -> float:
    below = sum(1 for v in vals if v < x)
    return below / len(vals) * 100.0


# ---------------------------------------------------------------- stage A --
def rolling_features() -> dict:
    m15, h1 = lab.load("m15.csv"), lab.load("h1.csv")
    closes = [b["c"] for b in m15]
    eF = lab.ema(closes, lab.EMA_FAST)
    eM = lab.ema(closes, lab.EMA_MID)
    atr = lab.wilder_atr(m15, lab.ATR_PERIOD)
    times = [b["t"] for b in m15]
    dts = [bar_date(t) for t in times]

    # daily returns for TREND_DAYS
    day_last: dict[date, float] = {}
    for dt, c in zip(dts, closes):
        day_last[dt] = c
    days = sorted(day_last)
    day_ret = {days[i]: (day_last[days[i]] / day_last[days[i - 1]] - 1.0)
               for i in range(1, len(days))}

    # PC20 touches over the whole corpus (stack-aligned EMA20 touches)
    touches = []  # (index, direction, touch_close, atr)
    for i in range(1, len(m15) - 9):
        a = atr[i]
        if a <= 0:
            continue
        if eF[i] > eM[i] and abs(closes[i] - eF[i]) <= 0.35 * a:
            touches.append((i, 1, closes[i], a))
        elif eF[i] < eM[i] and abs(closes[i] - eF[i]) <= 0.35 * a:
            touches.append((i, -1, closes[i], a))

    def window_pc20(lo: date, hi: date) -> float | None:
        cont = tot = 0
        for i, dr, c0, a in touches:
            if not (lo <= dts[i] <= hi):
                continue
            tot += 1
            if dr > 0:
                ok = max(closes[i + 1:i + 9]) >= c0 + 0.5 * a
            else:
                ok = min(closes[i + 1:i + 9]) <= c0 - 0.5 * a
            cont += 1 if ok else 0
        return (cont / tot) if tot >= 20 else None

    def window_r90(hi: date) -> float | None:
        import math
        lo = hi.toordinal() - 90
        los = [dd for dd in days if dd.toordinal() <= lo]
        if not los or hi not in day_last:
            return None
        p0, p1 = day_last[los[-1]], day_last[hi]
        return math.log(p1 / p0) if p0 > 0 else None

    def window_volr(hi: date) -> float | None:
        # realized vol: std of daily returns over trailing 30d
        import statistics
        tail = [abs(day_ret[dd]) for dd in days if 0 < (hi - dd).days <= 30 and dd in day_ret]
        if len(tail) < 15:
            return None
        recent = statistics.pstdev([day_ret[dd] for dd in days
                                    if 0 < (hi - dd).days <= 30 and dd in day_ret])
        hist = []
        for back in range(30, 360, 30):
            seg = [day_ret[dd] for dd in days if back < (hi - dd).days <= back + 30 and dd in day_ret]
            if len(seg) >= 10:
                hist.append(statistics.pstdev(seg))
        return (recent / (statistics.median(hist))) if hist and statistics.median(hist) > 0 else None

    def window_trend_days(lo: date, hi: date) -> float | None:
        import statistics
        vals = [day_ret[dd] for dd in days if lo <= dd <= hi and dd in day_ret]
        if len(vals) < 30:
            return None
        vol = statistics.pstdev([day_ret[dd] for dd in days
                                 if 0 < (hi - dd).days <= 90 and dd in day_ret])
        if vol <= 0:
            return None
        return sum(1 for v in vals if abs(v) > 2 * vol) / len(vals)

    def features_for(lo: date, hi: date) -> dict:
        return {"R90": window_r90(hi), "PC20": window_pc20(lo, hi),
                "VOLR": window_volr(hi), "TREND_DAYS": window_trend_days(lo, hi)}

    # rolling 92d windows, weekly steps
    first, last = dts[0], dts[-1]
    ends, cur = [], last
    while (cur - first).days >= WINDOW_DAYS:
        ends.append(cur)
        cur = date.fromordinal(cur.toordinal() - 7)
    ends.reverse()
    rolling = []
    for hi in ends:
        lo = date.fromordinal(hi.toordinal() - WINDOW_DAYS + 1)
        f = features_for(lo, hi)
        f["window"] = [str(lo), str(hi)]
        rolling.append(f)

    is_f = features_for(d(IS_START), d(IS_END))
    oos_f = features_for(d(OOS_START), d(OOS_END))

    extremity = {}
    for k in ("R90", "PC20", "VOLR", "TREND_DAYS"):
        vals = [r[k] for r in rolling if r[k] is not None]
        if oos_f[k] is None or len(vals) < 10:
            extremity[k] = {"oos": oos_f[k], "pct": None, "call": "INSUFFICIENT"}
            continue
        p = pct_rank(vals, oos_f[k])
        extremity[k] = {"oos": round(oos_f[k], 4), "pct": round(p, 1),
                        "call": "EXTREME" if p >= 95 else ("NORM" if p < 75 else "MIDDLE"),
                        "corpus_p95": round(sorted(vals)[int(0.95 * len(vals))], 4)}
    return {"rolling_windows": rolling, "IS": is_f, "OOS": oos_f,
            "extremity": extremity,
            "n_windows": len(rolling),
            "note": "PC20 = pullback-continuation index (family thesis as a market property); "
                    "EXTREME = OOS percentile >= 95 of all rolling 92d windows."}


# ---------------------------------------------------------------- stage B --
CONFIGS = {
    # deployed preset geometry (sprint baseline definition): TP 1.8, module-const
    # PB band 0.30-2.2, MR/BF on, EMA-side off — must reproduce n=119/-15.10R OOS
    "shipped": {"tp_mult": 1.8},
    # harness module defaults (legacy TP 2.4) — extra anatomy config
    "legacy24": {},
    "rebuilt": {"tp_mult": 1.6, "pb_min": 0.60, "pb_max": 0.70,
                "ema_side_filter": True, "disable_mr": True, "use_bandfade": False},
    "gated": {"tp_mult": 1.6, "pb_min": 0.60, "pb_max": 0.70, "ema_side_filter": True,
              "disable_mr": True, "use_bandfade": False,
              "htf_slope_gate": True, "no_mom": True},
}


def trade_batch() -> dict:
    EQUITY = 300.0
    out = {}
    for name, kw in CONFIGS.items():
        for wname, (lo, hi) in (("IS", (IS_START, IS_END)), ("OOS", (OOS_START, OOS_END))):
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                rep = lab.certify(EQUITY, start=datetime.fromisoformat(lo),
                                  end=datetime.fromisoformat(hi), **kw)
            s = {k: v for k, v in rep.items() if k not in ("trades", "veto_sample")}
            out[f"{name}_{wname}"] = {
                "n": s.get("n"), "total_r": s.get("total_r"),
                "max_dd_pct": s.get("max_drawdown_pct"),
                "trades": [{k: t[k] for k in ("t", "strat", "dir", "reg", "z",
                                              "atr_pct", "r", "exit", "sig_t")}
                           for t in rep["trades"]]}
    return out


# ---------------------------------------------------------------- stage C --
def monthly_r(trades: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        m = t["t"][:7]
        out[m] = out.get(m, 0.0) + t["r"]
    return out


def spearman(pairs: list[tuple[float, float]]) -> float:
    def ranks(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for rank, idx in enumerate(s):
            r[idx] = rank
        return r
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    rx, ry = ranks(xs), ranks(ys)
    n = len(pairs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


# ---------------------------------------------------------------- stage D --
def random_control(n_trades: int = 200, seed: int = 20260916) -> dict:
    m15 = lab.load("m15.csv")
    atr = lab.wilder_atr(m15, lab.ATR_PERIOD)
    dts = [bar_date(b["t"]) for b in m15]
    rng = random.Random(seed)
    out = {}
    for wname, (lo, hi) in (("IS", (IS_START, IS_END)), ("OOS", (OOS_START, OOS_END))):
        lo_i = next((i for i, dd in enumerate(dts) if dd >= d(lo)), 0)
        hi_i = next((i for i, dd in enumerate(dts) if dd >= d(hi)), len(dts) - 10)
        total = 0.0
        for _ in range(n_trades):
            i = rng.randrange(lo_i, max(lo_i + 1, hi_i - 9))
            a = atr[i]
            if a <= 0:
                continue
            sd = 1.7 * a
            direction = rng.choice((1, -1))
            entry = m15[i + 1]["o"]
            exitc = m15[i + 9]["c"]
            r = ((exitc - entry) / sd) if direction > 0 else ((entry - exitc) / sd)
            total += r - lab.SPREAD_V75 / sd
        out[wname] = round(total, 2)
    out["ratio_oos_over_is"] = round(out["OOS"] / out["IS"], 3) if out["IS"] else None
    return out


def v100_rows() -> dict:
    scan = json.load(open(os.path.join(ART, "CROSS_SYMBOL_SCAN_v100.json")))
    amend = json.load(open(os.path.join(ART, "AMENDMENT_C_V100.json")))
    rows = {}
    cfgs = scan.get("configs", {})
    items = cfgs.items() if isinstance(cfgs, dict) else \
        ((c.get("name") or c.get("config"), c) for c in cfgs)
    for nm, cfg in items:
        if isinstance(cfg, dict) and cfg.get("oos"):
            rows[f"v100_{nm}"] = {"is_total_r": (cfg.get("is") or {}).get("total_r"),
                                  "oos_total_r": cfg["oos"].get("total_r")}
    for nm, v in amend.items():
        if isinstance(v, dict) and "is" in v:
            rows[f"v100_gated_{nm}"] = {"is_total_r": (v["is"] or {}).get("total_r"),
                                        "oos_total_r": (v.get("oos") or {}).get("total_r")}
    return rows


# ---------------------------------------------------------------- main -----
def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"

    feats = None
    fpath = os.path.join(ART, "REGIME_FEATURES.json")
    if stage in ("features", "all"):
        feats = rolling_features()
        json.dump(feats, open(fpath, "w"), indent=1)
        print("== FEATURE EXTREMITY (OOS vs all rolling 92d windows) ==")
        for k, v in feats["extremity"].items():
            print(f"  {k:10s} OOS={v['oos']} pct={v.get('pct')} -> {v['call']}")
    elif stage in ("trades", "analyze", "all"):
        feats = json.load(open(fpath))

    trades_path = os.path.join(ART, "HOSTILE_VS_OVERFIT_TRADES.json")
    if stage in ("trades", "all"):
        batch = trade_batch()
        json.dump(batch, open(trades_path, "w"), indent=1)
        print("== TRADE BATCH ==")
        for k, v in batch.items():
            print(f"  {k:16s} n={v['n']} totalR={v['total_r']} dd={v['max_dd_pct']}")
    elif stage in ("analyze", "all"):
        batch = json.load(open(trades_path))

    if stage != "analyze" and stage != "all":
        return

    # anatomy
    oos_monthly = {name: monthly_r(v["trades"]) for name, v in batch.items() if name.endswith("OOS")}
    months = sorted({m for mm in oos_monthly.values() for m in mm})
    print("== OOS monthly totalR by config ==")
    for name, mm in oos_monthly.items():
        print(f"  {name:16s} " + "  ".join(f"{m}:{mm.get(m, 0):+.2f}" for m in months))
    corr = {}
    names = list(oos_monthly)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            xs = [oos_monthly[a].get(m, 0.0) for m in months]
            ys = [oos_monthly[b].get(m, 0.0) for m in months]
            n = len(months)
            mx, my = sum(xs) / n, sum(ys) / n
            num = sum((p - mx) * (q - my) for p, q in zip(xs, ys))
            den = (sum((p - mx) ** 2 for p in xs) * sum((q - my) ** 2 for q in ys)) ** 0.5
            corr[f"{a}|{b}"] = round(num / den, 3) if den else None
    print("== cross-config monthly-R correlation ==", corr)

    # loser decomposition (gated + rebuilt OOS)
    decomp = {}
    for name in ("rebuilt_OOS", "gated_OOS", "shipped_OOS"):
        losers = [t for t in batch[name]["trades"] if t["r"] < 0]
        by = {"month": {}, "dir": {}, "strat": {}, "reg": {}}
        for t in losers:
            for key, val in (("month", t["t"][:7]), ("dir", t["dir"]),
                             ("strat", t["strat"]), ("reg", t["reg"])):
                cell = by[key].setdefault(val, {"n": 0, "r": 0.0})
                cell["n"] += 1
                cell["r"] = round(cell["r"] + t["r"], 2)
        decomp[name] = by
        print(f"== losers {name}: n={len(losers)} of {batch[name]['n']} ==")
        for key in by:
            print(f"   {key}: " + "  ".join(f"{k}:{v['n']}({v['r']:+.1f})"
                                            for k, v in sorted(by[key].items())))

    # overfit gradient across today's recorded configs
    pairs = []
    for fin in json.load(open(os.path.join(ART, "SPRINT_REPORT.json")))["oos"]["finalists"]:
        pairs.append((fin["is"]["total_r"], fin["oos"]["total_r"]))
    for fin in json.load(open(os.path.join(ART, "V75LOW_H1_TUNING_OOS.json"))).values():
        if isinstance(fin, dict) and "is_total_r" in fin and "oos" in fin:
            pairs.append((fin["is_total_r"], (fin["oos"] or {}).get("total_r")))
    gate = json.load(open(os.path.join(ART, "AUTOPSY_GATE_RESULTS.json")))
    for k in ("NO_MOM", "BOTH", "HTF_SLOPE"):
        v = gate.get(k, {})
        if isinstance(v, dict) and "is" in v and "oos" in v:
            pairs.append((v["is"].get("total_r"), v["oos"].get("total_r")))
    diag = json.load(open(os.path.join(ART, "OOS_DIAGNOSTICS.json")))
    for k, v in diag.items():
        if isinstance(v, dict) and "is" in v and "oos" in v:
            pairs.append((v["is"].get("total_r"), v["oos"].get("total_r")))
    for name, v in v100_rows().items():
        if v["is_total_r"] is not None and v["oos_total_r"] is not None:
            pairs.append((v["is_total_r"], v["oos_total_r"]))
    pairs = [p for p in pairs if p[0] is not None and p[1] is not None]
    grad = round(spearman(pairs), 3)
    print(f"== IS->OOS gradient (spearman, n={len(pairs)}): {grad} ==")
    for p in sorted(pairs):
        print(f"   IS {p[0]:+7.2f} -> OOS {p[1]:+7.2f}")

    ctrl = random_control()
    print("== random-entry control ==", ctrl)

    results = {"oos_monthly": oos_monthly, "corr": corr, "decomp": decomp,
               "gradient_spearman": grad, "gradient_pairs": pairs,
               "random_control": ctrl, "v100_rows": v100_rows(),
               "extremity": feats["extremity"]}
    json.dump(results, open(os.path.join(ART, "HOSTILE_VS_OVERFIT_RESULTS.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
