"""Tests for the MT5-VPS migration preflight/verify/era tool.

The failure that built this: 2026-09-23 12:32:38Z, subscription 6911490, the operator
clicked Migrate with the EA running as a startup-INI chart and the VPS received
"nothing to synchronize, no any EA" — the arm traded from a hibernating laptop all day
while the rented VPS idled at 0 charts / 0 EAs. These tests pin the two contracts:

* preflight refuses the unsafe moments of each plan (no carrier chart, wrong preset,
  wrong execution flag, wrong tag, non-flat book on a cutover, live startup-INI
  conflict) and passes a correctly prepared world;
* verify-after reads the LOCAL journal's own words and fails closed on the empty
  migration, a missed chart, a missing guard, and a missing day.

The era marker is the operator's only honest hosting source for the watchdog and the
morning report (midas_watchdog.vps_hosting_active) — its shape and path are pinned
here because two consumers read it.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import midas_vps_migration as M  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# A real preset file for the identity check: the dedicated VPS rehearsal pin (the
# paper preset with only InpArmTag=VPS changed) and the LIVE pin it must not be.
VPS_PIN = os.path.join(REPO, "mql5", "MIDASTOUCH", "MidastouchAI_VPS_gold.set")
LIVE_PIN = os.path.join(REPO, "mql5", "MIDASTOUCH", "MidastouchAI_upcomers_gold_LIVE.set")


def _carrier_from(pin_path: str, overrides: dict[str, str] | None = None) -> tuple[str, str]:
    """A carrier .chr body from a real pin file (the fixture cannot rot when a pin moves)."""
    txt = open(pin_path, encoding="utf-8").read()
    for k, v in (overrides or {}).items():
        lines = []
        for ln in txt.splitlines():
            if ln.startswith(k + "="):
                ln = f"{k}={v}"
            lines.append(ln)
        txt = "\r\n".join(lines) + "\r\n"
    return os.path.join("chart.chr"), txt


def _no_attach_ini(monkeypatch) -> None:
    monkeypatch.setattr(M, "attach_ini_chart_spawns_ea", lambda: False)


# --- preflight: the carrier ----------------------------------------------------------

def test_preflight_refuses_the_measured_empty_migration():
    """The 2026-09-23 failure mode, as a blocker: no saved EA chart, nothing can ship."""
    ok, lines = M.preflight(M.PLAN_PAPER, positions=[], term_root="Z:/none",
                            attach_ini_spawns=False)
    assert not ok
    assert any("no profile-saved chart carries MidastouchAI" in ln for ln in lines)


def test_preflight_paper_passes_a_correctly_prepared_world(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "ARMED_PATH", os.path.join(str(tmp_path), "none.json"))
    _no_attach_ini(monkeypatch)
    ok, lines = M.preflight(M.PLAN_PAPER, positions=[{"t": 1}],
                            carrier=_carrier_from(VPS_PIN),
                            attach_ini_spawns=False)
    assert ok, lines
    assert any("InpLiveExecution=false" in ln or "byte-identical" in ln for ln in lines)
    assert any("allowed for paper-rehearsal" in ln for ln in lines), lines


def test_preflight_rejects_a_live_carrier_in_rehearsal(monkeypatch):
    _no_attach_ini(monkeypatch)
    ok, lines = M.preflight(M.PLAN_PAPER, positions=[],
                            carrier=_carrier_from(VPS_PIN, {"InpLiveExecution": "true"}),
                            attach_ini_spawns=False)
    assert not ok
    assert any("PAPER preset" in ln for ln in lines)


def test_preflight_rejects_wrong_tag_in_rehearsal(monkeypatch):
    """The rehearsal must write its own ledger: tag VPS, not the live arm's U25."""
    _no_attach_ini(monkeypatch)
    ok, lines = M.preflight(M.PLAN_PAPER, positions=[],
                            carrier=_carrier_from(VPS_PIN, {"InpArmTag": "U25"}),
                            attach_ini_spawns=False)
    assert not ok
    assert any("InpArmTag=VPS" in ln for ln in lines)


def test_preflight_rejects_drifted_carrier(monkeypatch):
    """A carrier whose inputs differ from the plan's pin is today's silent preset loss,
    shipped to the cloud — refused even though an EA chart exists."""
    _no_attach_ini(monkeypatch)
    ok, lines = M.preflight(M.PLAN_PAPER, positions=[],
                            carrier=_carrier_from(VPS_PIN, {"InpSpreadCapPctStop": "9.9"}),
                            attach_ini_spawns=False)
    assert not ok
    assert any("not byte-identical" in ln for ln in lines)


def test_vps_rehearsal_pin_differs_from_live_only_by_tag():
    """The rehearsal pin exists, is byte-identical to the paper pin except the tag, and
    is NOT the live pin (so a rehearsal can never ship live execution)."""
    paper = open(os.path.join(REPO, "mql5", "MIDASTOUCH", "MidastouchAI_upcomers_gold.set"),
                 encoding="utf-8").read().splitlines()
    vps = open(VPS_PIN, encoding="utf-8").read().splitlines()
    live = open(LIVE_PIN, encoding="utf-8").read().splitlines()
    diffs = [(a, b) for a, b in zip(paper, vps) if a != b]
    assert diffs == [("InpArmTag=U25", "InpArmTag=VPS")]
    assert vps != live, "the rehearsal carrier must not be the LIVE preset"


# --- preflight: the cutover guards ---------------------------------------------------

def _armed_record(tmp_path) -> str:
    p = os.path.join(str(tmp_path), "armed.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"armed": True, "override": True, "arm": "U25",
                   "summary": "ARMED BY OPERATOR OVERRIDE — the walk-forward gate FAILED"},
                  fh)
    return p


def test_preflight_cutover_needs_flat_book(tmp_path, monkeypatch):
    """A position straddling the handover changes managers mid-flight: refused."""
    _no_attach_ini(monkeypatch)
    monkeypatch.setattr(M, "ARMED_PATH", _armed_record(tmp_path))
    ok, lines = M.preflight(M.PLAN_FULL, positions=[{"t": 1}],
                            carrier=_carrier_from(LIVE_PIN),
                            attach_ini_spawns=False)
    assert not ok
    assert any("book is not flat" in ln for ln in lines)


def test_preflight_cutover_needs_the_arming_record(tmp_path, monkeypatch):
    _no_attach_ini(monkeypatch)
    monkeypatch.setattr(M, "ARMED_PATH", os.path.join(str(tmp_path), "absent.json"))
    ok, lines = M.preflight(M.PLAN_FULL, positions=[],
                            carrier=_carrier_from(LIVE_PIN),
                            attach_ini_spawns=False)
    assert not ok
    assert any("no arming record" in ln for ln in lines)


def test_preflight_cutover_flags_the_startup_ini_conflict(tmp_path, monkeypatch):
    """After a cutover, the attach-INI would boot a SECOND live EA next to the profile
    EA on every restart — the blocker carries the exact remedy."""
    _no_attach_ini(monkeypatch)
    monkeypatch.setattr(M, "ARMED_PATH", _armed_record(tmp_path))
    ok, lines = M.preflight(M.PLAN_FULL, positions=[],
                            carrier=_carrier_from(LIVE_PIN),
                            attach_ini_spawns=True)
    assert not ok
    assert any("midas_attach.ini" in ln and "second" in ln.lower() for ln in lines)


def test_preflight_cutover_passes_when_everything_aligns(tmp_path, monkeypatch):
    _no_attach_ini(monkeypatch)
    monkeypatch.setattr(M, "ARMED_PATH", _armed_record(tmp_path))
    ok, lines = M.preflight(M.PLAN_FULL, positions=[],
                            carrier=_carrier_from(LIVE_PIN),
                            attach_ini_spawns=False)
    assert ok, lines
    assert any("arming record" in ln for ln in lines)


# --- verify-after: read what actually happened ---------------------------------------

def _journal(tmp_path, *lines) -> str:
    p = os.path.join(str(tmp_path), "journal.log")
    with open(p, "w", encoding="utf-16") as fh:
        fh.write("\r\n".join(lines))
    return p


def test_verify_after_fails_on_the_measured_empty_migration(tmp_path, monkeypatch):
    """The exact 12:32:38Z journal: '0 charts of 1', 'nothing to synchronize'."""
    p = _journal(tmp_path,
                 "FI\t0\t12:32:38.201\tVirtual Hosting\t6911490: prepare charts to synchronize...",
                 "JO\t0\t12:32:38.201\tVirtual Hosting\t6911490: 0 charts of 1 prepared to synchronize",
                 "QJ\t3\t12:32:38.201\tVirtual Hosting\t6911490: nothing to synchronize, no any EA or custom indicator, signal for '1428765' is not enabled",
                 "EJ\t0\t12:32:38.696\tVirtual Hosting\t6911490: migration processed")
    monkeypatch.setattr(M, "journal_text", lambda day=None: open(p, encoding="utf-16").read())
    ok, lines = M.verify_after(plan=M.PLAN_FULL)
    assert not ok
    assert any("nothing to synchronize" in ln for ln in lines)
    assert any("charts prepared to synchronize: 0" in ln for ln in lines)


def test_verify_after_passes_a_full_cutover_with_the_guard_fired(tmp_path, monkeypatch):
    p = _journal(tmp_path,
                 "JO\t0\t13:05:01.000\tVirtual Hosting\t6911490: 1 charts of 1 prepared to synchronize",
                 "EJ\t0\t13:05:02.000\tVirtual Hosting\t6911490: migration processed",
                 "AB\t0\t13:05:03.000\tTerminal\tautomated trading disabled after migration and enabled on virtual hosting")
    monkeypatch.setattr(M, "journal_text", lambda day=None: open(p, encoding="utf-16").read())
    ok, lines = M.verify_after(plan=M.PLAN_FULL)
    assert ok, lines
    assert any("guard" in ln and "FIRED" in ln for ln in lines)


def test_verify_after_fails_when_the_guard_did_not_fire(tmp_path, monkeypatch):
    """A 'successful' EA transfer without the local lock means a live EA may exist on
    BOTH sides — the one failure verify-after must never wave through."""
    p = _journal(tmp_path,
                 "JO\t0\t13:05:01.000\tVirtual Hosting\t6911490: 1 charts of 1 prepared to synchronize",
                 "EJ\t0\t13:05:02.000\tVirtual Hosting\t6911490: migration processed")
    monkeypatch.setattr(M, "journal_text", lambda day=None: open(p, encoding="utf-16").read())
    ok, lines = M.verify_after(plan=M.PLAN_FULL)
    assert not ok
    assert any("guard did not fire" in ln or "guard" in ln for ln in lines)


def test_verify_after_rehearsal_does_not_require_the_guard(tmp_path, monkeypatch):
    p = _journal(tmp_path,
                 "JO\t0\t13:05:01.000\tVirtual Hosting\t6911490: 1 charts of 1 prepared to synchronize",
                 "EJ\t0\t13:05:02.000\tVirtual Hosting\t6911490: migration processed")
    monkeypatch.setattr(M, "journal_text", lambda day=None: open(p, encoding="utf-16").read())
    ok, lines = M.verify_after(plan=M.PLAN_PAPER)
    assert ok, lines
    assert any("not fired (correct" in ln for ln in lines)


def test_verify_after_fails_closed_on_a_missing_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "journal_text", lambda day=None: "")
    ok, lines = M.verify_after(plan=M.PLAN_FULL)
    assert not ok
    assert any("no terminal journal" in ln for ln in lines)


# --- the era marker: two consumers read this file ------------------------------------

def test_era_marker_roundtrip_and_shape(tmp_path, monkeypatch):
    """The marker lives at the path midas_watchdog.vps_hosting_active reads, and carries
    what the morning report prints (the expected-staleness note)."""
    marker = os.path.join(str(tmp_path), "midas_vps_hosting.json")
    monkeypatch.setattr(M, "ERA_MARKER", marker)
    monkeypatch.setattr(M, "ERA_ARCHIVE", os.path.join(str(tmp_path), "archive"))
    got = M.mark_era("6911490", "VPS Germany 01", M.PLAN_FULL, "test window")
    assert got == marker
    rec = json.load(open(marker, encoding="utf-8"))
    assert rec["subscription"] == "6911490"
    assert rec["plan"] == M.PLAN_FULL
    assert "stale" in rec["local_lv_ledger_expected"]
    M.clear_era()
    assert not os.path.exists(marker), "clear archives the marker, leaving no active era"
    archived = os.listdir(os.path.join(str(tmp_path), "archive"))
    assert len(archived) == 1 and archived[0].startswith("midas_vps_hosting_")


def test_watchdog_reads_the_marker_this_tool_writes():
    """The consumer contract: the watchdog's marker path IS this tool's marker path."""
    import midas_watchdog as W
    assert W.VPS_HOSTING_MARKER == M.ERA_MARKER
