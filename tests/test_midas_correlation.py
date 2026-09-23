"""Tests for the [3b] correlation view (aggregate paper exposure).

Day one of the §14 portfolio, two modes opened the same-direction position on the
same bar — the modes share a signal bar by construction, so the portfolio's
exposure is sometimes the cluster's SUM, not one arm's risk. The fixtures now carry
the two arms that actually ship (the M1 baseline and this account's `U25` mirror);
the retired modes survive as labels in the pure cluster-rule tests below.
These tests pin: the cluster boundary (900 s = one M15 bar, direction must
match), the OPEN-row collector (EA row grammar, dir 1=BUY/-1=SELL, dangling
OPEN = live position), and that the section prints the cluster per arm and
in summary WITHOUT turning correlation into a health verdict (the §14 modes
are certified individually — a correlated fill is information, not drift).
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import morning_status as ms  # noqa: E402
from midas_watchdog import preset_for_tag  # noqa: E402


# --- fixtures -------------------------------------------------------------------

#: The live portfolio: the certified M1 baseline, and this account's mirror arm, whose
#: TAG is `U25` while its FILE is `MidastouchAI_upcomers_gold.set`.
#:
#: Fixtures must use arms whose presets actually ship. An arm whose repo `.set` cannot
#: be read is *correctly* flagged `preset identity UNVERIFIABLE` by [3b] — so a fixture
#: built on a deleted preset cannot yield a healthy portfolio, however its assertions
#: are written. That is exactly what happened here: the retired arms (M1t/M1m/M1o/M1s,
#: LV — presets deleted by commit `4fba1fe`, "Delete the seven non-trading presets")
#: were used to build charts, and five live tests failed for a reason nobody could act
#: on. They now survive only as pure-function LABELS in the cluster tests below, where
#: no preset is read and the retired tag is just a name.
LIVE_ARM = "M1"
ACCOUNT_ARM = "U25"
SYMBOL = "XAUUSD"


def _chart_text(tag: str, armed: bool = False) -> str:
    """A realistic pinned .chr body for one arm, from that ARM'S OWN repo `.set`
    pins (building a chart from another arm's pins is fixture drift, and [3b]
    correctly flags that as preset DRIFT). `armed=True` builds it from the LIVE pin,
    which is the configuration a chart actually carries once a record exists."""
    lines = ["; chart", "MidastouchAI", f"symbol={SYMBOL}", "period_size=15",
             "==== Strategy (frozen protocol defaults) ===="]
    with open(preset_for_tag(tag, armed=armed), encoding="utf-8") as f:
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


def _portfolio(tmp_path, arms: dict[str, list[str]], armed: bool = False) -> str:
    """A fake terminal tree: one chart + one ledger per arm tag."""
    term_root = os.path.join(str(tmp_path), "Term")
    d = os.path.join(term_root, "FAKEHASH", "MQL5", "Profiles", "Charts", "Default")
    fd = os.path.join(term_root, "FAKEHASH", "MQL5", "Files")
    os.makedirs(d, exist_ok=True)
    os.makedirs(fd, exist_ok=True)
    for tag, rows in arms.items():
        with open(os.path.join(d, f"chart_{tag}.chr"), "w", encoding="utf-16") as f:
            f.write(_chart_text(tag, armed=armed))
        with open(os.path.join(fd, f"MIDASTOUCH_paper_{SYMBOL}_{tag}.csv"), "w") as f:
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
        LIVE_ARM: [_open_row(BAR, 111, 1, LIVE_ARM),
                   "CLOSE,1789657800,111,TP,4444.99643,2.00,9.10,59.10",  # closed
                   _open_row(BAR + 3600, 112, -1, LIVE_ARM)],            # the live one
        ACCOUNT_ARM: [_open_row(BAR, 211, -1, ACCOUNT_ARM)],
    })
    charts = _charts_of(term_root)
    got = {p["tag"]: p for p in ms.collect_midas_positions(charts)}
    assert set(got) == {LIVE_ARM, ACCOUNT_ARM}
    assert got[LIVE_ARM]["dir"] == -1 and got[LIVE_ARM]["epoch"] == BAR + 3600
    assert got[ACCOUNT_ARM]["dir"] == -1, "dir -1 is SELL (EA writes 1 for BUY)"


def test_collect_skips_missing_and_corrupt(tmp_path, capsys):
    """Two ways an arm drops out of the view: unreadable rows, and no ledger at all.

    The chart-without-a-ledger arm is written directly here, because `_portfolio`
    always writes a ledger alongside its chart — the missing-file path has to be made
    on purpose, and it now gets a tag of its own instead of borrowing a retired arm's.
    """
    term_root = _portfolio(tmp_path, {
        LIVE_ARM: [_open_row(BAR, 111, 1, LIVE_ARM)],
        ACCOUNT_ARM: ["OPEN,x,211,1,1,1,1,1,1,1,1," + ACCOUNT_ARM,  # unparseable epoch
                      "OPEN," + ",".join(["1"] * 10)],            # too short
    })
    charts_dir = os.path.join(term_root, "FAKEHASH", "MQL5", "Profiles", "Charts",
                              "Default")
    with open(os.path.join(charts_dir, "chart_GHOST.chr"), "w", encoding="utf-16") as f:
        f.write(_chart_text(LIVE_ARM).replace(f"InpArmTag={LIVE_ARM}", "InpArmTag=GHOST"))
    charts = _charts_of(term_root)
    got = ms.collect_midas_positions(charts)
    assert [p["tag"] for p in got] == [LIVE_ARM]


# --- the [3b] section: displayed, never a health verdict ---------------------------

def _paper_world(monkeypatch) -> None:
    """Pin the [3b] section into the world these display tests describe: no arming record.

    THE FIXTURES ARE PINNED TO THE PAPER PRESET, and that is only the correct pin while
    nothing is armed. Once `artifacts/live/armed.json` exists, `preset_for_tag("U25")`
    resolves to the LIVE variant by design — so a fixture chart built from the paper pin
    becomes DRIFT, and these tests would flip from "clean" to "unhealthy" the moment the
    operator arms the account. That is a test depending on this machine's arming state,
    which is exactly what `preset_for_tag(armed=...)` set out to avoid. So the paper-world
    tests say which world they are in, and `test_armed_world_*` below covers the other one.
    """
    monkeypatch.setattr(ms.R, "arming_state",
                        lambda *a, **k: {"armed": False, "override": False, "arm": "",
                                         "summary": "no arming record — execution is OFF"})
    _no_account_deals(monkeypatch)


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
        LIVE_ARM: [_open_row(BAR, 111, 1, LIVE_ARM)],
        ACCOUNT_ARM: [_open_row(BAR + 60, 211, 1, ACCOUNT_ARM)],
    })
    _paper_world(monkeypatch)
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    healthy = ms.print_midas_section()
    out = capsys.readouterr().out
    assert "correlation:" in out
    assert f"2 arms LONG opened within 15 min: {LIVE_ARM}, {ACCOUNT_ARM}" in out
    assert out.count("live cluster:") == 2, "each exposed arm sees its own cluster"
    assert healthy is False, "correlation is display-only, not an unhealthy signal"
    assert "PROBLEM" not in out


def test_section_quiet_when_flat_or_opposed(tmp_path, monkeypatch, capsys):
    term_root = _portfolio(tmp_path, {
        LIVE_ARM: [_open_row(BAR, 111, 1, LIVE_ARM)],
        ACCOUNT_ARM: [_open_row(BAR, 211, -1, ACCOUNT_ARM)],  # opposite: not one exposure
    })
    _paper_world(monkeypatch)
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    healthy = ms.print_midas_section()
    out = capsys.readouterr().out
    assert "correlation:" not in out and "live cluster:" not in out
    assert healthy is False


# --- the [3b] section in the ARMED world (2026-09-21 operator override) -------------

def _no_account_deals(monkeypatch) -> None:
    """Pin the other machine-state dependency: the account's deal history.

    [3b] reconciles the live ledger against the ACCOUNT, so a synthetic world without this
    still reads the real terminal. MEASURED 2026-09-22: the arm's first live fill turned
    `test_armed_world_...(the paper arm paper)` unhealthy — the exact class of dependency
    `preset_for_tag(armed=...)` exists to remove. The fixtures below hold no account deals,
    so the world says so (morning_status.LIVE_FILL_DEAL_READER).
    """
    monkeypatch.setattr(ms, "LIVE_FILL_DEAL_READER", lambda *a, **k: [])


def _armed_world(monkeypatch) -> None:
    """The record names the U25 arm and says, in its own field, that it is an override."""
    monkeypatch.setattr(ms.R, "arming_state", lambda *a, **k: {
        "armed": True, "override": True, "arm": ACCOUNT_ARM,
        "summary": "ARMED BY OPERATOR OVERRIDE — the walk-forward gate FAILED"})
    _no_account_deals(monkeypatch)


def test_armed_world_marks_the_live_arm_live_and_the_paper_arm_paper(tmp_path, monkeypatch, capsys):
    """The banner follows the CHART, and the ARMED line follows the RECORD's own arm.

    Both halves are the failure mode this pins: the live marker used to be `tag == "LV"`,
    so the account's own live arm would have printed "paper" while placing real orders,
    and the override notice used to print on every arm block, which reads as "this paper
    arm is armed" on the one branch whose ledger is meant to be arms-length.
    """
    term_root = _portfolio(tmp_path, {
        LIVE_ARM: [_open_row(BAR, 111, 1, LIVE_ARM)],
        ACCOUNT_ARM: [_open_row(BAR, 211, 1, ACCOUNT_ARM)],
    }, armed=True)
    _armed_world(monkeypatch)
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    healthy = ms.print_midas_section()
    out = capsys.readouterr().out
    blocks: dict[str, str] = {}
    for blk in re.split(r"\[3b\] MIDASTOUCH GOLD ARM", out)[1:]:
        m = re.search(r"tag (\S+)", blk)
        blocks[m.group(1)] = blk
    assert set(blocks) == {LIVE_ARM, ACCOUNT_ARM}, out
    assert "LIVE $$$" in blocks[ACCOUNT_ARM].splitlines()[0], blocks[ACCOUNT_ARM]
    assert "paper" in blocks[LIVE_ARM].splitlines()[0], blocks[LIVE_ARM]
    assert "ARMED:" in blocks[ACCOUNT_ARM], "the armed arm's block does not say it is armed"
    assert "ARMED:" not in blocks[LIVE_ARM], "the paper arm's block claims the override"
    assert healthy is False, f"the armed world's own pins must be clean:\n{out}"


def test_armed_record_with_an_arm_still_on_the_paper_pin_is_drift(tmp_path, monkeypatch, capsys):
    """The go-live guard: an arm left on the paper preset while the record is armed.

    This is the mistake that would silently halve a deployment — the record says real
    orders, the chart still runs `InpLiveExecution=false`, and every tool that only
    asked "is a record present?" would report a healthy live arm that places nothing.
    """
    term_root = _portfolio(tmp_path, {  # note: NOT `armed=True` — the stale chart
        ACCOUNT_ARM: [_open_row(BAR, 211, 1, ACCOUNT_ARM)],
    })
    _armed_world(monkeypatch)
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    healthy = ms.print_midas_section()
    out = capsys.readouterr().out
    assert healthy is True, f"a stale paper pin under an armed record is unhealthy:\n{out}"
    assert "CHART IS INERT" in out.upper() or "inert" in out, out


def test_section_flat_portfolio_has_no_correlation_block(tmp_path, monkeypatch, capsys):
    term_root = _portfolio(tmp_path, {LIVE_ARM: [], ACCOUNT_ARM: []})
    _paper_world(monkeypatch)
    monkeypatch.setattr(ms, "TERM_ROOT", term_root)
    ms.print_midas_section()
    out = capsys.readouterr().out
    assert out.count("live: flat") == 2
    assert "correlation:" not in out
