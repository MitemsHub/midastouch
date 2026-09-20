#!/usr/bin/env python3
"""MIDASTOUCH Step 5 — build parity (protocol §8), v2 (keyed).

History: the original harness (run3, 2026-09-16) reported EA 150 vs python 147
and aligned trades positionally, which quantized SL/TP/timeout outcomes against
the WRONG partner trade after the first misalignment. Root-caused 2026-09-17:
both sides were stale vintages, not a live EA defect —
  * the frozen python artifact (midas_parity_python_wf_rd.json) reproduces only
    under the PRE-amendment-2 Wilder ATR (verified 2026-09-17: exact 147-trade
    match with M.wilder_atr); the engine of record now uses bounded SMA ATR
    (protocol amendment 2) and yields 151 trades / +1.47R on WF;
  * the harness predated the v1.04+ BAR-parity engine: it omitted InpBarModel
    and the InpWindowStart/End pins and pointed at the old install path.

v2 therefore:
  1. regenerates python R from the engine of record (scripts/midas_sweep.py
     run_mode, REVERSE_DIRECTION, WF window) — no frozen artifact dependency;
  2. pins the full BAR-parity contract on the tester pass (InpBarModel=true,
     InpWindowStart/End = python t0/t1, recorded spread file via tester_file);
  3. aligns trades by KEY (open_ct, close_ct, direction) — positional zip is
     banned; EA evidence comes from the agent sandbox ledger (OPEN/CLOSE join)
     with the appended journal "Trade R:" lines as a degraded fallback;
  4. rotates stale sandbox ledgers before the pass and pauses the paper arm's
     watchdog (scripts/.midas_watchdog_paused) so a tester session never fights
     the arm's auto-recovery; the terminal is always relaunched afterwards.

Tolerance (protocol §8, house standard): equal trade count AND max |dR| <=
0.01R per trade. Key agreement on open/close times and direction is itself
part of the verdict — a pure R match on mistimed trades is a fail.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, "tests")

import v75_tester_runner as T                       # noqa: E402
import mt5_ops as R                                 # noqa: E402  (terminal ops;
# was v28_sweep_runner, the closed indices sweep runner, kept alive only for these
# four primitives — they now resolve the LIVE install by account identity)
import midas_sweep as M                             # noqa: E402

# --- point the house runner at the default install (49E0 data folder) -------
T.TERMINAL_EXE = Path(R.terminal_exe())
T._BASE_TESTER_INI["Symbol"] = "XAUUSD"
T._BASE_TESTER_INI["Period"] = "M15"
T._BASE_TESTER_INI["Leverage"] = "1000"
T._BASE_TESTER_INI["Deposit"] = "1000"

# R6 preconditions, mirrored python-side (one commit with the EA's
# INIT_FAILED guards): the engine of record runs gold-only and treats the
# news-filter input as the no-protection value it honestly is. The harness
# declares what it feeds; python_build_data refuses if the declaration and
# the feed ever disagree.
R6_GOLD_ONLY = True
R6_NEWS_FILTER_OFF = True

EXPERT = r"MITEMSHUB_AI\MidastouchAI"  # v1.09 deploy layout (49E0 tester keeps
                                       # the gold EA under the legacy folder;
                                       # "MIDASTOUCH\\..." fails as ex5-not-found)

# The shadow certification path — the one at which un-deployed builds are
# certified (V2-register §2 baseline). It MUST stay distinct from EXPERT: the
# live gold charts load EXPERT, and a re-cert launched at the live path would
# swap the binary under the running §13 arms at relaunch (the 2026-09-17
# load-path hazard). Pinned distinct by tests/test_midas_parity_paths.py.
SHADOW_EXPERT = r"MIDASTOUCH_parity\MidastouchAI"

# EA enum ENUM_MIDAS_MODE (MidastouchAI.mq5 §47): registry order is fixed.
MODE_CODE = {"ORIGINAL": "0", "REVERSE_DIRECTION": "1", "REVERSE_TRIGGER": "2",
             "REVERSE_BOTH": "3", "LONG_ONLY": "4", "SHORT_ONLY": "5",
             "MACRO_ONLY": "6", "TRIGGER_ONLY": "7"}

# Certified parity windows. Each spec carries its own tester tag (separate
# INI/report namespaces — no cross-window collisions) and tester calendar
# extending PAST the research window (ToDate 00:00 truncation lesson, §11).
# The OOS calendar ends 2026.09.18 so a final-window signal can fill at
# 09-17 00:00 and time-out 720 min later; ticks end naturally at data end
# and the EA's tail flush drops an un-closed tail position exactly like the
# python engine (both engines are bounded by the same bar series).
WINDOW_SPECS = {
    "wf":  {"tag": "midas_wf_rd",  "mode": "REVERSE_DIRECTION",
            "dates": ("2025.09.15", "2026.04.03")},
    "oos": {"tag": "midas_oos_rd", "mode": "REVERSE_DIRECTION",
            "dates": ("2026.04.01", "2026.09.18")},
}
DEFAULT_WINDOW = "wf"


def _window_spec(name: str) -> dict:
    """Resolve a window spec: tester tag/dates + the python window epochs."""
    if name not in WINDOW_SPECS:
        raise SystemExit(f"unknown window '{name}' (have: {', '.join(WINDOW_SPECS)})")
    spec = WINDOW_SPECS[name]
    a, b = M.WINDOWS[name]
    return {**spec, "window_name": name, "t0": M.iso_to_ts(a), "t1": M.iso_to_ts(b)}


def build_inputs(mode: str, t0: int, t1: int) -> dict:
    """The BAR-parity input contract, per window (mode + window pins vary)."""
    return {
        "InpMagic": "7801001",
        "InpArmTag": "M1",
        "InpMode": MODE_CODE[mode],
        "InpMacroEmaPeriod": "20",
        "InpBBPeriod": "20",
        "InpBBDev": "2.0",
        "InpRSIPeriod": "14",
        "InpRSIUpper": "70.0",
        "InpRSILower": "30.0",
        "InpAtrPeriod": "14",
        "InpSlAtrMult": "2.0",
        "InpTpMult": "2.0",
        "InpTimeoutMinutes": "720",
        "InpSessionStartHour": "6",
        "InpSessionEndHour": "20",
        "InpSpreadCapPctStop": "1.5",
        "InpFridayCutoffHour": "20",
        "InpUseNewsFilter": "false",
        "InpStaleMinutes": "30",
        "InpRiskPercent": "1.0",
        "InpLiveExecution": "false",
        "InpPaperEquity": "5000.0",      # = python START_EQUITY: identical sizing path
        # --- v1.04+ BAR-parity contract (the run3 harness predates these) -------
        "InpBarModel": "true",           # bar replay, recorded spreads — python's model
        "InpSpreadFile": "MIDASTOUCH_spread_M15.csv",  # bundled via tester_file
        "InpWindowStart": str(t0),       # EA fail-closed without these: window pins
        "InpWindowEnd": str(t1),
    }


# WF defaults at module level (the certified 2026-09-17 certificate window);
# other windows resolve through _window_spec() at run time.
_WF = _window_spec(DEFAULT_WINDOW)
TAG = _WF["tag"]
MODE = _WF["mode"]
T0, T1 = _WF["t0"], _WF["t1"]
DATES = _WF["dates"]
INPUTS = build_inputs(MODE, T0, T1)

TRADE_R_RE = re.compile(r"Trade R: ([+-]?\d+\.\d+)")
TOLERANCE = 0.01
GOLD_LEDGER = "MIDASTOUCH_paper_XAUUSD_M1.csv"   # the live paper arm's book


# --- EA evidence ------------------------------------------------------------

def agent_files_dirs() -> list[Path]:
    out: list[Path] = []
    for root in T._tester_roots():
        out += sorted(Path(root).glob("Agent-*/MQL5/Files"))
    return out


def rotate_sandbox_ledgers() -> list[str]:
    """One-deep rotation of any stale sandbox ledger in every agent Files dir.

    The sandbox persists across passes (a dangling OPEN would be adopted by the
    EA's own restore rule and poison the next run), so each certified pass
    starts from a clean ledger. Returns the rotated paths.
    """
    rotated = []
    for d in agent_files_dirs():
        p = d / "MIDASTOUCH_paper_XAUUSD_M1.csv"
        if p.exists():
            bak = p.with_suffix(".csv.prev")
            os.replace(p, bak)
            rotated.append(str(p))
    return rotated


def parse_ledger(path: Path) -> list[dict]:
    """OPEN/CLOSE join, keyed by ticket → open_ct/close_ct/side/reason/r."""
    opens: dict[str, dict] = {}
    trades: list[dict] = []
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            if row[0] == "OPEN" and len(row) >= 12:
                opens[row[2]] = {"open_ct": int(row[1]), "side": int(row[3])}
            elif row[0] == "CLOSE" and len(row) >= 7:
                o = opens.get(row[2], {})
                trades.append({"open_ct": o.get("open_ct"), "close_ct": int(row[1]),
                               "side": o.get("side"), "reason": row[3],
                               "r": float(row[5])})
    return trades


def journal_trade_rs(snaps: dict) -> list[float]:
    """All 'Trade R:' values in the appended journal bytes, in order."""
    out: list[float] = []
    for log in T.journal_paths():
        offset = snaps.get(log, 0)
        try:
            blob = log.read_bytes()[offset:].decode("utf-16-le", "ignore")
        except OSError:
            continue
        out += [float(m) for m in TRADE_R_RE.findall(blob)]
    return out


def collect_ea_evidence(snaps: dict) -> tuple[list[dict], str]:
    """Ledger first (keyed), journal 'Trade R:' lines as degraded fallback."""
    fresh = []
    for d in agent_files_dirs():
        p = d / "MIDASTOUCH_paper_XAUUSD_M1.csv"
        if p.exists():
            try:
                trades = parse_ledger(p)
            except OSError:
                continue
            if trades:
                fresh.append((p, trades))
    if fresh:
        # newest written ledger wins (agents may rotate ports)
        p, trades = max(fresh, key=lambda pt: pt[0].stat().st_mtime)
        return trades, f"ledger:{p.name}"
    rs = journal_trade_rs(snaps)
    return [{"open_ct": None, "close_ct": None, "side": None,
             "reason": "?", "r": r} for r in rs], "journal:TradeR"


# --- python engine of record ------------------------------------------------

def python_build_data() -> dict:
    """Indicator build shared by every mode's regen (done once per session).

    v1.16 R6 mirror (one-commit law with the EA): the python engine of
    record runs the SAME two fail-closed preconditions the EA enforces at
    init — news-filter input must be the no-protection value (false) and
    the symbol must be gold. The harness feeds exactly that (XAUUSD,
    InpUseNewsFilter=false), so a violation here is a harness bug and must
    refuse loudly instead of certifying an un-labeled configuration.
    """
    assert R6_NEWS_FILTER_OFF, "R6: news filter must be the no-protection value"
    assert R6_GOLD_ONLY, "R6: engine of record is gold-only by charter"
    assert T._BASE_TESTER_INI.get("Symbol", "").upper().startswith("XAU"), \
        "R6: harness must feed a gold symbol"
    assert inputs_declares_news_off()
    h1 = M.load_bars(os.path.join(M.DATA_DIR, "XAUUSD_H1.csv"))
    m15 = M.load_bars(os.path.join(M.DATA_DIR, "XAUUSD_M15.csv"))
    h4 = M.h4_series(h1)
    mc = [b["close"] for b in m15]
    return {
        "h1": h1, "m15": m15, "h4": h4,
        "h1_ct": [b["time"] + 3600 for b in h1],
        "h4_ct": [b["time"] + 14400 for b in h4],
        "h1_ema": M.ema([b["close"] for b in h1], 20),
        "h1_atr": M.sma_atr(h1),          # amendment 2: bounded ATR
        "h4_ema": M.ema([b["close"] for b in h4], 20),
        "m15_close": mc,
        "m15_rsi": M.rsi_wilder(mc),
        "m15_bb": [M.bb_touch(mc, i) for i in range(len(m15))],
    }


def python_regen(mode: str, t0: int, t1: int,
                 data: dict | None = None) -> list[dict]:
    """Run scripts/midas_sweep.py run_mode on the requested window (SMA ATR)."""
    data = data or python_build_data()
    rr = M.run_mode(mode, t0, t1, data)
    return [{"open_ct": t["open_ct"], "close_ct": t["close_ct"], "side": t["side"],
             "reason": t["reason"], "r": t["r"]} for t in rr.trades]


# Short mode codes for per-run tester tags (INI/report namespaces).
TAG_MODE_CODE = {"ORIGINAL": "orig", "REVERSE_DIRECTION": "rd",
                 "REVERSE_TRIGGER": "rt", "REVERSE_BOTH": "rb",
                 "LONG_ONLY": "lo", "SHORT_ONLY": "so",
                 "MACRO_ONLY": "mo", "TRIGGER_ONLY": "to"}

SWEEP_ANCHOR = os.path.join("artifacts", "midas_sweep_20260917.json")


def sweep_anchor(mode: str, window: str) -> dict | None:
    """The frozen sweep's (n, net_r) for this mode/window, for cross-checking
    the regen against the engine of record's certified run. None if absent."""
    try:
        with open(SWEEP_ANCHOR) as fh:
            m = json.load(fh)["results"]["modes"][mode][window]
        return {"n": m.get("n"), "net_r": m.get("net_r")}
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def matrix_verdict(records: list[dict]) -> tuple[str, list[str]]:
    """Matrix PASS requires every mode PASS and every sweep anchor reproduced."""
    fails = [r["mode"] for r in records if r["cmp"]["verdict"] != "PASS"]
    anchors = [r["mode"] for r in records if not r["anchor_match"]]
    verdict = "PASS" if not (fails or anchors) else "FAIL"
    return verdict, fails + anchors


# --- keyed comparison (pure; unit-tested) ------------------------------------

def keyed_compare(ea: list[dict], py: list[dict], tol: float = TOLERANCE) -> dict:
    """Align trades positionally ONLY after proving the keys agree 1:1.

    A positional zip is illegal evidence: after one misalignment every later
    |dR| is quantization noise against the wrong partner trade (run3's lesson).
    The verdict requires count equality AND key agreement AND max |dR| <= tol.
    """
    n = min(len(ea), len(py))
    pairs = list(zip(ea[:n], py[:n]))
    open_bad = [i for i, (a, b) in enumerate(pairs) if a["open_ct"] != b["open_ct"]]
    close_bad = [i for i, (a, b) in enumerate(pairs) if a["close_ct"] != b["close_ct"]]
    side_bad = [i for i, (a, b) in enumerate(pairs) if a["side"] != b["side"]]
    diffs = [abs(a["r"] - b["r"]) for a, b in pairs]
    max_d = max(diffs) if diffs else None
    over = [i for i, d in enumerate(diffs) if d > tol]
    keys_ok = not (open_bad or close_bad or side_bad)
    count_match = len(ea) == len(py)
    degraded = any(a["open_ct"] is None for a in ea[:n])
    verdict = ("PASS" if count_match and keys_ok and not degraded
               and max_d is not None and max_d <= tol else "FAIL")
    return {
        "count_match": count_match,
        "open_ct_mismatches": open_bad[:20],
        "close_ct_mismatches": close_bad[:20],
        "side_mismatches": side_bad[:20],
        "degraded_keyless_source": degraded,
        "max_abs_dR": max_d,
        "trades_over_tol": over[:20],
        "n_over_tol": len(over),
        "verdict": verdict,
    }


# --- main --------------------------------------------------------------------

def _should_relaunch_terminal(stopped: bool, ran_passes: bool) -> bool:
    """The finally-block relaunch guard (2026-09-17 latent-hazard fix).

    The harness relaunches the terminal after a session because a pass
    REQUIRES stopping it first. When the flat-check gate aborts BEFORE any
    stop (live arm holding a position — the §13-protecting gate doing its
    job), the terminal is still running and must be left alone: an
    unconditional relaunch would bounce a healthy terminal mid-window.
    """
    return stopped or ran_passes


def inputs_declares_news_off() -> bool:
    """The EA input block the harness builds must carry the R6 value."""
    return str(build_inputs("ORIGINAL", 0, 1)["InpUseNewsFilter"]).lower() == "false"


def run_one_mode(mode: str, spec: dict, window_name: str, data: dict,
                 expert: str = EXPERT) -> dict:
    """One certified tester pass + keyed comparison for a single mode.

    `expert` names the binary path under MQL5\\Experts the pass runs. The
    default is the DEPLOYED path (the certified v1.10 re-cert semantics);
    --expert-path overrides it for shadow-path certification of an
    un-deployed build (V2-register baseline) without ever touching the
    live charts' load path.

    V2 register §1 awareness: the comparison is version-agnostic BY LAW —
    keys (open/close ct, side) + per-trade |dR| tolerance, never an APP
    VERSION pin. A telemetry-only build (cited per §1, e.g. v1.13's R10
    columns) changes no trade and no R, so it passes identically; live-verified
    2026-09-18 when the v1.15 shadow certified PASS at max|dR| 0.0005. Pinned
    version-agnostic by tests/test_midas_parity.py
    (TestVersionAwareness).
    """
    t0, t1, dates = spec["t0"], spec["t1"], spec["dates"]
    tag = f"{spec['tag']}_{TAG_MODE_CODE[mode]}"
    inputs = build_inputs(mode, t0, t1)
    rotated = rotate_sandbox_ledgers()
    if rotated:
        print(f"  rotated stale sandbox ledgers: {rotated}")
    snaps = T.journal_snapshots()
    print(f"  pass tag={tag} mode={mode} (real ticks; be patient)", flush=True)
    res = T.run_pass(tag, inputs, timeout_s=3600, dates=dates, expert=expert)
    time.sleep(10)                   # agent flushes journal + ledger after report
    ea, source = collect_ea_evidence(snaps)
    py = python_regen(mode, t0, t1, data)
    cmp = keyed_compare(ea, py)
    anchor = sweep_anchor(mode, window_name)
    anchor_match = (anchor is not None and anchor["n"] == len(py)
                    and abs((anchor["net_r"] or 0) - sum(t["r"] for t in py)) < 5e-4)
    print("  " + "-" * 66)
    print(f"  {mode:<20} py {len(py):>3}tr {sum(t['r'] for t in py):+8.3f}R | "
          f"EA {len(ea):>3}tr {sum(t['r'] for t in ea):+8.3f}R | "
          f"max|dR| {cmp['max_abs_dR']:.5f} | keys "
          f"{'OK' if not (cmp['open_ct_mismatches'] or cmp['close_ct_mismatches'] or cmp['side_mismatches']) else 'MISMATCH'} | "
          f"anchor {'reproduced' if anchor_match else ('NO-ANCHOR' if anchor is None else 'MISMATCH')} | "
          f"{cmp['verdict']}")
    if cmp["verdict"] != "PASS":
        for i in cmp["trades_over_tol"][:10]:
            a, b = ea[i], py[i]
            print(f"    trade {i}: ea {a['r']:+.4f} (ct={a['close_ct']}) vs "
                  f"py {b['r']:+.4f} (ct={b['close_ct']}) dR {a['r'] - b['r']:+.4f}")
        for name in ("open_ct_mismatches", "close_ct_mismatches", "side_mismatches"):
            if cmp[name]:
                print(f"    {name}: {cmp[name]}")
    return {"mode": mode, "tag": tag, "evidence_source": source,
            "anchor": anchor, "anchor_match": anchor_match, "cmp": cmp,
            "python": {"n": len(py), "sum_r": round(sum(t["r"] for t in py), 4), "trades": py},
            "ea": {"n": len(ea), "sum_r": round(sum(t["r"] for t in ea), 4), "trades": ea}}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MIDAS keyed parity harness (protocol §11/§8)")
    ap.add_argument("--window", default=DEFAULT_WINDOW, choices=sorted(WINDOW_SPECS),
                    help="research window of record (default: wf)")
    ap.add_argument("--mode", action="append", dest="modes",
                    help="registry mode to certify (repeatable); default: the window spec's mode")
    ap.add_argument("--expert-path", default=EXPERT, dest="expert_path",
                    help="EA path under MQL5\\Experts for the tester pass "
                         "(default: the deployed binary — the certified target; "
                         "pass a shadow path to certify an un-deployed build)")
    args = ap.parse_args()
    expert = args.expert_path
    if expert != EXPERT:
        print(f"SHADOW-PATH certification: expert={expert} — the live charts' "
              f"load path ({EXPERT}) is NOT touched by this run")
    spec = _window_spec(args.window)
    modes = args.modes or [spec["mode"]]
    for m in modes:
        if m not in MODE_CODE:
            raise SystemExit(f"unknown mode '{m}' (registry: {', '.join(MODE_CODE)})")
    t0, t1, dates = spec["t0"], spec["t1"], spec["dates"]
    matrix_run = len(modes) > 1

    # the paper arm's watchdog must not restart the terminal mid-tester-pass
    marker = os.path.join(REPO_MARK_DIR(), ".midas_watchdog_paused")
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    paused_by_us = not os.path.exists(marker)
    if paused_by_us:
        open(marker, "w").write(datetime.now(timezone.utc).isoformat() + "\n")
        print("watchdog paused for the parity session")
    stopped = False       # did THIS session stop the terminal?
    ran_passes = False    # did THIS session run tester passes?

    try:
        # flat-check gate (v28_sweep_runner discipline): the paper arm's EA
        # adopts a dangling OPEN as a live virtual position, so a tester
        # session never stops its host with an open paper trade.
        # Every gold paper book on the terminal gates the stop. The inventory used to
        # also carry the V75 arms; that program is closed, so no book of its remains.
        data_folder = R.data_folder_for_terminal()
        arms = R.inventory_arms(data_folder)
        flat, bad = R.verify_all_flat(arms)
        gold = None
        if data_folder:
            gpath = os.path.join(data_folder, "MQL5", "Files", GOLD_LEDGER)
            if os.path.exists(gpath):
                gold = R.ledger_flatness(gpath)
                flat = flat and gold["flat"]
        else:
            flat = False
            bad.append({"name": "terminal-data-folder", "problem": "unresolvable — gold ledger unverifiable"})
        if gold is not None:
            print(f"gold ledger flat-check: flat={gold['flat']} rows={gold['rows']} open={len(gold['open_positions'])}")
        if not flat:
            print("ABORT: paper ledger(s) not flat — refusing to stop the terminal:")
            for b in bad:
                print(" ", b)
            return 4
        print(f"flat-check OK ({len(arms)} gold arm book(s) on the terminal; legacy "
              f"gold ledger {'checked' if gold else 'absent'})")

        pids = R.terminal_pids_exact()
        if pids:
            print(f"terminal running (pids {pids}) — stopping first")
            stopped = R.stop_terminal(pids)
            if not stopped:
                print("ABORT: terminal did not stop cleanly — refusing to run passes "
                      "against an unverified terminal state")
                return 4

        if M.selftest() != 0:
            print("python engine selftest FAILED — refusing to certify")
            return 3
        data = python_build_data()

        print(f"parity session: window={args.window} tester_dates={dates} "
              f"modes={','.join(modes)} expert={expert}")
        records = [run_one_mode(m, spec, args.window, data, expert=expert)
                   for m in modes]
        ran_passes = True

        if matrix_run:
            verdict, why = matrix_verdict(records)
            print("=" * 70)
            print(f"MATRIX ({args.window}, {len(modes)} modes): {verdict}")
            if why:
                print("  failing:", ", ".join(why))
            out = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "harness": "midas_parity.py v2 (keyed, matrix)",
                "expert": expert, "window": {"t0": t0, "t1": t1, "name": args.window},
                "tester_dates": dates, "symbol": "XAUUSD",
                "modes": records, "matrix_verdict": verdict,
                "matrix_failing": why,
            }
            path = f"artifacts/midas_parity_matrix_{args.window}_{datetime.now():%Y%m%d_%H%M}.json"
            with open(path, "w") as fh:
                json.dump(out, fh, indent=1)
            print("artifact:", path)
            rc = 0 if verdict == "PASS" else 1
        else:
            rec = records[0]
            cmp = rec["cmp"]
            print("=" * 70)
            print(f"python ({rec['mode']}, SMA-ATR era): {len(rec['python']['trades'])} trades "
                  f"sumR {rec['python']['sum_r']:+.3f}")
            print(f"EA BAR ledger ({rec['evidence_source']}): {len(rec['ea']['trades'])} trades "
                  f"sumR {rec['ea']['sum_r']:+.3f}")
            print(f"count match:        {cmp['count_match']}")
            print(f"open_ct agreement:  {not cmp['open_ct_mismatches']}")
            print(f"close_ct agreement: {not cmp['close_ct_mismatches']}")
            print(f"side agreement:     {not cmp['side_mismatches']}")
            print(f"max |dR|:           {cmp['max_abs_dR']}")
            print(f"over tolerance:     {cmp['n_over_tol']}")
            print(f"PARITY:             {cmp['verdict']}")
            out = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "harness": "midas_parity.py v2 (keyed)",
                "expert": expert, "tag": rec["tag"], "mode": rec["mode"],
                "window": {"t0": t0, "t1": t1, "name": args.window},
                "tester_dates": dates, "symbol": "XAUUSD",
                "inputs": build_inputs(rec["mode"], t0, t1),
                "evidence_source": rec["evidence_source"],
                "python": rec["python"], "ea": rec["ea"],
                **cmp,
            }
            path = f"artifacts/midas_parity_result_{datetime.now():%Y%m%d_%H%M}.json"
            with open(path, "w") as fh:
                json.dump(out, fh, indent=1)
            print("artifact:", path)
            rc = 0 if cmp["verdict"] == "PASS" else 1
    finally:
        if paused_by_us:
            os.remove(marker)
            print("watchdog resumed")
        if _should_relaunch_terminal(stopped, ran_passes):
            R.relaunch_terminal()
            print("terminal relaunched")
        else:
            print("terminal untouched (gate aborted before any stop)")
    return rc


def REPO_MARK_DIR() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


if __name__ == "__main__":
    sys.exit(main())
