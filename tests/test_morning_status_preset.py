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
        r = ms.preset_identity(_chart_text({"InpBBDev": "2.00"}))
        assert r["verdict"] == "DRIFT"
        assert r["drift"] == [("InpBBDev", "2.00", "2.0")]

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

    def test_section_reports_preset_ok(self, tmp_path, monkeypatch, capsys):
        self._write_fixture(tmp_path, monkeypatch, _chart_text())
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "inputs byte-identical to repo .set)" in out
        assert "PROBLEM" not in out and healthy is False

    def test_section_flags_drift_as_unhealthy(self, tmp_path, monkeypatch, capsys):
        self._write_fixture(tmp_path, monkeypatch,
                            _chart_text({"InpMode": "2"}))
        healthy = ms.print_midas_section()
        out = capsys.readouterr().out
        assert "preset DRIFT: InpMode=2 (repo pin 0)" in out
        assert healthy is True
