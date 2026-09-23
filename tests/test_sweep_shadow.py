"""The Asian-range sweep: one definition, non-repainting, and a rule the recorder cannot move.

WHY THIS FILE EXISTS. `docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md` records the strongest
measured number in this program on a window the study itself declined to call a test (UTC
07-18: 152 held-out trades, +0.1955R, pf 1.499, t +2.21), and prescribes a forward shadow
recorder as the only blind evidence left. Three things can make that recorder worthless, and
each has a test here:

  * the mechanism being re-implemented on the recording side, so the record describes a
    different rule than the one that was measured — hence the one-definition test and the
    reproduction of the published number;
  * the signal repainting, i.e. a row's value moving when a LATER bar moves — the defect
    class this repository already found once, in the cross-asset study's context leg;
  * the frame being read wrong, which shifts every bar out of its own window — the
    two-hour lie this program has paid for.

The mechanism moved out of `scripts/midas_asia_sweep.py` into `scripts/midas_sweep.py` on
2026-09-22 so there could be exactly one definition; the reproduction test is how that move
is kept honest rather than asserted.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import midas_sweep as M  # noqa: E402
import midas_sweep_shadow as ss  # noqa: E402

DAY = 86400
#: 2026-09-22 00:00 UTC, a Tuesday well inside the venue's history. The synthetic series
#: below only has to be internally consistent, but the stamp is stated so a reader checking
#: the window arithmetic by hand is not sent to the wrong day by a comment.
DAY0 = 1790035200


def bar(t: int, o: float, h: float, lo: float, c: float) -> dict:
    return {"time": t, "open": o, "high": h, "low": lo, "close": c}


def flat_day(day0: int, last_hour: int = 19, px: float = 100.0) -> list[dict]:
    """A day of M15 bars from 00:00 to `last_hour`, flat, with a tight 1.0 wide range."""
    return [bar(day0 + k * 900, px, px + 0.5, px - 0.5, px)
            for k in range(last_hour * 4)]


def at_day_hour(bars: list[dict], day0: int, hour: int) -> dict:
    want = day0 + hour * 3600
    return next(b for b in bars if b["time"] == want)


# --- 1. one definition, and it is the one that was measured ---------------------------

def test_the_mechanism_has_exactly_one_definition():
    """`midas_asia_sweep` must IMPORT the mechanism, not carry its own copy.

    Two implementations is how a program certifies one rule and records another, which is
    the specific way this recorder would become worthless. Identity, not equality: a copy
    that happens to agree today would drift on the next edit.
    """
    import midas_asia_sweep as A
    assert A.build_signals is M.sweep_signals
    assert A.asian_ranges is M.asian_ranges
    assert A.VARIANTS is M.SWEEP_VARIANTS
    assert A.SECONDARY == M.SWEEP_WINDOW == (7, 18)


def test_the_published_secondary_window_number_reproduces():
    """The load-bearing check: this mechanism is the one the study measured.

    `artifacts/midas_asia_sweep_20260922.json` is a published artifact and may not be
    quietly re-derived. If the refactor changed the mechanism at all, this fails — and the
    resolver's own `self_check()` refuses the same way, so a run that printed numbers while
    this was broken is not possible.
    """
    import midas_parity as P
    from midas_decision_attribution import t_stat

    oos = P._window_spec("oos")
    data = P.python_build_data(offset_min=P.assert_server_offset(oos), corpus="venue")
    sig = M.sweep_signals(data["m15"])["SWEEP_CONT"]
    prev = M._BASIS
    M.use_basis(P.ACCOUNT_BASIS_USD)
    try:
        rr = M.run_mode("TRIGGER_ONLY", oos["t0"], oos["t1"], {**data, "m15_bb": sig},
                        win_lo=7, win_hi=18)
    finally:
        M._BASIS = prev
    rs = [t["r"] for t in rr.trades]
    assert len(rs) == 152, len(rs)
    assert abs(sum(rs) / len(rs) - 0.1955) < 5e-4
    assert abs(t_stat(rs) - 2.208) < 5e-3


# --- 2. non-repainting, by construction and by behaviour -------------------------------

def test_a_later_bar_can_never_move_an_earlier_signal():
    """Perturb the FUTURE and the past must not notice.

    This is the pin the cross-asset study earned the hard way: its context leg read bar
    OPEN times while its signal leg read closes, which gave the context series one bar of
    lookahead. The signal is read here on the same bar's own closed high/low/close, so a
    later bar is invisible to it by construction — and this test is what says so.
    """
    d1 = flat_day(DAY0)
    d2 = flat_day(DAY0 + DAY)
    at_day_hour(d1, DAY0, 7)["high"] = 101.0            # day 1 sweeps up
    at_day_hour(d2, DAY0 + DAY, 7)["high"] = 101.0      # day 2 sweeps up
    base = M.sweep_signals(d1 + d2)["SWEEP_CONT"]
    day1_before = [v for b, v in zip(d1 + d2, base) if b["time"] < DAY0 + DAY]

    for b in d2:                                        # move every day-2 bar a lot
        b["high"] += 50.0
        b["low"] -= 50.0
        b["close"] += 25.0
    after = M.sweep_signals(d1 + d2)["SWEEP_CONT"]
    day1_after = [v for b, v in zip(d1 + d2, after) if b["time"] < DAY0 + DAY]

    assert day1_before == day1_after, "a later bar moved an earlier signal"


def test_one_signal_per_utc_day_per_side():
    """The first sweep of the day on a side is the signal; later ones repeat nothing."""
    d = flat_day(DAY0)
    at_day_hour(d, DAY0, 7)["high"] = 101.0
    at_day_hour(d, DAY0, 8)["high"] = 102.0
    sig = M.sweep_signals(d)["SWEEP_CONT"]
    assert sig[d.index(at_day_hour(d, DAY0, 7))] == 1
    assert sig[d.index(at_day_hour(d, DAY0, 8))] == 0, "only the FIRST sweep of a side fires"
    # ...and the two sides are independent: a down-sweep later the same day still fires.
    at_day_hour(d, DAY0, 10)["low"] = 99.0
    sig = M.sweep_signals(d)["SWEEP_CONT"]
    assert sig[d.index(at_day_hour(d, DAY0, 10))] == -1


def test_the_range_closes_at_0645_and_not_at_0700():
    """00:00-06:45 builds the range; the 07:00 bar may sweep it but is not part of it."""
    d = flat_day(DAY0)
    at_day_hour(d, DAY0, 6)["high"] = 105.0             # 06:00 is the last whole range hour
    b_0645 = next(b for b in d if b["time"] == DAY0 + 6 * 3600 + 2700)
    b_0645["high"] = 106.0                              # 06:45 still counts
    at_day_hour(d, DAY0, 7)["high"] = 200.0             # 07:00 must NOT
    rng = M.asian_ranges(d)
    assert rng[str(_iso(DAY0))] == (106.0, 99.5), rng


def _iso(day0: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(day0, tz=timezone.utc).date().isoformat()


def test_no_signal_can_exist_before_the_range_is_known():
    """Hours 00:00-06:45 are the range itself; nothing there is a sweep."""
    d = flat_day(DAY0)
    for b in d:
        b["high"] = 300.0                               # everything trades beyond everything
        b["low"] = -300.0
    sig = M.sweep_signals(d)["SWEEP_CONT"]
    from datetime import datetime, timezone
    for b, v in zip(d, sig):
        if datetime.fromtimestamp(b["time"], tz=timezone.utc).hour < 7:
            assert v == 0, f"a signal before 07:00 UTC: {b['time']}"


def test_engine_signals_past_the_window_are_ignored_by_the_resolver():
    """The engine marks a sweep at ANY hour >= 07:00; only 07-18 is the recorder's claim.

    This is a real asymmetry and it is deliberately harmless: a sweep at hour >= 18 is the
    last window-hour bar of its day, so it can never change the answer for an in-window bar.
    The resolver filters the comparison to its declared window and never reports the rest,
    so the two sides cannot disagree about a bar the EA would never write.
    """
    d = flat_day(DAY0, last_hour=23)
    at_day_hour(d, DAY0, 20)["high"] = 101.0            # an evening sweep, outside the window
    sig = M.sweep_signals(d)["SWEEP_CONT"]
    idx = d.index(at_day_hour(d, DAY0, 20))
    assert sig[idx] == 1, "the engine does mark it..."
    # ...and this is why that is fine: no in-window bar can follow it, so no EA row exists
    # for a bar whose answer the extra signal could change.
    from datetime import datetime, timezone
    after = [b for b, v in zip(d, sig)
             if b["time"] > d[idx]["time"]
             and 7 <= datetime.fromtimestamp(b["time"], tz=timezone.utc).hour < 18]
    assert after == []


def test_a_reclaim_is_flagged_and_is_not_a_signal():
    """`RECLAIM_REV` is the textbook read and it is derivable, never stored as a direction."""
    d = flat_day(DAY0)
    b = at_day_hour(d, DAY0, 7)
    b["high"] = 101.0
    b["close"] = 100.0                                  # traded beyond, closed back inside
    sig = M.sweep_signals(d)
    i = d.index(b)
    assert sig["RECLAIM_REV"][i] == -1
    assert sig["SWEEP_FADE"][i] == -1, "the mirror of SWEEP_CONT's +1"
    assert sig["SWEEP_CONT"][i] == 1, "the break is still a continuation signal"


# --- 3. the ledger side: the row, the frame, the vocabulary ---------------------------

def _row_ledger(tmp: Path, *, sig_open: int, off_min: int, side: int) -> Path:
    p = tmp / "ledger.csv"
    p.write_text(
        f"SWEEPSHADOW,{sig_open},{sig_open},20718,105.00000,99.50000,28,{side},"
        f"{1 if side else 0},0,41.31000,{off_min},MIDAS1.28\n",
        encoding="utf-8")
    return p


def test_the_resolver_parses_the_row_the_ea_writes(tmp_path):
    p = _row_ledger(tmp_path, sig_open=DAY0 + 7 * 3600 + 7200, off_min=120, side=1)
    rows, broken = ss.read_rows(p)
    assert not broken and len(rows) == 1
    r = rows[0]
    assert r["side"] == 1 and r["range_bars"] == 28 and r["off_min"] == 120
    assert r["version"] == "MIDAS1.28"
    assert r["asian_hi"] == 105.0 and r["asian_lo"] == 99.5


def test_a_short_row_is_reported_and_never_read_generously(tmp_path):
    """A row that states no direction is not a statement about a setup."""
    p = tmp_path / "ledger.csv"
    p.write_text("SWEEPSHADOW,1,2,20718,105.0,99.5,28,1\n", encoding="utf-8")
    rows, broken = ss.read_rows(p)
    assert rows == [] and broken and "fields" in broken[0]


def test_the_window_is_read_in_utc_from_the_rows_own_offset():
    """A server-stamped epoch read as UTC puts every bar two hours out of its window.

    MEASURED 2026-09-23 07:15Z, the first live row: the EA stamps SERVER-wall bar opens and
    the series (corpus via `venue_bars_utc`, terminal via `live_bars`) is keyed on true UTC,
    so the lookup must convert with the row's own `off_min`. The first cut converted the
    hour check but keyed the lookup on the raw stamp — every live row read `unmatched`
    forever and no EA-vs-engine agreement could ever be computed. Same row, same UTC-keyed
    array, two offsets: at +120 the stamp converts to the 17:00Z bar and belongs to the
    shadow; read as if the offset were 0 it converts to 19:00Z, which is not a bar in the
    series at all — the two-hour lie manifesting as `unmatched`, not as a wrong window.
    """
    server_open = DAY0 + 17 * 3600 + 7200            # the EA stamps the server-wall bar open
    m15 = [bar(server_open - 7200, 100.0, 101.0, 99.0, 100.0)]   # the series is UTC-keyed
    sig = [1]
    t0 = DAY0

    def check(off: int) -> dict:
        row = {"sig_open": server_open, "side": 1, "off_min": off}
        return ss.check_rows_against_engine([row], m15, sig, t0)

    good = check(120)
    assert good["rows_in_window"] == 1 and good["n_disagreements"] == 0, good
    bad = check(0)
    assert bad["n_unmatched"] == 1, \
        "at offset 0 the stamp converts to 19:00Z — a bar the series does not hold"


def test_a_disagreeing_row_voids_the_run():
    """The EA's rows and the independently rebuilt array must agree, or nothing is reported."""
    utc_open = DAY0 + 10 * 3600
    m15 = [bar(utc_open, 100.0, 101.0, 99.0, 100.0)]                    # the series is UTC-keyed
    row = {"sig_open": utc_open + 7200, "side": -1, "off_min": 120}     # EA says SHORT
    checks = ss.check_rows_against_engine([row], m15, [1], DAY0)        # engine says LONG
    assert checks["n_disagreements"] == 1
    word, why = ss.verdict(_res(n=200), checks)
    assert word == "VOID" and "disagree" in why[0]


def _res(n: int, *, t: float = 3.0, per_day: float = 0.9, mean: float = 0.2,
         fade: float = -0.2, reclaim: float = -0.15) -> dict:
    return {ss.VARIANT: {"n": n, "t": t, "per_day": per_day, "mean_r": mean},
            "SWEEP_FADE": {"mean_r": fade},
            "RECLAIM_REV": {"mean_r": reclaim}}


def test_the_verdict_vocabulary_is_four_words():
    ok = {"n_disagreements": 0}
    assert ss.verdict(_res(n=0), ok)[0] == "ACCUMULATING"
    assert ss.verdict(_res(n=59), ok)[0] == "ACCUMULATING"
    assert ss.verdict(_res(n=60), ok)[0] == "PASS"
    # FAIL names which test failed, and never says PASS at the threshold's edge
    assert ss.verdict(_res(n=60, t=2.3), ok)[0] == "FAIL"
    assert ss.verdict(_res(n=60, per_day=0.29), ok)[0] == "FAIL"
    assert ss.verdict(_res(n=60, mean=-0.01), ok)[0] == "FAIL"
    # VOID is a different word for a different thing: the RECORDER is broken, not the rule
    word, why = ss.verdict(_res(n=200, fade=+0.05), ok)
    assert word == "VOID" and "SWEEP_FADE" in why[0]


def test_the_rule_constants_match_the_pre_registration():
    doc = (REPO / "docs" / "ASIA_SWEEP_FORWARD_PREREG_20260922.md").read_text(encoding="utf-8")
    for phrase in ("N ≥ 60", "t ≥ 2.4", "0.30", "ACCUMULATING", "VOID", "PASS", "FAIL"):
        assert phrase in doc, f"the pre-registration must state `{phrase}`"
    assert ss.N_TARGET == 60 and ss.T_BAR == 2.4 and abs(ss.MIN_PER_DAY - 0.30) < 1e-9
    assert ss.VARIANT == "SWEEP_CONT"
    assert set(ss.DIRECTION_CHECKS) == {"SWEEP_FADE", "RECLAIM_REV"}


def test_the_resolver_is_residue_and_cannot_reach_an_order():
    """It is a research harness: outside the live closure, and by construction order-free."""
    text = (REPO / "scripts" / "midas_sweep_shadow.py").read_text(encoding="utf-8")
    for forbidden in ("OrderSend", "mt5.order_send", "positions_get", "order_send"):
        assert forbidden not in text, f"the resolver must not touch `{forbidden}`"
    import audit_program_surface as aps
    live = aps.closure(aps.LIVE_ENTRY_POINTS)
    assert "midas_sweep_shadow" not in live, "the resolver must stay outside the live closure"
