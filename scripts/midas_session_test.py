#!/usr/bin/env python3
"""MIDASTOUCH Amendment 4 — pre-registered London/NY-overlap session test (H3).

Protocol order of operations (docs/MIDASTOUCH_PROTOCOL.md §12):
  1. INTEGRITY PRECONDITION — the engine at the default frozen session
     (06-20) must reproduce the artifact of record
     (artifacts/midas_sweep_20260917.json) exactly, per mode per window.
     Any mismatch VOIDS the test: this script exits BEFORE computing any
     overlap number.
  2. ONE-SHOT OVERLAP RE-SIMULATION — all 8 modes x all 4 frozen windows
     with signal hours restricted to [12, 16) UTC. No other change.
  3. SCORING — the FROZEN gates() function, imported unmodified from
     midas_sweep, plus the §12.3 dual money measure (OOS net_pnl > 0)
     appended on G2. Strictly stricter than the frozen scorer alone.
  4. G6 SHIFT TABLE — per-window net signs, overlap vs full session.
  5. §12.6 CROSS-CHECK (descriptive only, cannot flip the verdict) —
     the full-session trade rows split by entry hour: overlap vs rest.

Writes artifacts/midas_sweep_session_<date>.json. One shot: re-running
after reading results is a protocol violation, not an analysis option.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import midas_sweep as S  # frozen engine + frozen gates()

BASELINE = os.path.join(S.ART, "midas_sweep_20260917.json")
SES_DEFAULT = (6, 20)
SES_OVERLAP = (12, 16)
METRIC_KEYS = ("n", "net_r", "pf", "net_pnl", "expectancy_r", "max_dd_r")


def dual_gates(oos: dict, window_nets: dict) -> tuple[bool, list[str]]:
    """Frozen gates() verbatim, plus the §12.3 money-implied G2 measure."""
    ok, why = S.gates(oos, window_nets)
    if oos.get("n", 0) and not (oos.get("net_pnl", 0) > 0):
        ok = False
        why.append("G2b OOS net_pnl not positive (money-implied)")
    return ok, why


def run_all(data: dict, ses: tuple[int, int]) -> tuple[dict, dict, dict]:
    """All modes x windows at one session setting. Returns (metrics, trades, window_nets)."""
    metrics, trades, wnets = {}, {}, {}
    for mode in S.MODES:
        metrics[mode], trades[mode], wnets[mode] = {}, {}, {}
        for w, (a, b) in S.WINDOWS.items():
            rr = S.run_mode(mode, S.iso_to_ts(a), S.iso_to_ts(b), data, *ses)
            m = S.metrics(rr.trades)
            m["floored_lots"] = rr.floored
            m["final_equity"] = round(rr.final_equity, 2)
            metrics[mode][w] = m
            trades[mode][w] = rr.trades
            wnets[mode][w] = m.get("net_r", 0)
    return metrics, trades, wnets


def main() -> int:
    data = S.build_data()
    baseline = json.load(open(BASELINE))
    base = baseline["results"]["modes"]

    # ── 1) integrity precondition (void before any overlap number) ─────────
    print("== integrity precondition: engine @ 06-20 vs artifact of record ==")
    def_metrics, def_trades, def_nets = run_all(data, SES_DEFAULT)
    integrity_ok = True
    for mode in S.MODES:
        for w in S.WINDOWS:
            ref, got = base[mode][w], def_metrics[mode][w]
            diffs = [f"{k}: {ref.get(k)} vs {got.get(k)}"
                     for k in METRIC_KEYS if ref.get(k) != got.get(k)]
            if diffs:
                integrity_ok = False
                print(f"  MISMATCH {mode}/{w}: " + "; ".join(diffs))
    print("  integrity:", "PASS" if integrity_ok else "FAIL")
    if not integrity_ok:
        print("VOID per §12.3 — no overlap number may be read until this is explained.")
        return 2

    # ── 2) the one-shot overlap re-simulation ──────────────────────────────
    print(f"== one-shot overlap re-simulation (signal hours [{SES_OVERLAP[0]:02d},"
          f"{SES_OVERLAP[1]:02d}) UTC) ==")
    ovl_metrics, ovl_trades, ovl_nets = run_all(data, SES_OVERLAP)

    verdicts, g6_shift = {}, {}
    for mode in S.MODES:
        ok, why = dual_gates(ovl_metrics[mode]["oos"], ovl_nets[mode])
        verdicts[mode] = {"verdict": "EDGE" if ok else "NO-SHIP", "reasons": why}
        pos_o = sum(1 for v in ovl_nets[mode].values() if v > 0)
        pos_d = sum(1 for v in def_nets[mode].values() if v > 0)
        g6_shift[mode] = {"overlap_positive_windows": pos_o,
                          "full_session_positive_windows": pos_d}
        o = ovl_metrics[mode]["oos"]
        print(f"{mode:<20} OOS n={o.get('n', 0):>3} netR={o.get('net_r', 0):>7.2f} "
              f"pf={o.get('pf')} exp={o.get('expectancy_r')} ddR={o.get('max_dd_r')} "
              f"G6 {pos_o}/4 (full-session {pos_d}/4) -> {verdicts[mode]['verdict']}")

    # ── 3) §12.6 cross-check: frozen full-session trades split by hour ────
    print("== cross-check (descriptive only): full-session trades, overlap vs rest ==")
    cross = {}
    for mode in S.MODES:
        cross[mode] = {}
        for w in S.WINDOWS:
            rows = def_trades[mode][w]
            ovl = [t for t in rows if SES_OVERLAP[0] <= t["hour"] < SES_OVERLAP[1]]
            rst = [t for t in rows if not (SES_OVERLAP[0] <= t["hour"] < SES_OVERLAP[1])]
            cross[mode][w] = {
                "overlap": {"n": len(ovl),
                            "net_r": round(sum(t["r"] for t in ovl), 3),
                            "expectancy_r": round(sum(t["r"] for t in ovl) / len(ovl), 4) if ovl else None},
                "rest": {"n": len(rst),
                         "net_r": round(sum(t["r"] for t in rst), 3),
                         "expectancy_r": round(sum(t["r"] for t in rst) / len(rst), 4) if rst else None}}

    out = os.path.join(S.ART, f"midas_sweep_session_{datetime.now():%Y%m%d}.json")
    with open(out, "w") as fh:
        json.dump({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "amendment": 4, "session_utc": list(SES_OVERLAP),
                   "baseline_artifact": os.path.basename(BASELINE),
                   "integrity": "PASS" if integrity_ok else "FAIL",
                   "results": ovl_metrics, "trades_overlap": ovl_trades,
                   "verdicts": verdicts, "g6_shift": g6_shift,
                   "cross_check_full_session_by_hour": cross}, fh, indent=1)
    print("artifact:", out)
    passed = [m for m, v in verdicts.items() if v["verdict"] == "EDGE"]
    print("AMENDMENT 4 VERDICT:", f"{len(passed)} mode(s) pass the frozen gates" if passed
          else "NO mode passes the frozen gates — H3 falsified-for-promotion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
