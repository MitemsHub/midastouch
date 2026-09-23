"""Source pins for register R6 as executed in-tree (v1.16) — and for the
compile contract that produced the binary.

Pins:
  * the news-filter input is NO LONGER an init failure but a fail-closed ENTRY
    veto (v1.19c): v1.16 refused the true-value because no calendar engine
    existed, and there is one now — a refused init on a live account holding a
    position would leave the shield rules unmanaged, which is worse than
    standing aside. What stays refused is the BAR replay running a rule the
    other engine cannot see;
  * a non-gold symbol still INIT_FAILs (an out-of-charter attach);
  * the guards run BEFORE the init banner (a refused attach must never
    announce itself as a healthy start);
  * the banner no longer claims "(calendar pending)" — the input's value
    can now never be true on a running EA, so the pending label is a lie;
  * the harness mirrors both preconditions (the R6 constants + the
    gold-symbol feed assertion) — the one-commit python+EA law;
  * scripts/compile_midas.py exists and encodes the verified conventions:
    explicit /log, 0 errors AND 0 warnings AND an .ex5, in-tree scratch.

Comment-stripped / AST conventions per the house test style.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
HARNESS = REPO / "scripts" / "midas_parity.py"
COMPILE_TOOL = REPO / "scripts" / "compile_midas.py"


def src(path: Path = EA) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return re.sub(r"//[^\n]*", "", text)


def body(fn_name: str, path: Path = EA) -> str:
    s = src(path)
    m = re.search(rf"\b\w+\s+{re.escape(fn_name)}\s*\(", s)
    assert m, f"{fn_name} missing"
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


# --- the guards exist, fail-closed, and run before the banner -----------------

def test_the_news_guard_is_a_veto_and_not_an_init_failure() -> None:
    """R6 REVISED (v1.19c). v1.16 refused InpUseNewsFilter=true at INIT because no
    calendar engine existed; inventing one was worse than refusing. There is one now — a
    shared file both engines read — so the true-value must NOT fail init: it must gate
    ENTRIES, and it must try to repair the source before judging it."""
    b = body("OnInit")
    assert "if(InpUseNewsFilter)" in b, "OnInit must report/handle the filter's state"
    m = re.search(r"if\(InpUseNewsFilter\)\s*\{(.*?)\}", b, re.S)
    assert m and "INIT_FAILED" not in m.group(1), (
        "a true news filter must not refuse init — a live account holding a position "
        "would be left with its shield rules unmanaged")
    assert "NewsRefreshIfDue" in m.group(1), "repair the source before judging it"
    assert "NewsSourceProblem" in m.group(1), "and report what the source is"
    gate = body("TrackFreshM15Bar")
    assert "if(InpUseNewsFilter)" in gate and "g_nofill_news++" in gate, (
        "the fail-closed veto belongs on the ENTRY path, counted in the NOFILL census")


def test_gold_only_guard_fails_init() -> None:
    b = body("OnInit")
    m = re.search(r"if\(!is_gold\)\s*\{(.*?)\}", b, re.S)
    assert m and "INIT_FAILED" in m.group(1), (
        "a non-gold symbol must INIT_FAILED — gold-only by charter (R6 + #35)")


def test_guards_precede_the_banner() -> None:
    b = body("OnInit")
    banner = b.find('"MIDASTOUCH started | mode=%d')
    news = b.find("if(InpUseNewsFilter)")
    gold = b.find("if(!is_gold)")
    assert -1 not in (banner, news, gold)
    assert news < banner and gold < banner, (
        "a source problem must be reported before a healthy-start banner claims one")


def test_banner_dropped_the_calendar_pending_label() -> None:
    s = src()
    assert "calendar pending" not in s, (
        "the banner must not label as 'pending' an input that can never be "
        "true on a running EA (R6 made it a precondition)")


def test_every_reader_of_the_news_input_is_registered_here() -> None:
    """Every reader of InpUseNewsFilter is a DECISION, so the set is pinned: a new one
    must be registered deliberately rather than appearing silently. The one v1.21 addition
    is deliberately NOT a decision — the HUD's NEWS line reports the switch, and it is
    display-only by construction (it writes no state and no decision reads it).

    Pin shape: 8 occurrences in comment-stripped source and exactly TWO
    `if(InpUseNewsFilter)` readers — the init block (refresh + report) and the entry
    veto — plus the BAR-replay refusal (condition + message), the input declaration,
    the banner field, the refresher's own early return, and the v1.21 display echo
    `if(!InpUseNewsFilter)` in NewsText(). String-literal stripping is
    deliberately NOT used — quote pairing across MQL continuation lines is fragile and
    silently swallows regions (found while writing this test)."""
    s = src()
    total = len(re.findall(r"InpUseNewsFilter", s))
    guards = len(re.findall(r"if\(InpUseNewsFilter\)", s))
    display = len(re.findall(r"if\(!InpUseNewsFilter\)", s))
    assert total == 8 and guards == 2 and display == 1, (
        f"expected 8 sites / 2 guards / 1 display echo (input, BAR refusal + its message, "
        f"init block, banner, refresh early-return, entry veto, HUD NEWS line); got "
        f"{total} sites / {guards} guards / {display} display — a new READER of this input "
        f"must be registered in this test")


# --- the harness mirror (one-commit python+EA law) ------------------------------

def test_harness_declares_the_r6_preconditions() -> None:
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            consts[node.targets[0].id] = node.value
    gold, news = consts.get("R6_GOLD_ONLY"), consts.get("R6_NEWS_FILTER_OFF")
    mirrored = consts.get("R6_NEWS_MIRRORED")
    assert isinstance(gold, ast.Constant) and gold.value is True
    assert isinstance(news, ast.Constant) and news.value is True, \
        "the certified contract still declares the gate OFF by default"
    assert isinstance(mirrored, ast.Constant) and mirrored.value is True, (
        "R6, REVISED 2026-09-21: the invariant is no longer 'news is never on' — the "
        "engine of record applies the same veto now, so what must hold is that the gate "
        "is NEVER ON FOR ONE ENGINE ONLY")


def test_harness_asserts_a_gold_feed() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert 'startswith("XAU")' in text, (
        "python_build_data must refuse a non-gold feed (R6 mirror)")


# --- the compile contract --------------------------------------------------------

def test_compile_tool_exists_with_the_verified_conventions() -> None:
    text = COMPILE_TOOL.read_text(encoding="utf-8")
    assert "/log:" in text, "the tool must pass an explicit /log (no stray debris logs)"
    assert 'errors == 0 and warnings == 0' in text, (
        "the tool must fail on warnings, not only errors")
    assert "no compile log" in text, (
        "a missing log is a failure — MetaEditor's silent no-op must not pass")
    assert "MIDASTOUCH_compile" in text, (
        "the scratch must live inside the terminal MQL5 tree (the discovered "
        "requirement: MetaEditor no-ops on sources outside it)")


def test_ea_version_is_the_r6_build() -> None:
    s = src()
    prop = re.search(r'#property\s+version\s+"(\d+)\.(\d+)"', s)
    define = re.search(r'#define\s+APP_VERSION\s+"MIDAS(\d+)\.(\d+)"', s)
    assert prop and define and prop.groups() == define.groups()
    # R6 shipped as v1.16; the tree advanced through v1.17 (P5 telemetry), v1.18 (NOFILL
    # diagnostics), v1.19 (the P6 build block), v1.20 (the restart-persistent refusal
    # census), v1.21 (the HUD view + the STATE row), v1.22 (the configured-risk stamp on
    # every fill row), v1.23 (the deduped venue-spec warning + its SPEC ledger record) and
    # v1.24 (the ledger-backed LIVE CENSUS: the tally counts the ledger's own LCLOSE rows and
    # is restored at init, so an armed arm can no longer print `trades: 0/30` after a closed
    # live trade) and v1.25 (THE THREE DEFECTS THE ARM'S OWN FILL EXPOSED: the fill row's entry
    # price resolved from the position or the entry deal and labelled `entry=pending` when it
    # cannot be, the `%s`-count/argument mismatch that printed `(missed string parameter)` on
    # every fill row, and day-P&L attribution by POSITION because the venue stamps the CLOSING
    # deal with magic 0) and v1.26 (WHAT `vEq` MEANS ON AN ARMED ARM: the HUD's equity line and
    # every live heartbeat EQ row carry the arm's own equity - the venue's account on the live
    # path, the paper book on the paper path - instead of the paper counter that never moves on
    # an armed arm, labelled with which record it is reading) and v1.27 (THE FOUR REFUSALS THAT
    # SAID NOTHING NOW SAY WHY, THE STATE ROW CARRIES THE BAR'S OWN CONTEXT, THE ARM MEASURES
    # ITS OWN SPREAD BY HOUR, AND A BAR THAT COULD NOT BE PRICED IS COUNTED RATHER THAN DROPPED:
    # the session and Friday gates set g_last_action, the two pricing guards get their own
    # APPENDED tenth counter `nodata` instead of inflating the refusal census, StateAppend()
    # rides every STATE row before the keyed cfg token, SPREADHOUR records the live spread per
    # UTC hour, and the census snapshot floor moved 12 -> 13 with the append)
    # — each a registered never-abort build, and the pin follows that history.
    # v1.28 (2026-09-22): THE SWEEP SHADOW — the Asian-range sweep continuation recorded
    # forward with NO ORDER PATH (a `SWEEPSHADOW` row per evaluated bar inside UTC 07-18,
    # carrying the setup and never an outcome, resolved by scripts/midas_sweep_shadow.py
    # against docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md; record-only, so the entry, exit,
    # size, veto and protective rules are untouched and the certified trade set is unchanged).
    # A NEW RELEASE EXTENDS THIS LIST, it does not replace it.
    # v1.29 (2026-09-22): THE EXIT REASON WORD — the LCLOSE row names who closed the trade
    # (SL/TP/SO from the OUT deal's DEAL_REASON, EXPERT when the closing deal bears our
    # magic, MANUAL-* for the platform's client/web/mobile/other family, EXTERNAL-UNKNOWN
    # only when nothing is known) instead of one EXTERNAL word for "the venue did it";
    # record-only vocabulary, no decision reads it, so the certified trade set is unchanged).
    assert define.group(2) in ("16", "17", "18", "19", "20", "21", "22", "23", "24",
                               "25", "26", "27", "28", "29"), \
        "tree version outside registered history"
