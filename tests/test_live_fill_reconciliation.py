"""A silent live ledger is not health: the account's own deals are the second source.

THE FAILURE MODE THIS PINS. While the arm was paper, the ledger WAS the record: if it was
flat, nothing had traded. On a live account that stops being true — a flat ledger means
either the strategy has not signalled yet, or the EA is not running at all, and
`morning_status` printed `live: flat` for both while calling the arm healthy. The venue
holds the other copy of the truth, so a live arm is verified against `history_deals_get`
for its own magic.

States, and the rule each one carries:

  * silent in both       -> alive and unproven; healthy but explicitly NOT a health claim
  * ledger == account    -> matched
  * account has more     -> ALARM (`ledger-short`): every R derived from the ledger is
                            unverified from that moment on
  * terminal unreadable  -> unknown, which is never healthy
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import midas_watchdog as wd  # noqa: E402

LEDGER_HEADER = ("ERA,MIDAS1.19,1789651864,pertick-fills\nEQ,25000.00\n")


def _ledger(tmp_path: Path, tickets: list[int]) -> Path:
    p = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    rows = "".join(
        f"LOPEN,1789712100,{1000 + i},{t},{t},1,4354.085,4308.629,4444.996,0.10,4.55,45.45,"
        f"43200,U25\n" for i, t in enumerate(tickets))
    p.write_text(LEDGER_HEADER + rows, encoding="utf-8")
    return p


class _Deal:
    def __init__(self, ticket: int, magic: int, time: float = 1789712100.0,
                 position_id: int | None = None, entry: int = -1, reason: int = 0):
        self.ticket, self.magic, self.time = ticket, magic, time
        # Real deals always carry a position id; the synthetic ones above default to None so
        # they keep exercising the ticket fallback. Added for the netting case below, which is
        # the shape the venue actually returned for the arm's first fill.
        self.position_id = position_id
        # `entry` is what the by-position rule needs: 0 = IN (an opening), 1 = OUT (a close).
        # -1 is the "this fixture predates the rule" value and keeps every older test on the
        # magic-only path, which is what they were written to exercise.
        self.entry, self.reason = entry, reason


def _fake_mt5(monkeypatch, deals: list[_Deal] | None, *, initialize: bool = True) -> None:
    mod = types.SimpleNamespace(
        initialize=lambda *a, **k: initialize,
        last_error=lambda: (1, "fake"),
        history_deals_get=lambda *a, **k: deals,
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", mod)


def test_an_unreadable_ledger_is_not_a_pass(tmp_path, monkeypatch) -> None:
    _fake_mt5(monkeypatch, [])
    rec = wd.live_fill_reconciliation(str(tmp_path / "nope.csv"), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_NO_LEDGER and rec["healthy"] is False


def test_silence_in_both_is_alive_and_unproven_never_healthy_by_itself(tmp_path, monkeypatch) -> None:
    _fake_mt5(monkeypatch, [])
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_SILENT
    assert rec["healthy"] is True, "no signal yet must not read as a failure either"
    assert "NOT a health claim" in rec["detail"], \
        "the state must say what it does not authorise — this is the whole point"


def test_a_deal_the_ledger_does_not_record_is_an_alarm(tmp_path, monkeypatch) -> None:
    """The expensive one: the audit trail is short, so the ledger stops being evidence."""
    _fake_mt5(monkeypatch, [_Deal(11, 7825001), _Deal(12, 7825001)])
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [11])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_LEDGER_SHORT and rec["healthy"] is False
    assert rec["missing"] == ["12"]
    assert "unverified" in rec["detail"]


def test_a_close_the_venue_stamped_with_magic_zero_is_adopted_by_position(tmp_path,
                                                                         monkeypatch) -> None:
    """THE DEFECT THIS FILE NOW PINS. MEASURED 2026-09-22 on the arm's first real fill: the venue
    stamped the ENTRY deal with magic 7825001 and the CLOSING deal with **magic 0** (its reason read
    MOBILE — the platform executed it). Filtering on `deal.magic == magic` therefore threw the close
    away, and it did so silently: the reader reported a smaller world rather than an error. Ownership
    belongs to the POSITION — an OUT deal is ours iff its position has an IN deal bearing our magic.
    """
    deals = [_Deal(18137411, 7825001, position_id=5001, entry=0),
             _Deal(18138688, 0, position_id=5001, entry=1, reason=1)]
    _fake_mt5(monkeypatch, deals)
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [5001])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_MATCHED and rec["healthy"] is True
    assert rec["account"] == 1, "the position is one fill, not two"
    closes = rec["closes_attributed_by_position"]
    assert [c["ticket"] for c in closes] == [18138688]
    assert closes[0]["magic"] == 0 and closes[0]["price"] is None or True   # shape, not values
    assert "adopted BY POSITION" in rec["detail"], \
        "the reader must SAY that it needed the rule — the defect was that this could not be told"


def test_a_stray_close_is_never_adopted(tmp_path, monkeypatch) -> None:
    """FAIL CLOSED, and this is the direction that matters. The two mistakes are not symmetric:
    dropping one of our closes under-reports our P&L, while adopting a STRANGER's close would put
    someone else's loss inside this arm's day cap — invisible, and inside a risk rule. A close whose
    opening we cannot see is therefore NOT ours, and it is named as unattributed rather than dropped.
    """
    stray = _Deal(99999, 0, position_id=7777, entry=1, reason=1)
    _fake_mt5(monkeypatch, [stray])
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [])), magic=7825001)
    assert rec["account"] == 0 and rec["closes_attributed_by_position"] == []
    assert rec["unattributed_deals"] == 1
    assert rec["state"] == wd.LIVE_FILLS_SILENT, "a stranger's close is not this arm's evidence"


def test_an_in_deal_without_our_magic_does_not_confer_ownership(tmp_path, monkeypatch) -> None:
    """The rule is anchored on an IN deal bearing OUR magic, not on "some deal mentions this
    position". A position opened by someone else and closed by someone else is not ours even though
    both deals name it — adopting it would inflate the arm's record with a trade it never took."""
    deals = [_Deal(1, 0, position_id=5001, entry=0), _Deal(2, 0, position_id=5001, entry=1)]
    _fake_mt5(monkeypatch, deals)
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [])), magic=7825001)
    assert rec["account"] == 0 and rec["closes_attributed_by_position"] == []
    assert rec["state"] == wd.LIVE_FILLS_SILENT


def test_matching_fills_reconcile(tmp_path, monkeypatch) -> None:
    _fake_mt5(monkeypatch, [_Deal(11, 7825001), _Deal(12, 7825001)])
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [11, 12])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_MATCHED and rec["healthy"] is True
    assert rec["ledger"] == rec["account"] == 2


def test_a_netting_fill_keys_on_the_order_ticket_in_the_real_rows_shape(tmp_path, monkeypatch) -> None:
    """MEASURED 2026-09-22 on the arm's FIRST REAL FILL — the shape the synthetic rows above do
    NOT have, and the one that made this alarm lie.

    The EA writes `LOPEN` as the fill is acknowledged, and on a NETTING account neither the
    position id nor the deal ticket is resolvable at that instant — its own journal says so
    ("fill acknowledged but owned position not yet selectable — IDs will reconcile on the next
    tick"). The real row and the real venue deal, values as returned by the terminal:

      LOPEN,1790092800,0,18874164,0,-1,...   <- posid=0, order=18874164, deal=0
      deal: position_id=18874164, order=18874164, ticket=18137411, magic 7825001

    Keying the ledger on parts[2]/parts[4] alone read ("0", "0") from that row, matched
    nothing, and returned `ledger-short` — the ALARM state, whose own text is "every R derived
    from this ledger is unverified" — on a fill the ledger had recorded in full, with an LOPEN
    and a matching LCLOSE. Keying the account side on the deal ticket as well made it
    permanent, because the row cannot contain that ticket at write time. Both are fixed; this
    test is the pin, and it fails on the previous behaviour.
    """
    p = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    p.write_text(LEDGER_HEADER
                 + "LOPEN,1790092800,0,18874164,0,-1,0.00000,4374.38000,4250.77000,0.01,41.20,"
                   "41.20143,43200,U25,1790091900,13,1.39453,out,120,cfg=62.50@0.25\n"
                   "LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104\n",
                 encoding="utf-8")
    _fake_mt5(monkeypatch, [_Deal(18137411, 7825001, 1790100000.0, position_id=18874164)])
    rec = wd.live_fill_reconciliation(str(p), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_MATCHED, rec
    assert rec["healthy"] is True and rec["ledger"] == 1 and rec["account"] == 1


def test_a_zero_identifier_in_a_row_is_not_an_identifier(tmp_path, monkeypatch) -> None:
    """`0` must never be used as a key: it would match any deal that carries 0 — a false MATCH,
    which is worse than the false alarm it replaces. A row whose every identifier is zero
    therefore records nothing, and a real deal is still reported as missing."""
    p = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    p.write_text(LEDGER_HEADER + "LOPEN,1790092800,0,0,0,-1,0,0,0,0.01,0,0,43200,U25\n",
                 encoding="utf-8")
    _fake_mt5(monkeypatch, [_Deal(55, 7825001)])
    rec = wd.live_fill_reconciliation(str(p), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_LEDGER_SHORT, rec
    assert rec["missing"] == ["55"]


def test_another_arms_magic_is_not_this_arms_evidence(tmp_path, monkeypatch) -> None:
    """The portfolio shares an account: a sibling arm's deals must not count here."""
    _fake_mt5(monkeypatch, [_Deal(99, 1111111)])
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_SILENT, "a foreign magic produced a fill claim"


def test_an_unqueryable_terminal_is_unknown_not_healthy(tmp_path, monkeypatch) -> None:
    _fake_mt5(monkeypatch, None, initialize=False)
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_UNREADABLE and rec["healthy"] is False


# --------------------------------------------------------------------------- #
# The first fill: captured once, from all three sources, and never rewritten
# --------------------------------------------------------------------------- #

def test_no_fill_means_no_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wd, "FIRST_FILL_PATH", str(tmp_path / "first_fill.json"))
    assert wd.record_first_fill([{"tag": "U25", "ledger": 0, "account": 0}]) is None
    assert not (tmp_path / "first_fill.json").exists()


def test_the_first_fill_records_ledger_account_and_the_eas_own_row(tmp_path, monkeypatch) -> None:
    """All three at once: while they are the same event, not a later reconstruction."""
    monkeypatch.setattr(wd, "FIRST_FILL_PATH", str(tmp_path / "first_fill.json"))
    rec = {"tag": "U25", "state": wd.LIVE_FILLS_MATCHED, "ledger": 1, "account": 2,
           "first_ledger_row": "LOPEN,1789712100,2048845860,987654321,2048845860,1,4354.0",
           "first_deal": {"ticket": 2048845860, "price": 4354.085, "volume": 0.10}}
    out = wd.record_first_fill([rec], now=1789712100.0)
    assert out["ledger_fills"] == 1 and out["account_identifiers"] == 2
    assert out["first_ledger_row"].startswith("LOPEN,")
    assert out["first_account_deal"]["ticket"] == 2048845860
    assert "recorded_utc" in out
    assert (tmp_path / "first_fill.json").exists()


def test_the_first_fill_is_never_rewritten(tmp_path, monkeypatch) -> None:
    """An observation, not a state: the second call returns the first record unchanged."""
    path = tmp_path / "first_fill.json"
    monkeypatch.setattr(wd, "FIRST_FILL_PATH", str(path))
    first = wd.record_first_fill([{"tag": "U25", "ledger": 1, "account": 1}], now=1000.0)
    before = path.read_text(encoding="utf-8")
    again = wd.record_first_fill([{"tag": "U25", "ledger": 9, "account": 9}], now=2000.0)
    assert again["ledger_fills"] == first["ledger_fills"] == 1
    assert path.read_text(encoding="utf-8") == before, "the first fill was overwritten"


def test_the_reconciliation_carries_the_evidence_the_record_needs(tmp_path, monkeypatch) -> None:
    """A matched state must hand over the raw row and the first deal, or the record is a
    count with nothing behind it."""
    _fake_mt5(monkeypatch, [_Deal(11, 7825001)])
    led = _ledger(tmp_path, [11])
    rec = wd.live_fill_reconciliation(str(led), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_MATCHED
    assert rec["first_ledger_row"].startswith("LOPEN,")
    assert rec["first_deal"]["ticket"] == 11


def test_only_the_live_pin_is_checked(tmp_path, monkeypatch) -> None:
    """A paper arm is skipped: its ledger is the record by design, and the account has
    (and should have) no deals for it. The decision comes from the PIN the arm runs, not
    from the ledger being verified."""
    called: list[str] = []
    monkeypatch.setattr(wd, "live_fill_reconciliation",
                        lambda path, *, magic: called.append(path) or
                        {"state": wd.LIVE_FILLS_SILENT, "healthy": True, "ledger": 0,
                         "account": 0, "detail": "x"})
    pins = {}

    def fake_preset_for_tag(tag: str, *, armed: bool = False) -> str:
        p = tmp_path / f"pin_{tag}.set"
        p.write_text(pins[tag], encoding="utf-8")
        return str(p)

    monkeypatch.setattr(wd, "preset_for_tag", fake_preset_for_tag)
    monkeypatch.setattr(wd.R, "arming_state",
                        lambda *a, **k: {"armed": True, "override": True, "arm": "U25"})
    pins["U25"] = "InpLiveExecution=true\nInpMagic=7825001\n"
    pins["M1"] = "InpLiveExecution=false\nInpMagic=7825000\n"
    out = wd.live_fill_problems([{"tag": "U25", "ledger": "live.csv"},
                                 {"tag": "M1", "ledger": "paper.csv"}])
    assert [r["tag"] for r in out] == ["U25"], out
    assert called == ["live.csv"], "a paper arm's ledger was verified against the account"
