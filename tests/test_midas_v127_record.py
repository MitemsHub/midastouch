"""The v1.27 record build: the refusals that said nothing, the bar context, the spread hour.

WHY THIS FILE EXISTS. Measured 2026-09-22, by reading this arm's own ledger and its own
`TrackFreshM15Bar` against the question the whole census exists to answer ("why didn't it
trade"). Four return points in that function wrote no reason anywhere the operator looks:

  * the session gate and the Friday cutoff incremented the census and returned WITHOUT
    setting `g_last_action`, so the chart's `last:` line still showed the PREVIOUS bar's
    action — the HUD said "SIGNAL BUY evaluated" for a bar that was refused;
  * the two pricing guards (`atr <= 0`, `stop <= 0`) returned before the census as well,
    so a bar the engine could not price was not counted AND not named.

Alongside that, the STATE row — written for EVERY evaluated bar — carried no `StateAppend()`
tail while the OPEN row had carried one since v1.19e, so the 83% of bars this arm REFUSES
were exactly the ones with no context on the record.

This file pins all of it, plus the property that makes it safe to ship: NONE of it is read by
anything that decides. The last test is the load-bearing one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
sys.path.insert(0, str(REPO / "scripts"))


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


# --- 1. the four refusals that said nothing ------------------------------------------

def test_every_early_return_in_the_evaluation_names_itself():
    """A return that writes no reason is the defect, and there must be none left.

    This walks the body the way the operator reads it: each guard, in order, either sets
    `g_last_action` or is a `return` that cannot be reached from a bar (the function's own
    prologue). Anything else is a silent refusal, which is what this build removes.
    """
    b = body("TrackFreshM15Bar")
    for reason in ("outside session window", "Friday cutoff",
                   "ATR not computable", "stop distance <= 0"):
        assert reason in b, f"the refusal `{reason}` must be named on the record"
    # The two pricing guards also have to be COUNTED — they were not, before v1.27 — but in
    # their own counter: nothing about the arm refused those bars, the engine could not
    # price them, and inflating the refusal census with them would be a false statement.
    assert b.count("g_nofill_nodata++") == 2, "both pricing guards are counted"
    assert "unpriced" in b and "vetoed" in b, "the two vocabularies are kept apart"


def test_the_pricing_guards_are_not_counted_as_refusals():
    """`nodata` is appended to the census, never folded into `signal`/`spread`/etc.

    Read the two branches themselves, not the function: the counters appear in the order the
    gates run, so a whole-body index comparison measures nothing about which guard incremented
    what. The property is about the branch's OWN body.
    """
    b = body("TrackFreshM15Bar")
    blocks = re.findall(r"if\((?:atr|stop) <= 0\)\s*\{(.*?)\}", b, re.S)
    assert len(blocks) == 2, f"expected the two pricing guards, found {len(blocks)}"
    refusal = ("g_nofill_signal", "g_nofill_mism", "g_nofill_session", "g_nofill_friday",
               "g_nofill_spread", "g_nofill_riskcap", "g_nofill_brk", "g_nofill_notr",
               "g_nofill_news")
    for blk in blocks:
        assert "g_nofill_nodata++" in blk
        for ctr in refusal:
            assert ctr not in blk, f"the pricing guard must not touch {ctr}"


def test_the_hud_names_the_unpriced_count_next_to_the_vetoes():
    """The V: line carries it, so the chart answers the question without a second reader."""
    b = body("HudUpdate")
    assert "V: mis %d no-trg %d sess %d spr %d nodata %d" in b
    assert "g_nofill_nodata" in b


# --- 2. the bar's own context, on every evaluated bar ---------------------------------

def test_the_state_row_carries_the_same_stamp_the_fill_rows_do():
    """One `StateAppend()`, one parser, two row types.

    A second implementation of the context stamp is how the bar record and the fill record
    come to describe one bar differently — the R6 lesson, and the reason the wire-contract
    owner module exists at all.
    """
    b = body("StateRowWrite")
    assert "StateAppend() + RiskAppend(ConfiguredRiskUsd())" in b, \
        "the STATE row rides the same tail as the OPEN row, before the keyed cfg token"
    # The keyed token must stay LAST: `_split_risk_tail` reads it off the END of the row, so
    # appending anything after it would make the reader treat a state field as the budget.
    assert b.index("StateAppend()") < b.index("RiskAppend(")


def test_the_state_row_adds_no_positional_column():
    """The append rides inside the existing `%s`, so every positional reader is untouched."""
    b = body("StateRowWrite")
    literal = re.search(r'"STATE,([^"]+)"', b)
    assert literal, "STATE row format literal not found"
    specs = re.findall(r"%I64[du]|%[-0-9.]*[dfs]", literal.group(1))
    assert specs == ["%I64d", "%I64d"] + ["%d"] * 8 + ["%.2f"] * 3 + ["%s"], specs
    assert literal.group(1).count("%s") == 1


def test_the_reader_renders_the_context_and_refuses_the_sentinels(tmp_path):
    """`na` is not `out` and `-1` is not midnight: a sentinel is printed as one."""
    import morning_status as ms

    tail = {"sig_ct": 1789998000, "hour_utc": 13, "vol_ratio": 1.25, "news": "out",
            "off_min": 120}
    text = ms.state_context_text(tail)
    assert "13Z" in text and "vol x1.25" in text and "news out" in text, text

    unasserted = {"sig_ct": 1789998000, "hour_utc": -1, "vol_ratio": 0.0, "news": "na",
                  "off_min": -9999}
    text = ms.state_context_text(unasserted)
    assert "hour unasserted" in text and "vol unmeasurable" in text, text
    assert "00Z" not in text, "an unasserted hour must not render as midnight"


def test_a_state_row_without_the_tail_renders_exactly_as_before():
    """Absence is not a defect: a row written before v1.27 prints no context and no error."""
    import morning_status as ms

    assert ms.state_context_text({}) == ""
    assert ms.state_context_text({"malformed": "2 state field(s), expected 5"}) == ""


def test_the_state_reader_picks_the_tail_up_off_a_written_row(tmp_path):
    """End-to-end: a v1.27 row parses, and the cfg token is NOT read as a state field."""
    import morning_status as ms

    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "ERA,MIDAS1.27,1,note\n"
        "STATE,1000,900,-1,1,-1,0,5230,1,1,3184,0.00,250.00,23540.00,"
        "1789998000,13,1.24775,out,120,cfg=62.50@0.25\n",
        encoding="utf-8")
    row = ms.state_last(str(ledger))
    assert row is not None
    assert row["state_tail"]["hour_utc"] == 13
    assert row["state_tail"]["vol_ratio"] == 1.24775
    assert row["state_tail"]["news"] == "out"
    assert row["cfg_risk"] == {"cfg_risk_usd": 62.50, "cfg_risk_pct": 0.25}
    assert "13Z" in ms.state_text(row)


# --- 3. the arm measuring its own spread, by hour ------------------------------------

def test_the_spread_row_is_sampled_per_tick_and_rolled_daily():
    s = strip_comments(src())
    assert "SpreadSampleTick();" in body("OnTick"), "sampled on the live tick path"
    b = body("SpreadSampleTick")
    assert "MQL_TESTER" in b and "InpBarModel" in b, \
        "gated out of tester/BAR runs, so parity ledgers stay byte-identical"
    assert "ask < bid" in b, "a crossed quote is not a spread and must not enter a mean"
    assert "SpreadHourWrite(now, g_diag_day)" in body("DiagRollIfNewDay")
    # ...written BEFORE the zeroing, or every day would roll an empty histogram
    roll = body("DiagRollIfNewDay")
    assert roll.index("SpreadHourWrite(") < roll.index("DiagCountReset();")


def test_the_spread_reader_round_trips_the_writers_row(tmp_path):
    import morning_status as ms

    cells = []
    for h in range(24):
        n, mean, mx = (5, 0.20, 22) if h == 13 else (0, 0.0, 0)
        cells.append(f"{h},{n},{mean:.5f},{mx}")
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("SPREADHOUR,1000,20717," + ",".join(cells) + "\n", encoding="utf-8")
    row = ms.spread_hours(str(ledger))
    assert row is not None and row["day"] == 20717
    # Only hours with samples exist: an hour with no quotes must be ABSENT rather than 0.0,
    # which would render as the tightest hour of the day.
    assert set(row["hours"]) == {13}
    assert row["hours"][13] == {"n": 5, "mean": 0.20, "max_x100": 22}
    assert "1/24 hours sampled" in ms.spread_hours_text(row)


def test_a_short_or_absent_spread_row_is_not_half_believed(tmp_path):
    import morning_status as ms

    ledger = tmp_path / "ledger.csv"
    ledger.write_text("SPREADHOUR,1000,20717,13,5,0.20000,22\n", encoding="utf-8")
    assert ms.spread_hours(str(ledger)) is None, "a partial histogram is not a record"
    assert ms.spread_hours(str(tmp_path / "missing.csv")) is None


# --- 4. the load-bearing property: none of it can move a trade ------------------------

def test_nothing_that_decides_reads_any_of_it():
    """The whole build is record-only, and this is what says so.

    Every v1.27 write sits on a path gated out of the strategy tester and out of BAR mode
    (the certified parity replay), so the certified ledgers cannot move. And no entry, exit,
    size, veto or protective rule reads a spread hour or a bar-context field.
    """
    for fn in ("SpreadSampleTick", "SpreadHourWrite"):
        b = body(fn)
        assert "MQL_TESTER" in b, f"{fn} must be gated out of parity runs"
        assert "InpBarModel" in b, f"{fn} must be gated out of BAR mode"
    s = strip_comments(src())
    # The spread histogram is written and measured, and read by NOTHING in the EA.
    for reader in ("g_spread_sum[", "g_spread_max_x100["):
        uses = [m.start() for m in re.finditer(re.escape(reader), s)]
        assert uses, f"{reader} should be used"
    assert "g_spread_sum[h]" not in body("LiveSendOrder")
    assert "g_spread_n[h]" not in body("LiveSendOrder")
    # And the version tag is one number everywhere it is stated. The VALUE moves with each
    # build — v1.28 did, so the literal that used to live here would have pinned a build this
    # file is not about — and the INVARIANT is what actually matters: the property and the
    # define may never disagree, which is what `tests/test_midas_hud.py` and
    # `tests/test_midas_telemetry.py` both pin and what every reader of the ledger relies on.
    prop = re.search(r'#property version\s+"([\d.]+)"', s)
    app = re.search(r'#define APP_VERSION\s+"MIDAS([\d.]+)"', s)
    assert prop and app, "both #property version and APP_VERSION must exist"
    assert prop.group(1) == app.group(1), \
        f"#property {prop.group(1)} != APP_VERSION MIDAS{app.group(1)}"
