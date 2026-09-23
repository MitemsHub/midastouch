"""Tests for the [3b] preset-identity check (silent-preset-loss guard).

The 2026-09-17 drift incidents (mode/session flip found live at 09:57;
code-defaults reattach at 11:11) are exactly what this check makes impossible
to miss again: the chart's inputs must be byte-exact against the repo .set
pins, and morning status [3b] reports any difference as a PROBLEM.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import morning_status as ms  # noqa: E402

PRESET_KEYS_URL = ms.MIDAS_PRESET


def _preset_input_lines() -> list[str]:
    """The repo .set's Inp lines, verbatim — tests self-maintain against the
    real pin file so a pin edit can never silently invalidate the fixtures."""
    with open(ms.MIDAS_PRESET, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip().startswith("Inp")]


def _chart_text(overrides: dict[str, str] | None = None,
                drop: tuple[str, ...] = (), extra: tuple[str, ...] = ()) -> str:
    """A realistic .chr body: MT5 metadata, group headers, and all 30 inputs."""
    lines = ["; chart", "MidastouchAI", "symbol=XAUUSD", "period_size=15",
             "==== Strategy (frozen protocol defaults) ===="]
    for ln in _preset_input_lines():
        k = ln.split("=", 1)[0]
        if k in drop:
            continue
        if overrides and k in overrides:
            lines.append(f"{k}={overrides.pop(k)}")
        else:
            lines.append(ln)
    if overrides:
        raise AssertionError(f"override keys not in preset: {sorted(overrides)}")
    lines.extend(extra)
    return "\r\n".join(lines) + "\r\n"


class TestPresetIdentityPure:
    def test_ok_on_byte_identical_chart(self):
        r = ms.preset_identity(_chart_text())
        assert r["verdict"] == "OK"
        assert r["n_keys"] == len(_preset_input_lines()) == r["n_chart_keys"]
        assert not (r["missing"] or r["extra"] or r["drift"] or r["problems"])

    def test_value_reformatting_is_drift(self):
        # The reference is the preset's OWN value, read from the pin file (as `_chart_text`
        # already does for every other key), so this fixture cannot rot when a pin legitimately
        # moves — which it did on 2026-09-22 (InpBBDev 2.0 -> 1.5, docs/FREQUENCY_AXES_PREREG
        # _20260922.md). What is asserted is that REFORMATTING is drift; the literal it used to
        # compare against was pinning the value instead, and went stale the moment the pin moved.
        want = dict(ln.split("=", 1) for ln in _preset_input_lines())["InpBBDev"]
        reformatted = f"{float(want):.2f}"
        assert reformatted != want, "the fixture needs a value whose reformatting differs"
        r = ms.preset_identity(_chart_text({"InpBBDev": reformatted}))
        assert r["verdict"] == "DRIFT"
        assert r["drift"] == [("InpBBDev", reformatted, want)]

    def test_pinned_value_change_is_drift(self):
        r = ms.preset_identity(_chart_text({"InpMode": "2"}))
        assert r["verdict"] == "DRIFT"
        assert r["drift"] == [("InpMode", "2", "0")]

    def test_missing_key_is_drift(self):
        r = ms.preset_identity(_chart_text(drop=("InpLiveExecution",)))
        assert r["verdict"] == "DRIFT"
        assert r["missing"] == ["InpLiveExecution"]

    def test_deferred_newer_build_pin_is_not_drift(self):
        """A repo pin owned by a NEWER build than the deployed arms is
        recorded evidence, never drift (2026-09-18 era law): the chart
        legitimately cannot carry InpMaxRiskPct until the next era."""
        r = ms.preset_identity(_chart_text(drop=("InpMaxRiskPct",)))
        assert r["verdict"] == "OK", "deferred pin must not flip the verdict"
        assert r.get("deferred") == ["InpMaxRiskPct"]
        assert any("deferred pin" in p and "MIDAS1.14" in p
                   for p in r["problems"]), "the deferral must cite its owner"
        assert r["missing"] == [], "the missing list stays clean for consumers"

    def test_unknown_missing_pin_is_still_drift(self):
        """Fail-closed half: only pins in DEFERRED_PINS defer. Any other
        missing key is exactly the silent-preset-loss signature."""
        r = ms.preset_identity(_chart_text(drop=("InpMagic",)))
        assert r["verdict"] == "DRIFT"
        assert r["missing"] == ["InpMagic"]

    def test_extra_key_is_drift(self):
        r = ms.preset_identity(_chart_text(extra=("InpFoo=1",)))
        assert r["verdict"] == "DRIFT"
        assert r["extra"] == ["InpFoo"]

    def test_group_headers_and_comments_are_ignored(self):
        r = ms.preset_identity(_chart_text(
            extra=("==== Live execution (only with InpLiveExecution=true) ====",
                   "; a comment line")))
        assert r["verdict"] == "OK"

    def test_conflicting_duplicate_inputs_flagged(self):
        r = ms.preset_identity(_chart_text(extra=("InpMode=2",)))
        assert r["verdict"] == "DRIFT"
        assert any("duplicate input InpMode" in p for p in r["problems"])

    def test_identical_duplicate_rows_are_tolerated(self):
        r = ms.preset_identity(_chart_text(extra=(_preset_input_lines()[0],)))
        assert r["verdict"] == "OK"

    def test_unverifiable_when_repo_preset_missing(self):
        r = ms.preset_identity(_chart_text(), preset_path="Z:/no/such/set")
        assert r["verdict"] == "UNVERIFIABLE"
        assert any("unreadable" in p for p in r["problems"])


class TestMidasSectionIntegration:
    def _write_fixture(self, tmp_path, monkeypatch, chart_txt: str):
        term_root = os.path.join(str(tmp_path), "Term")
        d = os.path.join(term_root, "FAKEHASH", "MQL5", "Profiles", "Charts",
                         "Default")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "chart01.chr"), "w", encoding="utf-16") as f:
            f.write(chart_txt)
        fd = os.path.join(term_root, "FAKEHASH", "MQL5", "Files")
        os.makedirs(fd, exist_ok=True)
        with open(os.path.join(fd, "MIDASTOUCH_paper_XAUUSD_M1.csv"), "w") as f:
            f.write("ERA,MIDAS1.10,1757894400,pertick-fills\nEQ,50.00\n")
        monkeypatch.setattr(ms, "TERM_ROOT", term_root)
        # The coverage-alarm record is machine state; default the fixture to an absent
        # alarm so a real gap on this host can never leak into these tests (measured
        # 2026-09-23: the hibernation gap broke every clean-section assertion here).
        alarm_path = os.path.join(str(tmp_path), "heartbeat_gap_alarm.json")
        monkeypatch.setattr(ms, "COV_ALARM_PATH", alarm_path)
        return alarm_path

    @staticmethod
    def _write_alarm(path: str, *, acked: bool) -> None:
        """A coverage alarm record in live_coverage's own shape, current (raised now)."""
        import json
        from datetime import datetime, timezone
        rec = {
            "episode": "supervision-gap:fixture", "kind": "supervision-gap",
            "raised_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gap_min": 90.0, "from_utc": "2026-09-23T15:28:42Z",
            "to_utc": "2026-09-23T18:35:00Z", "threshold_min": 40, "cadence_min": 20,
            "detail": "fixture: no supervision pass for 90 min",
        }
        if acked:
            rec["acked_utc"] = rec["raised_utc"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f)

    def test_section_reports_preset_ok(self, tmp_path, monkeypatch, capsys):
        self._write_fixture(tmp_path, monkeypatch, _chart_text())
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "inputs byte-identical to repo .set)" in out
        assert "PROBLEM" not in out and healthy is False

    # --- the VPS-era tally fold (runbook §0d) ------------------------------

    LCLOSE_ROW = ("LCLOSE,1790200000,18874164,EXTERNAL,4262.39000,0.10400")

    @staticmethod
    def _live_chart_text() -> str:
        """A .chr body from the LIVE pin file itself (the upcomers LIVE .set — the
        same trick _preset_input_lines uses for the M1 world). A U25 chart is graded
        against preset_for_tag('U25', armed=True); building it from the M1 fixture
        defaults manufactured DRIFT problems that drowned the fold's own signal."""
        with open(ms.MIDAS_PRESET.replace("M1_gold", "upcomers_gold_LIVE"),
                  encoding="utf-8") as f:
            inp = [ln.strip() for ln in f if ln.strip().startswith("Inp")]
        lines = ["; chart", "MidastouchAI", "symbol=XAUUSD", "period_size=15",
                 "==== Strategy (frozen protocol defaults) ===="]
        return "\r\n".join(lines + inp) + "\r\n"

    def _vps_artifact(self, tmp_path, *, verdict="OK", tally=None, ts=None):
        import json
        from datetime import datetime, timedelta, timezone
        p = os.path.join(str(tmp_path), "vps_fills.json")
        art = {"verdict": verdict,
               "ts": ts or datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if tally is not None:
            art["tally"] = tally
        if verdict == "FAIL":
            art["problems"] = ["era is active but the venue cannot be read"]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(art, f)
        return p

    @staticmethod
    def _enter_vps_era(monkeypatch, tmp_path, vps_fills_path, *, era=True):
        import midas_watchdog as W
        monkeypatch.setattr(ms, "VPS_FILLS_PATH", vps_fills_path)
        monkeypatch.setattr(W, "vps_hosting_active", lambda: era)

    def _live_arm_with_lclose(self, tmp_path, monkeypatch) -> None:
        """The fold prints inside the LIVE arm's closed-block, so the fixture is a
        live-chart world: tag U25 (the ledger name follows the tag — an M1 chart
        looks for _M1.csv and reports MISSING), one consistent fill seen by BOTH
        sides (an LCLOSE row plus its IN/OUT deals, so the reconciliation agrees
        instead of manufacturing a PROBLEM of its own), and the synthetic reader
        so nothing reaches this machine's real account (the 2026-09-22 lesson)."""
        from types import SimpleNamespace
        self._write_fixture(tmp_path, monkeypatch, self._live_chart_text())
        led = os.path.join(str(tmp_path), "Term", "FAKEHASH", "MQL5", "Files",
                           "MIDASTOUCH_paper_XAUUSD_U25.csv")
        with open(led, "w", encoding="utf-8") as f:
            f.write("ERA,MIDAS1.19,1789956934,pertick-fills\nEQ,25000.00\n"
                    # the fill BOTH sides saw, in the real row grammar (order = the
                    # venue's position id), then its adopted close
                    "LOPEN,1790170200,0,18874164,0,-1,4306.19000,4327.54000,"
                    "4262.39000,0.02,43.43,21.71714,43200,U25,1790169300,11,"
                    "0.70381,out,120,cfg=62.51@0.25\n"
                    + self.LCLOSE_ROW + "\n")

        def deals(*a, **k):
            # the same fill the LCLOSE row records: IN carries the magic, the
            # platform OUT carries magic 0 (the venue's real stamping)
            return [SimpleNamespace(ticket=18137411, magic=7825001, entry=0,
                                    position_id=18874164),
                    SimpleNamespace(ticket=18138688, magic=0, entry=1,
                                    position_id=18874164)]
        monkeypatch.setattr(ms, "LIVE_FILL_DEAL_READER", deals)
        import midas_watchdog as W
        ff = os.path.join(str(tmp_path), "first_fill.json")  # this world's own record
        with open(ff, "w", encoding="utf-8") as f:
            f.write('{"recorded_utc": "2026-09-23T00:00:00Z", "ledger_fills": 1, '
                    '"account_identifiers": 1, "first_ledger_row": "fixture"}')
        monkeypatch.setattr(W, "FIRST_FILL_PATH", ff)

    def test_out_of_era_prints_no_vps_line(self, tmp_path, monkeypatch, capsys):
        """The fold exists only where LCLOSE rows cannot — out of era it is absent."""
        self._write_fixture(tmp_path, monkeypatch, _chart_text())
        ms.print_midas_section()
        assert "vps era" not in capsys.readouterr().out

    def test_era_without_artifact_is_a_yellow_note_not_a_problem(self, tmp_path, monkeypatch, capsys):
        """The marker is set BEFORE the migration completes, so an era window with
        nothing yet ingested is normal — a note, never a PROBLEM."""
        self._live_arm_with_lclose(tmp_path, monkeypatch)
        missing = os.path.join(str(tmp_path), "vps_fills.json")  # never written
        self._enter_vps_era(monkeypatch, tmp_path, missing)
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "no vps_fills.json yet" in out
        assert "PROBLEM" not in out and healthy is False

    def test_era_with_failing_artifact_is_a_problem(self, tmp_path, monkeypatch, capsys):
        """FAIL means the venue went dark on the ingest: the tally is blind again —
        the exact state the ingest exists to prevent, so it must surface as PROBLEM."""
        self._live_arm_with_lclose(tmp_path, monkeypatch)
        p = self._vps_artifact(tmp_path, verdict="FAIL")
        self._enter_vps_era(monkeypatch, tmp_path, p)
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "ingest FAILED" in out
        assert "PROBLEM" in out and healthy is True

    def test_era_with_stale_artifact_is_a_problem(self, tmp_path, monkeypatch, capsys):
        from datetime import datetime, timedelta, timezone
        self._live_arm_with_lclose(tmp_path, monkeypatch)
        old = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat(timespec="seconds")
        p = self._vps_artifact(tmp_path, tally={"closed": 1, "wins": 1, "sum_r": 0.2},
                               ts=old)
        self._enter_vps_era(monkeypatch, tmp_path, p)
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "stale" in out
        assert "PROBLEM" in out and healthy is True

    def test_era_with_healthy_artifact_folds_the_tally(self, tmp_path, monkeypatch, capsys):
        """THE contract: ledger LCLOSE rows (1 in the fixture) plus the venue-
        attributed VPS-era closes (2) print as the COMBINED tally 3/30."""
        self._live_arm_with_lclose(tmp_path, monkeypatch)
        p = self._vps_artifact(tmp_path, tally={"closed": 2, "wins": 1, "sum_r": 0.35})
        self._enter_vps_era(monkeypatch, tmp_path, p)
        ms.print_midas_section()
        out = capsys.readouterr().out
        assert "2 VPS-era closed position(s)" in out
        assert "1W/1L" in out and "sumR +0.35" in out
        assert "tally 3/30 includes them" in out

    def test_section_flags_drift_as_unhealthy(self, tmp_path, monkeypatch, capsys):
        self._write_fixture(tmp_path, monkeypatch,
                            _chart_text({"InpMode": "2"}))
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "preset DRIFT: InpMode=2 (repo pin 0)" in out
        assert healthy is True

    def test_unacked_alarm_is_a_problem_in_the_section(self, tmp_path, monkeypatch, capsys):
        """A current, unacknowledged coverage alarm reads as PROBLEM and marks the
        section unhealthy — pinned with a fixture, not with the host's real record
        (which is exactly what the 2026-09-23 hibernation gap proved necessary)."""
        alarm_path = self._write_fixture(tmp_path, monkeypatch, _chart_text())
        self._write_alarm(alarm_path, acked=False)
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "coverage: PROBLEM: supervision-gap" in out
        assert healthy is True, "a PROBLEM line makes the section unhealthy"

    def test_acked_alarm_is_recorded_not_current(self, tmp_path, monkeypatch, capsys):
        """An acknowledged alarm keeps its history visible (the night happened and
        stays answerable) but no longer reads as a current PROBLEM."""
        alarm_path = self._write_fixture(tmp_path, monkeypatch, _chart_text())
        self._write_alarm(alarm_path, acked=True)
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "coverage: past: supervision-gap" in out
        assert "acknowledged" in out
        assert "PROBLEM" not in out
        assert healthy is False


class TestShadowRecordSection:
    """[3b.1] quotes the published sweep-shadow artifact — and imports nothing
    from the research layer, so the surface audit's 0-dangling gate holds."""

    @staticmethod
    def _artifact(path, **over):
        import json
        d = {"harness": "midas_sweep_shadow.py",
             "ts": "2026-09-23T07:45:00+00:00",
             "verdict": "ACCUMULATING",
             "rule": {"variant": "SWEEP_CONT", "n_target": 60},
             "checks": {"rows_total": 3, "rows_in_window": 3, "coverage": 1.0,
                        "n_disagreements": 0, "n_unmatched": 0},
             "forward": {"results": {"SWEEP_CONT": {"n": 0}}}}
        d.update(over)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        return path

    def test_no_artifact_is_reported_not_fatal(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ms, "SHADOW_ART", os.path.join(str(tmp_path), "absent.json"))
        ms.print_shadow_record()
        out = capsys.readouterr().out
        assert "no forward record" in out

    def test_artifact_is_quoted_with_counts(self, tmp_path, monkeypatch, capsys):
        art = self._artifact(os.path.join(str(tmp_path), "sweep_shadow_forward.json"))
        monkeypatch.setattr(ms, "SHADOW_ART", art)
        ms.print_shadow_record()
        out = capsys.readouterr().out
        assert "ACCUMULATING" in out and "N=0 of 60 resolved (SWEEP_CONT)" in out
        assert "coverage 1.0" in out and "disagreements 0" in out and "unmatched 0" in out

    def test_corrupt_artifact_reads_as_absent(self, tmp_path, monkeypatch, capsys):
        art = os.path.join(str(tmp_path), "sweep_shadow_forward.json")
        with open(art, "w", encoding="utf-8") as f:
            f.write("{not json")
        monkeypatch.setattr(ms, "SHADOW_ART", art)
        ms.print_shadow_record()
        assert "no forward record" in capsys.readouterr().out
