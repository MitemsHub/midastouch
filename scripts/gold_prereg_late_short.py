#!/usr/bin/env python3
"""The pre-registered late-session short test (declaration: docs/GOLD_PREREG_LATE_SHORT_20260921.md).

THE DECLARED RULE, implemented literally and nothing else: take the frozen engine's own
signals, restricted to

  * SHORT side only, entered when the H1 trend (EMA 8 > 21 > 50) and the H4 trend
    (close vs EMA 20) are BOTH down — the engine's own `h1_ok_short` / `h4_ok_short`;
  * entry hour 17..21 UTC (the 17-22 bucket; the engine already refuses entries at or
    after 22:00 by its flat-by rule);
  * the certified exit geometry family (stop 1.0 x ATR, target 3.0R), unchanged;
  * the engine's own ATR band (0.20-0.95 trailing percentiles) and one-Position-at-a-time
    occupancy, unchanged;
  * the venue's measured cost model (spread 1.073 bps, $10/lot round trip), unchanged.

Longs are suppressed by passing all-False H1/H4 long flags into `simulate`, i.e. at the
SIGNAL level — the same way a short-only build would behave — not by deleting trades from
the finished list.

WHAT THE DECLARATION FIXED BEFORE THIS RAN, so the run cannot move the goalposts:

  * the rule above, in full;
  * the sample it needs: **190 trades** at the discovered effect (+0.1329R, sd 1.22) for
    a trade-level t >= 1.5, stated up front;
  * the pass conditions and the kill conditions (`§3` of the declaration).

WHAT IT CANNOT BE, said first: the cell was found on the whole venue window, so any split
of that window is CONTAMINATED as a holdout. The halves below are reported as a robustness
check on a hypothesis, and the only clean test of the declared rule is FORWARD — 190 trades
at the observed ~0.65 trades/day, which is roughly ten months. The verdict line says this
in every run, so no reader has to infer it.
"""
from __future__ import annotations

import argparse
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

#: The declared geometry. Not tuned: it is the certified family's own stop/target pair.
DECLARED_CFG = {"emas": (8, 21, 50), "stop_mult": 1.0, "tp_mult": 3.0,
                "win_lo": 17, "win_hi": 21}
#: The declared sample requirement, from the discovery run (+0.1329R/trade, sd 1.22).
DECLARED_NEEDED = 190
#: The pass / kill thresholds (declaration §3).
PASS_T = 1.5
KILL_MEAN_R = 0.0


def stats(rs: list[float]) -> dict:
    n = len(rs)
    if n < 2:
        return {"n": n, "mean_r": None, "sd": None, "t": None, "total_r": round(sum(rs), 3)}
    mean = sum(rs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rs) / (n - 1))
    return {"n": n, "mean_r": round(mean, 4), "sd": round(sd, 4),
            "t": round(mean / (sd / math.sqrt(n)), 2) if sd > 0 else 0.0,
            "total_r": round(sum(rs), 3)}


def run_rule(B, epoch, n, atr, hours, ok) -> list[dict]:
    """The declared rule, through the frozen engine, with longs suppressed at the signal."""
    fake_long = np.zeros(n, dtype=bool)
    return gw.simulate(B, hours, fake_long, ok["h1_short"], fake_long, ok["h4_short"],
                       atr, DECLARED_CFG, start=gw.WARMUP_BARS, end=n)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default=gw.SYMBOL)
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--out", default="artifacts/gold_prereg_late_short.json")
    a = ap.parse_args(argv)

    B, epoch, n, atr, hours, ok = gg.venue_data(a.symbol, a.bars)
    trades = run_rule(B, epoch, n, atr, hours, ok)
    overall = stats([t["net_r"] for t in trades])
    first = datetime.fromtimestamp(epoch[0], timezone.utc)
    last = datetime.fromtimestamp(epoch[-1], timezone.utc)

    print(f"DECLARED RULE: short-only, H1+H4 both down, 17-21 UTC, stop 1.0xATR, tp 3.0R")
    print(f"window: the venue's served bars {first:%Y-%m-%d} .. {last:%Y-%m-%d} (n={n})")
    print(f"\nPOOLED (the hypothesis, on the window it was found on):")
    print(f"  n={overall['n']} mean={overall['mean_r']}R sd={overall['sd']} "
          f"t={overall['t']} total={overall['total_r']}R")
    print(f"  declared sample requirement: {DECLARED_NEEDED} trades "
          f"-> {'MET' if overall['n'] >= DECLARED_NEEDED else 'NOT MET'}")

    # Halves: a robustness check on a hypothesis, NOT a holdout — the cell was selected on
    # this whole window, so both halves have seen the selection.
    mid = n // 2
    halves = {}
    for label, lo, hi in (("first_half", 0, mid), ("second_half", mid, n)):
        rs = [t["net_r"] for t in trades if lo <= t["entry_i"] < hi]
        halves[label] = {**stats(rs),
                         "from": str(datetime.fromtimestamp(epoch[lo], timezone.utc).date()),
                         "to": str(datetime.fromtimestamp(epoch[min(hi, n) - 1],
                                                          timezone.utc).date())}
        h = halves[label]
        print(f"  {label:<12} {h['from']}..{h['to']}  n={h['n']} mean={h['mean_r']} "
              f"t={h['t']} total={h['total_r']}R")

    rules = ThunderboltClassicRules(account_size=25000.0)
    # The entry-only governor is the one the EA actually runs, so the declared rule is
    # also reported under it — a rule that only works ungoverned is not deployable.
    kept, vetoes = gg.govern(trades, epoch, rules=rules)
    gov = stats([t["net_r"] for t in kept])
    prop = gw.prop_compat(kept, epoch, rules, gg.RISK_USD)
    print(f"\nUNDER THE EA'S OWN GOVERNOR (what the chart would actually have taken):")
    print(f"  n={gov['n']} mean={gov['mean_r']}R t={gov['t']} total={gov['total_r']}R "
          f"vetoes={vetoes or '-'}")
    print(f"  venue rules: worst day {prop['worst_day_r']}R = ${prop['worst_day_usd']:,.0f} "
          f"vs ${prop['daily_limit_usd']:,.0f} | shield/daily breaches "
          f"{len(prop['shield_breaches'])}/{len(prop['daily_breaches'])} -> "
          f"{'SURVIVED' if prop['survived'] else 'BREACHED'}")

    mean = overall["mean_r"] or 0.0
    verdict, why = "INSUFFICIENT EVIDENCE (hypothesis, contaminated window)", (
        "the cell was found on this window; the only clean test is forward")
    if overall["n"] >= DECLARED_NEEDED and mean <= KILL_MEAN_R:
        verdict, why = ("DECLARED DEAD", "the declared sample is in and the mean is <= 0R")
    elif overall["n"] >= DECLARED_NEEDED and (overall["t"] or 0) >= PASS_T and mean > 0:
        verdict, why = ("PASS ON A CONTAMINATED WINDOW — still requires the forward record",
                        "t >= 1.5 with the sample met, but the window saw the selection")
    print(f"\nVERDICT: {verdict}\n  {why}")
    print(f"  forward requirement: {DECLARED_NEEDED} trades after 2026-09-21T13:25Z "
          f"(~10 months at the observed rate) — see docs/GOLD_FORWARD_PREREG_20260921.md")

    out = {"declared": {"cfg": {k: str(v) for k, v in DECLARED_CFG.items()},
                        "side": "short only", "regime": "H1 and H4 both down",
                        "session_utc": "17-21",
                        "needed_trades": DECLARED_NEEDED, "pass_t": PASS_T,
                        "kill_mean_r": KILL_MEAN_R,
                        "declaration": "docs/GOLD_PREREG_LATE_SHORT_20260921.md",
                        "contamination": ("the cell was selected on this whole window, so "
                                          "the halves are a robustness check, not a holdout")},
           "window": [first.isoformat(), last.isoformat()], "bars": n,
           "pooled": overall, "halves": halves, "governed": {**gov, "vetoes": vetoes,
                                                             "prop_compat": prop},
           "verdict": verdict, "reason": why}
    dest = Path(a.out)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nartifact: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
