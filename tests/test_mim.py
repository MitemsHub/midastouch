"""The MIM study: mechanism, no-lookahead, and a verdict that cannot drift from its pre-reg.

WHY THIS FILE EXISTS. `docs/MIM_PREREG_20260922.md` was written before any measurement and
fixes the mechanism, the spans, and the verdict rule. `docs/MIM_VERDICT_20260922.md` records
the measured FAIL (t=0.17 on 182 held-out trades). Three things would make that record
worthless, and each has a pin here:
  * a lookahead read of `thr` — the still-open 10:00Z H1 bar closes at 11:00Z, one tick
    after the decision; if it is ever read, the huge-bar test below fails,
  * the signal arrays trading on days that lack an anchor bar (a guessed fill),
  * and the verdict in the artifact drifting from what its own numbers pass or fail.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts"))

import midas_mim as MM          # noqa: E402

UTC = timezone.utc


def _bar(t: datetime, o: float, h: float, l: float, c: float) -> dict:
    return {"time": int(t.timestamp()), "open": o, "high": h, "low": l, "close": c,
            "spread": 20.0}


def _synth_day(day0: datetime, open_px: float = 4300.0, r1_move: float = 12.0) -> list[dict]:
    """One UTC day of m15 bars (04:00..12:45) whose 10:45 close carries `r1_move`."""
    bars: list[dict] = []
    for k in range(20):                      # 04:00 .. 08:45, flat at open_px
        t = day0 + timedelta(minutes=15 * (16 + k))
        bars.append(_bar(t, open_px, open_px + 1, open_px - 1, open_px))
    for k in range(8):                       # 09:00 .. 10:45, drifting to open_px + r1_move
        t = day0 + timedelta(minutes=15 * (36 + k))
        px = open_px + r1_move * (k + 1) / 8
        bars.append(_bar(t, px - r1_move / 8, px + 0.5, px - 1.5, px))
    for k in range(8):                       # 11:00 .. 12:45, flat after the decision
        t = day0 + timedelta(minutes=15 * (44 + k))
        px = open_px + r1_move
        bars.append(_bar(t, px, px + 1, px - 1, px))
    return bars


@pytest.fixture()
def series():
    d0 = datetime(2026, 9, 1, tzinfo=UTC)
    m15: list[dict] = []
    h1: list[dict] = []
    for d in range(5):
        base = d0 + timedelta(days=d)
        m15 += _synth_day(base, r1_move=12.0 if d % 2 == 0 else -10.0)
        for k in range(24):                  # flat H1: tiny, deterministic ATR
            t = base + timedelta(hours=k)
            h1.append(_bar(t, 4300.0, 4300.6, 4299.4, 4300.0))
    return m15, h1


def test_signals_only_on_the_decision_bar(series):
    """Nonzero entries exist ONLY at 10:45Z bars — one decision per day, by construction."""
    m15, h1 = series
    sig = MM.mim_signals(m15, h1)
    for name, arr in sig.items():
        nz = [i for i, v in enumerate(arr) if v != 0]
        assert nz, f"{name} never fired on a series built to fire"
        for i in nz:
            dt = datetime.fromtimestamp(m15[i]["time"], tz=UTC)
            assert (dt.hour, dt.minute) == (10, 45), f"{name} fired at {dt}"


def test_no_guessed_fills_on_short_days(series):
    """A day missing its 04:00Z anchor bar gets NO signal."""
    m15, h1 = series
    d1 = datetime(2026, 9, 2, tzinfo=UTC)
    m15_no4 = [b for b in m15
               if not (datetime.fromtimestamp(b["time"], tz=UTC).date() == d1.date()
                       and datetime.fromtimestamp(b["time"], tz=UTC).hour == 4)]
    sig = MM.mim_signals(m15_no4, h1)
    day1 = [v for name in ("MOM_0.0", "REV_0.0")
            for i, v in enumerate(sig[name])
            if datetime.fromtimestamp(m15_no4[i]["time"], tz=UTC).date() == d1.date()]
    assert all(v == 0 for v in day1)


def test_thr_reads_the_last_closed_h1_never_the_open_one():
    """The lookahead pin: a huge STILL-OPEN 10:00Z H1 bar must not move the decision.

    The 10:00Z H1 bar closes at 11:00Z — after the 10:45Z decision. Day B below carries
    r1 = +12 while its 10:00Z H1 bar has a 400-point range. The correct (closed-bars)
    read sees a tiny ATR and fires MOM; a lookathread read of the open bar inflates thr
    past 12 and fires nothing. This test fails by construction if the cut is raised.
    """
    d0 = datetime(2026, 9, 1, tzinfo=UTC)
    m15 = _synth_day(d0, r1_move=0.5) + _synth_day(d0 + timedelta(days=1), r1_move=12.0)
    h1: list[dict] = []
    for d in range(2):
        base = d0 + timedelta(days=d)
        for k in range(24):
            h1.append(_bar(base + timedelta(hours=k), 4300.0, 4300.6, 4299.4, 4300.0))
    # day B (d=1): poison the STILL-OPEN bar only — its 10:00Z H1 bar (index 24+10)
    poison = 24 + 10
    t_poison = datetime.fromtimestamp(h1[poison]["time"], tz=UTC)
    h1[poison] = _bar(t_poison, 4300.0, 4500.0, 4100.0, 4300.0)

    sig = MM.mim_signals(m15, h1)
    db = d0 + timedelta(days=1)
    dec = [i for i, b in enumerate(m15)
           if datetime.fromtimestamp(b["time"], tz=UTC).date() == db.date()
           and datetime.fromtimestamp(b["time"], tz=UTC).hour == 10
           and datetime.fromtimestamp(b["time"], tz=UTC).minute == 45]
    assert len(dec) == 1
    i = dec[0]
    b0 = next(b for b in m15
              if datetime.fromtimestamp(b["time"], tz=UTC).date() == db.date()
              and datetime.fromtimestamp(b["time"], tz=UTC).hour == 4
              and datetime.fromtimestamp(b["time"], tz=UTC).minute == 0)
    r1 = m15[i]["close"] - b0["open"]
    assert abs(r1 - 12.0) < 1e-9
    assert sig["MOM_0.5"][i] == 1, "closed-bars ATR should fire here; the open bar must not be read"
    assert sig["REV_0.5"][i] == -1


def test_verdict_gate_arithmetic_matches_the_prereg():
    """The verdict recorded in the artifact is exactly what its own numbers pass or fail."""
    art = Path("artifacts/midas_mim_20260922.json")
    if not art.exists():
        pytest.skip("study not run yet")
    d = json.loads(art.read_text(encoding="utf-8"))
    oos = d["windows"]["oos"]["results"]
    prim = oos["MOM_0.0"]
    failed = []
    if prim["t"] is None or prim["t"] < MM.T_BAR:
        failed.append("t")
    if prim["n"] < MM.MIN_TRADES:
        failed.append("n")
    if prim.get("per_day", 0) < MM.MIN_PER_DAY:
        failed.append("per_day")
    if (prim["expectancy_r"] or 0) <= 0:
        failed.append("mean")
    rev_beats = any((oos[f"REV_{c}"]["expectancy_r"] or 0)
                    > (oos[f"MOM_{c}"]["expectancy_r"] or 0) for c in MM.THRESHOLDS)
    if rev_beats:
        failed.append("REV")
    recorded = d["verdict"]["result"]
    if failed:
        assert recorded.startswith("FAIL"), f"verdict drift: {recorded} vs failures {failed}"
        assert ", ".join(failed) in recorded, f"verdict must name its failed gates: {recorded}"
    else:
        assert recorded.startswith("PASS"), f"verdict drift: {recorded} vs no failures"


def test_verdict_doc_matches_the_artifact():
    """The verdict doc's headline numbers are the artifact's numbers."""
    art = Path("artifacts/midas_mim_20260922.json")
    doc = Path("docs/MIM_VERDICT_20260922.md")
    if not (art.exists() and doc.exists()):
        pytest.skip("artifacts not present")
    d = json.loads(art.read_text(encoding="utf-8"))
    txt = doc.read_text(encoding="utf-8")
    prim = d["windows"]["oos"]["results"]["MOM_0.0"]
    assert "FAIL" in d["verdict"]["result"]
    for token in (str(prim["n"]), f"{prim['expectancy_r']:+.4f}", f"{prim['t']:.2f}"):
        assert token in txt, f"verdict doc missing measured token {token}"
