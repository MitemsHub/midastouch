#!/usr/bin/env python3
"""ML signal-filter table builder — the frozen floor-mode entry bar.

Turns the featurized v28 dataset (signal_filter_dataset_v1.jsonl) into a
P(win) bucket table the forward EA consults at entry, following the house
meta-label pattern (Lopez de Prado): the model answers "given this context,
is this signal above or below average?" — the EA still decides.

DESIGN, FROZEN BEFORE THE FIRST SHIPPED TABLE (protocol §10.7):

  Bucket key   (side, six-hour block of the entry timestamp). The §10 recon
               (799 trades, all plain M30_REVERSED_EXTREME) shows a large
               simple structure (bucket P(win) 0.32-0.90 vs baseline 0.56)
               and NO out-of-sample ranking skill from the 15-feature GBC
               (mean walk-forward AUC 0.476; calibration flips between
               folds). Small transfers; complexity overfits this coverage.

  Shrinkage    smoothed toward the training-set win rate with alpha = 5.
  Fallback     a bucket with fewer than MIN_BUCKET_N trades falls back to the
               global rate (the EA knows: bucket=P, source=GLOBAL).
  Muted        a bucket whose smoothed rate is within MUTED_EPS of the global
               rate ships as 0.50 in the table — the EA treats exactly 0.50
               as "no opinion". It must never be a veto.

  ACTIVATION   the table ships PASSIVE: the EA prints its read on every
               floor-mode evaluation but never vetoes. It becomes ACTIVE
               (real veto authority) only when the frozen gate below passes
               on fresh re-run data, certified by rerunning this tool in
               --certify mode against an expanded dataset.

  GATE (all legs, else FAIL):
               - n >= 500 featurized trades
               - coverage >= 50% of the registry denominator
               - walk-forward AUC > 0.55 in >= 5 of 6 folds (mean > 0.55)
               - worst single fold expR delta >= -0.05R (no fold may cost)

  PASSIVE never vetoes: with the table's minimum possible rate (0.0) fed to
  the EA's evaluate, the decision is TAKE (pinned by test).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

ART = REPO / "artifacts" / "v28_research"
DATASET = ART / "signal_filter_dataset_v1.jsonl"
TABLE_OUT = REPO / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_filter_table_A2.csv"
REPORT_OUT = ART / "filter_table_build_20260916.json"

# ---- frozen design constants --------------------------------------------------
BUCKET_HOURS = 6            # four time-of-day blocks
ALPHA = 5.0                 # Laplace-style shrinkage weight
MIN_BUCKET_N = 15           # below this a bucket ships as GLOBAL fallback
MUTED_EPS = 0.02            # within this of global -> muted 0.50
TABLE_VERSION = "bucket-side-tod-v0"

# activation gate (protocol §10.7, frozen 2026-09-16)
GATE_MIN_N = 500
GATE_MIN_COVERAGE = 0.50
GATE_COVERAGE_DENOMINATOR = 8426
GATE_MIN_FOLDS_AUC = 5      # of 6 folds above...
GATE_FOLD_AUC = 0.55        # ...this threshold
GATE_MEAN_AUC = 0.55
GATE_WORST_FOLD_DELTA = -0.05

# current status (recon numbers, protocol §10.7): every activation leg fails
CURRENT_N = 799
CURRENT_COVERAGE = 799 / 8426
CURRENT_AUC_FOLDS_ABOVE = 3
CURRENT_MEAN_AUC = 0.476

TABLE_HEADER = ("# MITEMSHUB signal-filter bucket table — consult-only unless "
                "ACTIVATION=ACTIVE\n"
                "# version,bucket_side,bucket_tod,p_win,source\n")


# ---- bucket math ----------------------------------------------------------------
def bucket_key(side: str, entry_ts: str) -> tuple[str, int]:
    return (side, int(entry_ts[11:13]) // BUCKET_HOURS)


def build_table(rows: list[dict]) -> tuple[dict, float]:
    """Smoothed per-bucket P(win) vs the global rate. A bucket below
    MIN_BUCKET_N is not in the table (caller falls back)."""
    glob_w = sum(1 for r in rows if r["label_win"])
    glob_n = len(rows)
    base = glob_w / glob_n
    agg: dict = defaultdict(lambda: [0, 0])
    for r in rows:
        k = bucket_key(r["side"], r["ts"])
        agg[k][0] += 1
        agg[k][1] += 1 if r["label_win"] else 0
    out = {}
    for k, (n, w) in sorted(agg.items()):
        if n < MIN_BUCKET_N:
            continue
        p = (w + ALPHA * base) / (n + ALPHA)
        if abs(p - base) <= MUTED_EPS:
            p = 0.50                       # muted: no opinion, never a veto
        out[k] = round(p, 4)
    return out, base


def evaluate_table(table: dict, base: float, rows: list[dict]) -> dict:
    """expR / keep-rate if the (ACTIVE) keep rule P >= base were applied."""
    keep = [r for r in rows
            if (table.get(bucket_key(r["side"], r["ts"])) or base) >= base]
    if not rows:
        return {"kept_expr": 0.0, "baseline_expr": 0.0, "keep_rate": 0.0}
    kept_r = sum(r["r"] for r in keep) / len(keep) if keep else 0.0
    base_r = sum(r["r"] for r in rows) / len(rows)
    return {"kept_expr": round(kept_r, 4), "baseline_expr": round(base_r, 4),
            "keep_rate": round(len(keep) / len(rows), 4)}


# ---- walk-forward feasibility (the gate's evidence) --------------------------------
def walk_forward_auc(rows: list[dict]) -> dict:
    """Expanding-window folds, 1-month embargo, per protocol §10.3."""
    months = sorted({r["ts"][:7] for r in rows})
    folds = []
    for vi in range(len(months) - 6, len(months)):
        if vi < 1:
            continue
        vm = months[vi]
        train_m = set(months[:vi - 1])
        tr = [r for r in rows if r["ts"][:7] in train_m]
        va = [r for r in rows if r["ts"][:7] == vm]
        if not tr or not va:
            continue
        tab, base = build_table(tr)
        pv = [tab.get(bucket_key(r["side"], r["ts"])) or base for r in va]
        yv = [1 if r["label_win"] else 0 for r in va]
        a = _auc(pv, yv)
        ev = evaluate_table(tab, base, va)
        folds.append({"val_month": vm, "auc": None if a is None else round(a, 4),
                      "kept_expr": ev["kept_expr"], "baseline_expr": ev["baseline_expr"],
                      "keep_rate": ev["keep_rate"]})
    return {"folds": folds}


def _auc(p: list[float], y: list[int]) -> float | None:
    p, y = np.asarray(p), np.asarray(y)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    gt = (pos[:, None] > neg[None, :]).sum()
    eq = (pos[:, None] == neg[None, :]).sum()
    return (gt + 0.5 * eq) / (len(pos) * len(neg))


def evaluate_gate(wf: dict, n: int, coverage: float) -> dict:
    folds = wf.get("folds", [])
    aucs = [f["auc"] for f in folds if f["auc"] is not None]
    above = sum(1 for a in aucs if a > GATE_FOLD_AUC)
    mean_auc = float(np.mean(aucs)) if aucs else 0.0
    deltas = [f["kept_expr"] - f["baseline_expr"] for f in folds]
    worst = min(deltas) if deltas else -1.0
    legs = {
        "n_trades": {"value": n, "pass": n >= GATE_MIN_N},
        "coverage": {"value": round(coverage, 4), "pass": coverage >= GATE_MIN_COVERAGE},
        "folds_auc_above": {"value": f"{above}/{len(aucs)}",
                            "pass": above >= GATE_MIN_FOLDS_AUC},
        "mean_auc": {"value": round(mean_auc, 4), "pass": mean_auc > GATE_MEAN_AUC},
        "worst_fold_delta_r": {"value": round(worst, 4),
                               "pass": worst >= GATE_WORST_FOLD_DELTA},
    }
    return {"legs": legs,
            "verdict": "PASS" if all(l["pass"] for l in legs.values()) else "FAIL"}


# ---- artifact -----------------------------------------------------------------
def write_table_csv(path: Path, table: dict, activation: str, base: float) -> None:
    lines = [TABLE_HEADER,
             f"# ACTIVATION={activation}\n",
             "# meta\n",
             f"version={TABLE_VERSION},global_rate={base:.4f}\n"]
    lines.append(f"# global_rate={base:.4f}\n")
    for (side, tod), p in sorted(table.items()):
        lines.append(f"{side},{tod},{p:.4f},BUCKET\n")
    lines.append(f"*,*,{base:.4f},GLOBAL\n")
    path.write_text("".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--certify", action="store_true",
                    help="re-check the frozen gate against the CURRENT dataset")
    ap.add_argument("--dataset", type=Path, default=DATASET)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.dataset) if l.strip()]
    table, base = build_table(rows)
    wf = walk_forward_auc(rows)
    cov = len(rows) / GATE_COVERAGE_DENOMINATOR
    gate = evaluate_gate(wf, len(rows), cov)

    activation = "ACTIVE" if gate["verdict"] == "PASS" else "PASSIVE"
    write_table_csv(TABLE_OUT, table, activation, base)
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "table_version": TABLE_VERSION,
        "dataset_n": len(rows),
        "coverage": round(cov, 4),
        "buckets": {f"{s}|{t}": p for (s, t), p in table.items()},
        "global_rate": round(base, 4),
        "walk_forward": wf,
        "activation_gate": gate,
        "activation": activation,
        "recon_disclosure": {
            "recon_date": "2026-09-16",
            "gbc_verdict_note": "the 15-feature GBC (§10.4) showed no "
                                "out-of-window ranking skill (mean wf AUC "
                                "0.476, calibration flips) — FAIL stands",
            "bucket_auc_folds_above": CURRENT_AUC_FOLDS_ABOVE,
            "bucket_mean_auc": CURRENT_MEAN_AUC,
            "trigger_coverage": "all featurized trades are "
                                "M30_REVERSED_EXTREME — conviction class is "
                                "not learnable yet and stays rule-based",
        },
    }
    REPORT_OUT.write_text(json.dumps(report, indent=2))
    print(f"table: {TABLE_OUT.name} ({len(table)} buckets + GLOBAL fallback)")
    print(f"gate: {gate['verdict']} -> activation {activation}")
    for k, v in gate["legs"].items():
        print(f"  {k}: {v['value']} [{'PASS' if v['pass'] else 'FAIL'}]")
    return 0 if activation in ("PASSIVE", "ACTIVE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
