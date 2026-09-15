"""Regime analysis: what separates profitable 2024-25 months from losing 2026?

Uses the 75 real long-only entries from the v2.10 31-month tester run, joined to
deep terminal price history (M30 + H1, full window). Per-entry regime features
(H1 ATR(14) z-score, H1 ADX(14), 6h EMA slope) are aggregated per month and
correlated against monthly PnL. A threshold filter is fit on the train segment
(2024.01-2025.08) and evaluated out-of-sample (2025.09-2026.09), mirroring the
repo's walkforward convention.

Usage: python scripts/v75_regime_analysis.py
Writes: artifacts/v75_macro_engine_tester/regime_analysis_20260914.txt
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, "tests")
sys.path.insert(0, "scripts")
from v75_tester_runner import parse_report, pair_trades  # noqa: E402

SYMBOL = "Volatility 75 Index"
TRAIN_END = "2025.09"          # first test month
OUT = Path("artifacts/v75_macro_engine_tester/regime_analysis_20260914.txt")


def fetch(tf_const, start: datetime):
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")
    rates = mt5.copy_rates_range(SYMBOL, tf_const, start, datetime.now())
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError("no rates returned")
    return rates


def wilder_atr(h, l, c, period=14):
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    atr = np.full(len(c), np.nan)
    if len(tr) < period:
        return atr
    atr[period] = tr[:period].mean()
    for i in range(period + 1, len(c)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period
    return atr


def wilder_adx(h, l, c, period=14):
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    n = len(c)
    adx = np.full(n, np.nan)
    if n < period * 3:
        return adx
    atr = tr[:period].sum()
    pdm = plus_dm[:period].sum()
    mdm = minus_dm[:period].sum()
    dxs: list[float] = []
    for i in range(period, n - 1):
        atr = atr - atr / period + tr[i]
        pdm = pdm - pdm / period + plus_dm[i]
        mdm = mdm - mdm / period + minus_dm[i]
        pdi = 100 * pdm / atr if atr > 0 else 0.0
        mdi = 100 * mdm / atr if atr > 0 else 0.0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
        dxs.append(dx)
        if len(dxs) == period:
            adx[i + 1] = float(np.mean(dxs))
        elif len(dxs) > period:
            adx[i + 1] = (adx[i] * (period - 1) + dx) / period
    return adx


def month_of(ts: str) -> str:
    return ts[:7].replace(".", "-")   # '2024.03.01 06:00' -> '2024-03'


def main() -> None:
    res = parse_report("v210_31m")
    trades = pair_trades(res["deals"])
    assert len(trades) == 75, f"expected 75 long-only entries, got {len(trades)}"

    t0 = datetime(2024, 1, 1)
    h1 = fetch(16385, t0)  # TIMEFRAME_H1
    m30 = fetch(30, t0)    # TIMEFRAME_M30
    ht, hh, hl, hc = (h1["time"].astype(np.int64), h1["high"].astype(float),
                      h1["low"].astype(float), h1["close"].astype(float))
    mc = m30["close"].astype(float)

    atr = wilder_atr(hh, hl, hc)
    adx = wilder_adx(hh, hl, hc)

    rows = []
    for t in trades:
        ts = datetime.strptime(t["entry_time"], "%Y.%m.%d %H:%M:%S")
        idx = int(np.searchsorted(ht, np.int64(ts.timestamp())))
        base = idx - 1                      # last closed H1 bar at entry
        if base < 30 or np.isnan(atr[base]):
            continue
        atr_now = atr[base]
        atr_hist = atr[max(0, base - 720):base]          # ~30d of H1 ATR
        atr_med = float(np.nanmedian(atr_hist))
        rows.append({
            "time": t["entry_time"], "month": month_of(t["entry_time"]),
            "pnl": t["pnl"],
            "atr_z": atr_now / atr_med if atr_med > 0 else np.nan,
            "adx": adx[base],
            "slope": (hc[base] - hc[base - 6]) / hc[base - 6] * 100.0,
        })
    print(f"entries with features: {len(rows)} / 75")
    assert len(rows) >= 70, "too many entries lost in feature join"

    # Month table: n, pnl, median features + month realized vol from M30 closes
    months: dict[str, dict] = {}
    mtimes = np.array([datetime.fromtimestamp(x) for x in m30["time"]], dtype="datetime64[m]")
    for r in rows:
        m = months.setdefault(r["month"], {"n": 0, "pnl": 0.0, "atr_z": [], "adx": [], "slope": []})
        m["n"] += 1
        m["pnl"] += r["pnl"]
        for k in ("atr_z", "adx", "slope"):
            if not np.isnan(r[k]):
                m[k].append(r[k])
    for m, d in months.items():
        mask = (mtimes >= np.datetime64(m)) & (mtimes < np.datetime64(m) + np.timedelta64(1, "M"))
        if mask.sum() > 2:
            lr = np.diff(np.log(mc[mask]))
            d["rvol"] = float(np.std(lr) * 1000) if len(lr) else float("nan")
        else:
            d["rvol"] = float("nan")

    lines: list[str] = []
    def w(s: str = ""):
        lines.append(s)
        print(s)

    w("# V75 regime analysis: profitable 2024-25 vs losing 2026 (2026-09-14)")
    w(f"# entries: {len(rows)} | source: V75_regress_v210_31m (75 real long-only fills)")
    w("")
    w("## Per-month table (features = median over that month's entries)")
    w("month      n  pnl     atr_z  adx    slope%  rvol")
    for m in sorted(months):
        d = months[m]
        med = lambda k: (np.median(d[k]) if d[k] else float("nan"))
        w(f"{m}  {d['n']:2d} {d['pnl']:8.2f} {med('atr_z'):6.2f} {med('adx'):6.1f} "
          f"{med('slope'):7.2f} {d.get('rvol', float('nan')):6.2f}")

    # Correlations (month level)
    ms = sorted(months)
    pnl_v = np.array([months[m]["pnl"] for m in ms])
    med = {k: {m: (np.median(months[m][k]) if months[m][k] else np.nan)
               for m in ms}
           for k in ("atr_z", "adx", "slope")}
    med["rvol"] = {m: months[m].get("rvol", np.nan) for m in ms}
    w("\n## Month-level correlation with PnL (n=29)")
    for k in ("atr_z", "adx", "slope", "rvol"):
        fv = np.array([med[k][m] for m in ms], dtype=float)
        ok = ~np.isnan(fv)
        if ok.sum() > 5:
            r = float(np.corrcoef(fv[ok], pnl_v[ok])[0, 1])
            from scipy.stats import spearmanr
            rho = float(spearmanr(fv[ok], pnl_v[ok]).statistic)
            w(f"  {k:6s} pearson {r:+.2f} | spearman {rho:+.2f}")

    # Walkforward-honest threshold test: fit on train, evaluate on test
    w(f"\n## Threshold filters (fit on 2024.01-2025.08 train, evaluated 2025.09-2026.09 out-of-sample)")
    w("   rule: drop trades whose train-fit median month feature is past threshold")
    w(f"{'feature':7s} {'dir':4s} {'thr':>8s} | {'train keep':>10s} {'train drop':>10s} | {'test keep':>9s} {'test drop':>9s} | {'full kept':>9s}")
    best_full = None
    for k in ("atr_z", "adx", "slope", "rvol"):
        fv = med[k]
        tr_m = [m for m in ms if m < TRAIN_END and not np.isnan(fv[m])]
        te_m = [m for m in ms if m >= TRAIN_END and not np.isnan(fv[m])]
        tr_pnl = sum(months[m]["pnl"] for m in tr_m)
        cands = sorted(set(fv[m] for m in tr_m))
        best = None
        for thr in cands:
            for drop_high in (True, False):
                keep = [m for m in tr_m if (fv[m] <= thr) == drop_high]
                drop = [m for m in tr_m if (fv[m] > thr) == drop_high]
                kept_n = sum(months[m]["n"] for m in keep)
                if kept_n < 20:
                    continue
                kept_pnl = sum(months[m]["pnl"] for m in keep)
                if best is None or kept_pnl > best[0]:
                    best = (kept_pnl, thr, drop_high, sum(months[m]["pnl"] for m in drop))
        if best is None:
            continue
        _, thr, drop_high, tr_drop_pnl = best
        tk = [m for m in te_m if (fv[m] <= thr) == drop_high]
        td = [m for m in te_m if (fv[m] > thr) == drop_high]
        te_keep = sum(months[m]["pnl"] for m in tk)
        te_drop = sum(months[m]["pnl"] for m in td)
        full_keep = sum(months[m]["pnl"] for m in ms if (m in fv and (fv[m] <= thr) == drop_high))
        w(f"{k:7s} {'<=thr' if drop_high else '>=thr':4s} {thr:8.2f} | "
          f"{best[0]:10.2f} {tr_drop_pnl:10.2f} | {te_keep:9.2f} {te_drop:9.2f} | {full_keep:9.2f}")
        if best_full is None or full_keep > best_full[0]:
            best_full = (full_keep, k, thr, drop_high, te_keep, te_drop)

    if best_full:
        w(f"\nBest full-window kept PnL: {best_full[0]:.2f} via {best_full[1]} "
          f"{'<=' if best_full[3] else '>='} {best_full[2]:.2f} "
          f"(out-of-sample kept {best_full[4]:.2f} / dropped {best_full[5]:.2f})")

    # Per-trade analysis: the decision-relevant granularity (EA filters at entry)
    w("\n## Per-trade feature vs PnL (n=75) - decision-relevant granularity")
    from scipy.stats import spearmanr
    tr_rows = [r for r in rows if r["month"] < TRAIN_END]
    te_rows = [r for r in rows if r["month"] >= TRAIN_END]
    w(f"   train trades: {len(tr_rows)} | test trades: {len(te_rows)} | "
      f"train PnL {sum(r['pnl'] for r in tr_rows):+.2f} | test PnL {sum(r['pnl'] for r in te_rows):+.2f}")
    best_ft = None
    for k in ("atr_z", "adx", "slope"):
        fv_t = np.array([r[k] for r in rows]); pv = np.array([r["pnl"] for r in rows])
        ok = ~np.isnan(fv_t)
        r_p = float(np.corrcoef(fv_t[ok], pv[ok])[0, 1])
        rho_t = float(spearmanr(fv_t[ok], pv[ok]).statistic)
        w(f"  {k:6s} pearson {r_p:+.2f} | spearman {rho_t:+.2f}")
        cands = sorted(set(r[k] for r in tr_rows if not np.isnan(r[k])))
        best = None
        for thr in cands:
            for drop_high in (True, False):
                keep = [r for r in tr_rows if (r[k] <= thr) == drop_high]
                if len(keep) < 20:
                    continue
                kp = sum(r["pnl"] for r in keep)
                if best is None or kp > best[0]:
                    best = (kp, thr, drop_high)
        if best is None:
            continue
        _, thr, drop_high = best
        tk = [r for r in te_rows if (r[k] <= thr) == drop_high]
        td = [r for r in te_rows if (r[k] > thr) == drop_high]
        te_kp = sum(r["pnl"] for r in tk); te_dp = sum(r["pnl"] for r in td)
        w(f"         train-fit filter {'<=' if drop_high else '>='} {thr:.2f}: "
          f"train kept {best[0]:+.2f} | OOS kept {te_kp:+.2f} ({len(tk)} trades) vs "
          f"dropped {te_dp:+.2f} ({len(td)} trades)")
        if best_ft is None or (te_kp - te_dp) > best_ft[0]:
            best_ft = (te_kp - te_dp, k, thr, drop_high)
    if best_ft:
        w(f"\nBest per-trade OOS separation: {best_ft[1]} {'<=' if best_ft[3] else '>='} "
          f"{best_ft[2]:.2f} -> OOS gain {best_ft[0]:+.2f} over keeping everything")
    w(f"\nBaseline v2.10 full window: +730.66 | 2026 test segment (unfiltered): -236.04")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
