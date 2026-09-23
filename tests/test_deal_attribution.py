"""Whose deal is this? ONE rule, every reader of the venue's deal history.

WHY THIS FILE EXISTS. MEASURED 2026-09-22 on the arm's first real fill: the venue stamped the ENTRY
deal with magic 7825001 and the **CLOSING** deal with magic 0 — the platform had executed it, and its
reason field read MOBILE. Every python reader that filtered the venue's deal history on
`deal.magic == ours` therefore threw that close away, silently: a filter that drops a row reports a
smaller world rather than an error. On the EA side the same defect was a RISK number (the day's
realised P&L, and the Best Day cap and reconstructed opening equity measured from it) and was fixed
in v1.25 by attributing **by position**; these are the python copies, and there were three of them:

  * `midas_watchdog.live_fill_reconciliation` (the completeness alarm `morning_status` reports),
  * `midas_first_fill_packet.venue_deals`    (the ledger-vs-venue packet),
  * `midas_lv_broker_monitor.build_state`    (the LV broker-evidence surface).

A rule copied into three files is three rules, so the rule now lives once — `mt5_ops.attribute_deal`,
`mt5_ops.our_positions_from_deals`, `mt5_ops.attributed_deals` — and this file pins both the rule's
behaviour and the fact that the readers call it instead of carrying their own filter.

PURE: no terminal, no network, no clock.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import mt5_ops as R  # noqa: E402

OUR_MAGIC = 7825001


def _deal(ticket: int, magic: int, entry: int, position_id, **kw) -> SimpleNamespace:
    return SimpleNamespace(ticket=ticket, magic=magic, entry=entry, position_id=position_id, **kw)


#: The venue's own two rows for the arm's first fill (ticket/position ids as returned by the bridge).
REAL_IN = _deal(18137411, OUR_MAGIC, 0, 18874164)
REAL_OUT = _deal(18138688, 0, 1, 18874164)


def test_an_out_deal_is_ours_when_its_position_has_an_in_deal_with_our_magic() -> None:
    ours = R.our_positions_from_deals([REAL_IN, REAL_OUT], OUR_MAGIC)
    assert ours == {"18874164"}
    assert R.attribute_deal(REAL_IN, OUR_MAGIC, ours) == R.DEAL_BY_MAGIC
    assert R.attribute_deal(REAL_OUT, OUR_MAGIC, ours) == R.DEAL_BY_POSITION


def test_a_close_whose_opening_we_cannot_see_is_not_ours() -> None:
    """THE FAIL-CLOSED DIRECTION, and the two mistakes are not symmetric: dropping one of our closes
    under-reports our P&L, while adopting a stranger's close would put someone else's loss inside this
    arm's day cap — invisible, and inside a risk rule."""
    ours = R.our_positions_from_deals([REAL_IN], OUR_MAGIC)
    assert R.attribute_deal(_deal(7, 0, 1, 999999), OUR_MAGIC, ours) is None
    assert R.attribute_deal(_deal(7, 0, 1, 18874164), OUR_MAGIC, ours) == R.DEAL_BY_POSITION, (
        "the position IS ours — a close of it is ours even though the opening was not in this batch")


def test_an_in_deal_without_our_magic_confers_nothing() -> None:
    """Ownership is anchored on an IN deal bearing OUR magic, not on \"some deal mentions the position\":
    a position opened by someone else is not ours, however many of its deals name it."""
    both_stranger = [_deal(1, 0, 0, 5001), _deal(2, 0, 1, 5001)]
    assert R.our_positions_from_deals(both_stranger, OUR_MAGIC) == set()
    ours = R.our_positions_from_deals(both_stranger, OUR_MAGIC)
    assert all(R.attribute_deal(d, OUR_MAGIC, ours) is None for d in both_stranger)


def test_a_zero_position_id_is_never_an_identity() -> None:
    """A position id of 0 would make every unidentified deal ours — the direction this rule must not
    fail in. It cannot enter the set."""
    ours = R.our_positions_from_deals([_deal(1, OUR_MAGIC, 0, 0), _deal(2, OUR_MAGIC, 0, None)],
                                      OUR_MAGIC)
    assert ours == set()
    assert R.attribute_deal(_deal(3, 0, 1, 0), OUR_MAGIC, ours) is None


def test_deals_are_normalised_for_both_shapes_the_repo_passes_in() -> None:
    """The live readers hand this rule MT5 namedtuples and the packet hands it normalised dicts, and
    the rule has to be the same object in both places or it is two rules again."""
    as_dicts = [{"ticket": "18137411", "magic": OUR_MAGIC, "entry": 0, "position_id": "18874164"},
                {"ticket": "18138688", "magic": 0, "entry": 1, "position_id": "18874164"}]
    rows, unattributed = R.attributed_deals(as_dicts, OUR_MAGIC)
    assert [r["attributed_by"] for r in rows] == [R.DEAL_BY_MAGIC, R.DEAL_BY_POSITION]
    assert unattributed == []
    rows2, unattributed2 = R.attributed_deals([_deal(9, 1234, 0, 5)], OUR_MAGIC)
    assert rows2 == [] and len(unattributed2) == 1, "unattributable deals are NAMED, never dropped"


# --------------------------------------------------------------------------- #
# The readers must call it — a rule that three files re-implement is three rules
# --------------------------------------------------------------------------- #

#: reader module -> the fragment that proves it goes through the shared rule.
READERS = {
    "midas_watchdog.py": "R.our_positions_from_deals(deals, magic)",
    "midas_first_fill_packet.py": "_ops.attributed_deals(deals, magic)",
    "midas_lv_broker_monitor.py": "_ops.our_positions_from_deals(deals, LV_MAGIC)",
}


@pytest.mark.parametrize("module,marker", sorted(READERS.items()))
def test_every_venue_deal_reader_uses_the_one_rule(module: str, marker: str) -> None:
    src = (REPO / "scripts" / module).read_text(encoding="utf-8", errors="replace")
    assert marker in src, f"{module} must attribute deals through mt5_ops, not on its own"


@pytest.mark.parametrize("module", sorted(READERS))
def test_no_reader_still_filters_deals_on_the_magic_alone(module: str) -> None:
    """The defect in one line, and it must not come back: `if getattr(d, "magic", 0) != ours: continue`.

    A reader MAY still speak about a deal's own magic — every one of these files keeps the sentence
    that records what the filter used to do, and `midas_lv_broker_monitor` even prints the magic it
    could not attribute — so this looks for the *statement* shape (`if ... != ... :`), which prose
    and comments do not have. Stripping comments would not be enough: the explanations are the point.
    """
    src = (REPO / "scripts" / module).read_text(encoding="utf-8", errors="replace")
    bad = re.findall(r"if\s+getattr\(d,\s*\"magic\",\s*0\)\s*!=\s*\w+\s*:", src)
    assert not bad, (f"{module} filters deals on the magic alone ({bad}) — an externally-closed trade "
                     f"is dropped by that line, silently, which is the defect this rule replaces")
    # and the shared rule must actually be called (any of its three entry points, either alias)
    assert any(name in src for name in ("attribute_deal(", "our_positions_from_deals(",
                                        "attributed_deals(")), \
        f"{module} must ask the shared rule which deals are ours"


def test_the_rule_lives_in_exactly_one_module() -> None:
    """`our_positions_from_deals` is defined once. If a second copy appears, the next venue quirk gets
    a partial fix — which is exactly how three readers came to lose the same close."""
    hits = []
    for p in (REPO / "scripts").glob("*.py"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^def our_positions_from_deals\(", txt, re.M):
            hits.append(p.name)
    assert hits == ["mt5_ops.py"], hits
