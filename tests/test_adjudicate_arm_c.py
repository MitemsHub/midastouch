"""Synthetic-ledger tests for scripts/adjudicate_arm_c.py.

The frozen rule must be executable correctly BEFORE any real candidate data
exists (docs/ARM_C_TEMPLATE.md). These tests build synthetic arm-C and arm-A
ledgers + journals covering every gate and every verdict branch.
"""
from __future__ import annotations

import calendar
import json
import time

import pytest

from scripts import adjudicate_arm_c as adj

BASE = calendar.timegm((2026, 10, 1, 10, 0, 0, 0, 0, 0))  # 10:00 UTC daily
FLOOR = 225.54
START_EQ = 250.0
RISK = 4.5


def day_epoch(i: int, hour: int = 10) -> int:
    return BASE + i * 86400 + (hour - 10) * 3600


def c_rows(i: int, r: float, eq: float, pnl: float, idx: int = 0):
    """(OPEN, CLOSE, EQ) rows for one synthetic arm-C trade. The ticket key
    (epoch + idx) stays unique even when several trades share a day."""
    key = day_epoch(i) + idx
    op = f"OPEN,{day_epoch(i)},{key},1,100.00000,98.00000,104.00000,0.01,{RISK:.2f},2.00000,86400,PAPER"
    cl = f"CLOSE,{day_epoch(i, 11)},{key},{'TARGET' if r > 0 else 'STOP'},{'104.00000' if r > 0 else '98.00000'},{r:.3f},{pnl:.2f},{eq:.2f}"
    return op, cl, f"EQ,{eq:.2f}"


def build_c_ledger(path, rs, start_eq=START_EQ, days=None):
    """C ledger with exact veq bookkeeping (equity moves only at closes).
    days: optional per-trade calendar-day offset (default = list index)."""
    eq = start_eq
    opens, closes, eqs = [], [], []
    for i, r in enumerate(rs):
        di = days[i] if days is not None else i
        pnl = r * RISK
        eq += pnl
        op, cl, e = c_rows(di, r, eq, pnl, idx=i)
        opens.append(op)
        closes.append(cl)
        eqs.append(e)
    with open(path, "w") as f:
        f.write("\n".join(opens + closes + eqs) + "\n")
    return eq


def build_a_ledger(path, rs, start_day=0, days=None):
    """Arm-A reference ledger (same format; open epoch in the ticket column)."""
    eq, opens, closes = 300.0, [], []
    for j, r in enumerate(rs):
        i = (days[j] if days is not None else j) + start_day
        key = day_epoch(i) + j          # unique even for several trades per day
        pnl = r * 5.0
        eq += pnl
        opens.append(f"OPEN,{day_epoch(i)},{key},1,100.00000,98.00000,106.00000,0.01,5.00,2.00000,86400,PAPER")
        closes.append(f"CLOSE,{day_epoch(i, 12)},{key},{'TARGET' if r > 0 else 'STOP'},106.00000,{r:.3f},{pnl:.2f},{eq:.2f}")
    with open(path, "w") as f:
        f.write("\n".join(opens + closes) + "\n")


def write_monitor(path, generated=None, floor=FLOOR):
    readings = [{"generated_utc": generated or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                 "verdict": "WATCH",
                 "strangulation_floor": {"floor_certified": floor, "k_certified": 6,
                                         "s_worst_p95": 20.5}}]
    with open(path, "w") as f:
        json.dump(readings, f)


def write_journal(dir_, name, blocks, engine="MitemshubAI", hour=11):
    """blocks: list of (day_index, [line, ...]) — one init banner per entry.
    Timestamps default to 11:00 so banners sit inside the trades' day window."""
    lines = []
    for di, msgs in blocks:
        base = day_epoch(di, hour)
        for k, msg in enumerate(msgs):
            ts = time.strftime("%Y.%m.%d %H:%M:%S", time.gmtime(base + k))
            lines.append(f"0\t0\t{ts}\t{engine} (Volatility 75 Index,M15)\t{msg}")
    path = f"{dir_}/{name}"
    with open(path, "wb") as f:
        f.write("\r\n".join(lines).encode("utf-16-le"))
    return path


def banner(version="v26.37"):
    return [f"[{version}] MicroFit     = 1.5%",
            f"[{version}] Session=00-00",
            f"[{version}] PAPER MODE $250.00",
            f"[{version}] COOLDOWN 2 bars left"]


def run_tool(tmp_path, c_rs, a_rs, monitor="fresh", blocks_c=None, blocks_a=None,
             extra_c_rows=None, c_ledger_text=None, c_days=None, a_days=None):
    c_led = tmp_path / "C.csv"
    a_led = tmp_path / "A.csv"
    if c_ledger_text is not None:
        c_led.write_text(c_ledger_text)
    else:
        build_c_ledger(str(c_led), c_rs, days=c_days)
    build_a_ledger(str(a_led), a_rs, days=a_days)
    mon = tmp_path / "monitor.json"
    if monitor == "fresh":
        write_monitor(str(mon))
    elif monitor == "stale":
        write_monitor(str(mon), generated="2026-09-01T00:00:00")
    elif monitor == "missing":
        mon = tmp_path / "nope.json"
    j1, j2 = tmp_path / "jA", tmp_path / "jB"
    j1.mkdir(exist_ok=True)
    j2.mkdir(exist_ok=True)
    if blocks_c is not None:
        write_journal(str(j1), "fb9a.log", blocks_c, engine="V75MacroEngine")
    if blocks_a is not None:
        write_journal(str(j2), "71bf.log", blocks_a, engine="MitemshubAI")
    out = adj.run(["--c-ledger", str(c_led), "--a-ledger", str(a_led),
                   "--monitor", str(mon), "--out", str(tmp_path / "out.json"),
                   "--journal-dir", str(j1), "--journal-dir", str(j2)])
    saved = json.load(open(tmp_path / "out.json"))
    return out, saved


# ---------------------------------------------------------------- verdicts

def test_confirmed_happy_path(tmp_path):
    # 34 C closes over 34 days, C clearly better than A on every paired day
    c_rs = [2.0, -1.0] * 15 + [2.0] * 4
    a_rs = [-1.0] * 34
    out, saved = run_tool(tmp_path, c_rs, a_rs,
                          blocks_c=[(0, banner())], blocks_a=[(0, banner())])
    v = saved["verdict"]
    assert v["status"] == "VALIDATED-CANDIDATE-CONFIRMED", v
    assert saved["stats"]["n_paired_days"] == 34
    assert saved["stats"]["t"] > 1.0 and saved["stats"]["mean_d_i"] > 0
    assert saved["gates"]["G5"]["floor_certified"] == pytest.approx(FLOOR)
    assert saved["spec"]["schema"] == "mitemshub.artifact-spec.v1"


def test_rejected_branch(tmp_path):
    c_rs = [-1.0, -1.0, 2.0] * 11 + [-1.0]        # 33 trades, mostly losers
    a_rs = [2.0, -1.0] * 17                        # A healthier
    out, saved = run_tool(tmp_path, c_rs, a_rs,
                          blocks_c=[(0, banner())], blocks_a=[(0, banner())])
    v = saved["verdict"]
    assert v["status"] == "REJECTED", v
    assert saved["stats"]["t"] <= -1.0 and saved["stats"]["mean_d_i"] < 0


def test_inconclusive_short_series_collects(tmp_path):
    # 36 C trades over 12 sparse days (n_d=12 < 13): plain INCONCLUSIVE with
    # the collect-to-30 message (the tie-breaker fires only at n_d 13/14)
    tp = tmp_path
    c_rs = [2.0, -1.0, 2.0] * 12                 # 3 trades/day, day mean 1.0
    c_days = [d * 2 for d in range(12) for _ in range(3)]   # every other day
    a_rs = [1.0, -1.0] * 23                      # A daily, 2/day, mean 0.0
    a_days = [d for d in range(23) for _ in range(2)]
    c_led, a_led = tp / "C.csv", tp / "A.csv"
    build_c_ledger(str(c_led), c_rs, days=c_days)
    build_a_ledger(str(a_led), a_rs, days=a_days)
    mon = tp / "monitor.json"
    write_monitor(str(mon))
    (tp / "j").mkdir(exist_ok=True)
    blocks_c = [(0, banner())]
    blocks_a = [(0, banner())]
    write_journal(str(tp / "j"), "fb9a.log", blocks_c, engine="V75MacroEngine")
    write_journal(str(tp / "j"), "71bf.log", blocks_a, engine="MitemshubAI")
    adj.run(["--c-ledger", str(c_led), "--a-ledger", str(a_led),
             "--monitor", str(mon), "--out", str(tp / "o.json"),
             "--journal-dir", str(tp / "j")])
    saved = json.load(open(tp / "o.json"))
    v = saved["verdict"]
    assert v["status"] == "INCONCLUSIVE", v
    assert f"collect to {adj.CAP_PAIRED_DAYS}" in v["reason"]


def test_tiebreaker_13_and_14_days_break_to_inconclusive(tmp_path):
    # n_d exactly 13 / 14 with every other gate clean: the pre-declared
    # tie-breaker must fire BEFORE any declare branch (scarcity never
    # manufactures confidence), even with t at the zero-variance extreme.
    for n_keep in (13, 14):
        tp = tmp_path / f"tb{n_keep}"
        tp.mkdir()
        c_rs = [2.0, -1.0, 2.0] * n_keep          # 3 trades/day, day mean 1.0
        c_days = [d * 2 for d in range(n_keep) for _ in range(3)]
        span = 2 * (n_keep - 1) + 1               # A covers the whole span daily
        a_rs = [1.0, -1.0] * span                 # 2 trades/day -> 2*span rows
        a_days = [d for d in range(span) for _ in range(2)]
        c_led, a_led = tp / "C.csv", tp / "A.csv"
        build_c_ledger(str(c_led), c_rs, days=c_days)
        build_a_ledger(str(a_led), a_rs, days=a_days)
        mon = tp / "monitor.json"
        write_monitor(str(mon))
        (tp / "j").mkdir(exist_ok=True)
        write_journal(str(tp / "j"), "fb9a.log", [(0, banner())], engine="V75MacroEngine")
        write_journal(str(tp / "j"), "71bf.log", [(0, banner())], engine="MitemshubAI")
        adj.run(["--c-ledger", str(c_led), "--a-ledger", str(a_led),
                 "--monitor", str(mon), "--out", str(tp / "o.json"),
                 "--journal-dir", str(tp / "j")])
        saved = json.load(open(tp / "o.json"))
        v = saved["verdict"]
        assert v["status"] == "INCONCLUSIVE", (n_keep, v)
        assert "tie-breaker" in v["reason"], v
        assert saved["stats"]["n_paired_days"] == n_keep


def test_totalr_guard_blocks_confirmed(tmp_path):
    # mean(d_i)>0 with t at the zero-variance extreme, yet C's totalR < A's
    # concurrent totalR (A packs 4 trades/day at a lower mean) — the frozen
    # CONFIRMED condition's totalR clause must block the declaration.
    c_rs = [2.0] * 34                              # 1 trade/day, mean 2.0
    a_rs = [1.0, 1.0, 0.0, 1.0] * 34               # 4 trades/day, mean 0.75
    a_days = [d for d in range(34) for _ in range(4)]
    out, saved = run_tool(tmp_path, c_rs, a_rs, a_days=a_days,
                          blocks_c=[(0, banner())], blocks_a=[(0, banner())])
    v = saved["verdict"]
    assert v["status"] == "INCONCLUSIVE", v
    s = saved["stats"]
    assert s["mean_d_i"] > 0 and s["t"] >= 1.0
    assert s["total_r_c"] < s["total_r_a_concurrent"]


# ---------------------------------------------------------------- gates

def test_g1_keep_collecting_below_30(tmp_path):
    c_rs = [2.0, -1.0] * 12
    a_rs = [2.0, -1.0] * 30
    out, saved = run_tool(tmp_path, c_rs, a_rs,
                          blocks_c=[(0, banner())], blocks_a=[(0, banner())])
    assert saved["verdict"]["status"] == "KEEP COLLECTING"
    assert saved["gates"]["G1"]["closed_trades"] == 24
    assert saved["gates"]["G1"]["eta"]["days_to_30"] > 0


def test_g2_dead_reference_day_invalidates(tmp_path):
    # A skips day 5 entirely while C trades it
    c_rs = [2.0] * 25
    a_rs = [2.0] * 25
    tp = tmp_path
    c_led = tp / "C.csv"
    build_c_ledger(str(c_led), c_rs)
    a_led = tp / "A.csv"
    build_a_ledger(str(a_led), [2.0] * 24, start_day=0)  # covers days 0..23 only
    mon = tp / "monitor.json"
    write_monitor(str(mon))
    out = adj.run(["--c-ledger", str(c_led), "--a-ledger", str(a_led),
                   "--monitor", str(mon), "--out", str(tp / "o.json")])
    saved = json.load(open(tp / "o.json"))
    assert saved["verdict"]["status"] == "INVALID"
    assert "G2" in saved["verdict"]["gates"]


def test_g3_dangling_opens_and_duplicate_tickets(tmp_path):
    rows = [f"OPEN,{day_epoch(i)},{day_epoch(i)},1,100.0,98.0,104.0,0.01,4.50,2.0,86400,PAPER"
            for i in range(4)]
    rows += [f"CLOSE,{day_epoch(0, 11)},{day_epoch(0)},STOP,98.0,-1.000,-4.50,245.50",
             f"EQ,245.50"]
    text = "\n".join(rows) + "\n"
    out, saved = run_tool(tmp_path, [], [], monitor="fresh",
                          blocks_c=[(0, banner())], blocks_a=[(0, banner())],
                          c_ledger_text=text)
    assert saved["verdict"]["status"] == "INVALID"
    assert "G3" in saved["verdict"]["gates"]
    assert any("OPEN rows never closed" in str(p) for p in saved["gates"]["G3"]["problems"])


def test_g3_veq_bookkeeping_break_on_c(tmp_path):
    rs = [2.0, -1.0, 2.0, -1.0, 2.0, -1.0]
    tp = tmp_path
    c_led = tp / "C.csv"
    eq = build_c_ledger(str(c_led), rs)
    # corrupt one CLOSE veq so delta != pnl
    text = c_led.read_text().replace(f"{eq:.2f}", f"{eq + 10:.2f}", 1)
    c_led.write_text(text.replace(f"EQ,{eq:.2f}", f"EQ,{eq + 10:.2f}"))
    a_led = tp / "A.csv"
    build_a_ledger(str(a_led), rs * 4)
    mon = tp / "monitor.json"
    write_monitor(str(mon))
    adj.run(["--c-ledger", str(c_led), "--a-ledger", str(a_led),
             "--monitor", str(mon), "--out", str(tp / "o.json")])
    saved = json.load(open(tp / "o.json"))
    assert saved["verdict"]["status"] == "INVALID"
    assert "G3" in saved["verdict"]["gates"]
    assert any("veq bookkeeping" in str(p) for p in saved["gates"]["G3"]["problems"])


def test_g5_subcase_b_streak_death_mid_window(tmp_path):
    # start compliant, dip below floor mid-window via a brutal streak, recover
    # streak FIRST: 6 straight losses take equity 250 -> 223 < floor 225.54
    c_rs = [-1.0] * 6 + [2.0] * 28
    a_rs = [0.5] * 34
    out, saved = run_tool(tmp_path, c_rs, a_rs,
                          blocks_c=[(0, banner())], blocks_a=[(0, banner())])
    assert saved["verdict"]["status"] == "INVALID"
    g5 = next(i for i in saved["verdict"]["reasons"] if i["gate"] == "G5")
    assert g5["sub_case"] == "b"
    assert saved["gates"]["G5"]["window_min_equity"] < FLOOR
    assert saved["gates"]["G5"]["start_equity"] >= FLOOR


def test_g5_subcase_a_started_below_floor(tmp_path):
    # start equity already below the floor: sub-case (a), the floor-amendment path
    tp = tmp_path / "sub_a"
    tp.mkdir()
    c_rs = [2.0] * 34
    a_rs = [0.5] * 34
    c_led = tp / "C.csv"
    build_c_ledger(str(c_led), c_rs, start_eq=200.0)
    a_led = tp / "A.csv"
    c_led = tp / "C.csv"
    build_c_ledger(str(c_led), c_rs, start_eq=200.0)
    a_led = tp / "A.csv"
    build_a_ledger(str(a_led), a_rs)
    mon = tp / "monitor.json"
    write_monitor(str(mon))
    adj.run(["--c-ledger", str(c_led), "--a-ledger", str(a_led),
             "--monitor", str(mon), "--out", str(tp / "o.json")])
    saved = json.load(open(tp / "o.json"))
    assert saved["verdict"]["status"] == "INVALID"
    g5 = next(i for i in saved["verdict"]["reasons"] if i["gate"] == "G5")
    assert g5["sub_case"] == "a"


def test_g5_stale_monitor_is_a_data_gate(tmp_path):
    c_rs = [2.0] * 34
    a_rs = [0.5] * 34
    out, saved = run_tool(tmp_path, c_rs, a_rs, monitor="stale",
                          blocks_c=[(0, banner())], blocks_a=[(0, banner())])
    assert saved["verdict"]["status"] == "INVALID"
    g5 = next(i for i in saved["verdict"]["reasons"] if i["gate"] == "G5")
    assert "stale" in g5["detail"]


def test_g4_no_journals_unverified_invalid(tmp_path):
    c_rs = [2.0, -1.0] * 17
    a_rs = [2.0, -1.0] * 17
    out, saved = run_tool(tmp_path, c_rs, a_rs)  # no journal blocks at all
    assert saved["verdict"]["status"] == "INVALID"
    assert saved["gates"]["G4"]["status"] == "UNVERIFIED"


def test_g4_identical_banners_clean(tmp_path):
    # G4 reads clean on identical banners; the 17-day span is short, so the
    # run ends KEEP COLLECTING (schedule gate) — not an evidence verdict.
    c_rs = [2.0, -1.0] * 17
    a_rs = [2.0, -1.0] * 17
    out, saved = run_tool(tmp_path, c_rs, a_rs,
                          blocks_c=[(0, banner()), (5, banner())],
                          blocks_a=[(0, banner()), (5, banner())])
    assert saved["gates"]["G4"]["status"] == "clean"
    v = saved["verdict"]
    assert v["status"] == "INCONCLUSIVE", v
    assert "does not meet either declare branch" in v["reason"]


def test_g4_changed_banner_invalid(tmp_path):
    c_rs = [2.0, -1.0] * 17
    a_rs = [2.0, -1.0] * 17
    out, saved = run_tool(tmp_path, c_rs, a_rs,
                          blocks_c=[(0, banner()), (5, banner(version="v26.38-CHANGED"))],
                          blocks_a=[(0, banner())])
    assert saved["verdict"]["status"] == "INVALID"
    assert "G4" in saved["verdict"]["gates"]


def test_g4_version_bump_alone_is_not_a_diff(tmp_path):
    c_rs = [2.0, -1.0] * 17
    a_rs = [2.0, -1.0] * 17
    out, saved = run_tool(tmp_path, c_rs, a_rs,
                          blocks_c=[(0, banner()), (5, banner(version="v26.38"))],
                          blocks_a=[(0, banner())])
    assert saved["gates"]["G4"]["status"] == "clean"


# ---------------------------------------------------------------- helpers

def test_paired_t_zero_variance():
    assert adj.paired_t([1.0, 1.0, 1.0]) == 999.0
    assert adj.paired_t([-1.0, -1.0]) == -999.0
    assert adj.paired_t([0.0, 0.0]) == 0.0
    assert abs(adj.paired_t([1.0, -1.0, 1.0, -1.0])) == 0.0


def test_day_key_and_diff():
    assert adj.day_key(day_epoch(0)) == "2026-10-01"
    assert adj.day_diff("2026-10-01", "2026-10-22") == 21
