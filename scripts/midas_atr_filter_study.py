#!/usr/bin/env python3
"""ATR-regime filter study for the MIDAS live config (research artifact).

Question (external review, 2026-09-18, item 4): should the engine skip
signals whose H1 ATR is in a "dead zone" (too low = chop) or "news zone"
(too high = slippage)? The review guessed fixed thresholds; this study
measures them on the certified corpus with the certified engine.

Method: run ORIGINAL k=1.0/75-25 (the live LV config) unfiltered and with
candidate ATR percentile bands, where atr_pct = atr/median_atr*100. The
percentile basis is the corpus's own H1 ATR distribution. Every variant
reuses run_config's exact bookkeeping (pending-fill protocol, certified
_manage exits, amendment-6 veto) so results are comparable with the
2026-09-18 sweep artifact.

NOT a certified engine. Output: artifacts JSON + ranked table.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_sweep as ms                       # certified primitives
from midas_variant_research import build_data, run_config  # same bookkeeping

ART = "artifacts"
CANDIDATES = [  # (floor_pct, ceil_pct) in % of median ATR; (None, None) = off
    (None, None),
    (50, 200),
    (50, 300),
    (60, 250),
    (40, 300),
    (30, None),
    (50, None),
]


def metrics(trades: list[dict], days: float) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "net_r": 0.0, "pf": 0.0, "exp": 0.0,
                "win": 0.0, "per_month": 0.0, "dd": 0.0}
    rs = [t["r"] for t in trades]
    gross_w = sum(r for r in rs if r > 0)
    gross_l = -sum(r for r in rs if r < 0)
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"n": n, "net_r": round(sum(rs), 2), "pf": round(pf, 3),
            "exp": round(sum(rs) / n, 4), "win": round(
                sum(1 for r in rs if r > 0) / n, 3),
            "per_month": round(n / max(days / 30.44, 1e-9), 1),
            "dd": round(abs(dd), 2)}


def main() -> int:
    data = build_data()
    m15 = data["m15"]
    h1_atr = data["h1_atr"]
    from bisect import bisect_right
    t0 = m15[0]["time"] + 900
    t1 = m15[-1]["time"]
    days = (t1 - t0) / 86400.0

    # percentile basis: H1 ATR at every in-window evaluated signal bar
    atrs = []
    for i, b in enumerate(m15):
        ct = b["time"] + 900
        if not (t0 < ct <= t1):
            continue
        k1 = bisect_right(data["h1_ct"], ct)
        if k1 >= 21:
            atrs.append(h1_atr[k1 - 1])
    atrs.sort()
    med = atrs[len(atrs) // 2]
    def pct(p): return atrs[min(int(p * len(atrs)), len(atrs) - 1)]
    print(f"corpus H1-ATR: median={med:.2f} | p01={pct(0.01):.2f} "
          f"p05={pct(0.05):.2f} p95={pct(0.95):.2f} p99={pct(0.99):.2f} "
          f"(n={len(atrs)})")

    rows = []
    for flo, cei in CANDIDATES:
        lo_atr = (flo / 100.0 * med) if flo else None
        hi_atr = (cei / 100.0 * med) if cei else None
        trades = run_config(data, "ORIGINAL", data["m15_bb"].get(1.0) or
                            _bb_list(data, 1.0), 75, 25, t0, t1,
                            atr_lo=lo_atr, atr_hi=hi_atr)
        m = metrics(trades, days)
        m.update(filter=f"{flo or 0}-{cei or 'inf'}%med", atrs=(
            f"{lo_atr:.2f}" if lo_atr else "-", hi_atr))
        rows.append(m)
        print(f"  band {m['filter']:<14} n={m['n']:<5} net_r={m['net_r']:<8} "
              f"pf={m['pf']:<7} exp={m['exp']:<8} dd={m['dd']}")

    os.makedirs(ART, exist_ok=True)
    out = os.path.join(ART, "midas_atr_filter_study_20260918.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"median_atr": med, "pcts": {"p01": pct(0.01),
                   "p05": pct(0.05), "p95": pct(0.95), "p99": pct(0.99)},
                   "days": round(days, 1), "rows": rows}, f, indent=1)
    print(f"saved {out}")
    return 0


def _bb_list(data: dict, k: float) -> list[int]:
    closes = data["m15_close"]
    return [ms.bb_touch(closes, i, 20, k) for i in range(len(closes))]


if __name__ == "__main__":
    sys.exit(main())
