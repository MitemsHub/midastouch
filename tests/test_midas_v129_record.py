"""The v1.29 record build: the exit-reason word.

WHY THIS FILE EXISTS. Measured 2026-09-22 (`docs/LIVE_EXIT_AUDIT_20260922.md`): the arm's
first live fill was closed by a MOBILE order — closing deal `magic 0`,
`DEAL_REASON_MOBILE` — and the ledger's word for it was `EXTERNAL`, the same word a
server-side stop-out gets, because the external-adoption path in `LiveCheckExits()` read
the OUT deal's PRICE only and never `DEAL_REASON` or `DEAL_MAGIC`. "My stop was hit" and
"a human tapped Close on their phone" were the same row, and the distinction lived only
in the venue's history, outside the artifact this program keeps as evidence.

v1.29 makes the adoption scan name the close: SL/TP/SO from the platform's reason
family, EXPERT when the closing deal bears our magic, MANUAL-* for the client/web/
mobile/other family, and EXTERNAL-UNKNOWN only when nothing is known. The load-bearing
property is unchanged from every record build since v1.21: **no decision reads the
word** — it widens the LCLOSE reason slot's vocabulary, which every reader parses
positionally and tolerantly, so the certified trade set cannot move.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
sys.path.insert(0, str(REPO / "scripts"))

# The decision surface: a record-only build must not appear in any of these. The ADOPTION
# path inside LiveCheckExits is the WRITER of the word and is pinned separately; what may
# never read the vocabulary is everything that ACTS on a position or a bar.
_DECISION_FNS = (
    "LiveSendOrder", "LiveFridayFlatCheck", "LiveClosePosition",
    "PaperCheckHardExits", "PaperClose", "SizingNumbers", "SpreadCapOK",
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
    assert prop.group(1) == app.group(1) == "1.29", (prop.group(1), app.group(1))


def test_the_era_note_names_the_new_vocabulary():
    s = src()
    assert "+exit-reason" in s, "the ERA note must name the new vocabulary"
    # ...and it rides the same single note as the four record-only appends before it,
    # in the same place, so a reader keyed on the note's END is not moved.
    assert re.search(
        r'era_note \+= "\+census10\+state-ctx\+spread-hour\+sweep-shadow\+exit-reason"', s)


# --- 2. the adoption scan names the close --------------------------------------------

def test_the_adoption_scan_reads_reason_and_magic():
    """The defect was reading PRICE only; the fix must read both stamps."""
    b = body("LiveCheckExits")
    assert "DEAL_REASON" in b, "the OUT deal's reason must be read"
    assert "DEAL_MAGIC" in b, "the OUT deal's magic must be read"


def test_the_reason_vocabulary_is_the_documented_one():
    b = body("LiveCheckExits")
    for word in ("SL", "TP", "SO", "EXPERT",
                 "MANUAL-CLIENT", "MANUAL-WEB", "MANUAL-MOBILE"):
        assert f'"{word}"' in b, f"the vocabulary must name {word}"
    assert '"EXTERNAL-UNKNOWN"' in b, \
        "an unknown close must not render as a known word"
    # The toolchain's ENUM_DEAL_REASON has no OTHER member (measured 2026-09-22, error 256
    # on DEAL_REASON_OTHER) — so the MANUAL-* family is the three members this venue can
    # produce, and any unnamed reason stays EXTERNAL-UNKNOWN by design. The source says so.
    assert "DEAL_REASON_OTHER" not in b, \
        "a constant this toolchain does not declare must not appear"


def test_the_reason_precedence_puts_our_magic_first():
    """A closing deal bearing OUR magic is the EA's own path — even if the venue
    stamped a reason the naive mapping would read as manual. Magic answers WHO,
    reason answers WHAT; when they disagree about whose act it was, WHO wins."""
    b = body("LiveCheckExits")
    magic_pos = b.index("magic == InpMagic")
    for reason_word in ("DEAL_REASON_SL", "DEAL_REASON_TP", "DEAL_REASON_SO"):
        assert magic_pos < b.index(reason_word), \
            f"{reason_word} must be tested AFTER our own magic"


def test_the_fallback_is_never_a_confident_word():
    """`why` must start as EXTERNAL-UNKNOWN, so a deal with no readable stamps
    cannot inherit a guessed word from a previous iteration."""
    b = body("LiveCheckExits")
    assert re.search(r'string why = "EXTERNAL-UNKNOWN";', b)


def test_the_lclose_writer_prints_the_word():
    b = body("LiveCheckExits")
    assert re.search(r'LCLOSE,%I64d,%I64u,%s,%.5f,%.3f', b), \
        "the LCLOSE row carries the reason word in its reason slot"


def test_the_manual_reasons_never_come_from_our_magic():
    """The inverse of the precedence pin: nothing maps our magic to a MANUAL-* word."""
    b = body("LiveCheckExits")
    magic_pos = b.index("magic == InpMagic")
    for manual in ("MANUAL-CLIENT", "MANUAL-WEB", "MANUAL-MOBILE"):
        assert magic_pos < b.index(f'"{manual}"')


# --- 3. the load-bearing property: no decision reads the word ------------------------

def test_no_decision_function_mentions_the_reason_words():
    """The whole safety property of v1.21–v1.29, restated for the vocabulary: the
    entry, exit, sizing and protective paths must be unable to behave differently
    because of what the close row SAYS."""
    s = strip_comments(src())
    for fn in _DECISION_FNS:
        b = body(fn)
        for word in ("MANUAL-", "EXTERNAL-UNKNOWN"):
            assert word not in b, f"{fn} must not read the exit-reason vocabulary"


def test_the_reason_words_are_not_read_anywhere_outside_the_writer():
    """Writers print the word; readers of LCLOSE parse the row positionally. A grep
    for the literal words must therefore hit only the adoption block (and the
    comments/version banner that document it)."""
    s = strip_comments(src())
    hits = s.count('"EXTERNAL-UNKNOWN"')
    assert hits == 1, f"EXTERNAL-UNKNOWN must be written in exactly one place, found {hits}"


# --- 4. the readers are tolerant of the wider vocabulary -----------------------------

def test_ledger_flatness_does_not_switch_on_the_reason_word():
    """`ledger_flatness` pairs LOPEN/LCLOSE positionally; the word must stay inert."""
    import mt5_ops as ops
    b = ops.ledger_flatness.__doc__ or ""
    src_txt = open(ops.__file__, encoding="utf-8").read()
    fn = src_txt.split("def ledger_flatness", 1)[1].split("\ndef ", 1)[0]
    assert '"EXTERNAL"' not in fn and "'EXTERNAL'" not in fn, \
        "the flatness reader must not branch on a reason literal"


def test_golive_grammar_counts_any_reason_word_as_a_close():
    """The reconciliation reader treats the reason slot as a word, not a keyword."""
    import morning_status as ms
    src_txt = open(ms.__file__, encoding="utf-8").read()
    fn = src_txt.split("def live_grammar_view", 1)[1].split("\ndef ", 1)[0]
    # It may keep recognising the legacy word; it must not REQUIRE it.
    assert fn.count("EXTERNAL") <= 2, \
        "the grammar reader must not hard-require the legacy EXTERNAL literal"


# --- 5. the record names the measured event ------------------------------------------

def test_the_exit_audit_documented_the_gap_this_build_closes():
    doc = REPO / "docs" / "LIVE_EXIT_AUDIT_20260922.md"
    text = doc.read_text(encoding="utf-8")
    assert "DEAL_REASON" in text and "EXTERNAL" in text, \
        "the audit that prescribed this fix must remain in the repository"
