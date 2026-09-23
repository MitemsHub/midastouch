"""The heartbeat-gap alarm and the night coverage measurement.

WHY THIS FILE EXISTS. MEASURED 2026-09-22 from the supervisor's own log: 54 supervision
passes in 25.3 h where a 20-minute cadence owes 76, ZERO passes in the 01:00-06:00 UTC
hours, one gap of 282.8 minutes and one pass that began and never completed. Nothing in
this program recorded any of it — the watchdog reads the ledger's age at the moment it
runs, which cannot see the hours when it did not run. These tests pin the reader that now
does, and the pre-registered rule it applies.

They also pin the bug the reader itself first shipped with: a naive `...Z` stamp fed to
`datetime.astimezone()` is read as LOCAL time, which on this host moved every summary line
an hour earlier and made the night look BETTER covered than it was. A measurement harness
that can flatter the thing it measures is the failure this whole repository is about.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import live_coverage as lc

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 22, 0, 0, 0, tzinfo=timezone.utc).timestamp()


def _hb(ts: float, age: float | None = 2.0, verdict: str = "OK") -> dict:
    return {"ts": ts, "src": "heartbeat", "action": "NONE", "verdict": verdict,
            "ledger_age_min": age, "complete": True}


def _cadence_pass(n: int, *, step_min: float = 20.0, age: float | None = 2.0) -> list[dict]:
    return [_hb(T0 + i * step_min * 60, age) for i in range(n)]


# --------------------------------------------------------------- the timestamp rule

def test_a_naive_z_stamp_is_utc_and_not_local_time():
    """The bug measured on 2026-09-22: `astimezone` reads a naive datetime as local.

    The assertion is positive (the stamp IS that UTC instant) and then negative only when
    the host is not on UTC, so the test states the rule rather than this machine's offset.
    """
    want = datetime(2026, 9, 22, 7, 27, 46, tzinfo=timezone.utc).timestamp()
    assert lc._epoch("2026-09-22T07:27:46Z") == want
    assert lc._epoch("2026-09-22T07:27:46+00:00") == want
    if time.timezone != 0:                       # host is not on UTC: the bug is visible
        local = datetime.fromisoformat("2026-09-22T07:27:46").astimezone(
            timezone.utc).timestamp()
        assert lc._epoch("2026-09-22T07:27:46Z") != local


def test_the_night_window_anchors_on_the_last_08z():
    since, until = lc.night_window(T0 + 12 * 3600)      # 12:00Z
    assert lc._utc(until) == "2026-09-22T08:00:00Z"
    assert lc._utc(since) == "2026-09-21T22:00:00Z"
    # Before 08:00Z the most recent COMPLETE night is the previous one, never a window
    # that ends in the future (which would report the remainder as a gap).
    since2, until2 = lc.night_window(T0 + 3 * 3600)     # 03:00Z
    assert (until2 - since2) == 10 * 3600
    assert until2 < T0 + 3 * 3600


# ------------------------------------------------------------------------ the rule

def test_a_fully_covered_night_passes():
    r = lc.analyze(_cadence_pass(30), T0, T0 + 10 * 3600)
    assert r["verdict"] == "PASS", r["problems"]
    assert r["coverage_pct"] == 100.0
    assert r["gaps"] == [] and r["uncovered_min"] == 0.0
    assert r["n_passes"] == 30 and r["passes_expected"] == 30


def test_the_measured_pre_fix_night_is_gapped_and_names_the_hole():
    """The real 2026-09-21/22 shape: a 282.8-minute hole and 10 passes in 30 slots."""
    passes = [_hb(T0 + i * 1200) for i in range(4)]                      # 22:00 -> 23:00
    passes += [_hb(T0 + 1.0 * 3600 + 68 * 60)]                           # 00:08-ish
    passes += [_hb(T0 + 1.0 * 3600 + 68 * 60 + 282.8 * 60)]              # after the hole
    r = lc.analyze(passes, T0, T0 + 10 * 3600)
    assert r["verdict"] == "GAPPED"
    assert any(280 < g["minutes"] < 286 for g in r["gaps"]), r["gaps"]
    assert r["longest_gap_min"] > 280
    assert r["coverage_pct"] < 60
    assert any("nothing was watching" in p for p in r["problems"])


def test_a_window_with_no_passes_is_unconfirmed_never_a_pass():
    r = lc.analyze([], T0, T0 + 3600)
    assert r["verdict"] == "UNCONFIRMED"
    assert "unmeasured" in r["problems"][0]


def test_a_ledger_that_stopped_beating_while_a_pass_ran_is_its_own_problem():
    r = lc.analyze(_cadence_pass(10, age=3.0) + [_hb(T0 + 10 * 1200, age=41.0)],
                   T0, T0 + 11 * 1200)
    assert r["max_ledger_age_min"] == 41.0
    assert any("the arm was not beating" in p for p in r["problems"])


def test_a_single_late_firing_is_not_an_incident():
    """2 x cadence, deliberately: scheduler jitter must never be an alarm."""
    r = lc.analyze([_hb(T0), _hb(T0 + 38 * 60), _hb(T0 + 58 * 60)], T0, T0 + 76 * 60)
    assert r["gaps"] == [], r["gaps"]
    assert r["verdict"] == "PASS"
    assert lc.GAP_ALARM_MIN == 2 * lc.CADENCE_MIN


def test_the_alarm_thresholds_are_the_programs_own_numbers():
    """One definition of 'the arm stopped beating', not two."""
    import midas_watchdog as wd
    assert lc.HEARTBEAT_ALARM_MIN == wd.STALE_MIN
    src = (REPO / "scripts" / "install_paper_task.ps1").read_text(encoding="utf-8")
    assert f"[int]$EveryMinutes = {lc.CADENCE_MIN}" in src, \
        "the coverage alarm is stated relative to the registered cadence"
    assert "New-TimeSpan -Minutes $EveryMinutes" in src, \
        "the registered repetition interval must be the pinned one, not a literal"


# ------------------------------------------------------------------- reading records

def test_one_pass_written_twice_is_counted_once():
    """The log holds a JSON line AND a summary line per pass; both, or the count doubles."""
    text = (
        '{"ts": "2026-09-22T10:00:00+00:00", "action": "NONE", '
        '"ledgers": [{"tag": "U25", "mtime_age_min": 4.0}]}\n'
        "2026-09-22T10:00:02Z OK action=NONE terminal=x\n")
    got = lc.merge_timeline(lc.parse_supervisor_log(text))
    assert len(got) == 1
    assert got[0]["ledger_age_min"] == 4.0 and got[0]["verdict"] == "OK"
    assert got[0]["complete"] is True


def test_a_pass_that_never_completed_is_counted_and_flagged():
    """MEASURED 2026-09-22: a JSON line at 05:23:13Z whose summary only appeared at
    07:27:46Z — the host slept INSIDE the check, which is a different night from one
    where the supervisor never started."""
    text = ('{"ts": "2026-09-22T05:23:13+00:00", "action": "NONE", '
            '"ledgers": [{"tag": "U25", "mtime_age_min": 0.4}]}\n')
    got = lc.merge_timeline(lc.parse_supervisor_log(text))
    assert got[0]["complete"] is False
    r = lc.analyze(got, T0, T0 + 6 * 3600)
    assert r["unfinished_passes"] == 1
    assert any("never completed" in p for p in r["problems"])
    assert r["verdict"] == "GAPPED"


def test_unparseable_lines_are_skipped_not_guessed():
    got = lc.merge_timeline(lc.parse_supervisor_log("garbage\n{not json\n\n"))
    assert got == []


# ------------------------------------------------------------------------ the alarm

def test_record_pass_raises_a_supervision_gap_alarm_and_writes_the_heartbeat(tmp_path):
    hb = tmp_path / "hb.jsonl"
    alarm = tmp_path / "alarm.json"
    alerts = tmp_path / "alerts.log"
    empty = tmp_path / "none.log"
    six_hours_ago = T0
    hb.write_text(json.dumps({"utc": lc._utc(six_hours_ago), "action": "NONE",
                              "verdict": "OK", "ledger_age_min": 1.0}) + "\n",
                  encoding="utf-8")
    out = lc.record_pass({"action": "NONE", "terminal_running": True,
                          "ledgers": [{"tag": "U25", "mtime_age_min": 2.0}]},
                         now=six_hours_ago + 6 * 3600,
                         heartbeat_path=str(hb), log_path=str(empty),
                         alarm_path=str(alarm), alerts_path=str(alerts))
    assert out["alarm_new"] is True
    assert out["alarm"]["kind"] == "supervision-gap"
    assert out["alarm"]["gap_min"] == 360.0
    assert "nothing was watching" in out["alarm"]["detail"]
    # The heartbeat line is appended, so the NEXT pass measures from now.
    lines = hb.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1])["ledger_age_min"] == 2.0
    assert alerts.read_text(encoding="utf-8").count("ALARM") == 1


def test_the_same_gap_episode_alerts_once(tmp_path):
    """The first pass after a hole is not the only pass that can see it."""
    alarm = tmp_path / "alarm.json"
    alerts = tmp_path / "alerts.log"
    a = {"episode": "supervision-gap:1", "kind": "supervision-gap",
         "raised_utc": lc._utc(T0), "gap_min": 400.0, "detail": "d"}
    assert lc.raise_alarm(a, alarm_path=str(alarm), alerts_path=str(alerts)) is True
    assert lc.raise_alarm(a, alarm_path=str(alarm), alerts_path=str(alerts)) is False
    assert alerts.read_text(encoding="utf-8").count("ALARM") == 1


def test_a_stale_ledger_at_a_pass_that_ran_is_the_other_kind(tmp_path):
    hb = tmp_path / "hb.jsonl"
    hb.write_text(json.dumps({"utc": lc._utc(T0 - 60), "action": "NONE",
                              "verdict": "OK", "ledger_age_min": 1.0}) + "\n",
                  encoding="utf-8")
    out = lc.record_pass({"action": "NONE", "ledgers": [{"tag": "U25",
                                                         "mtime_age_min": 44.0}]},
                         now=T0, heartbeat_path=str(hb),
                         log_path=str(tmp_path / "none.log"),
                         alarm_path=str(tmp_path / "a.json"),
                         alerts_path=str(tmp_path / "alerts.log"))
    assert out["alarm"]["kind"] == "ledger-heartbeat-gap"
    assert out["alarm"]["gap_min"] == 44.0
    assert "the supervisor was present" in out["alarm"]["detail"]


def test_no_gap_no_alarm_and_the_standing_alarm_is_left_alone(tmp_path):
    out = lc.record_pass({"action": "NONE", "ledgers": []}, now=T0,
                         heartbeat_path=str(tmp_path / "hb.jsonl"),
                         log_path=str(tmp_path / "none.log"),
                         alarm_path=str(tmp_path / "a.json"),
                         alerts_path=str(tmp_path / "alerts.log"))
    assert out["alarm"] is None and out["alarm_new"] is False
    assert not (tmp_path / "a.json").exists()


def test_alarm_state_is_current_until_it_is_acknowledged(tmp_path):
    alarm = tmp_path / "a.json"
    lc.raise_alarm({"episode": "e", "kind": "supervision-gap", "raised_utc": lc._utc(T0),
                    "detail": "gap of 400 min"},
                   alarm_path=str(alarm), alerts_path=str(tmp_path / "alerts.log"))
    st = lc.alarm_state(alarm_path=str(alarm), now=T0 + 600)
    assert st["present"] and st["current"] and st["unacked"]
    assert "PROBLEM" in lc.alarm_line(alarm_path=str(alarm), now=T0 + 600)
    lc.ack_alarm(alarm_path=str(alarm), now=T0 + 700)
    st = lc.alarm_state(alarm_path=str(alarm), now=T0 + 800)
    assert not st["current"] and not st["unacked"]
    assert "acknowledged" in lc.alarm_line(alarm_path=str(alarm), now=T0 + 800)
    # ...and an alarm older than the TTL is no longer "current", but is never deleted.
    old = lc.alarm_state(alarm_path=str(alarm), now=T0 + 48 * 3600)
    assert old["present"] and not old["current"]


def test_the_alarm_record_names_what_would_fix_it(tmp_path):
    """An alarm nobody can act on is a log line. Both kinds must say the next step."""
    out = lc.record_pass({"action": "NONE", "ledgers": []},
                         now=T0,
                         heartbeat_path=str(tmp_path / "hb.jsonl"),
                         log_path=str(tmp_path / "none.log"),
                         alarm_path=str(tmp_path / "a.json"),
                         alerts_path=str(tmp_path / "alerts.log"))
    assert out["alarm"] is None                      # nothing recorded before it
    (tmp_path / "hb.jsonl").write_text(
        json.dumps({"utc": lc._utc(T0), "action": "NONE", "verdict": "OK"}) + "\n",
        encoding="utf-8")
    out = lc.record_pass({"action": "NONE", "ledgers": []}, now=T0 + 4000,
                         heartbeat_path=str(tmp_path / "hb.jsonl"),
                         log_path=str(tmp_path / "none.log"),
                         alarm_path=str(tmp_path / "a.json"),
                         alerts_path=str(tmp_path / "alerts.log"))
    why = out["alarm"]["why"]
    assert "unattended.py" in why and "host_power.py" in why


def test_the_prereg_states_the_rule_as_the_evidence_that_was_measured():
    p = lc.prereg()
    assert p["frozen_utc"] == "2026-09-22"
    assert str(lc.GAP_ALARM_MIN) in p["pass_rule"]
    assert "BASELINE" in p["why_these"]
    assert "not a push notification" in p["what_it_cannot_see"]


# ------------------------------------------------------------------ the live checkout

def test_the_reader_reads_this_repos_own_records():
    """A reader that matches nothing passes every rule vacuously."""
    tl = lc.timeline()
    if not tl:
        pytest.skip("no supervision record on this machine yet")
    assert all(d["ts"] > 1_700_000_000 for d in tl)
    assert tl == sorted(tl, key=lambda d: d["ts"])


def test_the_supervisor_records_every_pass_it_makes():
    src = (REPO / "scripts" / "paper_supervisor.py").read_text(encoding="utf-8")
    assert "lc.record_pass(" in src, "a pass that is not recorded is not coverage"
    assert "if not dry_run:" in src, "a dry run must not count as coverage"
