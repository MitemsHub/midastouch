"""Offline tests for the MIDAS parity harness discipline.

Pins the keyed-alignment law (positional zip is illegal evidence after run3's
150-vs-147 lesson), the fail-closed verdict, and the v2 input contract that the
run3 harness lacked. Nothing here touches a terminal or the tester.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import midas_parity as P   # noqa: E402


def _t(open_ct, close_ct, side, r, reason="TP"):
    return {"open_ct": open_ct, "close_ct": close_ct, "side": side,
            "reason": reason, "r": r}


EA = [_t(100, 200, 1, 1.5), _t(300, 400, -1, -1.0, "SL")]
PY_MATCH = [_t(100, 200, 1, 1.5004), _t(300, 400, -1, -1.001, "SL")]


class TestKeyedCompare:
    def test_pass_on_exact_keys_within_tol(self):
        c = P.keyed_compare(EA, PY_MATCH)
        assert c["verdict"] == "PASS"
        assert c["count_match"] and c["max_abs_dR"] <= P.TOLERANCE

    def test_close_time_shift_fails_even_if_r_matches(self):
        shifted = [PY_MATCH[0], _t(300, 401, -1, -1.001, "SL")]
        c = P.keyed_compare(EA, shifted)
        assert c["verdict"] == "FAIL"
        assert c["close_ct_mismatches"] == [1]

    def test_open_time_shift_fails(self):
        shifted = [_t(101, 200, 1, 1.5004), PY_MATCH[1]]
        c = P.keyed_compare(EA, shifted)
        assert c["verdict"] == "FAIL"
        assert c["open_ct_mismatches"] == [0]

    def test_side_flip_fails_even_if_r_matches(self):
        flipped = [PY_MATCH[0], _t(300, 400, 1, -1.001, "SL")]
        c = P.keyed_compare(EA, flipped)
        assert c["verdict"] == "FAIL"
        assert c["side_mismatches"] == [1]

    def test_count_mismatch_fails(self):
        c = P.keyed_compare(EA, [PY_MATCH[0]])
        assert c["verdict"] == "FAIL"
        assert c["count_match"] is False

    def test_r_over_tolerance_fails(self):
        over = [_t(100, 200, 1, 1.52), PY_MATCH[1]]
        c = P.keyed_compare(EA, over)
        assert c["verdict"] == "FAIL"
        assert c["n_over_tol"] == 1 and c["trades_over_tol"] == [0]

    def test_keyless_journal_source_is_never_pass(self):
        degraded = [_t(None, 200, 1, 1.5), _t(None, 400, -1, -1.0, "SL")]
        c = P.keyed_compare(degraded, PY_MATCH)
        assert c["verdict"] == "FAIL"
        assert c["degraded_keyless_source"] is True

    def test_empty_sides_fail_closed(self):
        c = P.keyed_compare([], [])
        assert c["verdict"] == "FAIL"


class TestInputContract:
    """The v2 pins the run3 harness lacked (InpBarModel, window pins, path)."""

    def test_bar_model_is_pinned_true(self):
        assert P.INPUTS["InpBarModel"] == "true"

    def test_window_pins_equal_python_wf_window(self):
        assert int(P.INPUTS["InpWindowStart"]) == P.T0
        assert int(P.INPUTS["InpWindowEnd"]) == P.T1
        assert P.T0 == P.M.iso_to_ts(P.M.WINDOWS["wf"][0])
        assert P.T1 == P.M.iso_to_ts(P.M.WINDOWS["wf"][1])

    def test_expert_points_at_the_upcomers_layout(self):
        """The deploy path must describe the install being tested.

        It was `MITEMSHUB_AI\\MidastouchAI` — the Deriv-era 49E0 tester's legacy folder,
        correct for that install and meaningless for this one, which resolves by account
        identity. The harness now preflights the path it will launch into, so a stale
        value refuses instead of dying as ex5-not-found after stopping the terminal.
        """
        assert P.EXPERT == r"MIDASTOUCH\MidastouchAI"
        problems, notes = P.preflight(P.EXPERT)
        assert isinstance(problems, list) and isinstance(notes, list)
        # A missing tester root is a note, never a blocker: the first pass creates it,
        # so blocking on it would make the first run on an install impossible.
        assert not any("tester root" in p for p in problems)
        # the tester root follows the resolved install, not the house runner's default
        assert str(P.T.TERMINAL_DATA) == str(P.R.data_folder_for_terminal())
        assert P.MODE == "REVERSE_DIRECTION"
        assert P.INPUTS["InpMode"] == "1"

    def test_paper_equity_matches_python_book(self):
        """The EA's paper-sizing input must equal the basis the python pass is run at.

        This used to assert equality with `M.START_EQUITY` — the research engine's own
        $5,000 corpus basis. That was the bug written down as an invariant: it made the
        sandbox agree with a research convention instead of with the account being
        traded, and it disagreed with the tester's own $1,000 deposit at the same time.
        The invariant is now "both sides use the account's declared basis", asserted
        through the registry rather than through either engine's default.
        """
        import mt5_terminals as _t

        basis = _t.active_account_size()
        assert float(P.INPUTS["InpPaperEquity"]) == basis
        assert P.T._BASE_TESTER_INI["Deposit"] == f"{basis:.0f}"
        assert P.ACCOUNT_BASIS_USD == basis


class TestRegistryMatrix:
    def test_mode_code_map_covers_full_registry(self):
        assert set(P.MODE_CODE) == set(P.M.MODES)
        assert len(set(P.MODE_CODE.values())) == len(P.MODE_CODE)  # unique EA codes
        assert P.MODE_CODE["REVERSE_TRIGGER"] == "2" and P.MODE_CODE["MACRO_ONLY"] == "6"

    def test_tag_mode_codes_unique_and_complete(self):
        assert set(P.TAG_MODE_CODE) == set(P.M.MODES)
        assert len(set(P.TAG_MODE_CODE.values())) == len(P.TAG_MODE_CODE)

    def test_matrix_verdict_requires_every_mode_pass(self):
        recs = [{"mode": "A", "cmp": {"verdict": "PASS"}, "anchor_match": True},
                {"mode": "B", "cmp": {"verdict": "PASS"}, "anchor_match": True}]
        assert P.matrix_verdict(recs) == ("PASS", [])

    def test_matrix_verdict_fails_on_fail_or_anchor_miss(self):
        recs = [{"mode": "A", "cmp": {"verdict": "PASS"}, "anchor_match": True},
                {"mode": "B", "cmp": {"verdict": "FAIL"}, "anchor_match": True},
                {"mode": "C", "cmp": {"verdict": "PASS"}, "anchor_match": False}]
        verdict, why = P.matrix_verdict(recs)
        assert verdict == "FAIL" and why == ["B", "C"]

    def test_sweep_anchor_reads_frozen_sweep(self, tmp_path, monkeypatch):
        p = tmp_path / "sweep.json"
        p.write_text('{"results": {"modes": {"ORIGINAL": {"oos": {"n": 94, "net_r": 6.555}}}}}')
        monkeypatch.setattr(P, "SWEEP_ANCHOR", str(p))
        assert P.sweep_anchor("ORIGINAL", "oos") == {"n": 94, "net_r": 6.555}

    def test_sweep_anchor_missing_is_none_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(P, "SWEEP_ANCHOR", str(tmp_path / "absent.json"))
        assert P.sweep_anchor("ORIGINAL", "oos") is None
