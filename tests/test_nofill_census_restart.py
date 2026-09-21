"""The refusal census must survive a restart — and say so from the ledger alone.

WHY THIS FILE EXISTS. `NOFILL` rows are the arm's only record of *why* it did not trade,
and on 2026-09-21 the record was empty for a whole live day on which every evaluated bar
was refused. Two defects produced that, and they are different defects:

  1. the day anchor and all nine counters lived in the EA's memory (`g_diag_day0` plus the
     `g_nofill_*` globals), so each of that day's 22 inits reset them, and the
     once-per-24h-since-first-refusal rule could never fire — a census that resets with
     the process is a census that disappears exactly when the arm is being reloaded most;
  2. `morning_status.NOFILL_KEYS` named the row's fields in a DIFFERENT order than the EA
     writes them (`no_trigger` third, where the third field is `session`), so every
     column from three onward was reported under the wrong name. Nothing caught it because
     the only fixture used a row whose trailing fields were all zero, and a permutation of
     zeros is invisible.

So this file pins both halves: the EA keeps the census in the LEDGER (a snapshot row it
reads back at init) and rolls it on the UTC day key; python reads that record with the
writer's own field order. The behavioural tests below are real reads of synthetic ledgers
that contain a restart, and they assert the numbers a restart used to erase.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
sys.path.insert(0, str(REPO / "scripts"))

from morning_status import (                      # noqa: E402
    NOFILL_KEYS,
    nofill_open_day,
    nofill_summary,
)

#: A real hour of the live arm: UTC day 20717 (2026-09-21), 13:00Z.
BASE = 1789998000
DAY = BASE // 86400


def src() -> str:
    return EA.read_text(encoding="utf-8", errors="replace")


def strip_comments(s: str) -> str:
    return re.sub(r"//[^\n]*", "", s)


def body(fn_name: str) -> str:
    """Brace-matched body of a named function."""
    s = src()
    m = re.search(rf"\b\w+\s+{re.escape(fn_name)}\s*\(", s)
    assert m, f"{fn_name} missing from source"
    j = s.index("{", m.end())
    depth, k = 0, j
    while k < len(s):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return s[j:k + 1]
        k += 1
    raise AssertionError(f"unbalanced braces in {fn_name}")


def snap(epoch: int, day: int, counters: list[int]) -> str:
    return f"NOFILLSUM,{epoch},{day}," + ",".join(str(c) for c in counters)


def roll(epoch: int, counters: list[int]) -> str:
    return f"NOFILL,{epoch}," + ",".join(str(c) for c in counters)


def _ledger(tmp_path: Path, rows: list[str], name: str = "ledger.csv") -> str:
    p = tmp_path / name
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(p)


#: 9 counters in the writer's field order:
#: signal, mismatch, session, friday, spread, riskcap, breaker, no_trigger, news
def _c(signal: int, mismatch: int, session: int, friday: int, spread: int,
       riskcap: int, breaker: int, no_trigger: int, news: int) -> list[int]:
    return [signal, mismatch, session, friday, spread, riskcap, breaker, no_trigger, news]


# --- the field order: the defect that made the record lie -----------------------------

def test_the_reader_names_the_rows_fields_in_the_writers_order(tmp_path):
    """DISTINCT values, one per field. This is the pin the old fixture could not be.

    The row below is written the way the EA writes it, so the assertion is a direct
    statement of the contract: position 3 is the SESSION count, position 8 is the
    trigger-less count. Under the old key order this test reads
    no_trigger=3 / session=8 and fails — which is the mislabel, reproduced.
    """
    counters = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    p = _ledger(tmp_path, [f"ERA,MIDAS1.19,{BASE},pertick-fills", roll(BASE + 60, counters)])
    agg = nofill_summary(p, now_ts=BASE + 120)
    assert agg == {"signal": 1, "mismatch": 2, "session": 3, "friday": 4, "spread": 5,
                   "riskcap": 6, "breaker": 7, "no_trigger": 8, "news": 9}, agg
    assert NOFILL_KEYS == ("signal", "mismatch", "session", "friday", "spread",
                           "riskcap", "breaker", "no_trigger", "news")


def test_the_snapshot_row_is_read_with_the_same_order_as_the_census_row(tmp_path):
    counters = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    p = _ledger(tmp_path, [snap(BASE, DAY, counters)])
    od = nofill_open_day(p)
    assert od["day"] == DAY
    for key, want in zip(NOFILL_KEYS, counters):
        assert od[key] == want, f"{key} read as {od[key]}, writer put {want} there"


# --- the restart: what used to be erased ---------------------------------------------

def test_a_restart_in_the_middle_of_a_day_loses_nothing(tmp_path):
    """The whole request, as a read of two ledgers that differ only by the restart.

    Both contain the same 14 refusals: signal=14, no_trigger=9 (the dominant class),
    mismatch=1, session=3, spread=1. In the restarted ledger the EA reloads twice, each
    reload writing a fresh ERA row and its restored snapshot — which is what the EA now
    does and what it could not do before.
    """
    first = _c(4, 0, 1, 0, 0, 0, 0, 3, 0)     # 4 bars: 3 trigger-less, 1 session veto
    first[1] = 1                               # one of them: trigger fired, mode refused
    first[7] = 2
    second = _c(10, 0, 2, 0, 1, 0, 0, 7, 0)    # 10 more bars after the reloads

    interrupted = [
        f"ERA,MIDAS1.19,{BASE},pertick-fills+diag-census",
        "EQ,25000.00",
        snap(BASE + 900, DAY, first),
        f"ERA,MIDAS1.19,{BASE + 1800},pertick-fills+diag-census",   # reload #1
        snap(BASE + 1800, DAY, first),         # ... restored exactly here
        "EQ,25000.00",
        f"ERA,MIDAS1.19,{BASE + 2700},pertick-fills+diag-census",   # reload #2
        snap(BASE + 2700, DAY, first),
        snap(BASE + 3600, DAY, second),        # ... and continued to the running total
    ]
    uninterrupted = [
        f"ERA,MIDAS1.19,{BASE},pertick-fills+diag-census",
        "EQ,25000.00",
        snap(BASE + 3600, DAY, second),
    ]
    a = nofill_open_day(_ledger(tmp_path, interrupted, "restarted.csv"))
    b = nofill_open_day(_ledger(tmp_path, uninterrupted, "clean.csv"))
    assert a == b, "a reload must not change the day's census"
    assert a["signal"] == 10 and a["no_trigger"] == 7 and a["session"] == 2
    assert a["day"] == DAY

    # The roll at the day change carries the census of the day that ENDED, and the
    # snapshots that led up to it are not added on top — they are the same increments,
    # recorded early. (Two roll rows are two DIFFERENT days, which is why the 24h summary
    # adds them: see the second ledger.)
    rolled = interrupted + [roll(BASE + 43200, second)]
    one_day = _ledger(tmp_path, rolled, "rolled.csv")
    agg = nofill_summary(one_day, now_ts=BASE + 43260)
    assert agg["signal"] == 10, "a snapshot must never be counted as a second census"
    assert agg["no_trigger"] == 7 and agg["spread"] == 1
    assert nofill_open_day(one_day)["signal"] == 10, \
        "and the open day still reads the running total, not the rolled one twice"

    two_days = _ledger(tmp_path, interrupted + [roll(BASE + 43200, first),
                                               roll(BASE + 43200 + 86400, second)],
                       "two_days.csv")
    # The 24h window is inclusive at its cutoff, so this now_ts is the moment both rows
    # are inside it (roll #1 sits exactly 86400 before).
    assert nofill_summary(two_days, now_ts=BASE + 43200 + 86400)["signal"] == 14, \
        "a NOFILL row IS a day's interval; consecutive ones sum by design"


def test_a_ledger_with_no_snapshot_is_reported_as_unanswerable_not_as_zero(tmp_path):
    """The old failure mode, stated as the reader's honesty rather than as a crash.

    A v1.18 ledger after a restart holds NOFILLSUM nothing and NOFILL nothing, because the
    counters died with the process. That day cannot be answered from the record, and the
    reader must say so by returning nothing — not by reporting a day of zeros, which would
    read as 'the arm was idle' when what happened was 'the arm's account of itself was
    erased'.
    """
    v118 = [f"ERA,MIDAS1.18,{BASE},pertick-fills", "EQ,25000.00"]
    p = _ledger(tmp_path, v118)
    assert nofill_open_day(p) is None
    assert nofill_summary(p, now_ts=BASE + 60) is None


def test_a_truncated_snapshot_row_is_ignored_and_the_last_complete_one_wins(tmp_path):
    """Append-only means old and new rows coexist; a short row is not a partial state."""
    good = _c(3, 0, 0, 0, 0, 0, 0, 3, 0)
    p = _ledger(tmp_path, [
        snap(BASE, DAY, good),
        f"NOFILLSUM,{BASE + 60},{DAY},3,0,0,0,0",          # truncated: must be ignored
        snap(BASE + 120, DAY, _c(5, 1, 0, 0, 0, 0, 0, 4, 0)),
    ])
    od = nofill_open_day(p)
    assert od["signal"] == 5 and od["mismatch"] == 1 and od["no_trigger"] == 4


def test_a_previous_days_roll_is_not_reported_as_the_open_day(tmp_path):
    """Day 20717's census must not be shown as day 20718's running state."""
    old = _c(9, 0, 0, 0, 0, 0, 0, 9, 0)
    p = _ledger(tmp_path, [
        snap(BASE, DAY, old),
        roll(BASE + 86400, old),
        snap(BASE + 86460, DAY + 1, _c(1, 0, 0, 0, 0, 0, 0, 1, 0)),
    ])
    od = nofill_open_day(p)
    assert od["day"] == DAY + 1 and od["signal"] == 1
    agg = nofill_summary(p, now_ts=BASE + 86520)
    assert agg["signal"] == 9, "the rolled day is the one the census row accounts for"


# --- the EA side: one writer, one reader, one day key --------------------------------

def test_the_census_has_exactly_one_writer_and_it_is_the_day_roll():
    code = strip_comments(src())
    writers = re.findall(r'"NOFILL,%I64d(?:,%d){9}"', code)
    assert len(writers) == 1, "one census row type, one writer"
    assert '"NOFILL,%I64d(?:,%d){9}"' not in writers  # sanity: the literal is the match
    assert re.search(r'"NOFILL,%I64d(?:,%d){9}"', body("DiagRollIfNewDay")), \
        "the census row is written by the roll, not by a veto path"
    assert "DiagCounters()" in body("DiagRollIfNewDay") or \
        body("DiagRollIfNewDay").count("g_nofill_notr") == 1, \
        "the roll writes the counters"
    assert body("DiagSnapshot").count('"NOFILLSUM,%I64d,%d,%s"') == 1, \
        "exactly one snapshot writer"


def test_the_ea_never_anchors_the_census_in_memory_again():
    code = strip_comments(src())
    assert "g_diag_day0" not in code, \
        "the 24h in-memory anchor is the defect this change removes"
    assert "if(g_diag_day == 0) { g_diag_day = day; return; }" in code, \
        "the day key is set on first sighting, and nothing is rolled for a day that has not ended"
    assert "if(day == g_diag_day) return;" in code
    assert "UtcDayNo(now)" in code


def test_the_restore_runs_before_anything_can_account_a_veto():
    """Order matters: a restore after the first bar would blend two days."""
    s = src()
    i_era = s.index('PaperLog(StringFormat("ERA,%s,%I64d,%s"')
    i_restore = s.index("DiagRestoreFromLedger();")
    i_first_bar = s.index("void TrackFreshM15Bar")
    assert i_era < i_restore < i_first_bar, \
        "restore the census after the ERA row and before any veto can be counted"
    assert "DiagRestoreFromLedger()" in body("OnInit")
    assert "DiagSnapshot()" in body("OnDeinit")


def test_the_zeroed_state_is_forced_onto_the_record_after_a_roll():
    """A reload right after a roll must not resurrect the counts the roll accounted for."""
    roll_body = body("DiagRollIfNewDay")
    assert "DiagCountReset();" in roll_body
    assert 'g_diag_sig = "";' in roll_body, \
        "an empty signature makes the snapshot write the zeroed counters"


def test_the_era_note_carries_the_new_grammar_citation():
    """The row type is a grammar change, so the ledger says which grammar it is."""
    code = strip_comments(src())
    assert 'era_note += "+diag-census";' in code
    assert code.index('era_note += "+diag-nofill";') < code.index('era_note += "+diag-census";'), \
        "the chain grows by appending, never by rewriting"
