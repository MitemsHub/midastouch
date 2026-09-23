"""Offline source tests for the MidastouchAI v1.11 live-path ID architecture.

Pins the three position-handling invariants (register R2/R3 remediation):
  * every position touch goes through SelectOurPosition() — the magic-
    isolated selector — or PositionSelectByTicket on the held ticket; no
    bare PositionSelect(_Symbol) / PositionClose(_Symbol) anywhere;
  * HistorySelectByPosition only ever receives g_lv_posid, the
    POSITION_IDENTIFIER;
  * no code path assigns ResultDeal()/ResultOrder() into position-state
    variables (order/deal IDs are provenance, position IDs are keys).

These are source pins, not behavior tests: the MQL5 grammar is frozen
enough (regex over comment-stripped source, brace-matched function bodies)
that any regression — a re-introduced symbol-wide select, a deal ID fed to
HistorySelectByPosition, a ResultOrder() sneaking into g_lv_posid — fails
the suite before it can compile into a binary.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI.mq5"


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
    raise AssertionError(f"unbalanced braces after {fn_name}")


# --- invariant 1: the magic-isolated selector is the only door -----------------

def test_selector_exists_and_checks_magic_and_symbol() -> None:
    b = strip_comments(body("SelectOurPosition"))
    assert "PositionSelectByTicket" in b or "PositionGetSymbol" in b, \
        "the selector must identify positions by ticket/symbol enumeration"
    assert "InpMagic" in b, "the selector must verify the magic number"
    assert "_Symbol" in b, "the selector must verify the symbol"


def test_no_bare_symbol_wide_position_select_anywhere() -> None:
    code = strip_comments(src())
    bad = [m.start() for m in re.finditer(
        r"\bPositionSelect\s*\(\s*_Symbol\s*\)", code)]
    assert not bad, ("bare PositionSelect(_Symbol) found — position touches "
                     "must go through SelectOurPosition()")


def test_no_symbol_wide_position_close_anywhere() -> None:
    code = strip_comments(src())
    bad = re.findall(r"\bPositionClose\s*\(\s*_Symbol\s*\)", code)
    assert not bad, "PositionClose(_Symbol) found — close by held ticket only"


def test_every_position_touch_is_isolated() -> None:
    """All position-API touch sites live inside the sanctioned functions:
    SelectOurPosition (adoption), ResolveLiveIds (post-selection ID
    resolution), LiveClosePosition (verified close), LiveCheckExits
    (verified exit reconciliation), LiveRecoverState (restart adoption),
    ResolveEntryPriceById (the v1.25 fill-price resolver — it verifies symbol
    AND magic before it reads anything, and returns false rather than a price
    when the identity is not one this EA claims)."""
    code = strip_comments(src())
    sanctioned = ("SelectOurPosition", "ResolveLiveIds", "LiveClosePosition",
                  "LiveCheckExits", "LiveRecoverState", "ResolveEntryPriceById")
    for fn in sanctioned:
        body(fn)  # must exist
    # every occurrence must sit inside one of the sanctioned bodies
    for m in re.finditer(r"\b(PositionSelectByTicket|PositionGetSymbol|"
                         r"PositionSelect\s*\()", code):
        at = m.start()
        assert any(_inside_body(code, fn, at) for fn in sanctioned), \
            f"position touch outside the sanctioned selectors near: " \
            f"{code[at - 40:at + 60]!r}"


def _inside_body(code: str, fn_name: str, at: int) -> bool:
    m = re.search(rf"\b\w+\s+{re.escape(fn_name)}\s*\(", code)
    if not m:
        return False
    j = code.index("{", m.end())
    depth = 0
    for k in range(j, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return j <= at <= k
    return False


# --- invariant 2: history selection is posid-only ------------------------------

def test_history_select_only_receives_identities_we_claim() -> None:
    """THE INVARIANT IS OWNERSHIP, AND IT IS NOW NAMED THAT WAY (v1.25).

    The original pin required the literal `g_lv_posid`, which was true while the only caller
    was the exit reconciler. Two honest callers arrived with fixes the arm's own fill demanded:
    `ResolveEntryPriceById` (which must reach the fill's history while the globals are still
    empty — at the ack, `g_lv_posid` is 0) and `PositionHasOurEntry` (whose whole body IS the
    ownership test, because the venue stamps the CLOSING deal with magic 0). So the rule the
    pin now enforces is the one that actually protects the account: an argument is either state
    we hold, or a parameter of a function that PROVES the identity is ours before selecting.
    """
    code = strip_comments(src())
    held = ("g_lv_posid", "g_lv_order")           # identities this EA tracks as its own
    verifying = ("ResolveEntryPriceById", "PositionHasOurEntry")
    calls = list(re.finditer(r"\bHistorySelectByPosition\s*\(\s*([^)]*?)\s*\)", code))
    assert calls, "live reconciliation must select history by position"
    for m in calls:
        arg = m.group(1).strip()
        if arg in held:
            continue
        for fn in verifying:
            body(fn)                              # must exist
        owner = next((fn for fn in verifying if _inside_body(code, fn, m.start())), None)
        assert owner, (f"HistorySelectByPosition({arg}) is neither held state nor a parameter "
                       f"of an ownership-verifying selector")
        b = strip_comments(body(owner))
        assert "PositionHasOurEntry(" in b or "InpMagic" in b, \
            f"{owner} must prove the identity is OURS before selecting its history"
    # and the plain held-state calls are still the literal, so a rename cannot hide one
    literal = [m.group(1).strip() for m in calls]
    assert literal.count("g_lv_posid") >= 2, (
        "the exit reconciler and the entry-deal resolver select OUR position by g_lv_posid")
    assert "key" in literal, (
        "the fill-price resolver selects the identity the fill row carries (posid, or the "
        "order ticket that IS the posid on netting) — see the v1.25 note in the EA")


def test_history_deal_filter_matches_the_position_id() -> None:
    b = strip_comments(body("LiveCheckExits"))
    assert "DEAL_POSITION_ID" in b
    assert "g_lv_posid" in b, "external-close reconciliation keys on the posid"


# --- invariant 3: order/deal IDs are provenance, never position keys -----------

def test_result_deal_and_order_are_provenance_only() -> None:
    lb = strip_comments(body("LiveSendOrder"))
    hits = re.findall(r"(g_lv_\w+)\s*=\s*g_trade\.Result(Deal|Order)\s*\(\s*\)",
                      lb)
    assert sorted(h[0] for h in hits) == ["g_lv_deal", "g_lv_order"], \
        "ResultDeal/ResultOrder may only feed the provenance fields"
    for var in ("g_lv_posid", "g_lv_ticket"):
        assert not re.search(rf"{var}\s*=\s*g_trade\.Result", lb), \
            f"{var} must never be assigned from ResultDeal/ResultOrder"


def test_posid_resolution_falls_back_to_the_position_identifier() -> None:
    b = strip_comments(body("ResolveLiveIds"))
    assert "POSITION_IDENTIFIER" in b, \
        "g_lv_posid comes from the position's own identifier"
    assert "g_lv_posid" in b and "POSITION_TICKET" in b, \
        "ticket and identifier are resolved as separate fields"


def test_position_state_variables_only_take_position_space_values() -> None:
    code = strip_comments(src())
    for var in ("g_lv_posid", "g_lv_ticket"):
        for m in re.finditer(rf"{var}\s*=\s*([^;\n]+);", code):
            rhs = m.group(1).strip()
            assert not re.search(r"\bResult(Deal|Order)\s*\(", rhs), \
                f"{var} = {rhs!r}: order/deal ID assigned into position state"
            assert not re.search(r"\bEntryOrder\b|\bEntryDeal\b", rhs), \
                f"{var} = {rhs!r}: history deal/order space leaked into position state"


# --- the state reset keeps all four fields coherent ----------------------------

def test_flat_reset_clears_all_live_id_fields() -> None:
    for fn in ("LiveClosePosition", "LiveRecoverState", "LiveCheckExits"):
        b = strip_comments(body(fn))
        if "g_lv_posid = 0" in b:
            assert "g_lv_ticket = 0" in b and "g_lv_order = 0" in b \
                and "g_lv_deal = 0" in b, \
                f"{fn}: the flat reset must clear posid, ticket, order and deal together"


def test_close_uses_the_held_ticket_not_the_symbol() -> None:
    b = strip_comments(body("LiveClosePosition"))
    assert "g_trade.PositionClose(g_lv_ticket)" in b, \
        "close operates on the verified held ticket"
