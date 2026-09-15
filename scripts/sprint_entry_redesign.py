"""Entry-redesign sprint driver — executes docs/SPRINT_ENTRY_REDESIGN_20260915.md.

Families A/B/C run on IS only; the frozen ranking picks <=3 structurally
distinct finalists; OOS runs once per finalist + a fresh shipped-baseline
row; the TRAINING_PROTOCOL §6 gates decide SHIP. Writes
artifacts/train/SPRINT_REPORT.json.
"""
from __future__ import annotations

import io
import itertools
import json
import os
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["CERT_DATA_DIR"] = os.path.join(ROOT, "artifacts", "train")
os.environ["CERT_SPREAD"] = "18.5"
os.environ["CERT_USD_PER_UNIT_PER_LOT"] = "1.009"
os.environ["CERT_MIN_LOT"] = "0.01"
os.environ["CERT_LOT_STEP"] = "0.001"
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import entry_lab as lab  # noqa: E402

EQUITY = 300.0
IS = ("2025-08-01", "2026-06-01")
OOS = ("2026-06-01", "2026-09-03")
SEL = {"min_n": 80, "max_dd": 25.0, "max_streak": 8, "min_wr": 40.0}
GATES = {"min_oos_n": 25, "max_oos_dd": 30.0, "degrade_frac": 0.5,
         "beat_baseline_r": 1.0}
K = ("n", "wins", "win_rate", "total_r", "max_drawdown_pct",
     "worst_loss_streak")


def run(window, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rep = lab.certify(EQUITY, set(), exit_mode="touch",
                          start=datetime.fromisoformat(window[0]) if window[0] else None,
                          end=datetime.fromisoformat(window[1]) if window[1] else None,
                          **kw)
    m = {k: rep[k] for k in K}
    m["mean_r"] = m["total_r"] / m["n"] if m["n"] else 0.0
    return m, rep


def base_cfg(**kw):
    c = dict(tp_mult=1.8, stop_mult=1.0, be_trigger=1.0, plock_z=0.5,
             pb_min=0.60, pb_max=0.75, ema_side_filter=True)
    c.update(kw)
    return c


def eligible(m):
    return (m["n"] >= SEL["min_n"] and m["max_drawdown_pct"] <= SEL["max_dd"]
            and m["worst_loss_streak"] <= SEL["max_streak"]
            and m["win_rate"] >= SEL["min_wr"])


def rank_key(r):
    return (-r["is"]["total_r"], -r["is"]["n"], r["is"]["max_drawdown_pct"])


def main():
    t0 = time.time()
    report = {"protocol": "docs/SPRINT_ENTRY_REDESIGN_20260915.md",
              "generated_utc": datetime.utcnow().isoformat() + "Z",
              "equivalence_proof": "anchors EXACT (ema off/on) — see log",
              "families": {"A": [], "B": [], "C": []}, "finalists": [],
              "oos": {}, "gate_results": {}, "verdict": None}

    # ---- Family A: geometry around the kernel (32 runs) --------------------
    for pb_lo, pb_hi, tp, be, bf in itertools.product(
            (0.50, 0.60), (0.70, 0.80), (1.6, 1.8), (0.8, 1.0), (False, True)):
        c = base_cfg(pb_min=pb_lo, pb_max=pb_hi, tp_mult=tp, be_trigger=be,
                     use_bandfade=bf)
        m, _ = run(IS, **c)
        report["families"]["A"].append({"cfg": c, "is": m})
        print(f"A pb={pb_lo}/{pb_hi} tp={tp} be={be} bf={int(bf)} "
              f"n={m['n']:>3} R={m['total_r']:+7.2f} dd={m['max_drawdown_pct']:5.1f}% "
              f"wr={m['win_rate']:4.1f}% stk={m['worst_loss_streak']}", flush=True)

    # BF gap pricing (frozen curiosity from §0): mean IS R with vs without BF
    def bf_gap(rows):
        on = [r["is"]["total_r"] for r in rows if r["cfg"]["use_bandfade"]]
        off = [r["is"]["total_r"] for r in rows if not r["cfg"]["use_bandfade"]]
        return {"mean_R_bf_on": sum(on) / len(on), "mean_R_bf_off": sum(off) / len(off),
                "gap_R": sum(on) / len(on) - sum(off) / len(off)}
    report["bf_gap_pricing"] = bf_gap(report["families"]["A"])
    print("BF gap (IS):", report["bf_gap_pricing"], flush=True)

    # ---- Family B: structure tightenings on best-2 A geometries (<=64) -----
    a_sorted = sorted(report["families"]["A"], key=rank_key)
    best2 = a_sorted[:2]
    for seed in best2:
        s = seed["cfg"]
        for full, sep, nomr, momc in itertools.product(
                (False, True), (None, 0.30), (False, True), (False, True)):
            c = base_cfg(**{k: s[k] for k in
                            ("pb_min", "pb_max", "tp_mult", "be_trigger",
                             "use_bandfade")},
                         m15_full_stack=full, h1_sep=sep,
                         disable_mr=nomr, mom_confirm=momc)
            m, _ = run(IS, **c)
            report["families"]["B"].append({"cfg": c, "is": m})
            print(f"B pb={c['pb_min']}/{c['pb_max']} tp={c['tp_mult']} "
                  f"bf={int(c['use_bandfade'])} full={int(full)} sep={sep} "
                  f"nomr={int(nomr)} momc={int(momc)} n={m['n']:>3} "
                  f"R={m['total_r']:+7.2f} dd={m['max_drawdown_pct']:5.1f}% "
                  f"stk={m['worst_loss_streak']}", flush=True)

    # ---- Family C: fine steps on top-2 B (8 runs) --------------------------
    b_sorted = sorted(report["families"]["B"], key=rank_key)
    top2b = b_sorted[:2]
    for seed in top2b:
        s = seed["cfg"]
        for dlo, dhi in ((-0.05, 0.0), (0.05, 0.0), (0.0, -0.05), (0.0, 0.05)):
            carry = {k: s[k] for k in s if k in (
                "tp_mult", "be_trigger", "use_bandfade",
                "m15_full_stack", "h1_sep", "disable_mr", "mom_confirm")}
            c = base_cfg(**carry, pb_min=round(s["pb_min"] + dlo, 2),
                         pb_max=round(s["pb_max"] + dhi, 2))
            m, _ = run(IS, **c)
            report["families"]["C"].append({"cfg": c, "is": m})
            print(f"C pb={c['pb_min']}/{c['pb_max']} (from {s['pb_min']}/{s['pb_max']}) "
                  f"n={m['n']:>3} R={m['total_r']:+7.2f} "
                  f"dd={m['max_drawdown_pct']:5.1f}% stk={m['worst_loss_streak']}",
                  flush=True)

    # ---- Frozen ranking over all IS runs -----------------------------------
    pool = (report["families"]["A"] + report["families"]["B"]
            + report["families"]["C"])
    elig = [r for r in pool if eligible(r["is"])]
    elig.sort(key=rank_key)
    report["eligible_count"] = len(elig)
    print(f"\neligible IS runs: {len(elig)}/{len(pool)}")

    # structurally distinct: coarse fingerprint collapses fine-step variants
    def fp(c):
        return (round(c["pb_min"], 1), round(c["pb_max"], 1), c["tp_mult"],
                c["use_bandfade"], c.get("m15_full_stack", False),
                c.get("h1_sep"), c.get("disable_mr", False),
                c.get("mom_confirm", False))
    seen, finalists = set(), []
    for r in elig:
        f = fp(r["cfg"])
        if f in seen:
            continue
        seen.add(f)
        finalists.append(r)
        if len(finalists) == 3:
            break
    report["finalists"] = [{"cfg": f["cfg"], "is": f["is"]} for f in finalists]
    for i, f in enumerate(finalists):
        print(f"finalist {i+1}: R={f['is']['total_r']:+.2f} n={f['is']['n']} "
              f"cfg={f['cfg']}", flush=True)

    # ---- OOS: fresh baseline + one run per finalist ------------------------
    # shipped defaults = module constants (PB band PB_MIN/PB_MAX = 0.30/2.2),
    # NOT the runner CLI defaults — pinned by the n=119/-15.10R training row.
    bm, _ = run(OOS, tp_mult=1.8, stop_mult=1.0, be_trigger=1.0, plock_z=0.5,
                ema_side_filter=False)
    report["oos"]["baseline_shipped"] = bm
    print(f"OOS baseline(shipped): n={bm['n']} R={bm['total_r']:+.2f} "
          f"dd={bm['max_drawdown_pct']:.1f}%", flush=True)

    results = []
    for i, f in enumerate(finalists):
        om, rep = run(OOS, **f["cfg"])
        g = {
            "g1_n": om["n"] >= GATES["min_oos_n"],
            "g2_total_r": om["total_r"] > 0,
            "g3_dd": om["max_drawdown_pct"] <= GATES["max_oos_dd"],
            "g4_degradation": om["mean_r"] >= GATES["degrade_frac"] * f["is"]["mean_r"],
            "g5_beats_baseline": om["total_r"] >= bm["total_r"] + GATES["beat_baseline_r"],
        }
        results.append({"finalist": i + 1, "cfg": f["cfg"], "is": f["is"],
                        "oos": om, "gates": g,
                        "passed": all(g.values())})
        print(f"OOS finalist {i+1}: n={om['n']} R={om['total_r']:+.2f} "
              f"dd={om['max_drawdown_pct']:.1f}% gates="
              f"{''.join('P' if v else 'F' for v in g.values())}", flush=True)
    report["oos"]["finalists"] = results

    ship = [r for r in results if r["passed"]]
    if ship:
        best = max(ship, key=lambda r: r["oos"]["total_r"])
        # ladder stress row (recorded, not gated)
        lm, _ = run(OOS, **{**best["cfg"], "exit_mode": "ladder"})
        report["oos"]["winner_ladder_stress"] = lm
        report["verdict"] = f"SHIP: finalist {best['finalist']} passes all gates"
        report["ship_cfg"] = best["cfg"]
    else:
        report["verdict"] = "NO_SHIP: no finalist passed all five OOS gates"
    _write(report)
    print(f"\nVERDICT: {report['verdict']}")
    print(f"elapsed: {time.time()-t0:.0f}s")


def _write(report):
    out = os.path.join(ROOT, "artifacts", "train", "SPRINT_REPORT.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"report: {out}")


if __name__ == "__main__":
    main()
