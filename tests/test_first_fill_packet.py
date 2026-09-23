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
          entry: int, comment: str = "", magic: int = MAGIC) -> SimpleNamespace:
    return SimpleNamespace(ticket=ticket, position_id=position_id, time=t, price=price,
                           volume=volume, type=type_, entry=entry, magic=magic,
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


def test_a_netting_fill_pairs_its_own_lopen_and_lclose(tmp_path: Path) -> None:
    """MEASURED 2026-09-22 on the arm's FIRST REAL FILL, and the reason this shape is pinned.

    The EA writes `LOPEN` as the fill is acknowledged, so on a NETTING account `posid` and
    `deal` are 0 and the ORDER ticket holds the position id (its own journal: "fill
    acknowledged but owned position not yet selectable — IDs will reconcile on the next tick").
    Reading `posid` alone keyed the LOPEN row under "0" and its own LCLOSE under "18874164",
    so the packet reported the ledger's LOPEN as a fill with no close AND the ledger's LCLOSE
    as "the venue holds a fill this ledger never recorded" — a phantom MISSING_LEDGER_ROW
    generated from the ledger's own two rows, about a fill that was recorded in full.

    The rows and the deal below are the real values, unedited:
      LOPEN ,1790092800(14:00Z) ,0 ,18874164 ,0 ,-1 ...
      LCLOSE,1790093197(14:06Z) ,18874164 ,EXTERNAL ,4328.76000 ,+0.104
      deal: ticket 18137411, position_id 18874164, price 4333.07, type 1 (sell), magic 7825001
    """
    led = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    led.write_text("ERA,MIDAS1.23,1790091000,pertick-fills\nEQ,25000.00\n"
                   "LOPEN,1790092800,0,18874164,0,-1,0.00000,4374.38000,4250.77000,0.01,"
                   "41.20,41.20143,43200,U25,1790091900,13,1.39453,out,120\n"
                   "LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104\n",
                   encoding="utf-8")
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(
        _deal("18137411", "18874164", 1790092800, 4333.07, 0.01, 1, 0, "MIDAS")))
    assert [f["posid"] for f in p["fills"]] == ["18874164"], p["fills"]
    assert not any(f["verdict"] == "MISSING_LEDGER_ROW" for f in p["fills"]), \
        "the ledger's own LCLOSE was read as a venue fill the ledger never recorded"
    verdicts = {r["field"]: r["verdict"] for r in p["fills"][0]["rows"]}
    assert verdicts["identifier"] == "AGREE"
    assert verdicts["entry time (s)"] == "AGREE"
    assert verdicts["lots"] == "AGREE" and verdicts["direction"] == "AGREE"
    # The close PAIRED to its own open: the only way this key appears is the branch that fires
    # when the ledger has no LCLOSE at all, which is what the old reading produced.
    assert "LCLOSE row" not in verdicts, "the close did not pair to its own open"
    # THE ONE THAT USED TO DISAGREE, and it was a real gap in the arm's record rather than a
    # reader's bug: the ledger's LOPEN carries entry 0.00000 because it is written before the
    # fill price is known. The pin was placed here so that fixing it in the EA would have to
    # change this test — v1.25 is that change. A row with no price and NO amendment is now
    # reported as PENDING ("an unfinished record, not a disagreement") and the fill lands on
    # OPEN; `test_an_lentry_amendment_prices_the_row_it_amends` below is the same fill after
    # the amendment, which is what the ledger will carry on the next start.
    assert verdicts["entry price"] == "PENDING", verdicts
    assert p["fills"][0]["rows"][2]["ledger"] == "entry=pending", p["fills"][0]["rows"][2]
    # And the second honest one stays: the position was closed by the VENUE (the ledger's own
    # LCLOSE says EXTERNAL) and THIS venue stamps the closing deal with magic 0, so a deal
    # history filtered by our magic holds the entry and not the close. NOTHING here grades the
    # ledger's R against a close the reader cannot see — the fill is DISAGREE for that reason
    # and the row names it. (The EA's own day-P&L attribution was fixed for the same defect in
    # v1.25; this reader is pinned by `test_the_closing_deal_with_magic_zero_is_attributed_by_position`.)
    assert verdicts["exit deal"] == "DISAGREE", verdicts
    assert p["fills"][0]["verdict"] == "DISAGREE", p["fills"][0]


def test_an_lentry_amendment_prices_the_row_it_amends(tmp_path: Path) -> None:
    """THE AMENDMENT IS READ, AND WHERE IT CAME FROM IS PRINTED.

    MEASURED 2026-09-22: the arm's one live fill row carries `entry=0.00000`, and the venue's
    own entry deal — ticket 18137411, price 4333.07 — carried the real price in the same second.
    v1.25 writes `LENTRY,<epoch>,<identity>,<price>,<source>` once the venue answers, so the
    ledger can state the price it could not know at write time. A reader that ignored the
    amendment would keep reporting the disagreement the amendment exists to remove; a reader
    that substituted it silently would be worse. So: the amended figure is graded AND named.
    """
    led = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    led.write_text("ERA,MIDAS1.25,1790091000,pertick-fills+fill-price-heal\nEQ,25000.00\n"
                   "LOPEN,1790092800,0,18874164,0,-1,0.00000,4374.38000,4250.77000,0.01,"
                   "41.20,41.20143,43200,U25,1790091900,13,1.39453,out,120,entry=pending,"
                   "cfg=62.50@0.25\n"
                   "LENTRY,1790092990,18874164,4333.07000,entry deal\n"
                   "LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104\n",
                   encoding="utf-8")
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(
        _deal("18137411", "18874164", 1790092800, 4333.07, 0.01, 1, 0, "MIDAS")))
    assert p["ledger_problems"] == [], p["ledger_problems"]
    rows = {r["field"]: r for r in p["fills"][0]["rows"]}
    assert rows["entry price"]["verdict"] == "AGREE", rows["entry price"]
    assert rows["entry price"]["ledger"] == 4333.07, rows["entry price"]
    assert "LENTRY amendment" in rows["entry price"]["note"], rows["entry price"]
    assert "0.0" in rows["entry price"]["note"], (
        "the note must show the UNRESOLVED figure the row was written with, or the reader "
        "cannot tell an amended row from a row that always knew")


def test_the_closing_deal_with_magic_zero_is_attributed_by_position(tmp_path: Path) -> None:
    """THE VENUE STAMPS THE EXECUTING SIDE, NOT THE ARM (v1.25, MEASURED).

    On the arm's own fill the ENTRY deal carried magic 7825001 and the CLOSING deal carried
    **magic 0** — the platform had executed the close (its reason field read MOBILE). A history
    filtered on `magic == ours` therefore holds the entry and NOT the close, and this packet
    reported a disagreement about a close the venue really did execute. The EA's day-P&L was
    fixed for exactly this reason (v1.25, `PropDayRealisedPnlUtc` attributes by POSITION); this
    is the same rule on the reader side, and the deal that needed it is NAMED in the packet.
    """
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC), _lclose(ENTRY_UTC + 300, 4320.00, 2.0)])
    p = ffp.build_packet(str(led), MAGIC, reader=_reader(
        _entry_deal(),
        _deal("309099", "308417", ENTRY_UTC + 300, 4320.00, 0.01, 1, 1, "MOBILE", magic=0)))
    assert p["venue_deals"] == 2, p["venue_deals"]
    assert p["venue_attributed_by_position"] == ["308417"], p["venue_attributed_by_position"]
    verdicts = {r["field"]: r["verdict"] for r in p["fills"][0]["rows"]}
    # the "exit deal: absent" row is the shape of a MISSING close — with the close attributed,
    # it must not appear at all, and the price is graded against the deal that carried it
    assert "exit deal" not in verdicts, verdicts
    assert verdicts["exit price"] == "AGREE", verdicts
    assert p["fills"][0]["verdict"] == "AGREE", p["fills"][0]


def test_a_strangers_deal_is_still_refused(tmp_path: Path) -> None:
    """The fail-closed direction, because attribution by position is a widening.

    An OUT deal whose position has NO entry deal of ours is somebody else's trade: it must not
    be adopted, and a position the ledger does not hold must still surface as the alarm.
    """
    led = _ledger(tmp_path, [_lopen(ENTRY_UTC), _lclose(ENTRY_UTC + 300, 4320.00, 2.0)])
    deals, why = ffp.venue_deals(MAGIC, reader=_reader(
        _entry_deal(),
        _deal("309099", "999999", ENTRY_UTC + 300, 4320.00, 0.01, 1, 1, "", magic=0)))
    assert why == ""
    assert [d["ticket"] for d in deals] == ["309004"], deals


def test_an_amendment_that_prices_nothing_is_a_problem(tmp_path: Path) -> None:
    """An LENTRY row names an identity; if no fill row in this ledger carries it, something
    wrote a price amendment for a trade this ledger does not hold. Reported, not dropped."""
    led = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    led.write_text("LOPEN,1790092800,0,18874164,0,-1,4333.07000,4374.38000,4250.77000,0.01,"
                   "41.20,41.20143,43200,U25\n"
                   "LENTRY,1790092990,99999999,4333.07000,entry deal\n", encoding="utf-8")
    led_out = ffp.read_live_ledger(str(led))
    assert any("prices no fill row" in p for p in led_out["problems"]), led_out["problems"]


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
    # THE PACKET FOLLOWS THE CAPTURE. MEASURED 2026-09-22: the packet path was hardcoded, so
    # this test (which redirects the capture to tmp_path) wrote its synthetic packet — posid
    # 308417, a position that never existed — into `artifacts/live/`, the arm's own record.
    # A record written by a test is not a record; the two paths are one location now.
    assert (tmp_path / "first_fill_packet.json").is_file(), (
        "the packet must be written beside the capture, not at a second location")
    assert rec["packet"]["path"].startswith(str(tmp_path)), rec["packet"]["path"]


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
