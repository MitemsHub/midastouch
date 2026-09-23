"""The v1.28 record build: the sweep shadow, recorded and never traded.

WHY THIS FILE EXISTS. `docs/ASIA_SWEEP_PREREG_20260922.md` REFUSED to port the Asian-range
sweep continuation — its pre-registered primary window failed on all three variants — and
the same run reported the strongest number in this program on its SECONDARY window (UTC
07-18: 152 held-out trades, +0.1955R, pf 1.499, t +2.21), with the mirror image at -0.1584R
and the textbook reversal read at -0.1425R. It prescribed exactly one next step: record it
forward, with NO ORDER PATH AT ALL, and read it after enough trades accumulate.

This file pins that the build does exactly that and nothing more. The load-bearing tests are
the last three: the shadow is reachable from ONE place, no decision function mentions it, and
the row it writes cannot contain an outcome. Those are what make a record-only build a
structural claim rather than a promise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
PREREG = REPO / "docs" / "ASIA_SWEEP_FORWARD_PREREG_20260922.md"
sys.path.insert(0, str(REPO / "scripts"))

#: Everything that decides, sizes, vetoes, protects or closes. The shadow may be referenced
#: by NONE of them, and this list is the whole claim the build makes.
DECISION_FUNCTIONS = (
    "ModeDecide", "TriggerOnClosedBar", "MacroState", "PropGovernorBlock", "PropPhaseCheck",
    "LiveSendOrder", "LiveCheckExits", "LiveFridayFlatCheck", "LiveTimeoutCheck",
    "PaperOpen", "PaperCheckExits", "SizingNumbers", "SpreadCapOK", "InpSessionStartHour",
)


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    return re.sub(r"//[^\n]*", "", s)


def body(fn_name: str) -> str:
    """Brace-matched body of a named function (any return type)."""
    s = src()
    m = re.search(rf"\b\w+\s+{re.escape(fn_name)}\s*\(", s)
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
    raise AssertionError(f"unbalanced braces in {fn_name}")


# --- 1. the build states its own number ----------------------------------------------

def test_the_version_property_and_define_are_one_number():
    s = strip_comments(src())
    prop = re.search(r'#property version\s+"([\d.]+)"', s)
    app = re.search(r'#define APP_VERSION\s+"MIDAS([\d.]+)"', s)
    assert prop and app
    # The value moves with every build (v1.29's exit-reason word did); the invariant this
    # file has always pinned is that the two CANNOT disagree. The v1.29-specific pins live
    # in tests/test_midas_v129_record.py.
    assert prop.group(1) == app.group(1), (prop.group(1), app.group(1))


def test_the_era_note_names_the_new_row_type():
    """A reader of this arm's book meets a row it has not seen, and the note says so."""
    s = src()
    assert "+sweep-shadow" in s, "the ERA note must name the new row type"
    # v1.29 appended a fifth record-only field (+exit-reason) to the SAME note, so the
    # literal below is the note as it now stands — and the sweep-shadow token must survive
    # every future append, or a reader keyed on it silently mis-dates the ledger.
    assert re.search(r'era_note \+= "\+census10\+state-ctx\+spread-hour\+sweep-shadow\+exit-reason"', s), \
        "the record-only appends are one note, in one place"
    # ...and it is the LAST append before the ERA row is written, so a reader that keys on
    # the end of the note is not moved by a field added in front of it.
    last_append = max(m.start() for m in re.finditer(r"era_note \+=", s))
    era_write = s.index('PaperLog(StringFormat("ERA,')
    assert last_append < era_write, "the sweep-shadow field is appended BEFORE the ERA row"
    assert s[last_append:era_write].count("era_note +=") == 1, \
        "nothing else may be appended after the sweep-shadow field"


# --- 2. the mechanism, and the window it claims ---------------------------------------

def test_the_window_is_the_one_the_study_measured():
    s = strip_comments(src())
    assert "#define SWEEP_WINDOW_LO   7" in s
    assert "#define SWEEP_WINDOW_HI   18" in s
    # ...and the EA and the engine of record state the same window: one definition lives
    # here, the other in scripts/midas_sweep.py, and the pre-registration names both.
    import midas_sweep as M
    assert (M.SWEEP_WINDOW[0], M.SWEEP_WINDOW[1]) == (7, 18)


def test_the_range_is_closed_before_the_window_opens():
    """00:00-06:45 is the range; 07:00 is the first bar that may sweep it."""
    b = body("SweepShadowFor")
    assert "day0 + 7 * 3600" in b, "the range is bounded at 07:00 UTC"
    assert "day0 + 6 * 3600" not in b, "and NOT at 06:00 — 06:45 is the last range bar"


def test_the_sweep_scan_can_never_read_a_later_bar():
    """Non-repainting, stated in the source and pinned by behaviour in test_sweep_shadow."""
    b = body("SweepShadowFor")
    assert "if(r[k].time >= sig_open) continue;" in b, \
        "every scan must skip this bar and anything later"
    # The bar's own sweep is read from the element whose stamp IS the signal bar — found by
    # stamp rather than by index, because the copy's element ordering is not assumed.
    assert "r[k].time == sig_open" in b


def test_the_first_sweep_of_the_day_on_that_side_is_the_only_signal():
    b = body("SweepShadowFor")
    assert "earlier_this_side" in b
    assert "side = up ? 1 : -1" in b, "SWEEP_CONT is WITH the break"


# --- 3. what the row says, and what it must never say ---------------------------------

def test_the_row_has_thirteen_fields_and_no_outcome():
    """The EA writes the SETUP. An outcome is the resolver's, because the EA cannot know it."""
    b = body("SweepShadowRow")
    literal = re.search(r'"SWEEPSHADOW,([^"]+)"', b)
    assert literal, "SWEEPSHADOW row format literal not found"
    specs = re.findall(r"%I64[du]|%[-0-9.]*[dfs]", literal.group(1))
    # 12 values, plus the leading `SWEEPSHADOW` tag = the 13 comma-separated fields the
    # resolver splits on. Counted in one place so a field added on one side without the
    # other fails here rather than in a ledger nobody re-reads.
    assert len(specs) == 12, specs
    import midas_sweep_shadow as ss
    assert len(specs) + 1 == ss.ROW_FIELDS == 13, (len(specs), ss.ROW_FIELDS)
    assert literal.group(1).count("%s") == 1, "only the version tag is a string"
    # No R, no price the trade would have exited at, no P&L: the row cannot contain a claim
    # its writer could not have measured.
    for forbidden in ("r=", "pnl", "exit", "R="):
        assert forbidden not in literal.group(1), f"the row must not carry `{forbidden}`"


def test_the_stop_distance_reuses_the_arm_s_own_geometry():
    """`InpSlAtrMult x AtrNow()` — the same value the entry path sizes from, not a restatement."""
    b = body("SweepShadowRow")
    assert "InpSlAtrMult * AtrNow()" in b


# --- 4. the load-bearing property: it cannot move a trade -----------------------------

def test_the_shadow_is_called_from_exactly_one_place():
    s = strip_comments(src())
    calls = [m.start() for m in re.finditer(r"\bSweepShadowRow\(\)", s)]
    # one definition (inside `void SweepShadowRow()`), one call
    assert len(calls) == 2, f"expected the definition and ONE call site, found {len(calls)}"
    # and that call site is inside the per-bar evaluator, not the init heartbeat
    tfb = body("TrackFreshM15Bar")
    assert "SweepShadowRow();" in tfb, "the shadow rides the SAME evaluated bar as the STATE row"
    start = s.index("void TrackFreshM15Bar")
    end = start + len(tfb) + 2
    assert all(start <= c <= end for c in calls[1:]), "no call outside TrackFreshM15Bar"


def test_no_decision_function_mentions_the_shadow():
    """The build is record-only, structurally: nothing that decides can see it."""
    s = strip_comments(src())
    for fn in DECISION_FUNCTIONS:
        if re.search(rf"\b\w+\s+{re.escape(fn)}\s*\(", s) is None:
            continue                     # an input name, or a function this build does not have
        if fn == "InpSessionStartHour":
            continue                     # an input, not a function body
        b = body(fn)
        for token in ("SweepShadow", "g_sw_", "SWEEP_WINDOW"):
            assert token not in b, f"{fn} must not read the shadow (`{token}`)"


def test_the_shadow_writes_nothing_but_a_ledger_line():
    b = body("SweepShadowRow")
    for forbidden in ("OrderSend", "PositionClose", "PropGovernor", "g_nofill_", "g_pv_",
                      "g_lv_posid", "Trade.Buy", "Trade.Sell", "g_last_action"):
        assert forbidden not in b, f"the shadow must not touch `{forbidden}`"
    assert b.count("PaperLog(") == 1, "one row, one writer"


def test_it_is_gated_out_of_parity_and_tester_runs():
    """Certified parity ledgers must stay byte-identical, exactly as v1.27's writes do."""
    b = body("SweepShadowRow")
    assert "MQLInfoInteger(MQL_TESTER)" in b
    assert "InpBarModel" in b
    # and it returns false — writes no row — when no offset may be named
    bf = body("SweepShadowFor")
    assert "STATE_OFF_UNKNOWN" in bf, "no frame, no claim"


# --- 5. the operator's side: the morning report says how much is recorded -----------------

def _shadow_ledger(tmp: Path, rows: list[str]) -> str:
    p = tmp / "ledger.csv"
    p.write_text("ERA,MIDAS1.29,1,+census10+state-ctx+spread-hour+sweep-shadow+exit-reason\n"
                 + "\n".join(rows) + "\n", encoding="utf-8")
    return str(p)


def _row(sig_open: int, side: int, off: int = 120) -> str:
    return (f"SWEEPSHADOW,{sig_open},{sig_open},20718,105.00000,99.50000,28,{side},"
            f"{1 if side else 0},0,41.31000,{off},MIDAS1.29")


def test_the_shadow_reader_counts_rows_and_setups_separately(tmp_path):
    """Rows measure the arm's uptime; `fired` is the setup count. They are not the same number,
    and a reader that conflated them could not tell "nothing swept" from "nothing ran"."""
    import morning_status as ms

    path = _shadow_ledger(tmp_path, [_row(1000, 0), _row(2000, 1), _row(3000, 0)])
    got = ms.sweep_shadow_last(path)
    assert got["rows"] == 3 and got["fired"] == 1
    assert got["last"]["sig_open"] == 3000 and got["last"]["side"] == 0
    assert "3 row(s), 1 with a sweep" in ms.sweep_shadow_text(got)


def test_the_shadow_reader_says_so_when_there_are_no_rows(tmp_path):
    """The honest answer on a book written by an earlier build, not `None` and not a zero line."""
    import morning_status as ms

    got = ms.sweep_shadow_last(_shadow_ledger(tmp_path, []))
    assert got == {"rows": 0, "fired": 0, "unreadable": 0, "last": None}
    assert "no rows yet" in ms.sweep_shadow_text(got)
    assert ms.sweep_shadow_last(str(tmp_path / "missing.csv")) is None


def test_a_short_shadow_row_is_counted_as_unreadable_and_never_believed(tmp_path):
    import morning_status as ms

    path = _shadow_ledger(tmp_path, ["SWEEPSHADOW,1,2,20718,105.0,99.5,28,1", _row(4000, 1)])
    got = ms.sweep_shadow_last(path)
    assert got["rows"] == 1 and got["unreadable"] == 1, got
    assert got["last"]["sig_open"] == 4000, "the good row still stands"


def test_the_shadow_line_renders_the_frame_it_was_given(tmp_path):
    """`off_min` is applied and PRINTED; an unasserted frame is named as unasserted."""
    import morning_status as ms

    sig = 1790069400          # 2026-09-22 07:30 UTC, server-stamped as +120 => 09:30 server
    got = ms.sweep_shadow_last(_shadow_ledger(tmp_path, [_row(sig, 1, off=120)]))
    text = ms.sweep_shadow_text(got)
    assert "07:30Z (server +120min)" in text, text
    assert "side 1" in text and "stop 41.31" in text
    # A row whose frame cannot be named must not render a plausible time instead.
    unknown = {"rows": 1, "fired": 1, "unreadable": 0,
               "last": {"sig_open": sig, "off_min": -9999, "side": 1,
                        "asian_hi": 105.0, "asian_lo": 99.5, "range_bars": 28,
                        "stop_d": 41.31}}
    assert "frame unasserted" in ms.sweep_shadow_text(unknown)


def test_the_pre_registration_governs_the_rule_and_not_the_code():
    """The rule is the document's; the module repeats the constants so a reader can see them."""
    doc = PREREG.read_text(encoding="utf-8")
    for phrase in ("N ≥ 60", "t ≥ 2.4", "0.30", "VOID"):
        assert phrase in doc, f"the pre-registration must state `{phrase}`"
    import midas_sweep_shadow as ss
    assert ss.N_TARGET == 60 and ss.T_BAR == 2.4 and abs(ss.MIN_PER_DAY - 0.30) < 1e-9
    assert ss.VARIANT == "SWEEP_CONT"
    assert "ACCUMULATING" in doc
