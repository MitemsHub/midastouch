"""Pins for v1.23: the venue self-inconsistency prints once per session / on change,
and the evidence survives in the ledger (the keyed `SPEC` row).

THE COMPLAINT, REPRODUCED FROM THE SOURCE. `DollarPerUnitPerLot()` printed
`TICK VALUE MISMATCH` on EVERY call, and on the live arm the 15-minute heartbeat calls
that function twice (the STATE row writer and the HUD refresh), every evaluated bar
calls it again, and the sizing sites add one per attempt — so the same two static
numbers re-printed all day and buried the `VETO`/`NOFILL` refusals the journal exists
to carry. The warning is now gated by `SpecMoved()` — first observation of the session,
or a material move in either number — and those same moments append a `SPEC` row, so
quieting the journal does not lose the evidence.

The pins are structural (MQL5 cannot run here) plus a pure round-trip of the reader:
the gate must stay between the caller and the print, the record must be written where
the print is (not on a clock), the row must stay keyed, and a no-op change to the
numbers must not reactivate the line.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    return re.sub(r"//[^\n]*", "", s)


def body(fn_name: str) -> str:
    """Brace-matched body of a named function DEFINITION (any return type).

    Anchored at the line start: `DollarPerUnitPerLot` is also called by the
    `DollarPerUnit()` wrapper earlier in the file, and a bare-word match would return
    the wrapper's neighbourhood instead of the function (measured while writing this
    pin — the first version of it did exactly that).
    """
    s = src()
    m = re.search(rf"(?m)^\w+\s+{re.escape(fn_name)}\s*\(", s)
    assert m, f"{fn_name} missing from source"
    j = s.index("{", m.end())
    depth = 0
    for k in range(j, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return s[j:k]
    raise AssertionError(f"unbalanced braces after {fn_name}")


def _morning_status():
    sys.path.insert(0, str(REPO / "scripts"))
    import morning_status as ms
    return ms


# --- the gate: the print cannot be reached without it --------------------------

def test_every_mismatch_print_rides_the_session_gate() -> None:
    """Both lines (first observation and CHANGED) live inside `if(SpecMoved(...))`.

    Restoring the v1.22 shape — a bare `PrintFormat` on the mismatch condition — drops
    `SpecMoved(` out of the path and fails here, which is the defect this file pins.
    """
    b = body("DollarPerUnitPerLot")
    assert b.count("TICK VALUE MISMATCH") == 2, \
        "one line for the first observation and one for a change; a third is a new site"
    gate = b.index("if(SpecMoved(")
    assert b.index("TICK VALUE MISMATCH") > gate
    assert b.rindex("TICK VALUE MISMATCH") > gate
    # and the session state advances AT the print, so the next call with the same pair
    # of numbers is silent — the whole point of the change
    tail = b[b.rindex("TICK VALUE MISMATCH"):]
    assert "g_spec_warn_broker = via_tv" in tail and "g_spec_warn_used   = out" in tail


def test_spec_moved_is_first_observation_or_a_material_move() -> None:
    b = strip_comments(body("SpecMoved"))
    assert "g_spec_warn_broker <= 0.0" in b and "g_spec_warn_used <= 0.0" in b, \
        "the first observation of the session must return true"
    assert "return true" in b.split("MathAbs", 1)[0], \
        "the no-record case returns before any tolerance arithmetic"
    for var in ("g_spec_warn_broker", "g_spec_warn_used"):
        assert re.search(rf"MathAbs\([^)]*\)\s*/\s*{var}\s*>\s*0\.005", b), \
            f"{var} must be compared with a relative 0.5% band"
    # the globals exist and start at zero, so an EA init IS a new session
    s = src()
    assert "double g_spec_warn_broker = 0.0;" in s
    assert "double g_spec_warn_used   = 0.0;" in s


# --- the record: same moments as the print, and never on a clock ----------------

def test_the_record_is_written_at_the_print_not_on_a_clock() -> None:
    b = body("DollarPerUnitPerLot")
    assert "SpecRecord(" in b, "the record must be written by the observation itself"
    i_print = b.rindex("TICK VALUE MISMATCH")
    i_rec = b.index("SpecRecord(")
    i_state = b.index("g_spec_warn_broker = via_tv")
    assert i_print < i_rec < i_state, \
        "print -> record -> advance the session state, in that order"
    # no timer-driven writer: a SPEC row is a consequence of observing the venue, not
    # of the heartbeat being due (the heartbeat would just be the spam again, in a file)
    assert "SpecRecord" not in body("OnTimer")
    assert "SpecRecord" not in body("DiagMaybeWrite")


def test_the_record_is_gated_out_of_the_parity_paths() -> None:
    b = body("SpecRecord")
    head = b[:b.index("PaperLog(")]
    assert "MQL_TESTER" in head, "tester runs must not write SPEC rows"
    assert "InpBarModel" in head, "the BAR replay ledger is a reproduction artifact"
    assert "TimeUTCNow()" in b, \
        "the row is stamped on the same live UTC clock as the STATE row"


def test_the_row_is_keyed_and_only_the_epoch_is_positional() -> None:
    """Keyed fields, because the NOFILL mislabel (2026-09-21) was a writer/reader
    column-order disagreement that a permutation of zeros made invisible."""
    ms = _morning_status()
    b = body("SpecRecord")
    literal = re.search(r'"SPEC,([^"]+)"', b)
    assert literal, "SPEC row format literal not found"
    fmt = literal.group(1)
    specs = re.findall(r"%I64[du]|%[-0-9.]*[dfs]", fmt)
    assert specs[0] == "%I64d", "the row's own epoch is the only positional value"
    assert specs.count("%I64d") == 1 and len(specs) == 1 + len(ms.SPEC_FIELDS)
    for key in ms.SPEC_FIELDS:
        assert f"{key}=%" in fmt, f"field {key!r} must be keyed, not a column"


# --- the reader: keyed, complete, and loud about nothing -----------------------

def test_spec_reader_round_trips_and_refuses_partial_rows(tmp_path) -> None:
    ms = _morning_status()
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "ERA,MIDAS1.23,1,note\n"
        "SPEC,1700000000,tv=0.10000,ts=0.01000,cs=100.00,broker=10.00,"
        "settled=100.0000,used=100.0000,ratio=0.1000\n"
        # a SHORT row is ignored, never partially believed — the last COMPLETE row wins
        "SPEC,1700000100,tv=0.10000,ts=0.01000,cs=100.00,broker=10.00\n"
        # and an unparsable value cannot poison the dict either
        "SPEC,1700000200,tv=not-a-number,ts=0.01000,cs=100.00,broker=10.00,"
        "settled=100.0000,used=100.0000,ratio=0.1000\n",
        encoding="utf-8")
    row = ms.spec_last(str(ledger))
    assert row is not None
    assert row["ct"] == 1700000000
    assert row["broker"] == pytest.approx(10.0)
    assert row["settled"] == pytest.approx(100.0)
    assert row["used"] == pytest.approx(100.0)
    assert row["ratio"] == pytest.approx(0.10)
    assert all(k in row for k in ms.SPEC_FIELDS)
    # a later COMPLETE row wins
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write("SPEC,1700000300,tv=0.10000,ts=0.01000,cs=100.00,broker=10.00,"
                 "settled=0.0000,used=100.0000,ratio=0.1000\n")
    row2 = ms.spec_last(str(ledger))
    assert row2 is not None and row2["ct"] == 1700000300
    assert row2["settled"] == pytest.approx(0.0)
    # a ledger with no SPEC row answers nothing, not zeros
    empty = tmp_path / "empty.csv"
    empty.write_text("ERA,MIDAS1.23,1,note\nEQ,25000.00\n", encoding="utf-8")
    assert ms.spec_last(str(empty)) is None


def test_spec_text_names_the_authority_it_sized_on() -> None:
    ms = _morning_status()
    settled = ms.spec_text({"settled": 100.0, "cs": 100.0, "broker": 10.0,
                            "ratio": 0.10, "used": 100.0})
    assert "10.00" in settled and "100.00" in settled and "settled value" in settled
    geometry = ms.spec_text({"settled": 0.0, "cs": 100.0, "broker": 10.0,
                             "ratio": 0.10, "used": 100.0})
    assert "geometry" in geometry and "order_calc_profit unavailable" in geometry


def test_parse_ledger_tolerates_the_spec_row(tmp_path) -> None:
    """The new row type must be invisible to the existing readers, not a corruption."""
    ms = _morning_status()
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "ERA,MIDAS1.23,1,note\n"
        "SPEC,1700000000,tv=0.10000,ts=0.01000,cs=100.00,broker=10.00,"
        "settled=100.0000,used=100.0000,ratio=0.1000\n"
        "EQ,25000.00\n", encoding="utf-8")
    parsed = ms.parse_ledger(str(ledger))
    assert parsed["veq_last"] == pytest.approx(25000.0)
    assert parsed["problems"] == []


# --- the era note: a reader must know the ledger can carry the record ----------

def test_the_era_note_cites_the_spec_record() -> None:
    s = src()
    assert 'era_note += "+spec-record";' in s, \
        "v1.23 must cite the register in its ERA note (§1 never-abort class)"
    idx = s.find('era_note += "+spec-record";')
    assert "if(!InpBarModel)" in s[idx - 200:idx], \
        "the citation rides the paper/live path only, like the rest of the chain"
