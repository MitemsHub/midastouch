"""First-fills audit tests: synthetic ledgers with planted violations.

The audit is pre-registered acceptance — these tests pin its rules so the
auditor itself can never drift (a silent auditor is worse than none).
"""
import calendar
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import midas_first_fills_audit as A          # noqa: E402

ERA = "ERA,MIDAS1.09,1789635451,pertick-fills"


def _h1_fixture():
    """5 H1 bars, TR = 5.0 each -> bounded SMA-ATR = 5.0, 2xATR = 10.0.
    Bars open 09:00..13:00 UTC 2026-09-16, so closes are 10:00..14:00."""
    base = calendar.timegm((2026, 9, 16, 9, 0, 0, 0, 0, 0))
    bars, px = [], 2500.0
    for i in range(5):
        t = base + i * 3600
        bars.append({"time": t, "open": px, "high": px + 5.0,
                     "low": px, "close": px + 5.0, "spread": 0.12})
        px += 5.0
    return bars


def _make_data_dir(tmp_path, bars):
    dd = tmp_path / "data"
    dd.mkdir(exist_ok=True)
    with open(dd / "XAUUSD_H1.csv", "w") as fh:
        fh.write("time,open,high,low,close,spread\n")
        for b in bars:
            fh.write(f"{b['time']},{b['open']},{b['high']},{b['low']},"
                     f"{b['close']},{b['spread']}\n")
    return str(dd)


def _write_ledger(tmp_path, rows):
    p = tmp_path / "MIDASTOUCH_paper_XAUUSDmicro_M1.csv"
    p.write_text("\r\n".join(rows) + "\r\n", encoding="ascii")
    return str(p)


def _run_capture(led, dd, session=(12, 16)):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = A.run(led, session, 2.0, dd, False)
    return rc, buf.getvalue()


def _rows(open_ct, side=1, reason="TP", exit_r=2.0, stop_d=10.0,
          entry=2500.0, pnl=2.0, veq=52.0, r=None):
    """One well-formed trade; fields mutated per test."""
    rec_r = exit_r if r is None else r
    sl = entry - side * stop_d
    tp = entry + side * 2 * stop_d
    o = (f"OPEN,{open_ct},{open_ct},{side},{entry:.5f},{sl:.5f},{tp:.5f},"
         f"0.10,{stop_d:.5f},{stop_d:.5f},720,M1")
    exit_px = entry + side * exit_r * stop_d
    c = (f"CLOSE,{open_ct + 2700},{open_ct},{reason},{exit_px:.5f},"
         f"{rec_r:.4f},{pnl:.2f},{veq:.2f}")
    return [o, c]


def test_clean_ledger_passes(tmp_path):
    # signal M15 bar opens 12:30 UTC Wed 2026-09-16 -> open_ct 12:45;
    # k1 = last H1 closing <= 12:45 = the 11:00-open bar (closes 12:00)
    # -> ATR 5.0 -> 2xATR = 10.0, matching the row
    open_ct = calendar.timegm((2026, 9, 16, 12, 45, 0, 0, 0, 0))
    led = _write_ledger(tmp_path, [ERA, *_rows(open_ct), "EQ,52.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 0, txt
    assert "VIOLATION" not in txt
    assert "research 10.0000" in txt          # stop geometry actually verified


def test_session_violation(tmp_path):
    # signal bar opens 10:30 UTC — outside the 12-16 window
    open_ct = calendar.timegm((2026, 9, 16, 10, 45, 0, 0, 0, 0))
    led = _write_ledger(tmp_path, [ERA, *_rows(open_ct), "EQ,52.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 1
    assert "SESSION" in txt


def test_friday_cutoff_violation(tmp_path):
    # 2026-09-18 is a Friday; signal bar opens 21:30 UTC >= 20:00 cutoff
    open_ct = calendar.timegm((2026, 9, 18, 21, 45, 0, 0, 0, 0))
    led = _write_ledger(tmp_path, [ERA, *_rows(open_ct), "EQ,52.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 1
    assert "FRIDAY CUTOFF" in txt


def test_stop_geometry_violation(tmp_path):
    open_ct = calendar.timegm((2026, 9, 16, 12, 45, 0, 0, 0, 0))
    led = _write_ledger(tmp_path,
                        [ERA, *_rows(open_ct, stop_d=12.0), "EQ,52.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 1
    assert "STOP GEOMETRY" in txt


def test_stop_unverifiable_beyond_data(tmp_path):
    # trade Fri 09-18 12:45 UTC — data of record's last H1 closed Wed 14:00
    # (46.75h stale > 24h) -> disclosed UNVERIFIABLE, not a violation
    open_ct = calendar.timegm((2026, 9, 18, 12, 45, 0, 0, 0, 0))
    led = _write_ledger(tmp_path, [ERA, *_rows(open_ct), "EQ,52.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 0
    assert "UNVERIFIABLE" in txt


def test_r_math_violation(tmp_path):
    open_ct = calendar.timegm((2026, 9, 16, 12, 45, 0, 0, 0, 0))
    # exit implies +2.0R but the row records +1.5R
    led = _write_ledger(tmp_path,
                        [ERA, *_rows(open_ct, exit_r=2.0, r=1.5), "EQ,52.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 1
    assert "R MATH" in txt


def test_reason_sanity_sl(tmp_path):
    open_ct = calendar.timegm((2026, 9, 16, 12, 45, 0, 0, 0, 0))
    led = _write_ledger(tmp_path,
                        [ERA, *_rows(open_ct, reason="SL", exit_r=0.5,
                                     pnl=0.5, veq=50.5), "EQ,50.50"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 1
    assert "REASON: SL" in txt


def test_veq_continuity_violation(tmp_path):
    open_ct = calendar.timegm((2026, 9, 16, 12, 45, 0, 0, 0, 0))
    led = _write_ledger(tmp_path,
                        [ERA, *_rows(open_ct, pnl=2.0, veq=99.0), "EQ,99.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 1
    assert "VEQ" in txt


def test_format_and_contamination(tmp_path):
    c = "CLOSE,1789636000,1789635400,TIMEOUT,2500.00000,-0.5000,-0.50,49.50"
    lopen = ("LOPEN,1789636100,123,1,2500.0,2490.0,2520.0,0.10,"
             "10.0,10.0,720,M1")
    led = _write_ledger(tmp_path, [ERA, c, "EQ,49.50", lopen])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 1
    assert "contamination" in txt


def test_empty_ledger_arms_the_rules(tmp_path):
    led = _write_ledger(tmp_path, [ERA, "EQ,50.00"])
    rc, txt = _run_capture(led, _make_data_dir(tmp_path, _h1_fixture()))
    assert rc == 0
    assert "nothing to audit" in txt
