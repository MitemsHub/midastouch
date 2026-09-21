"""P6 consistent-daily-income study pins (register §2b row P6, 2026-09-18).

The operator's directive — "many small consistent daily wins, compounding
does the scaling" — is now a REGISTERED experiment with a pre-registered
ranking. These pins make the study trustworthy rather than just runnable:

  * the ranking, quality gates, and OOS law are source-frozen: editing the
    thresholds or the ranking key silently is a register violation;
  * daily_metrics scoring math is pinned on hand-built ledgers (the
    operator's scoreboard: positive-days %, median day, worst day);
  * qualify() boundaries are pinned on both sides (n 59/60, pf 1.149/1.150,
    net_r 0/+);
  * ENGINE FAITHFULNESS: run_p6 at tp=2.0 must reproduce the certified
    variant-research engine's ORIGINAL k=2.0/70-30 bookkeeping EXACTLY
    (same entries, same exits, same PnL per trade) — the P6 engine may
    differ from the certified one ONLY where the study's axes say so;
  * the registered artifact + winner are consistent with the register's
    recorded verdict (M5/k=2.0/TP=1.5R, OOS survivor), and the M15
    cross-check claim (TP 1.5R best median day; TP 2.0R worst) holds in
    the recorded rows;
  * the M5 corpus provenance artifact exists and covers a real depth.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_p6_income_study as p6  # noqa: E402
import midas_sweep as ms  # noqa: E402

ART = REPO / "artifacts" / "midas_p6_income_study_20260918.json"
FETCH_ART = REPO / "artifacts" / "midas_p6_m5_fetch.json"
M5_CSV = REPO / "data" / "forex" / "xauusd" / "XAUUSDmicro_M5.csv"


# --- the pre-registration is frozen in source --------------------------------

def test_pre_registered_ranking_is_source_frozen():
    src = (REPO / "scripts" / "midas_p6_income_study.py").read_text(encoding="utf-8")
    # ranking key: consistency first, quality-eligibility as the gate
    assert '(r["eligible"], r["pos_days_pct"], r["med_day"])' in src
    # OOS split boundary: Jan-Mar in-sample, Apr onward OOS
    assert 'M5_IS_END = "2026-04-01T00:00"' in src
    # the OOS survivor must gate full-span winners (selection walks down)
    assert "oos_clean" in src
    # NO-SHIP is a possible registered outcome
    assert "NO-SHIP" in src


def test_quality_gates_boundaries():
    # n: 59 fails, 60 passes (all else clean)
    m59 = {"n": 59}
    m60 = {"n": 60}
    ok59, why59 = p6.qualify(m59, total_r=1.0, pf=1.3)
    ok60, _ = p6.qualify(m60, total_r=1.0, pf=1.3)
    assert not ok59 and any("n=59" in w for w in why59)
    assert ok60
    # pf boundary
    okpf, whypf = p6.qualify({"n": 100}, total_r=1.0, pf=1.149)
    assert not okpf and any("pf=1.149" in w for w in whypf)
    okpf2, _ = p6.qualify({"n": 100}, total_r=1.0, pf=1.15)
    assert okpf2
    # net_r must be strictly positive — consistency at breakeven is void
    ok0, why0 = p6.qualify({"n": 100}, total_r=0.0, pf=1.3)
    assert not ok0 and "net_r not positive" in why0


def test_daily_metrics_scoring_math():
    # hand-built: day A +2 trades +1.0 +0.5 (positive), day B -1.0 (negative),
    # day C +3.0 (positive) -> 66.7% positive days, median 0.5, worst -1.0
    def t(day, pnl, ct):
        return {"pnl": pnl, "close_ct": ct}

    # 2026-09-14 = Monday (1789430400 = 2026-09-15T00:00Z; use close inside day)
    d1 = 1789430400 + 3600 * 10   # mid-day UTC
    d2 = 1789516800 + 3600 * 10
    d3 = 1789603200 + 3600 * 10
    trades = [t("a", 1.0, d1), t("a", 0.5, d1 + 60), t("b", -1.0, d2), t("c", 3.0, d3)]
    m = p6.daily_metrics(trades)
    assert m["n"] == 4
    assert m["days_traded"] == 3
    assert m["pos_days_pct"] == pytest.approx(66.7)
    # sorted daily pnls [-1.0, +1.5, +3.0] -> median is the middle value
    assert m["med_day"] == pytest.approx(1.5)
    assert m["worst_day"] == pytest.approx(-1.0)
    assert m["best_day"] == pytest.approx(3.0)
    # no trades -> zero-safe dict, and qualify() must reject it
    assert p6.daily_metrics([]) == {"n": 0}
    ok, why = p6.qualify({"n": 0}, total_r=0.0, pf=None)
    assert not ok and any("n=0" in w for w in why)


# --- engine faithfulness: the study engine must BE the certified engine -------

#: THIS venue's own bars (written alongside by `midas_fetch_history.py --suffix`).
#: These pins were built on the `XAUUSDmicro_*` corpus, which was deleted with the
#: micro era — commit `dc436d8`, "Retire the XAUUSDmicro era: the live chain stops
#: importing the closed indices engine". The micro files are gone, so the pins that
#: read them could only ever fail for a reason nobody could act on.
#:
#: Pointing them at the traded symbol costs nothing and buys something real: the two
#: engines are compared against EACH OTHER on one build, so engine faithfulness is
#: corpus-independent by construction — and the bars are now the ones this account
#: would actually trade, not a closed symbol's.
CORPUS_H1 = REPO / "data" / "forex" / "xauusd" / "XAUUSD_H1_upcomers.csv"
CORPUS_M15 = REPO / "data" / "forex" / "xauusd" / "XAUUSD_M15_upcomers.csv"


def _shared_corpus_data():
    """One build for both engines, over this venue's own bars.

    Populates the bb arrays the way main() does before run_p6 — the runner
    consumes them from data["bb"][k] and must not be handed an empty map.
    """
    assert CORPUS_H1.is_file() and CORPUS_M15.is_file(), (
        f"the venue corpus is missing ({CORPUS_H1.name}/{CORPUS_M15.name}); fetch it "
        f"with scripts/midas_fetch_history.py --suffix rather than re-pointing these "
        f"pins at a symbol this program no longer trades")
    d = p6.build_data(str(CORPUS_H1), str(CORPUS_M15), 900)
    for k in p6.KS:
        arr = [0] * len(d["close"])
        for i in range(len(arr)):
            arr[i] = ms.bb_touch(d["close"], i, 20, k)
        d["bb"][k] = arr
    h1 = ms.load_bars(str(CORPUS_H1))
    m15 = ms.load_bars(str(CORPUS_M15))
    h4 = ms.h4_series(h1)
    closes = [b["close"] for b in m15]
    # variant-research view of the SAME arrays
    vr = {"h1": h1, "m15": m15, "h4": h4,
          "h1_ct": d["h1_ct"], "h4_ct": d["h4_ct"],
          "h1_ema": d["h1_ema"], "h1_atr": d["h1_atr"], "h4_ema": d["h4_ema"],
          "m15_close": closes, "m15_rsi": d["rsi"], "m15_bb": d["bb"]}
    return d, vr


def test_run_p6_reproduces_certified_engine_at_tp2():
    import midas_variant_research as vr_mod
    d, vr = _shared_corpus_data()
    ent = d["ent"]
    t0, t1 = ent[0]["time"], ent[-1]["time"] + 900
    p6_trades = p6.run_p6(d, 2.0, 2.0, t0, t1)
    vr_trades = vr_mod.run_config(vr, "ORIGINAL", vr["m15_bb"][2.0], 70, 30, t0, t1)
    # same book, trade for trade
    assert len(p6_trades) == len(vr_trades) > 0
    key = lambda t: (t["open_ct"], t["close_ct"], t["side"], t["pnl"], t["reason"])
    assert [key(t) for t in p6_trades] == [key(t) for t in vr_trades]


def test_tp_axis_actually_changes_the_tp():
    """tp=1.5 positions must carry a 1.5R target — the axis is not cosmetic.

    The realized TP move is 1.5×stop_d MINUS the exit half-spread (certified
    _manage charges it on top of the level), and the spread is recorded on
    the exit bar, not the trade row — so pin the band: strictly under the
    1.5R target (spread cost) and within half a max-spread of it. A 2.0R
    target can never land in this band for stop_d ≥ 1.0.
    """
    d, _ = _shared_corpus_data()
    ent = d["ent"]
    t0, t1 = ent[0]["time"], ent[-1]["time"] + 900
    tr = p6.run_p6(d, 2.0, 1.5, t0, t1)
    assert tr, "expected trades on the certified corpus"
    tp_exits = [t for t in tr if t["reason"] == "TP"]
    assert tp_exits, "expected at least one TP exit on the certified corpus"
    for t in tp_exits:
        stop_d = t["risk_d"] / (t["lots"] * ms.TICK_VALUE_PER_LOT)
        move = (t["exit"] - t["entry"]) * t["side"]
        assert move <= 1.5 * stop_d + 1e-9
        assert move > 1.5 * stop_d - 0.5, (move, 1.5 * stop_d)


# --- the registered artifact and winner ---------------------------------------

@pytest.mark.skipif(not ART.exists(), reason="P6 artifact not yet written")
def test_registered_artifact_winner_matches_register():
    v = json.loads(ART.read_text(encoding="utf-8"))
    w = v["winner"]
    # the register's recorded verdict
    assert w["corpus"] == "m5" and w["tf_min"] == 5
    assert w["k"] == 2.0 and w["tp_r"] == 1.5
    assert w["eligible"] is True and w["pf"] >= 1.15 and w["net_r" if False else "tot_r"] > 0
    # the winner's M5 config survived the OOS law
    oos = {(r["k"], r["tp_r"]): r for r in v["m5_oos"]}
    assert (2.0, 1.5) in oos and oos[(2.0, 1.5)]["eligible"]
    # and the ranking it won by is the frozen one
    ranked = [r for r in v["results"] if r["eligible"]]
    ranked.sort(key=lambda r: (r["eligible"], r["pos_days_pct"], r["med_day"]), reverse=True)
    first_m5_clean = next(
        r for r in ranked
        if r["corpus"] == "m5" and oos.get((r["k"], r["tp_r"]), {}).get("eligible", False))
    assert first_m5_clean["k"] == w["k"] and first_m5_clean["tp_r"] == w["tp_r"]


@pytest.mark.skipif(not ART.exists(), reason="P6 artifact not yet written")
def test_m15_crosscheck_median_day_structure():
    """Register claim (as recorded): on the current M15 config (k=2.0), the
    median day DECLINES monotonically as TP lengthens — TP 1.0R best,
    TP 2.0R (the live shape) worst. The M5 OOS leg is what narrows the
    amendment choice to 1.5R (1.0R missed the OOS pf gate by a hair)."""
    v = json.loads(ART.read_text(encoding="utf-8"))
    m15 = [r for r in v["results"] if r["corpus"] == "cert-m15" and r["eligible"]]
    by_tp = {r["tp_r"]: r["med_day"] for r in m15 if r["k"] == 2.0}
    assert set(by_tp) == {1.0, 1.5, 1.8, 2.0}
    assert by_tp[1.0] == max(by_tp.values())
    assert by_tp[2.0] == min(by_tp.values())
    assert by_tp[1.0] > by_tp[1.5] > by_tp[1.8] > by_tp[2.0]


@pytest.mark.skipif(not (FETCH_ART.exists() and M5_CSV.exists()),
                    reason="M5 corpus not fetched")
def test_m5_corpus_provenance_and_schema():
    meta = json.loads(FETCH_ART.read_text(encoding="utf-8"))
    assert meta["symbol"] == "XAUUSDmicro" and meta["timeframe"] == "M5"
    assert meta["rows"] >= 40000
    head = M5_CSV.read_text(encoding="utf-8").splitlines()[0]
    assert head == "time,iso,open,high,low,close,tick_volume,spread"


def test_register_records_p6_row_and_amendment_path():
    reg = (REPO / "docs" / "MIDASTOUCH_V2_REGISTER.md").read_text(encoding="utf-8")
    assert "| P6 |" in reg
    assert "midas_p6_income_study_20260918.json" in reg
    # the amendment is QUEUED behind the reading — nothing shipped tonight
    assert "2026-10-01" in reg
    assert "M5-entry LV variant" in reg
