#!/usr/bin/env python3
"""MIDASTOUCH first-fills audit — mechanical rule compliance for the live
paper ledger (protocol discipline: the acceptance rule is written BEFORE
the evidence it grades, so trade #1 is audited exactly like trade #150).

Per closed trade, verified against the frozen rules:
  A. session       — signal-bar open hour (open_ct - 900) inside the arm's
                     session gate (default 12-16 UTC per Amendment 4/5),
                     Friday entries before the cutoff hour.
  B. stop geometry — recorded stop distance equals 2.0 x bounded SMA-ATR
                     (H1,14) of the data of record at the signal (2% feed
                     tolerance; UNVERIFIABLE beyond the data's last bar —
                     refresh the data of record to extend verification).
  C. R math        — (exit-entry)*side/stop vs the recorded R (0.01 tol),
                     plus reason sanity (TP >= +1.9, SL <= -0.95).
  D. veq continuity— CLOSE veq == previous veq + pnl (0.01); heartbeat EQ
                     rows must agree with the running virtual equity.
  E. format        — OPEN12/CLOSE8 wire contract, ticket pairing, ERA row.

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
import midas_sweep as S          # sma_atr + load_bars: the research definitions

TOL_R = 0.01
TOL_VEQ = 0.01
TOL_STOP_PCT = 0.02              # live feed vs data-of-record tolerance
DEFAULT_SESSION = (12, 16)       # Amendment 4/5 arm policy
FRIDAY_CUTOFF = 20               # protocol (entries)
WIRE_OPEN_N, WIRE_CLOSE_N = 12, 8


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
    veq = 50.0                    # virtual start (playbook floor-zone policy)
    veq_initialized = False
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
                    if veq_initialized and abs(v - veq) > TOL_VEQ:
                        problems.append(
                            f"line {ln}: EQ snapshot {v:.2f} != running veq {veq:.2f}")
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
                    }
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
                    trades.append(o)
                elif p[0] in ("LOPEN", "LCLOSE"):
                    problems.append(
                        f"line {ln}: {p[0]} row in the PAPER mirror ledger — "
                        "live-order contamination of the paper book")
    except OSError as e:
        raise SystemExit(f"cannot read ledger {path}: {e}")
    if open_rows:
        problems.append(f"{len(open_rows)} OPEN row(s) without CLOSE (open position(s), not a violation — listed)")
    return {"trades": trades, "eras": eras, "problems": problems, "veq_end": veq}


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


def audit_trade(t: dict, session: tuple[int, int], stop_mult: float,
                h1: list[dict], h1_atr: list[float]) -> list[str]:
    """All checks for one closed trade; returns violation strings."""
    v: list[str] = []
    sig_ct = t["open_ct"] - 900                      # signal bar close time
    sig_bar_open = sig_ct - 900                      # signal bar OPEN (session key)
    dt = datetime.fromtimestamp(sig_bar_open, tz=timezone.utc)
    # A. session + Friday cutoff (entries)
    if not (session[0] <= dt.hour < session[1]):
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


def run(ledger: str, session: tuple[int, int], stop_mult: float,
        data_dir: str, as_json: bool) -> int:
    led = read_ledger(ledger)
    h1_path = os.path.join(data_dir, "XAUUSD_H1.csv")
    h1 = S.load_bars(h1_path) if os.path.exists(h1_path) else []
    h1_atr = S.sma_atr(h1) if h1 else []
    # veq continuity needs the running equity in trade order — ledger CLOSE
    # order is chronological by construction (append-only file)
    prev = 50.0
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
                 "stop_note": t.get("stop_note", ""), "violations": vs}
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
            for x in vs:
                print(f"      VIOLATION: {x}")
        for p in led["problems"]:
            print(f"  problem: {p}")
        if rows:
            print(f"  summary: {len(rows)} closed, {n_bad} with violations, "
                  f"veq {led['veq_end']:.2f}")
        if not h1:
            print(f"  note: data of record not found at {h1_path} — stop checks UNVERIFIABLE")
    if led["problems"] and any("contamination" in p for p in led["problems"]):
        return 1
    return 1 if n_bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", default=None, help="ledger path (default: auto-discover)")
    ap.add_argument("--session", default=f"{DEFAULT_SESSION[0]}-{DEFAULT_SESSION[1]}")
    ap.add_argument("--stop-mult", type=float, default=2.0)
    ap.add_argument("--data-dir", default=S.DATA_DIR)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    led = a.ledger or discover_ledger()
    if not led or not os.path.exists(led):
        print("no MIDASTOUCH paper ledger found")
        return 2
    s = tuple(int(x) for x in a.session.split("-"))
    return run(led, s, a.stop_mult, a.data_dir, a.json)


if __name__ == "__main__":
    sys.exit(main())
