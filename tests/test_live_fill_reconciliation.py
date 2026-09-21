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
    def __init__(self, ticket: int, magic: int, time: float = 1789712100.0):
        self.ticket, self.magic, self.time = ticket, magic, time


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


def test_matching_fills_reconcile(tmp_path, monkeypatch) -> None:
    _fake_mt5(monkeypatch, [_Deal(11, 7825001), _Deal(12, 7825001)])
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [11, 12])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_MATCHED and rec["healthy"] is True
    assert rec["ledger"] == rec["account"] == 2


def test_another_arms_magic_is_not_this_arms_evidence(tmp_path, monkeypatch) -> None:
    """The portfolio shares an account: a sibling arm's deals must not count here."""
    _fake_mt5(monkeypatch, [_Deal(99, 1111111)])
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_SILENT, "a foreign magic produced a fill claim"


def test_an_unqueryable_terminal_is_unknown_not_healthy(tmp_path, monkeypatch) -> None:
    _fake_mt5(monkeypatch, None, initialize=False)
    rec = wd.live_fill_reconciliation(str(_ledger(tmp_path, [])), magic=7825001)
    assert rec["state"] == wd.LIVE_FILLS_UNREADABLE and rec["healthy"] is False


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
