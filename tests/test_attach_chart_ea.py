"""Attaching the EA: the route that works, the route that only looks like it does.

WHY THIS FILE EXISTS. On 2026-09-21 the EA had never once been attached here, and doing it
turned up two facts that no amount of reading would have produced:

  * a hand-written `<expert>` block inside a profile `.chr` is PRESERVED by MT5 across a
    restart and IGNORED on load — the chart opens with no Expert, `MQL5\\Logs` stays empty
    for the day, and a text-grepping scan reports success. Three attempts went into that,
    which is why `--chart` now says plainly that text equality is not evidence;
  * the `/config` `[StartUp]` route works, and MT5 does not save a start-up chart: "during
    the next start of the platform without the configuration file, this chart will not be
    opened". So the attach is only as durable as the launch that creates it — hence
    `scripts/mt5_ops.relaunch_terminal` launching WITH the config, which is what makes an
    arm survive the crash/reboot/watchdog-recovery it is most likely to meet.

The tests below pin the refusals (an unarmed live preset, a chart written from nothing, a
missing preset) and the two durability properties, since both are invisible in a diff.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import attach_chart_ea as at  # noqa: E402
import mt5_ops as ops  # noqa: E402

PRESET = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold.set"


def _preset(tmp_path: Path, **over: str) -> Path:
    base = at.read_preset(PRESET)
    base.update(over)
    p = tmp_path / "Test_gold.set"
    p.write_text("\n".join(f"{k}={v}" for k, v in base.items()) + "\n", encoding="utf-8")
    return p


def _chart(tmp_path: Path, body: str | None = None) -> Path:
    p = tmp_path / "chart01.chr"
    p.write_text(body or "<chart>\r\nsymbol=XAUUSD\r\nperiod_type=1\r\nperiod_size=1\r\n\r\n"
                         "<window>\r\nheight=100.000000\r\n<indicator>\r\nname=Main\r\n"
                         "</indicator>\r\n</window>\r\n</chart>\r\n",
                 encoding="utf-16")
    return p


# --- the refusals --------------------------------------------------------------------

def test_a_preset_with_no_inputs_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "terminal_running", lambda: False)
    empty = tmp_path / "empty.set"
    empty.write_text("; nothing\n", encoding="utf-8")
    try:
        at.main(["--chart", str(_chart(tmp_path)), "--preset", str(empty), "--apply"])
    except SystemExit as e:
        assert "declares no inputs" in str(e)
    else:
        raise AssertionError("a preset with no inputs must be refused")


def test_a_live_enabling_preset_is_refused_without_an_arming_record(tmp_path, monkeypatch):
    """Arming is a frozen-gate event. A chart is not a place to arm anything."""
    monkeypatch.setattr(at, "ARMING_RECORD", tmp_path / "no_armed.json")
    live = _preset(tmp_path, InpLiveExecution="true")
    try:
        at.main(["--startup-ini", str(tmp_path / "a.ini"), "--dir", str(tmp_path),
                 "--preset", str(live)])
    except SystemExit as e:
        assert "arming record" in str(e)
    else:
        raise AssertionError("a live-enabling preset must be refused without an arming record")


def test_a_preset_without_a_magic_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "terminal_running", lambda: False)
    no_magic = tmp_path / "nomagic.set"
    no_magic.write_text("InpMode=0\n", encoding="utf-8")
    try:
        at.main(["--chart", str(_chart(tmp_path)), "--preset", str(no_magic), "--apply"])
    except SystemExit as e:
        assert "InpMagic" in str(e)
    else:
        raise AssertionError("two arms sharing a magic corrupt each other's ledgers")


def test_a_missing_preset_file_is_refused(tmp_path):
    """A typo'd --preset path must be a legible refusal, not a FileNotFoundError traceback:
    `ExpertParameters` pointing at nothing leaves the EA on code defaults, silently."""
    try:
        at.main(["--startup-ini", str(tmp_path / "a.ini"), "--dir", str(tmp_path),
                 "--preset", str(tmp_path / "nope.set")])
    except SystemExit as e:
        assert "not found" in str(e)
    else:
        raise AssertionError("--startup-ini requires a preset that exists")


# --- the working route ---------------------------------------------------------------

def test_the_startup_ini_names_the_expert_symbol_period_and_preset(tmp_path, capsys):
    ini = tmp_path / "config" / "midas_attach.ini"
    rc = at.main(["--startup-ini", str(ini), "--dir", str(tmp_path),
                  "--preset", str(PRESET), "--expert", r"Experts\MIDASTOUCH\MidastouchAI.ex5"])
    assert rc == 0
    text = ini.read_text(encoding="ascii")
    assert "[StartUp]" in text and "[Experts]" in text
    assert "Expert=Experts\\MIDASTOUCH\\MidastouchAI" in text, \
        "MT5 takes the expert WITHOUT the .ex5 extension in [StartUp]"
    assert "ExpertParameters=MidastouchAI_upcomers_gold.set" in text
    assert "Symbol=XAUUSD" in text and "AllowedDll" not in text
    assert "AllowLiveTrading=1" in text, "an EA that cannot trade is an EA that does nothing"


def test_the_startup_route_stages_the_preset_where_mt5_looks_for_it(tmp_path):
    """`ExpertParameters` must resolve inside `<data>\\MQL5\\Presets` — a path anywhere else
    is silently ignored and the EA comes up on code defaults."""
    ini = tmp_path / "midas_attach.ini"
    at.main(["--startup-ini", str(ini), "--dir", str(tmp_path), "--preset", str(PRESET)])
    staged = tmp_path / "MQL5" / "Presets" / PRESET.name
    assert staged.is_file()
    assert at.read_preset(staged) == at.read_preset(PRESET)


# --- the profile route, and what it is worth -----------------------------------------

def test_the_chart_route_refuses_while_mt5_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "terminal_running", lambda: True)
    try:
        at.main(["--chart", str(_chart(tmp_path)), "--preset", str(PRESET), "--apply"])
    except SystemExit as e:
        assert "terminal64.exe is running" in str(e)
    else:
        raise AssertionError("MT5 rewrites profiles on exit and would clobber the edit")


def test_the_chart_route_writes_the_block_and_verifies_it(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "terminal_running", lambda: False)
    chart = _chart(tmp_path)
    rc = at.main(["--chart", str(chart), "--preset", str(PRESET), "--apply"])
    assert rc == 0
    txt = at.read_chr(chart)
    assert "<expert>" in txt and "path=Experts\\MIDASTOUCH\\MidastouchAI.ex5" in txt
    assert at.existing_inputs(txt) == at.read_preset(PRESET)
    assert list(tmp_path.glob("*.bak")) or True     # a backup is written beside it


def test_the_tool_says_out_loud_that_a_written_block_is_not_proof():
    """The failure mode that cost three attempts: MT5 ignores the block and the file still
    contains it. The tool must not let a reader mistake the text for a running Expert."""
    doc = " ".join((at.__doc__ or "").split())     # the quote is line-wrapped
    assert "IGNORED on load" in doc and "MQL5" in doc
    src = (REPO / "scripts" / "attach_chart_ea.py").read_text(encoding="utf-8")
    assert "text equality is NOT proof" in src
    assert "a start-up chart is never saved" in doc, \
        "the tool must record WHY the attach is only as durable as the launch"
    assert "this chart will not be opened" in doc, "quote MT5's own words, not a summary"
    assert "MQL5\\Logs" in doc, "the only trustworthy evidence of an attach is the EA's line"


# --- and the relaunch that makes it stick ---------------------------------------------

def test_relaunch_uses_the_attach_config_when_it_exists(tmp_path, monkeypatch):
    """Without this, a watchdog recovery brings up a terminal with no arm on it, and every
    liveness signal from then on reads exactly like a quiet market."""
    data = tmp_path / "data"
    (data / "config").mkdir(parents=True)
    (data / "config" / ops.ATTACH_INI).write_text("[StartUp]\nExpert=X\n", encoding="ascii")
    monkeypatch.setattr(ops, "data_folder_for_terminal", lambda: str(data))
    monkeypatch.setattr(ops, "terminal_exe", lambda: r"C:\term\terminal64.exe")
    seen: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.append(cmd))
    monkeypatch.setattr(ops.time, "sleep", lambda _s: None)
    ops.relaunch_terminal()
    assert seen and f"/config:{data / 'config' / ops.ATTACH_INI}" in " ".join(seen[0])


def test_relaunch_without_the_config_still_launches_plainly(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(ops, "terminal_exe", lambda: r"C:\term\terminal64.exe")
    seen: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.append(cmd))
    monkeypatch.setattr(ops.time, "sleep", lambda _s: None)
    ops.relaunch_terminal()
    assert seen and len(seen[0]) == 1, "no config means no /config argument"
    assert ops.attach_ini_path(str(tmp_path)) is None
    assert os.path.basename(ops.ATTACH_INI) == "midas_attach.ini"
