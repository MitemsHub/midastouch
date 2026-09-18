"""Source pins for register R6 as executed in-tree (v1.16) — and for the
compile contract that produced the binary.

Pins:
  * both fail-closed preconditions exist and INIT_FAILED — the news-filter
    input must refuse a protection that does not exist, and a non-gold
    symbol must refuse an out-of-charter attach;
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

def test_news_filter_guard_fails_init() -> None:
    b = body("OnInit")
    assert 'if(InpUseNewsFilter)' in b, "the R6 news-filter precondition must gate OnInit"
    m = re.search(r"if\(InpUseNewsFilter\)\s*\{(.*?)\}", b, re.S)
    assert m and "INIT_FAILED" in m.group(1), (
        "InpUseNewsFilter=true must INIT_FAILED — no protection exists to run under")
    assert "V2 register R6" in m.group(1), "the refusal must cite the register"


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
        "a refused attach must not print the healthy-start banner first")


def test_banner_dropped_the_calendar_pending_label() -> None:
    s = src()
    assert "calendar pending" not in s, (
        "the banner must not label as 'pending' an input that can never be "
        "true on a running EA (R6 made it a precondition)")


def test_news_filter_reader_is_only_the_guard() -> None:
    """InpUseNewsFilter appears at exactly: the input declaration, the
    precondition guard (code + its message), and the banner — no decision
    path may depend on an input whose true-value is impossible.

    Pin shape: 4 occurrences in comment-stripped source (input, guard,
    guard's message string, banner) and exactly ONE `if(InpUseNewsFilter)`
    code reader. String-literal stripping is deliberately NOT used — quote
    pairing across MQL continuation lines is fragile and silently swallows
    regions (found while writing this test)."""
    s = src()
    total = len(re.findall(r"InpUseNewsFilter", s))
    guards = len(re.findall(r"if\(InpUseNewsFilter\)", s))
    assert total == 4 and guards == 1, (
        f"expected input+guard+message+banner (4 sites, 1 guard); got "
        f"{total} sites / {guards} guards — a new READER of this input "
        "must be registered in this test")


# --- the harness mirror (one-commit python+EA law) ------------------------------

def test_harness_declares_the_r6_preconditions() -> None:
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            consts[node.targets[0].id] = node.value
    gold, news = consts.get("R6_GOLD_ONLY"), consts.get("R6_NEWS_FILTER_OFF")
    assert isinstance(gold, ast.Constant) and gold.value is True
    assert isinstance(news, ast.Constant) and news.value is True


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
    # R6 shipped as v1.16; the tree advanced to v1.17 (P5 telemetry) and
    # v1.18 (NOFILL diagnostics) with registered never-abort builds — the
    # pin follows the tree's registered version history.
    assert define.group(2) in ("16", "17", "18"), "tree version outside registered history"
