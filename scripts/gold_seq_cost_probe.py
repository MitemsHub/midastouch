#!/usr/bin/env python3
"""Does DAILY-SEQ fail because of cost, or for reasons cost cannot reach?

DIAGNOSTIC, NOT A PRE-REGISTERED STUDY. DAILY-SEQ's protocol
(`docs/GOLD_DAILY_SEQ_PROTOCOL.md`) is frozen and its verdict (3/8) stands as recorded.
This probe does not re-score it, does not touch the grid, and writes no verdict. It asks
one question the cost-sensitivity protocol raised for DAILY-ONE and that DAILY-SEQ had
never been asked: **is the failure a cost artefact?**

The method is the strongest available form of the question and it needs no market to be
open: run the frozen pipeline at `m = 0` — free trading, no spread, no commission — and
at `m = 1` (the model as published). If a leg fails at `m = 0`, then no honest measurement
of the live spread can change that leg, because the spread is not being charged at all.
If a leg fails only above some `m`, its failure is a statement about the cost model, and
it is that leg — not the strategy — that Sunday's measurement can overturn.

Nulls are re-run per level and seeded identically, so the direction stream is the same at
both levels and the difference between them is cost alone.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_daily_one as d1  # noqa: E402
import gold_daily_two as d2  # noqa: E402
import gold_walkforward as wf  # noqa: E402
import gold_wfo_v2 as w2  # noqa: E402
from gold_walkforward import tstat  # noqa: E402
from midas_prop.risk.upcomers_rules import ThunderboltClassicRules  # noqa: E402

LEVELS = (0.0, 1.0)
REPS = 200
BASE = wf.SPREAD_BPS


def set_mult(m: float) -> None:
    for mod in (wf, w2, d1):
        if hasattr(mod, "SPREAD_BPS"):
            mod.SPREAD_BPS = BASE * m


def main() -> int:
    rules = ThunderboltClassicRules(account_size=d1.ACCOUNT)
    P = w2.prepare("XAUUSD", bars=60000)
    folds, epoch = P["folds"], P["epoch"]
    out = {"base_spread_bps": BASE, "levels": {}, "generated": None}
    print(f"DAILY-SEQ COST PROBE: levels {LEVELS} x brakes {d2.BRAKES}, null {REPS} reps\n")

    for m in LEVELS:
        set_mult(m)
        level = {"m": m, "bps": round(BASE * m, 3), "arms": {}}
        # Null first, seeded identically at every level: the same coin stream is drawn
        # each time, so nothing but cost differs between levels.
        rng = np.random.default_rng(d1.NULL_SEED)
        nulls = {b: [] for b in d2.BRAKES}
        for _rep in range(REPS):
            for b in d2.BRAKES:
                cfgs = [c for c in d2.configs() if c["brake"] == b]
                nrs, _ = d2.run(P, cfgs, folds, rng=rng)
                nulls[b].append(sum(nrs))
        for b in d2.BRAKES:
            nulls[b].sort()
        for b in d2.BRAKES:
            cfgs = [c for c in d2.configs() if c["brake"] == b]
            rs, tr = d2.run(P, cfgs, folds)
            st = d2.loss_stats(tr, epoch)
            nl = nulls[b]
            p95 = nl[int(0.95 * len(nl)) - 1]
            lo = rules.profit_target_usd / st["total_r"] if st["total_r"] > 0 else math.inf
            hi = (rules.daily_loss_limit_usd / abs(st["worst_loss_run_r"])
                  if st["worst_loss_run_r"] < 0 else math.inf)
            r_ok = 0.0
            if st["total_r"] > 0 and lo <= max(hi, lo * 2):
                r_ok, _p = d1.max_surviving_risk(rules, tr, epoch, lo, max(hi, lo * 2))
            arm = {"total_r": round(st["total_r"], 3), "t": round(tstat(rs), 3),
                   "trades": st["days"], "best_day_share": st["best_day_share"],
                   "survivable_usd": round(r_ok, 2), "null_p95": round(p95, 3),
                   "beats_null": st["total_r"] > p95,
                   "worst_loss_run_r": st["worst_loss_run_r"]}
            level["arms"][str(b)] = arm
            share = st["best_day_share"]
            print(f"m={m:<4} brake={b}  total {st['total_r']:+7.2f}R  t {tstat(rs):+5.2f}  "
                  f"null p95 {p95:+7.2f}  beats {'YES' if arm['beats_null'] else 'no ':>3}  "
                  f"best-day {f'{100 * share:.1f}%' if share else 'n/a':>6}  "
                  f"size ${r_ok:>7,.2f}")
        out["levels"][str(m)] = level
        set_mult(1.0)

    out["generated"] = datetime.now(timezone.utc).isoformat()
    p = ROOT / "artifacts/gold_seq_cost_probe.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))

    print("\n=== READING (does the failure survive free trading?) ===")
    for b in d2.BRAKES:
        a0 = out["levels"]["0.0"]["arms"][str(b)]
        a1 = out["levels"]["1.0"]["arms"][str(b)]
        verdict = ("cost-INDEPENDENT: fails with the spread switched off entirely"
                   if not a0["beats_null"] else
                   "cost-FRAGILE: passes free, fails at the model spread")
        print(f"  brake={b}: {a0['total_r']:+.2f}R at m=0 -> {a1['total_r']:+.2f}R at m=1"
              f"   {verdict}")
    print(f"\nwrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
