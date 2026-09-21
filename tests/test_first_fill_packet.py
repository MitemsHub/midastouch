"""The first-fill packet: three sources side by side, and every disagreement named.

WHY THIS FILE EXISTS. `midas_watchdog.live_fill_reconciliation` answers "is the audit trail
complete" by comparing identifier SETS, and that is the right alarm for that question. It is
not enough for the arm's FIRST fill, which is the only moment the venue's deal history, the
EA's ledger row and the EA's state stamp describe the same event while it is still an
observation rather than a reconstruction — and a count of "1 fill" cannot say which of the
three is wrong. So the packet compares them field by field, and these tests pin the four
outcomes that matter: agreement, a named disagreement, a ledger row the venue has and the
ledger does not, and the server-vs-UTC frame case, which must be DISCLOSED (the two agree only
after conversion) rather than silently converted on one side.

Nothing here touches a terminal: the venue side is injected through the `reader` hook.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_first_fill_packet as ffp  # noqa: E402

MAGIC = 7825001
#: 2026-09-21 19:15:00 UTC, and the venue's asserted +2 h server offset for this era.
ENTRY_UTC = 1790008500
SERVER_OFFSET_S = 2 * 3600
STATE_TAIL = "1790007600,19,0.812500,out,120"      # sig_ct, hour_utc, vol_ratio, news, off_min


def _lopen(epoch: int, entry: float = 4311.42, lots: float = 0.01, direction: int = 1,
           posid: str = "308417", state: str = STATE_TAIL) -> str:
    return (f"LOPEN,{epoch},{posid},309001,309004,{direction},{entry},4300.0,4400.0,{lots},"
            f"33.09,33.09,43200,U25,{state}")


def _lclose(epoch: int, exit_: float = 4320.00, r: float = 2.0, posid: str = "308417") -> str:
    return f"LCLOSE,{epoch},{posid},TP,{exit_},{r}"


def _ledger(tmp_path: Path, rows: list[str], name: str = "MIDASTOUCH_paper_XAUUSD_U25.csv") -> Path:
    (tmp_path / "MQL5" / "Files").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "MQL5" / "Files" / name
    p.write_text("ERA,MIDAS1.19,1790008000,pertick-fills\nEQ,25000.00\n" + "\n".join(rows) + "\n",
                 encoding="utf-8")
    return p


def _deal(ticket: str, position_id: str, t: float, price: float, volume: float, type_: int,
          entry: int, comment: str = "") -> SimpleNamespace:
    return SimpleNamespace(ticket=ticket, position_id=position_id, time=t, price=price,
                           volume=volume, type=type_, entry=entry, magic=MAGIC,
                           symbol="XAUUSD", comment=comment)


def _entry_deal(t: float = ENTRY_UTC, price: float = 4311.42, volume: float = 0.01,
                type_: int = 0) -> SimpleNamespace:
    return _deal("309004", "308417", t, price, volume, type_, 0, "U25")


def _reader(*deals):
    return lambda a, b: list(deals)


def test_a_correct_closed_fill_agrees_field_by_field(tmp_path: Path) -> None:
    """The happy path still has to be checkable: same instant, price, size, side, exit."""
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC), _lclose(ENTRY_UTC + 3600)])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(
        _entry_deal(),
        _deal("309009", "308417", ENTRY_UTC + 3600, 4320.00, 0.01, 1, 1, "TP")))
    c = p["fills"][0]
    assert c["verdict"] == "AGREE", c["rows"]
    verdicts = {r["field"]: r["verdict"] for r in c["rows"]}
    assert verdicts["exit price"] == "AGREE"
    assert verdicts["exit deal"] if "exit deal" in verdicts else True
    assert any(r["field"] == "exit reason" for r in c["rows"]), \
        "the exit reason and the venue's comment must both be shown"
    assert verdicts["identifier"] == "AGREE"
    assert verdicts["entry price"] == "AGREE"
    assert verdicts["lots"] == "AGREE"
    assert verdicts["direction"] == "AGREE"
    assert verdicts["state stamp"] == "RECORDED"
    note = next(r for r in c["rows"] if r["field"] == "entry time (s)")
    assert note["verdict"] == "AGREE" and "same frame" in note["note"], note


def test_an_open_ledger_row_with_no_exit_deal_is_open_not_agreed(tmp_path: Path) -> None:
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC)])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(_entry_deal()))
    c = p["fills"][0]
    assert c["verdict"] == "OPEN"
    assert any(r["field"] == "LCLOSE row" and r["verdict"] == "OPEN" for r in c["rows"])


def test_a_close_the_venue_does_not_hold_is_a_disagreement(tmp_path: Path) -> None:
    """The first draft fell through to AGREEMENT here — the one case where the ledger claims
    something the venue does not hold was the one case that passed silently."""
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC), _lclose(ENTRY_UTC + 3600)])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(_entry_deal()))
    row = next(r for r in p["fills"][0]["rows"] if r["field"] == "exit deal")
    assert row["verdict"] == "DISAGREE" and "does not hold" in row["note"]
    assert p["verdict"] == "DISAGREE"


def test_a_price_disagreement_is_named_with_both_values(tmp_path: Path) -> None:
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC)])
    p = ffp.build_packet(str(led), MAGIC,
                         reader=_reader(_entry_deal(price=4312.00)))
    row = next(r for r in p["fills"][0]["rows"] if r["field"] == "entry price")
    assert row["verdict"] == "DISAGREE"
    assert row["ledger"] == 4311.42 and row["venue"] == 4312.0
    assert p["verdict"] == "DISAGREE"


def test_a_deal_the_ledger_never_recorded_is_the_alarm(tmp_path: Path) -> None:
    """The venue holds a fill with no ledger row: every R from that ledger is unverified."""
    led = _ledger(tmp_path, [])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(_entry_deal()))
    assert p["verdict"] == "DISAGREE"
    assert p["fills"][0]["verdict"] == "MISSING_LEDGER_ROW"
    assert "never recorded" in p["fills"][0]["rows"][0]["note"]


def test_the_ledger_has_a_live_row_the_venue_does_not(tmp_path: Path) -> None:
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC)])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader())
    row = next(r for r in p["fills"][0]["rows"] if r["field"] == "entry deal")
    assert row["verdict"] == "DISAGREE"


def test_the_server_versus_utc_frame_is_disclosed_not_silently_converted(tmp_path: Path) -> None:
    """The case that decides whether a reader is off by the whole offset.

    The ledger stamps `TimeCurrent()` (broker server); what `history_deals_get` returns is the
    terminal's business. If the two agree only after the pinned offset, the packet must SAY so
    — a silent conversion on one side would make every later comparison unfalsifiable.
    """
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC + SERVER_OFFSET_S)])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(_entry_deal()))
    row = next(r for r in p["fills"][0]["rows"] if r["field"] == "entry time (s)")
    assert row["verdict"] == "AGREE"
    assert "ONLY AFTER CONVERSION" in row["note"] and "SERVER" in row["note"], row["note"]


def test_a_real_time_disagreement_is_not_excused_as_a_frame_difference(tmp_path: Path) -> None:
    """Off by neither zero nor the offset is a different instant, and must fail."""
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC + 90)])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(_entry_deal()))
    row = next(r for r in p["fills"][0]["rows"] if r["field"] == "entry time (s)")
    assert row["verdict"] == "DISAGREE"
    assert "not a frame difference" in row["note"]


def test_a_half_written_state_stamp_is_a_defect(tmp_path: Path) -> None:
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC, state="1790007600,19")])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(_entry_deal()))
    row = next(r for r in p["fills"][0]["rows"] if r["field"] == "state stamp")
    assert row["verdict"] == "DISAGREE" and "half-written" in row["note"]


def test_an_absent_state_stamp_is_not_a_defect(tmp_path: Path) -> None:
    """Rows written before v1.19e have no tail, and the stamp is off in tester runs."""
    led = _ledger(tmp_path, [",".join(_lopen(ENTRY_UTC).split(",")[:14])])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(_entry_deal()))
    row = next(r for r in p["fills"][0]["rows"] if r["field"] == "state stamp")
    assert row["verdict"] == "ABSENT"


def test_no_fills_is_reported_as_nothing_yet(tmp_path: Path) -> None:
    led = _ledger(tmp_path, [])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader())
    assert p["fills"] == [] and p["verdict"] == "OPEN"
    assert p["completeness"]["state"] == "silent-both"


def test_a_malformed_live_row_is_reported_not_guessed(tmp_path: Path) -> None:
    led = _ledger(tmp_path, ["LOPEN,1790008500,308417,309001"])
    led_data = ffp.read_live_ledger(str(led))
    assert led_data["fills"] == {} and led_data["problems"]
    assert "LOPEN row has 4 fields" in led_data["problems"][0]


def test_a_paper_ledger_yields_no_live_rows(tmp_path: Path) -> None:
    """The paper book's OPEN rows are not live fills, and the packet must not invent them."""
    led = _ledger(tmp_path,
                  ["OPEN,1790008500,111,1,4300.0,4240.0,4360.0,0.10,5.87,58.71,720,U25",
                   "CLOSE,1790008600,111,TP,4360.0,2.05,10.25,60.25"])
    led_data = ffp.read_live_ledger(str(led))
    assert led_data["fills"] == {} and led_data["problems"] == []


# --- the firing path: the watchdog must run the packet at the first fill -----------

def test_the_watchdog_runs_the_packet_when_the_first_fill_lands(
        tmp_path: Path, monkeypatch) -> None:
    """`record_first_fill` is the moment; the packet is what makes it a report.

    The identifier-set alarm says the trail is complete, which is not the same as the two
    sides agreeing on price, size, side and time. This pins that the record carries the
    packet's verdict AND its named disagreements — a verdict alone would send a reader back
    to the raw sources to find out what disagreed.
    """
    import midas_watchdog as wd
    monkeypatch.setattr(wd, "FIRST_FILL_PATH", str(tmp_path / "first_fill.json"))
    monkeypatch.setattr(ffp, "build_packet", lambda ledger, magic: {
        "verdict": "DISAGREE",
        "fills": [{"posid": "308417", "verdict": "DISAGREE",
                   "rows": [{"field": "entry price", "ledger": 4311.42, "venue": 4312.0,
                             "verdict": "DISAGREE", "note": ""}]}],
    })
    rec = wd.record_first_fill([{"tag": "U25", "state": "matched", "ledger": 1, "account": 1,
                                 "ledger_path": str(tmp_path / "led.csv"),
                                 "magic": MAGIC, "first_ledger_row": "LOPEN,...",
                                 "first_deal": None}],
                               now=1790008500.0)
    assert rec and rec["packet"]["verdict"] == "DISAGREE"
    assert rec["packet"]["paths"] == ["DISAGREE"]
    bad = rec["packet"]["disagreements"]
    assert bad == [{"position": "308417", "field": "entry price",
                    "ledger": 4311.42, "venue": 4312.0}], bad


def test_the_record_survives_a_packet_that_cannot_run(tmp_path: Path, monkeypatch) -> None:
    """A packet failure must never lose the fill record itself."""
    import midas_watchdog as wd
    monkeypatch.setattr(wd, "FIRST_FILL_PATH", str(tmp_path / "first_fill.json"))

    def boom(ledger, magic):
        raise RuntimeError("terminal exploded")

    monkeypatch.setattr(ffp, "build_packet", boom)
    rec = wd.record_first_fill([{"tag": "U25", "state": "matched", "ledger": 1, "account": 1,
                                 "ledger_path": str(tmp_path / "led.csv"), "magic": MAGIC}],
                               now=1790008500.0)
    assert rec and rec["state"] == "matched"
    assert rec["packet"]["verdict"] == "UNREADABLE"
    assert "terminal exploded" in rec["packet"]["why"]
