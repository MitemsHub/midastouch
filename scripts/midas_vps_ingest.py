"""Keep the tally alive in the MT5-VPS era: ingest the VPS EA's trades from the venue.

WHY THIS EXISTS (the blind-EA problem, docs/VPS_MIGRATION_RUNBOOK_20260923.md §0c/§0d):
the built-in MetaTrader VPS writes the EA's ledger on MetaQuotes' own disk, where no
tool on this side can read it. But the ACCOUNT's deal history is a transport both sides
see — the local terminal is signed into the same account, so every VPS-era fill and
close arrives in the local history sync. This tool diffs that history against the local
ledger and records the delta, so the 30-trade forward tally and the paper gate keep
counting while the EA trades blind-hosted.

DESIGN (docs/VPS_MIGRATION_RUNBOOK_20260923.md §0d):
  * Era-gated: a NO-OP unless artifacts/midas_vps_hosting.json exists (the same marker
    midas_watchdog.vps_hosting_active and morning_status [3b] read). Without the era
    there is nothing to ingest and running it would manufacture a fake era.
  * Attribution reuses the engine's own rule (mt5_ops.attribute_deal): a deal belongs
    to the arm by MAGIC, or BY POSITION when its position's entry deal carries the
    magic — the exact rule that already adopted this arm's three platform-closed
    positions (the venue stamps platform closes with magic 0).
  * Read-only: this writes one artifact and mutates nothing else — no orders, no
    terminal state, no ledger edits. The tally CONSUMES it; nothing here changes the
    ledger (the ledger is the EA's voice, not ours to edit).
  * Fail-closed: an unreadable venue and an era marker present is a FAIL (the era
    without eyes is exactly what this tool exists to prevent), not an empty OK.

Output: artifacts/live/vps_fills.json —
    {"era": {...}, "ts": ..., "positions": [...], "tally": {"closed": N, "wins": W,
     "sum_r": X}, "verdict": "OK"|"FAIL", "problems": [...]}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mt5_ops as R  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERA_MARKER = os.path.join(REPO, "artifacts", "midas_vps_hosting.json")
OUT_PATH = os.path.join(REPO, "artifacts", "live", "vps_fills.json")
ARMED_PATH = os.path.join(REPO, "artifacts", "live", "armed.json")

#: The risk denominator per position, in price units, from the venue's own deal pair:
#: R = (exit - entry) * dir / stop_distance. The stop comes from the SL the EA attached;
#: for positions whose SL was later moved (none yet), the OPEN deal's SL is what the
#: certification was made on — the ingest reports the R the strategy defined, not the
#: R a trailing hand gave it.
def _r_of_position(entry: dict, close: dict) -> float | None:
    """R = dir * (exit - entry) / stop_distance, dir +1 long / -1 short.

    The denominator is the ABSOLUTE stop distance: `entry - sl` is negative for a
    short, and dividing by it flips every short's sign — a winning short read as -1R.
    MEASURED against the arm's own opens (all shorts) before this tool ever ran."""
    sl = entry.get("sl")
    if not sl or not entry.get("price") or not close.get("price"):
        return None
    stop_d = abs(entry["price"] - sl)
    if not stop_d:
        return None
    dirn = 1.0 if entry.get("type") == 0 else -1.0   # mt5 DEAL_TYPE_BUY = 0 (a long entry)
    return round(dirn * (close["price"] - entry["price"]) / stop_d, 4)


def era_active(marker_path: str = "") -> bool:
    """Read through the module global at CALL time (a default parameter binds at def
    time and cannot be patched — the exact trap that broke the [3b] fixtures)."""
    return os.path.exists(marker_path or ERA_MARKER)


def collect_deals(reader=None):
    """All account deals, wide window. `reader(from_dt, until_dt)` injectable for tests."""
    frm = datetime(2000, 1, 1, tzinfo=timezone.utc)
    until = datetime.now(timezone.utc) + timedelta(days=1)
    if reader is None:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")
        try:
            return list(mt5.history_deals_get(frm, until) or [])
        finally:
            mt5.shutdown()
    return list(reader(frm, until) or [])


def ingest(magic: int, deals: list, known_ids: set[int]) -> dict:
    """One pass: attribute the deals, pair positions, diff against the ledger.

    `magic` comes from the ARMING RECORD (resolved by main), never defaulted: the
    era marker carries no magic, and attributing with magic 0 would adopt every
    unbranded IN deal on the account — the one direction attribution must not
    fail in (tests/test_deal_attribution.py)."""
    ours_positions = R.our_positions_from_deals(deals, magic)
    by_pos: dict[int, dict] = {}
    for d in deals:
        if R.attribute_deal(d, magic, ours_positions) is None:
            continue
        pid = getattr(d, "position_id", None)
        if pid is None:
            continue
        side = by_pos.setdefault(pid, {"entry": None, "closes": []})
        rec = {"ticket": getattr(d, "ticket", None),
               "time": getattr(d, "time", None),
               "price": getattr(d, "price", None),
               "volume": getattr(d, "volume", None),
               "type": getattr(d, "type", None),
               "sl": getattr(d, "sl", None),
               "magic": getattr(d, "magic", None)}
        # DEAL_TYPE_BUY sells the position (a close on a hedging account) — mirror the
        # reconciliation's rule: entry is the deal whose side OPENS in the magic's
        # direction; simplest robust rule here: first-seen deal is the entry, later
        # opposite-side deals are closes.
        if side["entry"] is None:
            side["entry"] = rec
        else:
            side["closes"].append(rec)

    positions = []
    for pid in sorted(by_pos):
        e = by_pos[pid]["entry"]
        if e is None or not by_pos[pid]["closes"]:
            continue  # still open, or an unpaired entry — not a tally event yet
        last_close = by_pos[pid]["closes"][-1]
        r = _r_of_position(e, last_close)
        positions.append({
            "position_id": pid,
            "opened_utc": datetime.fromtimestamp(e["time"], timezone.utc).isoformat() if e["time"] else None,
            "closed_utc": datetime.fromtimestamp(last_close["time"], timezone.utc).isoformat() if last_close["time"] else None,
            "entry": e["price"], "exit": last_close["price"], "sl": e["sl"],
            "volume": last_close["volume"] or e["volume"],
            "r": r,
            "in_local_ledger": pid in known_ids,
        })
    fresh = [p for p in positions if not p["in_local_ledger"]]
    closed = len(fresh)
    wins = sum(1 for p in fresh if (p["r"] or 0) > 0)
    sum_r = round(sum(p["r"] for p in fresh if p["r"] is not None), 4)
    return {"positions": positions, "fresh": len(fresh),
            "tally": {"closed": closed, "wins": wins, "sum_r": sum_r}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a = ap.parse_args()

    era = None
    if era_active():
        try:
            era = json.load(open(ERA_MARKER, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL: era marker unreadable ({exc})")
            return 2

    out = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "artifact": "vps_fills", "era": era, "verdict": "OK", "problems": []}

    if era is None:
        out["verdict"] = "NO-OP"
        out["problems"].append("no era marker (midas_vps_hosting.json) — not in the "
                               "MT5-VPS era; there is nothing to ingest and this tool "
                               "does not manufacture one")
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(out["problems"][0])
        return 0

    # Era active: identity first, then the venue. The magic is the ARming record's
    # (top-level `magic`), with an era-marker override for a rehearsal arm. Both
    # silent is a FAIL — attribution with magic 0 would adopt strangers' deals.
    magic = _resolve_magic(era)
    if not magic:
        out["verdict"] = "FAIL"
        out["problems"].append("era is active but no usable magic exists (arming "
                               "record and era marker both silent) — attribution "
                               "with magic 0 would adopt strangers' IN deals")
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(out["problems"][0])
        return 2

    try:
        deals = collect_deals()
    except Exception as exc:
        out["verdict"] = "FAIL"
        out["problems"].append(f"era is active but the venue cannot be read ({exc}) — "
                               f"the VPS EA is trading without eyes; fix the terminal "
                               f"bridge before relying on the era")
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(out["problems"][0])
        return 2

    known = _ledger_position_ids()
    result = ingest(magic, deals, known)
    out.update(result)
    out["tally_note"] = ("VPS-era closed positions by venue attribution — the tally "
                         "consumer adds these to the ledger's own closes")
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"vps_fills: {result['fresh']} new closed position(s) outside the local "
          f"ledger, tally sum_r {result['tally']['sum_r']:+.4f} -> {OUT_PATH}")
    return 0


def _armed_magic(armed_path: str = "") -> int:
    """The arm's identity from the ARMING RECORD (call-time path: patchable, the
    [3b] lesson). 0 when silent — and 0 is never used for attribution (main fails)."""
    try:
        armed = json.load(open(armed_path or ARMED_PATH, encoding="utf-8"))
        return int(armed.get("magic") or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def _resolve_magic(era: dict) -> int:
    """Arming record first; an era-marker `magic` overrides (a rehearsal arm runs
    its own identity). Zero from both is returned as 0 and FAILS in main."""
    magic = _armed_magic()
    try:
        marker_magic = int(era.get("magic") or 0)
    except (TypeError, ValueError):
        marker_magic = 0
    return marker_magic or magic


def _ledger_position_ids(ledger_paths: list[str] | None = None) -> set[int]:
    """Position ids the local ledger already knows (any of its identifier fields).

    `ledger_paths` injectable for tests; the default scans every terminal data
    folder's MIDASTOUCH ledger (the arm's identity is the magic, the suffix is
    the arm tag, so the glob spans tags deliberately)."""
    import glob
    from pathlib import Path
    from midas_arm_record import read_rows  # scripts/ already on sys.path
    if ledger_paths is None:
        ledger_paths = glob.glob(os.path.join(
            os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "*",
            "MQL5", "Files", "MIDASTOUCH_paper_XAUUSD_*.csv"))
    ids: set[int] = set()
    for a in ledger_paths:
        rows = read_rows(Path(a))
        for r in rows["rows"].get("lopen", []):
            for k in ("posid", "order", "deal"):
                v = str(r.get(k) or "").strip()
                if v and v != "0":   # a zero is not an identifier (the reconciliation's rule)
                    try:
                        ids.add(int(v))
                    except ValueError:
                        continue
    return ids


if __name__ == "__main__":
    raise SystemExit(main())
