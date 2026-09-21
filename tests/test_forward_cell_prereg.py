"""Pins for the forward-cell pre-registration: the arithmetic, the refusals, and the mask.

WHY THIS FILE EXISTS. `docs/GOLD_PREREG_FORWARD_CELL_20260921.md` declares a sample, a threshold,
a futility rule and a cell, and then hands the measurement to `scripts/gold_forward_cell_prereg.py`
on a record that does not exist yet (the arm's ledger holds 0 closed trades). Everything that could
go wrong between now and that measurement is a drift, and drift is what this file catches:

* **the arithmetic** — the MDE, the dispersion and the sample are the declaration's promises; if an
  edit moves one, the promise is broken before any data arrives, and the suite says so;
* **the refusals** — below the futility floor nothing may be printed as encouragement, a month
  without a single server offset may not be defaulted, and a row beyond the data of record may not
  be guessed into (or out of) the cell. Each has a test that fails if the refusal is softened;
* **the mask itself** — the last test round-trips the study's own 658 entries through the ledger's
  SERVER frame and checks the harness reproduces the artifact's cell exactly (199 trades, 92/107 at
  the midpoint, +0.6210R/+0.6918R). It costs ~17 s because it regenerates the entry set; that is
  the price of proving the forward label is the same measurement as the selection's, and it skips
  when the data of record is absent (data/ is gitignored, like artifacts/).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gold_forward_cell_prereg as fw  # noqa: E402
import gold_governed_wfo as gg  # noqa: E402
import gold_persistence_state as gps  # noqa: E402
import gold_walkforward as gw  # noqa: E402
import midas_first_fills_audit as ffa  # noqa: E402
import midas_sweep as S  # noqa: E402

DOC = ROOT / "docs" / "GOLD_PREREG_FORWARD_CELL_20260921.md"
#: The venue's own M15 series: the data of record, and the input every axis of the mask is built
#: from. `data/` is gitignored, so a checkout without it skips the round-trip rather than failing.
M15 = Path(S.DATA_DIR) / "XAUUSD_M15_upcomers.csv"
NO_DATA = ("the venue's own M15 series is absent (data/ is gitignored) — fetch it with "
           "python scripts/midas_fetch_history.py --suffix _upcomers")
SIG_OPEN_UTC = 1_790_000_000                       # an arbitrary in-range signal-bar open
NEWS_OUT, NEWS_IN = False, True


def _row(sig_open_utc: int = SIG_OPEN_UTC, off_min: int = 120, net_r: float = 1.0) -> dict:
    """A ledger trade dict as `midas_first_fills_audit.read_ledger` shapes it.

    `open_ct` is SERVER time and lands one M15 bar after the signal bar closes, which is what the
    audit's two -900s mean; the harness must undo exactly that.
    """
    return {"open_ct": sig_open_utc + off_min * 60 + fw.FILL_LAG, "net_r": net_r,
            "close_ct": sig_open_utc + off_min * 60 + 4 * 3600, "pnl": net_r * 100.0,
            "ticket": "1"}


def _axes(sig_open_utc: int = SIG_OPEN_UTC, ratio: float = 1.0,
          news_in: bool = NEWS_OUT) -> dict:
    """A one-bar venue series: `ratio` picks the volatility bin, `news_in` the news bin."""
    return {"index": {sig_open_utc: 0}, "atr": np.array([ratio]), "atr_med": np.array([1.0]),
            "hours": np.array([8]), "ok": {}, "news_mask": np.array([news_in]),
            "news_note": "synthetic", "last_epoch": sig_open_utc}


@pytest.fixture
def plain_offset(monkeypatch):
    """Pin the server offset so these tests measure the harness, not the era table."""
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: 120)


# ---------------------------------------------------------- the declaration's arithmetic

def test_the_declared_sample_is_the_number_the_document_publishes():
    """The MDE and the dispersion are promises; the sample they imply is arithmetic."""
    assert fw.MDE_R == 0.15
    assert fw.SD_PLAN == 1.10
    assert fw.n_required() == 207
    assert fw.n_power80() == 423
    assert fw.CERT_T == pytest.approx(1.9604, abs=1e-4)
    assert gw.selection_threshold(2) == pytest.approx(2.2369, abs=1e-4)
    assert gw.selection_threshold(3) == pytest.approx(2.3867, abs=1e-4)


def test_the_document_and_the_harness_cannot_drift_apart():
    """Every number the harness decides with must be legible in the declaration it implements."""
    text = DOC.read_text(encoding="utf-8")
    for needle in ("207", "423", "1.9604", "2.2369", "2.3867", "1790001518",
                   "vol=normal | sess=06-12 | news=out", "+0.15 R/trade", "1.10 R",
                   "0.20", "ATR_LOOKBACK = 500"):
        assert needle in text, f"the declaration no longer states {needle!r}"


def test_the_declaration_names_only_scripts_that_exist():
    """A pre-registration an operator cannot run is a promise with no instrument behind it."""
    import re
    refs = set(re.findall(r"scripts[\\/]([A-Za-z0-9_.\-]+\.py)",
                          DOC.read_text(encoding="utf-8")))
    assert refs, "the declaration names no harness at all"
    missing = sorted(r for r in refs if not (ROOT / "scripts" / r).is_file())
    assert not missing, f"the declaration names scripts that do not exist: {missing}"


def test_the_cell_string_is_built_from_the_studys_own_axes():
    """The label must come from the constants that produced it, not from a re-typed string."""
    assert fw.CELL_PRIMARY == "vol=normal|sess=06-12|news=out"
    assert fw.CELL_SECONDARY_A_PREFIX == "vol=normal|sess=06-12"
    assert fw.CELL_PRIMARY == gps.cell_of(0, {}, np.array([1.0]), np.array([1.0]),
                                          np.array([8]), np.array([NEWS_OUT]))
    assert fw.CELL_SECONDARY_A_PREFIX == gps.cell_of(0, {}, np.array([1.0]), np.array([1.0]),
                                                     np.array([8]), None)


# ------------------------------------------------------------------- the refusals

def test_a_row_in_the_cell_is_labelled_in_and_one_out_of_it_is_not(plain_offset):
    inside = _row()
    high_vol = _row(net_r=0.0)
    late = _row(net_r=0.0)
    labelled, meta = fw.label_rows([inside], _axes())
    assert [r["cell"] for r in labelled] == [fw.CELL_PRIMARY]
    assert meta["excluded"] == {}
    # the same row against a high-volatility bar, and against a news-blackout bar
    got_hi, _ = fw.label_rows([high_vol], _axes(ratio=2.0))
    got_news, _ = fw.label_rows([late], _axes(news_in=NEWS_IN))
    assert got_hi[0]["cell"] == "vol=high|sess=06-12|news=out"
    assert got_news[0]["cell"] == "vol=normal|sess=06-12|news=IN"
    assert got_hi[0]["cell"] != fw.CELL_PRIMARY
    assert got_news[0]["cell"] != fw.CELL_PRIMARY
    # the two-axis label drops the news axis and nothing else
    assert got_news[0]["cell_2axis"] == fw.CELL_SECONDARY_A_PREFIX


def test_a_signal_bar_beyond_the_data_of_record_is_excluded_not_guessed(plain_offset):
    """Out-of-cell is evidence; beyond-the-data is a gap. They are never merged."""
    beyond = _row(sig_open_utc=SIG_OPEN_UTC + 86_400)
    labelled, meta = fw.label_rows([beyond], _axes())
    assert labelled == []
    assert len(meta["excluded"]) == 1
    reason = next(iter(meta["excluded"]))
    assert "data of record" in reason and "midas_fetch_history" in reason


def test_a_month_without_a_single_offset_is_refused_not_defaulted(monkeypatch):
    month = datetime.fromtimestamp(SIG_OPEN_UTC, tz=timezone.utc).strftime("%Y-%m")
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda m: None)
    got, why = fw.utc_of_server(SIG_OPEN_UTC)
    assert got is None and month in why and "DST" in why
    labelled, meta = fw.label_rows([_row()], _axes())
    assert labelled == []
    assert any("unresolvable server offset" in r for r in meta["excluded"])


def test_the_fill_lag_is_the_audits_own_two_subtractions():
    """The mask and the wire-contract audit must agree on which bar the signal is."""
    assert fw.FILL_LAG == 1800
    assert fw.FILL_LAG == 900 + 900          # the audit's sig_ct then sig_bar_open


def test_the_unlabellable_cap_fires_above_its_declared_share():
    assert fw.UNLABELLABLE_MAX == 0.20
    assert fw.unlabellable_flood(5, 20) == (True, pytest.approx(0.25))
    assert fw.unlabellable_flood(3, 20)[0] is False
    assert fw.unlabellable_flood(0, 0) == (False, 0.0)


# ------------------------------------------------------------ the declared decision

_OK_PROPS = {"daily_ok": True, "best_day_ok": True}
_BAD_PROPS = {"daily_ok": False, "best_day_ok": True}


def _st(n: int, mean: float | None, t: float | None, sd: float = 1.10) -> dict:
    return {"n": n, "mean_r": mean, "t": t, "sd": sd, "total_r": (mean or 0.0) * n}


def test_a_short_record_can_never_be_reported_as_promising():
    """The failure mode this whole apparatus exists to prevent, pinned by name."""
    verdict, reason = fw.decide(10, _st(10, 2.0, 9.0), _OK_PROPS, fw.n_required())
    assert verdict == "NOT EVALUABLE" and "futility" in reason
    # even an apparently enormous effect at n=60, still below the declared sample
    verdict, reason = fw.decide(60, _st(60, 0.5, 2.5), _OK_PROPS, fw.n_required())
    assert verdict == "NOT EVALUABLE" and "not yet decidable" in reason


def test_the_kill_rule_fires_at_the_declared_floor_and_outranks_everything():
    verdict, reason = fw.decide(fw.FUTILITY_N, _st(fw.FUTILITY_N, -0.01, -1.0),
                                _OK_PROPS, fw.n_required())
    assert verdict == "KILL" and "declared dead" in reason
    # a negative mean at a full sample is still KILL, not FAIL: the weaker number is never quoted
    verdict, _ = fw.decide(300, _st(300, -0.2, -3.0), _OK_PROPS, fw.n_required())
    assert verdict == "KILL"


def test_the_variance_only_revision_is_disclosed_and_may_only_grow_the_sample():
    st = _st(120, 0.30, 1.2, sd=1.45)
    verdict, reason = fw.decide(120, st, _OK_PROPS, fw.n_required())
    assert verdict == "NOT EVALUABLE"
    assert "variance-only revision" in reason
    revised = fw.n_required(sd=1.45)
    assert revised > fw.n_required() and str(revised) in reason


def test_a_full_sample_below_the_threshold_fails_and_above_it_passes_only_as_a_candidate():
    verdict, reason = fw.decide(fw.n_required(), _st(fw.n_required(), 0.16, 1.20),
                                _OK_PROPS, fw.n_required())
    assert verdict == "FAIL" and "does not carry forward" in reason
    verdict, reason = fw.decide(250, _st(250, 0.25, 2.60), _OK_PROPS, fw.n_required())
    assert verdict == "PASS" and "CANDIDATE" in reason


def test_a_venue_rule_breach_blocks_the_pass_even_with_a_significant_cell():
    verdict, reason = fw.decide(250, _st(250, 0.25, 2.60), _BAD_PROPS, fw.n_required())
    assert verdict == "FAIL" and "breaches a venue rule" in reason


# ----------------------------------------------------------------- the record's plumbing

def test_live_layer_rows_are_counted_but_kept_out_of_the_paper_statistic(tmp_path):
    """One signal, two execution models: mixing them would double-count the trade."""
    led = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    led.write_text("ERA,MIDAS1.19,1789996684,note\n"
                   "EQ,25000.00\n"
                   "OPEN,1790000200,7,1,4000.00000,3990.00000,4020.00000,0.10,10.00,10.00000,"
                   "720,U25,10.00000,0.20000\n"
                   "CLOSE,1790001000,7,TARGET,4020.00000,2.000,20.00,25020.00,0.20000,0.0,"
                   "2.0,0,1\n"
                   "LOPEN,1790002000,8,1,4001.00000,3991.00000,4021.00000,0.10,10.00,10.00000,"
                   "720,U25,10.00000,0.20000\n"
                   "LCLOSE,1790003000,8,STOP,3991.00000,-1.000\n", encoding="utf-8")
    led_parsed = ffa.read_ledger(str(led))
    assert [t["r"] for t in led_parsed["trades"]] == [2.0]
    assert fw.count_live_rows(str(led)) == 2


# --------------------------------------------- the harness end to end, on synthetic records

#: One row per UTC day. Compressing the sample into a couple of days is not a shortcut here: the
#: declared PASS also requires the venue's 20% Best Day ceiling, and a record with 200 trades in two
#: days breaches it — correctly. The synthetic record has to be shaped like a real one to test the
#: rules that grade a real one.
_STEP = 86_400
#: The first 08:00 UTC at or after the declaration's cutoff. Starting at a fixed UTC HOUR is what
#: lets a stamped row and the rebuilt axes describe the SAME instant, so a test that varies one of
#: them varies exactly one thing.
_BASE = (fw.CUTOFF_EPOCH // _STEP + 1) * _STEP + 8 * 3600


def _synthetic_ledger(tmp_path: Path, n_cell: int, rs: list[float],
                      stamp: float | None = None) -> Path:
    """A ledger whose rows all sit on in-cell bars, priced at the given R values.

    `sig_open_utc` values step one day apart from just after the declaration cutoff, so every row
    clears the cutoff filter, lands on its own bar of the synthetic series, and sits on its own
    UTC day for the daily-rule checks.

    `stamp` adds the EA's v1.19e state tail with that volatility RATIO — the recorded label is then
    the one the statistic must use, and a stamp that disagrees with the rebuilt axes is how the
    preference is tested rather than asserted.
    """
    base = _BASE
    rows = []
    for i, r in enumerate(rs[:n_cell]):
        sig = base + _STEP * i
        pnl = r * 100.0
        tail = ("" if stamp is None else
                f",{sig + 120 * 60},{sig % 86400 // 3600},{stamp:.5f},out,120")
        rows.append(f"OPEN,{sig + 120 * 60 + fw.FILL_LAG},{i + 1},1,4000.00000,3990.00000,"
                    f"4020.00000,0.10,10.00,10.00000,720,U25,10.00000,0.20000{tail}")
        rows.append(f"CLOSE,{sig + 120 * 60 + fw.FILL_LAG + 3600},{i + 1},TARGET,4020.00000,"
                    f"{r:.3f},{pnl:.2f},{25000 + pnl:.2f},0.20000,0.0,2.0,0,1")
        rows.append(f"EQ,{25000 + pnl:.2f}")
    led = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    led.write_text("ERA,MIDAS1.19,1789996684,synthetic\nEQ,25000.00\n" + "\n".join(rows) + "\n",
                   encoding="utf-8")
    return led


def _synthetic_axes(n: int, base: int | None = None) -> dict:
    """`n` in-cell bars one day apart: normal volatility, 08:00 UTC, outside news."""
    base = _BASE if base is None else base
    epochs = [base + _STEP * i for i in range(n)]
    return {"index": {e: i for i, e in enumerate(epochs)},
            "atr": np.ones(n), "atr_med": np.ones(n), "hours": np.full(n, 8),
            "ok": {}, "news_mask": np.zeros(n, dtype=bool), "news_note": "synthetic",
            "last_epoch": epochs[-1]}


def _run(tmp_path: Path, monkeypatch, n_cell: int, rs: list[float],
         stamp: float | None = None) -> tuple[int, str, dict]:
    """Run the harness end to end and return (exit code, verdict, the written artifact)."""
    led = _synthetic_ledger(tmp_path, n_cell, rs, stamp=stamp)
    out = tmp_path / "out.json"
    monkeypatch.setattr(fw, "build_axes", lambda symbol, bars: _synthetic_axes(n_cell))
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: 120)
    code = fw.main(["--ledger", str(led), "--out", str(out)])
    art = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return code, art.get("verdict"), art


def test_the_harness_kills_a_negative_cell_at_the_declared_floor(tmp_path, monkeypatch):
    """KILL is reachable and its exit code is distinct: the rule that can fire soon."""
    n = fw.FUTILITY_N
    code, verdict, _ = _run(tmp_path, monkeypatch, n, [-0.10] * n)
    assert (code, verdict) == (4, "KILL")


def test_the_harness_fails_a_full_sample_below_the_threshold(tmp_path, monkeypatch):
    """A decided, negative verdict at the declared sample — and never called a candidate."""
    n = fw.n_required()
    rs = [1.0 if i % 4 else -2.9 for i in range(n)]        # mean ~ +0.018R, t ~ +0.25
    code, verdict, _ = _run(tmp_path, monkeypatch, n, rs)
    assert (code, verdict) == (0, "FAIL")


def test_the_harness_passes_only_at_the_declared_sample_with_a_real_effect(tmp_path, monkeypatch):
    """PASS needs the sample, the effect AND unbroken venue rules; it is a candidate, not a win."""
    n = fw.n_required()
    rs = [1.0 if i % 5 < 3 else -0.875 for i in range(n)]   # mean ~ +0.25R, t ~ +3.9
    code, verdict, art = _run(tmp_path, monkeypatch, n, rs)
    assert (code, verdict) == (0, "PASS")
    assert art["counts"]["cell_primary"] == n and art["stats"]["cell_primary"]["t"] >= fw.CERT_T
    # ...and the same numbers below the declared sample are NOT EVALUABLE, exit 3
    code, verdict, _ = _run(tmp_path, monkeypatch, fw.FUTILITY_N, rs[:fw.FUTILITY_N])
    assert (code, verdict) == (3, "NOT EVALUABLE")


def test_the_forward_record_is_labelled_from_the_ea_s_own_stamp(tmp_path, monkeypatch):
    """The stamp decides membership, and its disagreements with the rebuild are REPORTED.

    Two runs over the same rows, the same R values and the same venue series; the only thing that
    changes is what the EA stamped. That is the whole point of the column: the mask no longer
    depends on the data of record reaching the newest row.
    """
    n = fw.n_required()
    rs = [1.0 if i % 5 < 3 else -0.875 for i in range(n)]      # the same series that PASSes
    # stamped HIGH volatility while the synthetic series says normal: the stamp wins, so the
    # primary cell is empty and nothing may be reported as promising
    code, verdict, art = _run(tmp_path, monkeypatch, n, rs, stamp=2.0)
    assert (code, verdict) == (3, "NOT EVALUABLE")
    assert art["counts"]["cell_primary"] == 0
    assert art["labels"]["source"] == {"recorded": n, "rebuilt": 0}
    assert art["labels"]["reconciliation"]["disagree"] == n, (
        "every row must be reconciled, not absorbed")
    # captured of the same record whose stamp agrees: in the cell, and PASS, from the stamp
    code2, verdict2, art2 = _run(tmp_path, monkeypatch, n, rs, stamp=1.0)
    assert (code2, verdict2) == (0, "PASS")
    assert art2["labels"]["primary_cell_by_source"] == {"recorded": n}
    assert art2["labels"]["reconciliation"]["disagree"] == 0


def test_the_harness_reports_an_empty_record_as_not_evaluable(tmp_path, monkeypatch):
    """The state the arm is actually in: no trades, so no verdict and no encouragement."""
    led = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    led.write_text("ERA,MIDAS1.19,1789996684,synthetic\nEQ,25000.00\n", encoding="utf-8")
    monkeypatch.setattr(fw, "build_axes", lambda symbol, bars: _synthetic_axes(4))
    assert fw.main(["--ledger", str(led), "--out", str(tmp_path / "o.json")]) == 3
    art = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    assert art["verdict"] == "NOT EVALUABLE" and art["counts"]["closed_paper"] == 0


# ------------------------------------------------------- the mask reproduces its selection

@pytest.mark.skipif(not M15.is_file(), reason=NO_DATA)
def test_the_forward_mask_reproduces_the_studys_own_cell():
    """The one check that makes this a test of the same cell rather than a lookalike.

    Takes the study's own 658 entries, writes each one back into the LEDGER's frame (server epochs
    with the declared fill lag) and pushes it through the forward labeler, then compares against
    the numbers `artifacts/gold_persistence_state.json` published. Nothing here is re-derived from
    the artifact: the expected values are literals, so this fails if the mask, the frame conversion
    or the axes move.
    """
    import gold_exit_capture as ge
    import gold_prereg_no_target as pn

    B, epoch, n, atr, hours, ok = gg.venue_data(gw.SYMBOL, 60000)
    entries = gg.run_grid(B, hours, ok, atr, pn.entry_config((6, 20)), n)
    trades = ge.simulate_policy(B, entries, atr, stop_mult=1.0, tp=None, trail=None,
                                time_bars=None)
    assert len(trades) == 658

    offsets: dict[str, int | None] = {}
    rows = []
    for t in trades:
        sig_utc = int(epoch[t["entry_i"]])
        month = datetime.fromtimestamp(sig_utc, tz=timezone.utc).strftime("%Y-%m")
        off = offsets.setdefault(month, S.server_offset_for_month(month))
        assert off is not None, f"no single server offset pins {month}; the round-trip is undefined"
        rows.append({"open_ct": sig_utc + off * 60 + fw.FILL_LAG, "net_r": t["net_r"],
                     "close_ct": sig_utc + off * 60 + 4 * 3600, "pnl": 0.0, "ticket": str(t["entry_i"])})

    labelled, meta = fw.label_rows(rows, fw.build_axes(gw.SYMBOL, 60000))
    assert len(labelled) == 658 and meta["excluded"] == {}
    assert meta["news_axis_measurable"] is True

    cell = [r for r in labelled if r["cell"] == fw.CELL_PRIMARY]
    assert len(cell) == 199
    first, last = float(epoch[gw.WARMUP_BARS]), float(epoch[n - 1])
    mid = first + (last - first) / 2.0
    h1 = [r["net_r"] for r in cell if r["sig_open_utc"] < mid]
    h2 = [r["net_r"] for r in cell if r["sig_open_utc"] >= mid]
    assert (len(h1), len(h2)) == (92, 107)
    assert sum(h1) / len(h1) == pytest.approx(0.6210, abs=5e-5)
    assert sum(h2) / len(h2) == pytest.approx(0.6918, abs=5e-5)
