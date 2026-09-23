#!/usr/bin/env python3
"""The arm's FIRST real fill, three ways at once: venue | ledger row | state stamp.

WHY THIS EXISTS AS A PACKET AND NOT AS A COUNT. `midas_watchdog.live_fill_reconciliation`
answers one question — does the account hold a fill the ledger does not — and it answers it by
comparing identifier SETS. That is the right alarm for "is the audit trail complete", and it is
not enough for the first fill, because the first fill is the only moment when three independent
sources describe the same event while it is still an observation rather than a reconstruction:

  * the VENUE's own deal history — the record, and the only source that can contradict us;
  * the EA's LEDGER row — a claim, written by the thing being audited;
  * the EA's STATE STAMP on that row — the entry's own volatility/hour/news axes, recorded at
    fill time so a pre-registered forward test never has to rebuild them.

So this prints them side by side, field by field, with a verdict per field and every
disagreement NAMED with both values. A count of "1 fill" hides which of the three is wrong.

THE TIME FRAMES ARE THE SUBTLE PART, so they are disclosed rather than assumed. The ledger is
stamped `TimeCurrent()` (broker server). What `history_deals_get` returns depends on the
terminal, so this compares the raw values first and, when they differ, tests the pinned
server->UTC offset and reports which frame each source is in — instead of converting one side
and quietly comparing the result to the other.

Exit codes: 0 nothing yet, or every field agrees; 1 a disagreement; 2 unreadable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import midas_first_fills_audit as audit        # noqa: E402  (the wire contract's owner)
import midas_watchdog as wd                    # noqa: E402  (the completeness alarm)
import mt5_ops as _ops                        # noqa: E402  (whose-deal-is-this, one rule)

#: The live grammars, from the EA's own writers (MidastouchAI.mq5):
#:   LOPEN,<epoch>,<posid>,<order>,<deal>,<dir>,<entry>,<sl>,<tp>,<lots>,<risk_usd>,<stop_d>,
#:         <hold_s>,<tag[_FLOORED]>,<state x5>            -> 14 fixed + up to 5 state fields
#:   LENTRY,<epoch>,<identity>,<entry>,<source>           -> 5   (the v1.25 price amendment)
#:   LCLOSE,<epoch>,<posid>,<reason>,<exit>,<r>           -> 6
#:
#: THE AMENDMENT IS READ, NOT DECORATION. On this venue the entry price is not knowable at the
#: instant the fill is acknowledged (MEASURED 2026-09-22: `ResultPrice()` returned 0 and the row
#: went out as `0.00000` while the position's own price was 4333.07 within the same second), so
#: the row may say `entry=pending` and a later LENTRY row prices it. This packet is the tool
#: that reported `entry price: ledger 0.0 vs venue 4333.07`; a reader that ignores the amendment
#: would keep reporting it after the ledger has been corrected.
#: The state tail sits at the same index as on an OPEN row, which is why `read_state_tail` is
#: reused rather than re-implemented: one wire contract, one reader.
LOPEN_N = 14
LCLOSE_N = 6
#: The venue's deal type codes (MetaTrader5: 0 = buy, 1 = sell), mapped to the ledger's sign
#: convention (`dir` is +1 for a long and -1 for a short).
DEAL_TYPE_SIGN = {0: 1, 1: -1}
TOL_TIME_S = 2          # the ledger stamps the fill the EA saw; the venue stamps the execution
TOL_PRICE = 1e-5
TOL_LOTS = 1e-9


def read_live_ledger(path: str) -> dict:
    """(fills, problems) from a LIVE ledger — LOPEN/LCLOSE rows only.

    A paper ledger has no live rows and returns nothing, which is not an error: it means this
    arm has placed no order yet.
    """
    fills: dict[str, dict] = {}
    order: list[str] = []
    problems: list[str] = []
    amendments: dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for ln, line in enumerate(fh, 1):
                if line.startswith(audit.ENTRY_ROW):
                    for ident, amd in audit.read_entry_rows([line]).items():
                        if ident in amendments and amendments[ident]["price"] != amd["price"]:
                            problems.append(
                                f"line {ln}: LENTRY for {ident} contradicts line "
                                f"{amendments[ident]['line']} "
                                f"({amd['price']} vs {amendments[ident]['price']})")
                        amendments.setdefault(ident, amd)
                    continue
                p = line.strip().split(",")
                if not p or not p[0]:
                    continue
                if p[0] == "LOPEN":
                    if len(p) < LOPEN_N:
                        problems.append(f"line {ln}: LOPEN row has {len(p)} fields (<{LOPEN_N})")
                        continue
                    # THE POSITION'S IDENTITY, from whichever field carries it. MEASURED
                    # 2026-09-22 on the arm's FIRST REAL FILL: the EA writes LOPEN as the fill
                    # is acknowledged, and on a netting account the position id is not
                    # resolvable yet, so `posid` is 0 and `deal` is 0 while `order` holds
                    # 18874164 — which IS the position id ("netting: pos==order; hedging:
                    # pos_id is authoritative").
                    #
                    # READING `p[2]` ALONE KEYED THE LOPEN ROW UNDER "0" AND ITS OWN LCLOSE
                    # UNDER "18874164", so the packet reported the ledger's LOPEN as a fill with
                    # no close AND the ledger's LCLOSE as "the venue holds a fill this ledger
                    # never recorded" — a phantom MISSING_LEDGER_ROW generated from the ledger's
                    # own two rows. The real row: LOPEN,1790092800,0,18874164,0,-1,... and
                    # LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104.
                    posid = p[2] if p[2] and p[2] != "0" else p[3]
                    if posid in fills and "lopen" in fills[posid]:
                        problems.append(f"line {ln}: LOPEN for position {posid} written twice")
                    fills.setdefault(posid, {})["lopen"] = {
                        "line": ln, "epoch": int(p[1]), "posid": posid, "order": p[3],
                        "deal": p[4], "dir": int(p[5]), "entry": float(p[6]),
                        "sl": float(p[7]), "tp": float(p[8]), "lots": float(p[9]),
                        "risk_usd": float(p[10]), "stop_d": float(p[11]),
                        "hold_s": int(p[12]), "tag": p[13],
                        "state": audit.read_state_tail(p),
                        "entry_written": float(p[6]),
                        "pending": bool(audit.read_entry_pending(p)) or float(p[6]) <= 0.0,
                    }
                    if posid not in order:
                        order.append(posid)
                elif p[0] == "LCLOSE":
                    if len(p) < LCLOSE_N:
                        problems.append(f"line {ln}: LCLOSE row has {len(p)} fields (<{LCLOSE_N})")
                        continue
                    fills.setdefault(p[2], {})["lclose"] = {
                        "line": ln, "epoch": int(p[1]), "posid": p[2], "reason": p[3],
                        "exit": float(p[4]), "r": float(p[5])}
    except OSError as exc:
        raise SystemExit(f"cannot read ledger {path}: {exc}")
    # the amendments, applied to the fills they price — on identity, whichever of the row's
    # three identifiers the amendment names. An amendment that prices nothing is a problem, not
    # a decoration: it means a row was written against a fill this ledger does not hold.
    for led in fills.values():
        op = led.get("lopen")
        if not op or not op["pending"]:
            continue
        for ident in (op["posid"], op["order"], op["deal"]):
            amd = amendments.pop(ident, None)
            if amd:
                op["entry"] = amd["price"]
                op["entry_source"] = (f"LENTRY amendment, line {amd['line']}, source "
                                      f"'{amd['source']}'")
                op["pending"] = False
                break
    for ident, amd in amendments.items():
        problems.append(f"line {amd['line']}: LENTRY amendment for {ident} prices no fill row "
                        f"in this ledger")
    return {"fills": {k: fills[k] for k in order},
            "problems": problems,
            "closed": sum(1 for v in fills.values() if "lclose" in v)}


def venue_deals(magic: int, since: float | None = None, reader=None) -> tuple[list[dict], str]:
    """The account's own deals for this magic, or a refusal that says why not.

    `reader` exists so the packet can be tested without a terminal: it is called with
    (since_datetime, until_datetime) and must return objects with the MetaTrader5 deal fields.
    """
    if reader is None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except Exception as exc:       # noqa: BLE001
            return [], f"the MetaTrader5 bridge is unavailable ({exc})"
        if not mt5.initialize():
            return [], f"initialize() failed ({mt5.last_error()})"
        frm = datetime.fromtimestamp(since, timezone.utc) if since else \
            datetime(2000, 1, 1, tzinfo=timezone.utc)
        until = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
        until = until.replace(hour=23, minute=59, second=59)
        try:
            reader = lambda a, b: mt5.history_deals_get(a, b) or []  # noqa: E731
            raw = reader(frm, until)
        except Exception as exc:       # noqa: BLE001
            return [], f"history_deals_get failed ({exc})"
    else:
        raw = reader(None, None)
    deals = []
    for d in raw or []:
        if since is not None and float(getattr(d, "time", 0) or 0) < since:
            continue
        deals.append({"ticket": str(getattr(d, "ticket", "")),
                      "position_id": str(getattr(d, "position_id", "")),
                      "time": float(getattr(d, "time", 0) or 0),
                      "price": float(getattr(d, "price", 0) or 0),
                      "volume": float(getattr(d, "volume", 0) or 0),
                      "type": int(getattr(d, "type", -1)),
                      "entry": int(getattr(d, "entry", -1)),
                      "magic": int(getattr(d, "magic", 0) or 0),
                      "symbol": str(getattr(d, "symbol", "")),
                      "comment": str(getattr(d, "comment", ""))})
    # A CLOSING DEAL IS NOT ALWAYS STAMPED WITH OUR MAGIC (v1.25, MEASURED). On the arm's own
    # first fill the ENTRY deal carried magic 7825001 and the CLOSING deal carried magic 0 —
    # the platform had executed it (its reason field read MOBILE). A history filtered on
    # `magic == ours` therefore loses the close, and this packet then reported the ledger's R
    # against nothing while claiming "the ledger recorded a close the account does not hold".
    # Ownership is a property of the POSITION: an OUT deal is ours iff its position has an IN
    # deal bearing our magic. The attribution is recorded per deal rather than flattened, so a
    # reader can see which deals needed it.
    #
    # THE RULE ITSELF LIVES IN `mt5_ops` NOW, because this was never one reader's problem: the
    # watchdog's ledger reconciliation, this packet and the LV broker monitor all read the venue's
    # deal history, and a rule copied into three files is three rules that can drift. This call site
    # is the reference — it is the one that was correct first — and the others now import it.
    rows, unattributed = _ops.attributed_deals(deals, magic)
    out = [{**row["deal"], "attributed_by": row["attributed_by"]} for row in rows]
    for d in unattributed:
        # Named, never silently dropped: "this reader could not say whose deal this is" is a fact
        # about the venue's stamping that belongs on the record.
        d["attributed_by"] = None
    return out, ""


def _ts(e: float) -> str:
    return datetime.fromtimestamp(e, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def compare_fill(posid: str, led: dict, venue: list[dict]) -> dict:
    """Every field of one fill, both sides, with a verdict and a named disagreement."""
    rows: list[dict] = []

    def check(field: str, lv, vv, ok: bool, note: str = "") -> None:
        rows.append({"field": field, "ledger": lv, "venue": vv,
                     "verdict": "AGREE" if ok else "DISAGREE", "note": note})

    op = led.get("lopen")
    cl = led.get("lclose")
    entry_deal = next((d for d in venue if d["entry"] == 0), None)
    exit_deal = next((d for d in venue if d["entry"] == 1), None)

    if op is None:
        return {"posid": posid, "rows": [{"field": "LOPEN row", "ledger": "absent",
                                          "venue": "present", "verdict": "DISAGREE",
                                          "note": "the venue holds a fill this ledger never "
                                                  "recorded — every R derived from this ledger "
                                                  "is unverified"}],
                "verdict": "MISSING_LEDGER_ROW"}

    # identifier pairing — either identifier may be the one the venue reports
    ids_l = {op["posid"], op["order"], op["deal"]}
    ids_v = {d["ticket"] for d in venue} | {d["position_id"] for d in venue}
    check("identifier", sorted(ids_l), sorted(ids_v), bool(ids_l & ids_v),
          "paired on position id / order / deal ticket, whichever the venue reports")

    if entry_deal:
        raw = abs(op["epoch"] - entry_deal["time"])
        utc = audit.utc_of_server(int(op["epoch"]))
        conv = abs(utc.timestamp() - entry_deal["time"]) if utc else None
        if raw <= TOL_TIME_S:
            check("entry time (s)", int(op["epoch"]), int(entry_deal["time"]), True,
                  "same frame: the ledger's TimeCurrent() and the deal's time agree raw")
        elif conv is not None and conv <= TOL_TIME_S:
            check("entry time (s)", int(op["epoch"]), int(entry_deal["time"]), True,
                  f"AGREE ONLY AFTER CONVERSION: the ledger epoch is SERVER time and the "
                  f"venue's is UTC — {_ts(op['epoch'])} server = {_ts(utc.timestamp())} UTC. "
                  f"A reader that compares them raw is off by the whole offset.")
        else:
            check("entry time (s)", f"{op['epoch']} ({_ts(op['epoch'])})",
                  f"{int(entry_deal['time'])} ({_ts(entry_deal['time'])})", False,
                  "different instants in either frame — not a frame difference")
        # v1.25: THE WRITTEN PRICE MAY NOT BE A PRICE. On this venue the entry price is not
        # knowable at the instant the fill is acknowledged (measured: `ResultPrice()` was 0 and
        # the row went out as `0.00000`), so a row can carry `entry=pending` and a later LENTRY
        # row prices it. Two rules follow, and both are about not making a claim:
        #   * AMENDED — grade the amended figure, and SAY where it came from. A reader that
        #     silently substitutes a number is the defect this row exists to prevent.
        #   * STILL PENDING — do not grade it at all. An unpriced row is an unfinished record,
        #     not a disagreement, and grading it would report the writing date as a difference.
        if op.get("pending") and not op.get("entry_source"):
            rows.append({"field": "entry price", "ledger": "entry=pending",
                         "venue": entry_deal["price"], "verdict": "PENDING",
                         "note": "no price was knowable at write time and no LENTRY amendment "
                                 "has priced it yet: the venue's figure is shown but NOT graded"})
        else:
            note = ""
            if op.get("entry_source"):
                note = (f"the row itself carries {op['entry_written']!r}: the price was UNRESOLVED "
                        f"at write time and this figure is the {op['entry_source']}")
            check("entry price", op["entry"], entry_deal["price"],
                  abs(op["entry"] - entry_deal["price"]) <= TOL_PRICE, note)
        check("lots", op["lots"], entry_deal["volume"],
              abs(op["lots"] - entry_deal["volume"]) <= TOL_LOTS)
        check("direction", op["dir"], DEAL_TYPE_SIGN.get(entry_deal["type"], 0),
              op["dir"] == DEAL_TYPE_SIGN.get(entry_deal["type"], 0),
              "ledger +1/-1 vs deal type 0=buy/1=sell")
        check("symbol", str(op["tag"]), entry_deal["symbol"], True,
              "not a comparison: the ledger does not carry the symbol (it is per-arm)")
    else:
        check("entry deal", "present", "absent", False,
              "the ledger recorded a live open the account's history does not hold")

    if cl and exit_deal:
        check("exit price", cl["exit"], exit_deal["price"],
              abs(cl["exit"] - exit_deal["price"]) <= TOL_PRICE)
        rows.append({"field": "exit reason", "ledger": cl["reason"],
                     "venue": exit_deal["comment"], "verdict": "OBSERVATION",
                     "note": "the venue's comment is free text; the ledger's reason is the EA's "
                             "own classification. Neither grades the other."})
        rows.append({"field": "R (ledger)", "ledger": cl["r"], "venue": "n/a",
                     "verdict": "OBSERVATION",
                     "note": "R is the EA's own arithmetic and is audited by "
                             "midas_first_fills_audit's C check against the venue's OWN H1 "
                             "stop geometry, not against the venue's P&L"})
    elif cl is None:
        rows.append({"field": "LCLOSE row", "ledger": "absent", "venue":
                     "present" if exit_deal else "absent", "verdict": "OPEN",
                     "note": "the position is still open in the ledger — nothing to compare yet"})
    else:
        # A CLOSE row the account cannot confirm. The first draft let this fall through as
        # AGREEMENT because the comparison only ran when BOTH sides had an exit — i.e. the
        # one case where the ledger claims something the venue does not hold was the one case
        # that passed silently. Caught by tests/test_first_fill_packet.py.
        check("exit deal", cl["exit"], "absent", False,
              "the ledger recorded a close the account's own history does not hold — the R on "
              "that row is unverified against the venue")

    state = op.get("state") or {}
    if state.get("malformed"):
        rows.append({"field": "state stamp", "ledger": state["malformed"], "venue": "n/a",
                     "verdict": "DISAGREE", "note": "a half-written stamp is a defect"})
    elif state:
        rows.append({"field": "state stamp", "ledger": json.dumps(state, sort_keys=True),
                     "venue": "n/a", "verdict": "RECORDED",
                     "note": "the EA's own axes at fill time; the forward cell mask reads this "
                             "instead of rebuilding it"})
    else:
        rows.append({"field": "state stamp", "ledger": "absent", "venue": "n/a",
                     "verdict": "ABSENT",
                     "note": "row written before v1.19e, or the stamp is off — the label then "
                             "has to be rebuilt, which is what the stamp exists to avoid"})

    # v1.25: PENDING is not a disagreement and not an agreement — it is a record that cannot be
    # graded yet, so it lands on OPEN ("nothing to compare yet") with its own named row above.
    if any(r["verdict"] == "DISAGREE" for r in rows):
        verdict = "DISAGREE"
    elif cl is None or any(r["verdict"] == "PENDING" for r in rows):
        verdict = "OPEN"
    else:
        verdict = "AGREE"
    return {"posid": posid, "rows": rows, "verdict": verdict}


def build_packet(ledger: str, magic: int, reader=None) -> dict:
    """The whole packet: completeness alarm, then every fill field by field."""
    led = read_live_ledger(ledger)
    # THE READER IS FORWARDED, and that is a fix rather than a convenience: without it the
    # completeness block always queried the live terminal, so this packet's own promise
    # ("Nothing here touches a terminal: the venue side is injected through the `reader` hook")
    # was false for one of its two venue readers, and its test passed only while the account
    # held no deals. MEASURED 2026-09-22: the arm's first real fill made that test fail with
    # `ledger-short` while the ledger had recorded the fill in full.
    recon = wd.live_fill_reconciliation(ledger, magic=magic, reader=reader)
    deals, why = venue_deals(magic, reader=reader)
    by_pos: dict[str, list[dict]] = {}
    for d in deals:
        by_pos.setdefault(d["position_id"], []).append(d)
    compared = []
    for posid, entry in led["fills"].items():
        venue = []
        for pid, ds in by_pos.items():
            ids = {pid} | {d["ticket"] for d in ds}
            if ids & {posid, entry.get("lopen", {}).get("order", ""),
                      entry.get("lopen", {}).get("deal", "")}:
                venue.extend(ds)
        compared.append(compare_fill(posid, entry, venue))
    missing = sorted(set(by_pos) - set(led["fills"]))
    for posid in missing:
        compared.append(compare_fill(posid, {}, by_pos[posid]))
    by_position = sorted({d["position_id"] for d in deals if d.get("attributed_by") == "position"})
    return {"ledger_fills": len(led["fills"]), "ledger_closed": led["closed"],
            "venue_deals": len(deals), "venue_why": why, "ledger_problems": led["problems"],
            # v1.25: the deals a magic filter alone would have dropped, named so the attribution
            # is auditable rather than invisible
            "venue_attributed_by_position": by_position,
            "completeness": recon, "fills": compared,
            "verdict": ("AGREE" if compared and all(c["verdict"] == "AGREE" for c in compared)
                        else "OPEN" if all(c["verdict"] == "OPEN" for c in compared)
                        else "DISAGREE")}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default=None,
                    help="the arm's ledger (default: the U25 ledger in the terminal's Files)")
    ap.add_argument("--magic", type=int, default=None,
                    help="default: InpMagic from the armed preset")
    ap.add_argument("--out", default="artifacts/live/first_fill_packet.json")
    ap.add_argument("--write-always", action="store_true",
                    help="write the packet even when no fill has arrived")
    a = ap.parse_args(argv)

    import mt5_ops as R
    data = R.data_folder_for_terminal()
    ledger = a.ledger or (str(Path(data) / "MQL5" / "Files" /
                             "MIDASTOUCH_paper_XAUUSD_U25.csv") if data else None)
    magic = a.magic
    if magic is None:
        pin = REPO / "mql5" / "MIDASTOUCH" / "MidastouchAI_upcomers_gold_LIVE.set"
        txt = pin.read_text(encoding="utf-8-sig", errors="replace") if pin.is_file() else ""
        magic = int(next((l.split("=")[1] for l in txt.splitlines()
                          if l.startswith("InpMagic=")), "0") or 0)
    if not ledger or not Path(ledger).is_file():
        print(f"REFUSING: no ledger at {ledger}")
        return 2

    print("=== MIDASTOUCH first-fill packet ===")
    print(f"ledger: {ledger}\nmagic : {magic}")
    p = build_packet(str(ledger), magic)
    print(f"\ncompleteness (midas_watchdog.live_fill_reconciliation): {p['completeness']['state']}")
    print(f"  {p['completeness']['detail']}")
    if p.get("venue_attributed_by_position"):
        print(f"  venue deals attributed BY POSITION (their own magic was not ours, the venue "
              f"stamped the executing side): {', '.join(p['venue_attributed_by_position'])}")
    if p["venue_why"]:
        print(f"  venue unreadable: {p['venue_why']} — the packet cannot be completed")
    if not p["fills"]:
        print("\nNO FILLS YET — nothing to compare. This is not a health claim: it says the "
              "ledger holds no live row and the account holds no deal for this magic.")
        if a.write_always:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(json.dumps(p, indent=2), encoding="utf-8")
            print(f"wrote {a.out} (no fill)")
        return 0

    for c in p["fills"]:
        print(f"\n--- position {c['posid']}: {c['verdict']} ---")
        print(f"  {'field':<16} {'ledger':<34} {'venue':<34} verdict")
        for r in c["rows"]:
            print(f"  {r['field']:<16} {str(r['ledger'])[:34]:<34} "
                  f"{str(r['venue'])[:34]:<34} {r['verdict']}")
            if r["note"]:
                print(f"    note: {r['note']}")
    for pr in p["ledger_problems"]:
        print(f"  ledger problem: {pr}")
    print(f"\npacket verdict: {p['verdict']}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(p, indent=2), encoding="utf-8")
    print(f"wrote {a.out}")
    return 1 if p["verdict"] == "DISAGREE" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
