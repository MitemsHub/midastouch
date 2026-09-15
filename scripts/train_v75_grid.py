"""V75 parameter training driver — executes docs/TRAINING_PROTOCOL_20260915.md.

Runs the frozen Stage-1/Stage-2 grid on the IS window, applies the frozen
selection rule, then validates the winner + baseline on the untouched OOS
window and writes artifacts/train/TRAINING_REPORT.json.

Data: CERT_DATA_DIR is set to artifacts/train (40k-bar corpus converted to
harness format by the protocol's data step). Selection objective runs in
`touch` fill mode; the winner additionally gets a `ladder` stress row
(recorded, not gated). Equity basis 300 everywhere; auto-disable ON.
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
# V75 instrument truth (spec-integrity guard: all four must accompany CERT_DATA_DIR)
os.environ["CERT_SPREAD"] = "18.5"
os.environ["CERT_USD_PER_UNIT_PER_LOT"] = "1.009"
os.environ["CERT_MIN_LOT"] = "0.01"
os.environ["CERT_LOT_STEP"] = "0.001"
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import study_frozen_certify_v75 as hz  # noqa: E402  (env must be set first)

EQUITY = 300.0
IS_START, IS_END = "2025-08-01", "2026-06-01"
OOS_START, OOS_END = "2026-06-01", "2026-09-03"  # exclusive end; corpus ends 09-02
SEL = {"min_n": 80, "max_dd": 25.0, "max_streak": 8, "min_wr": 40.0}
GATES = {"min_oos_n": 25, "max_oos_dd": 30.0, "degrade_frac": 0.5,
         "beat_baseline_r": 1.0}


def run(window, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rep = hz.certify(EQUITY, set(), exit_mode="touch",
                         start=datetime.fromisoformat(window[0]) if window[0] else None,
                         end=datetime.fromisoformat(window[1]) if window[1] else None,
                         **kw)
    m = {k: rep[k] for k in ("n", "wins", "win_rate", "total_r",
                             "max_drawdown_pct", "worst_loss_streak")}
    m["mean_r"] = m["total_r"] / m["n"] if m["n"] else 0.0
    return m


def cfg(**kw):
    base = dict(tp_mult=1.8, stop_mult=1.0, be_trigger=1.0, plock_z=0.5,
                pb_min=0.60, pb_max=0.75)
    base.update(kw)
    return base


def main():
    t0 = time.time()
    report = {"protocol": "docs/TRAINING_PROTOCOL_20260915.md",
              "generated_utc": datetime.utcnow().isoformat() + "Z",
              "fill_mode": "touch", "equity_basis": EQUITY,
              "splits": {"is": [IS_START, IS_END], "oos": [OOS_START, OOS_END]},
              "selection_rule": SEL, "gates": GATES,
              "stage1": [], "stage2": [], "oos": {}}

    def key(c):
        return (c["tp_mult"], c["stop_mult"], c["be_trigger"], c["plock_z"])

    # ---- Stage 1 grid -----------------------------------------------------
    for tp, sm, be, pz in itertools.product((1.6, 1.8, 2.0, 2.4),
                                            (0.9, 1.0, 1.15),
                                            (0.8, 1.0, 1.2),
                                            (0.4, 0.5, 0.6)):
        c = cfg(tp_mult=tp, stop_mult=sm, be_trigger=be, plock_z=pz)
        m = run((IS_START, IS_END), **c)
        report["stage1"].append({"cfg": c, "is": m})
        print(f"S1 tp={tp} sm={sm} be={be} pz={pz} n={m['n']:>3} "
              f"R={m['total_r']:+7.2f} dd={m['max_drawdown_pct']:5.1f}% "
              f"wr={m['win_rate']:4.1f}% stk={m['worst_loss_streak']}", flush=True)

    # ---- Frozen selection rule -------------------------------------------
    elig = [r for r in report["stage1"]
            if r["is"]["n"] >= SEL["min_n"]
            and r["is"]["max_drawdown_pct"] <= SEL["max_dd"]
            and r["is"]["worst_loss_streak"] <= SEL["max_streak"]
            and r["is"]["win_rate"] >= SEL["min_wr"]]
    elig.sort(key=lambda r: (-r["is"]["total_r"], -r["is"]["n"],
                             r["is"]["max_drawdown_pct"]))
    top8 = elig[:8]
    report["stage1_eligible"] = len(elig)
    print(f"\nstage1 eligible: {len(elig)}/{len(report['stage1'])}; "
          f"top IS R: {top8[0]['is']['total_r'] if top8 else float('nan'):.2f}")

    # ---- Stage 2 grid (top-8 only) ----------------------------------------
    s2 = []
    for r in top8:
        c0 = r["cfg"]
        for pbmin, pbmax, blocks in itertools.product(
                (0.55, 0.60, 0.65), (0.70, 0.75, 0.80), (None, "3,14,20")):
            if blocks is None:
                c = cfg(**{k: c0[k] for k in
                           ("tp_mult", "stop_mult", "be_trigger", "plock_z")},
                        pb_min=pbmin, pb_max=pbmax)
                m = run((IS_START, IS_END), **c)
            else:
                c = dict(c)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rep = hz.certify(
                        EQUITY, {int(h) for h in blocks.split(",")},
                        exit_mode="touch",
                        start=datetime.fromisoformat(IS_START),
                        end=datetime.fromisoformat(IS_END), **c)
                m = {k: rep[k] for k in ("n", "wins", "win_rate", "total_r",
                                         "max_drawdown_pct", "worst_loss_streak")}
                m["mean_r"] = m["total_r"] / m["n"] if m["n"] else 0.0
            s2.append({"cfg": c, "blocks": blocks, "is": m})
            print(f"S2 {c} blocks={blocks} n={m['n']:>3} R={m['total_r']:+7.2f}",
                  flush=True)
    report["stage2"] = s2

    # ---- Final pick (IS only) ---------------------------------------------
    pool = s2 if s2 else [dict(r, blocks=None) for r in elig]
    pool = [p for p in pool
            if p["is"]["n"] >= SEL["min_n"]
            and p["is"]["max_drawdown_pct"] <= SEL["max_dd"]
            and p["is"]["worst_loss_streak"] <= SEL["max_streak"]
            and p["is"]["win_rate"] >= SEL["min_wr"]]
    pool.sort(key=lambda p: (-p["is"]["total_r"], -p["is"]["n"],
                             p["is"]["max_drawdown_pct"]))
    if not pool:
        report["verdict"] = "NO_CANDIDATE (stage-1/2 eligibility empty)"
        _write(report)
        print("\nVERDICT: no eligible candidate; baseline stands")
        return
    winner = pool[0]

    # ---- OOS validation: winner, baseline, ladder stress -------------------
    base = cfg()  # shipped defaults == baseline
    rows = {"winner": winner, "baseline": {"cfg": base, "blocks": None,
                                           "is": run((IS_START, IS_END), **base)}}
    w = dict(winner["cfg"])
    for name, c, blocks in (("winner_oos", w, winner.get("blocks")),
                            ("baseline_oos", base, None)):
        if blocks:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rep = hz.certify(EQUITY, {int(h) for h in blocks.split(",")},
                                 exit_mode="touch",
                                 start=datetime.fromisoformat(OOS_START),
                                 end=datetime.fromisoformat(OOS_END), **c)
            m = {k: rep[k] for k in ("n", "wins", "win_rate", "total_r",
                                     "max_drawdown_pct", "worst_loss_streak")}
        else:
            m = run((OOS_START, OOS_END), **c)
        m["mean_r"] = m["total_r"] / m["n"] if m["n"] else 0.0
        rows[name] = m
        print(f"OOS {name}: n={m['n']} R={m['total_r']:+.2f} "
              f"dd={m['max_drawdown_pct']:.1f}%", flush=True)

    # ladder stress row for the winner (recorded, not gated)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rep = hz.certify(EQUITY, set(), exit_mode="ladder",
                         start=datetime.fromisoformat(OOS_START),
                         end=datetime.fromisoformat(OOS_END), **w)
    rows["winner_oos_ladder_stress"] = {
        k: rep[k] for k in ("n", "wins", "win_rate", "total_r",
                            "max_drawdown_pct", "worst_loss_streak")}
    rows["winner_oos_ladder_stress"]["note"] = (
        "bar-open fill bound; recorded only, not a gate")
    report["oos"] = rows

    # ---- Frozen ship gates -------------------------------------------------
    w_oos, b_oos = rows["winner_oos"], rows["baseline_oos"]
    g = {
        "g1_n": w_oos["n"] >= GATES["min_oos_n"],
        "g2_total_r_positive": w_oos["total_r"] > 0,
        "g3_dd": w_oos["max_drawdown_pct"] <= GATES["max_oos_dd"],
        "g4_degradation": (w_oos["mean_r"]
                           >= GATES["degrade_frac"] * winner["is"]["mean_r"]),
        "g5_beats_baseline": (w_oos["total_r"]
                              >= b_oos["total_r"] + GATES["beat_baseline_r"]),
    }
    report["gate_results"] = g
    report["verdict"] = ("SHIP" if all(g.values())
                         else "NO_SHIP: " + ", ".join(k for k, v in g.items() if not v))
    _write(report)
    print(f"\nVERDICT: {report['verdict']}")
    print(f"elapsed: {time.time()-t0:.0f}s")


def _write(report):
    out = os.path.join(ROOT, "artifacts", "train", "TRAINING_REPORT.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"report: {out}")


if __name__ == "__main__":
    main()
