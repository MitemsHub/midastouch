"""Unit tests for the init-silence canary in scripts/morning_status.py.

The canary guards the loaded-but-dead EA signature (v27 WIP, 2026-09-13/14:
init banner printed, then zero journal/telemetry activity while the arms froze
for ~2 days). These tests pin the semantics with synthetic MQL5/Logs journals
in the exact real line format.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import morning_status as ms  # noqa: E402

NOW = datetime(2026, 9, 14, 23, 50, 0)
EA = "MitemshubAI"


def write_log(tmp_path, lines: list[str], now_local: datetime = NOW) -> str:
    d = os.path.join(tmp_path, "MQL5", "Logs")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{now_local:%Y%m%d}.log")
    with open(p, "w", encoding="utf-16") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return p


def arm(tmp_path, ea: str = EA) -> dict:
    return {"name": "B_tp24", "magic": "7788100", "ea": ea, "dir": str(tmp_path),
            "files_dir": str(tmp_path), "telem_age": None, "ledger_path": ""}


def banner(ts: str, ea: str = EA) -> str:
    return f"PR\t0\t{ts}\t{ea} (Volatility 75 Index,M15)\t[v26.35] MITEMSHUB AI v26.35 started | Volatility-Only"


def barline(ts: str, ea: str = EA) -> str:
    return f"AB\t0\t{ts}\t{ea} (Volatility 75 Index,M15)\t[v26.35] Bar open: signal=NONE"


def other_ea_line(ts: str) -> str:
    return f"IR\t0\t{ts}\tV75MacroEngine (Volatility 75 Index,M30)\tv2.21 initialized (LONG-ONLY, 2h timeout, PAPER)"


def test_alert_banner_then_silence(tmp_path):
    """The exact 09-13 failure: banner, then nothing for hours -> alert."""
    write_log(tmp_path, [banner("20:00:00.000")])
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "alert"
    assert "NO journal processing" in r["msg"]


def test_ok_telemetry_after_banner_when_journal_silent(tmp_path):
    """2026-09-15 amendment: with 24/7 collection a quiet bar journals nothing;
    a telemetry write AFTER the banner is liveness evidence (heartbeats write
    every bar even when the journal channel is silent)."""
    write_log(tmp_path, [banner("20:00:00.000")])
    telem = os.path.join(tmp_path, "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl")
    with open(telem, "w") as f:
        f.write('{"k": "hb"}\n')
    after = datetime(2026, 9, 14, 23, 45).timestamp()
    os.utime(telem, (after, after))
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "ok"
    assert "telemetry written after init" in r["msg"]


def test_alert_telemetry_only_before_banner(tmp_path):
    """Telemetry written BEFORE the banner proves nothing about the current
    process - banner + silence + stale telemetry is still the corpse."""
    write_log(tmp_path, [banner("20:00:00.000")])
    telem = os.path.join(tmp_path, "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl")
    with open(telem, "w") as f:
        f.write('{"k": "hb"}\n')
    before = datetime(2026, 9, 14, 19, 0).timestamp()
    os.utime(telem, (before, before))
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "alert"


def test_wlost_alerts_scans_today_journal(tmp_path):
    """v26.36/v2.23 writers quarantine a twice-failed append as a WLOST journal
    line - the watchdog must surface it (the row is NOT in the ledger file, so
    parse_ledger can never report it)."""
    write_log(tmp_path, [
        banner("20:00:00.000"),
        f"KK\t0\t20:15:00.000\t{EA} (Volatility 75 Index,M15)\t"
        f"[v26.36] WLOST [CLOSE,] append failed twice err=5004 "
        f"line=CLOSE,1789124400,1789119000,STOP,47003.77000,-1.038,-5.03,37.09",
    ])
    alerts = ms.wlost_alerts(arm(tmp_path), NOW)
    assert len(alerts) == 1
    assert "WLOST" in alerts[0]
    assert "CLOSE,1789124400" in alerts[0]


def test_wlost_alerts_empty_on_clean_journal(tmp_path):
    write_log(tmp_path, [banner("20:00:00.000"), barline("20:15:00.000")])
    assert ms.wlost_alerts(arm(tmp_path), NOW) == []


def test_ok_processing_within_grace(tmp_path):
    write_log(tmp_path, [banner("23:30:06.000"), barline("23:45:10.000")])
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "ok"
    assert "within 16m" in r["msg"]


def test_ok_quiet_period_then_resume(tmp_path):
    """Night init before the session: nothing in-window but later lines prove life."""
    write_log(tmp_path, [banner("20:00:00.000"), barline("21:00:05.000")])
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "ok"
    assert "quiet period" in r["msg"]


def test_armed_inside_grace(tmp_path):
    write_log(tmp_path, [banner("23:49:00.000")])
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "armed"


def test_na_when_no_banner_today(tmp_path):
    write_log(tmp_path, [barline("23:45:10.000")])
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "na"


def test_channel_isolation(tmp_path):
    """Only the arm EA's own channel counts - other EAs' banners/lines must not
    satisfy it (the V75 engine shares the FB9A journal with arm A/C)."""
    write_log(tmp_path, [other_ea_line("20:00:00.000"), banner("22:00:00.000")])
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    # the OTHER EA's line at 20:00 must not count as this EA's processing;
    # banner 22:00 + silence -> alert, proving the other channel was ignored
    assert r["state"] == "alert"


def test_channel_prefix_does_not_overmatch(tmp_path):
    """`MitemshubAI (` must not match `MitemshubAI_v28 (` (sibling research EA)."""
    sibling = f"AB\t0\t23:45:00.000\tMitemshubAI_v28 (Volatility 75 Index,M15)\tv28 bar"
    write_log(tmp_path, [banner("20:00:00.000"), sibling])
    r = ms.init_silence_canary(arm(tmp_path), NOW)
    assert r["state"] == "alert"


def test_v75_grace_is_31m(tmp_path):
    """V75MacroEngine bars M30: a line 20m after init is still inside grace."""
    write_log(tmp_path, [
        f"NO\t0\t22:12:09.000\tV75MacroEngine (Volatility 75 Index,M30)\tv2.21 initialized (LONG-ONLY, 2h timeout, PAPER)",
        f"IR\t0\t22:32:00.000\tV75MacroEngine (Volatility 75 Index,M30)\tMACRO Aligned DOWNTREND",
    ])
    r = ms.init_silence_canary(arm(tmp_path, ea="V75MacroEngine"), NOW)
    assert r["state"] == "ok"


def test_parse_mql5_log_channel_and_message():
    p = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(p, exist_ok=True)
    f = os.path.join(p, "_canary_probe.log")
    with open(f, "w", encoding="utf-16") as fh:
        fh.write("PR\t0\t23:30:06.286\tMitemshubAI (Volatility 75 Index,M15)\t[v26.35] started\r\n")
        fh.write("AB\t0\t23:45:00.000\tV75MacroEngine (Volatility 75 Index,M30)\tMACRO line\r\n")
    rows = ms.parse_mql5_log(f, NOW)
    assert rows[0][1] == "MitemshubAI (Volatility 75 Index,M15)"
    assert rows[0][2] == "[v26.35] started"
    assert rows[1][1] == "V75MacroEngine (Volatility 75 Index,M30)"
    assert rows[0][0] == NOW.replace(hour=23, minute=30, second=6)
    os.remove(f)


# ---------------------------------------------------------------------------
# v26.40 arm-D discovery (InpArmTag → tagged file pair, recorder exclusion)
# ---------------------------------------------------------------------------

def write_chart(tmp_path, ea: str = EA, magic: str = "7788100",
                arm_tag: str | None = None) -> None:
    # terminal_inventory() scans TERM_ROOT/<terminal-hash>/MQL5/Profiles/...,
    # so the fixture mirrors that two-level layout under tmp_path/Term.
    term_root = os.path.join(tmp_path, "Term")
    d = os.path.join(term_root, "FAKEHASH", "MQL5", "Profiles", "Charts", "default")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "chart01.chr")
    tag_line = f"InpArmTag={arm_tag}\r\n" if arm_tag else ""
    with open(p, "w", encoding="utf-16") as f:
        f.write(f"; chart\r\n{ea}\r\nInpMagic={magic}\r\n{tag_line}Volatility 75 Index\r\n")
    return term_root


def test_discovery_finds_arm_d_via_tag(tmp_path, monkeypatch):
    """v26.40: arm D (InpMagic=7788150 + InpArmTag=D on a MitemshubAI chart)
    resolves to the arm-tagged file pair (SymbolTaggedFile suffixes every
    Files output) and is excluded from the tick-recorder canary (arm B owns
    the terminal's shared tick file)."""
    write_chart(tmp_path, magic="7788150", arm_tag="D")
    monkeypatch.setattr(ms, "TERM_ROOT", os.path.join(str(tmp_path), "Term"))
    inv = ms.terminal_inventory()
    assert len(inv) == 1
    t = inv[0]
    assert t["name"] == "D_fwd" and t["tag"] == "D"
    assert t["ledger_path"].endswith("MitemshubAI_paper_Volatility_75_Index_D.csv")
    assert t["has_tick_recorder"] is False


def test_discovery_untagged_arm_b_unchanged(tmp_path, monkeypatch):
    """Regression: the untagged arm-B path must resolve exactly as before."""
    write_chart(tmp_path, magic="7788100")
    monkeypatch.setattr(ms, "TERM_ROOT", os.path.join(str(tmp_path), "Term"))
    inv = ms.terminal_inventory()
    assert len(inv) == 1
    t = inv[0]
    assert t["name"] == "B_tp24" and t["tag"] is None
    assert t["ledger_path"].endswith("MitemshubAI_paper_Volatility_75_Index.csv")
    assert t["has_tick_recorder"] is True


def test_discovery_raises_on_unregistered_tag(tmp_path, monkeypatch):
    """Fail closed: a tagged chart whose EA has no tagged file pair registered
    must abort loudly rather than silently read the wrong ledger."""
    write_chart(tmp_path, ea="V75MacroEngine", magic="7788125", arm_tag="X")
    monkeypatch.setattr(ms, "TERM_ROOT", os.path.join(str(tmp_path), "Term"))
    with pytest.raises(SystemExit):
        ms.terminal_inventory()
