"""Offline tests for the §10 ML signal-filter pipeline.

Synthetic journals, synthetic bars, no terminal, no registry writes. The
pins that matter: journal parsing against the REAL agent-log line shapes
(reason-word CLOSE, mid-line sim timestamps), leakage-safe features (last
CLOSED bar only), the embargo + group-cap fold discipline, the frozen gate
constants, and end-to-end coverage accounting that can never overcount.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import v28_signal_filter as sf  # noqa: E402


# --- journal parsing (real line shapes) -----------------------------------------

def _open_line(ts: str, side: str, trigger: str = "M30_REVERSED_EXTREME",
               tag: str = "v28.00") -> str:
    return (f"CS\t0\t10:49:04.906\tMitemshubAI_v28 (Volatility 75 Index,M30)\t"
            f"{ts}   [{tag}] OPEN {side} volume=0.2470 entry=36940.02000 "
            f"SL=36536.56000 TP=38553.87000 risk=$100.00 risk_src=ENTRY "
            f"expiry=2026.03.17 18:30:00 trigger={trigger}")


def _close_line(ts: str, reason: str = "TIMEOUT", r: str = "+1.032",
                peak: str = "2.373", hold: int = 10812,
                tag: str = "v28.00") -> str:
    return (f"CS\t0\t10:49:04.910\tMitemshubAI_v28 (Volatility 75 Index,M30)\t"
            f"{ts}   [{tag}] CLOSE {reason} ticket=2 pnl=+103.22 R={r} "
            f"risk=100.00 risk_src=ENTRY peak_r={peak} cum_pnl=+103.22 "
            f"cum_R=+1.032 exit=38553.87000 hold={hold} sec")


def test_parse_extracts_opens_and_closes_from_real_shapes() -> None:
    lines = [
        "CS\t0\t10:49:04.900\tMitemshubAI_v28 (Volatility 75 Index,M30)\t"
        "2026.03.17 15:30:00   [v28.00] MITEMSHUB V75 MACRO started | mode=3 | "
        "experiment=run_a | gate=M30 | r=1.0%",
        _open_line("2026.03.17 15:30:00", "BUY"),
        _close_line("2026.03.17 18:30:02", "TIMEOUT", "+1.032", "2.373", 10812),
        _open_line("2026.03.18 09:30:00", "SELL", "M30_REVERSED_EXTREME"),
        _close_line("2026.03.18 10:53:52", "SL", "-1.004", "0.373", 5032),
    ]
    segs = sf.parse_journal_segments(lines)
    assert list(segs) == ["run_a"]
    t, dropped = sf.pair_segment(segs["run_a"])
    assert dropped == 0 and len(t) == 2
    assert t[0]["side"] == "BUY" and t[0]["r"] == 1.032
    assert t[0]["trigger"] == "M30_REVERSED_EXTREME"
    assert t[1]["side"] == "SELL" and t[1]["exit_reason"] == "SL"
    assert t[1]["peak_r"] == 0.373 and t[1]["hold"] == 5032


def test_parse_splits_segments_by_experiment_tag() -> None:
    lines = [
        "x\t2026.03.17 15:30:00   [v28.00] MACRO started | experiment=run_a",
        _open_line("2026.03.17 15:30:00", "BUY"),
        "x\t2026.03.20 15:30:00   [v28.10] MACRO started | experiment=run_b",
        _open_line("2026.03.20 15:30:00", "SELL", tag="v28.10"),
    ]
    segs = sf.parse_journal_segments(lines)
    assert sorted(segs) == ["run_a", "run_b"]
    assert segs["run_a"][0]["side"] == "BUY"
    assert segs["run_b"][0]["side"] == "SELL"


def test_pair_counts_dangling_events_never_uses_them() -> None:
    events = [
        {"kind": "OPEN", "ts": "2026.03.17 15:30:00", "side": "BUY",
         "entry": 1.0, "sl": 0.9, "tp": 1.2, "trigger": "T"},
        {"kind": "OPEN", "ts": "2026.03.17 16:30:00", "side": "SELL",
         "entry": 1.0, "sl": 1.1, "tp": 0.8, "trigger": "T"},
        {"kind": "CLOSE", "reason": "TP", "r": 2.0, "peak_r": 2.1, "hold": 60},
    ]
    t, dropped = sf.pair_segment(events)
    assert len(t) == 1 and dropped == 1
    assert t[0]["side"] == "BUY"          # side comes from the OPEN


def test_lines_without_sim_timestamp_are_skipped() -> None:
    lines = ["agent noise without timestamps"] * 3
    assert sf.parse_journal_segments(lines) == {}


# --- registry join + coverage ------------------------------------------------------

def test_join_registry_counts_every_class(monkeypatch) -> None:
    rows = [
        {"run_tag": "run_rb", "mode": "V28_REVERSE_BOTH", "window": "is180",
         "experiment_id": "V28-0030", "geometry": {"sl_atr": 2.0,
         "tp_atr": 2.0, "hold_min": 180}},
        {"run_tag": "run_orig", "mode": "V28_ORIGINAL", "window": "is90",
         "geometry": {"sl_atr": 2.0, "tp_atr": 4.0, "hold_min": 180}},
        {"run_tag": "run_oos", "mode": "V28_REVERSE_BOTH", "window": "oos",
         "geometry": {"sl_atr": 2.0, "tp_atr": 2.0, "hold_min": 180}},
    ]
    monkeypatch.setattr(sf, "load_registry", lambda: rows)
    segs = {
        "run_rb": [{"kind": "OPEN", "ts": "2026.03.17 15:30:00", "side": "BUY",
                    "entry": 1, "sl": 0.9, "tp": 1.2, "trigger": "T"}] * 3
                  + [{"kind": "CLOSE", "reason": "TP", "r": 1.0,
                      "peak_r": 1.5, "hold": 60}] * 3,
        "run_orig": [{"kind": "OPEN", "ts": "2026.03.17 15:30:00",
                      "side": "BUY", "entry": 1, "sl": 0.9, "tp": 1.2,
                      "trigger": "T"},
                     {"kind": "CLOSE", "reason": "TP", "r": 1.0,
                      "peak_r": 1.5, "hold": 60}],
        "run_oos": [{"kind": "OPEN", "ts": "2026.03.17 15:30:00",
                     "side": "BUY", "entry": 1, "sl": 0.9, "tp": 1.2,
                     "trigger": "T"},
                    {"kind": "CLOSE", "reason": "TP", "r": 1.0,
                     "peak_r": 1.5, "hold": 60}],
        "run_ghost": [{"kind": "OPEN", "ts": "2026.03.17 15:30:00",
                       "side": "BUY", "entry": 1, "sl": 0.9, "tp": 1.2,
                       "trigger": "T"},
                      {"kind": "CLOSE", "reason": "TP", "r": 1.0,
                       "peak_r": 1.5, "hold": 60}],
    }
    trades, cov = sf.join_registry(segs)
    assert len(trades) == 3
    assert cov["journal_trades_paired"] == 6
    assert cov["journal_trades_other_mode"] == 1
    assert cov["journal_trades_oos_excluded"] == 1
    assert cov["journal_trades_no_registry_row"] == 1
    assert trades[0]["sl_atr"] == 2.0 and trades[0]["tp_atr"] == 2.0
    assert trades[0]["experiment_id"] == "V28-0030"


# --- bars + features -----------------------------------------------------------------

def _synth_bars(n: int, start_ts: int = 1_750_000_000 - (1_750_000_000 % 900)) -> dict:
    rng = np.random.default_rng(7)
    ts = start_ts + 900 * np.arange(n)
    close = 100.0 + np.cumsum(rng.normal(0, 0.2, n))
    high = close + np.abs(rng.normal(0, 0.1, n))
    low = close - np.abs(rng.normal(0, 0.1, n))
    return {"ts": ts, "open": close.copy(), "high": high, "low": low,
            "close": close, "spread": np.full(n, 30.0),
            "index": {int(t): i for i, t in enumerate(ts)}}


def test_load_bars_rejects_unaligned_timestamps(tmp_path) -> None:
    p = tmp_path / "bars.csv"
    p.write_text("ts,open,high,low,close,tick_volume,spread,real_volume\n"
                 "1750000001,1,1,1,1,1,30,0\n")
    with pytest.raises(ValueError, match="900 s"):
        sf.load_bars(p)


def test_feature_row_joins_last_closed_bar_no_leakage() -> None:
    bars = _synth_bars(400)
    pack = sf.bar_feature_pack(bars)
    ts0 = int(bars["ts"][100])
    from datetime import datetime, timezone
    entry_ts = datetime.fromtimestamp(ts0, tz=timezone.utc).strftime(
        "%Y.%m.%d %H:%M:%S")
    row, why = sf.feature_row(bars, pack, entry_ts)
    assert why == ""
    j = 99  # last CLOSED bar before the entry bar-open
    assert row[0] == pytest.approx(float(pack["ret1"][j]), abs=5e-9)
    assert row[4] == pytest.approx(float(pack["atr_ratio"][j]), abs=5e-9)
    # the entry bar itself must not influence anything: perturb it and the
    # row must not change
    bars2 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in bars.items()}
    bars2["close"][100] *= 3.0
    bars2["high"][100] *= 3.0
    pack2 = sf.bar_feature_pack(bars2)
    row2, _ = sf.feature_row(bars2, pack2, entry_ts)
    assert row == row2


def test_feature_row_excludes_out_of_coverage_and_warmup() -> None:
    bars = _synth_bars(400)
    pack = sf.bar_feature_pack(bars)
    row, why = sf.feature_row(bars, pack, "2019.01.01 00:00:00")
    assert row is None and "coverage" in why
    from datetime import datetime, timezone
    # entry at the FIRST bar: its bar-open has no closed predecessor at all
    first = datetime.fromtimestamp(int(bars["ts"][0]), tz=timezone.utc).strftime(
        "%Y.%m.%d %H:%M:%S")
    row, why = sf.feature_row(bars, pack, first)
    assert row is None and "no closed bar" in why
    # entry a few bars in: the ret48/ATR50 warm-up window is still incomplete
    early = datetime.fromtimestamp(int(bars["ts"][30]), tz=timezone.utc).strftime(
        "%Y.%m.%d %H:%M:%S")
    row, why = sf.feature_row(bars, pack, early)
    assert row is None and "warm-up" in why


# --- folds + cap -----------------------------------------------------------------------

def _mk_trades(months: list[str], per: int, cell=(2.0, 2.0, 180)) -> list[dict]:
    out = []
    for m in months:
        for d in range(per):
            out.append({"ts": f"{m}.{(d % 27) + 1:02d} 12:30:00",
                        "side": "BUY", "trigger": "T",
                        "r": 1.0 if d % 3 else -1.0,
                        "peak_r": 1.0, "hold": 60, "label_win": d % 3 != 0,
                        "sl_atr": cell[0], "tp_atr": cell[1],
                        "hold_min": cell[2], "features": [0.0] * 12})
    return out


def test_folds_expanding_with_one_month_embargo() -> None:
    months = [f"2026.{m:02d}" for m in range(1, 10)]
    trades = _mk_trades(months, 12)
    folds = sf.build_folds(trades)
    assert [f["val_month"] for f in folds] == months[-sf.N_FOLDS:]
    for f in folds:
        vm = f["val_month"]
        train_months = {sf.month_key(t["ts"]) for t in f["train"]}
        assert vm not in train_months
        # embargo: the month immediately before the val month is excluded
        prev = months[months.index(vm) - 1]
        assert prev not in train_months
        # expanding: everything strictly before the embargo month is in
        expected = {m for m in months if m < prev}
        assert train_months == expected
        assert {sf.month_key(t["ts"]) for t in f["val"]} == {vm}


def test_folds_skip_thin_validation_months() -> None:
    # 2026.08 has only 3 trades (below MIN_VAL_TRADES) and must be skipped
    # even though it is among the last six months — so only 5 folds form.
    trades = _mk_trades([f"2026.{m:02d}" for m in range(1, 8)], 12)
    trades += _mk_trades(["2026.08"], 3)
    folds = sf.build_folds(trades)
    assert "2026.08" not in [f["val_month"] for f in folds]
    assert len(folds) == sf.N_FOLDS - 1


def test_group_cap_is_seeded_and_respected() -> None:
    months = [f"2026.{m:02d}" for m in range(1, 6)]
    trades = _mk_trades(months, 50, cell=(2.0, 2.0, 180))
    trades += _mk_trades(months, 50, cell=(2.0, 4.0, 180))
    a = sf.apply_group_cap(trades)
    b = sf.apply_group_cap(trades)
    assert a == b                                   # deterministic
    groups = {}
    for t in a:
        k = (sf.month_key(t["ts"]), (t["sl_atr"], t["tp_atr"], t["hold_min"]))
        groups[k] = groups.get(k, 0) + 1
    assert max(groups.values()) <= sf.GROUP_CAP     # the cap binds here
    assert sum(groups.values()) == len(a)


# --- model + gate -----------------------------------------------------------------------

def test_balanced_sample_weight_matches_sklearn_semantics() -> None:
    y = np.asarray([0] * 75 + [1] * 25)
    w = sf.balanced_sample_weight(y)
    assert w[y == 0].mean() == pytest.approx(100 / (2 * 75))
    assert w[y == 1].mean() == pytest.approx(100 / (2 * 25))


def _fold_row(uplift: float, n: int = 100, keep: float = 0.5) -> dict:
    return {"val_month": "x", "n_val": n, "keep_rate": keep,
            "baseline_expr": 0.1, "filtered_expr": 0.1 + uplift,
            "uplift": uplift}


def test_gate_constants_are_frozen() -> None:
    assert sf.SEED == 20260916
    assert sf.REGISTRY_DENOMINATOR == 8426
    assert sf.N_FOLDS == 6 and sf.EMBARGO_MONTHS == 1
    assert sf.GATE_MIN_FOLDS_IMPROVED == 5
    assert sf.GATE_MIN_UPLIFT_R == 0.10
    assert sf.GATE_MIN_KEEP_RATE == 0.35


def test_gate_passes_only_on_all_legs() -> None:
    good = [_fold_row(0.15) for _ in range(6)]
    g = sf.evaluate_gate(good)
    assert g["verdict"] == "PASS"
    # 5/6 folds improved, uplift ok, but keep-rate too low -> FAIL
    mixed = [_fold_row(0.15, keep=0.20) for _ in range(5)] + [_fold_row(0.15)]
    g = sf.evaluate_gate(mixed)
    assert g["verdict"] == "FAIL" and not g["legs"]["keep_rate"]["pass"]
    # only 2 folds improve -> FAIL (the recorded first-run result class)
    weak = [_fold_row(0.5), _fold_row(0.2)] + [_fold_row(-0.1) for _ in range(4)]
    g = sf.evaluate_gate(weak)
    assert g["verdict"] == "FAIL" and g["legs"]["folds_improved"]["value"] == 2


def test_gate_aggregates_are_trade_weighted() -> None:
    rows = [_fold_row(0.5, n=200, keep=0.5), _fold_row(-0.1, n=50, keep=0.5)]
    g = sf.evaluate_gate(rows)
    assert g["legs"]["aggregate_uplift_r"]["value"] == pytest.approx(
        (0.5 * 200 + (-0.1) * 50) / 250, abs=1e-6)


# --- end-to-end on synthetic data ---------------------------------------------------------

def test_run_pipeline_end_to_end_synthetic(tmp_path, monkeypatch) -> None:
    """Synthetic 12-month journal + bars: the pipeline must produce a full
    report with correct coverage accounting, folds, and a gate verdict —
    and write the dataset snapshot."""
    # synthetic bars: all of 2026 at M15 (aligned to 900 s)
    from datetime import datetime, timezone
    t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    n = 96 * 365  # Jan 1 .. Dec 31 inclusive
    ts = t0 + 900 * np.arange(n)
    rng = np.random.default_rng(11)
    close = 100.0 + np.cumsum(rng.normal(0, 0.2, n))
    high = close + np.abs(rng.normal(0, 0.1, n))
    low = close - np.abs(rng.normal(0, 0.1, n))
    hdr = "ts,open,high,low,close,tick_volume,spread,real_volume\n"
    lines = [hdr]
    for i in range(n):
        lines.append(f"{ts[i]},{close[i]},{high[i]},{low[i]},{close[i]},1,30,0\n")
    bars_path = tmp_path / "bars.csv"
    bars_path.write_text("".join(lines))

    # synthetic journal: 13 trades/month (>= MIN_VAL_TRADES) across a full
    # year of bars — the model itself is not under test here, the wiring is
    from datetime import datetime, timezone
    jl = []
    trades_n = 0
    for m in range(1, 13):
        for d in range(2, 28, 2):
            dt = datetime(2026, m, d, 12, 30, 0, tzinfo=timezone.utc)
            ts = dt.strftime("%Y.%m.%d %H:%M:%S")
            r = "+1.0" if (m + d) % 3 else "-1.0"
            jl.append("CS\t0\t10:49:04.900\tMitemshubAI_v28 (V,M30)\t"
                      f"{ts}   [v28.00] MITEMSHUB V75 MACRO started | mode=3 | "
                      f"experiment=run_{m:02d} | gate=M30")
            jl.append(_open_line(ts, "BUY"))
            jl.append(_close_line(ts.replace("12:30:00", "15:30:00"),
                                  "TP" if r.startswith("+") else "SL", r,
                                  "1.5", 10800))
            trades_n += 1
    log = tmp_path / "20260101.log"
    log.write_text("\n".join(jl), encoding="utf-16-le")
    monkeypatch.setattr(sf, "journal_day_files", lambda: [log])

    reg_rows = [{"run_tag": f"run_{m:02d}", "mode": "V28_REVERSE_BOTH",
                 "window": "is180", "experiment_id": f"V28-{m:04d}",
                 "geometry": {"sl_atr": 2.0, "tp_atr": 2.0, "hold_min": 180}}
                for m in range(1, 13)]
    monkeypatch.setattr(sf, "load_registry", lambda: reg_rows)

    snap = tmp_path / "ds.jsonl"
    rep = sf.run_pipeline(dataset_out=snap, bars_path=bars_path)
    assert rep["coverage"]["journal_trades_paired"] == trades_n
    assert rep["coverage"]["featurized"] == trades_n
    assert rep["coverage"]["coverage_ratio"] == round(trades_n / 8426, 4)
    assert len(rep["folds"]) == sf.N_FOLDS
    assert all("skipped" not in f for f in rep["folds"])
    assert rep["gate"]["verdict"] in ("PASS", "FAIL")
    assert snap.exists() and sum(1 for _ in open(snap)) == trades_n
    # every fold's val month is a real calendar month string
    for f in rep["folds"]:
        assert f["val_month"].startswith("2026.")


def test_run_pipeline_insufficient_data_fails_closed(tmp_path, monkeypatch) -> None:
    log = tmp_path / "20260101.log"
    log.write_text("nothing", encoding="utf-16-le")
    monkeypatch.setattr(sf, "journal_day_files", lambda: [log])
    monkeypatch.setattr(sf, "load_registry", lambda: [])
    rep = sf.run_pipeline(bars_path=tmp_path / "none.csv")
    assert rep["verdict"] == "INSUFFICIENT_DATA"
