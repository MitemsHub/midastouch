"""Ancient-window validation — executes docs/ANCIENT_WINDOW_VALIDATION_20260916.md.

Fixed configs (no search), one window (2025-04-20 -> 2025-07-26), one batch.
Usage: python scripts/ancient_window_run.py
Env CERT_DATA_DIR is set HERE before entry_lab is imported (spec-first loader).
"""
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["CERT_DATA_DIR"] = os.path.join(ROOT, "artifacts", "data", "ancient")
# V75 spec truth (per the lab's cross-instrument integrity guard)
os.environ.setdefault("CERT_SPREAD", "18.5")
os.environ.setdefault("CERT_USD_PER_UNIT_PER_LOT", "1.009")
os.environ.setdefault("CERT_MIN_LOT", "0.01")
os.environ.setdefault("CERT_LOT_STEP", "0.001")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import entry_lab as lab  # noqa: E402  (reads CERT_DATA_DIR at import)

WINDOW = (datetime.fromisoformat("2025-04-20"), datetime.fromisoformat("2025-07-26"))
EQUITY = 300.0

CONFIGS = {
    # frozen canonical definitions, copied verbatim from hostile_vs_overfit.CONFIGS
    "shipped": {"tp_mult": 1.8},
    "rebuilt": {"tp_mult": 1.6, "pb_min": 0.60, "pb_max": 0.70,
                "ema_side_filter": True, "disable_mr": True, "use_bandfade": False},
    "gated": {"tp_mult": 1.6, "pb_min": 0.60, "pb_max": 0.70, "ema_side_filter": True,
              "disable_mr": True, "use_bandfade": False,
              "htf_slope_gate": True, "no_mom": True},
}


def gates(n: int, total_r: float, dd: float, mean_r: float) -> dict:
    return {"n>=30": n >= 30, "totalR>0": total_r > 0, "dd<=25%": dd <= 25.0,
            "meanR>=0.05": mean_r >= 0.05}


def main() -> None:
    out = {"window": ["2025-04-20", "2025-07-26"], "equity": EQUITY, "configs": {}}
    for name, kw in CONFIGS.items():
        buf = io.StringIO()
        with redirect_stdout(buf):
            rep = lab.certify(EQUITY, start=WINDOW[0], end=WINDOW[1], **kw)
        s = {k: v for k, v in rep.items() if k not in ("trades", "veto_sample")}
        trades = [{k: t[k] for k in ("t", "strat", "dir", "reg", "z",
                                     "atr_pct", "r", "exit", "sig_t")}
                  for t in rep["trades"]]
        n = s.get("n", 0)
        total_r = s.get("total_r", 0.0)
        dd = s.get("max_drawdown_pct", 0.0)
        mean_r = (total_r / n) if n else 0.0
        g = gates(n, total_r, dd, mean_r)
        out["configs"][name] = {"summary": s, "gates": g, "pass": all(g.values()),
                                "trades": trades}
        print(f"{name:>8}: n={n:>4}  totalR={total_r:+8.2f}  meanR={mean_r:+.3f}  "
              f"DD={dd:5.1f}%  pass={all(g.values())}  {g}")
    with open(os.path.join(ROOT, "artifacts", "ANCIENT_WINDOW_RESULTS.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("artifact written: artifacts/ANCIENT_WINDOW_RESULTS.json")


if __name__ == "__main__":
    main()
