"""Go-live pins (2026-09-18): the LIVE ledger grammar is a first-class row
class everywhere the paper grammar is.

The live arm writes LOPEN/LCLOSE rows (LCLOSE[2] = posid, matching
LOPEN[2]; LCLOSE carries R, not $). Pinned here:
  * the WRITER-EXACT row shape: the fixtures below are built from the MQ5
    format strings themselves (14-field LOPEN, 6-field LCLOSE) — the
    2026-09-18 incident where synthetic tests passed on an imagined 15-field
    shape while the real EA row was invisible to every python consumer is
    structurally impossible to repeat;
  * watchdog ledger_health: a dangling LOPEN is an OPEN POSITION — the
    flat gate must refuse a terminal restart over a live real-money trade
    (SKIP-OPEN-POSITION), and must return to flat after the LCLOSE;
  * morning_status.parse_ledger: dangling LOPEN pairs with LCLOSE, and
    LCLOSE rows never enter the PAPER closed list (no $pnl/veq on them);
  * morning_status.live_grammar_view: open positions + close count + exit
    reasons, including a corrupt-row fail-closed problem;
  * the parity harness ledger_flatness: same LIVE-grammar awareness (a
    dangling LOPEN refuses the cert session's terminal stop);
  * the LIVE preset: execution=true, dedicated magic, PERTICK — and the
    four paper presets stay paper (the one-commit rule, both directions).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_watchdog as wd  # noqa: E402
import morning_status as ms  # noqa: E402

NOW = 1789713600.0


# --- the writer-exact grammar, derived from the EA source at test time ----------

def _writer_format(prefix: str) -> str:
    """The PaperLog format string for `prefix` (LOPEN/LCLOSE), straight from
    MidastouchAI.mq5. The row shape is OWNED by this string."""
    src = (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5").read_text(
        encoding="utf-8", errors="replace")
    m = re.search(rf'PaperLog\(StringFormat\("{prefix},([^"\\]+)"', src)
    assert m, f"the {prefix} writer format string moved — update this fixture"
    return m.group(1)


def _writer_specs(prefix: str) -> list[str]:
    fmt = _writer_format(prefix)
    specs = re.findall(r"%I64[du]|%[-0-9.]*[dfs]", fmt)
    return specs


# Writer order: epoch,posid,order,deal,dir,entry,sl,tp,lots,risk$,stop,timeout,tag
# (%s%s = tag + optional _FLOORED suffix, joined with NO separator -> ONE field)
LOPEN = ("LOPEN,1789712100,2048845860,987654321,2048845860,1,"
         "4389.07500,4359.41071,4448.40357,0.10,2.91,29.08429,43200,LV")
LOPEN_DANGLING = [LOPEN]
# EA LCLOSE writer: LCLOSE,epoch,posid,reason,exit,R (6 fields)
LOPEN_CLOSED = [LOPEN, "LCLOSE,1789716600,2048845860,TIMEOUT,4360.10,-1.00",
                "EQ,50.00"]


def test_lopen_writer_shape_is_14_fields_and_parsers_agree(tmp_path: Path) -> None:
    """THE structural pin: count the MQ5 writer's specifiers, then require the
    python consumers to see exactly that row. The 2026-09-18 incident (a
    15-field parser contract against a 14-field writer — the first live fill
    would have been invisible to [3b] AND the restart gate) cannot recur."""
    specs = _writer_specs("LOPEN")
    assert len(specs) == 14, specs
    # %s%s (tag + _FLOORED suffix) join into one field: 13 comma fields + prefix
    assert specs[-2:] == ["%s", "%s"]
    parts = LOPEN.split(",")
    assert len(parts) == 14 and parts[0] == "LOPEN"
    # parser indices: posid [2], dir [5] — the writer's deal id sits at [4]
    v = ms.live_grammar_view(_write(tmp_path, LOPEN_DANGLING))
    assert v["problems"] == [] and len(v["open"]) == 1
    o = v["open"][0]
    assert o["posid"] == "2048845860" and o["dir"] == 1
    assert o["entry"] == 4389.07500 and o["vol"] == 0.10
    assert o["sl"] == 4359.41071 and o["tp"] == 4448.40357
    # and the watchdog's flat gate keys the same row
    h = wd.ledger_health(_write(tmp_path, LOPEN_DANGLING), NOW)
    assert not h["flat"] and h["open_positions"][0]["ticket"] == "2048845860"


def test_lclose_writer_shape_is_6_fields() -> None:
    specs = _writer_specs("LCLOSE")
    assert len(specs) == 5, specs          # epoch,posid,reason,exit,R after prefix
    parts = "LCLOSE,1789716600,2048845860,TIMEOUT,4360.10,-1.00".split(",")
    assert len(parts) == 6 and parts[3] == "TIMEOUT"


def _write(tmp: Path, rows: list[str]) -> str:
    p = tmp / "MIDASTOUCH_paper_XAUUSDmicro_LV.csv"
    p.write_text("\n".join(["ERA,MIDAS1.16,1789720595,pertick-fills"] + rows) + "\n")
    return str(p)


# --- watchdog: a live position blocks the restart gate ---------------------------

def test_dangling_lopen_is_not_flat(tmp_path: Path) -> None:
    h = wd.ledger_health(_write(tmp_path, LOPEN_DANGLING), NOW)
    assert h["exists"] and not h["flat"]
    assert h["open_positions"] and h["open_positions"][0]["ticket"] == "2048845860"


def test_lclose_returns_the_book_to_flat(tmp_path: Path) -> None:
    h = wd.ledger_health(_write(tmp_path, LOPEN_CLOSED), NOW)
    assert h["flat"] and h["closed"] == 1


def test_live_position_blocks_restart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wd, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(wd, "LAST_PATH", str(tmp_path / "l.json"))
    ledger = _write(tmp_path, LOPEN_DANGLING)
    stamp = NOW - (wd.STALE_MIN + wd.GRACE_MIN + 1) * 60
    import os
    os.utime(ledger, (stamp, stamp))
    h = wd.ledger_health(ledger, NOW)
    action, problems, _ = wd.decide(h, wd.load_state(), NOW)
    assert action == "SKIP-OPEN-POSITION"
    assert any("stale ledger" in p for p in problems)


def test_force_overrides_the_live_position_guard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wd, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(wd, "LAST_PATH", str(tmp_path / "l.json"))
    ledger = _write(tmp_path, LOPEN_DANGLING)
    stamp = NOW - (wd.STALE_MIN + wd.GRACE_MIN + 1) * 60
    import os
    os.utime(ledger, (stamp, stamp))
    h = wd.ledger_health(ledger, NOW)
    action, _, _ = wd.decide(h, wd.load_state(), NOW, force=True)
    assert action == "RESTUP"


# --- morning_status: live grammar accounting --------------------------------------

def test_parse_ledger_pairs_lclose_but_not_in_paper_closed(tmp_path: Path) -> None:
    res = ms.parse_ledger(_write(tmp_path, LOPEN_CLOSED))
    assert res["closed"] == []          # LCLOSE never fabricates a paper trade
    assert res["veq_last"] == 50.00
    assert res["problems"] == []


def test_parse_ledger_dangling_lopen_survives(tmp_path: Path) -> None:
    res = ms.parse_ledger(_write(tmp_path, LOPEN_DANGLING))
    # one dangling LOPEN is the normal in-position state, not corruption
    assert res["problems"] == []


def test_live_grammar_view_open_position(tmp_path: Path) -> None:
    v = ms.live_grammar_view(_write(tmp_path, LOPEN_DANGLING))
    assert len(v["open"]) == 1
    o = v["open"][0]
    assert o["posid"] == "2048845860" and o["dir"] == 1
    assert o["entry"] == 4389.07500 and o["vol"] == 0.10
    assert v["lclose_ct"] == 0


def test_parity_harness_flatness_sees_the_live_row(tmp_path: Path) -> None:
    """The cert session's flat gate (v28_sweep_runner.ledger_flatness) must
    refuse a terminal stop while LV holds a real position — the 2026-09-18
    pre-cert fix: the harness had NO LIVE-grammar awareness at all."""
    import v28_sweep_runner as R  # noqa: E402
    res = R.ledger_flatness(_write(tmp_path, LOPEN_DANGLING))
    assert not res["flat"]
    assert res["open_positions"] and res["open_positions"][0]["ticket"] == "2048845860"
    res2 = R.ledger_flatness(_write(tmp_path, LOPEN_CLOSED))
    assert res2["flat"] and res2["closed"] == 1


def test_live_grammar_view_closes_and_reasons(tmp_path: Path) -> None:
    rows = LOPEN_CLOSED + [
        "LOPEN,1789720000,2048845861,987654322,2048845861,-1,4360.00000,"
        "4389.00000,4330.00000,0.10,3.10,31.00000,43200,LV",
        "LCLOSE,1789723600,2048845861,TP,4329.90,2.00",
    ]
    v = ms.live_grammar_view(_write(tmp_path, rows))
    assert v["lclose_ct"] == 2
    assert v["reasons"] == ["TIMEOUT", "TP"]


def test_live_grammar_view_corrupt_row_fails_closed(tmp_path: Path) -> None:
    bad = _write(tmp_path, ["LOPEN,not-an-epoch,x,y,x,1,1,1,1,0.1,1,1,1,LV"])
    v = ms.live_grammar_view(bad)
    assert v["problems"] and "corrupt row" in v["problems"][0]


# --- §14 banner attribution: exec-aware matching, no phantom drift ----------------

BANNER_LIVE = ("PR\t0\t09:36:35.210\tMidastouchAI (XAUUSDmicro,M15)\t"
               "[MIDAS1.16]MIDASTOUCH started | mode=0 | symbol=XAUUSDmicro (GOLD-OK) | "
               "session=06-20 UTC | execution=LIVE | exec-model=PERTICK")
BANNER_PAPER_M1 = ("PR\t0\t09:36:35.210\tMidastouchAI (XAUUSDmicro,M15)\t"
                   "[MIDAS1.10]MIDASTOUCH started | mode=0 | symbol=XAUUSDmicro (GOLD-OK) | "
                   "session=06-20 UTC | execution=PAPER | exec-model=PERTICK")
BANNER_PAPER_M1T = BANNER_PAPER_M1.replace("mode=0", "mode=2")
BANNER_LIVE_DRIFTED = BANNER_LIVE.replace("session=06-20", "session=12-16")


def _pins_for(arm: str) -> dict:
    return wd._parse_preset_pins(wd.preset_for_tag(arm))


def test_chart_identity_adjudicates_the_real_drift_class(tmp_path: Path) -> None:
    """§14 chart-identity architecture (2026-09-18): the real drift class —
    a chart value that differs from the arm's own pinned preset (the 09:57
    session flip) — is adjudicated by the chart <inputs> block, the same
    byte-exact source morning status [3b] verifies. Banner text plays no
    part: five charts print identical banner text, so it cannot attribute."""
    from morning_status import preset_identity
    chart = tmp_path / "chart05.chr"
    chart.write_bytes(("<chart>\nsymbol=XAUUSDmicro\n<expert>\nname=MidastouchAI\n"
                       "<inputs>\nInpSessionStartHour=12\n</inputs>\n</expert>").encode("utf-16"))
    txt = open(chart, encoding="utf-16", errors="replace").read()
    ident = preset_identity(txt, wd.preset_for_tag("LV"))
    assert ident["verdict"] == "DRIFT"
    assert any(k == "InpSessionStartHour" for k, _got, _want in ident["drift"]), \
        ident["drift"]


# --- the preset contract, both directions -----------------------------------------

@pytest.mark.parametrize("arm,live", [
    ("M1", False), ("M1t", False), ("M1s", False), ("M1m", False), ("LV", True),
])
def test_execution_switch_by_preset(arm: str, live: bool) -> None:
    vals = {}
    for line in (REPO / "mql5" / "MIDASTOUCH" / f"MidastouchAI_{arm}_gold.set").read_text().splitlines():
        s = line.strip()
        if s and not s.startswith(";") and "=" in s:
            k, v = s.split("=", 1)
            vals[k.strip()] = v.strip()
    assert vals["InpLiveExecution"] == ("true" if live else "false"), arm


def test_live_preset_is_dedicated_and_certified_shape() -> None:
    vals = {}
    for line in (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI_LV_gold.set").read_text().splitlines():
        s = line.strip()
        if s and not s.startswith(";") and "=" in s:
            k, v = s.split("=", 1)
            vals[k.strip()] = v.strip()
    assert vals["InpMagic"] == "7801601"
    assert vals["InpArmTag"] == "LV"
    assert vals["InpMode"] == "0" and vals["InpBarModel"] == "false"
    assert vals["InpRiskPercent"] == "1.0" and vals["InpMaxRiskPct"] == "15.0"
    assert vals["InpSessionStartHour"] == "6" and vals["InpSessionEndHour"] == "20"
    # 2026-09-18 review amendment: LIVE breaker is 15% (a 3% paper default
    # would let one min-lot stop-out stand the live arm down for the UTC day);
    # the paper arms keep 3.0 (asserted below).
    assert vals["InpDailyLossCapPct"] == "15.0" and vals["InpFridayFlatHour"] == "20"
    # 2026-09-18 trigger-frequency amendment, CORRECTED adjudication 18:05 UTC.
    # First pass ranked configs by per-trade expectancy and shipped k=3.0/75-25;
    # re-adjudication on TOTAL OOS RETURN flipped the verdict: k=1.0/75-25
    # ORIGINAL — 152 OOS trades, +21.4R total, pf 1.287 OOS / 1.311 fresh-broker
    # (edge holds on BOTH independent corpora), ~1 fill/day, OOS dd 7.5R.
    # k=3.0/75-25: highest per-trade quality (pf 7.2 OOS) but only +7.3R total
    # and ~1 fill/18d — total-return inferior. M1 keeps the frozen §13
    # baseline 2.0/70-30 as the paper control — the divergence is the
    # amendment, not drift.
    assert vals["InpBBDev"] == "1.0"
    assert vals["InpRSIUpper"] == "75.0" and vals["InpRSILower"] == "25.0"
    # every strategy/gate value equals the M1 paper arm's (single-strategy law)
    m1 = {}
    for line in (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI_M1_gold.set").read_text().splitlines():
        s = line.strip()
        if s and not s.startswith(";") and "=" in s:
            k, v = s.split("=", 1)
            m1[k.strip()] = v.strip()
    for k in ("InpMode", "InpTpMult", "InpTimeoutMinutes", "InpSlAtrMult",
              "InpSessionStartHour", "InpSessionEndHour", "InpRiskPercent",
              "InpMaxRiskPct"):
        assert vals[k] == m1[k], k
    # the one deliberate divergence (live-arm breaker amendment):
    assert vals["InpDailyLossCapPct"] != m1["InpDailyLossCapPct"]
    # ...and the trigger-frequency amendment (M1 keeps the frozen §13 baseline
    # 2.0/70-30 as paper control; LV runs the corrected winner 1.0/75-25):
    assert m1["InpBBDev"] == "2.0"
    assert m1["InpRSIUpper"] == "70.0" and m1["InpRSILower"] == "30.0"
    assert m1["InpDailyLossCapPct"] == "3.0"   # paper arms stay certified
    for arm in ("M1t", "M1s", "M1m"):
        t = (REPO / "mql5" / "MIDASTOUCH" / f"MidastouchAI_{arm}_gold.set").read_text()
        assert "InpDailyLossCapPct=3.0" in t, arm
