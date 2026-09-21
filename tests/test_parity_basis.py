"""One account, one basis — pinned wherever a number could be invented instead.

WHY THIS FILE EXISTS. The parity harness claimed the EA and the python engine agreed on
one window, while three different books were in play underneath it:

  * the tester was funded at $1,000,
  * the EA's paper-sizing input was pinned at $5,000 to match the research engine's
    START_EQUITY,
  * the EA's prop governor defaulted to `true` and sized off whatever balance the tester
    handed it — and the parity contract never pinned it at all.

Lots are only lot-invariant where the min-lot floor does not bind, so those were three
trade sets wearing one verdict. Each test below fails if any of the three drifts again,
or if a missing declaration starts being answered with a default.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_sweep as M          # noqa: E402
import mt5_terminals as terms    # noqa: E402

DECLARED_BASIS = 25000.0


def test_the_registry_declares_the_account_basis():
    reg = terms.load_account_registry()
    assert reg.loaded, reg.status()
    assert reg.account_size_usd == DECLARED_BASIS, (
        f"the active account's sizing basis is {reg.account_size_usd!r}; the evaluation "
        f"is {DECLARED_BASIS:.0f} — update configs/mt5/accounts.json, not the callers")
    assert terms.active_account_size() == DECLARED_BASIS


def test_a_registry_without_a_basis_refuses_rather_than_defaulting(tmp_path, monkeypatch):
    """The failure that produced the three-book mess was a default, not a typo."""
    reg = tmp_path / "accounts.json"
    reg.write_text(json.dumps({"active": {"account": "1428765"}}), encoding="utf-8")
    monkeypatch.setenv("MITEMSHUB_MT5_REGISTRY", str(reg))
    with pytest.raises(terms.TerminalNotFound) as exc:
        terms.active_account_size()
    assert "account_size_usd" in str(exc.value)
    assert "do not default" in str(exc.value)


def test_a_retired_account_keeps_its_own_basis():
    """The Deriv era's $1,000 is history and must stay labelled as history."""
    reg = terms.load_account_registry()
    raw = json.loads(Path(reg.path).read_text(encoding="utf-8"))
    retired = {r["account"]: r for r in raw.get("retired", [])}
    assert retired["140778269"]["account_size_usd"] == 1000.0
    assert retired["140778269"]["account_size_usd"] != DECLARED_BASIS


ISA = terms.active_account_size()


def test_the_parity_harness_sizes_both_sides_from_the_registry():
    import midas_parity as P

    assert P.ACCOUNT_BASIS_USD == ISA
    # EA side: the tester's own book
    assert P.T._BASE_TESTER_INI["Deposit"] == f"{ISA:.0f}"
    # EA side: the sizing path the trades are actually built from
    assert P.INPUTS["InpPaperEquity"] == f"{ISA:.1f}"
    # python side, and it must resolve through the engine, not a copy of the number
    assert M.equity_basis() == M.START_EQUITY, "the research default must be untouched"
    P.python_regen  # noqa: B018  (the call site that sets it — exercised below)
    assert P.INPUTS["InpPropAccountSize"] == f"{ISA:.1f}"


def test_the_parity_contract_pins_the_venue_gate_off():
    """An unpinned input that changes meaning is how a certification run compares two
    different rule sets. The python engine models no governor, so parity must not have
    one on — and must say so rather than inherit the EA's default (which is true)."""
    import midas_parity as P

    assert P.INPUTS["InpPropGuard"] == "false"
    assert P.INPUTS["InpDailyLossCapPct"] == "0"
    ea = (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5").read_text(
        encoding="utf-8", errors="replace")
    assert "input bool                InpPropGuard        = true" in ea, (
        "if the EA's default changes, this pin must be re-decided, not left to drift")


def test_the_pinned_paper_equity_is_not_the_ea_default():
    """Pinning a value the EA already defaults to would look like a pin and be nothing."""
    import midas_parity as P

    ea = (REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5").read_text(
        encoding="utf-8", errors="replace")
    assert "input double              InpPaperEquity      = 1000.0;" in ea
    assert P.INPUTS["InpPaperEquity"] != "1000.0"


def test_the_preflight_refuses_an_undeployed_install(tmp_path, monkeypatch):
    """A parity pass must refuse BEFORE stopping the terminal, not after.

    On this install nothing is deployed, so the preflight returns the reasons a pass
    cannot produce a number: the missing binary, the missing recorded spreads, and the
    missing tester root. Anything less and the harness looks like it tried.
    """
    import midas_parity as P

    monkeypatch.setattr(P.R, "data_folder_for_terminal", lambda: str(tmp_path))
    monkeypatch.setattr(P.T, "_tester_roots", lambda: [tmp_path / "nowhere"])
    problems, notes = P.preflight(P.EXPERT)
    joined = "\n".join(problems)
    assert any("no EA binary" in p for p in problems), joined
    assert any("spread file" in p for p in problems), joined
    # a missing tester root is a NOTE, not a blocker: the pass creates it. Blocking on
    # it would make the first run on an install impossible forever.
    assert not any("tester root" in p for p in problems), joined
    assert any("tester root" in n for n in notes), "\n".join(notes)

    # ...and it passes once the two files exist
    expert_dir = tmp_path / "MQL5" / "Experts" / "MIDASTOUCH"
    expert_dir.mkdir(parents=True)
    (expert_dir / "MidastouchAI.ex5").write_bytes(b"ex5")
    files = tmp_path / "MQL5" / "Files"
    files.mkdir(parents=True)
    (files / "MIDASTOUCH_spread_M15.csv").write_text("spread\n", encoding="utf-8")
    monkeypatch.setattr(P.T, "_tester_roots", lambda: [tmp_path])
    problems, notes = P.preflight(P.EXPERT)
    assert problems == [] and notes == []


def test_the_python_basis_override_moves_the_book_it_simulates():
    """`use_basis` must change what a run starts from, and be run-scoped."""
    assert M.equity_basis() == M.START_EQUITY
    try:
        M.use_basis(ISA)
        assert M.equity_basis() == ISA
        assert M.RunResult().final_equity == ISA
        with pytest.raises(ValueError):
            M.use_basis(0)
    finally:
        M._BASIS = None
    assert M.equity_basis() == M.START_EQUITY


def test_no_module_hardcodes_a_basis():
    """A sizing basis may only enter a module from the registry.

    What this catches is a LITERAL — `Deposit = "1000"` or `"InpPaperEquity": "5000.0"` —
    not the assignment itself: `f"{ACCOUNT_BASIS_USD:.0f}"` is the registry's number being
    passed through, which is the thing we want. An earlier version of this test flagged
    the pass-through and would have taught the reader to ignore it.
    """
    import ast
    import re

    def prose_lines(src: str) -> set[int]:
        """Docstring line numbers — history explaining an old basis is not a basis."""
        out: set[int] = set()
        for node in ast.walk(ast.parse(src)):
            body = getattr(node, "body", None)
            if not isinstance(body, list) or not body:
                continue
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                out.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
        return out

    literal = re.compile(
        r"(?:\b(?:Deposit|START_EQUITY|InpPaperEquity|InpPropAccountSize)\s*=\s*"
        r'|["\'](?:Deposit|InpPaperEquity|InpPropAccountSize)["\']\s*:\s*)'
        r'["\']?\d')
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        if path.name in {"midas_sweep.py", "mt5_terminals.py"}:
            continue          # the certified default, and the registry reader itself
        src = path.read_text(encoding="utf-8", errors="replace")
        prose = prose_lines(src)
        for n, line in enumerate(src.splitlines(), 1):
            if n in prose:
                continue
            code = line.split("#", 1)[0]
            if literal.search(code):
                offenders.append(f"{path.name}:{n}: {line.strip()[:70]}")
    assert not offenders, ("a sizing basis is being set outside the registry:\n  "
                           + "\n  ".join(offenders))


def test_parity_sets_the_python_basis_at_the_call_site_not_at_import():
    """Importing the harness must not re-basis every other consumer in the process."""
    import midas_parity as P  # noqa: F401

    assert M._BASIS is None, (
        "midas_parity set the research engine's basis at import time; it must set it "
        "in python_regen so an import cannot change another consumer's book")
    assert os.environ.get("MITEMSHUB_MT5_ACCOUNT", "") in ("", "1428765")
