"""The recorded state stamp: one grammar, one binning, and the arithmetic behind it.

WHY THIS FILE EXISTS. `InpRecordStateLabel` makes the EA write the entry's own state into the
ledger's OPEN row (five appended fields), so the pre-registered forward cell
(`docs/GOLD_PREREG_FORWARD_CELL_20260921.md`) can label THIS arm's rows from the record the arm
made instead of rebuilding them from a history file that may not reach the newest row. That buys a
real capability and creates two new ways to be silently wrong:

* **a second definition of the cell.** The EA records a volatility ratio, a UTC hour and a news
  flag; the python side bins them. If the EA's constants drift from the study's axis constants,
  the forward cell stops being the registered cell and nothing in the statistic would show it.
  Pinned here against the python values, by parsing the EA's own source.
* **a reader off by one field.** The grammar is positional and append-only, so the reader's offset
  into the row is pinned against the writer's own format strings: inserting a field in the middle
  fails here instead of mis-labelling every trade from then on.

The arithmetic test at the end is the part a compiler cannot see. It transcribes the EA's
Wilder-recursion-with-warm-up into numpy and measures it against
`gold_walkforward.wilder_atr` + `trailing_percentile` on the venue's own bars — which is exactly
what licenses the harness to PREFER the stamp over the rebuild rather than merely report it.
"""
from __future__ import annotations

import re
import sys
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
from midas_prop.risk import news_calendar as nc  # noqa: E402

EA = ROOT / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
M15 = Path(S.DATA_DIR) / "XAUUSD_M15_upcomers.csv"
NO_DATA = ("the venue's own M15 series is absent (data/ is gitignored) — fetch it with "
           "python scripts/midas_fetch_history.py --suffix _upcomers")
_STATE_DEFINE = re.compile(r"^#define\s+(STATE_\w+)\s+(\S+)")


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def code() -> str:
    """Source with `//` comments removed, so a pin cannot be satisfied by prose."""
    return re.sub(r"//[^\n]*", "", src())


def defines() -> dict[str, str]:
    return {m.group(1): m.group(2) for m in
            (_STATE_DEFINE.match(ln) for ln in src().splitlines()) if m}


def body(fn_name: str) -> str:
    """Brace-matched body of a named function, comments stripped."""
    s = code()
    m = re.search(rf"\b\w+\s+{re.escape(fn_name)}\s*\(", s)
    assert m, f"{fn_name} missing from source"
    j = s.index("{", m.end())
    depth = 0
    for k in range(j, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return s[j:k]
    raise AssertionError(f"unbalanced braces after {fn_name}")


# ---------------------------------------------------- the axes: the EA's constants == the study's

def test_the_stamped_volatility_axis_is_the_studys_own_axis() -> None:
    """The ratio is binned by the study's edges; the ATR behind it is the study's own series."""
    d = defines()
    assert int(d["STATE_ATR_PERIOD"]) == gw.ATR_PERIOD, "the stamp's ATR period is the engine's"
    assert int(d["STATE_VOL_LOOKBACK"]) == gw.ATR_LOOKBACK, "the trailing median's window"
    lo_edge = next(hi for _lo, hi, name in gps.VOL_BINS if name == "low")
    hi_edge = next(hi for _lo, hi, name in gps.VOL_BINS if name == "normal")
    assert float(d["STATE_VOL_LO"]) == lo_edge
    assert float(d["STATE_VOL_HI"]) == hi_edge


def test_the_recorded_hour_is_binned_by_the_studys_session_edges() -> None:
    """The EA writes an hour; `label_of_values` places it — one bin list, not two."""
    assert [name for _lo, _hi, name in gps.SESSIONS] == ["00-06", "06-12", "12-17", "17-22"]
    for lo, _hi, name in gps.SESSIONS:
        assert gps.label_of_values(1.0, lo, False) == f"vol=normal|sess={name}|news=out"


def test_the_news_window_and_filter_are_the_ea_gates_own() -> None:
    """One policy, two readers: the stamp may not use a different window or a different tier."""
    m = re.search(r"InpNewsWindowMin\s*=\s*(\d+)", src())
    assert m and int(m.group(1)) == gps.NEWS_WINDOW_MIN
    assert 'parts[5] != "HIGH"' in body("NewsProximityFlag"), "top-tier only, as the gate is"
    assert nc.IMPORTANCE == "HIGH", "the one definition of top tier, in the shared module"


def test_the_stamp_refuses_instead_of_guessing_when_an_axis_is_missing() -> None:
    """`na` is not `out`, and a sentinel is not a measurement: each one must be refused."""
    assert defines()["STATE_NA"] == '"na"'
    assert int(defines()["STATE_OFF_UNKNOWN"]) == -9999
    na, why = fw.recorded_axes({"state": {"sig_ct": 1, "hour_utc": 8, "vol_ratio": 1.0,
                                          "news": "na", "off_min": 120}})
    assert na is None and "news" in why
    no_off, why = fw.recorded_axes({"state": {"sig_ct": 1, "hour_utc": -1, "vol_ratio": 1.0,
                                              "news": "out", "off_min": -9999}})
    assert no_off is None and "hour_utc" in why
    no_ratio, why = fw.recorded_axes({"state": {"sig_ct": 1, "hour_utc": 8, "vol_ratio": 0.0,
                                                "news": "out", "off_min": 120}})
    assert no_ratio is None and "vol_ratio" in why
    assert fw.recorded_axes({})[0] is None, "a row with no stamp cannot assert anything"


# ------------------------------------------------------------------- the grammar, both sides

def _open_formats() -> list[str]:
    return re.findall(r'"(OPEN,%[^"]*)"', code())


def test_the_readers_offset_is_the_writers_own_row() -> None:
    """A positional grammar pinned positionally, against the writer instead of a fixture."""
    fmts = _open_formats()
    assert len(fmts) == 2, f"expected the BAR and the PERTICK OPEN writers, found {fmts}"
    for f in fmts:
        head_fields = f.count(",") + 1        # the row includes the leading "OPEN" token
        assert head_fields == ffa.WIRE_OPEN_TELEM_N, (
            f"the OPEN head is {head_fields} fields (including the token); the state reader "
            f"starts at index {ffa.WIRE_OPEN_TELEM_N}")
        # v1.25: ONE `%s` for the state stamp AND the configured-risk token, because the writer
        # passes them as ONE concatenated argument. A second `%s` here is not decoration — it is
        # the measured defect (`(missed string parameter)` appended to the row) — and the bytes
        # are identical either way, since each segment starts with its own comma.
        assert f.endswith("%s"), (
            "the state stamp and the v1.22 configured-risk token are APPENDED — state first, "
            "then the keyed cfg token — as one specifier and one argument, never inserted "
            "into the certified head")
    assert ffa.STATE_N == len(ffa.STATE_FIELDS) == 5
    assert ffa.STATE_FIELDS == ("sig_ct", "hour_utc", "vol_ratio", "news", "off_min")
    # and the LIVE row's own head, for whoever reads the live layer next: the arm tag and
    # the _FLOORED suffix share one specifier there, so the tail starts one field earlier
    lopen = re.findall(r'"(LOPEN,%[^"]*)"', code())
    assert len(lopen) == 1, f"expected exactly one LOPEN writer, found {lopen}"
    # the token + 13 payload fields — the arm tag and the _FLOORED suffix share one specifier,
    # so the LIVE head is 14 fields and the state tail starts at index 14 on BOTH row types:
    # one offset reads either.
    assert lopen[0].count(",") == ffa.WIRE_OPEN_TELEM_N - 1, (
        "the LOPEN head must be the same width as the OPEN head")
    assert lopen[0].endswith("%s%s%s"), (
        "tag, _FLOORED, then the state stamp with the risk stamp concatenated after it — "
        "three specifiers for three arguments (v1.25: a fourth asked for an argument that "
        "does not exist, and MQL5 wrote `(missed string parameter)` into the row)")


def test_the_stamp_writes_exactly_five_fields_in_the_declared_order() -> None:
    fmts = re.findall(r'"(,\%[^"]*)"', body("StateAppend"))
    assert fmts, "StateAppend must build the tail itself"
    assert set(fmts) == {",%I64d,%d,%.5f,%s,%d"}, fmts
    assert fmts[0].split(",")[1:] == ["%I64d", "%d", "%.5f", "%s", "%d"], (
        "order is sig_ct, hour_utc, vol_ratio, news, off_min — the reader's order")


def test_the_stamp_rides_every_fill_path_and_never_a_tester_run() -> None:
    """Three writers — BAR OPEN, PERTICK OPEN, and the LIVE LOPEN — and a tester ledger
    that stays byte-identical.

    The third is not decoration. An ARMED arm routes through `LiveSendOrder` and never
    reaches `OpenPaperPosition`, so in the deployed stance the only rows the arm writes are
    `LOPEN`/`LCLOSE`. A stamp on the paper writers alone would leave exactly the record that
    matters unlabelled.
    """
    # Counted on the CONCATENATION, not on a comma: "a comma then StateAppend()" is a
    # whitespace accident, and this pin read 0 the moment the append moved onto its own line.
    #
    # v1.25 SPLIT THE LOPEN TAIL: it is `StateAppend() + EntryPendingAppend() + RiskAppend(...)`,
    # because the configured-risk token is read OFF THE END OF THE ROW
    # (`midas_first_fills_audit._split_risk_tail` takes `fields[-1]`), so the `,entry=pending`
    # token has to sit before it. Asserted as "each of the three writers carries BOTH stamps",
    # which is the property that matters, rather than as one literal substring.
    writers = _open_formats() + re.findall(r'"(LOPEN,%[^"]*)"', code())
    assert len(writers) == 3, f"the three fill writers must all be counted: {writers}"
    for i, fmt in enumerate(writers):
        text = code()
        lit = text.index(f'"{fmt}"')
        k = text.rindex("(", 0, lit)      # the StringFormat call's OWN parenthesis
        depth = 0
        while k < len(text):
            if text[k] == "(":
                depth += 1
            elif text[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        args = text[lit:k]
        assert "StateAppend()" in args, f"writer {i + 1} lost the state stamp: {args}"
        assert "RiskAppend(" in args, f"writer {i + 1} lost the configured-risk stamp: {args}"
    assert code().count("EntryPendingAppend()") == 2, (
        "the unresolved-price token is written by the LOPEN row and read back by the healer")
    b = body("StateAppend")
    assert "InpRecordStateLabel" in b, "off unless the input says otherwise"
    assert "MQL_TESTER" in b, "a tester ledger is a parity artifact: no stamp, by construction"
    assert "g_sig_bar_epoch" in b, "the stamp describes the SIGNAL bar, not the fill bar"


def test_the_configured_risk_is_recorded_beside_the_risk_actually_taken() -> None:
    """The v1.22 contract, pinned where it can actually break.

    A fill row's `risk` field is what the venue's lot step ALLOWED; the `cfg` token is what
    InpRiskPercent ASKED FOR. On this arm they differ on every single fill ($62.50 configured,
    $31.84 taken), and a row carrying only the second number cannot be told from a correctly
    sized one — which is the whole reason the token exists. So: the token is keyed (a reader
    finds it without counting fields, because the state stamp is 0 or 5 of them), it is appended
    LAST, it rides every fill path, and no tester row carries it.
    """
    r = body("RiskAppend")
    assert "MQL_TESTER" in r, "a parity ledger is a reproduction artifact: no stamp, by construction"
    assert "InpRiskPercent" in r, "the configured PERCENT rides with the configured dollars"
    assert re.search(r'"[^"]*cfg=%\.2f@%\.2f"', r), (
        "the one grammar: cfg=<usd>@<pct>, unparseable-by-accident is not an option")
    assert "InpRecordStateLabel" not in r, (
        "the configured risk is not a research option — it is what the arm was told to risk")
    # the reader takes it off the END, so it never has to know whether the state stamp is on
    assert ffa.RISK_PREFIX == "cfg="
    assert ffa.read_risk_tail(["OPEN", "1", "cfg=62.50@0.25"]).get("cfg_risk_usd") == 62.50
    assert ffa.read_risk_tail(["OPEN", "1", "LV"]) == {}
    # a token that cannot be read is REPORTED, never silently dropped
    assert "malformed" in ffa.read_risk_tail(["OPEN", "1", "cfg=nonsense"])


def test_the_source_keeps_the_calendar_the_stamp_reads_alive() -> None:
    """A recording-only arm (news gate OFF) must still refresh the source, or it stamps `na`
    forever — and `na` is not evidence of no news."""
    b = body("NewsRefreshIfDue")
    assert "!InpUseNewsFilter && !InpRecordStateLabel" in b.replace("  ", " ")
    assert "STATE LABEL ON" in src(), "INIT must say the stamp is running"
    assert "NOT STAMPED" in src(), "and must say when a run cannot stamp, rather than no-opping"


# ------------------------------------------------------------------ the reader, on real rows

_OPEN_HEAD = ("OPEN,1790000200,7,1,4000.00000,3990.00000,4020.00000,0.10,10.00,10.00000,"
              "720,U25,10.00000,0.20000")
_CLOSE = "CLOSE,1790001000,7,TARGET,4020.00000,2.000,20.00,25020.00,0.20000,0.0,2.0,0,1"


def _ledger(tmp_path: Path, tail: str) -> str:
    p = tmp_path / "ledger.csv"
    p.write_text("ERA,MIDAS1.19,1789996684,note\nEQ,25000.00\n"
                 + _OPEN_HEAD + tail + "\n" + _CLOSE + "\n", encoding="utf-8")
    return str(p)


def test_a_row_written_before_the_stamp_is_not_a_defect(tmp_path) -> None:
    """Absence means 'rebuild the label', not 'the ledger is broken'."""
    led = ffa.read_ledger(_ledger(tmp_path, ""))
    assert led["problems"] == []
    assert led["trades"][0]["state"] == {}


def test_a_full_stamp_reads_back_positionally(tmp_path) -> None:
    led = ffa.read_ledger(_ledger(tmp_path, ",1789999200,8,1.23456,out,120"))
    assert led["problems"] == []
    assert led["trades"][0]["state"] == {"sig_ct": 1789999200, "hour_utc": 8,
                                        "vol_ratio": 1.23456, "news": "out", "off_min": 120}


def test_a_half_written_stamp_is_reported_and_never_guessed(tmp_path) -> None:
    """A partial write is a defect: labelling it would put an invented axis into a statistic."""
    led = ffa.read_ledger(_ledger(tmp_path, ",1789999200,8"))
    assert led["trades"][0]["state"] == {"malformed": "2 state field(s), expected 5"}
    assert any("state stamp" in p for p in led["problems"])


def test_the_sentinels_survive_the_read(tmp_path) -> None:
    led = ffa.read_ledger(_ledger(tmp_path, ",1789999200,-1,0.00000,na,-9999"))
    assert led["trades"][0]["state"]["hour_utc"] == -1
    assert led["trades"][0]["state"]["news"] == "na"


# ---------------------------------------------------------------- the arithmetic in the stamp

_VENUE: dict = {}


def _venue() -> dict:
    """The venue's M15 series plus the engine's own ATR and trailing median, built once."""
    if not _VENUE:
        B, _epoch, n, atr, _hours, _ok = gg.venue_data(gw.SYMBOL, 60000)
        _VENUE.update({"B": B, "n": n, "atr": atr,
                       "atr_med": gw.trailing_percentile(atr, gw.ATR_LOOKBACK, 0.5)})
    return _VENUE


def _mql_ratio(hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, i: int) -> float | None:
    """The EA's `StateVolRatio`, transcribed step for step, at venue bar `i`.

    Same window, same seed (`mean(tr[1..period])`), same Wilder recursion, same median
    (the two middle order statistics of the 500-value window), and the same 200-bar warm-up
    before the window — the warm-up exists so the recursion's seed is decayed to <5e-7 by the
    time the window starts, which is exactly what this test measures rather than assumes.
    """
    lookback, warmup, period = int(defines()["STATE_VOL_LOOKBACK"]), \
        int(defines()["STATE_VOL_WARMUP"]), int(defines()["STATE_ATR_PERIOD"])
    need = lookback + warmup + period + 1
    lo_i = i - need + 1
    if lo_i < 0:
        return None
    h, l, c = hi[lo_i:i + 1], lo[lo_i:i + 1], cl[lo_i:i + 1]
    tr = np.empty(need)
    tr[0] = h[0] - l[0]
    for j in range(1, need):
        tr[j] = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
    atr = np.zeros(need)
    atr[period] = tr[1:period + 1].mean()
    for j in range(period + 1, need):
        atr[j] = (atr[j - 1] * (period - 1) + tr[j]) / period
    win = np.sort(atr[need - lookback:])
    med = (win[lookback // 2 - 1] + win[lookback // 2]) / 2.0
    return float(atr[-1] / med)


@pytest.mark.skipif(not M15.is_file(), reason=NO_DATA)
def test_the_stamp_s_ratio_is_the_engine_s_ratio_and_bins_the_same_way() -> None:
    """The measurement that licenses PREFERRING the stamp: the two agree at the bin edges.

    Sampled across the whole venue window, so a seasonal or regime-specific divergence cannot
    hide behind one lucky index. The bin is what matters — a ratio a hair either side of 0.8 or
    1.3 is a different CELL — so both the value and the label are asserted.
    """
    v = _venue()
    B, atr, atr_med, n = v["B"], v["atr"], v["atr_med"], v["n"]
    idx = [i for i in range(3000, n - 1, 397) if not np.isnan(atr_med[i])]
    assert len(idx) > 20, f"not enough venue bars sampled ({len(idx)}) to claim anything"
    worst = 0.0
    for i in idx:
        mine = _mql_ratio(B["high"], B["low"], B["close"], i)
        assert mine is not None
        engine = float(atr[i]) / float(atr_med[i])
        worst = max(worst, abs(mine - engine) / engine)
        assert gps.label_of_values(mine, 8, False) == gps.label_of_values(engine, 8, False), (
            f"bar {i}: the stamp's ratio {mine:.6f} and the engine's {engine:.6f} land in "
            f"different volatility bins")
    assert worst < 1e-4, f"the warm-up bound is not holding: worst relative deviation {worst:.2e}"


@pytest.mark.skipif(not M15.is_file(), reason=NO_DATA)
def test_the_warm_up_is_what_buys_that_agreement() -> None:
    """Both directions: without the warm-up the same transcription does NOT match, so the
    constant is load-bearing rather than decoration."""
    v = _venue()
    B, atr, atr_med, n = v["B"], v["atr"], v["atr_med"], v["n"]
    lookback, period = int(defines()["STATE_VOL_LOOKBACK"]), int(defines()["STATE_ATR_PERIOD"])
    need = lookback + period + 1                      # no warm-up: seed right at the window
    i = n - 1
    h, l, c = (B["high"][i - need + 1:i + 1], B["low"][i - need + 1:i + 1],
               B["close"][i - need + 1:i + 1])
    tr = np.empty(need)
    tr[0] = h[0] - l[0]
    for j in range(1, need):
        tr[j] = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
    atr_x = np.zeros(need)
    atr_x[period] = tr[1:period + 1].mean()
    for j in range(period + 1, need):
        atr_x[j] = (atr_x[j - 1] * (period - 1) + tr[j]) / period
    win = np.sort(atr_x[need - lookback:])
    unwarmed = atr_x[-1] / ((win[lookback // 2 - 1] + win[lookback // 2]) / 2.0)
    warm_result = _mql_ratio(B["high"], B["low"], B["close"], i)
    engine = float(atr[i]) / float(atr_med[i])
    d_warm = abs(warm_result - engine) / engine
    d_cold = abs(unwarmed - engine) / engine
    assert warm_result is not None
    assert d_cold > d_warm, (
        f"the warm-up is not doing anything: cold {d_cold:.2e} vs warm {d_warm:.2e}")


# --------------------------------------------------- the harness prefers the stamp, and says so
#: ONE instant, in both frames the two paths use. `SIG_UTC` is the signal bar's UTC epoch (08:00);
#: `SIG_SRV` is the SAME instant in the ledger's broker-SERVER frame, which is what the EA stamps
#: (`sig_ct`) and what a ledger's `open_ct` is written in. Getting the frames confused here would
#: reproduce the exact off-by-one-offset defect this whole stamp exists to make visible.
OFF_MIN = 120
SIG_UTC = 1_789_948_800 + 8 * 3600          # the venue window, 08:00 UTC
SIG_SRV = SIG_UTC + OFF_MIN * 60
HOUR_UTC = 8


def _stamped(sig_srv: int, off_min: int, ratio: float, news: str, net_r: float = 1.0) -> dict:
    """A ledger trade as `read_ledger` shapes it, WITH the EA's own state stamp."""
    utc = sig_srv - off_min * 60
    return {"open_ct": sig_srv + fw.FILL_LAG, "net_r": net_r,
            "close_ct": sig_srv + 4 * 3600, "pnl": net_r * 100.0, "ticket": "1",
            "state": {"sig_ct": sig_srv, "hour_utc": (utc % 86400) // 3600,
                      "vol_ratio": ratio, "news": news, "off_min": off_min}}


def _axes(sig_utc: int, ratio: float, news_in: bool, hour: int = HOUR_UTC) -> dict:
    """The venue's own answer for that bar: `ratio` picks the volatility bin."""
    return {"index": {sig_utc: 0}, "atr": np.array([ratio]), "atr_med": np.array([1.0]),
            "hours": np.array([hour]), "ok": {}, "news_mask": np.array([news_in]),
            "news_note": "synthetic", "last_epoch": sig_utc}


def test_the_stamp_wins_and_the_rebuild_is_kept_as_the_control(monkeypatch) -> None:
    """The recorded label is the source of record; the rebuilt one is still computed."""
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: OFF_MIN)
    # the stamp says HIGH volatility; the venue series says normal. The stamp decides...
    labelled, meta = fw.label_rows([_stamped(SIG_SRV, OFF_MIN, 2.0, "out")],
                                   _axes(SIG_UTC, 1.0, False))
    assert [r["cell"] for r in labelled] == ["vol=high|sess=06-12|news=out"]
    assert labelled[0]["label_source"] == "recorded"
    assert meta["label_source"] == {"recorded": 1, "rebuilt": 0}
    assert labelled[0]["sig_open_utc"] == SIG_UTC, "the stamped instant, in the UTC frame"
    # ...AND the disagreement is reported, with both readings, rather than absorbed
    assert meta["reconciliation"]["disagree"] == 1
    s = meta["reconciliation_samples"][0]
    assert (s["ratio_recorded"], s["ratio_rebuilt"]) == (2.0, 1.0)
    assert s["recorded"] != s["rebuilt"]


def test_the_stamp_and_the_rebuild_agreeing_is_the_normal_case(monkeypatch) -> None:
    """Not every row must disagree: the stamp on a row the series also reaches is a control."""
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: OFF_MIN)
    labelled, meta = fw.label_rows([_stamped(SIG_SRV, OFF_MIN, 1.0, "out")],
                                   _axes(SIG_UTC, 1.0, False))
    assert labelled[0]["label_source"] == "recorded"
    assert meta["reconciliation"] == {"agree": 1, "disagree": 0, "recorded_only": 0,
                                      "rebuilt_only": 0}
    assert meta["reconciliation_samples"] == []


def test_an_unstamped_row_falls_back_to_the_rebuild_and_is_counted(monkeypatch) -> None:
    """A row from before the stamp must still be labelable — that is what the rebuild is for."""
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: OFF_MIN)
    plain = _stamped(SIG_SRV, OFF_MIN, 2.0, "out")
    plain.pop("state")
    labelled, meta = fw.label_rows([plain], _axes(SIG_UTC, 1.0, False))
    assert [r["cell"] for r in labelled] == ["vol=normal|sess=06-12|news=out"]
    assert labelled[0]["label_source"] == "rebuilt"
    assert meta["label_source"] == {"recorded": 0, "rebuilt": 1}
    assert meta["reconciliation"]["rebuilt_only"] == 1
    assert meta["stamp_unusable"], "why the stamp was unusable is recorded, not swallowed"


def test_an_unusable_stamp_falls_back_and_is_never_read_as_out_of_cell(monkeypatch) -> None:
    """`news=na` is a gap. It must not become `news=out` (which would put the row IN the cell)."""
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: OFF_MIN)
    na = _stamped(SIG_SRV, OFF_MIN, 1.0, "na")
    labelled, meta = fw.label_rows([na], _axes(SIG_UTC, 1.0, False))
    assert [r["cell"] for r in labelled] == ["vol=normal|sess=06-12|news=out"]
    assert labelled[0]["label_source"] == "rebuilt"
    assert any("news" in k for k in meta["stamp_unusable"])


def test_an_unknown_offset_in_the_stamp_is_refused_not_defaulted(monkeypatch) -> None:
    """No offset, no UTC hour: the row falls back rather than being labelled in the wrong frame."""
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: OFF_MIN)
    blind = _stamped(SIG_SRV, OFF_MIN, 1.0, "out")
    blind["state"].update({"hour_utc": -1, "off_min": -9999})
    labelled, meta = fw.label_rows([blind], _axes(SIG_UTC, 1.0, False))
    assert [r["cell"] for r in labelled] == ["vol=normal|sess=06-12|news=out"]
    assert any("hour_utc" in k for k in meta["stamp_unusable"])


def test_when_neither_source_can_place_the_row_it_is_excluded(monkeypatch) -> None:
    """Beyond the data of record AND unstamped: a gap, counted, with both reasons named."""
    monkeypatch.setattr(fw.S, "server_offset_for_month", lambda month: OFF_MIN)
    far = {"open_ct": SIG_SRV + 86_400, "net_r": 1.0, "close_ct": SIG_SRV + 90_000,
           "pnl": 100.0, "ticket": "1"}
    labelled, meta = fw.label_rows([far], _axes(SIG_UTC, 1.0, False))
    assert labelled == []
    reason = next(iter(meta["excluded"]))
    assert "data of record" in reason and "midas_fetch_history" in reason
    assert "stamp" in reason
