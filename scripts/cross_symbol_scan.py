"""Cross-symbol edge scan — executes docs/CROSS_SYMBOL_SCAN_20260915.md.

Fixed config set (no searching), one pass per symbol, identical splits.
Usage: python scripts/cross_symbol_scan.py v100
Spec env (data dir + instrument truth) is set per symbol below from the
frozen docs — V100 spec comes from docs/V100_NET_EDGE_STUDY.md.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

SYMBOLS = {
    "v100": {
        "data": os.path.join(ROOT, "artifacts", "v100_replay"),
        "spread": "0.26", "usd": "1.0", "min_lot": "1.0", "lot_step": "1.0",
        "IS": ("2024-10-01", "2026-06-01"),
        "OOS": ("2026-06-01", "2026-09-05"),
    },
    # "v75low" (Volatility 75 (1s) Index) — collected live 2026-09-15 22:03 UTC,
    # 96,055 M15 bars 2023-11-06 → 2026-09-15. Spec measured live:
    # spread 1.90 units, $1.0/unit/lot, min lot 0.05, step 0.001.
    "v75low": {
        "data": os.path.join(ROOT, "artifacts", "train", "v75low"),
        "spread": "1.90", "usd": "1.0", "min_lot": "0.05", "lot_step": "0.001",
        "IS": ("2023-12-01", "2026-06-01"),
        "OOS": ("2026-06-01", "2026-09-16"),
    },
    # Amendment A (H1 timeframe test): H1 series in the harness's primary slot,
    # H4 context aggregated from the same source. Spread constants are per-trade
    # and timeframe-independent. v75t_H1 is the CONTROL (same logic, 1-tick V75).
    "v75low_H1": {
        "data": os.path.join(ROOT, "artifacts", "train", "v75low_h1"),
        "spread": "1.90", "usd": "1.0", "min_lot": "0.05", "lot_step": "0.001",
        "IS": ("2023-12-01", "2026-06-01"),
        "OOS": ("2026-06-01", "2026-09-16"),
    },
    "v75t_H1": {
        "data": os.path.join(ROOT, "artifacts", "train", "v75t_h1"),
        "spread": "18.5", "usd": "1.009", "min_lot": "0.01", "lot_step": "0.001",
        "IS": ("2025-08-01", "2026-06-01"),
        "OOS": ("2026-06-01", "2026-09-03"),
    },
}

EQUITY = 300.0
SCAN = {"min_n": 60, "max_dd": 30.0, "max_streak": 10, "min_wr": 40.0}
OOSG = {"min_n": 20, "max_dd": 30.0}
K = ("n", "wins", "win_rate", "total_r", "max_drawdown_pct", "worst_loss_streak")

CONFIGS = {
    "shipped": dict(ema_side_filter=False),
    "trained_best": dict(tp_mult=1.6, stop_mult=1.0, be_trigger=1.2, plock_z=0.5,
                         ema_side_filter=True),
    "rebuilt": dict(tp_mult=1.6, stop_mult=1.0, be_trigger=1.0, plock_z=0.5,
                    pb_min=0.60, pb_max=0.70, ema_side_filter=True,
                    use_bandfade=False, disable_mr=True),
    "rebuilt_fullstack": dict(tp_mult=1.6, stop_mult=1.0, be_trigger=1.0,
                              plock_z=0.5, pb_min=0.60, pb_max=0.70,
                              ema_side_filter=True, use_bandfade=False,
                              disable_mr=True, m15_full_stack=True),
}


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "v100"
    spec = SYMBOLS[sym]
    os.environ["CERT_DATA_DIR"] = spec["data"]
    os.environ["CERT_SPREAD"] = spec["spread"]
    os.environ["CERT_USD_PER_UNIT_PER_LOT"] = spec["usd"]
    os.environ["CERT_MIN_LOT"] = spec["min_lot"]
    os.environ["CERT_LOT_STEP"] = spec["lot_step"]

    import entry_lab as lab  # import after env so spec guard sees it

    def run(window, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rep = lab.certify(EQUITY, set(), exit_mode="touch",
                              start=datetime.fromisoformat(window[0]),
                              end=datetime.fromisoformat(window[1]), **kw)
        m = {k: rep[k] for k in K}
        m["mean_r"] = m["total_r"] / m["n"] if m["n"] else 0.0
        return m

    t0 = time.time()
    report = {"symbol": sym, "spec": {k: spec[k] for k in
                                      ("data", "spread", "usd", "min_lot", "lot_step")},
              "splits": {"is": list(spec["IS"]), "oos": list(spec["OOS"])},
              "scan_gates": SCAN, "oos_gates": OOSG, "configs": {}}
    print(f"=== {sym} scan (spec: spread={spec['spread']}, $/unit/lot={spec['usd']}, "
          f"min_lot={spec['min_lot']}) ===", flush=True)
    for name, cfg in CONFIGS.items():
        c = dict(tp_mult=1.8, stop_mult=1.0, be_trigger=1.0, plock_z=0.5)
        c.update(cfg)
        m_is = run(spec["IS"], **c)
        scan_pass = (m_is["n"] >= SCAN["min_n"]
                     and m_is["total_r"] > 0
                     and m_is["max_drawdown_pct"] <= SCAN["max_dd"]
                     and m_is["worst_loss_streak"] <= SCAN["max_streak"]
                     and m_is["win_rate"] >= SCAN["min_wr"])
        row = {"cfg": c, "is": m_is, "scan_pass": scan_pass, "oos": None,
               "oos_pass": None}
        if scan_pass:
            m_oos = run(spec["OOS"], **c)
            row["oos"] = m_oos
            row["oos_pass"] = (m_oos["n"] >= OOSG["min_n"]
                               and m_oos["total_r"] > 0
                               and m_oos["max_drawdown_pct"] <= OOSG["max_dd"])
        report["configs"][name] = row
        print(f"{name:<19} IS n={m_is['n']:>4} R={m_is['total_r']:+8.2f} "
              f"dd={m_is['max_drawdown_pct']:5.1f}% wr={m_is['win_rate']:4.1f}% "
              f"stk={m_is['worst_loss_streak']:>2} scan={'PASS' if scan_pass else 'fail'}",
              flush=True)
        if scan_pass:
            o = row["oos"]
            print(f"{'':19} OOS n={o['n']:>4} R={o['total_r']:+8.2f} "
                  f"dd={o['max_drawdown_pct']:5.1f}% "
                  f"oos={'PASS' if row['oos_pass'] else 'fail'}", flush=True)

    edges = [n for n, r in report["configs"].items()
             if r["scan_pass"] and r["oos_pass"]]
    report["verdict"] = (f"EDGE via {edges}" if edges else
                         "NO-EDGE: no config passed SCAN + OOS on this symbol")
    out = os.path.join(ROOT, "artifacts", "train", f"CROSS_SYMBOL_SCAN_{sym}.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"\nVERDICT [{sym}]: {report['verdict']}")
    print(f"report: {out} | elapsed {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
