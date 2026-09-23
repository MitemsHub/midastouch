"""The MT5-VPS-era ingest (`scripts/midas_vps_ingest.py`) — the tally's eyes when
the EA trades on MetaQuotes' disk.

WHY THIS FILE EXISTS. The ingest adopts venue deals into the 30-trade forward
tally — the gate that eventually authorises size. A tool that adopts the wrong
deals doesn't just misreport, it manufactures validation. So every failure
direction discovered before it ran is pinned here:

  * the SHORT SIGN FLIP (found 2026-09-23 before the tool ever touched live
    data): R = dir*(exit-entry)/(entry-sl) divides by a NEGATIVE denominator on
    shorts, reading every winning short as a loser — the tally's whole meaning;
  * magic-0 attribution: the era marker carries no magic, and attributing with
    0 would adopt every unbranded IN deal on the account (the fail-closed rule
    of tests/test_deal_attribution.py);
  * the era gate: without the operator marker the tool is a NO-OP — it never
    manufactures an era;
  * the fail-closed venue: era active + unreadable terminal is a FAIL, because
    "the VPS EA is trading without eyes" is exactly what this tool exists to
    prevent.

PURE: no terminal, no network, no clock, no real artifacts path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_vps_ingest as V  # noqa: E402
import mt5_ops as R  # noqa: E402

OUR = 7825001


def _deal(ticket, magic, entry, position_id, type_, price, sl=0.0,
          time_=0, volume=0.02):
    """A venue deal as the bridge returns it (attribute-shaped, duck-typed)."""
    return SimpleNamespace(ticket=ticket, magic=magic, entry=entry,
                           position_id=position_id, type=type_, price=price,
                           sl=sl, time=time_, volume=volume)


#: The arm's real shape: a short whose IN deal carries the magic and whose
#: platform OUT deal carries magic 0 (measured 2026-09-22, deal 18138688).
SHORT_IN = _deal(18137411, OUR, R.DEAL_ENTRY_IN, 18874164, 1,   # type 1 = SELL
                 4306.19, sl=4327.54, time_=1790170200)
SHORT_OUT = _deal(18138688, 0, R.DEAL_ENTRY_OUT, 18874164, 0,   # BUY closes it
                  4262.39, time_=1790200000)
STRANGER = _deal(777, 999, R.DEAL_ENTRY_IN, 600001, 0, 100.0, sl=101.0,
                 time_=1790170200)


# --- the R formula -----------------------------------------------------------

def test_r_of_a_winning_short_is_positive() -> None:
    """THE regression: `entry - sl` is negative on a short; dividing by it flips
    every short's sign and a +2R winner reads as a loser. The denominator is the
    ABSOLUTE stop distance."""
    r = V._r_of_position(
        {"price": 4306.19, "sl": 4327.54, "type": 1},
        {"price": 4262.39})
    assert r == round(-1 * (4262.39 - 4306.19) / abs(4306.19 - 4327.54), 4)
    assert r > 0


def test_r_sign_matrix_both_directions() -> None:
    win_short = V._r_of_position({"price": 4306.19, "sl": 4327.54, "type": 1},
                                 {"price": 4262.39})
    lose_short = V._r_of_position({"price": 4306.19, "sl": 4327.54, "type": 1},
                                  {"price": 4320.00})
    win_long = V._r_of_position({"price": 4300.00, "sl": 4280.00, "type": 0},
                                {"price": 4340.00})
    lose_long = V._r_of_position({"price": 4300.00, "sl": 4280.00, "type": 0},
                                 {"price": 4290.00})
    assert win_short > 0 and lose_short < 0
    assert win_long > 0 and lose_long < 0
    assert win_long == 2.0 and lose_long == -0.5


def test_r_is_none_without_a_stop_or_prices() -> None:
    assert V._r_of_position({"price": 4306.19, "sl": 0.0, "type": 1},
                            {"price": 4262.39}) is None
    assert V._r_of_position({"price": None, "sl": 4327.54, "type": 1},
                            {"price": 4262.39}) is None
    assert V._r_of_position({"price": 100.0, "sl": 100.0, "type": 0},
                            {"price": 101.0}) is None  # zero stop distance


# --- pairing + attribution (the engine's own rule, not a copy) ---------------

def _ledger(**kw) -> dict:
    """An empty `_ledger_facts()`-shaped world; pass opens=/closes=/stops= to fill."""
    d = {"opens": set(), "closes": set(), "stops": {}}
    d.update(kw)
    return d


def test_platform_closed_short_is_paired_and_counted_fresh() -> None:
    out = V.ingest(OUR, [SHORT_IN, SHORT_OUT, STRANGER], _ledger())
    assert len(out["positions"]) == 1, "the stranger's IN deal must never appear"
    p = out["positions"][0]
    assert p["position_id"] == 18874164
    assert p["close_in_local_ledger"] is False
    assert p["r"] is not None and p["r"] > 0
    assert out["fresh"] == 1
    assert out["tally"] == {"closed": 1, "wins": 1, "sum_r": p["r"]}


def test_a_position_whose_close_the_ledger_has_is_not_recounted() -> None:
    out = V.ingest(OUR, [SHORT_IN, SHORT_OUT],
                   _ledger(closes={18874164}, stops={18874164: 21.71714}))
    assert out["positions"][0]["close_in_local_ledger"] is True
    assert out["fresh"] == 0
    assert out["tally"] == {"closed": 0, "wins": 0, "sum_r": 0}


def test_the_diff_keys_on_closes_not_opens() -> None:
    """MEASURED 2026-09-23 against the real account: the ledger held all four LOPEN
    rows but one LCLOSE — the EA's re-entry moved its tracker before the exit scan
    adopted the manual close. Keying the diff on OPENS reported a tally of zero
    while two closed wins sat uncounted. An open the ledger knows with NO close is
    a tally event."""
    out = V.ingest(OUR, [SHORT_IN, SHORT_OUT],
                   _ledger(opens={18874164}, stops={18874164: 21.71714}))
    p = out["positions"][0]
    assert p["open_in_local_ledger"] is True
    assert p["close_in_local_ledger"] is False
    assert out["fresh"] == 1 and out["tally"]["closed"] == 1


def test_an_open_position_is_not_a_tally_event() -> None:
    out = V.ingest(OUR, [SHORT_IN], _ledger())
    assert out["positions"] == []
    assert out["fresh"] == 0


def test_a_close_without_its_open_is_not_ours() -> None:
    """The fail-closed direction: an OUT deal whose IN we cannot see adopts nothing."""
    orphan_out = _deal(888, 0, R.DEAL_ENTRY_OUT, 999999, 0, 4262.39)
    out = V.ingest(OUR, [orphan_out], _ledger())
    assert out["positions"] == []


# --- the stop join -------------------------------------------------------------

def test_r_falls_back_to_the_ledgers_stop_when_the_venue_has_none() -> None:
    """MEASURED 2026-09-23: the venue's own deals carry NO SL on either side, so
    without the ledger join every real R would be None. The LOPEN stop_d — the
    CERTIFIED stop — is the denominator."""
    no_sl_in = _deal(18137411, OUR, R.DEAL_ENTRY_IN, 18874164, 1, 4306.19,
                     sl=0.0, time_=1790170200)
    out = V.ingest(OUR, [no_sl_in, SHORT_OUT],
                   _ledger(stops={18874164: 21.71714}))
    p = out["positions"][0]
    assert p["r"] == round(-1 * (4262.39 - 4306.19) / 21.71714, 4)
    assert p["r"] > 0
    assert p["stop_d"] == 21.71714


def test_r_is_none_when_no_stop_exists_anywhere() -> None:
    no_sl_in = _deal(18137411, OUR, R.DEAL_ENTRY_IN, 18874164, 1, 4306.19,
                     sl=0.0, time_=1790170200)
    out = V.ingest(OUR, [no_sl_in, SHORT_OUT], _ledger())
    assert out["positions"][0]["r"] is None
    assert out["tally"]["closed"] == 1   # counted, but honestly carrying no R


# --- era gating and main()'s fail-closed directions --------------------------

def _run_main(monkeypatch, tmp_path, *, era=None, deals_reader=None,
              armed_magic=OUR, ledger_ids=None):
    """main() with every world-facing path pointed at tmp; returns (rc, artifact)."""
    era_marker = tmp_path / "midas_vps_hosting.json"
    out_path = tmp_path / "vps_fills.json"
    armed_path = tmp_path / "armed.json"
    if era is not None:
        era_marker.write_text(json.dumps(era), encoding="utf-8")
    armed_path.write_text(json.dumps({"magic": armed_magic}), encoding="utf-8")
    monkeypatch.setattr(V, "ERA_MARKER", str(era_marker))
    monkeypatch.setattr(V, "OUT_PATH", str(out_path))
    monkeypatch.setattr(V, "ARMED_PATH", str(armed_path))
    if deals_reader is not None:
        monkeypatch.setattr(V, "collect_deals", deals_reader)
    else:
        monkeypatch.setattr(V, "collect_deals",
                            lambda: (_ for _ in ()).throw(
                                AssertionError("venue must not be read in this scenario")))
    monkeypatch.setattr(V, "_ledger_facts",
                        lambda: {"opens": set(), "closes": set(), "stops": {}})
    monkeypatch.setattr(sys, "argv", ["midas_vps_ingest.py"])
    rc = V.main()
    artifact = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
    return rc, artifact


def test_no_era_marker_is_a_noop_that_writes_its_reason(monkeypatch, tmp_path) -> None:
    rc, art = _run_main(monkeypatch, tmp_path, era=None)
    assert rc == 0
    assert art["verdict"] == "NO-OP"
    assert "no era marker" in art["problems"][0]


def test_era_with_dark_venue_fails_closed(monkeypatch, tmp_path) -> None:
    def dark():
        raise RuntimeError("mt5.initialize() failed")
    rc, art = _run_main(monkeypatch, tmp_path, era={"subscription": "6911490"},
                        deals_reader=dark)
    assert rc == 2
    assert art["verdict"] == "FAIL"
    assert "without eyes" in art["problems"][0]


def test_era_without_any_magic_fails_before_touching_the_venue(monkeypatch, tmp_path) -> None:
    """Identity resolves BEFORE the venue read: the sentinel deals_reader proves
    the order — attribution with magic 0 must be unreachable, not merely unlikely."""
    rc, art = _run_main(monkeypatch, tmp_path, era={}, armed_magic=0)
    assert rc == 2
    assert art["verdict"] == "FAIL"
    assert "magic" in art["problems"][0]


def test_happy_path_uses_the_arming_record_magic(monkeypatch, tmp_path) -> None:
    rc, art = _run_main(monkeypatch, tmp_path, era={"subscription": "6911490"},
                        deals_reader=lambda: [SHORT_IN, SHORT_OUT])
    assert rc == 0
    assert art["verdict"] == "OK"
    assert art["tally"]["closed"] == 1
    assert art["era"]["subscription"] == "6911490"


# --- magic resolution ---------------------------------------------------------

def test_marker_magic_overrides_the_arming_record(monkeypatch) -> None:
    monkeypatch.setattr(V, "_armed_magic", lambda: OUR)
    assert V._resolve_magic({"magic": 5550001}) == 5550001
    assert V._resolve_magic({}) == OUR
    assert V._resolve_magic({"magic": "not-a-number"}) == OUR
    assert V._resolve_magic({}) == OUR


def test_armed_magic_reader_is_tolerant(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "nope.json"
    assert V._armed_magic(str(missing)) == 0
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert V._armed_magic(str(broken)) == 0
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert V._armed_magic(str(empty)) == 0
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"magic": OUR}), encoding="utf-8")
    assert V._armed_magic(str(good)) == OUR


# --- the ledger-diff join -----------------------------------------------------

def test_ledger_facts_ignore_zeros_and_keep_identifiers_and_stops(tmp_path) -> None:
    """One REAL LOPEN row (arm ledger, 2026-09-23): posid and deal are '0' — a zero
    is not an identity — `order` 19003889 is the venue-side position id, and its
    stop_d is the R denominator the venue's deals never carry."""
    led = tmp_path / "MIDASTOUCH_paper_XAUUSD_U25.csv"
    led.write_text(
        "ERA,MIDAS1.19,1789956934,pertick-fills\n"
        "LOPEN,1790170200,0,19003889,0,-1,4306.19000,4327.54000,4262.39000,"
        "0.02,43.43,21.71714,43200,U25,1790169300,11,0.70381,out,120,cfg=62.51@0.25\n"
        "LCLOSE,1790200000,19003889,EXTERNAL,4262.39000,0.10400\n",
        encoding="utf-8")
    facts = V._ledger_facts([str(led)])
    assert facts["opens"] == {19003889}
    assert facts["closes"] == {19003889}
    assert facts["stops"] == {19003889: 21.71714}
