#!/usr/bin/env python3
"""MIDASTOUCH Step 5 — build parity (protocol §8, amendment 3).

Three stages, each independently runnable (tester passes can outlive a
shell timeout):

  python scripts/midas_parity.py --prepare
      Rebuilds the python baseline from the CURRENT engine
      (midas_sweep.run_window_trades on the frozen WF window) and stages
      the tester config: BAR execution model, the shared recorded-spread
      series (written from the SAME CSV python prices with), fresh virtual
      equity, a clean EA ledger in the tester agent sandbox.

  python scripts/midas_parity.py --run
      Stops the terminal, runs MidastouchAI.ex5 (current build) in the strategy
      tester on real ticks over the same window. The tester agent sandbox
      can be slow on first run (tick download) — safe to re-invoke.

  python scripts/midas_parity.py --compare
      Aligns the EA ledger trade list against the python trade list
      (entry-open-time keyed, sequence checked) and issues the verdict:
      PASS requires identical trade count, identical sides/timestamps and
      max |dR| <= 0.01 (the house tolerance). Divergences print side by
      side with the mechanism they name. Restores the terminal for the
      paper arm either way.

Output: artifacts/midas_parity_result_<date>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "scripts")
sys.path.insert(0, "tests")

import v75_tester_runner as T                       # noqa: E402
import v28_sweep_runner as R                        # noqa: E402
import midas_sweep as S                             # noqa: E402

# --- point the house runner at the default install (49E0 data folder) -------
from pathlib import Path
T.TERMINAL_EXE = Path(R.TERM_EXE)
T._BASE_TESTER_INI["Symbol"] = "XAUUSD"
T._BASE_TESTER_INI["Period"] = "M15"
T._BASE_TESTER_INI["Leverage"] = "1000"
T._BASE_TESTER_INI["Deposit"] = "1000"

EXPERT = r"MITEMSHUB_AI\MidastouchAI"
TAG = "midas_wf_rd_bar"

# ── certification configuration (v1.08: parameterizable) ──────────────────
# defaults = the Amendment 3 configuration of record
MODE = "REVERSE_DIRECTION"          # python mode name under test
SESSION = (6, 20)                   # signal-hour gate (Amendment 4 cert uses (12, 16))
W0, W1 = S.WINDOWS["wf"]
# To covers the final window bar (python keeps MANAGING open positions past
# t1 until they close — max hold 12h — so the tester must run past t1 too;
# ending the pass at t1 truncated the EA ledger tail, 2026-09-17).
DATES = (f"{W0[:10].replace('-', '.')}", "2026.04.03")

# python mode execution order == the EA's ENUM_MIDAS_MODE index
_MODE_INDEX = {m: i for i, m in enumerate(
    ["ORIGINAL", "REVERSE_DIRECTION", "REVERSE_TRIGGER", "REVERSE_BOTH",
     "LONG_ONLY", "SHORT_ONLY", "MACRO_ONLY", "TRIGGER_ONLY"])}


def _baseline_path() -> str:
    return f"artifacts/midas_parity_python_{MODE.lower()}_ses{SESSION[0]}{SESSION[1]}.json"


def _config_path() -> str:
    return "artifacts/midas_parity_config.json"


def apply_config(mode: str, session: tuple[int, int]) -> None:
    """Point the whole certification at one mode + session gate.
    PERSISTS to artifacts/midas_parity_config.json: driver subcommands are
    separate processes, and prepare→run→compare MUST share one config —
    found live 2026-09-17 when --run silently reverted to defaults after a
    parameterized --prepare and the cert compared the wrong baseline."""
    global MODE, SESSION, W0, W1, DATES, TAG
    if mode not in _MODE_INDEX:
        raise SystemExit(f"unknown mode {mode}; one of {sorted(_MODE_INDEX)}")
    MODE = mode
    SESSION = session
    W0, W1 = S.WINDOWS["wf"]
    DATES = (f"{W0[:10].replace('-', '.')}", "2026.04.03")
    TAG = f"midas_wf_{mode.lower()}_ses{session[0]}{session[1]}"
    INPUTS["InpMode"] = str(_MODE_INDEX[mode])
    INPUTS["InpSessionStartHour"] = str(session[0])
    INPUTS["InpSessionEndHour"] = str(session[1])
    INPUTS["InpWindowStart"] = str(int(S.iso_to_ts(W0)))
    INPUTS["InpWindowEnd"] = str(int(S.iso_to_ts(W1)))
    with open(_config_path(), "w") as fh:
        json.dump({"mode": MODE, "session": list(SESSION)}, fh)


def load_staged_config() -> None:
    """Restore the staged certification config (if any). CLI args (when
    explicitly given) override it in main()."""
    try:
        cfg = json.load(open(_config_path()))
        apply_config(cfg["mode"], tuple(cfg["session"]))
    except (OSError, ValueError, KeyError):
        pass                                     # no staged config: defaults


INPUTS = {
    "InpMagic": "7801001",
    "InpArmTag": "M1",
    "InpMode": "1",                  # REVERSE_DIRECTION (overridden by apply_config)
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
    "InpSessionStartHour": "6",       # overridden by apply_config
    "InpSessionEndHour": "20",
    "InpSpreadCapPctStop": "1.5",
    "InpFridayCutoffHour": "20",
    "InpUseNewsFilter": "false",
    "InpStaleMinutes": "30",
    "InpRiskPercent": "1.0",
    "InpLiveExecution": "false",      # parity contract: the live layer NEVER runs here
    "InpDailyLossCapPct": "0.0",      # breaker off in tester/paper research paths
    "InpPaperEquity": "5000.0",       # = python START_EQUITY: identical sizing path
    "InpBarModel": "true",            # amendment 3: research-bar replay model
    # NOTE: the pass runs on the tester's 1-minute-OHLC model (see stage_run).
    # Real-tick mode only fires OnTick on bars that had recorded ticks, so the
    # replay loop skipped quiet M15 bars that python's loop always processes;
    "InpSpreadFile": "MIDASTOUCH_spread_M15.csv",
    "InpWindowStart": "0",            # set by apply_config (python window t0)
    "InpWindowEnd": "0",              # set by apply_config (python window t1)
}

TOL = 0.01


def agent_files_dir() -> str | None:
    r"""The local tester agent's MQL5\Files sandbox. Tester agents live under
    the SHARED root %APPDATA%\MetaQuotes\Tester\<hash>\Agent-... (the
    terminal data folder's own Tester dir holds only cache/logs — found
    live 2026-09-17)."""
    df = R.data_folder_for_terminal()
    if not df:
        return None
    h = os.path.basename(df.rstrip("\\/"))
    p = os.path.join(R.TERM_ROOT, "..", "Tester", h,
                     "Agent-127.0.0.1-3000", "MQL5", "Files")
    p = os.path.normpath(p)
    return p if os.path.isdir(p) else None


def ledger_path() -> str:
    d = agent_files_dir()
    if not d:
        raise SystemExit("tester agent sandbox not found — run a pass first")
    return os.path.join(d, "MIDASTOUCH_paper_XAUUSD_M1.csv")


def parse_ledger(path: str) -> list[dict]:
    """EA trade list in python-row vocabulary: open_ct, close_ct, side,
    reason, r, entry, exit."""
    rows: dict[str, dict] = {}
    trades: list[dict] = []
    with open(path) as fh:
        for line in fh:
            p = line.strip().split(",")
            if len(p) >= 12 and p[0] == "OPEN":
                rows[p[2]] = {"open_ct": int(p[1]), "side": int(p[3]),
                              "entry": float(p[4])}
            elif len(p) >= 8 and p[0] == "CLOSE":
                o = rows.pop(p[2], {})
                trades.append({"open_ct": o.get("open_ct"),
                               "close_ct": int(p[1]), "side": o.get("side"),
                               "reason": p[3], "exit": float(p[4]),
                               "r": float(p[5]), "pnl": float(p[6]),
                               "entry": o.get("entry", 0.0)})
    return trades


def stage_prepare() -> int:
    t0, t1 = S.iso_to_ts(W0), S.iso_to_ts(W1)

    # 1) the python baseline, from the CURRENT engine at the ACTIVE session
    #    gate — never a stale artifact (run_window_trades is 06-20-bound;
    #    the Amendment 4 certifications need the 12-16 engine).
    trades = S.run_mode(MODE, t0, t1, S.build_data(), *SESSION).trades
    baseline = _baseline_path()
    with open(baseline, "w") as fh:
        json.dump(trades, fh, indent=1)
    print(f"python baseline: {len(trades)} trades, sumR {sum(t['r'] for t in trades):+.3f} -> {baseline}")

    # 2) the shared recorded-spread series (from the same CSV python uses)
    spread_path = "artifacts/MIDASTOUCH_spread_M15.csv"
    m15 = S.load_bars(os.path.join(S.DATA_DIR, "XAUUSD_M15.csv"))
    n = S.dump_spread_file(m15, spread_path)
    print(f"spread series: {n} bars -> {spread_path}")

    # 3) stage the spread file where the tester copies FROM (the terminal data
    #    folder's MQL5\Files; the EA's #property tester_file pulls it into the
    #    agent sandbox at pass start — the agent wipes arbitrary staged files,
    #    found live 2026-09-17), plus a fresh agent ledger for a clean run.
    import shutil
    df = R.data_folder_for_terminal()
    if not df:
        raise SystemExit("terminal data folder not found")
    stage_dir = os.path.join(df, "MQL5", "Files")
    shutil.copyfile(spread_path, os.path.join(stage_dir, "MIDASTOUCH_spread_M15.csv"))
    d = agent_files_dir()
    if d:
        ea_ledger = os.path.join(d, "MIDASTOUCH_paper_XAUUSD_M1.csv")
        if os.path.exists(ea_ledger):
            os.remove(ea_ledger)
        print(f"staged spread file in {stage_dir} + clean EA ledger in {d}")
    else:
        print(f"staged spread file in {stage_dir} (agent sandbox not found — pass will create it)")

    return 0


def stage_sim() -> int:
    """Simulated-live test: REAL-TICK tester pass with the LIVE ORDER PATH
    enabled (InpLiveExecution=true, PERTICK model). Proves the order path
    end-to-end under market execution: signal → CTrade fill with server-side
    SL/TP → LOPEN/LCLOSE ledger rows → timeout closes. Paper mirror stays
    off (InpLiveExecution gates it), so only LOPEN/LCLOSE rows may appear."""
    with open(_hold_path(), "w") as fh:
        fh.write(str(os.getpid()))
    pids = R.terminal_pids_exact()
    if pids:
        print(f"terminal running (pids {pids}) — stopping first")
        R.stop_terminal(pids)
    T._BASE_TESTER_INI["Model"] = "4"          # REAL recorded ticks
    inputs = dict(INPUTS)
    inputs["InpBarModel"] = "false"
    inputs["InpLiveExecution"] = "true"
    res = T.run_pass(TAG + "_sim", inputs, timeout_s=3600, dates=DATES, expert=EXPERT)
    print("tester metrics:", json.dumps(res.get("report_stats", res), default=str)[:300])
    lp = ledger_path()
    counts = {"LOPEN": 0, "LCLOSE": 0, "OPEN": 0, "CLOSE": 0}
    reasons: dict[str, int] = {}
    if os.path.exists(lp):
        for line in open(lp):
            for k in counts:
                if line.startswith(k + ","):
                    counts[k] += 1
            p = line.strip().split(",")
            if p and p[0] == "LCLOSE" and len(p) >= 4:
                reasons[p[3]] = reasons.get(p[3], 0) + 1
        os.remove(lp)
    print(f"sim ledger: {counts} | close reasons: {reasons}")
    paper_leak = counts["OPEN"] or counts["CLOSE"]
    print("SIM VERDICT:", "LIVE PATH EXERCISED" if counts["LOPEN"] and not paper_leak else
          ("LIVE PATH DID NOT FIRE (0 signals — check window/session)" if not counts["LOPEN"] else
           "CONTAMINATED: paper mirror rows present"))
    if os.path.exists(_hold_path()):
        os.remove(_hold_path())
    return 0


def _hold_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".midas_terminal_hold")


def stage_run() -> int:
    # watchdog hold: the terminal being stopped here is EXPECTED — tell the
    # watchdog so it never relaunches mid-certification (PID lets the
    # watchdog drop a stale hold if this process dies before --compare).
    with open(_hold_path(), "w") as fh:
        fh.write(str(os.getpid()))
    pids = R.terminal_pids_exact()
    if pids:
        print(f"terminal running (pids {pids}) — stopping first")
        R.stop_terminal(pids)
    # Model 1 (1-minute OHLC): the BAR replay engine prices everything from
    # the bar series + shared spread file (never from ticks), so the tick
    # model only decides WHICH bars fire OnTick. Real ticks (model 4) leave
    # quiet M15 bars silent — python still iterates them; 1m-OHLC guarantees
    # every M15 bar fires, making the replay tick-model independent.
    T._BASE_TESTER_INI["Model"] = "1"
    # stale-ledger hygiene (2026-09-17): a leftover sandbox ledger from an
    # older pass (e.g. a full-year PERTICK sim) must never survive into this
    # pass — a compare consuming it produces a garbage verdict.
    d = agent_files_dir()
    if d:
        stale = os.path.join(d, "MIDASTOUCH_paper_XAUUSD_M1.csv")
        if os.path.exists(stale):
            os.remove(stale)
            print("removed stale sandbox ledger")
    res = T.run_pass(TAG, INPUTS, timeout_s=3600, dates=DATES, expert=EXPERT)
    print("tester metrics:", json.dumps(res.get("report_stats", res), default=str)[:300])
    return 0


def stage_compare(fingerprint: bool) -> int:
    py = json.load(open(_baseline_path()))
    fp = "skipped"
    if fingerprint:
        # Regression guard: rebuild the baseline with the CURRENT engine and
        # prove it equals the staged one. A FAIL with a drifted baseline is a
        # bug hunt, not a verdict — this catches EA-parity runs against a
        # stale research engine before they are believed.
        fresh = S.run_mode(MODE, S.iso_to_ts(W0), S.iso_to_ts(W1), S.build_data(), *SESSION).trades
        same = (len(fresh) == len(py) and all(
            a["open_ct"] == b["open_ct"] and a["side"] == b["side"]
            and abs(a["r"] - b["r"]) <= 1e-9 for a, b in zip(fresh, py)))
        fp = "match" if same else "DRIFT"
        print(f"regression fingerprint (current engine vs staged baseline): {fp}")
    ea = parse_ledger(ledger_path())

    # provenance check (v1.09): the sandbox ledger must be a BAR-model pass
    # (ERA note "bar-model-parity") with exactly one era stamp. A PERTICK or
    # stale ledger here means the pass never ran as configured — abort instead
    # of issuing a verdict (the 08:59 pollution lesson).
    era_rows = [l.strip() for l in open(ledger_path()) if l.startswith("ERA,")]
    era_note = era_rows[0].split(",")[3].strip() if len(era_rows) == 1 and len(era_rows[0].split(",")) > 3 else "?"
    if era_note != "bar-model-parity":
        raise SystemExit(
            f"PROVENANCE FAIL: sandbox ledger ERA note = '{era_note}' "
            f"({len(era_rows)} ERA rows) — not a BAR-model pass of this "
            f"certification. Re-run --prepare && --run, then --compare.")
    print(f"ledger provenance: {era_rows[0]}")

    n = min(len(ea), len(py))
    diffs: list[tuple] = []
    max_d = 0.0
    for i in range(n):
        a, b = ea[i], py[i]
        d = abs(a["r"] - b["r"])
        max_d = max(max_d, d)
        if (d > TOL or a["open_ct"] != b["open_ct"] or a["side"] != b["side"]):
            diffs.append((i, a, b, d))

    count_match = len(ea) == len(py)
    verdict = "PASS" if count_match and not diffs else "FAIL"

    print("=" * 78)
    print(f"python: {len(py)} trades, sumR {sum(t['r'] for t in py):+.3f}")
    print(f"EA:     {len(ea)} trades, sumR {sum(t['r'] for t in ea):+.3f}")
    print(f"count match: {count_match} | compared {n} | mismatching rows: {len(diffs)} | max |dR| {max_d:.4f}")
    print(f"PARITY: {verdict}")
    for i, a, b, d in diffs[:25]:
        print(f"  #{i}: open {a['open_ct']} vs {b['open_ct']} | side {a['side']} vs {b['side']} "
              f"| R {a['r']:+.4f} vs {b['r']:+.4f} (dR {a['r']-b['r']:+.4f}) "
              f"| {a['reason']} vs {b['reason']} | entry {a['entry']:.2f} vs {b['entry']:.2f}")
    if not count_match:
        tail = ea[len(py):] if len(ea) > len(py) else py[len(ea):]
        who = "EA-only" if len(ea) > len(py) else "python-only"
        for t in tail[:10]:
            print(f"  {who}: open {t['open_ct']} side {t['side']} R {t['r']:+.4f} {t['reason']}")

    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "expert": EXPERT, "tag": TAG, "dates": DATES, "symbol": "XAUUSD",
        "mode": MODE, "exec_model": "BAR (amendment 3)",
        "tester_model": "1 (1-minute OHLC)",
        "regression_fingerprint": fp,
        "python": {"n": len(py), "sum_r": round(sum(t["r"] for t in py), 4)},
        "ea": {"n": len(ea), "sum_r": round(sum(t["r"] for t in ea), 4)},
        "count_match": count_match,
        "row_mismatches": len(diffs),
        "max_abs_dR": round(max_d, 5),
        "tolerance": TOL,
        "verdict": verdict,
        "first_mismatch_details": [
            {"idx": i, "ea": {k: a[k] for k in ("open_ct", "side", "reason", "r")},
             "py": {k: b[k] for k in ("open_ct", "side", "reason", "r")}}
            for i, a, b, d in diffs[:5]],
    }
    path = f"artifacts/midas_parity_result_{TAG}_{datetime.now():%Y%m%d}.json"
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    print("artifact:", path)

    R.relaunch_terminal()
    print("terminal relaunched")
    if os.path.exists(_hold_path()):
        os.remove(_hold_path())
    return 0 if verdict == "PASS" else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--sim", action="store_true",
                    help="real-tick tester pass with the LIVE order path enabled (v1.08 simulated-live proof)")
    ap.add_argument("--mode", default=None,
                    help="python mode under certification; explicit > staged config > REVERSE_DIRECTION")
    ap.add_argument("--session", default=None,
                    help="signal-hour gate START-END UTC; explicit > staged config > 6-20")
    ap.add_argument("--fingerprint", action="store_true",
                    help="with --compare: re-run the engine and assert the staged baseline is current")
    a = ap.parse_args()
    # config precedence: explicit CLI args > staged config file > defaults
    load_staged_config()
    if a.mode is not None or a.session is not None:
        ses = tuple(int(x) for x in (a.session or f"{SESSION[0]}-{SESSION[1]}").replace(":", "-").split("-"))
        apply_config(a.mode or MODE, ses)
    print(f"cert config: mode={MODE} session={SESSION[0]}-{SESSION[1]} tag={TAG}")
    if a.prepare:
        return stage_prepare()
    if a.run:
        return stage_run()
    if a.compare:
        return stage_compare(a.fingerprint)
    if a.sim:
        return stage_sim()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
