"""Tests for the [3b] broker-vs-UTC clock-offset tracking.

Pins (against the v1.12 EA/probe writers, health guide §4): the journal-line
grammar both writers emit (`offset (server-GMT) = +N h MM min` probe /
`offset=+N h MM min` banner), the ±1-minute sampling-artifact band, the
persisted baseline at artifacts/midas_clock_offset_state.json, the DST-shift
flag (a ~1 h move against the last known offset), the non-1 h OFFSET CHANGE
flag, and the read-only/no-reading paths. Synthetic journals + tmp state
only — the real terminal logs belong to the operator, never to a test.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import morning_status as ms  # noqa: E402

NOW = datetime(2026, 9, 17, 8, 0, 0)


def _probe_line(h: int = 3, m: int = 0) -> str:
    return (f"PR\t0\t08:00:00.000\tMidasOffsetProbe (XAUUSD,M1)\t"
            f"  offset (server-GMT)   = {h:+d} h {m:02d} min")


def _banner_line(h: int = 2) -> str:
    return (f"PR\t0\t08:00:00.000\tMidastouchAI (XAUUSD,M15)\t"
            f"MIDAS1.12CLOCK: server=2026.09.17 10:00 | GMT=2026.09.17 08:00 | "
            f"offset={h:+d} h 00 min — session gates classify BAR EPOCHS")


def _state(tmp_path, **kw) -> str:
    return os.path.join(str(tmp_path), "offset_state.json")


# --- the journal-line grammar, both writers ---------------------------------

class TestParseOffset:
    def test_probe_line(self):
        assert ms._parse_offset_hm(_probe_line(3)) == 180

    def test_banner_line(self):
        assert ms._parse_offset_hm(_banner_line(2)) == 120

    def test_negative_offset_survives(self):
        assert ms._parse_offset_hm(_probe_line(-5, 30)) == -330

    def test_ignores_lines_without_an_offset(self):
        assert ms._parse_offset_hm("MIDAS OFFSET PROBE on XAUUSD") is None
        assert ms._parse_offset_hm("CHECK 1: open a UTC clock") is None

    def test_fmt_mirrors_the_mql5_writer(self):
        assert ms._fmt_off(180) == "+3 h 00 min"
        assert ms._fmt_off(120) == "+2 h 00 min"
        # C truncation toward zero: -179 min prints -2 h 59 min, never -3 h.
        assert ms._fmt_off(-179) == "-2 h 59 min"
        assert ms._fmt_off(-330) == "-5 h 30 min"


# --- reading today's journal --------------------------------------------------

class TestReadings:
    def _journal(self, tmp_path, lines: list[str]) -> list[str]:
        d = os.path.join(str(tmp_path), "FAKEHASH", "MQL5", "Logs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{NOW:%Y%m%d}.log")
        with open(p, "w", encoding="utf-16") as f:
            f.write("".join(ln + "\r\n" for ln in lines))
        return [os.path.join(str(tmp_path), "FAKEHASH")]

    def test_probe_and_banner_sources(self, tmp_path):
        dirs = self._journal(tmp_path, [_probe_line(3), _banner_line(3)])
        r = ms.probe_offset_readings(dirs, NOW)
        assert len(r) == 2
        assert r[0]["source"] == "probe" and r[0]["offset_min"] == 180
        assert r[1]["source"] == "banner" and r[1]["offset_min"] == 180

    def test_only_today_is_scanned(self, tmp_path):
        d = os.path.join(str(tmp_path), "FAKEHASH", "MQL5", "Logs")
        os.makedirs(d, exist_ok=True)
        old = NOW - timedelta(days=2)
        with open(os.path.join(d, f"{old:%Y%m%d}.log"), "w", encoding="utf-16") as f:
            f.write(_probe_line(3) + "\r\n")
        assert ms.probe_offset_readings([os.path.join(str(tmp_path), "FAKEHASH")],
                                        NOW) == []

    def test_missing_journal_reads_empty(self, tmp_path):
        assert ms.probe_offset_readings([os.path.join(str(tmp_path), "NOPE")],
                                        NOW) == []


# --- the baseline + DST flag ---------------------------------------------------

class TestCheckClockOffset:
    def test_first_reading_records_baseline(self, tmp_path, capsys):
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(3)])
        sp = _state(tmp_path)
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert r["alerts"] == [] and r["stable_offset_min"] == 180
        st = json.load(open(sp))
        assert st["last_offset_min"] == 180 and st["runs"] == 1
        out = capsys.readouterr().out
        assert "MidasOffsetProbe run" in out
        assert "matches last known" not in out

    def test_stable_reading_matches_last_known(self, tmp_path, capsys):
        dirs = TestReadings._journal(None, tmp_path, [_banner_line(2)])
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 120, "last_seen_epoch": (NOW - timedelta(days=1)).timestamp(),
                   "last_source": "probe", "runs": 1}, open(sp, "w"))
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert r["alerts"] == []
        out = capsys.readouterr().out
        assert "+2 h 00 min server-vs-UTC, matches last known" in out
        assert "v1.12 banner" in out

    def test_dst_shift_is_flagged(self, tmp_path, capsys):
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(3)])
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 120, "last_seen_epoch": (NOW - timedelta(days=91)).timestamp(),
                   "last_source": "probe", "runs": 4}, open(sp, "w"))
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert any("DST SHIFT" in a and "+2 h 00 min -> +3 h 00 min" in a
                   for a in r["alerts"])
        assert json.load(open(sp))["last_offset_min"] == 180
        assert "DST SHIFT" in capsys.readouterr().out

    def test_non_dst_change_flagged_differently(self, tmp_path):
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(5)])
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 120, "last_seen_epoch": NOW.timestamp(),
                   "last_source": "probe", "runs": 1}, open(sp, "w"))
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert any("OFFSET CHANGE" in a and "not a 1-h DST step" in a
                   for a in r["alerts"])
        assert not any("DST SHIFT" in a for a in r["alerts"])

    def test_sampling_artifact_is_absorbed(self, tmp_path):
        """A true +3h sampled across a second boundary can read +2h59m; the
        ±1-minute band absorbs it into the whole-hour baseline — no flag."""
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(2, 59)])
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 180, "last_seen_epoch": NOW.timestamp(),
                   "last_source": "probe", "runs": 1}, open(sp, "w"))
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert r["alerts"] == [] and r["stable_offset_min"] == 180

    def test_garbled_half_hour_reading_never_becomes_baseline(self, tmp_path):
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(2, 30)])
        sp = _state(tmp_path)
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert any("not a stable whole-hour" in a for a in r["alerts"])
        assert r["stable_offset_min"] is None
        assert not os.path.exists(sp), "a non-whole-hour value must not persist"

    def test_no_reading_with_baseline_is_informational(self, tmp_path, capsys):
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 120, "last_seen_epoch": (NOW - timedelta(days=91)).timestamp(),
                   "last_source": "probe", "runs": 1}, open(sp, "w"))
        r = ms.check_clock_offset([os.path.join(str(tmp_path), "FAKEHASH")], NOW,
                                  state_path=sp)
        assert r["alerts"] == []
        out = capsys.readouterr().out
        assert "no reading in today's journal; last known +2 h 00 min" in out
        assert "91.0d ago" in out

    def test_never_recorded_prompts_the_probe(self, tmp_path, capsys):
        r = ms.check_clock_offset([], NOW, state_path=_state(tmp_path))
        assert r["offset_min"] is None and r["alerts"] == []
        assert "never recorded - run MidasOffsetProbe once" in capsys.readouterr().out

    def test_state_corruption_starts_fresh(self, tmp_path):
        sp = _state(tmp_path)
        with open(sp, "w") as f:
            f.write("{broken json")
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(2)])
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert r["alerts"] == [] and json.load(open(sp))["last_offset_min"] == 120

    def test_partial_state_lacking_timestamp_is_not_a_crash(self, tmp_path, capsys):
        """A hand-edited state with last_offset_min but no last_seen_epoch
        degrades to 'age unknown' instead of crashing the report."""
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 120, "last_source": "probe"}, open(sp, "w"))
        r = ms.check_clock_offset([], NOW, state_path=sp)
        assert r["alerts"] == []
        assert "age unknown - state lacks last_seen_epoch" in capsys.readouterr().out


# --- the audit chain: the raw reading is persisted with the baseline ------------

class TestOffsetAuditChain:
    def test_baseline_persists_the_raw_reading(self, tmp_path, capsys):
        """The raw pre-rounding value + source + journal epoch + terminal dir
        land in state alongside the baseline, so any later flag can be
        audited against the exact journal line that produced it."""
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(3)])
        sp = _state(tmp_path)
        ms.check_clock_offset(dirs, NOW, state_path=sp)
        st = json.load(open(sp))
        rs = st.get("readings", [])
        assert len(rs) == 1
        raw = rs[0]
        assert raw["offset_min"] == 180 and raw["source"] == "probe"
        assert raw["epoch"] == NOW.timestamp()
        assert raw["dir"] == "FAKEHASH"
        # the chain links: the baseline claims THIS reading as its evidence
        assert st["last_seen_epoch"] == raw["epoch"]

    def test_dst_flag_is_auditable_against_both_legs(self, tmp_path):
        """After a DST shift, state holds BOTH raw legs plus the change
        record — the flag cites values whose provenance is on disk."""
        old_epoch = (NOW - timedelta(days=91)).timestamp()
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(3)])
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 120, "last_seen_epoch": old_epoch,
                   "last_source": "probe", "runs": 4,
                   "readings": [{"offset_min": 120, "source": "probe",
                                 "epoch": old_epoch, "dir": "FAKEHASH"}]},
                  open(sp, "w"))
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert any("DST SHIFT" in a for a in r["alerts"])
        st = json.load(open(sp))
        assert len(st["readings"]) == 2
        assert st["readings"][0]["offset_min"] == 120
        assert st["readings"][1]["offset_min"] == 180
        assert st["last_change"]["from_min"] == 120
        assert st["last_change"]["to_offset_min"] == 180
        assert st["last_change"]["to_source"] == "probe"

    def test_unstable_reading_never_enters_the_chain(self, tmp_path):
        """A non-whole-hour reading never becomes the baseline — so it must
        never masquerade as the audit evidence for one either. Nothing is
        written at all: a state file that never existed still doesn't."""
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(3, 25)])
        sp = _state(tmp_path)
        r = ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert not os.path.exists(sp), (
            "an unstable reading must not create/persist any state")
        assert any("not a stable whole-hour" in a for a in r["alerts"])

    def test_chain_is_capped(self, tmp_path):
        sp = _state(tmp_path)
        json.dump({"last_offset_min": 120, "last_seen_epoch": NOW.timestamp(),
                   "last_source": "probe", "runs": 1,
                   "readings": [{"offset_min": 120, "source": "probe",
                                 "epoch": 0, "dir": "X"}] * 60}, open(sp, "w"))
        dirs = TestReadings._journal(None, tmp_path, [_probe_line(2)])
        ms.check_clock_offset(dirs, NOW, state_path=sp)
        assert len(json.load(open(sp))["readings"]) == 50


# --- journal-retention guard -------------------------------------------------

class TestJournalRetention:
    def _chart(self, root: str, with_ledger: bool = True,
               ledger_mtime: float | None = None,
               ledger_rows: list[str] | None = None) -> list[tuple[str, str]]:
        td = os.path.join(root, "FAKEHASH")
        if with_ledger:
            fd = os.path.join(td, "MQL5", "Files")
            os.makedirs(fd, exist_ok=True)
            p = os.path.join(fd, "MIDASTOUCH_paper_XAUUSD_M1.csv")
            with open(p, "w") as fh:
                fh.write("\n".join(ledger_rows or ["EQ,50.00"]) + "\n")
            if ledger_mtime is not None:
                os.utime(p, (ledger_mtime, ledger_mtime))
        return [(td, "chart-text")]

    def _log(self, root: str, mtime: float | None = None,
             banners: int = 0) -> str:
        ld = os.path.join(root, "FAKEHASH", "MQL5", "Logs")
        os.makedirs(ld, exist_ok=True)
        p = os.path.join(ld, f"{datetime.now():%Y%m%d}.log")
        with open(p, "w", encoding="utf-8") as fh:
            for _ in range(banners):
                fh.write("0\t0\t10:31:13.488\tMidastouchAI (XAUUSD,M15)\t"
                         "[MIDAS1.10]MIDASTOUCH started | mode=0\n")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def test_fresh_log_alerts_nothing(self, tmp_path):
        now = datetime.now().timestamp()
        root = str(tmp_path)
        self._log(root, mtime=now)
        charts = self._chart(root, ledger_mtime=now - 600)
        assert ms.journal_retention_guard(charts, datetime.now()) == []

    def test_missing_log_with_live_ledger_alerts(self, tmp_path):
        now = datetime.now().timestamp()
        root = str(tmp_path)
        charts = self._chart(root, ledger_mtime=now - 60)
        assert not os.path.exists(os.path.join(root, "FAKEHASH", "MQL5", "Logs"))
        out = ms.journal_retention_guard(charts, datetime.now())
        assert len(out) == 1 and out[0][0] == "alert" and "MISSING" in out[0][1]

    def test_rewritten_log_alerts(self, tmp_path):
        """Ledger heartbeat 4 h newer than the log AND a today-ERA stamp (an
        EA init happened today but left no journal line): the journal was
        rebuilt (or logging died) — today's journal is partial."""
        now = datetime.now().timestamp()
        root = str(tmp_path)
        self._log(root, mtime=now - 4 * 3600)
        charts = self._chart(root, ledger_mtime=now - 600, ledger_rows=[
            f"ERA,MIDAS1.10,{now - 700},pertick-fills", "EQ,50.00"])
        out = ms.journal_retention_guard(charts, datetime.now())
        assert len(out) == 1 and out[0][0] == "alert" and "REWRITTEN" in out[0][1]

    def test_quiet_log_with_boot_banners_is_info_not_alert(self, tmp_path):
        """2026-09-18 12:26 live finding: a quiet terminal journals nothing
        after boot (EQ heartbeats are ledger-only file writes, never Prints)
        — a lagging mtime with today's boot banners intact is the QUIET
        signature, not a retention failure."""
        now = datetime.now().timestamp()
        root = str(tmp_path)
        self._log(root, mtime=now - 4 * 3600, banners=5)
        charts = self._chart(root, ledger_mtime=now - 600)
        out = ms.journal_retention_guard(charts, datetime.now())
        assert len(out) == 1 and out[0][0] == "info" and "QUIET" in out[0][1]
        assert "banner" in out[0][1]

    def test_one_terminal_yields_one_line(self, tmp_path):
        """charts carries one tuple PER ARM — five arms on one terminal must
        produce ONE retention line, not five identical alerts (the 12:26 ×5)."""
        now = datetime.now().timestamp()
        root = str(tmp_path)
        self._log(root, mtime=now - 4 * 3600, banners=5)
        charts = self._chart(root, ledger_mtime=now - 600)
        charts += [charts[0], charts[0]]      # five arms, one terminal
        assert len(ms.journal_retention_guard(charts, datetime.now())) == 1

    def test_small_inversion_inside_tolerance_is_silent(self, tmp_path):
        now = datetime.now().timestamp()
        root = str(tmp_path)
        self._log(root, mtime=now - 1800)
        charts = self._chart(root, ledger_mtime=now - 1500)
        assert ms.journal_retention_guard(charts, datetime.now()) == []

    def test_ledgerless_terminal_is_out_of_scope(self, tmp_path):
        now = datetime.now().timestamp()
        root = str(tmp_path)
        self._log(root, mtime=now - 9 * 3600)
        charts = self._chart(root, with_ledger=False)
        assert ms.journal_retention_guard(charts, datetime.now()) == []


# --- wiring into [3b] -----------------------------------------------------------

def test_midas_section_carries_the_clock_offset_line(tmp_path, monkeypatch, capsys):
    """End to end: a fake terminal whose journal holds a probe reading prints
    the offset line in the [3b] section without affecting arm health."""
    import tests.test_morning_status_preset as preset_mod
    root = os.path.join(str(tmp_path), "Term")
    d = os.path.join(root, "FAKEHASH", "MQL5", "Profiles", "Charts", "Default")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "chart01.chr"), "w", encoding="utf-16") as f:
        f.write(preset_mod._chart_text())
    fd = os.path.join(root, "FAKEHASH", "MQL5", "Files")
    os.makedirs(fd, exist_ok=True)
    with open(os.path.join(fd, "MIDASTOUCH_paper_XAUUSD_M1.csv"), "w") as f:
        f.write("ERA,MIDAS1.10,1757894400,pertick-fills\nEQ,50.00\n")
    ld = os.path.join(root, "FAKEHASH", "MQL5", "Logs")
    os.makedirs(ld, exist_ok=True)
    with open(os.path.join(ld, f"{datetime.now():%Y%m%d}.log"), "w", encoding="utf-16") as f:
        f.write(_probe_line(2) + "\r\n")
    sp = os.path.join(str(tmp_path), "state.json")
    monkeypatch.setattr(ms, "TERM_ROOT", root)
    monkeypatch.setattr(ms, "OFFSET_STATE_PATH", sp)
    healthy = ms.print_midas_section()
    out = capsys.readouterr().out
    assert "clock offset: +2 h 00 min server-vs-UTC" in out
    assert healthy is False
    assert json.load(open(sp))["last_offset_min"] == 120
