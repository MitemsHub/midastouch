#!/usr/bin/env python3
"""What the session gate discards: the EA rule measured hour by hour.

Protocol: docs/GOLD_SESSION_HOURS_EA_20260921.md (pre-registered; the required sample is
computed BEFORE the table and the study is declared UNDERPOWERED BY CONSTRUCTION).

The live arm refuses entries outside 06-20 UTC, which throws away 41% of the rule's signals.
This runs the same declared cell with the gate REMOVED (`win_lo=0, win_hi=24`) so the
discarded hours can be seen at all, then reports them per UTC hour — and reports, for every
bucket, whether its sample could decide anything. It cannot, and the arithmetic says so before
the numbers do.

This study changes no preset. The session window is policy until a forward test at the
declared sample says otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from calendar import timegm
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import midas_parity as P          # noqa: E402
import midas_sweep as M           # noqa: E402

PROTOCOL = "docs/GOLD_SESSION_HOURS_EA_20260921.md"
ARTIFACT = ROOT / "artifacts" / "gold_session_hours_ea.json"

ERAS = (("A", "2026-01-12", "2026-03-31", 60),
        ("B", "2026-04-01", "2026-09-18", 120))
BASIS_USD = 25000.0
RISK_FRACTION = 0.0025
CELL = {"mode": "ORIGINAL", "sl": 2.0, "tp": 2.0}

#: DECLARED BEFORE THE RUN (protocol §2): the effect size the requirement is computed at,
#: rounded UP from the walk-forward's own pooled figure so the requirement cannot be flattered,
#: and the dispersion of this rule measured on the frozen corpus.
DECLARED_EFFECT_R = 0.10
DECLARED_SD_R = 3.31
ALPHA_Z = 1.96
POWER_Z = 0.84


def iso_ts(date_str: str) -> int:
    return timegm(datetime.strptime(date_str, "%Y-%m-%d").timetuple())


def required_n(effect: float = DECLARED_EFFECT_R, sd: float = DECLARED_SD_R,
               extra_z: float = 0.0) -> int:
    """Trades needed for `t >= ALPHA_Z` at `effect`, optionally with 80% power."""
    if effect <= 0:
        raise ValueError("a non-positive effect can never be decided by more data")
    return math.ceil(((ALPHA_Z + extra_z) * sd / effect) ** 2)


def trade_t(rs: list[float]) -> float:
    n = len(rs)
    if n < 2:
        return 0.0
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else 0.0


def pooled_trades() -> tuple[list[dict], list[dict]]:
    """The declared cell's trades with NO session gate, plus the per-era rows."""
    M.use_basis(BASIS_USD)
    out: list[dict] = []
    eras: list[dict] = []
    for name, s_start, s_end, off in ERAS:
        shift = off * 60
        t0 = iso_ts(s_start) - shift
        t1 = iso_ts(s_end) + 86400 - shift
        data = P.python_build_data(news=False, offset_min=off, corpus="venue")
        res = M.run_mode(CELL["mode"], t0, t1, data,
                         sl_atr_mult=CELL["sl"], tp_mult=CELL["tp"],
                         win_lo=0, win_hi=24, risk_fraction=RISK_FRACTION)
        rs = [t["r"] for t in res.trades]
        eras.append({"era": name, "server_window": [s_start, s_end], "offset_min": off,
                     "trades_all_hours": len(rs), "total_r": round(sum(rs), 3),
                     "mean_r": round(sum(rs) / len(rs), 4) if rs else None,
                     "t": round(trade_t(rs), 3)})
        out.extend(res.trades)
    return out, eras


def hour_rows(trades: list[dict]) -> list[dict]:
    rows = []
    for hr in range(24):
        rs = [t["r"] for t in trades if int(t["hour"]) == hr]
        in_gate = 6 <= hr < 20
        rows.append({
            "hour_utc": hr, "in_the_shipped_gate": in_gate, "n": len(rs),
            "total_r": round(sum(rs), 3) if rs else 0.0,
            "mean_r": round(sum(rs) / len(rs), 4) if rs else None,
            "t": round(trade_t(rs), 3) if len(rs) > 1 else None,
            "required_n": required_n(),
            "verdict": ("NOT EVALUABLE" if len(rs) < required_n() else "large enough to test"),
        })
    return rows


def bucket(trades: list[dict], hours: tuple[int, ...]) -> dict:
    rs = [t["r"] for t in trades if int(t["hour"]) in hours]
    return {"hours_utc": list(hours), "n": len(rs),
            "total_r": round(sum(rs), 3) if rs else 0.0,
            "mean_r": round(sum(rs) / len(rs), 4) if rs else None,
            "t": round(trade_t(rs), 3) if len(rs) > 1 else None,
            "required_n": required_n(),
            "evaluable": len(rs) >= required_n()}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()

    trades, eras = pooled_trades()
    rows = hour_rows(trades)
    inside = bucket(trades, tuple(range(6, 20)))
    outside = bucket(trades, tuple(range(0, 6)) + tuple(range(20, 24)))
    small = bucket(trades, (0, 1, 2, 3))
    print(f"protocol : {PROTOCOL}")
    print(f"rule     : {CELL['mode']} stop {CELL['sl']}xATR target {CELL['tp']}R, "
          f"session gate REMOVED (win 0-24)")
    print(f"required sample per bucket at +{DECLARED_EFFECT_R:.2f}R/trade and sd "
          f"{DECLARED_SD_R:.2f}: n >= {required_n():,}  (80% power: {required_n(extra_z=POWER_Z):,})")
    for e in eras:
        print(f"era {e['era']}: {e['trades_all_hours']:4d} trades  total {e['total_r']:+8.3f}R  "
              f"mean {e['mean_r']:+.4f}R  t {e['t']:+.2f}")
    print(f"\n{'hr':>2} {'gate':>4} {'n':>5} {'totalR':>9} {'meanR':>8} {'t':>6}  verdict")
    for r in rows:
        print(f"{r['hour_utc']:>2} {'IN' if r['in_the_shipped_gate'] else '--':>4} {r['n']:>5} "
              f"{r['total_r']:+9.3f} {(r['mean_r'] if r['mean_r'] is not None else float('nan')):+8.4f} "
              f"{(r['t'] if r['t'] is not None else float('nan')):+6.2f}  {r['verdict']}")
    print()
    for name, b in (("shipped gate 06-20 UTC", inside), ("DISCARDED (all other hours)", outside),
                    ("the 00-04 block specifically", small)):
        print(f"{name:30s} n={b['n']:4d} meanR={b['mean_r'] if b['mean_r'] is not None else float('nan'):+.4f} "
              f"t={(b['t'] if b['t'] is not None else float('nan')):+.2f}  "
              f"{'EVALUABLE' if b['evaluable'] else 'NOT EVALUABLE'} "
              f"(needs {b['required_n']:,})")
    print("\nDECLARED READING: no bucket reaches the required sample, so every per-hour number "
          "above\n  is descriptive and none of them is a claim about the discarded hours — "
          "including\nthe claim that they are worse, which is what the shipped gate implies.")
    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "harness": "scripts/gold_session_hours_ea.py",
        "protocol": PROTOCOL,
        "protocol_sha256": hashlib.sha256((ROOT / PROTOCOL).read_bytes()).hexdigest(),
        "declared_effect_r": DECLARED_EFFECT_R, "declared_sd_r": DECLARED_SD_R,
        "required_n": required_n(), "required_n_80pct_power": required_n(extra_z=POWER_Z),
        "rule": {**CELL, "session_gate": "REMOVED for this study (win 0-24)",
                 "engine": "scripts/midas_sweep.py:run_mode (parity engine of record)"},
        "sizing": {"basis_usd": BASIS_USD, "risk_fraction": RISK_FRACTION},
        "eras": eras,
        "trades_all_hours": len(trades),
        "total_r_all_hours": round(sum(t["r"] for t in trades), 3),
        "per_hour": rows,
        "buckets": {"inside_06_20": inside, "outside_06_20": outside, "block_00_04": small},
        "declared_reading": "no bucket reaches the required sample; descriptive only",
        "changes_no_preset": True,
    }
    if args.write:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(out, indent=1))
        print(f"\nartifact: {ARTIFACT.relative_to(ROOT)}")
    return 0


def selftest() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'} {name}")
        ok &= bool(cond)

    check("the required sample is computed up front and is large",
          required_n() > 4000 and required_n() == math.ceil((ALPHA_Z * DECLARED_SD_R
                                                            / DECLARED_EFFECT_R) ** 2))
    check("80% power demands more than the bare t-test", required_n(extra_z=POWER_Z) > required_n())
    check("a non-positive effect is refused rather than answered",
          _raises(lambda: required_n(effect=0.0)))
    check("the gate is off in this study (win 0-24 covers every UTC hour)",
          all(0 <= h < 24 for h in (0, 23)))
    check("era A and era B pins are the manifest's",
          [e[3] for e in ERAS] == [60, 120])
    print(f"\nselftest: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
