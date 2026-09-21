"""Offline tests for the MIDASTOUCH gold-arm watchdog.

These pin the discipline that must never silently drift: the heartbeat
staleness tiers (fresh / grace / stale), the flat-check gate before any
terminal restart (mirrors v28_sweep_runner — the EA would adopt a dangling
OPEN as a live virtual position), weekend and escalation guards, fail-closed
ledger parsing, chart discovery, and the morning-status summary contract.
Nothing here touches a real terminal: process calls and paths are faked.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_watchdog as wd  # noqa: E402


# --- fixtures -------------------------------------------------------------------

# Decisions read only (now - mtime), so the fixture stamps mtimes RELATIVE TO
# THIS CONSTANT — not to time.time() at test runtime. In a 100+ suite session
# these tests execute minutes after module import; anchoring stamps to the
# same NOW that decide() receives keeps every mtime age exact regardless of
# collection-to-execution latency (learned 2026-09-18: garch's 60 s ahead of
# this suite pushed a 45-min stamp into the 44-min grace band → phantom WAIT).
# Pinned, not time.time(). The watchdog's weekend branch is a function of the LOCAL
# weekday of the instant it is handed, and this file handed it "now" — so the whole
# suite went red every Saturday and Sunday, because WAIT-WEEKEND short-circuits
# before every assertion below it. A suite that only passes on weekdays teaches the
# reader to ignore red. Friday 2026-09-18 12:00 UTC; the weekend branch keeps its own
# test (test_flat_weekend_stale_is_wait_weekend), which forces the weekday explicitly.
NOW = 1789713600.0


def _ledger(tmp: Path, rows: list[str], mtime_age_min: float = 1.0,
            name: str = "MIDASTOUCH_paper_XAUUSD_M1.csv") -> str:
    """Write a paper ledger and age it to `mtime_age_min` before NOW.

    `name` exists because a portfolio fixture used to write every arm to the default
    file name and then `os.replace` it onto the per-arm name — which, for the arm whose
    tag IS "M1", meant replacing a path with itself and leaving no ledger behind.
    """
    p = tmp / name
    p.write_text("\n".join(rows) + "\n")
    stamp = NOW - mtime_age_min * 60
    os.utime(p, (stamp, stamp))
    return str(p)


FLAT = [
    "ERA,MIDAS1.10,1789599864,pertick-fills",
    "EQ,50.00",
    "OPEN,1789500000,111,1,4300.0,4240.0,4360.0,0.10,5.87,58.71,720,M1",
    "CLOSE,1789500600,111,TP,4360.0,2.05,10.25,60.25",
    "EQ,60.25",
]
DANGLING = FLAT[:3]  # OPEN with no CLOSE


@pytest.fixture()
def fresh_state(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(wd, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(wd, "LAST_PATH", str(tmp_path / "last.json"))
    # the VPS-era marker is an OPERATOR artifact — tests NEVER touch the real
    # file; the two VPS-era tests point VPS_HOSTING_MARKER at a tmp copy
    monkeypatch.setattr(wd, "VPS_HOSTING_MARKER", str(tmp_path / "no_vps_marker"))
    # ...and so is the pause marker. It was read from the repo, so a parity or tester
    # session in progress — which is a NORMAL state on this machine, and the whole point
    # of the marker — made 7 of these tests fail with "pause marker present, observing
    # only". Red during every live session is red that gets ignored, and it hid the one
    # thing this suite exists to assert: what the watchdog does when nothing is paused.
    # test_pause_marker_blocks_action still overrides this with its own tmp marker.
    monkeypatch.setattr(wd, "PAUSE_MARKER", str(tmp_path / "no_pause_marker"))
    return tmp_path / "state.json"


# --- staleness tiers --------------------------------------------------------------

def test_fresh_ledger_is_none_and_resets_counter(fresh_state) -> None:
    wd.save_state({"consecutive_restups": 2, "restups_total": 2})
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)), FLAT,
                                 mtime_age_min=5), NOW)
    action, problems, ns = wd.decide(h, wd.load_state(), NOW)
    assert action == "NONE"
    assert ns["consecutive_restups"] == 0
    assert any("RECOVERED" in p for p in problems)


def test_within_grace_waits(fresh_state) -> None:
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)), FLAT,
                                 mtime_age_min=wd.STALE_MIN + 5), NOW)
    action, _, _ = wd.decide(h, wd.load_state(), NOW)
    assert action == "WAIT"


def test_beyond_grace_is_restup(fresh_state) -> None:
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)), FLAT,
                                 mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1), NOW)
    action, _, ns = wd.decide(h, wd.load_state(), NOW)
    assert action == "RESTUP"
    assert ns["consecutive_restups"] == 1 and ns["restups_total"] == 1


# --- the flat-check gate -----------------------------------------------------------

def test_dangling_open_blocks_restart(fresh_state) -> None:
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)), DANGLING,
                                 mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1), NOW)
    action, problems, _ = wd.decide(h, wd.load_state(), NOW)
    assert action == "SKIP-OPEN-POSITION"
    assert any("open paper position" in p for p in problems)


def test_force_overrides_the_open_position_guard(fresh_state) -> None:
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)), DANGLING,
                                 mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1), NOW)
    action, _, _ = wd.decide(h, wd.load_state(), NOW, force=True)
    assert action == "RESTUP"


# --- fail-closed parsing ------------------------------------------------------------

def test_unreadable_ledger_is_a_problem_not_flat(fresh_state) -> None:
    h = wd.ledger_health(str(Path(str(fresh_state.parent)) / "missing.csv"), NOW)
    assert h["exists"] is False and h["flat"] is False and h["problems"]
    action, problems, _ = wd.decide(h, wd.load_state(), NOW)
    assert action == "NONE"          # never restart on an unreadable book
    assert any("never initialized" in p for p in problems)


def test_rowless_ledger_fails_closed(fresh_state) -> None:
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)),
                                 ["junk,line,here"], mtime_age_min=1), NOW)
    assert h["flat"] is False and any("no recognizable" in p for p in h["problems"])


def test_midscan_oserror_fail_closed(fresh_state, monkeypatch) -> None:
    p = _ledger(Path(str(fresh_state.parent)), FLAT)
    real_open = open

    def boom(*a, **k):
        raise OSError("locked")

    monkeypatch.setattr("builtins.open", boom)
    h = wd.ledger_health(p, NOW)
    monkeypatch.setattr("builtins.open", real_open)
    assert h["flat"] is False and any("unreadable" in x for x in h["problems"])


# --- weekend + escalation guards ----------------------------------------------------

def test_flat_weekend_stale_is_wait_weekend(fresh_state, monkeypatch) -> None:
    import datetime as _dt
    real = _dt.datetime

    class FakeDT(real):
        @classmethod
        def fromtimestamp(cls, t, tz=None):  # force local Saturday
            d = real.fromtimestamp(t, tz)
            days_to_sat = (5 - d.weekday()) % 7
            return d + __import__("datetime").timedelta(days=days_to_sat)

    monkeypatch.setattr(wd, "datetime", FakeDT)
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)), FLAT,
                                 mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1), NOW)
    action, _, _ = wd.decide(h, wd.load_state(), NOW)
    assert action == "WAIT-WEEKEND"


def test_escalation_after_max_consecutive_restups(fresh_state) -> None:
    wd.save_state({"consecutive_restups": wd.MAX_RESTUPS, "restups_total": 3})
    h = wd.ledger_health(_ledger(Path(str(fresh_state.parent)), FLAT,
                                 mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1), NOW)
    action, problems, ns = wd.decide(h, wd.load_state(), NOW)
    assert action == "ESCALATE" and ns["consecutive_restups"] == wd.MAX_RESTUPS
    assert any("restart" in p.lower() for p in problems)


# --- discovery ----------------------------------------------------------------------

def test_midas_arm_finds_chart_and_tagged_ledger(tmp_path: Path) -> None:
    prof = tmp_path / "MQL5" / "Profiles" / "Charts" / "Default"
    prof.mkdir(parents=True)
    (prof / "chart01.chr").write_bytes(
        ("<chart>\nsymbol=XAUUSD\n<expert>\nname=MidastouchAI\n"
         "InpArmTag=M1\n</expert>").encode("utf-16"))
    (tmp_path / "MQL5" / "Files").mkdir(parents=True)
    arm = wd.midas_arm(str(tmp_path))
    assert arm and arm["symbol"] == "XAUUSD" and arm["tag"] == "M1"
    assert arm["ledger"].endswith("MIDASTOUCH_paper_XAUUSD_M1.csv")


def test_midas_arm_none_without_chart(tmp_path: Path) -> None:
    assert wd.midas_arm(str(tmp_path)) is None and wd.midas_arm(None) is None


# --- pause + morning-status contract --------------------------------------------------

def test_pause_marker_blocks_action(fresh_state, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd, "PAUSE_MARKER", str(tmp_path / "paused"))
    Path(wd.PAUSE_MARKER).write_text("x")
    rec = wd.check(now_s=NOW)
    assert rec["action"] == "PAUSED"


def test_watchdog_summary_contract(fresh_state) -> None:
    assert "never run" in wd.watchdog_summary()[0]
    wd.save_state({"consecutive_restups": wd.MAX_RESTUPS, "restups_total": 5})
    line, bad = wd.watchdog_summary()
    assert bad is True and "3 consecutive" in line


def test_check_full_restup_flow(fresh_state, monkeypatch, tmp_path: Path) -> None:
    """End-to-end: stale flat ledger -> RESTUP decision executed via faked procs."""
    calls: list[str] = []
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(wd, "midas_arms", lambda df: [{
        "chart": "chart01.chr", "symbol": "XAUUSD", "tag": "M1",
        "ledger": _ledger(Path(str(fresh_state.parent)), FLAT,
                          mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1)}])
    monkeypatch.setattr(wd, "terminal_pids_exact", lambda: [4242])
    monkeypatch.setattr(wd, "stop_terminal", lambda pids: calls.append("stop") or True)
    monkeypatch.setattr(wd, "relaunch_terminal", lambda: calls.append("relaunch"))
    monkeypatch.setattr(wd, "recent_banners", lambda df: [])   # no banner: no drift path
    rec = wd.check(now_s=NOW)
    assert rec["action"] == "RESTUP" and rec["relaunched"] is True
    assert calls == ["stop", "relaunch"]


# --- banner text is observation only; the CHART is the identity source --------

BANNER_OK = ("JQ\t0\t09:57:31.594\tMidastouchAI (XAUUSD,M15)\t"
             "[MIDAS1.10]MIDASTOUCH started | mode=0 | symbol=XAUUSD (GOLD-OK) | "
             "macro=H4+H1 EMA20 | trigger=M15 BB(20,2.0)/RSI(14) | SL=2.0xATR(H1) TP=2.0R "
             "timeout=720min | session=06-20 UTC | spreadcap=1.5%stop | risk=1.00% | "
             "execution=PAPER | exec-model=PERTICK | NEWS-FILTER=OFF (calendar pending)")
BANNER_DRIFT = BANNER_OK.replace("mode=0", "mode=1")
BANNER_LIVE = BANNER_OK.replace("execution=PAPER", "execution=LIVE")


def test_banner_matchers_are_gone() -> None:
    """§14 hardening: banner-text drift matching was REMOVED, not patched.

    Five charts print identical `mode=… | session=…` banner text with no arm
    tag, so no matcher can attribute a boot to an arm — the 09:05 phantom
    ESCALATE was exactly that (LV's matcher grabbed a paper arm's PAPER
    banner). Config identity is adjudicated exclusively by the chart's
    <inputs> block (below); the banner stays observation.
    """
    assert not hasattr(wd, "banner_drift"), (
        "banner_drift must stay removed — banner text cannot be attributed "
        "across five identically-labelled charts")
    assert not hasattr(wd, "banners_for_pins")


def test_ambiguous_banner_cannot_manufacture_drift(fresh_state, monkeypatch,
                                                   tmp_path: Path) -> None:
    """The 09:05 incident class, pinned end-to-end: a LIVE banner on disk
    while the PAPER arm's chart is byte-identical to its pins must produce
    ZERO drift — banners are unattributable, the chart decides."""
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    chr_p = tmp_path / "chart01.chr"
    chr_p.write_bytes(("<chart>\nsymbol=XAUUSD\n<expert>\nname=MidastouchAI\n"
                       "<inputs>\nInpMode=0\n</inputs>\n</expert>").encode("utf-16"))
    arm = {"chart": str(chr_p), "symbol": "XAUUSD", "tag": "M1",
           "ledger": _ledger(Path(str(fresh_state.parent)), FLAT, mtime_age_min=2)}
    assert wd.resplice_pins(arm), "fixture chart must be respliceable to its pins"
    monkeypatch.setattr(wd, "midas_arms", lambda df: [arm])
    monkeypatch.setattr(wd, "recent_banners", lambda df: [BANNER_LIVE])
    monkeypatch.setattr(wd, "terminal_pids_exact", lambda: [])
    rec = wd.check(now_s=NOW)
    assert rec.get("drift") is None and rec["action"] != "DRIFT", (
        "an unattributable banner must never manufacture chart drift")


def test_drift_action_remediates_with_resplice(fresh_state, monkeypatch, tmp_path: Path) -> None:
    """Drift with a fresh heartbeat -> DRIFT action, stop+resplice+relaunch."""
    calls: list[str] = []
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(wd, "midas_arms", lambda df: [{
        "chart": str(tmp_path / "chart01.chr"), "symbol": "XAUUSD", "tag": "M1",
        "ledger": _ledger(Path(str(fresh_state.parent)), FLAT, mtime_age_min=2)}])
    # a real chart file with an inputs block so resplice has something to edit
    chr_p = tmp_path / "chart01.chr"
    chr_p.write_bytes(("<chart>\nsymbol=XAUUSD\n<expert>\nname=MidastouchAI\n"
                       "<inputs>\nInpMode=1\nInpSessionStartHour=12\n</inputs>\n"
                       "</expert>").encode("utf-16"))
    monkeypatch.setattr(wd, "terminal_pids_exact", lambda: [4242])
    monkeypatch.setattr(wd, "stop_terminal", lambda pids: calls.append("stop") or True)
    monkeypatch.setattr(wd, "relaunch_terminal", lambda: calls.append("relaunch"))
    # §14 chart-identity attribution (2026-09-18): the drift that survives is
    # whatever the CHART says vs the pins — the fixture chart carries
    # InpMode=1 against the pinned 0. Even a simultaneously-present LIVE
    # banner must neither suppress nor redirect it: banners are observation.
    monkeypatch.setattr(wd, "recent_banners", lambda df: [BANNER_LIVE])
    rec = wd.check(now_s=NOW)
    assert rec["action"] == "DRIFT" and rec["relaunched"] is True
    assert calls == ["stop", "relaunch"]
    assert rec["respliced_backup"] and "bak_watchdog_" in rec["respliced_backup"][0]
    # the chart now carries the pins
    txt = open(chr_p, encoding="utf-16", errors="replace").read()
    import re as _re
    got = dict(l.split("=", 1) for l in
               _re.search(r"<inputs>([\s\S]*?)</inputs>", txt).group(1).splitlines() if "=" in l)
    assert got["InpMode"] == "0" and got["InpLiveExecution"] == "false"
    # and the escalation counter moved
    assert wd.load_state()["consecutive_restups"] == 1


def test_vps_hosting_marker_means_observe_only(fresh_state, monkeypatch,
                                               tmp_path: Path) -> None:
    """2026-09-18: with the operator-set VPS-hosting marker present, the
    watchdog OBSERVES and never remediates — local algo is MT5-locked during
    hosting and the LV surface lives on the VPS after the operator's sync;
    a frozen local LV ledger is the era's signature, not a fault."""
    marker = tmp_path / "vps.json"
    marker.write_text("{\"active\": true}\n")
    monkeypatch.setattr(wd, "VPS_HOSTING_MARKER", str(marker))
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(wd, "midas_arms", lambda df: [])
    rec = wd.check(now_s=NOW)
    assert rec["action"] == "VPS-HOSTING"
    assert "VPS" in (rec.get("problem") or "")
    assert wd.load_state().get("consecutive_restups", 0) == 0


def test_vps_hosting_marker_absent_restores_normal_supervision(
        fresh_state, monkeypatch, tmp_path: Path) -> None:
    """Clear the marker -> the watchdog is fully back in command."""
    assert not wd.vps_hosting_active()
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(wd, "midas_arms", lambda df: [])
    rec = wd.check(now_s=NOW)
    assert rec["action"] != "VPS-HOSTING"


def test_pin_check_error_is_observe_only(fresh_state, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(wd, "midas_arms", lambda df: [{
        "chart": "chart01.chr", "symbol": "XAUUSD", "tag": "M1",
        "ledger": _ledger(Path(str(fresh_state.parent)), FLAT, mtime_age_min=2)}])
    # §14: the chart file IS the identity source — unreadable chart means the
    # identity is UNVERIFIABLE, which is observation, never a restart.
    rec = wd.check(now_s=NOW)
    assert rec["action"] == "NONE"          # never restart on a broken pin source
    assert any("chart unreadable" in p and "observing" in p
               for p in rec.get("problems", []))


# --- §14 portfolio (multi-arm) -----------------------------------------------------

def _seed_two_arm_charts(tmp_path: Path) -> None:
    prof = tmp_path / "MQL5" / "Profiles" / "Charts" / "Default"
    prof.mkdir(parents=True, exist_ok=True)
    for i, (tag, mode) in enumerate([("M1", "0"), ("U25", "2")]):
        (prof / f"chart0{i + 1}.chr").write_bytes(
            (f"<chart>\nsymbol=XAUUSD\n<expert>\nname=MidastouchAI\n"
             f"InpArmTag={tag}\n"
             f"<inputs>\nInpMode={mode}\n</inputs>\n</expert>").encode("utf-16"))
    (tmp_path / "MQL5" / "Files").mkdir(parents=True, exist_ok=True)


def test_midas_arms_finds_whole_portfolio(tmp_path: Path) -> None:
    _seed_two_arm_charts(tmp_path)
    arms = wd.midas_arms(str(tmp_path))
    assert [a["tag"] for a in arms] == ["M1", "U25"]
    assert all(a["symbol"] == "XAUUSD" for a in arms)
    assert arms[1]["ledger"].endswith("MIDASTOUCH_paper_XAUUSD_U25.csv")
    assert wd.midas_arm(str(tmp_path))["tag"] == "M1"   # legacy single-arm view


# --- the attach route a VPS runs: the start-up config, which has no .chr -----------------

def _seed_startup_arm(tmp: Path, tag: str = "U25", symbol: str = "XAUUSD",
                      preset_body: str = "InpMode=0\nInpLiveExecution=false\n") -> str:
    """A terminal whose arm exists ONLY as a `/config` [StartUp] attach.

    This is the measured live configuration (2026-09-21): MT5 does not save a start-up chart,
    so there is no `.chr` anywhere in this directory, exactly as on the real install.
    """
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "MQL5" / "Presets").mkdir(parents=True, exist_ok=True)
    (tmp / "MQL5" / "Files").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "midas_attach.ini").write_text(
        "[StartUp]\nSymbol=XAUUSD\nPeriod=H1\nExpert=MIDASTOUCH\\MidastouchAI\n"
        "ExpertParameters=MidastouchAI_upcomers_gold.set\n", encoding="ascii")
    staged = tmp / "MQL5" / "Presets" / "MidastouchAI_upcomers_gold.set"
    staged.write_text(preset_body, encoding="utf-8")
    led = tmp / "MQL5" / "Files" / f"MIDASTOUCH_paper_{symbol}_{tag}.csv"
    led.write_text("\n".join(FLAT) + "\n", encoding="utf-8")
    return str(led)


def test_a_start_up_attached_arm_is_discovered_with_no_profile_chart(tmp_path: Path) -> None:
    """THE DEFECT, pinned. On the live install this returned NOTHING while the EA was running
    and its ledger advancing, because the arm is attached by the start-up config and MT5 never
    writes a `.chr` for one. The watchdog reported `no MidastouchAI chart found ... is the arm
    attached?` at action NONE — a dead-arm report that reads like a quiet market, which is
    exactly the failure this file exists to prevent. It must now see the arm, its tag from the
    ledger (never assumed) and its symbol from the config.
    """
    led = _seed_startup_arm(tmp_path)
    assert list((tmp_path / "MQL5" / "Profiles").glob("**/*.chr")) == [], (
        "the fixture must have no saved chart, or it does not test the start-up route")
    arms = wd.midas_arms(str(tmp_path))
    assert len(arms) == 1
    assert arms[0]["tag"] == "U25" and arms[0]["symbol"] == "XAUUSD"
    assert arms[0]["chart_kind"] == "startup"
    assert os.path.normcase(arms[0]["ledger"]) == os.path.normcase(led)
    assert wd.midas_arm(str(tmp_path))["tag"] == "U25"      # the single-arm view agrees


def test_the_drift_check_reads_a_start_up_arm_instead_of_throwing(tmp_path: Path) -> None:
    """The pin check must run on the route a VPS uses. Measured live: reading the config path
    as a UTF-16 chart threw `'utf-16' codec can't decode bytes in position 0-1`, which aborted
    the whole drift guard into `pin_check_error — observing, not acting`. A guard that is off on
    exactly the arms that survive a reboot is not a guard.
    """
    _seed_startup_arm(tmp_path, preset_body="InpMode=0\nInpArmTag=U25\n")
    arm = wd.midas_arms(str(tmp_path))[0]
    txt = wd.arm_chart_text(arm)                    # must not raise
    assert "InpMode=0" in txt and "InpArmTag=U25" in txt
    assert txt.startswith("symbol=XAUUSD"), "shaped like a chart body, so the checks are shared"


def test_a_start_up_arm_with_no_staged_preset_reports_defaults_not_health(tmp_path: Path) -> None:
    """Absent staged preset = the EA came up on CODE DEFAULTS under a certified name — the
    silent-preset-loss signature the watchdog found live on 2026-09-17. The shaped body is then
    empty, so preset identity reports every repo pin missing rather than passing quietly.
    """
    _seed_startup_arm(tmp_path)
    (tmp_path / "MQL5" / "Presets" / "MidastouchAI_upcomers_gold.set").unlink()
    arm = wd.midas_arms(str(tmp_path))[0]
    assert arm["startup"]["staged_present"] is False
    txt = wd.arm_chart_text(arm)
    assert "InpMode" not in txt and txt.startswith("symbol=XAUUSD")


def test_resplicing_a_start_up_arm_rewrites_the_staged_preset_it_loads(tmp_path: Path,
                                                                      monkeypatch) -> None:
    """The remedy has to match the route. A start-up arm has no chart to splice: the file the
    EA loads on launch is the staged preset, so that is the file the fix rewrites — from the
    arm's own repo preset, with a backup, verified by re-parse, and refused if the destination
    is missing. Splicing a `<inputs>` block into the config would be a write that changes
    nothing and reports success.
    """
    from pathlib import Path as _P
    repo_preset = _P(wd.REPO) / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold.set"
    # `armed=` is not decoration: the remedy resolves its source by the RECORD (see the
    # armed-resolution test below), so a fake that ignores it would pass while the live
    # path wrote the wrong preset.
    monkeypatch.setattr(wd, "preset_for_tag", lambda tag, **kw: str(repo_preset))
    monkeypatch.setattr(wd, "_armed", lambda: False)
    _seed_startup_arm(tmp_path, preset_body="InpMode=9\nInpArmTag=U25\n")
    arm = wd.midas_arms(str(tmp_path))[0]
    staged = _P(arm["startup"]["staged_preset"])
    assert "InpMode=9" in staged.read_text(encoding="utf-8-sig")
    bak = wd.resplice_pins(arm)
    assert bak and _P(bak).exists(), "a backup is written before the rewrite"
    assert "InpMode=9" in _P(bak).read_text(encoding="utf-8-sig")     # the old bytes survive
    got = staged.read_text(encoding="utf-8-sig")
    assert "InpMode=9" not in got, "the staged preset was not rewritten — the remedy no-ops"
    assert "InpLiveExecution=false" in got, "rewritten FROM the arm's own repo preset"
    # a destination that does not exist is refused, not invented
    staged.unlink()
    assert wd.resplice_pins(arm) is None


def test_the_remedy_resolves_the_armed_pin_not_the_paper_one(tmp_path: Path,
                                                             monkeypatch) -> None:
    """THE LOOP, pinned. Measured on this machine on 2026-09-21: 16:52:20Z the drift check
    reported `[U25] chart InpLiveExecution=false (repo pin true)` — it compares against
    `preset_for_tag(tag, armed=True)` — and the remedy then re-wrote the staged preset from
    `preset_for_tag(tag)` with arming DEFAULTED OFF, i.e. the paper preset (4564 bytes, paper
    header, `InpLiveExecution=false`). The terminal restarted and booted paper, twenty minutes
    later the same drift fired, and the supervisor reverted the operator's authorisation
    forever. Detection against one pin and remediation from another is the defect; the remedy
    must resolve the SAME pin.
    """
    from pathlib import Path as _P
    armed_pin = _P(wd.REPO) / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold_LIVE.set"
    paper_pin = _P(wd.REPO) / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold.set"
    assert "InpLiveExecution=true" in armed_pin.read_text(encoding="utf-8-sig")
    assert "InpLiveExecution=false" in paper_pin.read_text(encoding="utf-8-sig")
    asked: list[bool] = []

    def fake(tag: str, *, armed: bool = False) -> str:
        asked.append(armed)
        return str(armed_pin if armed else paper_pin)

    monkeypatch.setattr(wd, "preset_for_tag", fake)
    monkeypatch.setattr(wd, "_armed", lambda: True)
    _seed_startup_arm(tmp_path, preset_body="InpMode=9\nInpArmTag=U25\n")
    arm = wd.midas_arms(str(tmp_path))[0]
    assert wd.resplice_pins(arm), "the armed arm must still be remediable"
    staged = _P(arm["startup"]["staged_preset"]).read_text(encoding="utf-8-sig")
    assert "InpLiveExecution=true" in staged, (
        "the remedy wrote the paper preset over an ARMED arm — the arm boots paper and the "
        "drift it was remedying is re-detected on the next pass")
    assert asked == [True], f"the remedy must ask for the armed pin: {asked}"
    # ...and with no arming record the behaviour is unchanged (paper, as before)
    monkeypatch.setattr(wd, "_armed", lambda: False)
    _seed_startup_arm(tmp_path, preset_body="InpMode=9\nInpArmTag=U25\n")
    arm = wd.midas_arms(str(tmp_path))[0]
    assert wd.resplice_pins(arm)
    assert "InpLiveExecution=false" in _P(arm["startup"]["staged_preset"]).read_text(
        encoding="utf-8-sig")


def test_drift_remedy_is_handed_the_pin_the_drift_was_detected_against(
        fresh_state, tmp_path: Path, monkeypatch) -> None:
    """End to end through check(): the source used for the identity verdict must be the
    source handed to the remedy, not re-derived behind it. Anything else lets the two
    disagree — which is exactly how an armed arm got re-spliced to the paper preset.
    """
    from pathlib import Path as _P
    import midas_watchdog as _wd
    armed_pin = _P(wd.REPO) / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold_LIVE.set"
    _seed_two_arm_charts(tmp_path)
    for tag in ("M1", "U25"):
        p = tmp_path / "MQL5" / "Files" / f"MIDASTOUCH_paper_XAUUSD_{tag}.csv"
        p.write_text("\n".join(FLAT) + "\n")
        os.utime(p, (NOW, NOW))
    monkeypatch.setattr(_wd, "_armed", lambda: True)
    arms = _wd.midas_arms(str(tmp_path))
    for a in arms:
        assert _wd.resplice_pins(a), "seed charts must be respliceable"
    u25 = [a for a in arms if a["tag"] == "U25"][0]
    txt = open(u25["chart"], encoding="utf-16", errors="replace").read()
    m = re.search(r"InpMode=(\d+)", txt)
    assert m
    open(u25["chart"], "wb").write(
        txt.replace(f"InpMode={m.group(1)}", "InpMode=7").encode("utf-16"))

    handed: list[tuple[str, str | None]] = []
    monkeypatch.setattr(_wd, "resplice_pins",
                        lambda arm, pins_src=None: handed.append((arm["tag"], pins_src)) or "bak")
    monkeypatch.setattr(_wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(_wd, "terminal_pids_exact", lambda: [4242])
    monkeypatch.setattr(_wd, "stop_terminal", lambda pids: True)
    monkeypatch.setattr(_wd, "relaunch_terminal", lambda: None)
    rec = _wd.check(now_s=NOW)
    assert rec["action"] == "DRIFT"
    assert handed == [("U25", str(armed_pin))], (
        f"the remedy must be handed the armed pin it detected drift against: {handed}")


def test_preset_for_tag_maps_the_portfolio() -> None:
    assert wd.preset_for_tag("M1").endswith("MidastouchAI_M1_gold.set")
    # the tag/file divergence this repo actually has: the account's arm reports U25
    # while its preset file is named for the venue. A name-only lookup missed it, so
    # the drift check would have had no pins for the one arm that matters.
    assert wd.preset_for_tag("U25").endswith("MidastouchAI_upcomers_gold.set")
    import pytest
    with pytest.raises(OSError):
        # an arm with no preset must fail LOUDLY: the caller then observes without
        # pin enforcement rather than pinning to a file that is not there
        open(wd.preset_for_tag("M9x"))


def test_drift_is_attributed_per_arm_and_ignores_others(fresh_state, tmp_path: Path,
                                                        monkeypatch) -> None:
    """A drifted U25 chart must not blame M1: attribution is by the arm's
    own chart <inputs> vs its own pinned preset (§14 identity source)."""
    _seed_two_arm_charts(tmp_path)
    for tag in ("M1", "U25"):
        p = tmp_path / "MQL5" / "Files" / f"MIDASTOUCH_paper_XAUUSD_{tag}.csv"
        p.write_text("\n".join(FLAT) + "\n")
        os.utime(p, (NOW, NOW))
    import midas_watchdog as _wd
    arms = _wd.midas_arms(str(tmp_path))
    # heal both charts to their full pin sets first, so ONLY U25 is drifted
    for a in arms:
        assert _wd.resplice_pins(a), "seed charts must be respliceable"
    m1t = [a for a in arms if a["tag"] == "U25"][0]
    txt = open(m1t["chart"], encoding="utf-16", errors="replace").read()
    m = re.search(r"InpMode=(\d+)", txt)
    assert m, "respliced chart must carry InpMode"
    other = "0" if m.group(1) != "0" else "1"
    drifted = txt.replace(f"InpMode={m.group(1)}", f"InpMode={other}")
    open(m1t["chart"], "wb").write(drifted.encode("utf-16"))

    calls: list[str] = []
    monkeypatch.setattr(_wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(_wd, "terminal_pids_exact", lambda: [4242])
    monkeypatch.setattr(_wd, "stop_terminal", lambda pids: calls.append("stop") or True)
    monkeypatch.setattr(_wd, "relaunch_terminal", lambda: calls.append("relaunch"))
    rec = _wd.check(now_s=NOW)
    assert rec["action"] == "DRIFT" and rec.get("relaunched") is True
    assert all(d.startswith("[U25]") for d in rec["drift"]), \
        f"every drift entry must name the drifted arm: {rec['drift']}"
    assert not any(d.startswith("[M1]") for d in rec["drift"]), \
        "the pinned arm must never be blamed for another arm's drift"
    # and the remediation healed the drifted chart back to its pins
    healed = open(m1t["chart"], encoding="utf-16", errors="replace").read()
    assert f"InpMode={m.group(1)}" in healed


def test_portfolio_flat_gate_blocks_stop_when_one_arm_open(fresh_state,
                                                           monkeypatch,
                                                           tmp_path: Path) -> None:
    """One open position anywhere in the portfolio must veto the terminal stop."""
    _seed_two_arm_charts(tmp_path)
    calls: list[str] = []
    ledgers = {}
    for tag, rows in [("M1", FLAT), ("U25", DANGLING)]:
        ledgers[tag] = _ledger(tmp_path, rows,
                               mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1,
                               name=f"MIDASTOUCH_paper_XAUUSD_{tag}.csv")
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(wd, "midas_arms", lambda df: [
        {"chart": f"chart0{i}.chr", "symbol": "XAUUSD", "tag": t,
         "ledger": ledgers[t]} for i, t in enumerate(("M1", "U25"), 1)])
    monkeypatch.setattr(wd, "terminal_pids_exact", lambda: [4242])
    monkeypatch.setattr(wd, "stop_terminal", lambda pids: calls.append("stop") or True)
    monkeypatch.setattr(wd, "relaunch_terminal", lambda: calls.append("relaunch"))
    monkeypatch.setattr(wd, "recent_banners", lambda df: [])
    rec = wd.check(now_s=NOW)
    assert rec["action"] == "SKIP-OPEN-POSITION"
    assert calls == [], "the stop must never fire with any portfolio arm open"
    # the offending arm is identifiable in the record's per-arm ledger view
    m1t = next(l for l in rec["ledgers"] if l["tag"] == "U25")
    assert m1t["flat"] is False and next(l for l in rec["ledgers"]
                                         if l["tag"] == "M1")["flat"] is True


def test_portfolio_restup_restarts_everyone_when_all_flat(fresh_state,
                                                          monkeypatch,
                                                          tmp_path: Path) -> None:
    _seed_two_arm_charts(tmp_path)
    calls: list[str] = []
    ledgers = {}
    for tag in ("M1", "U25"):
        ledgers[tag] = _ledger(tmp_path, FLAT,
                               mtime_age_min=wd.STALE_MIN + wd.GRACE_MIN + 1,
                               name=f"MIDASTOUCH_paper_XAUUSD_{tag}.csv")
    monkeypatch.setattr(wd, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(wd, "midas_arms", lambda df: [
        {"chart": f"chart0{i}.chr", "symbol": "XAUUSD", "tag": t,
         "ledger": ledgers[t]} for i, t in enumerate(("M1", "U25"), 1)])
    monkeypatch.setattr(wd, "terminal_pids_exact", lambda: [4242])
    monkeypatch.setattr(wd, "stop_terminal", lambda pids: calls.append("stop") or True)
    monkeypatch.setattr(wd, "relaunch_terminal", lambda: calls.append("relaunch"))
    monkeypatch.setattr(wd, "recent_banners", lambda df: [])
    rec = wd.check(now_s=NOW)
    assert rec["action"] == "RESTUP" and rec["relaunched"] is True
    assert rec["restup_tags"] == ["M1", "U25"]
    assert calls == ["stop", "relaunch"]


# --- single-instance guard (reboot-survival precondition) -------------------------

@pytest.fixture()
def lock_paths(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(wd, "INSTANCE_LOCK", str(tmp_path / "midas_watchdog.lock"))
    return tmp_path / "midas_watchdog.lock"


def test_lock_acquires_and_writes_pid(lock_paths: Path) -> None:
    fd = wd.acquire_instance_lock()
    assert fd is not None
    try:
        assert lock_paths.exists()
        # The locked byte blocks other handles; read the PID through our own.
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 32).decode().strip() == str(os.getpid())
    finally:
        wd.release_instance_lock(fd)


def test_second_loop_cannot_take_the_lock(lock_paths: Path) -> None:
    fd1 = wd.acquire_instance_lock()
    assert fd1 is not None
    try:
        assert wd.acquire_instance_lock() is None, \
            "a second concurrent loop must be refused, not doubled"
    finally:
        wd.release_instance_lock(fd1)
    fd2 = wd.acquire_instance_lock()          # released: the next loop wins
    assert fd2 is not None
    wd.release_instance_lock(fd2)


def test_crashed_loop_releases_the_lock_implicitly(lock_paths: Path) -> None:
    """The lock lives on an OS handle, so a hard-killed watchdog leaves no
    stale lock — the next process (e.g. the logon task's) takes it cleanly."""
    fd = wd.acquire_instance_lock()
    assert fd is not None
    os.close(fd)                               # simulate process death (no unlock)
    assert wd.acquire_instance_lock() is not None


def test_main_loop_takes_the_lock_and_releases_on_interrupt(lock_paths, monkeypatch, capsys) -> None:
    """--loop takes the lock, and releases it even on KeyboardInterrupt —
    so the next logon/launch always finds the lock free."""
    monkeypatch.setattr(wd, "INSTANCE_LOCK", str(lock_paths))
    monkeypatch.setattr(sys, "argv", ["midas_watchdog.py", "--loop", "600"])

    def fake_check(**kw):
        raise KeyboardInterrupt()

    monkeypatch.setattr(wd, "check", fake_check)
    with pytest.raises(KeyboardInterrupt):
        wd.main()
    fd = wd.acquire_instance_lock()            # main exited: lock must be free
    assert fd is not None
    wd.release_instance_lock(fd)


def test_registration_script_contract() -> None:
    """The autostart task must be per-user/interactive (no SYSTEM, no admin):
    agent-spawned and service-session processes get reaped or cannot see the
    user's desktop — that is the failure this task exists to prevent."""
    src = (REPO / "scripts" / "register_midas_watchdog_task.ps1").read_text(encoding="utf-8")
    assert "MIDAS Watchdog Autostart" in src
    assert "start_midas_watchdog.bat" in src, "the .bat stays the only entry point"
    assert "-AtLogOn" in src and "Interactive" in src
    assert "New-ScheduledTaskPrincipal" in src
    assert "$env:USERNAME" in src, "per-user, never SYSTEM"
    assert "-Unregister" in src and "Unregister-ScheduledTask" in src
    assert "-Highest" not in src, "no elevation: a user-session process by design"
    assert "-RunLevel Highest" not in src
    assert "New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive" in src, \
        "the principal pins the interactive user — never a service account"
