"""Tests for the chained v1.17 certification runner (register P5 build block).

Pins the ordering law and the fail-closed decisions:
  * the v1.16 scheduler's jsonl event contract is parsed exactly
    (attempt->waiting, cert-complete->complete, unexpected-rc-stop->failed,
    expired->expired, missing file->absent, dead file->stale);
  * the decision table NEVER lets the shadow be refreshed before the v1.16
    baseline is certified (waiting->wait, stale/absent->takeover of the
    v1.16 cert, complete->refresh-and-certify, failed/expired->abort);
  * the shadow refresh is fail-closed: byte-identity of the copy required,
    an unchanged build refuses, a missing scratch binary refuses;
  * takeover never fires when the scheduler is alive and fresh.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import midas_cert_chain_v117 as chain

NOW = time.time()          # real clock: the parser reads real mtimes


def _write_jsonl(tmp_path: Path, events: list[dict], age_s: float = 0.0) -> Path:
    p = tmp_path / "sched.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if age_s:
        past = NOW - age_s
        os.utime(p, (past, past))
    return p


# ── scheduler-state parsing ──────────────────────────────────────────────────

def test_attempt_event_is_waiting(tmp_path):
    p = _write_jsonl(tmp_path, [{"event": "scheduler-armed"},
                                {"event": "attempt", "n": 1, "rc": 4}])
    s = chain.parse_scheduler_state(p, now=NOW, stale_min=35)
    assert s["status"] == "waiting" and s["last"]["n"] == 1


def test_fresh_attempt_within_stale_window_is_waiting_not_stale(tmp_path):
    p = _write_jsonl(tmp_path, [{"event": "attempt", "n": 12, "rc": 4}], age_s=600)
    s = chain.parse_scheduler_state(p, now=NOW, stale_min=35)
    assert s["status"] == "waiting"


def test_dead_file_beyond_stale_window_is_stale(tmp_path):
    p = _write_jsonl(tmp_path, [{"event": "attempt", "n": 12, "rc": 4}], age_s=40 * 60)
    s = chain.parse_scheduler_state(p, now=NOW, stale_min=35)
    assert s["status"] == "stale"


def test_cert_complete_is_complete_with_rc(tmp_path):
    p = _write_jsonl(tmp_path, [{"event": "attempt", "n": 13, "rc": 0},
                                {"event": "cert-complete", "rc": 0}])
    s = chain.parse_scheduler_state(p, now=NOW, stale_min=35)
    assert s["status"] == "complete" and s["last"]["rc"] == 0


def test_unexpected_rc_is_failed(tmp_path):
    p = _write_jsonl(tmp_path, [{"event": "unexpected-rc-stop", "rc": 9}])
    assert chain.parse_scheduler_state(p, now=NOW)["status"] == "failed"


def test_expired_is_expired(tmp_path):
    p = _write_jsonl(tmp_path, [{"event": "expired"}])
    assert chain.parse_scheduler_state(p, now=NOW)["status"] == "expired"


def test_missing_file_is_absent(tmp_path):
    assert chain.parse_scheduler_state(tmp_path / "nope.jsonl",
                                       now=NOW)["status"] == "absent"


def test_corrupt_file_is_absent(tmp_path):
    p = tmp_path / "sched.jsonl"
    p.write_text("{not json", encoding="utf-8")
    assert chain.parse_scheduler_state(p, now=NOW)["status"] == "absent"


# ── the ordering-law decision table ──────────────────────────────────────────

def test_waiting_means_wait_never_refresh():
    assert chain.decide_next_action({"status": "waiting"}) == "wait"


def test_stale_and_absent_take_over_v16_cert_first():
    assert chain.decide_next_action({"status": "stale"}) == "takeover-v16-cert"
    assert chain.decide_next_action({"status": "absent"}) == "takeover-v16-cert"


def test_complete_means_refresh_and_certify():
    assert chain.decide_next_action({"status": "complete"}) == "refresh-and-certify"


def test_failed_and_expired_abort():
    assert chain.decide_next_action({"status": "failed"}) == "abort"
    assert chain.decide_next_action({"status": "expired"}) == "abort"


def test_unknown_status_aborts_fail_closed():
    assert chain.decide_next_action({"status": "weird"}) == "abort"


# ── shadow refresh: fail-closed ──────────────────────────────────────────────

def test_refresh_copies_and_verifies_byte_identity(tmp_path):
    scratch = tmp_path / "scratch.ex5"
    shadow = tmp_path / "shadow.ex5"
    scratch.write_bytes(b"V17-BINARY" * 100)
    r = chain.refresh_shadow(scratch_ex5=scratch, shadow_ex5=shadow,
                             pre_hash="deadbeef" * 8)
    assert r["ok"] is True
    assert shadow.read_bytes() == scratch.read_bytes()
    assert r["sha256"] == chain.sha256_of(scratch)


def test_refresh_refuses_missing_scratch(tmp_path):
    r = chain.refresh_shadow(scratch_ex5=tmp_path / "nope.ex5",
                             shadow_ex5=tmp_path / "shadow.ex5",
                             pre_hash="")
    assert r["ok"] is False and "missing" in r["detail"]


def test_refresh_refuses_unchanged_build(tmp_path):
    """If the scratch binary equals the pre-refresh shadow, the source did
    not change the build — refreshing would be a no-op masquerading as a
    new baseline. Refuse."""
    scratch = tmp_path / "scratch.ex5"
    shadow = tmp_path / "shadow.ex5"
    scratch.write_bytes(b"SAME" * 10)
    shadow.write_bytes(b"SAME" * 10)
    r = chain.refresh_shadow(scratch_ex5=scratch, shadow_ex5=shadow,
                             pre_hash=chain.sha256_of(scratch))
    assert r["ok"] is False and "identical" in r["detail"]
    assert shadow.read_bytes() == b"SAME" * 10   # untouched


def test_refresh_creates_shadow_dir(tmp_path):
    scratch = tmp_path / "s.ex5"
    scratch.write_bytes(b"NEW")
    shadow = tmp_path / "deep" / "dir" / "MidastouchAI.ex5"
    r = chain.refresh_shadow(scratch_ex5=scratch, shadow_ex5=shadow, pre_hash="")
    assert r["ok"] and shadow.exists()


# ── the registered commands are the certified ones ──────────────────────────

def test_commands_match_the_registered_harness_invocation():
    for cmd in (chain.V16_COMMAND, chain.V17_COMMAND):
        assert cmd[1] == "scripts/midas_parity.py"
        assert "--window" in cmd and "wf" in cmd
        assert "MIDASTOUCH_parity" in cmd[cmd.index("--expert-path") + 1]
    assert chain.V16_COMMAND == chain.V17_COMMAND, \
        "the shadow's CONTENT defines the tree, not the command"


def test_constants_match_the_registered_chain():
    assert chain.STALE_MIN == 35          # > the scheduler's 20-min cadence
    assert chain.RETRY_MIN == 20
    assert chain.MAX_WAIT_H == 24
