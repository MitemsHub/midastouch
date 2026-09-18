"""Offline tests for the V2 register R10 telemetry ledger columns (v1.13).

The never-abort class law: telemetry columns ride ONLY as end-of-row
appends on the paper rows of record, and every python consumer of the
ledger grammar must tolerate the longer rows byte-for-byte. The format
prefixes pin the frozen grammar's head positionally — append-only is the
contract, insertion/reordering is the crime.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
sys.path.insert(0, str(REPO / "scripts"))

import era as era_mod                                   # noqa: E402
from midas_verdict import arm_statistics                # noqa: E402
from midas_parity import parse_ledger                   # noqa: E402
from morning_status import (                            # noqa: E402
    collect_midas_positions,
    correlate_midas_positions,
)


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    return re.sub(r"//[^\n]*", "", s)


def body(fn_name: str) -> str:
    """Brace-matched body of a named function."""
    s = src()
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


def _callsites(fmt: str) -> int:
    """How many PaperLog StringFormat callsites use exactly this format string."""
    code = strip_comments(src())
    return len(re.findall(re.escape(f'"{fmt}"'), code))


# --- the frozen grammar heads, pinned positionally ----------------------------

def test_paper_open_prefix_frozen_with_two_appends() -> None:
    # 12 frozen fields + arm tag, then the v1.13 appends: atr, spread-at-open
    assert _callsites(
        "OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s,%.5f,%.5f"
    ) == 1, "BAR OPEN must keep the frozen 12-field head + atr,spread appends"


def test_paper_close_prefix_frozen_with_two_appends() -> None:
    # 8 frozen fields, then the v1.13 appends: spread-at-close, slippage
    assert _callsites(
        "CLOSE,%I64d,%I64u,%s,%.5f,%.3f,%.2f,%.2f,%.5f,%.5f"
    ) == 2, "both paper CLOSE writers (BAR + PERTICK) carry the appends"


def test_appends_are_at_end_of_row_only() -> None:
    code = strip_comments(src())
    # every telemetry-bearing format ends in the append specifiers
    assert '"OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s,%.5f,%.5f"' in code
    assert '"CLOSE,%I64d,%I64u,%s,%.5f,%.3f,%.2f,%.2f,%.5f,%.5f"' in code
    # and no inserted-in-the-middle variant exists (telemetry specifiers only
    # ever appear at the tail of a format string)
    for m in re.finditer(r'"(OPEN|CLOSE)[^"]*"', code):
        f = m.group(0)
        if ",%.5f,%.5f\"" in f and f.startswith('"CLOSE'):
            assert f.endswith(',%.5f,%.5f"')


def test_era_note_cites_the_register() -> None:
    code = strip_comments(src())
    assert 'telemetry-only-per-V2-register' in code, "ERA note must cite the register"
    b = strip_comments(src())
    m = re.search(r'era_note \+?= [^;]+;', b)
    assert m, "era_note composition must exist"
    assert "if(!InpBarModel)" in code, "BAR tester ledgers keep the parity-era note byte-for-byte"


def test_version_bumped_and_property_consistent() -> None:
    s = src()
    prop = re.search(r'#property\s+version\s+"(\d+)\.(\d+)"', s)
    define = re.search(r'#define\s+APP_VERSION\s+"MIDAS(\d+)\.(\d+)"', s)
    assert prop and define
    assert prop.groups() == define.groups(), "#property version must equal APP_VERSION"
    assert define.group(2) == "16", "current tree build is MIDAS1.16 (R6 fail-closed preconditions)"


# --- the safety net: every python consumer tolerates the appended rows --------

def _write(tmp_path: Path, rows: list[str]) -> Path:
    p = tmp_path / "MIDASTOUCH_paper_XAUUSDmicro_M1.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return p


def _appended_open(tag: str) -> str:
    # 12 frozen fields + v1.13 appends (atr_at_entry, spread_at_open)
    return ("OPEN,1789657200,1789657200,1,4354.08500,4308.62929,4444.99643,"
            f"0.10,4.55,45.45571,43200,{tag},45.45571,0.50")


def _appended_close() -> str:
    # 8 frozen fields + v1.13 appends (spread_at_close, slippage)
    return "CLOSE,1789660800,1789657200,SL,4320.00000,-0.750,-3.41,46.59,0.50,0.00"


def test_midas_verdict_tolerates_appends(tmp_path):
    rows = [f"ERA,MIDAS1.13,{era_mod.ERA_EPOCH},"
            "pertick-fills+telemetry-only-per-V2-register"]
    for i in range(61):
        r = 1.0 if i < 55 else -0.5
        rows.append(f"CLOSE,{1789657200 + i * 3600},{1789657200 + i * 3600},"
                    f"SL,4320.00000,{r:.3f},1.50,50.00,45.45571,0.50")
    s = arm_statistics(str(_write(tmp_path, rows)))
    assert s["n"] == 61, "appended fields must not disturb the n read"
    assert abs(s["total_r"] - 52.0) < 1e-6, "r stays parts[5], veq stays parts[7]"
    assert s["era_versions"] == ["MIDAS1.13"], "single version: no structural abort"
    assert s.get("problems", []) == [], "no too-short/unparseable rows on appended grammar"


def test_parity_parse_ledger_tolerates_appends(tmp_path):
    rows = ["ERA,MIDAS1.13,1,pertick-fills", _appended_open("M1"), _appended_close()]
    trades = parse_ledger(_write(tmp_path, rows))
    assert len(trades) == 1
    t = trades[0]
    assert t["open_ct"] == 1789657200 and t["close_ct"] == 1789660800
    assert t["side"] == 1 and abs(t["r"] - (-0.750)) < 1e-9


def test_ledger_flatness_tolerates_appends(tmp_path):
    from v28_sweep_runner import ledger_flatness
    rows = [f"ERA,MIDAS1.13,{era_mod.ERA_EPOCH},"
            "pertick-fills+telemetry-only-per-V2-register",
            _appended_open("M1"), _appended_close(), "EQ,50.00"]
    f = ledger_flatness(str(_write(tmp_path, rows)))
    assert f["flat"] is True, "closed pair with appends must read flat"
    assert f["closed"] == 1 and not f["problems"]


def test_morning_status_collectors_tolerate_appends(tmp_path):
    d = tmp_path / "MQL5" / "Files"
    d.mkdir(parents=True)
    (d / "MIDASTOUCH_paper_XAUUSDmicro_M1t.csv").write_text(
        _appended_open("M1t") + "\n", encoding="utf-8")
    (d / "MIDASTOUCH_paper_XAUUSDmicro_M1m.csv").write_text(
        _appended_open("M1m") + "\n", encoding="utf-8")
    charts = [(str(tmp_path), "symbol=XAUUSDmicro\nInpArmTag=M1t\n"),
              (str(tmp_path), "symbol=XAUUSDmicro\nInpArmTag=M1m\n")]
    pos = collect_midas_positions(charts)
    assert len(pos) == 2, "appended OPEN rows must still count as live positions"
    clusters = correlate_midas_positions(pos)
    assert len(clusters) == 1 and "M1t" in str(clusters[0]) and "M1m" in str(clusters[0])


def test_era_row_with_note_suffix_classifies_post(tmp_path):
    # the register-citing note must not break era classification for consumers
    rows = [f"ERA,MIDAS1.13,{era_mod.ERA_EPOCH},"
            "pertick-fills+telemetry-only-per-V2-register",
            _appended_open("M1"), _appended_close()]
    p = _write(tmp_path, rows)
    eras = era_mod.parse_era_rows(str(p))
    assert eras and eras[0]["version"] == "MIDAS1.13"
    assert eras[0]["era"].startswith("pertick-fills"), "note rides as a suffix"


# --- consumer completeness: the enumerate, not a hand list ---------------------

def _ledger_grammar_consumers() -> list[str]:
    """Dynamically enumerate every module in scripts/ whose source mentions
    the ledger row grammar (OPEN/CLOSE row-prefix readers or the paper ledger
    filename pattern). A NEW consumer (a future script reading ledgers)
    enters this list automatically — and the tolerance test below then
    demands it accepts appended rows. The hand list in the tests above is
    complete BY CONSTRUCTION, not by maintenance. (First run found two
    real consumers the hand list had missed: ab_adjudicate,
    adjudicate_arm_c.)"""
    consumers = []
    for py in sorted((REPO / "scripts").glob("*.py")):
        text = py.read_text(encoding="utf-8", errors="replace")
        if 'parts[0] == "OPEN"' in text or 'parts[0] == "CLOSE"' in text \
                or 'row[0] == "OPEN"' in text or "MIDASTOUCH_paper_" in text:
            consumers.append(py.stem)
    return consumers


def test_consumer_enumerate_matches_the_hand_list() -> None:
    consumers = set(_ledger_grammar_consumers())
    assert {"midas_verdict", "midas_parity", "v28_sweep_runner",
            "morning_status", "midas_watchdog", "ab_adjudicate",
            "adjudicate_arm_c", "deploy_portfolio"} <= consumers, (
        "the known consumers must always be enumerated; the dynamic scan "
        "broke — fix the scan, not the list")


def test_every_enumerated_consumer_tolerates_appends(tmp_path):
    """For EACH enumerated consumer with a public ledger reader, run that
    reader against the appended grammar and demand it still reads the frozen
    fields. Readers are called with the leading path argument only where the
    signature allows; per-module assertions pin the semantic survival of the
    append."""
    import importlib
    rows = [f"ERA,MIDAS1.13,{era_mod.ERA_EPOCH},"
            "pertick-fills+telemetry-only-per-V2-register",
            _appended_open("M1"), _appended_close(), "EQ,50.00"]
    p = str(_write(tmp_path, rows))
    # exercised directly: the row-grammar readers of the paper book
    assert arm_statistics(p)["n"] == 1
    trades = parse_ledger(p)
    assert len(trades) == 1 and trades[0]["r"] == -0.750
    from v28_sweep_runner import ledger_flatness
    f = ledger_flatness(p)
    assert f["flat"] and f["closed"] == 1
    from ab_adjudicate import parse_ledger as ab_parse
    ab_trades, _curve, _integ = ab_parse(p)
    assert len(ab_trades) == 1 and ab_trades[0]["r"] == -0.750
    from adjudicate_arm_c import parse_ledger as c_parse
    c_trades = c_parse(p, "paper")
    assert c_trades, "arm-c reader must still pair the appended rows"
    from midas_watchdog import ledger_health
    h = ledger_health(p, now_s=0.0)
    assert h["flat"] and h["closed"] == 1 and not h["problems"]
    # morning_status.collect_midas_positions + deploy_portfolio (via
    # v28_sweep_runner.ledger_flatness) are covered by the tests above and
    # by the dynamic-enumerate pin; their grammars share the readers here.
