#!/usr/bin/env python3
"""V28 ML signal-filter track — the §10 pipeline, pre-registered before training.

Builds the decision-time dataset from the v28 tester registry joined to
per-trade journal telemetry (OPEN/CLOSE lines), featurizes at the last CLOSED
M15 bar before entry, trains a walk-forward purged/group-capped filter for
REVERSE_BOTH, and applies the frozen §10.4 ship gate. Fail-closed in the house
style: trades without journal evidence never become features; coverage against
the 8,426-trade registry is printed on every run; a gate miss ships nothing.

Writes artifacts/v28_research/signal_filter_report_<ts>.json (and, with
--dataset-out, the featurized trade snapshot for reuse and audit).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

from v75_tester_runner import _tester_roots  # noqa: E402

ART = REPO / "artifacts" / "v28_research"
REGISTRY = ART / "registry.jsonl"
BARS_CSV = REPO / "artifacts" / "data" / "volatility_75_index_m15_40000bars.csv"

# ---- frozen §10 constants ----------------------------------------------------
SEED = 20260916
CANDIDATE_MODE = "V28_REVERSE_BOTH"
REGISTRY_DENOMINATOR = 8426          # total trades across the 61 registry rows
N_FOLDS = 6
EMBARGO_MONTHS = 1                   # one full calendar month between sides
GROUP_CAP = 30                       # per (month x geometry cell) in training
MIN_VAL_TRADES = 10                  # a validation month below this is skipped
GATE_MIN_FOLDS_IMPROVED = 5          # of 6
GATE_MIN_UPLIFT_R = 0.10             # aggregate expR uplift per kept trade
GATE_MIN_KEEP_RATE = 0.35
P_THRESHOLD = 0.5                    # take the trade iff P(win) >= this

FEATURE_VERSION = "v1-decision-time"
MODEL_VERSION = "gbc-frozen-20260916"

# ---- journal parsing ----------------------------------------------------------
# Real line shapes (Agent-*.log, utf-16-le):
#   CS\t0\t10:49:04.906\tMitemshubAI_v28 (Volatility 75 Index,M30)\t2026.03.17 15:30:00   [v28.00] OPEN BUY volume=0.2470 entry=... SL=... TP=... risk=$100.00 risk_src=ENTRY expiry=... trigger=M30_REVERSED_EXTREME
#   ...\t2026.03.17 18:30:02   [v28.00] CLOSE TIMEOUT ticket=2 pnl=+103.22 R=+1.032 risk=100.00 risk_src=ENTRY peak_r=2.373 cum_pnl=... cum_R=... exit=... hold=10812 sec
# The CLOSE line carries the exit REASON, not a side — the pair's side comes
# from the OPEN (single-position sequential book).
RE_INIT = re.compile(r"MACRO started.*?experiment=(\S+)")
RE_SIMTS = re.compile(r"(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+\[v")
RE_OPEN = re.compile(
    r"\] OPEN (BUY|SELL) volume=(\S+) entry=(\S+) SL=(\S+) TP=(\S+) "
    r"risk=\$?([0-9.]+) risk_src=(\S+) expiry=(\S+ \S+) trigger=(\S+)")
RE_CLOSE = re.compile(
    r"\] CLOSE (\S+) ticket=(\S+) pnl=([+-][\d.]+) R=([+-][\d.]+) "
    r"risk=([0-9.]+) risk_src=(\S+) peak_r=([+-]?[\d.]+) cum_pnl=\S+ "
    r"cum_R=\S+ exit=\S+ hold=(\d+) sec")


def journal_day_files() -> list[Path]:
    """Every agent journal day that still exists (3 at pre-registration time)."""
    files: list[Path] = []
    for root in _tester_roots():
        files += sorted(root.glob("Agent-*/logs/*.log"))
    return files


def read_log(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-16-le", "ignore")
    except OSError:
        return ""


def parse_journal_segments(lines: list[str]) -> dict[str, list[dict]]:
    """Split a day's lines into per-pass segments keyed by experiment tag,
    extracting OPEN and CLOSE events in order (single-position book)."""
    segments: dict[str, list[dict]] = defaultdict(list)
    current: str | None = None
    for line in lines:
        m = RE_INIT.search(line)
        if m:
            current = m.group(1)
            continue
        if current is None:
            continue
        om = RE_OPEN.search(line)
        if om:
            side, _vol, entry, sl, tp, _risk, _rsrc, _expiry, trigger = om.groups()
            ts_m = RE_SIMTS.search(line)
            if ts_m is None:
                continue
            segments[current].append({
                "kind": "OPEN", "ts": ts_m.group(1), "side": side,
                "entry": float(entry), "sl": float(sl), "tp": float(tp),
                "trigger": trigger})
            continue
        cm = RE_CLOSE.search(line)
        if cm:
            reason, _ticket, _pnl, r, _risk, _rsrc, peak_r, hold = cm.groups()
            segments[current].append({
                "kind": "CLOSE", "reason": reason, "r": float(r),
                "peak_r": float(peak_r), "hold": int(hold)})
    return segments


def pair_segment(events: list[dict]) -> tuple[list[dict], int]:
    """Pair the i-th OPEN with the i-th CLOSE (sequential single-position).
    The CLOSE line carries a reason, not a side, so the pair's side is the
    OPEN's. Dangling unpaired events are counted, never silently used."""
    trades: list[dict] = []
    opens = [e for e in events if e["kind"] == "OPEN"]
    closes = [e for e in events if e["kind"] == "CLOSE"]
    for o, c in zip(opens, closes):
        trades.append({
            "ts": o["ts"], "side": o["side"], "trigger": o["trigger"],
            "entry": o["entry"], "sl": o["sl"], "tp": o["tp"],
            "r": c["r"], "peak_r": c["peak_r"], "hold": c["hold"],
            "exit_reason": c["reason"]})
    dropped = abs(len(opens) - len(closes))
    return trades, dropped


# ---- registry join --------------------------------------------------------------
def load_registry() -> list[dict]:
    return [json.loads(l) for l in REGISTRY.read_text().splitlines() if l.strip()]


def join_registry(segments: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    """Join journal trades to registry rows by run_tag. Coverage accounting:
    journal trades in segments that match no registry row are counted, not
    used. OOS-role rows are excluded from the feature set (counted)."""
    rows = load_registry()
    by_tag = {}
    for r in rows:
        by_tag.setdefault(r.get("run_tag", ""), r)
    trades: list[dict] = []
    cov = Counter()
    for tag, events in segments.items():
        t, dropped = pair_segment(events)
        cov["journal_trades_paired"] += len(t)
        cov["journal_dropped"] += dropped
        row = by_tag.get(tag)
        if row is None:
            cov["journal_trades_no_registry_row"] += len(t)
            continue
        if row.get("mode") != CANDIDATE_MODE:
            cov["journal_trades_other_mode"] += len(t)
            continue
        if row.get("window") == "oos":
            cov["journal_trades_oos_excluded"] += len(t)
            continue
        g = row.get("geometry", {})
        for x in t:
            x.update({
                "run_tag": tag, "experiment_id": row.get("experiment_id"),
                "mode": row.get("mode"), "window": row.get("window"),
                "sl_atr": g.get("sl_atr"), "tp_atr": g.get("tp_atr"),
                "hold_min": g.get("hold_min")})
        trades += t
    cov["candidate_trades_from_journal"] = len(trades)
    return trades, cov


# ---- bars + features --------------------------------------------------------------
def load_bars(path: Path = BARS_CSV) -> dict:
    """M15 bars as arrays with an open-ts index. ts must sit on a 900 s
    boundary (V75 trades 24/7, no session gaps)."""
    ts, o, h, l, c, spread = [], [], [], [], [], []
    with open(path) as f:
        header = f.readline()
        if not header.startswith("ts,"):
            raise ValueError(f"{path}: unexpected bars header {header!r}")
        for line in f:
            p = line.rstrip("\n").split(",")
            if len(p) < 8:
                continue
            ts.append(int(p[0])); o.append(float(p[1])); h.append(float(p[2]))
            l.append(float(p[3])); c.append(float(p[4])); spread.append(float(p[6]))
    t = np.asarray(ts, dtype=np.int64)
    if np.any(t % 900 != 0):
        raise ValueError("bars are not aligned to 900 s M15 opens")
    return {"ts": t, "open": np.asarray(o), "high": np.asarray(h),
            "low": np.asarray(l), "close": np.asarray(c),
            "spread": np.asarray(spread),
            "index": {int(x): i for i, x in enumerate(t)}}


def _rolling_mean(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    if len(a) >= w:
        cs = np.cumsum(np.insert(a, 0, 0.0))
        out[w - 1:] = (cs[w:] - cs[:-w]) / w
    return out


def _rsi(close: np.ndarray, w: int = 14) -> np.ndarray:
    out = np.full(len(close), np.nan)
    if len(close) <= w:
        return out
    d = np.diff(close)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = up[:w].mean()
    ad = dn[:w].mean()
    out[w] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / ad)
    for i in range(w + 1, len(close)):
        au = (au * (w - 1) + up[i - 1]) / w
        ad = (ad * (w - 1) + dn[i - 1]) / w
        out[i] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / ad)
    return out


def bar_feature_pack(bars: dict) -> dict:
    """Precompute the decision-time feature arrays once for all trades."""
    c, h, l = bars["close"], bars["high"], bars["low"]
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)),
                                      np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    ret = np.full(len(c), np.nan)
    ret[1:] = c[1:] / c[:-1] - 1.0
    atr14 = _rolling_mean(tr, 14)
    atr50 = _rolling_mean(tr, 50)
    rsi = _rsi(c, 14)
    lo96 = _rolling_min(l, 96)
    hi96 = _rolling_max(h, 96)
    vol = _rolling_std(ret, 32) / np.maximum(_rolling_std(ret, 96), 1e-12)
    return {"ret1": ret, "ret4": _shifted_sum(ret, 4),
            "ret12": _shifted_sum(ret, 12), "ret48": _shifted_sum(ret, 48),
            "atr_ratio": atr14 / np.maximum(atr50, 1e-12), "rsi": rsi,
            "range_pos": (c - lo96) / np.maximum(hi96 - lo96, 1e-12),
            "vol_regime": vol, "spread": bars["spread"]}


def _rolling_min(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    for i in range(w - 1, len(a)):
        out[i] = a[i - w + 1:i + 1].min()
    return out


def _rolling_max(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    for i in range(w - 1, len(a)):
        out[i] = a[i - w + 1:i + 1].max()
    return out


def _rolling_std(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    for i in range(w, len(a)):
        out[i] = a[i - w + 1:i + 1].std()
    return out


def _shifted_sum(ret: np.ndarray, k: int) -> np.ndarray:
    """Cumulative return over the k bars ENDING at the last closed bar:
    sum of ret[i-k+1 .. i] where ret[i] is bar i's own return."""
    out = np.full(len(ret), np.nan)
    cs = np.cumsum(np.nan_to_num(ret, nan=0.0))
    for i in range(k, len(ret)):
        out[i] = cs[i] - cs[i - k]
    return out


def feature_row(bars: dict, pack: dict, entry_ts: str) -> tuple[list[float] | None, str]:
    """Features from the last CLOSED M15 bar before the entry bar-open.
    Returns (row, "") or (None, reason). Leakage: nothing post-entry."""
    dt = datetime.strptime(entry_ts, "%Y.%m.%d %H:%M:%S").replace(
        tzinfo=timezone.utc)
    epoch = int(dt.timestamp())
    bar_open = epoch - (epoch % 900)
    idx = bars["index"].get(bar_open)
    if idx is None:
        return None, "entry bar outside bar coverage"
    if idx == 0:
        return None, "no closed bar before entry"
    j = idx - 1  # last closed bar
    hour = dt.hour + dt.minute / 60.0
    row = [
        pack["ret1"][j], pack["ret4"][j], pack["ret12"][j], pack["ret48"][j],
        pack["atr_ratio"][j], pack["rsi"][j], pack["range_pos"][j],
        pack["vol_regime"][j], pack["spread"][j],
        math.sin(2 * math.pi * hour / 24.0), math.cos(2 * math.pi * hour / 24.0),
        float(dt.weekday()),
    ]
    if any(isinstance(v, float) and math.isnan(v) for v in row):
        return None, "feature warm-up window incomplete"
    return row, ""


FEATURE_NAMES = [
    "ret1", "ret4", "ret12", "ret48", "atr_ratio", "rsi", "range_pos",
    "vol_regime", "spread", "hour_sin", "hour_cos", "dow",
]


def featurize(trades: list[dict], bars: dict) -> tuple[list[dict], dict]:
    pack = bar_feature_pack(bars)
    out: list[dict] = []
    cov = Counter()
    for t in trades:
        row, why = feature_row(bars, pack, t["ts"])
        if row is None:
            cov[f"excluded: {why}"] += 1
            continue
        t = dict(t)
        t["features"] = [round(float(v), 8) for v in row]
        t["label_win"] = bool(t["r"] > 0.0)
        cov["featurized"] += 1
        out.append(t)
    return out, cov


# ---- folds, cap, model, gate -------------------------------------------------------
def month_key(ts: str) -> str:
    return ts[:7]  # "YYYY.MM"


def build_folds(trades: list[dict]) -> list[dict]:
    """Expanding walk-forward on calendar months with a one-month embargo.
    The last 6 eligible months are validation folds; training never sees the
    embargo month or anything at/after the validation month."""
    months = sorted({month_key(t["ts"]) for t in trades})
    folds = []
    val_months = [m for m in months[-N_FOLDS:]
                  if sum(1 for t in trades if month_key(t["ts"]) == m) >= MIN_VAL_TRADES]
    for vm in val_months:
        vi = months.index(vm)
        train_months = months[:max(0, vi - EMBARGO_MONTHS)]
        tr = [t for t in trades if month_key(t["ts"]) in set(train_months)]
        va = [t for t in trades if month_key(t["ts"]) == vm]
        folds.append({"val_month": vm, "train": tr, "val": va})
    return folds


def apply_group_cap(train: list[dict], seed: int = SEED, cap: int = GROUP_CAP) -> list[dict]:
    """At most `cap` trades per (month x geometry cell) in training — the
    sweep re-ran the same months across many cells; without the cap those
    months dominate. Seeded so every run selects identically."""
    rng = np.random.default_rng(seed)
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, t in enumerate(train):
        cell = (t.get("sl_atr"), t.get("tp_atr"), t.get("hold_min"))
        groups[(month_key(t["ts"]), cell)].append(i)
    keep: list[int] = []
    for key, idxs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        idxs = list(idxs)
        rng.shuffle(idxs)
        keep += idxs[:cap]
    return [train[i] for i in sorted(keep)]


def trigger_vocab(trades: list[dict]) -> list[str]:
    return sorted({t["trigger"] for t in trades})


def design(trades: list[dict], vocab: list[str]) -> np.ndarray:
    X = np.asarray([t["features"] for t in trades], dtype=float)
    onehot = np.zeros((len(trades), len(vocab)))
    for i, t in enumerate(trades):
        if t["trigger"] in vocab:
            onehot[i, vocab.index(t["trigger"])] = 1.0
    geo = np.asarray([[t.get("sl_atr") or 0.0, t.get("tp_atr") or 0.0,
                       t.get("hold_min") or 0.0] for t in trades], dtype=float)
    return np.hstack([X, onehot, geo])


def balanced_sample_weight(y: np.ndarray) -> np.ndarray:
    """class_weight='balanced', applied as sample weights (GBC has no
    class_weight parameter)."""
    n = len(y)
    w = np.ones(n)
    for cls in (0, 1):
        m = int((y == cls).sum())
        if m:
            w[y == cls] = n / (2.0 * m)
    return w


def train_fold(train: list[dict], val: list[dict], vocab: list[str]) -> dict:
    from sklearn.ensemble import GradientBoostingClassifier
    clf = GradientBoostingClassifier(
        n_estimators=200, learning_rate=0.05, max_depth=3,
        min_samples_leaf=20, random_state=SEED)
    Xtr, ytr = design(train, vocab), np.asarray([t["label_win"] for t in train], int)
    clf.fit(Xtr, ytr, sample_weight=balanced_sample_weight(ytr))
    p = clf.predict_proba(design(val, vocab))[:, 1]
    keep = [t for t, pi in zip(val, p) if pi >= P_THRESHOLD]
    base_r = float(np.mean([t["r"] for t in val])) if val else 0.0
    filt_r = float(np.mean([t["r"] for t in keep])) if keep else 0.0
    wins = [t["r"] > 0 for t in keep]
    return {
        "val_month": None, "n_val": len(val), "n_keep": len(keep),
        "keep_rate": round(len(keep) / len(val), 4) if val else 0.0,
        "baseline_expr": round(base_r, 4),
        "filtered_expr": round(filt_r, 4),
        "uplift": round(filt_r - base_r, 4),
        "kept_win_rate": round(float(np.mean(wins)), 4) if wins else None,
        "calibration_deciles": calibration(val, p),
    }


def calibration(val: list[dict], p: np.ndarray) -> list[dict]:
    """Observed win rate by predicted-P decile — honest calibration read."""
    order = np.argsort(p)
    out = []
    n = len(val)
    for d in range(10):
        lo, hi = int(d * n / 10), int((d + 1) * n / 10)
        if hi > lo:
            sel = order[lo:hi]
            out.append({
                "p_mean": round(float(np.mean(p[sel])), 4),
                "obs_win_rate": round(float(np.mean([val[i]["r"] > 0 for i in sel])), 4),
                "n": int(hi - lo)})
    return out


def evaluate_gate(fold_rows: list[dict]) -> dict:
    """The frozen §10.4 gate, mechanically. Every leg is reported; a miss on
    any leg fails the gate."""
    improved = sum(1 for f in fold_rows if f["uplift"] > 0)
    tot_n = sum(f["n_val"] for f in fold_rows) or 1
    agg_uplift = sum(f["uplift"] * f["n_val"] for f in fold_rows) / tot_n
    agg_keep = sum(f["keep_rate"] * f["n_val"] for f in fold_rows) / tot_n
    legs = {
        "folds_improved": {"value": improved, "pass": improved >= GATE_MIN_FOLDS_IMPROVED},
        "aggregate_uplift_r": {"value": round(agg_uplift, 4),
                               "pass": agg_uplift >= GATE_MIN_UPLIFT_R},
        "keep_rate": {"value": round(agg_keep, 4),
                      "pass": agg_keep >= GATE_MIN_KEEP_RATE},
    }
    return {"legs": legs, "verdict": "PASS" if all(l["pass"] for l in legs.values())
            else "FAIL", "n_folds": len(fold_rows)}


# ---- pipeline ------------------------------------------------------------------------
def agent_journal_segments() -> dict[str, list[dict]]:
    segs: dict[str, list[dict]] = {}
    for f in journal_day_files():
        for tag, events in parse_journal_segments(read_log(f).splitlines()).items():
            segs.setdefault(tag, []).extend(events)
    return segs


def run_pipeline(dataset_out: Path | None = None, bars_path: Path = BARS_CSV) -> dict:
    t0 = time.time()
    segs = agent_journal_segments()
    trades, cov = join_registry(segs)
    cov["registry_denominator"] = REGISTRY_DENOMINATOR
    cov["coverage_ratio"] = round(cov["candidate_trades_from_journal"]
                                   / REGISTRY_DENOMINATOR, 4)

    report: dict = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "protocol": "V28_RESEARCH_PROTOCOL.md §10 (pre-registered 2026-09-16)",
        "feature_version": FEATURE_VERSION, "model_version": MODEL_VERSION,
        "candidate": CANDIDATE_MODE, "coverage": cov, "dataset_n": len(trades),
    }
    if len(trades) < MIN_VAL_TRADES * 2:
        report["verdict"] = "INSUFFICIENT_DATA"
        report["note"] = ("fewer featurized trades than one validation month "
                          "requires; coverage grows only by deterministic re-runs")
        _write_report(report)
        return report

    bars = load_bars(bars_path)
    trades, fcov = featurize(trades, bars)
    cov.update(fcov)
    cov["coverage_ratio"] = round(cov["featurized"] / REGISTRY_DENOMINATOR, 4)

    vocab = trigger_vocab(trades)
    folds = build_folds(trades)
    fold_rows = []
    for f in folds:
        tr = apply_group_cap(f["train"])
        if len(tr) < 20 or not any(t["label_win"] for t in tr):
            fold_rows.append({"val_month": f["val_month"], "skipped":
                              f"train n={len(tr)} or no positive class after cap"})
            continue
        row = train_fold(tr, f["val"], vocab)
        row["val_month"] = f["val_month"]
        row["n_train_raw"] = len(f["train"])
        row["n_train_capped"] = len(tr)
        fold_rows.append(row)

    evals = [r for r in fold_rows if "skipped" not in r]
    gate = evaluate_gate(evals) if evals else {
        "verdict": "FAIL", "legs": {}, "n_folds": 0}
    report.update({
        "trigger_vocab": vocab, "folds": fold_rows, "gate": gate,
        "ship_verdict": gate["verdict"],
        "honesty": [
            f"coverage {cov['featurized']}/{REGISTRY_DENOMINATOR} "
            f"({cov['coverage_ratio']:.1%}) — grows only by §2 re-runs",
            "training data is REVERSE_ONLY-sweep-shaped; the filter is "
            "candidate-specific until its own evidence says otherwise",
            "the filter only removes trades; it inherits §9's evidence status",
        ],
        "runtime_s": round(time.time() - t0, 1),
    })
    if dataset_out is not None and trades:
        with open(dataset_out, "w") as fh:
            for t in trades:
                fh.write(json.dumps(t) + "\n")
        report["dataset_snapshot"] = str(dataset_out)
    _write_report(report)
    return report


def _write_report(report: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    path = ART / f"signal_filter_report_{ts}.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"report: {path}")
    print(f"coverage: {report['coverage'].get('featurized', 0)}/"
          f"{report['coverage'].get('registry_denominator', REGISTRY_DENOMINATOR)}")
    if "gate" in report:
        print(f"gate: {report['gate']['verdict']} legs="
              f"{ {k: v['value'] for k, v in report['gate']['legs'].items()} }")
    else:
        print(f"verdict: {report.get('verdict')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-out", type=Path, default=None,
                    help="write the featurized trade snapshot here")
    ap.add_argument("--bars", type=Path, default=BARS_CSV)
    args = ap.parse_args()
    report = run_pipeline(dataset_out=args.dataset_out, bars_path=args.bars)
    return 0 if report.get("ship_verdict") in (None, "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
