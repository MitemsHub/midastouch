"""One clock for the parity contract: declared in UTC, translated at the EA boundary.

WHY THIS FILE EXISTS. The EA evaluates its gates against bar epochs, and those epochs
are the **venue's server time**. The python engine's are UTC. For the whole life of the
`wf` comparison the two were compared directly, so every key was off by the server's
offset — and that offset *moves*: measured from this venue's own bars it is **+60 min**
in Jan–Mar 2026 and **+120 min** from April, because the server follows EU DST.

Two things are pinned here, and the second is the one that catches a venue that
changes its clock:

1. **The translation itself** — gates the EA reads as epochs are shifted INTO server
   time on the way in, and the EA's ledger epochs are shifted BACK to UTC on the way
   out. Fixing only one of the two leaves the EA trading a session hours away from the
   one python models, which looks like a strategy disagreement and is not one.
2. **The refusal** — a window that crosses the DST step has no single correct offset,
   so it refuses rather than being mis-aligned on one side of the step while looking
   fixed. `wf` is exactly that window, which is why the re-run uses `oos`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_parity as P  # noqa: E402

OOS = P._window_spec("oos")
WF = P._window_spec("wf")


class TestMeasurement:
    def test_the_oos_window_has_one_constant_offset(self):
        measured, per_month = P.measure_server_offset_min(OOS["t0"], OOS["t1"])
        assert measured == 120, (
            f"the venue's server was measured at {measured} min from UTC over the `oos` "
            f"window; per-month evidence: {per_month}")
        assert set(per_month.values()) == {120}, per_month

    def test_the_wf_window_is_wholly_on_the_other_side_of_the_step(self):
        """`wf` ends 2026-03-31, before the DST change, so it is uniformly +60.

        Worth pinning because the tester calendar runs to 2026.04.03 while the research
        window stops at 03-31, and a reader who confuses the two would conclude the
        window crosses the step. The measurement is what settles it.
        """
        measured, per_month = P.measure_server_offset_min(WF["t0"], WF["t1"])
        assert measured == 60, per_month
        assert set(per_month.values()) == {60}, per_month

    def test_a_window_spanning_the_step_has_no_single_offset(self):
        """Not a bug in the measurement: a window either side of April genuinely has
        no one answer, and the caller is told that rather than handed a guess."""
        measured, per_month = P.measure_server_offset_min(
            P.M.iso_to_ts("2026-03-15"), P.M.iso_to_ts("2026-05-15"))
        assert measured is None, per_month
        assert len(set(per_month.values())) > 1, per_month

    def test_measurement_refuses_rather_than_guessing_without_a_corpus(self, tmp_path,
                                                                     monkeypatch):
        monkeypatch.setattr(P.M, "DATA_DIR", str(tmp_path / "empty"))
        with pytest.raises(SystemExit) as exc:
            P.measure_server_offset_min(OOS["t0"], OOS["t1"])
        assert "cannot assert the server clock" in str(exc.value)


class TestAssertion:
    def test_the_oos_pin_is_asserted_against_the_venue(self):
        assert P.assert_server_offset(OOS) == 120

    def test_a_cross_step_window_refuses(self):
        """No certified window does this today; the refusal exists so that if one ever
        does, it says so instead of mis-aligning every key on one side of April."""
        crossing = {"window_name": "synthetic", "server_offset_min": None,
                    "t0": P.M.iso_to_ts("2026-03-15"), "t1": P.M.iso_to_ts("2026-05-15")}
        with pytest.raises(SystemExit) as exc:
            P.assert_server_offset(crossing)
        msg = str(exc.value)
        assert "cannot be put on one clock" in msg
        assert "DST" in msg

    def test_a_stale_pin_refuses_rather_than_re_aligning_every_key(self, monkeypatch):
        """The failure mode the assertion exists for: the venue restores its clock and
        a pinned number silently mis-aligns every key instead of reporting the change."""
        stale = {**OOS, "server_offset_min": 60}
        with pytest.raises(SystemExit) as exc:
            P.assert_server_offset(stale)
        msg = str(exc.value)
        assert "pins the server offset at +60" in msg
        assert "measure +120" in msg


class TestTheContractIsDeclaredInUtc:
    def test_the_gates_the_ea_reads_as_epochs_move_into_server_time(self):
        inputs = P.build_inputs("REVERSE_DIRECTION", OOS["t0"], OOS["t1"], offset_min=120)
        assert inputs["InpSessionStartHour"] == "8"      # 06:00 UTC in server time
        assert inputs["InpSessionEndHour"] == "22"       # 20:00 UTC in server time
        assert inputs["InpFridayCutoffHour"] == "22"
        assert int(inputs["InpWindowStart"]) == OOS["t0"] + 120 * 60
        assert int(inputs["InpWindowEnd"]) == OOS["t1"] + 120 * 60

    def test_offset_zero_is_still_the_contract_of_record(self):
        """The module-level INPUTS is the UTC-declared contract and is pinned by
        tests/test_midas_parity.py; normalising the run must not rewrite it."""
        assert P.build_inputs("REVERSE_DIRECTION", P.T0, P.T1) == P.INPUTS
        assert P.INPUTS["InpSessionStartHour"] == "6"
        assert int(P.INPUTS["InpWindowStart"]) == P.T0


class TestEpochsComeBackToUtc:
    def test_epochs_shift_by_the_offset_and_nothing_else_moves(self):
        ea = [{"open_ct": 1_800_000_000, "close_ct": 1_800_003_600,
               "side": -1, "reason": "TP", "r": 1.75}]
        out = P.to_utc(ea, 120)
        assert out[0]["open_ct"] == 1_800_000_000 - 7200
        assert out[0]["close_ct"] == 1_800_003_600 - 7200
        # the frame-independent fields are the EA's own measurements
        assert (out[0]["side"], out[0]["reason"], out[0]["r"]) == (-1, "TP", 1.75)
        assert ea[0]["open_ct"] == 1_800_000_000, "the input list was mutated in place"

    def test_a_keyless_fallback_trade_stays_keyless(self):
        """The degraded journal fallback has no epochs; re-stamping them would invent
        keys that were never read, and `keyed_compare` must still mark it degraded."""
        out = P.to_utc([{"open_ct": None, "close_ct": None, "side": None,
                         "reason": "?", "r": 0.5}], 120)
        assert out[0]["open_ct"] is None and out[0]["close_ct"] is None

    def test_server_and_python_epochs_land_on_the_same_key(self):
        """The property the whole normalisation is for: the SAME trade, stamped by each
        side in its own clock, must produce identical keys after the conversion."""
        py_open, py_close = 1_780_000_000, 1_780_003_600     # python, in UTC
        server_shift = 120 * 60
        ea = [{"open_ct": py_open + server_shift,               # the same trade,
               "close_ct": py_close + server_shift,             # stamped by the venue
               "side": 1, "reason": "TP", "r": 1.0}]
        py = [{"open_ct": py_open, "close_ct": py_close,
               "side": 1, "reason": "TP", "r": 1.0}]

        aligned = P.to_utc(ea, 120)
        cmp = P.keyed_compare(aligned, py)
        assert cmp["open_ct_mismatches"] == [] and cmp["close_ct_mismatches"] == []
        assert cmp["verdict"] == "PASS", cmp

        # ...and that without the conversion the very same evidence fails on keys.
        assert P.keyed_compare(ea, py)["open_ct_mismatches"] == [0]

    def test_offset_zero_is_a_no_op(self):
        ea = [{"open_ct": 10, "close_ct": 20, "side": 1, "reason": "SL", "r": -1.0}]
        assert P.to_utc(ea, 0) == ea
