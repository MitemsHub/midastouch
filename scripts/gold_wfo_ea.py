#!/usr/bin/env python3
"""Pre-registered walk-forward of the EA'S OWN entry rule.

Protocol: docs/GOLD_WFO_EA_PROTOCOL.md (pre-registered BEFORE this file ran; its sha256 is
recorded in the artifact).

WHY THIS EXISTS. The gate the live arm is armed behind — `artifacts/gold_wfo.json`, cited by
`artifacts/live/armed.json` — is a walk-forward of a DIFFERENT strategy family: an M15 EMA
stack with an H1 EMA-stack regime, no Bollinger and no RSI anywhere in the engine. The EA's
trigger is BB(20, 2.0) touch-back-inside or RSI(14) 70/30 with an H1/H4 EMA20 regime. The two
agree on the same bar and the same direction 258 times out of the gate engine's 7,606 signals
(3.4%), so the frozen verdict is evidence about a rule that trades about five times more often
than the one holding orders — and no walk-forward of the EA's rule existed.

This harness supplies it, using the engine of record (`scripts/midas_sweep.py:run_mode`, the
parity-pinned implementation of the EA's rule) rather than a re-implementation, so the rule
certified here is the rule parity compares against the EA.

CLOCK. The venue's served window crosses one measured DST step, so a single offset does not
exist for it (`midas_parity.measure_server_offset_min` returns None — the correct refusal,
and `--selftest` pins that this harness refuses too). The WFO therefore runs per era, each
with the offset pinned in `configs/mt5/server_offsets.json` and each validated forward by a
parity pass, and no fold crosses an era boundary.
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

import gold_walkforward as gw          # noqa: E402  (folds, criteria, control, PBO)
import midas_parity as P               # noqa: E402
import midas_sweep as M                # noqa: E402

PROTOCOL = "docs/GOLD_WFO_EA_PROTOCOL.md"
ARTIFACT = ROOT / "artifacts" / "gold_wfo_ea.json"

FOLD_DAYS = 8
#: (name, first server date, last server date, pinned offset in minutes)
ERAS = (("A", "2026-01-12", "2026-03-31", 60),
        ("B", "2026-04-01", "2026-09-18", 120))

MODES = ("ORIGINAL", "REVERSE_DIRECTION", "REVERSE_TRIGGER", "REVERSE_BOTH",
         "LONG_ONLY", "SHORT_ONLY", "MACRO_ONLY", "TRIGGER_ONLY")
STOPS = (1.0, 1.5, 2.0)
TPS = (1.5, 2.0, 3.0)
WINDOWS = ((6, 20), (13, 18))

BASIS_USD = 25000.0        # the U25 mirror's evaluation size (== midas_parity.ACCOUNT_BASIS_USD)
RISK_FRACTION = 0.0025     # the arm's armed risk (preset InpRiskPercent = 0.25)

CONTROL_SEED = 20260921
CONTROL_REPS = 200
#: The arm's own configuration, declared in the protocol as a separate no-selection reading.
ARMED_CELL = {"mode": "ORIGINAL", "sl": 2.0, "tp": 2.0, "win": (6, 20)}


def iso_ts(date_str: str) -> int:
    return timegm(datetime.strptime(date_str, "%Y-%m-%d").timetuple())


def grid() -> list[dict]:
    """The closed 144-configuration grid, in a fixed order (mode, stop, target, window)."""
    out = []
    for mode in MODES:
        for sl in STOPS:
            for tp in TPS:
                for win in WINDOWS:
                    out.append({"mode": mode, "sl": sl, "tp": tp, "win": win})
    return out


def cfg_key(cfg: dict) -> str:
    return f"{cfg['mode']}|{cfg['sl']}|{cfg['tp']}|{cfg['win'][0]}-{cfg['win'][1]}"


def cfg_index(cfgs: list[dict], want: dict) -> int:
    for i, c in enumerate(cfgs):
        if c == want:
            return i
    raise SystemExit(f"the declared cell is not in the grid: {cfg_key(want)} — the grid and "
                     f"the protocol have diverged")


def era_bounds(server_start: str, server_end: str, offset_min: int) -> tuple[int, int]:
    """[t0, t1] in UTC for one era, aligned to the venue's own day boundaries.

    The window is declared in SERVER dates (that is how the venue's series is stamped), so
    both boundaries move with the era's offset — server midnight is not UTC midnight here.
    """
    shift = offset_min * 60
    return iso_ts(server_start) - shift, iso_ts(server_end) + 86400 - shift


def era_folds(t0: int, t1: int) -> list[tuple[str, int, int]]:
    """Contiguous 8-day fold blocks over [t0, t1), named F01.. within the era."""
    out, cur, n = [], t0, 0
    while cur + FOLD_DAYS * 86400 <= t1:
        out.append((f"F{n + 1:02d}", cur, cur + FOLD_DAYS * 86400))
        cur += FOLD_DAYS * 86400
        n += 1
    return out


def run_cfg(cfg: dict, data: dict, t0: int, t1: int) -> list[dict]:
    return M.run_mode(cfg["mode"], t0, t1, data,
                      sl_atr_mult=cfg["sl"], tp_mult=cfg["tp"],
                      win_lo=cfg["win"][0], win_hi=cfg["win"][1],
                      risk_fraction=RISK_FRACTION).trades


def fold_sums(trades: list[dict], folds: list[tuple[str, int, int]]) -> list[float]:
    """Total R per fold, attributed by the trade's ENTRY bar (same rule as the frozen WFO)."""
    return [round(sum(t["r"] for t in trades if f0 <= t["open_ct"] < f1), 4)
            for _n, f0, f1 in folds]


def session_indices(data: dict, t0: int, t1: int, win: tuple[int, int]) -> list[int]:
    """The bars the control may draw an entry from: inside the era and inside the window."""
    out = []
    for i, b in enumerate(data["m15"]):
        if not (t0 <= b["time"] <= t1):
            continue
        if win[0] <= datetime.fromtimestamp(b["time"], timezone.utc).hour < win[1]:
            out.append(i)
    return out


def control(data: dict, cfg: dict, t0: int, t1: int, n_trades: int,
            seed: int = CONTROL_SEED, reps: int = CONTROL_REPS) -> dict:
    """V4: random entry timing and direction, same engine, geometry, window and cost model.

    Implemented by feeding the engine of record a synthetic trigger series (±1 at randomly
    drawn in-session bars, RSI neutral so only that series can fire) and running the mode that
    takes the trigger's own direction. Nothing about the fills, the stop, the target, the
    timeout, the min-lot floor or the amendment-6 veto is bypassed — only *when* and *which
    way* is randomised, which is the one thing the rule claims as its edge.
    """
    usable = session_indices(data, t0, t1, cfg["win"])
    if not usable or n_trades <= 0:
        return {"reps": 0, "usable_bars": len(usable), "mean_total_r": None,
                "reason": "no usable session bars, or the controlled configuration traded not at all"}
    rng = np.random.default_rng(seed)
    n = min(n_trades, len(usable))
    totals, counts = [], []
    neutral_rsi = [50.0] * len(data["m15"])
    for _ in range(reps):
        bb = [0] * len(data["m15"])
        for i in rng.choice(usable, size=n, replace=False):
            bb[int(i)] = 1 if rng.random() < 0.5 else -1
        synth = {**data, "m15_bb": bb, "m15_rsi": neutral_rsi}
        res = M.run_mode("TRIGGER_ONLY", t0, t1, synth,
                         sl_atr_mult=cfg["sl"], tp_mult=cfg["tp"],
                         win_lo=cfg["win"][0], win_hi=cfg["win"][1],
                         risk_fraction=RISK_FRACTION)
        totals.append(round(sum(t["r"] for t in res.trades), 4))
        counts.append(len(res.trades))
    tot = sorted(totals)
    return {
        "reps": reps, "seed": seed, "usable_bars": len(usable),
        "signals_drawn": n, "realized_trades_mean": round(float(np.mean(counts)), 1),
        "mean_total_r": round(float(np.mean(totals)), 3),
        "median_total_r": round(float(np.median(totals)), 3),
        "min_total_r": tot[0], "max_total_r": tot[-1],
        "std_total_r": round(float(np.std(totals)), 3),
        "share_of_reps_positive": (round(sum(1 for x in totals if x > 0) / reps, 3)
                                  if reps else None),
    }


def selection_path(matrix: np.ndarray, cfgs: list[dict]) -> dict:
    """Select on fold k, score on fold k+1 only. Mirrors gold_walkforward.main()'s loop."""
    n_folds = matrix.shape[1]
    prev = int(np.argmax(matrix.sum(axis=1)))
    oos, picks = [], []
    for k in range(1, n_folds):
        scored = sorted(((matrix[i, k - 1], -cfgs[i]["sl"], -cfgs[i]["tp"],
                          -cfgs[i]["win"][0], -i, i) for i in range(len(cfgs))),
                        reverse=True)
        if scored[0][0] != 0.0:
            prev = scored[0][5]
        oos.append(round(float(matrix[prev, k]), 4))
        picks.append({"fold": k + 1, "selected_on": k, "pick": cfg_key(cfgs[prev])})
    return {"oos_r_per_fold": oos, "picks": picks,
            "distinct_picks": len({p["pick"] for p in picks})}


def leave_one_out(rs: list[float]) -> dict:
    if not rs:
        return {}
    return {"total": round(sum(rs), 3), "without_best": round(sum(rs) - max(rs), 3),
            "worst_fold_r": round(min(rs), 3),
            "without_worst": round(sum(rs) - min(rs), 3), "best_fold_r": round(max(rs), 3)}


def evaluate(rs: list[float], control_total: float, trials: int) -> dict:
    return gw.criteria(rs, control_total, trials=trials)


def failing_legs(crit: dict) -> list[str]:
    return [k for k, v in crit.items() if not k.startswith("_") and not v]


def verdict_block(cfg: dict) -> dict:
    return {"mode": cfg["mode"], "stop_atr_mult": cfg["sl"], "tp_mult": cfg["tp"],
            "window_utc": list(cfg["win"])}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="write artifacts/gold_wfo_ea.json")
    ap.add_argument("--selftest", action="store_true", help="pin the structure, refuse nothing")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    cfgs = grid()
    arm_i = cfg_index(cfgs, ARMED_CELL)
    M.use_basis(BASIS_USD)      # the engine of record owns the basis; called once, before any run

    print(f"protocol : {PROTOCOL}")
    print(f"grid     : {len(cfgs)} configurations "
          f"({len(MODES)} modes x {len(STOPS)} stops x {len(TPS)} targets x {len(WINDOWS)} windows)")
    print(f"sizing   : basis ${BASIS_USD:,.0f} at {RISK_FRACTION:.4%} "
          f"(min lot {M.MIN_LOT}, amendment-6 cap {M.MAX_RISK_FRACTION:.0%})")

    era_rows, pooled_matrix, pooled_folds, fold_labels = [], [], [], []
    era_cfg_counts: dict[str, list[int]] = {}
    cell_fold_r, cell_meta = [], {}
    for name, s_start, s_end, off in ERAS:
        t0, t1 = era_bounds(s_start, s_end, off)
        data = P.python_build_data(news=False, offset_min=off, corpus="venue")
        folds = era_folds(t0, t1)
        bars = [b for b in data["m15"] if t0 <= b["time"] <= t1]
        print(f"\nera {name}   : {s_start} -> {s_end} server, offset {off:+d}m "
              f"| {len(bars)} M15 bars | {len(folds)} folds of {FOLD_DAYS}d")
        trades_by_cfg = []
        for cfg in cfgs:
            trades_by_cfg.append(run_cfg(cfg, data, t0, t1))
        matrix = np.array([fold_sums(tr, folds) for tr in trades_by_cfg], dtype=float)
        er = {"name": name, "server_window": [s_start, s_end], "offset_min": off,
              "bars": len(bars), "folds": len(folds),
              "oos_trades_all_configs": int(sum(len(x) for x in trades_by_cfg)),
              "matrix_total_r": [round(float(v), 3) for v in matrix.sum(axis=1)]}
        cell = trades_by_cfg[arm_i]
        er["declared_cell_trades"] = len(cell)
        er["declared_cell_total_r"] = round(sum(t["r"] for t in cell), 3)
        era_rows.append(er)
        pooled_matrix.append(matrix)
        pooled_folds.extend(folds)
        fold_labels.extend(f"{name}{f[0]}" for f in folds)
        era_cfg_counts[name] = [len(x) for x in trades_by_cfg]
        cell_fold_r.extend(matrix[arm_i].tolist())
        t = gw.tstat(matrix[arm_i].tolist())
        print(f"  declared cell: {len(cell):4d} trades  total {sum(t['r'] for t in cell):+8.3f}R  "
              f"fold-mean t = {t:+.2f}")
        cell_meta[name] = {"trades": len(cell), "total_r": round(sum(t["r"] for t in cell), 3),
                           "t": round(t, 3),
                           "per_fold_r": [round(v, 4) for v in matrix[arm_i].tolist()]}

    # POOLED ALONG THE FOLD AXIS, not vstacked: each era contributes its own folds (9 + 21),
    # and stacking them as rows would make the fold count disagree with the window it names.
    matrix = np.hstack(pooled_matrix)
    print(f"\npooled   : {matrix.shape[1]} folds over {matrix.shape[0]} configurations")

    sel = selection_path(matrix, cfgs)
    cell_r = [round(v, 4) for v in cell_fold_r]
    cell_t = gw.tstat(cell_r)
    cell_total = sum(cell_r)
    selected_total = sum(sel["oos_r_per_fold"])

    print(f"\nselected path: {len(sel['oos_r_per_fold'])} OOS folds, total {selected_total:+.3f}R, "
          f"fold-mean t {gw.tstat(sel['oos_r_per_fold']):+.2f}, "
          f"{sel['distinct_picks']} distinct picks")
    print(f"declared cell: {len(cell_r)} folds, total {cell_total:+.3f}R, t {cell_t:+.2f} "
          f"({verdict_block(ARMED_CELL)})")

    # ---- controls (V4), for the selected winner and the declared cell -------------------
    win_i = cfg_index(cfgs, ARMED_CELL)
    last_pick = sel["picks"][-1]["pick"] if sel["picks"] else cfg_key(ARMED_CELL)
    for i, c in enumerate(cfgs):
        if cfg_key(c) == last_pick:
            win_i = i
    print(f"\ncontrol      : {CONTROL_REPS} random-entry repetitions, seed {CONTROL_SEED}")
    ctrl_cell, ctrl_sel = {}, {}
    for name, s_start, s_end, off in ERAS:
        t0, t1 = era_bounds(s_start, s_end, off)
        data = P.python_build_data(news=False, offset_min=off, corpus="venue")
        n_cell = cell_meta[name]["trades"]
        ctrl_cell[name] = control(data, ARMED_CELL, t0, t1, n_cell)
        n_sel = era_cfg_counts[name][win_i]
        ctrl_sel[name] = control(data, cfgs[win_i], t0, t1, n_sel, seed=CONTROL_SEED + 1)
        print(f"  era {name}: declared-cell control mean {ctrl_cell[name].get('mean_total_r')}R "
              f"vs the cell's own {cell_meta[name]['total_r']:+.3f}R")

    ctrl_cell_total = round(sum(v.get("mean_total_r") or 0.0 for v in ctrl_cell.values()), 3)
    ctrl_sel_total = round(sum(v.get("mean_total_r") or 0.0 for v in ctrl_sel.values()), 3)

    sel_crit = evaluate(sel["oos_r_per_fold"], ctrl_sel_total, trials=len(cfgs))
    cell_crit = evaluate(cell_r, ctrl_cell_total, trials=1)
    pbo = gw.probability_of_backtest_overfitting(matrix, n_splits=8)

    legs_ok = not failing_legs(sel_crit)
    cell_ok = cell_t >= 1.96
    verdict = "PASS" if (legs_ok and cell_ok) else "NOT VALIDATED"

    print(f"\ncriteria (selected path, {len(cfgs)} trials, control {ctrl_sel_total:+.2f}R):")
    for k, v in sel_crit.items():
        if not k.startswith("_"):
            print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"  _t={sel_crit['_t']:+.3f} _median={sel_crit['_median']:+.3f} "
          f"_pos={sel_crit['_pos']}/{sel_crit['_n']} _t_req={sel_crit['_t_req']:.3f}")
    print(f"\ncriteria (declared cell, 1 trial, control {ctrl_cell_total:+.2f}R):")
    for k, v in cell_crit.items():
        if not k.startswith("_"):
            print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"\nPBO (CSCV vs {pbo.get('windows')} windows): {pbo.get('pbo')} "
          f"over {pbo.get('n_combos')} combinations")
    print(f"\nVERDICT: {verdict}"
          + (f"  (failing: {', '.join(failing_legs(sel_crit))})" if failing_legs(sel_crit) else "")
          + ("" if cell_ok else f"  (declared cell t={cell_t:+.2f} < 1.96)"))

    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "harness": "scripts/gold_wfo_ea.py",
        "protocol": PROTOCOL,
        "protocol_sha256": hashlib.sha256((ROOT / PROTOCOL).read_bytes()).hexdigest(),
        "verdict": verdict,
        "failing_legs": failing_legs(sel_crit),
        "declared_cell_t_ok": cell_ok,
        "rule": {"trigger": "M15 BB(20,2.0) touch-back-inside or RSI(14) 70/30",
                 "regime": "H1 EMA20 and H4 EMA20 agreeing",
                 "engine": "scripts/midas_sweep.py:run_mode (the parity engine of record)",
                 "implementation_note": "the rule is NOT re-implemented here; the certified "
                                        "code path is the one parity compares against the EA"},
        "why": "the frozen gate (artifacts/gold_wfo.json) measures an EMA-stack family, not "
               "the rule the EA trades; this is the walk-forward of the EA's own rule",
        "spec": {"folds": FOLD_DAYS, "n_configs": len(cfgs), "modes": list(MODES),
                 "stops": list(STOPS), "targets": list(TPS),
                 "windows": [list(w) for w in WINDOWS],
                 "basis_usd": BASIS_USD, "risk_fraction": RISK_FRACTION,
                 "min_lot": M.MIN_LOT, "amendment6_cap": M.MAX_RISK_FRACTION,
                 "control": {"seed": CONTROL_SEED, "reps": CONTROL_REPS},
                 "criteria_source": "scripts/gold_walkforward.py:criteria "
                                    "(docs/GOLD_WFO_PROTOCOL.md section 6, V1-V7)",
                 "eras": [{"name": n, "server_window": [a, b], "offset_min": o}
                          for n, a, b, o in ERAS]},
        "eras": era_rows,
        "declared_cell": {"cfg": verdict_block(ARMED_CELL), "per_era": cell_meta,
                          "per_fold_r": cell_r, "total_r": round(cell_total, 3),
                          "mean_r": round(cell_total / len(cell_r), 4) if cell_r else None,
                          "t": round(cell_t, 3), "criteria": cell_crit,
                          "leave_one_fold_out": leave_one_out(cell_r),
                          "control": {"per_era": ctrl_cell, "total_r": ctrl_cell_total}},
        "selected_path": {"oos_r_per_fold": sel["oos_r_per_fold"],
                          "total_r": round(selected_total, 3),
                          "mean_r": round(selected_total / len(sel["oos_r_per_fold"]), 4),
                          "t": round(gw.tstat(sel["oos_r_per_fold"]), 3),
                          "distinct_picks": sel["distinct_picks"],
                          "last_pick": last_pick, "criteria": sel_crit,
                          "leave_one_fold_out": leave_one_out(sel["oos_r_per_fold"]),
                          "control": {"per_era": ctrl_sel, "total_r": ctrl_sel_total}},
        "pbo": pbo,
        "matrix": {"configs": [cfg_key(c) for c in cfgs], "folds": fold_labels,
                   "rows": [[round(float(v), 4) for v in row] for row in matrix.tolist()]},
        "selection_rule": "win on fold k by total R, ties by (lower stop, lower target, lower "
                          "window start, lower grid index); score that pick on fold k+1 only"
                          f"; pooled fold sequence = {len(pooled_folds)} folds "
                          f"({len(ERAS)} eras, no fold crosses an era boundary)",
        "look_already_taken": {
            "what": "this window is NOT blind. The rule has been run on it before: parity "
                    "passes in REVERSE_DIRECTION mode, and the armed record quotes the armed "
                    "mode at +0.1149R/trade over n=138 (t=1.22).",
            "what_is_new": "the fold structure, the selection procedure, the control, the "
                           "newest bars, and the criteria applied to the arm's own "
                           "configuration with no selection at all.",
            "what_a_pass_would_not_do": "arm anything. Arming is an arming-record event "
                                        "(artifacts/live/armed.json), never a protocol result.",
            "what_a_fail_does_not_do": "change the live arm. It is authorised by an operator "
                                       "override on a FAILED gate, recorded as such.",
        },
    }
    if args.write:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(out, indent=1))
        print(f"\nartifact: {ARTIFACT.relative_to(ROOT)}")
    else:
        print("\n(dry run: --write not passed, nothing written)")
    return 0 if verdict == "PASS" else 1


def selftest() -> int:
    """Structure pins: grid, folds, the declared cell's presence, and the clock refusal."""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'} {name}")
        ok &= bool(cond)

    cfgs = grid()
    check("grid is the declared 144 configurations", len(cfgs) == 144)
    check("grid keys are unique", len({cfg_key(c) for c in cfgs}) == 144)
    check("the arm's own configuration is in the grid", cfg_index(cfgs, ARMED_CELL) >= 0)
    check("every mode the EA implements is in the grid", set(MODES) == set(M.MODES))
    for name, s, e, off in ERAS:
        folds = era_folds(*era_bounds(s, e, off))
        want = 9 if name == "A" else 21
        check(f"era {name}: {want} folds of {FOLD_DAYS}d", len(folds) == want)
    check("pooled folds = 30 (the frozen protocol's structure)",
          sum(len(era_folds(*era_bounds(s, e, o))) for _n, s, e, o in ERAS) == 30)
    off, per_month = P.measure_server_offset_min(*era_bounds("2026-01-12", "2026-09-18", 0))
    check("the whole window is refused one clock (this harness must split it)", off is None)
    check("both era offsets are pinned in the manifest",
          per_month.get("2026-01") == 60 and per_month.get("2026-04") == 120)
    check("run_mode's defaults are the certified values",
          M.SL_ATR_MULT == 2.0 and M.TP_MULT == 2.0 and (M.SESSION_LO, M.SESSION_HI) == (6, 20))
    print(f"\nselftest: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
