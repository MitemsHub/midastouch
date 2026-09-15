"""Exit-geometry re-derivation for the v2.10 long-only build.

Uses the 75 REAL entries from the v210_31m tester pass (shared pair_trades),
deep M30 history for paths (44,353 bars, 2024.03-2026.09; M30 bars align
exactly with the gatekeeper's :00/:30 entries) and deep H1 history only for
the ATR(14) that defines R (= 2.0x ATR, the spec SL distance).

Prior corpus caveat: the published p75=0.64R / p90=0.88R came from the
two-sided run (sells drag every statistic). This study measures buys only.

Usage:  python scripts/v75_exit_rederivation.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from v75_tester_runner import pair_trades, parse_report  # noqa: E402

M30_DEEP = ROOT / "artifacts/npz/V75_M30_deep_31m.npy"
H1_DEEP = ROOT / "artifacts/npz/V75_H1_deep_31m.npy"
R_MULT = 2.0          # R is defined by the spec SL: 2.0x H1 ATR(14)


def load(path: Path) -> list[dict]:
    arr = np.load(path)
    return [{"epoch": float(b["time"]), "open": float(b["open"]), "high": float(b["high"]),
             "low": float(b["low"]), "close": float(b["close"])} for b in arr]


def h1_atr_at(h1: list[dict], t: float, period: int = 14) -> float:
    """ATR(period) over the period TRs ending at the last H1 bar closed before t."""
    idx = max(i for i, b in enumerate(h1) if b["epoch"] + 3600 <= t + 1)
    if idx < period:
        return 0.0
    trs = [max(h1[j]["high"] - h1[j]["low"],
               abs(h1[j]["high"] - h1[j - 1]["close"]),
               abs(h1[j]["low"] - h1[j - 1]["close"]))
           for j in range(idx - period + 1, idx + 1)]
    return sum(trs) / period


def main() -> None:
    h1 = load(H1_DEEP)
    m30 = load(M30_DEEP)
    trades = [t for t in pair_trades(parse_report("v210_31m")["deals"]) if t["side"] == "buy"]
    print(f"long-only entries: {len(trades)}   M30 bars: {len(m30)}   H1 bars: {len(h1)}")

    def ts(s: str) -> float:
        return datetime.strptime(s, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()

    MAX_HOLD_BARS = 16          # 8h ceiling for the grid (M30 bars)
    entries = []
    skipped = 0
    for t in trades:
        t0 = ts(t["entry_time"])
        atr = h1_atr_at(h1, t0)
        i = next((k for k, b in enumerate(m30) if b["epoch"] >= t0 - 1), None)
        if i is None or atr <= 0:
            skipped += 1
            continue
        r_dist = R_MULT * atr
        entry = t["entry_price"]
        window = m30[i:i + MAX_HOLD_BARS + 1]
        mfe = mae = 0.0
        for b in window:
            if b["epoch"] < t0 - 1:  # entries sit exactly on bar opens
                continue
            mfe = max(mfe, (b["high"] - entry) / r_dist)
            mae = max(mae, (entry - b["low"]) / r_dist)
        entries.append({"t0": t0, "entry": entry, "r": r_dist,
                        "mfe": mfe, "mae": mae, "window": window})
    print(f"usable entries: {len(entries)}  (skipped {skipped}: warmup/history)")

    mfes = sorted(e["mfe"] for e in entries)
    maes = sorted(e["mae"] for e in entries)
    n = len(mfes)
    def pct(xs, p):
        k = (len(xs) - 1) * p / 100.0
        f, c = int(k), min(int(k) + 1, len(xs) - 1)
        return xs[f] + (xs[c] - xs[f]) * (k - f)
    print("\nBUY-side MFE distribution (R = 2x H1 ATR):")
    print("  " + "  ".join(f"p{p}={pct(mfes, p):.2f}" for p in (25, 50, 75, 90, 95)) +
          f"  max={mfes[-1]:.2f}")
    print("BUY-side MAE distribution (R):")
    print("  " + "  ".join(f"p{p}={pct(maes, p):.2f}" for p in (50, 75, 90)) +
          f"  max={maes[-1]:.2f}  | reached -1R: {sum(1 for x in maes if x >= 1.0)}/{n}")
    ge = {f">{k}R": sum(1 for x in mfes if x >= k) for k in (0.3, 0.5, 0.8, 1.0)}
    print("  MFE thresholds: " + "  ".join(f"{k}:{v}({100*v/n:.0f}%)" for k, v in ge.items()))

    # --- what-if grid: TP target (R) x hold (hours), spec SL, worst-case ties ---
    print("\n=== WHAT-IF GRID (75 real buy entries, M30 bars, SL wins ties) ===")
    print(f"{'TP_R':>5} {'hold':>5} | {'R_sum':>7} {'PF':>6} {'win%':>5} {'tp':>3} {'sl':>3} {'to':>3}")
    results = []
    for tp_r in (0.6, 0.8, 1.0, 1.25, 1.5, 2.0):
        for hold_bars in (2, 4, 6, 8, 12, 16):  # 1h, 2h, 3h, 4h, 6h, 8h
            rs = []
            hits = {"tp_hits": 0, "sl_hits": 0, "to": 0}
            for e in entries:
                r, reason = None, "to"
                for b in e["window"][:hold_bars + 1]:
                    if b["epoch"] < e["t0"] - 1:
                        continue
                    if b["low"] <= e["entry"] - e["r"]:          # -1R stop first (worst case)
                        r, reason = -1.0, "sl_hits"
                        break
                    if b["high"] >= e["entry"] + tp_r * e["r"]:
                        r, reason = tp_r, "tp_hits"
                        break
                if r is None:
                    last = [b for b in e["window"][:hold_bars + 1] if b["epoch"] >= e["t0"] - 1]
                    px = last[-1]["close"] if last else e["entry"]
                    r = (px - e["entry"]) / e["r"]
                hits[reason] += 1
                rs.append(r)
            gw = sum(x for x in rs if x > 0)
            gl = abs(sum(x for x in rs if x <= 0))
            pf = gw / gl if gl else 99.0
            wr = 100 * sum(1 for x in rs if x > 0) / len(rs)
            results.append({"tp": tp_r, "hold": hold_bars, "r_sum": sum(rs), "pf": pf,
                            "wr": wr, **hits})
            print(f"{tp_r:>5.2f} {hold_bars // 2:>4}h | {sum(rs):>+7.2f} {pf:>6.2f} "
                  f"{wr:>5.1f} {hits['tp_hits']:>3} {hits['sl_hits']:>3} {hits['to']:>3}")

    print("\nTop 8 by R-sum:")
    for r in sorted(results, key=lambda x: -x["r_sum"])[:8]:
        print(f"  TP={r['tp']:.2f}R hold={r['hold'] // 2}h  R_sum={r['r_sum']:+.2f}  "
              f"PF={r['pf']:.2f}  wr={r['wr']:.0f}%  exits tp/sl/to = "
              f"{r['tp_hits']}/{r['sl_hits']}/{r['to']}")
    ctrl = next(r for r in results if r["tp"] == 2.0 and r["hold"] == 6)
    print(f"\nControl (spec: TP=2.0R, hold=3h): R_sum={ctrl['r_sum']:+.2f}  PF={ctrl['pf']:.2f}  "
          f"(tester control measured +7.15R, PF 1.529)")


if __name__ == "__main__":
    main()
