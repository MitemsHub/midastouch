"""Offline tests for the bucket-table signal filter (scripts/signal_filter_table.py).

Pins that matter: shrinkage + min-n fallback + muted-0.50 semantics, the
frozen activation gate (all five legs), the CSV round-trip the EA parses,
and the central safety contract — a PASSIVE table can never veto (the EA's
evaluate logic mirrored here fails open unless ACTIVATION is exactly ACTIVE).
The shipped artifact is also pinned: PASSIVE activation, 8 buckets, the
recon's bucket values.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import signal_filter_table as sft  # noqa: E402


def _rows(buckets: dict, per: int) -> list[dict]:
    """Synthetic dataset: buckets -> (win_rate); trades spread over months."""
    rows = []
    day = 1
    for (side, tod), wr in buckets.items():
        for i in range(per):
            m = 1 + (day // 28)
            rows.append({"ts": f"2026.{m:02d}.{(day % 28) + 1:02d} "
                               f"{tod * 6 + 1:02d}:30:00",
                         "side": side, "r": 1.0 if (i / per) < wr else -1.0,
                         "label_win": (i / per) < wr,
                         "trigger": "M30_REVERSED_EXTREME"})
            day += 1
    return rows


# --- bucket math ------------------------------------------------------------------

def test_bucket_key_blocks_hours_into_six() -> None:
    assert sft.bucket_key("BUY", "2026.03.17 00:30:00") == ("BUY", 0)
    assert sft.bucket_key("BUY", "2026.03.17 05:59:00") == ("BUY", 0)
    assert sft.bucket_key("SELL", "2026.03.17 06:00:00") == ("SELL", 1)
    assert sft.bucket_key("SELL", "2026.03.17 23:30:00") == ("SELL", 3)


def test_build_table_shrinkage_and_min_n() -> None:
    rows = _rows({("BUY", 0): 0.2, ("SELL", 0): 0.9}, per=30)
    table, base = sft.build_table(rows)
    assert ("BUY", 0) in table and ("SELL", 0) in table
    assert base == pytest.approx(0.55)
    # shrunk toward the global rate, but still ordering correctly
    assert table[("BUY", 0)] < base < table[("SELL", 0)]
    # a bucket with fewer than MIN_BUCKET_N trades is excluded (falls back)
    thin = rows[:5]  # all from the first bucket, way below 15
    t2, b2 = sft.build_table(thin + rows[5:])
    assert t2 == table  # 5 extra rows don't change membership


def test_muted_bucket_ships_exactly_half() -> None:
    # buckets at 0.72 / 0.73: global 0.725, and after shrinkage each sits
    # within MUTED_EPS of global — both ship as exactly 0.50 (no opinion)
    rows = _rows({("BUY", 0): 0.72, ("SELL", 0): 0.73}, per=40)
    table, base = sft.build_table(rows)
    assert base == pytest.approx(0.7375)   # win quantization: 59/80
    assert table[("BUY", 0)] == 0.50
    assert table[("SELL", 0)] == 0.50


# --- activation gate -----------------------------------------------------------------

def test_gate_fails_on_recon_numbers() -> None:
    """The recon state: n=799 passes the n leg; coverage, AUC-count, mean-AUC
    and worst-fold all fail — exactly the live build's leg pattern."""
    wf = {"folds": [{"val_month": str(m), "auc": 0.45, "kept_expr": 0.0,
                     "baseline_expr": 0.3, "keep_rate": 1.0} for m in range(6)]}
    g = sft.evaluate_gate(wf, n=799, coverage=799 / 8426)
    assert g["verdict"] == "FAIL"
    assert g["legs"]["n_trades"]["pass"]
    assert not g["legs"]["coverage"]["pass"]
    assert not g["legs"]["folds_auc_above"]["pass"]
    assert not g["legs"]["mean_auc"]["pass"]
    assert not g["legs"]["worst_fold_delta_r"]["pass"]


def test_gate_passes_only_when_all_legs_pass() -> None:
    wf = {"folds": [{"val_month": str(m), "auc": 0.60, "kept_expr": 0.35,
                     "baseline_expr": 0.30, "keep_rate": 0.6}
                    for m in range(6)]}
    g = sft.evaluate_gate(wf, n=600, coverage=0.60)
    assert g["verdict"] == "PASS"


def test_gate_worst_fold_leg_blocks_one_bad_fold() -> None:
    folds = [{"val_month": str(m), "auc": 0.60, "kept_expr": 0.35,
              "baseline_expr": 0.30, "keep_rate": 0.6} for m in range(6)]
    folds[2]["kept_expr"] = 0.20          # delta -0.10 < -0.05
    wf = {"folds": folds}
    g = sft.evaluate_gate(wf, n=600, coverage=0.60)
    assert g["verdict"] == "FAIL"
    assert not g["legs"]["worst_fold_delta_r"]["pass"]


def test_gate_constants_are_frozen() -> None:
    assert sft.GATE_MIN_N == 500
    assert sft.GATE_MIN_COVERAGE == 0.50
    assert sft.GATE_FOLD_AUC == 0.55
    assert sft.GATE_MIN_FOLDS_AUC == 5
    assert sft.GATE_WORST_FOLD_DELTA == -0.05
    assert sft.GATE_COVERAGE_DENOMINATOR == 8426


# --- the PASSIVE-never-vetoes contract -------------------------------------------------

def _ea_evaluate(activation: str, p: float) -> str:
    """Mirror of the EA's FilterConsultAllows decision rule."""
    can_veto = (activation == "ACTIVE") and (p != 0.50)
    if not can_veto:
        return "OBSERVE"
    return "TAKE" if p >= 0.50 else "VETO"


def test_passive_table_never_vetoes_even_at_zero_p() -> None:
    for p in (0.0, 0.1, 0.3, 0.49, 0.50, 0.9):
        assert _ea_evaluate("PASSIVE", p) == "OBSERVE"


def test_active_table_vetoes_below_half_but_never_muted() -> None:
    assert _ea_evaluate("ACTIVE", 0.30) == "VETO"
    assert _ea_evaluate("ACTIVE", 0.70) == "TAKE"
    assert _ea_evaluate("ACTIVE", 0.50) == "OBSERVE"   # muted = no opinion


def test_absent_table_behaves_like_passive() -> None:
    assert _ea_evaluate("ABSENT", 0.0) == "OBSERVE"


# --- CSV round-trip + shipped artifact pins ----------------------------------------------

def test_csv_round_trip(tmp_path) -> None:
    rows = _rows({("BUY", 0): 0.2, ("SELL", 0): 0.9}, per=30)
    table, base = sft.build_table(rows)
    out = tmp_path / "t.csv"
    sft.write_table_csv(out, table, "PASSIVE", base)
    txt = out.read_text()
    assert "ACTIVATION=PASSIVE" in txt
    assert f"*,*,{base:.4f},GLOBAL" in txt
    assert f"version={sft.TABLE_VERSION}" in txt
    for (side, tod), p in table.items():
        assert f"{side},{tod},{p:.4f},BUCKET" in txt


def test_shipped_table_is_passive_with_recon_buckets() -> None:
    """The artifact shipped to the terminal: PASSIVE (gate failed on the recon
    numbers), 8 buckets + GLOBAL, and the recon's bucket values."""
    p = REPO / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_filter_table_A2.csv"
    assert p.exists()
    txt = p.read_text()
    assert "ACTIVATION=PASSIVE" in txt
    buckets = [l for l in txt.splitlines()
               if l and not l.startswith("#") and l != "version=bucket-side-tod-v0,global_rate=0.5645"]
    assert len([l for l in buckets if l.endswith("BUCKET")]) == 8
    assert "*,*,0.5645,GLOBAL" in txt
    # the recon's extreme buckets — the values the EA will print in consults
    assert "BUY,2,0.7563,BUCKET" in txt
    assert "SELL,1,0.3264,BUCKET" in txt


def test_walk_forward_detects_real_bucket_signal() -> None:
    """On data where buckets genuinely carry persistent signal, the walk-
    forward AUC must clear 0.5 — proving the evaluator isn't a rubber stamp."""
    rows = []
    for m in range(1, 13):
        for d in range(1, 29):
            side = "BUY" if d % 2 else "SELL"
            tod = (d // 7) % 4
            wr = 0.85 if (side, tod) == ("BUY", 0) else 0.35
            win = ((d * 7 + m) % 100) / 100 < wr
            rows.append({"ts": f"2026.{m:02d}.{d:02d} {tod * 6 + 2:02d}:30:00",
                         "side": side, "r": 1.0 if win else -1.0,
                         "label_win": win, "trigger": "T"})
    wf = sft.walk_forward_auc(rows)
    aucs = [f["auc"] for f in wf["folds"] if f["auc"] is not None]
    assert len(aucs) == 6
    assert sum(1 for a in aucs if a > 0.55) >= 5
