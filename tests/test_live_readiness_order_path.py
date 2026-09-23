"""The readiness order-path legs: the venue's accept-check and the filling mode.

WHY THIS FILE EXISTS. On 2026-09-21 the arm's ability to place an order was proven by hand,
once — a min-lot request the venue priced and accepted (retcode 0, $241.76 of margin) and a
filling-mode question settled by reading the installed `Trade.mqh`. Both facts were true and
neither was checked by anything that runs on a schedule, so the proof lived in a transcript
and would have to be remembered and repeated by whoever asked next.

Two things must stay true for the gate to be worth having, and both are pinned here rather
than trusted:

1. **It never sends anything.** `order_check` is read-only by construction, and a source pin
   asserts there is no `order_send` in the file at all — the day this gate can place an order
   is the day it can place one by accident.
2. **An unasked question is not an answer.** A closed market or disabled trading must report
   UNCONFIRMED (which renders WARN and does not block), never a pass; a venue that REFUSES the
   order's shape must block.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import live_readiness as lr  # noqa: E402

SOURCE = (ROOT / "scripts" / "live_readiness.py").read_text(encoding="utf-8")


# --- the filling mode ---------------------------------------------------------------------

def test_both_modes_supported_resolves_to_fok() -> None:
    ok, why = lr.filling_verdict(lr.FILLING_FOK | lr.FILLING_IOC)
    assert ok and "FOK" in why


def test_ioc_only_is_usable_and_says_so() -> None:
    """This venue's measured state (0x2). CTrade's FOK default must not reach the wire."""
    ok, why = lr.filling_verdict(lr.FILLING_IOC)
    assert ok and "IOC only" in why and "FOK default" in why


def test_neither_mode_is_a_hard_failure() -> None:
    ok, why = lr.filling_verdict(0)
    assert not ok
    assert "neither FOK nor IOC" in why


# --- the accept-check ---------------------------------------------------------------------

class _Chk:
    def __init__(self, retcode, comment="", margin=0.0):
        self.retcode, self.comment, self.margin = retcode, comment, margin


class _Tick:
    ask = 4352.07
    bid = 4351.61


class _Info:
    digits = 2
    volume_min = 0.01
    volume_step = 0.01


class StubMT5:
    """The smallest bridge that answers the questions the probe asks."""

    TIMEFRAME_H1 = 16385
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_FILLING_IOC = 1, 0, 2

    def __init__(self, chk=None, raise_exc=None, rates=None):
        self._chk, self._raise, self._rates = chk, raise_exc, rates
        self.requests: list[dict] = []

    def symbol_info(self, symbol):
        return _Info()

    def symbol_info_tick(self, symbol):
        return _Tick()

    def copy_rates_from_pos(self, symbol, tf, start, count):
        return self._rates

    def order_check(self, request):
        self.requests.append(request)
        if self._raise:
            raise self._raise
        return self._chk

    def last_error(self):
        return (-1, "stub")


def _call(stub, atr=15.0):
    return lr.accept_check(stub, "XAUUSD", atr=atr, min_lot=0.01, volume_step=0.01)


def test_an_accepted_request_passes_and_names_the_margin() -> None:
    ok, detail = _call(StubMT5(_Chk(0, "Done", margin=241.25)))
    assert ok is True
    assert "ACCEPTED" in detail and "241.25" in detail and "nothing was sent" in detail


def test_a_refused_shape_fails_and_quotes_the_retcode() -> None:
    ok, detail = _call(StubMT5(_Chk(10030, "Unsupported filling mode")))
    assert ok is False
    assert "10030" in detail and "REFUSED" in detail


def test_a_closed_market_is_unconfirmed_not_a_pass_and_not_a_failure() -> None:
    for rc in lr.UNDECIDED_RETCODES:
        ok, detail = _call(StubMT5(_Chk(rc, "closed")))
        assert ok is None, f"retcode {rc} must not read as pass or fail"
        assert "UNCONFIRMED" in detail


def test_no_answer_at_all_is_unconfirmed() -> None:
    ok, detail = _call(StubMT5(None))
    assert ok is None and "UNCONFIRMED" in detail


def test_a_bridge_failure_is_unconfirmed_rather_than_lethal() -> None:
    ok, detail = _call(StubMT5(raise_exc=RuntimeError("bridge gone")))
    assert ok is None and "raised" in detail


def test_no_atr_means_no_request_is_built() -> None:
    stub = StubMT5(_Chk(0))
    ok, detail = _call(stub, atr=0.0)
    assert ok is None and "no ATR" in detail
    assert stub.requests == [], "nothing may be sent when the probe cannot size a stop"


def test_the_request_mirrors_the_arm_geometry_and_is_labelled_as_a_probe() -> None:
    stub = StubMT5(_Chk(0))
    _call(stub)
    req = stub.requests[0]
    assert req["symbol"] == "XAUUSD" and req["volume"] == 0.01
    assert req["sl"] < req["price"] < req["tp"]
    # 2.0x ATR below, 2.0R above
    assert abs((req["price"] - req["sl"]) - 15.0 * lr.PROBE_SL_ATR_MULT) < 0.01
    assert abs((req["tp"] - req["price"]) - 15.0 * lr.PROBE_SL_ATR_MULT * lr.PROBE_TP_R) < 0.01
    assert "never sent" in req["comment"]


# --- the ATR the probe sizes on -----------------------------------------------------------

class _Rates(list):
    def __getitem__(self, i):
        row = super().__getitem__(i)
        return dict(zip(("high", "low", "close"), row))


def test_atr_is_taken_from_closed_bars_only() -> None:
    """`start=1` is asserted through the call: a forming bar in the sample would make the
    probe ask about a stop the arm would never use."""
    rows = [(100.0 + i, 99.5 + i, 99.8 + i) for i in range(40)]
    stub = StubMT5(_Chk(0), rates=_Rates(rows))
    atr = lr.h1_atr_closed(stub, "XAUUSD", 14)
    assert atr > 0


def test_too_few_bars_reports_zero_rather_than_a_guess() -> None:
    stub = StubMT5(_Chk(0), rates=_Rates([(1.0, 0.5, 0.8)]))
    assert lr.h1_atr_closed(stub, "XAUUSD", 14) == 0.0
    assert lr.h1_atr_closed(StubMT5(_Chk(0), rates=None), "XAUUSD", 14) == 0.0


# --- the file stays read-only -------------------------------------------------------------

def _code_only(text: str) -> str:
    """The module with every docstring and comment removed.

    A regex is not enough here and the failure is instructive: the first version of this pin
    tripped over the word `order_send` INSIDE the docstring that explains there is no
    `order_send`. Prose must not be able to satisfy — or violate — a code pin.
    """
    import ast
    tree = ast.parse(text)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body[0].value.value = ""
    code = ast.unparse(tree)
    return "\n".join(re.sub(r"#[^\n]*", "", ln) for ln in code.splitlines())


def test_readiness_can_never_send_an_order() -> None:
    """The gate's whole licence is that it asks without acting."""
    code = _code_only(SOURCE)
    assert "order_send" not in code, "readiness must never gain an order-sending call"
    assert "order_check" in code


def test_the_legs_are_registered_and_block_only_on_a_refusal() -> None:
    assert '"symbol filling mode is usable"' in SOURCE
    assert '"order path accept-check (min lot, nothing sent)"' in SOURCE
    # an unconfirmed check must not block, and a refusal must
    assert "blocking=(ok_acc is False)" in SOURCE


def test_the_probe_geometry_is_declared_next_to_its_reason() -> None:
    assert lr.PROBE_SL_ATR_MULT == 2.0 and lr.PROBE_TP_R == 2.0
    assert "InpSlAtrMult" in SOURCE, "the mirrored input must be named where it is mirrored"
    assert "not a second sizing engine" in SOURCE, \
        "the probe must say what it is not, so it is never read as a sizing verdict"
