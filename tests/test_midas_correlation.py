"""Tests for the [3b] correlation view (aggregate paper exposure).

Day one of the §14 portfolio, M1t and M1m opened the same-direction position
on the same bar — the modes share a signal bar by construction, so the
portfolio's exposure is sometimes the cluster's SUM, not one arm's risk.
These tests pin: the cluster boundary (900 s = one M15 bar, direction must
match), the OPEN-row collector (EA row grammar, dir 1=BUY/-1=SELL, dangling
OPEN = live position), and that the section prints the cluster per arm and
in summary WITHOUT turning correlation into a health verdict (the §14 modes
are certified individually — a correlated fill is information, not drift).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import morning_status as ms  # noqa: E402
from midas_watchdog import preset_for_tag  # noqa: E402


# --- fixtures -------------------------------------------------------------------

def _chart_text(tag: str) -> str:
    """A realistic pinned .chr body for one arm: the ARM'S OWN repo .set pins
    (M1t really runs mode=2 — building every chart from M1's pins would be
    fixture drift, and [3b] correctly flags that as preset DRIFT)."""
    lines = ["; chart", "MidastouchAI", "symbol=XAUUSDmicro", "period_size=15",
             "==== Strategy (frozen protocol defaults) ===="]
    with open(preset_for_tag(tag), encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln.startswith("Inp"):
                key, _, val = ln.partition("=")
                lines.append(f"InpArmTag={tag}" if key == "InpArmTag" else ln)
    return "\r\n".join(lines) + "\r\n"


def _open_row(epoch: int, ticket: int, direction: int, tag: str) -> str:
    return (f"OPEN,{epoch},{ticket},{direction},4354.08500,4308.62929,"
            f"4444.99643,0.10,4.55,45.45571,43200,{tag}")


def _ledger(rows: list[str]) -> str:
    return ("ERA,MIDAS1.10,1789651864,pertick-fills\nEQ,50.00\n"
            + "".join(r + "\n" for r in rows))


BAR = 1789657200  # one M15 signal bar (epoch seconds)


def _portfolio(tmp_path, arms: dict[str, list[str]]) -> str:
    """A fake terminal tree: one chart + one ledger per arm tag."""
    term_root = os.path.join(str(tmp_path), "Term")
    d = os.path.join(term_root, "FAKEHASH", "MQL5", "Profiles", "Charts", "Default")
    fd = os.path.join(term_root, "FAKEHASH", "MQL5", "Files")
    os.makedirs(d, exist_ok=True)
    os.makedirs(fd, exist_ok=True)
    for tag, rows in arms.items():
        with open(os.path.join(d, f"chart_{tag}.chr"), "w", encoding="utf-16") as f:
            f.write(_chart_text(tag))
        with open(os.path.join(fd, f"MIDASTOUCH_paper_XAUUSDmicro_{tag}.csv"), "w") as f:
            f.write(_ledger(rows))
    return term_root


# --- the cluster boundary (pure) --------------------------------------------------

def _pos(tag: str, epoch: int, direction: int) -> dict:
    return {"tag": tag, "dir": direction, "epoch": epoch, "ticket": "1"}


def test_no_positions_no_clusters():
    assert ms.correlate_midas_positions([]) == []
    assert ms.correlate_midas_positions([_pos("M1", BAR, 1)]) == []


def test_two_arms_same_bar_same_direction_cluster():
    c = ms.correlate_midas_positions([_pos("M1", BAR, 1), _pos("M1t", BAR, 1)])
    assert len(c) == 1
    assert c[0]["n"] == 2 and c[0]["dir"] == 1
    assert sorted(c[0]["tags"]) == ["M1", "M1t"]


def test_opposite_directions_never_cluster():
    c = ms.correlate_midas_positions([_pos("M1", BAR, 1), _pos("M1t", BAR, -1)])
    assert c == [], "a LONG and a SHORT on the same bar are not the same exposure"


def test_tolerance_is_one_m15_bar_inclusive():
    inside = ms.correlate_midas_positions([_pos("M1", BAR, -1),
                                           _pos("M1t", BAR + 900, -1)])
    assert len(inside) == 1 and inside[0]["n"] == 2
    outside = ms.correlate_midas_positions([_pos("M1", BAR, -1),
                                            _pos("M1t", BAR + 901, -1)])
    assert outside == [], "901 s apart is a different signal bar"


def test_gap_does_not_merge_distant_opens():
    """Two arms now, one more 2 h later, same direction: one cluster of two,
    not one cluster of three — the later signal is a different bar."""
    c = ms.correlate_midas_positions([_pos("M1", BAR, 1),
                                      _pos("M1t", BAR + 30, 1),
                                      _pos("M1m", BAR + 7200, 1)])
    assert len(c) == 1 and c[0]["n"] == 2
    assert sorted(c[0]["tags"]) == ["M1", "M1t"]


def test_long_and_short_clusters_coexist():
    c = ms.correlate_midas_positions([_pos("M1", BAR, 1), _pos("M1t", BAR + 60, 1),
                                      _pos("M1s", BAR, -1), _pos("M1m", BAR + 60, -1)])
    assert {(x["dir"], x["n"]) for x in c} == {(1, 2), (-1, 2)}


# --- the collector (EA row grammar) ------------------------------------------------

def test_collect_reads_dangling_opens_only(tmp_path):
    term_root = _portfolio(tmp_path, {
        "M1": [_open_row(BAR, 111, 1, "M1"),
               "CLOSE,1789657800,111,TP,4444.99643,2.00,9.10,59.10",  # closed
               _open_row(BAR + 3600, 112, -1, "M1")],                 # the live one
        "M1t": [_open_row(BAR, 211, -1, "M1t")],
    })
    charts = _charts_of(term_root)
    got = {p["tag"]: p for p in ms.collect_midas_positions(charts)}
    assert set(got) == {"M1", "M1t"}
    assert got["M1"]["dir"] == -1 and got["M1"]["epoch"] == BAR + 3600
    assert got["M1t"]["dir"] == -1, "dir -1 is SELL (EA writes 1 for BUY)"


def test_collect_skips_missing_and_corrupt(tmp_path, capsys):
    term_root = _portfolio(tmp_path, {
        "M1": [_open_row(BAR, 111, 1, "M1")],
        "M1t": ["OPEN,x,211,1,1,1,1,1,1,1,1,M1t",         # unparseable epoch/dir
                "OPEN," + ",".join(["1"] * 10)],           # too short
        "M1s": [],                                          # ledger exists, flat
    })
    os.remove(os.path.join(term_root, "FAKEHASH", "MQL5", "Files",
                           "MIDASTOUCH_paper_XAUUSDmicro_M1s.csv"))
    charts = _charts_of(term_root)
    got = ms.collect_midas_positions(charts)
    assert [p["tag"] for p in got] == ["M1"]


# --- the [3b] section: displayed, never a health verdict ---------------------------

def _charts_of(term_root: str) -> list[tuple[str, str]]:
    """(terminal_dir, chart_text) pairs, mirroring how print_midas_section
    discovers charts under TERM_ROOT."""
    out = []
    for root, _dirs, files in os.walk(term_root):
        for fn in files:
            if fn.endswith(".chr"):
                p = os.path.join(root, fn)
                with open(p, encoding="utf-16") as f:
                    # p = <term_root>/<hash>/MQL5/Profiles/Charts/Default/x.chr
                    # the collector needs <term_root>/<hash> (five dirnames up)
                    td = p
                    for _ in range(5):
                        td = os.path.dirname(td)
                    out.append((td, f.read()))
    return out


def test_section_prints_cluster_for_same_bar_fills(tmp_path, monkeypatch, capsys):
    term_root = _portfolio(tmp_path, {
        "M1": [_open_row(BAR, 111, 1, "M1")],
        "M1t": [_open_row(BAR + 60, 211, 1, "M1t")],
    })
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    healthy = ms.print_midas_section()
    out = capsys.readouterr().out
    assert "correlation:" in out
    assert "2 arms LONG opened within 15 min: M1, M1t" in out
    assert out.count("live cluster:") == 2, "each exposed arm sees its own cluster"
    assert healthy is False, "correlation is display-only, not an unhealthy signal"
    assert "PROBLEM" not in out


def test_section_quiet_when_flat_or_opposed(tmp_path, monkeypatch, capsys):
    term_root = _portfolio(tmp_path, {
        "M1": [_open_row(BAR, 111, 1, "M1")],
        "M1t": [_open_row(BAR, 211, -1, "M1t")],   # opposite: not one exposure
    })
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    healthy = ms.print_midas_section()
    out = capsys.readouterr().out
    assert "correlation:" not in out and "live cluster:" not in out
    assert healthy is False


def test_section_flat_portfolio_has_no_correlation_block(tmp_path, monkeypatch, capsys):
    term_root = _portfolio(tmp_path, {"M1": [], "M1t": []})
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    ms.print_midas_section()
    out = capsys.readouterr().out
    assert out.count("live: flat") == 2
    assert "correlation:" not in out
