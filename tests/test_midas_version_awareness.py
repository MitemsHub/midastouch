"""Version-awareness pins for the parity harness and the watchdog.

V2 register §1 law: version transitions are adjudicated EXCLUSIVELY by
midas_verdict.py's telemetry-exemption walk (ERA-note citation
`telemetry-only-per-V2-register`). No other version-string consumer may
exist: a cited telemetry-only build (e.g. v1.13's R10 columns) must pass
through the watchdog's drift check and the parity harness's comparison
without tripping anything version-related — a mid-window version change is
either §13's own abort decision (verdict tool) or it is nothing.

These pins enforce the law structurally:
  * the watchdog's banner-text drift matchers are REMOVED (§14: banner text
    cannot be attributed across five identically-labelled charts); the
    chart-identity check that replaced them reads no version stamp, and no
    version constant may be added to the watchdog's executable strings;
  * the harness's keyed_compare() is version-agnostic by construction
    (keys + per-trade dR tolerance); a version-regex injection into the
    comparison path fails the suite;
  * midas_verdict.py keeps the one lawful version consumer: the §1
    citation constant and the transition walk.

Python sources are parsed with ast (docstrings excluded from the
"executable string constants" sweep — prose may discuss versions; code
may not consume them). Comment-stripped text for the .mq5 check, per the
test_midas_time.py convention.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WATCHDOG = REPO / "scripts" / "midas_watchdog.py"
PARITY = REPO / "scripts" / "midas_parity.py"
VERDICT = REPO / "scripts" / "midas_verdict.py"

VERSION_CONSUMER_RE = re.compile(r"MIDAS1\.|APP_VERSION")
VER_STAMP_RE = re.compile(r"MIDAS1\.\d+")


def tree_of(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def func_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} must exist")


def docstring_node_ids(tree: ast.Module) -> set[int]:
    """ids() of every docstring Constant node — the first statement of any
    Module/ClassDef/FunctionDef body. Positional, not value-based:
    ast.get_docstring returns dedented text, so value-matching would fail
    to exclude indented docstrings and the sweep would flag prose."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        # Only statement-bearing nodes hold docstrings; IfExp/Lambda also
        # have a .body — an EXPRESSION, not a statement list.
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            ids.add(id(first.value))
    return ids


def code_string_constants(tree: ast.Module) -> set[str]:
    """Every string constant in the module EXCEPT docstrings."""
    docs = docstring_node_ids(tree)
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docs:
            out.add(node.value)
    return out


# --- watchdog: the drift check must stay version-blind ------------------------

def test_watchdog_has_no_banner_drift_consumer() -> None:
    """§14 hardening: banner_drift/banners_for_pins are REMOVED, not patched.

    Five charts print identical `mode=… | session=…` banner text with no arm
    tag, so no banner matcher can attribute a boot to an arm (the 09:05
    phantom ESCALATE). The chart <inputs> check that replaced them reads no
    version stamp either — the version no-consumer sweep below still applies.
    """
    sys.path.insert(0, str(REPO / "scripts"))
    import midas_watchdog as W  # noqa: E402
    assert not hasattr(W, "banner_drift") and not hasattr(W, "banners_for_pins"), (
        "banner-text drift matching must stay removed — it cannot be "
        "attributed across identically-labelled charts")
    names = {n.name for n in ast.walk(tree_of(WATCHDOG))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "banner_drift" not in names and "banners_for_pins" not in names


def test_watchdog_code_carries_no_version_consumer() -> None:
    consts = code_string_constants(tree_of(WATCHDOG))
    offenders = [c for c in consts if VERSION_CONSUMER_RE.search(c)]
    assert not offenders, (
        "the watchdog must not gain a version-string consumer — if a check "
        "needs the build version, it belongs in midas_verdict.py's §1 walk; "
        f"offending constants: {offenders}")


def test_watchdog_documents_the_exemption_awareness() -> None:
    src = WATCHDOG.read_text(encoding="utf-8")
    assert "telemetry-only-per-V2-register" in src and "midas_verdict" in src, (
        "the watchdog must document WHERE version adjudication lives (§1: "
        "midas_verdict.py's telemetry-exemption walk) at the site where the "
        "banner matchers were removed")


# --- harness: the comparison must stay version-agnostic -----------------------

def test_parity_comparison_code_has_no_version_logic() -> None:
    tree = tree_of(PARITY)
    for fn in ("keyed_compare", "run_one_mode"):
        consts = code_string_constants(
            ast.Module(body=[func_node(tree, fn)], type_ignores=[]))
        offenders = [c for c in consts if VERSION_CONSUMER_RE.search(c)]
        assert not offenders, (
            f"{fn} must stay version-agnostic — keys+tolerance compare "
            f"behavior, never build strings; offenders: {offenders}")


def test_keyed_compare_passes_identical_trades_from_any_version() -> None:
    """The comparison contract: identical trade lists pass regardless of any
    version context around them (the §1 telemetry build's guarantee)."""
    sys.path.insert(0, str(REPO / "scripts"))
    import midas_parity as P  # noqa: E402

    def trades(tag: str) -> list[dict]:
        return [{"open_ct": 100 + i, "close_ct": 200 + i,
                 "side": 1 if i % 2 == 0 else -1,
                 "r": 0.5 - 0.01 * i, "tag": tag} for i in range(5)]
    verdict = P.keyed_compare(trades("v1.10"), trades("v1.13"))
    assert verdict["verdict"] == "PASS", (
        "identical keyed trades must PASS with no version awareness involved")


# --- verdict tool: the one lawful version consumer ----------------------------

def test_verdict_keeps_the_exemption_mechanism() -> None:
    text = VERDICT.read_text(encoding="utf-8")
    assert "telemetry-only-per-V2-register" in text, (
        "midas_verdict.py must remain the sole owner of the §1 citation")
    assert "version_transitions" in text, (
        "the transition evidence record must stay in the verdict tool")


# --- live-tree corroboration ---------------------------------------------------

def test_current_stamp_exists_in_tree() -> None:
    """The build line this awareness was written for actually stamps MIDAS1.x."""
    ea = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"
    text = ea.read_text(encoding="utf-8", errors="replace")
    assert VER_STAMP_RE.search(text), (
        "the in-tree EA must carry its MIDAS1.x stamp for the §1 walk to key on")
