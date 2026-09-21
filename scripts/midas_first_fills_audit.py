#!/usr/bin/env python3
"""MIDASTOUCH first-fills audit — mechanical rule compliance for the live
paper ledger (protocol discipline: the acceptance rule is written BEFORE
the evidence it grades, so trade #1 is audited exactly like trade #150).

TWO FRAMES, AND THE AUDIT HAS TO SAY WHICH IS WHICH. The ledger's epochs are broker SERVER
time — the EA writes `TimeCurrent()` (mql5/MIDASTOUCH/MidastouchAI.mq5, "Ledger row stamps
stay TimeCurrent() as frame-") — while the session gate is a UTC policy. So the session check
converts with the pinned era in `configs/mt5/server_offsets.json` and REFUSES (discloses
UNVERIFIABLE) for a month whose DST step makes the offset unresolvable, instead of grading a
server-clock hour against a UTC rule. The stop-geometry check needs no conversion: it compares
the ledger against the venue's own H1, which is stamped in that same server frame.

Per closed trade, verified against the frozen rules:
  A. session       — signal-bar open hour (open_ct - 900) in UTC, inside the arm's
                     session gate (default 12-16 UTC per Amendment 4/5),
                     Friday entries before the cutoff hour.
  B. stop geometry — recorded stop distance equals 2.0 x bounded SMA-ATR
                     (H1,14) of the data of record at the signal (2% feed
                     tolerance; UNVERIFIABLE beyond the data's last bar —
                     refresh the data of record to extend verification).
                     The data of record is the VENUE's own series
                     (`XAUUSD_H1_upcomers.csv`). The 50,000-bar research series
                     this check used to read was retired on 2026-09-21 into a
                     hash-pinned archive, because having two series both
                     answer to "the gold bars" cost a day of misdiagnosis:
                     see docs/FROZEN_CORPUS_20260921.md.
  C. R math        — (exit-entry)*side/stop vs the recorded R (0.01 tol),
                     plus reason sanity (TP >= +1.9, SL <= -0.95).
  D. veq continuity— CLOSE veq == previous veq + pnl (0.01); heartbeat EQ
                     rows must agree with the running virtual equity.
  E. format        — OPEN12/CLOSE8 wire contract, ticket pairing, ERA row, and the
                     v1.19e STATE TAIL (5 appended fields: sig_ct, hour_utc,
                     vol_ratio, news, off_min) read but never required — a row
                     written before the stamp existed carries none, and a tester row
                     never will, while a HALF-WRITTEN tail is reported.

Exit codes: 0 compliant (or nothing closed yet), 1 violations, 2 unreadable.
Stdlib + the engine's own loaders only.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "scripts")
import midas_sweep as S          # sma_atr + load_bars + the pinned era table

#: The venue's own series is the data of record, and it is SUFFIXED to say so: this program
#: traded a different gold series until 2026-09-21 and both files were named XAUUSD_H1.csv.
VENUE_SUFFIX = "_upcomers"


def utc_of_server(epoch: int) -> datetime | None:
    """A broker-SERVER epoch as UTC, through the pinned era table — or None when the month
    contains a DST step and no single offset converts it.

    The ledger is stamped with `TimeCurrent()` (broker server time); the session gate is a UTC
    policy. Grading one against the other without this conversion is off by the whole offset —
    a +120 venue turns a 12-16 UTC session into a 14-18 one, and the violation list fills with
    correct trades. `None` must be disclosed, not defaulted.
    """
    month = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m")
    off = S.server_offset_for_month(month)
    if off is None:
        return None
    return datetime.fromtimestamp(epoch - off * 60, tz=timezone.utc)

TOL_R = 0.01
TOL_VEQ = 0.01
TOL_STOP_PCT = 0.02              # live feed vs data-of-record tolerance
#: The arm's session is a property of its PRESET, not of this audit. This file used to carry
#: `DEFAULT_SESSION = (12, 16)` -- Amendment 4/5 of the RETIRED micro arm -- as a flag default, so
#: running the audit with no arguments against the $25,000 arm flagged every entry before 12:00 UTC
#: as a session violation. Default to the preset the arm is deployed under; `--session` overrides,
#: and a preset that cannot be read leaves the check UNVERIFIABLE rather than graded against a rule
#: the arm does not run.
ARM_PRESET = os.path.join("mql5", "MIDASTOUCH", "MidastouchAI_upcomers_gold_LIVE.set")
FRIDAY_CUTOFF = 20               # protocol (entries)
#: Kept only so a caller that explicitly wants the retired Amendment's gate can still name it.
DEFAULT_SESSION = (12, 16)
WIRE_OPEN_N, WIRE_CLOSE_N = 12, 8
#: The frozen 12-field head + the v1.13 appends (atr_at_entry, spread_at_open): where the
#: v1.19e state tail starts on an OPEN row. Appended, never inserted, so this is an index.
WIRE_OPEN_TELEM_N = 14
#: The EA's state stamp (`StateAppend()` in MidastouchAI.mq5), in order. This module is the
#: wire-contract owner, so the list lives here and the research side imports it rather than
#: re-typing it — `gold_persistence_state.STATE_FIELDS` is this tuple.
STATE_FIELDS = ("sig_ct", "hour_utc", "vol_ratio", "news", "off_min")
STATE_N = len(STATE_FIELDS)


def read_state_tail(fields: list[str]) -> dict:
    """The EA's own state stamp from an OPEN row, or {} when the row carries none.

    ABSENCE IS NOT A DEFECT. Every row written before v1.19e has no tail, and a strategy-tester
    row never will (the stamp is deliberately off there so parity ledgers stay byte-identical),
    so a reader must treat "no tail" as "the label has to be rebuilt from the data of record".

    A HALF-WRITTEN TAIL IS A DEFECT, and it is reported by the caller rather than half-read here:
    a row carrying some of the five fields is a partial write, and silently labelling it would put
    a guessed axis into a statistic.

    The sentinels travel as they are. `news == "na"` means the EA could not assert the news axis
    and `hour_utc == -1` means no server offset could be vouched for; a consumer that needs either
    axis must REFUSE on those values rather than default them, because `na` is not `out`.
    """
    tail = fields[WIRE_OPEN_TELEM_N:]
    if not tail:
        return {}
    if len(tail) < STATE_N:
        return {"malformed": f"{len(tail)} state field(s), expected {STATE_N}"}
    try:
        return {"sig_ct": int(tail[0]), "hour_utc": int(tail[1]),
                "vol_ratio": float(tail[2]), "news": tail[3].strip(), "off_min": int(tail[4])}
    except (TypeError, ValueError) as exc:
        return {"malformed": f"unreadable state field ({exc})"}


def session_from_preset(path: str) -> tuple[int, int] | None:
    """The session gate the preset actually declares, or None when it cannot be read.

    Reading it from the preset is what keeps this audit grading the arm that is RUNNING: the literal
    it replaces came from a different arm's amendment, and a stale rule inside the checker is how a
    correct trade gets reported as a violation.
    """
    try:
        import set_chart_preset as scp
        vals = scp.parse_preset(path)
        return (int(vals["InpSessionStartHour"]), int(vals["InpSessionEndHour"]))
    except Exception:
        return None


def discover_ledger() -> str | None:
    """The live gold paper ledger: newest MIDASTOUCH_paper_*_M1.csv across
    terminal data folders (same discovery philosophy as morning_status)."""
    root = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
    hits: list[tuple[float, str]] = []
    for p in glob.glob(os.path.join(root, "*", "MQL5", "Files",
                                    "MIDASTOUCH_paper_*_M1.csv")):
        hits.append((os.path.getmtime(p), p))
    return max(hits)[1] if hits else None


def read_ledger(path: str) -> dict:
    """Row-walk the ledger once: ERA notes, OPEN/CLOSE pairs, EQ checks."""
    trades: list[dict] = []
    eras: list[str] = []
    problems: list[str] = []
    open_rows: dict[str, dict] = {}
    veq: float | None = None      # the running virtual equity, as the FILE states it
    veq_initialized = False
    opening_eq: float | None = None   # the first EQ row seen BEFORE any close: the start
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for ln, line in enumerate(fh, 1):
                p = line.strip().split(",")
                if not p or p[0] == "":
                    continue
                if p[0] == "ERA":
                    eras.append(line.strip())
                    if len(p) < 4:
                        problems.append(f"line {ln}: malformed ERA row")
                    continue
                if p[0] == "EQ" and len(p) >= 2:
                    v = float(p[1])
                    if veq_initialized and veq is not None and abs(v - veq) > TOL_VEQ:
                        problems.append(
                            f"line {ln}: EQ snapshot {v:.2f} != running veq {veq:.2f}")
                    if not trades and opening_eq is None:
                        opening_eq = v          # an EQ row before any close IS the opening equity
                    veq = v
                    veq_initialized = True
                    continue
                if p[0] == "OPEN":
                    if len(p) < WIRE_OPEN_N:
                        problems.append(f"line {ln}: OPEN row has {len(p)} fields (<{WIRE_OPEN_N})")
                        continue
                    open_rows[p[2]] = {
                        "line": ln, "open_ct": int(p[1]), "ticket": p[2],
                        "side": int(p[3]), "entry": float(p[4]), "sl": float(p[5]),
                        "tp": float(p[6]), "vol": float(p[7]), "risk": float(p[8]),
                        "stop_d": float(p[9]), "hold": int(p[10]), "tag": p[11],
                        "state": read_state_tail(p),
                    }
                    if "malformed" in open_rows[p[2]]["state"]:
                        problems.append(f"line {ln}: state stamp {open_rows[p[2]]['state']['malformed']}")
                elif p[0] == "CLOSE":
                    if len(p) < WIRE_CLOSE_N:
                        problems.append(f"line {ln}: CLOSE row has {len(p)} fields (<{WIRE_CLOSE_N})")
                        continue
                    o = open_rows.pop(p[2], None)
                    if o is None:
                        problems.append(f"line {ln}: CLOSE without matching OPEN (ticket {p[2]})")
                        continue
                    o.update({"close_ct": int(p[1]), "reason": p[3],
                              "exit": float(p[4]), "r": float(p[5]),
                              "pnl": float(p[6]), "close_veq": float(p[7]),
                              "close_line": ln})
                    # The equity path ADVANCES at a close. Without this line `veq` stayed at the
                    # pre-close snapshot, so every post-close heartbeat was compared against it and
                    # a correct ledger reported one bogus "EQ snapshot != running veq" per trade --
                    # noise printed exactly where an operator reads for real defects.
                    veq = float(p[7])
                    veq_initialized = True
                    trades.append(o)
                elif p[0] in ("LOPEN", "LCLOSE"):
                    problems.append(
                        f"line {ln}: {p[0]} row in the PAPER mirror ledger — "
                        "live-order contamination of the paper book")
    except OSError as e:
        raise SystemExit(f"cannot read ledger {path}: {e}")
    if open_rows:
        problems.append(f"{len(open_rows)} OPEN row(s) without CLOSE (open position(s), not a violation — listed)")
    return {"trades": trades, "eras": eras, "problems": problems, "veq_end": veq,
            "veq_start": _equity_start(trades, veq, opening_eq)}


def _equity_start(trades: list[dict], veq_end: float | None,
                  opening_eq: float | None = None) -> float | None:
    """The equity the ledger STARTED from, for the per-trade continuity chain.

    This used to be the literal 50.0 — the retired micro arm's virtual start — while the $25,000
    arm's ledger says `EQ,25000.00`. The result was a VIOLATION on trade #1 of a perfect ledger
    ("close veq 25020.00 != prev 50.00 + pnl +20.00"), which is precisely the first fill this
    audit exists to grade. Take the start from the file: its first EQ snapshot, else (when the
    ledger carries no EQ row at all) the first trade's own implied previous equity, and never a
    constant belonging to an arm this ledger does not belong to.
    """
    if opening_eq is not None:
        return opening_eq
    if not trades:
        return veq_end
    first = trades[0]
    return round(first["close_veq"] - first["pnl"], 2)


def expected_stop(stop_mult: float, h1: list[dict], h1_atr: list[float],
                  open_ct: int) -> tuple[float | None, str]:
    """2.0 x bounded SMA-ATR at the last H1 bar closing <= open_ct (= sig_ct).
    Mirrors the engine's k1 selection exactly."""
    lo, hi, ans = 0, len(h1) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if h1[mid]["time"] + 3600 <= open_ct:
            ans = mid; lo = mid + 1
        else:
            hi = mid - 1
    if ans < 0:
        return None, "no H1 bar closes at/before the signal"
    # freshness guard: an ATR from bars far behind the signal would judge the
    # EA's live ATR with stale data — false violations. Disclose instead.
    age_h = (open_ct - (h1[ans]["time"] + 3600)) / 3600.0
    if age_h > 24.0:
        return None, f"data of record ends {age_h:.0f}h before the signal — refresh it to verify"
    return stop_mult * h1_atr[ans], datetime.fromtimestamp(
        h1[ans]["time"], tz=timezone.utc).strftime("%m-%d %H:%M")


def audit_trade(t: dict, session: tuple[int, int] | None, stop_mult: float,
                h1: list[dict], h1_atr: list[float]) -> list[str]:
    """All checks for one closed trade; returns violation strings."""
    v: list[str] = []
    sig_ct = t["open_ct"] - 900                      # signal bar close time (SERVER frame:
    sig_bar_open = sig_ct - 900                      # the EA writes TimeCurrent())
    dt = utc_of_server(sig_bar_open)
    # A. session + Friday cutoff (entries), in UTC — the policy's frame, not the ledger's
    if dt is None:
        month = datetime.fromtimestamp(sig_bar_open, tz=timezone.utc).strftime("%Y-%m")
        t["frame_note"] = (f"session check UNVERIFIABLE: {month} contains a DST step, so the "
                           f"venue's offset is not a single number for it")
    else:
        if session is None:
            t["frame_note"] = ("session check UNVERIFIABLE: no session gate resolved — pass "
                               "--session, or make the arm's preset readable")
        elif not (session[0] <= dt.hour < session[1]):
            v.append(f"SESSION: signal bar opens {dt:%H:%M} UTC outside {session[0]:02d}-{session[1]:02d}")
        if dt.weekday() == 4 and dt.hour >= FRIDAY_CUTOFF:
            v.append(f"FRIDAY CUTOFF: signal at {dt:%H:%M} UTC Friday >= {FRIDAY_CUTOFF}:00")
    # B. stop geometry vs the data of record
    exp, h1_note = expected_stop(stop_mult, h1, h1_atr, t["open_ct"])
    if exp is None:
        t["stop_note"] = f"UNVERIFIABLE ({h1_note})"
    else:
        d = abs(t["stop_d"] - exp) / exp
        t["stop_note"] = f"EA {t['stop_d']:.4f} vs research {exp:.4f} (d {d*100:.2f}%)"
        if d > TOL_STOP_PCT:
            v.append(f"STOP GEOMETRY: stop {t['stop_d']:.4f} != 2xATR {exp:.4f} ({d*100:.1f}% off)")
    # C. R math + reason sanity (pure consistency of the row's own fields)
    if t["stop_d"] > 0:
        r_calc = (t["exit"] - t["entry"]) * t["side"] / t["stop_d"]
        if abs(r_calc - t["r"]) > TOL_R:
            v.append(f"R MATH: recorded {t['r']:+.4f} vs fields-implied {r_calc:+.4f}")
    if t["reason"] == "TP" and t["r"] < 1.9:
        v.append(f"REASON: TP but R {t['r']:+.3f} < +1.9")
    if t["reason"] == "SL" and t["r"] > -0.95:
        v.append(f"REASON: SL but R {t['r']:+.3f} > -0.95")
    if t["reason"] == "TIMEOUT" and not (-1.0 - 1e-9 <= t["r"] <= 2.0 + 1e-9):
        v.append(f"REASON: TIMEOUT but R {t['r']:+.3f} outside [-1, +2]")
    # D. veq continuity
    if abs((t["prev_veq"] + t["pnl"]) - t["close_veq"]) > TOL_VEQ:
        v.append(f"VEQ: close veq {t['close_veq']:.2f} != prev {t['prev_veq']:.2f} + pnl {t['pnl']:+.2f}")
    return v


def run(ledger: str, session: tuple[int, int] | None, stop_mult: float,
        data_dir: str, as_json: bool) -> int:
    led = read_ledger(ledger)
    # The VENUE's own H1 — the data of record, and the same SERVER frame the ledger is stamped
    # in, so the geometry comparison needs no conversion on either side. Refused-name explicit:
    # this used to look for `XAUUSD_H1.csv`, which is the RETIRED research series and no longer
    # exists, so the check silently reported every stop UNVERIFIABLE instead of failing.
    h1_path = os.path.join(data_dir, f"XAUUSD_H1{VENUE_SUFFIX}.csv")
    h1 = S.load_bars(h1_path) if os.path.exists(h1_path) else []
    h1_atr = S.sma_atr(h1) if h1 else []
    # veq continuity needs the running equity in trade order — ledger CLOSE
    # order is chronological by construction (append-only file)
    prev = led["veq_start"]
    for t in led["trades"]:
        t["prev_veq"] = prev
        prev = t["close_veq"]

    rows = []
    for i, t in enumerate(led["trades"], 1):
        vs = audit_trade(t, session, stop_mult, h1, h1_atr)
        rows.append((i, t, vs))
    n_bad = sum(1 for _, _, vs in rows if vs)

    if as_json:
        print(json.dumps({
            "ledger": ledger,
            "eras": led["eras"],
            "closed": len(rows), "violations": n_bad,
            "veq_end": led["veq_end"],
            "problems": led["problems"],
            "trades": [
                {"i": i, "open_ct": t["open_ct"], "side": t["side"],
                 "reason": t["reason"], "r": t["r"], "pnl": t["pnl"],
                 "stop_note": t.get("stop_note", ""),
                 "frame_note": t.get("frame_note", ""), "violations": vs}
                for i, t, vs in rows],
        }, indent=1, default=str))
    else:
        print(f"first-fills audit — {os.path.basename(ledger)}")
        if led["eras"]:
            print(f"  era: {led['eras'][-1]} ({len(led['eras'])} era stamps on file)")
        if not rows:
            print("  0 closed trades — nothing to audit yet (gate clock 0/30); "
                  "acceptance rules are armed and pre-registered")
        for i, t, vs in rows:
            ts = datetime.fromtimestamp(t["open_ct"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"  #{i} {ts} side {t['side']:+d} {t['reason']:>6} R {t['r']:+.3f} "
                  f"pnl {t['pnl']:+.2f} | {t.get('stop_note','')}")
            if t.get("frame_note"):
                print(f"      note: {t['frame_note']}")
            for x in vs:
                print(f"      VIOLATION: {x}")
        for p in led["problems"]:
            print(f"  problem: {p}")
        if rows:
            print(f"  summary: {len(rows)} closed, {n_bad} with violations, "
                  f"veq {led['veq_end']:.2f}")
        if not h1:
            print(f"  note: the venue's own H1 not found at {h1_path} — stop checks "
                  f"UNVERIFIABLE (fetch it with scripts/midas_fetch_history.py --suffix _upcomers)")
    if led["problems"] and any("contamination" in p for p in led["problems"]):
        return 1
    return 1 if n_bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", default=None, help="ledger path (default: auto-discover)")
    ap.add_argument("--session", default=None,
                    help="UTC session as lo-hi (default: the gate the arm's preset declares; "
                         "UNVERIFIABLE if that cannot be read)")
    ap.add_argument("--preset", default=ARM_PRESET,
                    help="the preset whose session gate this ledger is graded against")
    ap.add_argument("--stop-mult", type=float, default=2.0)
    ap.add_argument("--data-dir", default=S.DATA_DIR)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    led = a.ledger or discover_ledger()
    if not led or not os.path.exists(led):
        print("no MIDASTOUCH paper ledger found")
        return 2
    if a.session:
        s = tuple(int(x) for x in a.session.split("-"))
    else:
        preset = a.preset if os.path.isabs(a.preset) else os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", a.preset)
        s = session_from_preset(preset)
        if s is None:
            print(f"  note: no session gate resolvable from {a.preset} — the session check is "
                  f"UNVERIFIABLE for this run (pass --session to grade one explicitly)")
        else:
            print(f"  session gate: {s[0]:02d}-{s[1]:02d} UTC, read from {a.preset}")
    return run(led, s, a.stop_mult, a.data_dir, a.json)


if __name__ == "__main__":
    sys.exit(main())
