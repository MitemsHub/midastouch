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
  * the presets: EVERY one of them is paper-only. The contract asserted here is
    that no file in this repo can arm real orders — the Deriv-era live preset
    that carried execution=true is gone.
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
    # 14 specifiers before v1.19e, 15 now: the state stamp rides as ONE appended specifier
    # that expands to five comma-separated fields at fill time, or to NOTHING when the stamp
    # is off (a tester row) — which is why the row is 14 fields or 19, never 15. The head is
    # unchanged, and `tests/test_state_label_contract.py` pins the stamp's own shape.
    assert len(specs) == 15, specs
    # %s%s (tag + _FLOORED suffix) join into one field: 13 comma fields + prefix
    assert specs[-3:] == ["%s", "%s", "%s"]
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
    p = tmp / "MIDASTOUCH_paper_XAUUSD_LV.csv"
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
    """The cert session's flat gate (mt5_ops.ledger_flatness) must refuse a terminal
    stop while the arm holds a real position — the 2026-09-18 pre-cert fix: the harness
    had NO LIVE-grammar awareness at all. The reader moved to mt5_ops when the V75
    sweep runner was retired; the grammar it must keep honouring did not change."""
    import mt5_ops as R  # noqa: E402
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


def test_the_floor_table_prints_the_risk_it_was_computed_at() -> None:
    """The journal's FLOOR TABLE line names the quantity it divides by.

    MEASURED defect, 2026-09-21. The format read `equity@1%%` while the value was
    `risk_min / InpRiskPercent` — correct only while the configured risk happened to BE
    1.00%. When the arm was re-sized to the measured survivable 0.25%, the line printed
    `equity@1%=$13234`, a label saying 1% beside a number computed at 0.25%: the number was
    right and only the label was wrong, which is the worst kind of diagnostic — a reader
    checks the arithmetic, finds it sound, and keeps the wrong mental model.
    """
    src = (Path(__file__).resolve().parents[1] / "mql5" / "MIDASTOUCH"
           / "MidastouchAI.mq5").read_text(encoding="utf-8", errors="replace")
    # the FLOOR TABLE statement that CARRIES the value (there is an "unavailable" early
    # return with its own FLOOR TABLE literal), and the whole call rather than one literal:
    # the format is split across adjacent literals, so a regex that saw only the first
    # asserted on half the statement
    # the LITERAL, not the word: the explanatory comment beside this code quotes the old
    # label, so a bare `equity@` search lands in a comment and then finds the wrong call
    i = src.index('"equity@')
    call = src[src.rindex("PrintFormat(", 0, i):src.index(");", i) + 2]
    assert "%.2f%%=" in call, f"the percentage must be a printed argument: {call!r}"
    assert "equity@1%" not in call and "equity@1%%" not in call, call
    assert "InpRiskPercent" in call, (
        "the printed percentage must be the configured risk the value was computed at")


# --- §14 banner attribution: exec-aware matching, no phantom drift ----------------

BANNER_LIVE = ("PR\t0\t09:36:35.210\tMidastouchAI (XAUUSD,M15)\t"
               "[MIDAS1.16]MIDASTOUCH started | mode=0 | symbol=XAUUSD (GOLD-OK) | "
               "session=06-20 UTC | execution=LIVE | exec-model=PERTICK")
BANNER_PAPER_M1 = ("PR\t0\t09:36:35.210\tMidastouchAI (XAUUSD,M15)\t"
                   "[MIDAS1.10]MIDASTOUCH started | mode=0 | symbol=XAUUSD (GOLD-OK) | "
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
    chart.write_bytes(("<chart>\nsymbol=XAUUSD\n<expert>\nname=MidastouchAI\n"
                       "<inputs>\nInpSessionStartHour=12\n</inputs>\n</expert>").encode("utf-16"))
    txt = open(chart, encoding="utf-16", errors="replace").read()
    ident = preset_identity(txt, wd.preset_for_tag("upcomers"))
    assert ident["verdict"] == "DRIFT"
    assert any(k == "InpSessionStartHour" for k, _got, _want in ident["drift"]), \
        ident["drift"]


# --- the preset contract, both directions -----------------------------------------

# --- the preset contract, both directions -----------------------------------------


def _preset_vals(name: str) -> dict[str, str]:
    """A .set as key -> value, comments and blanks skipped.

    A REPEATED key raises: MT5's behaviour on a duplicate is unspecified, so a file
    that declares one twice cannot be read as a statement of what it configures. This
    repo has already produced one such file by accident.
    """
    vals: dict[str, str] = {}
    for line in (REPO / "mql5" / "MIDASTOUCH" / name).read_text().splitlines():
        s = line.strip()
        if not s or s.startswith(";") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip()
        if k in vals:
            raise AssertionError(f"{name} declares {k} twice: {vals[k]!r} then {v!r}")
        vals[k] = v
    return vals


def _presets_on_disk() -> list[str]:
    """Every gold preset in the tree, enumerated rather than hand-listed.

    The hand list this replaces named the arm portfolio (M1/M1t/M1s/M1m/LV) and went
    red the day those files were retired — it pinned the era, not the contract. An
    enumeration cannot be outgrown: a preset added later is checked without anyone
    remembering to add it here.
    """
    found = (REPO / "mql5" / "MIDASTOUCH").glob("MidastouchAI_*_gold.set")
    return sorted(p.name[len("MidastouchAI_"):-len("_gold.set")] for p in found)


# 2026-09-20: no preset in this repo may arm real orders. The LV arm was the last one
# carrying true (a live arm on a Deriv account that no longer exists); on the funded
# Upcomers account that is a loaded switch, not a record. Arming is a frozen-gate event
# driven by an arming record, never by a preset default.
@pytest.mark.parametrize("arm", _presets_on_disk())
def test_execution_switch_by_preset(arm: str) -> None:
    vals = _preset_vals(f"MidastouchAI_{arm}_gold.set")
    assert vals["InpLiveExecution"] == "false", arm


#: The certified strategy values. None of these changed when the venue changed —
#: trading is the same work, and this is the set the pre-registered studies fitted.
CERTIFIED_STRATEGY = {
    "InpMode": "0", "InpMacroEmaPeriod": "20", "InpBBPeriod": "20",
    "InpBBDev": "2.0", "InpRSIPeriod": "14", "InpRSIUpper": "70.0",
    "InpRSILower": "30.0", "InpAtrPeriod": "14", "InpSlAtrMult": "2.0",
    "InpTpMult": "2.0", "InpTimeoutMinutes": "720",
    "InpSessionStartHour": "6", "InpSessionEndHour": "20",
    "InpSpreadCapPctStop": "1.5", "InpEntryTF": "15", "InpBarModel": "false",
    "InpStaleMinutes": "30", "InpFridayFlatHour": "20",
    "InpDailyLossCapPct": "3.0", "InpUseNewsFilter": "false",
}


@pytest.mark.parametrize("arm", _presets_on_disk())
def test_every_preset_runs_the_certified_strategy(arm: str) -> None:
    """Identity and account size may vary per preset; the strategy may not.

    Asserted against a literal rather than against the other preset: two files that
    drifted together would agree with each other while both being wrong.
    """
    vals = _preset_vals(f"MidastouchAI_{arm}_gold.set")
    for k, v in CERTIFIED_STRATEGY.items():
        assert vals.get(k) == v, f"{arm}: {k}={vals.get(k)!r}, certified {v!r}"


def test_live_preset_is_dedicated_and_certified_shape() -> None:
    """The preset that would run the funded account, asserted key by key.

    Repointed 2026-09-20 from the closed Deriv-era live preset
    (`MidastouchAI_LV_gold`, magic 7801601, a $1,000 Deriv account) to the Upcomers
    paper mirror. What is certified here is what must hold before arming is even
    contemplated: one dedicated magic per era, the frozen strategy, the venue's four
    numbers, and live execution hard off.
    """
    vals = _preset_vals("MidastouchAI_upcomers_gold.set")
    # identity: a magic distinct from the Deriv-era 7801001, so no ledger can mix the
    # two eras' fills, and an arm tag naming the account this mirrors
    assert vals["InpMagic"] == "7825001" and vals["InpArmTag"] == "U25"
    # the venue's four numbers — mirrored by
    # src/midas_prop/risk/upcomers_rules.py, enforced in the EA's
    # PropGovernorBlock()
    assert vals["InpPropGuard"] == "true"
    assert vals["InpPropAccountSize"] == "25000.0"
    assert vals["InpPropTargetPct"] == "5.0"
    assert vals["InpPropMaxDdPct"] == "6.0"
    assert vals["InpPropBestDayPct"] == "20.0"
    # the daily breaker is the venue's 3.0, not the Deriv-era live preset's 15.0 (that
    # 15.0 existed because a min-lot stop-out on a $1,000 account would have stood the
    # arm down for the day; on this account 3% is the rule that applies)
    assert vals["InpDailyLossCapPct"] == "3.0"
    # the paper mirror is sized for the account it mirrors: the Deriv-era $50 equity
    # understated every lot by ~500x and would have made the only forward record we
    # have unrepresentative of the account it represents
    assert vals["InpPaperEquity"] == "25000.0"
    # ...and sized to a MEASURED survivable size, not to the EA's 1.00 default. 1.00%
    # breaches the venue's 3% daily line on 13 of 30 simulated days (worst -$804.84
    # against $750); 0.25% breaches on none (worst -$466.60, $283.40 of headroom). The
    # table is in scripts/gold_preset_upcomers.py (RISK_PERCENT) and the scan is in
    # artifacts/gold_prereg_no_target.json; this pin is what forces a future re-size to
    # be a DECISION with a comment rather than an edit.
    assert vals["InpRiskPercent"] == "0.25"
    assert vals["InpLiveExecution"] == "false"
