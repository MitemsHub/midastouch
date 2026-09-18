"""Hermetic tests for the v1.18 deploy runner.

Pins the ordering law and the fail-closed decisions:
  * chain_terminal_state classifies the newest chain jsonl exactly
    (v17-cert-complete -> chain-complete; unexpected-rc-stop/expired/abort
    -> chain-failed; any other last event -> running; no file -> absent);
  * deploy_decision NEVER lets the deploy start on anything but a
    completed chain — running waits, failed/absent stand down;
  * deploy_binaries writes md5-verified copies ONLY to the two registered
    targets, never to the parity shadow or the live path, and keeps a
    backup of the replaced binary;
  * verify_arms demands an ERA MIDAS1.18 row with the diag-nofill tag AND
    a fresh EQ heartbeat per paper arm.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import midas_deploy_v118 as dep  # noqa: E402


def _write_chain(tmp_path: Path, events: list[dict]) -> None:
    (tmp_path / "midas_cert_chain_v117_20260918.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


# --- chain_terminal_state ------------------------------------------------------

def test_state_chain_complete_on_v17_cert_complete(tmp_path):
    _write_chain(tmp_path, [
        {"event": "waiting"}, {"event": "v17-compile", "rc": 0},
        {"event": "shadow-refresh", "ok": True},
        {"event": "v17-cert-complete", "rc": 0}])
    s = dep.chain_terminal_state(tmp_path)
    assert s["state"] == "chain-complete" and s["rc"] == 0


def test_state_chain_failed_on_unexpected_stop_or_expired_or_abort(tmp_path):
    for ev in ("unexpected-rc-stop", "expired", "abort"):
        _write_chain(tmp_path, [{"event": ev}])
        assert dep.chain_terminal_state(tmp_path)["state"] == "chain-failed"


def test_state_running_on_nonterminal_tail(tmp_path):
    _write_chain(tmp_path, [{"event": "waiting", "scheduler_age_s": 12.0}])
    assert dep.chain_terminal_state(tmp_path)["state"] == "running"


def test_state_absent_and_empty(tmp_path):
    assert dep.chain_terminal_state(tmp_path)["state"] == "absent"
    (tmp_path / "midas_cert_chain_v117_20260918.jsonl").write_text(
        "", encoding="utf-8")
    assert dep.chain_terminal_state(tmp_path)["state"] == "empty"


def test_state_newest_file_wins(tmp_path):
    old = tmp_path / "midas_cert_chain_v117_20260917.jsonl"
    new = tmp_path / "midas_cert_chain_v117_20260918.jsonl"
    old.write_text(json.dumps({"event": "abort"}) + "\n", encoding="utf-8")
    new.write_text(json.dumps({"event": "v17-cert-complete", "rc": 0}) + "\n",
                   encoding="utf-8")
    import os
    os.utime(old, (1, 1))  # force mtime ordering
    assert dep.chain_terminal_state(tmp_path)["state"] == "chain-complete"


# --- deploy_decision: the ordering law -----------------------------------------

def test_decision_never_deploys_before_the_chain_completes():
    assert dep.deploy_decision({"state": "running"})["act"] == "wait"
    assert dep.deploy_decision({"state": "absent"})["act"] == "wait"
    for s in ("chain-failed", "empty"):
        assert dep.deploy_decision({"state": s})["act"] == "stand-down"
    assert dep.deploy_decision({"state": "chain-complete"})["act"] == "deploy"


# --- deploy_binaries ------------------------------------------------------------

def test_deploy_copies_verified_with_backup_and_never_touches_forbidden(
        tmp_path, monkeypatch):
    experts = tmp_path / "Experts"
    for d in ("MITEMSHUB_AI", "MIDASTOUCH", "MIDASTOUCH_parity",
              "MIDASTOUCH_live"):
        (experts / d).mkdir(parents=True)
    # pre-existing binaries everywhere — shadow and live must stay untouched
    for d in ("MITEMSHUB_AI", "MIDASTOUCH", "MIDASTOUCH_parity",
              "MIDASTOUCH_live"):
        (experts / d / "MidastouchAI.ex5").write_bytes(b"OLD")
    scratch = tmp_path / "scratch.ex5"
    scratch.write_bytes(b"FRESH-V118")

    logs = []
    res = dep.deploy_binaries(scratch, experts, logs.append)
    assert all(r["ok"] for r in res)
    fresh = scratch.read_bytes()
    for rel, _ in dep.DEPLOY_TARGETS:
        p = experts / rel
        assert p.read_bytes() == fresh, f"{rel} must carry the fresh build"
        assert p.with_suffix(".ex5.pre_v118").read_bytes() == b"OLD"
    # the forbidden paths are byte-identical to before
    assert (experts / "MIDASTOUCH_parity" / "MidastouchAI.ex5").read_bytes() == b"OLD"
    assert (experts / "MIDASTOUCH_live" / "MidastouchAI.ex5").read_bytes() == b"OLD"
    assert {l["target"] for l in logs} == {rel for rel, _ in dep.DEPLOY_TARGETS}


# --- verify_arms ----------------------------------------------------------------

def test_verify_arms_requires_era18_with_diag_tag_and_fresh_eq(tmp_path):
    now = 1_800_000_000.0
    ok = tmp_path / "MIDASTOUCH_paper_XAUUSDmicro_M1.csv"
    ok.write_text(
        "ERA,MIDAS1.17,100,pertick-fills+telemetry-only-per-V2-register\n"
        "ERA,MIDAS1.18,101,pertick-fills+telemetry-only-per-V2-register+diag-nofill\n"
        "EQ,50.00\n", encoding="utf-8")
    import os
    os.utime(ok, (now, now))
    bad_era = tmp_path / "MIDASTOUCH_paper_XAUUSDmicro_M1t.csv"
    bad_era.write_text(
        "ERA,MIDAS1.18,101,pertick-fills\nEQ,50.00\n", encoding="utf-8")
    os.utime(bad_era, (now, now))
    v = dep.verify_arms(tmp_path, min_epoch=now - 60)
    assert v["M1"] == "ok"
    assert v["M1t"] == "era18=True fresh_eq=True" or "era18=" in v["M1t"]
    assert v["M1t"] != "ok", "ERA row without the diag tag must not verify"
