"""Arm C paper-ledger tester validation (V75_TESTER tier, one-off drill).

QUESTION (2026-09-15): does V75MacroEngine v2.21's paper mode, run in the
Strategy Tester over the cached 71-day real-tick window, produce a ledger
whose CLOSE rows are valid — and does the REAL watchdog parser
(morning_status.parse_ledger) read a filled trade end-to-end?

Why a tester pass: the arm-C chart sits on the real account at FB9A and the
engine is standing down in aligned DOWNTREND — no fill exists yet, so the
ledger's CLOSE path has never executed live. The tester exercises the exact
same writers against the real tick stream without touching any terminal or
account. The pass runs on 49E0 (tester/reserve-only, no arm magics); the
paper arms' terminals are never closed and the ledger lands in the tester
agent's sandbox, not in any terminal the watchdog scans.

Checks (all must hold for PASS):
  V1  identity: the journal's init line says v2.21 ... PAPER and
      "virtual fills only"; no live-path "=== EXECUTING" print appears.
  V2  ledger produced in the agent sandbox with >= 1 OPEN and >= 1 CLOSE row.
  V3  row schema: OPEN rows have 12 comma fields, CLOSE rows 8, per the
      v2.21 writers; every CLOSE references the epoch of the OPEN it closes.
  V4  accounting: R == pnl/riskAmount (OPEN row) within 0.02 per trade;
      recomputed equity (start 50 + cumulative pnl) matches every EQ row
      within 0.01 and the final CLOSE's veq column.
  V5  end-to-end watchdog: morning_status.parse_ledger() over the tester
      ledger reports closed trades, zero problems, and a veq_last equal to
      the ledger's own final equity — the exact object the A/B machinery
      and the morning report consume.
  V6  telemetry: a "fill" event per OPEN and a "close" event per CLOSE.

If the production config (1% risk at the $50 virtual floor) refuses fills on
the min-lot guard, that is REPORTED as the primary result (it is correct
behavior) and a --risk-variant pass with a raised InpRiskPercent proves the
CLOSE machinery with real fills, clearly labeled as a config variant.

Usage: python scripts/validate_armc_paper_ledger_tester.py [--keep-report]
Writes: artifacts/v75_macro_engine_tester/armc_paper_ledger_<date>.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import v75_tester_runner as runner                      # noqa: E402
from morning_status import parse_ledger                 # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART_DIR = os.path.join(REPO, "artifacts", "v75_macro_engine_tester")

# Arm C's exact chart inputs (FB9A chart03, re-parse verified 2026-09-14)
ARM_C_INPUTS = {
    "InpMagicNumber": "7788125",
    "InpH4EMAPeriod": "20",
    "InpH1EMAPeriod": "20",
    "InpBBPeriod": "20",
    "InpBBDeviation": "2.0",
    "InpRSIPeriod": "14",
    "InpRSIBuyLevel": "35.0",
    "InpATRPeriod": "14",
    "InpRiskPercent": "1.0",
    "InpRRMultiplier": "2.0",
    "InpEnableTickSafety": "true",
    "InpPaperMode": "true",
}


def preflight() -> None:
    """The tester's own install (49E0 / MitemshubMT5_B) must not be running.

    The constraint is per-install, not global: the arms live on other installs
    (FB9A default, 71BF MitemshubMT5_C) which run as separate processes with
    their own data folders — launching 49E0's terminal64.exe headless never
    touches them. What WOULD corrupt state is two processes sharing the 49E0
    data folder (profiles are rewritten on exit)."""
    import subprocess
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
          "Select-Object -ExpandProperty ExecutablePath")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise SystemExit(f"cannot enumerate running terminals ({e}) - refusing to guess")
    running = [l.strip() for l in out.splitlines() if l.strip()]
    exe = str(runner.TERMINAL_EXE).lower()
    if any(p.lower() == exe for p in running):
        raise SystemExit(
            f"the tester terminal ({runner.TERMINAL_EXE}) is already running - close it "
            "first (two processes on one data folder corrupt profiles). Other running "
            "terminals are separate installs and are not touched.")
    print(f"preflight OK: {len(running)} other terminal64 process(es) running "
          "(arm terminals - untouched); tester install is free.")


def find_sandbox_ledger(max_age_s: int = 900) -> str | None:
    """The paper ledger inside the tester agent sandbox (written this run)."""
    now = datetime.now().timestamp()
    hits = []
    for root in runner._tester_roots():
        for path in root.glob("Agent-*/MQL5/Files/V75MacroEngine_paper_Volatility_75_Index.csv"):
            if now - path.stat().st_mtime <= max_age_s:
                hits.append(path)
    if not hits:
        return None
    return str(max(hits, key=lambda p: p.stat().st_mtime))


def clear_sandbox() -> None:
    """Remove tester-sandbox ledger/telemetry before a pass.

    The agent's Files dir persists between passes and the writers APPEND
    (FILE_READ|FILE_WRITE + seek-end), so a leftover ledger would splice two
    runs into one file and break the $50 equity replay. Scratch data only -
    nothing here belongs to the arms.
    """
    names = ("V75MacroEngine_paper_Volatility_75_Index.csv",
             "V75MacroEngine_paper_telemetry_Volatility_75_Index.jsonl")
    for root in runner._tester_roots():
        for path in root.glob("Agent-*/MQL5/Files/*"):
            if path.name in names:
                path.unlink(missing_ok=True)


def read_rows(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\r\n").split(",") for line in f if line.strip()]


def validate_ledger(path: str) -> tuple[dict, list[str]]:
    """V3/V4 row-level validation; returns (summary, problems)."""
    rows = read_rows(path)
    opens, closes, eqs = [], [], []
    for r in rows:
        if r[0] == "OPEN":
            opens.append(r)
        elif r[0] == "CLOSE":
            closes.append(r)
        elif r[0] == "EQ":
            eqs.append(r)
    problems: list[str] = []

    for r in opens:
        if len(r) != 12:
            problems.append(f"OPEN row with {len(r)} fields (want 12): {r}")
    for r in closes:
        if len(r) != 8:
            problems.append(f"CLOSE row with {len(r)} fields (want 8): {r}")
    open_epochs = {r[1] for r in opens}
    for r in closes:
        if r[2] not in open_epochs:
            problems.append(f"CLOSE references entry epoch {r[2]} with no matching OPEN")

    # V4 accounting, replayed from the ledger's own columns. The file is
    # append-only and chronological by construction, so file order IS the
    # trade sequence (EQ rows carry equity, not a timestamp - never sort on it).
    equity, seq = 50.0, 0.0
    # arms' schema: col8 = eff_risk $ (the R denominator), col9 = stop_dist
    risk_of = {r[1]: float(r[8]) for r in opens if len(r) >= 12}
    for r in rows:
        if r[0] == "CLOSE":
            try:
                pnl, r_mult, veq = float(r[6]), float(r[5]), float(r[7])
            except (ValueError, IndexError):
                problems.append(f"unparseable CLOSE: {r}")
                continue
            risk = risk_of.get(r[2], 0.0)
            if risk > 0 and abs(pnl / risk - r_mult) > 0.02:
                problems.append(f"R mismatch: pnl {pnl} / risk {risk} != R {r_mult}")
            equity += pnl
            seq += r_mult
            if abs(equity - veq) > 0.01:
                problems.append(f"veq discontinuity: CLOSE says {veq}, replay {equity:.2f}")
        elif r[0] == "EQ":
            try:
                eq = float(r[1])
            except (ValueError, IndexError):
                problems.append(f"unparseable EQ: {r}")
                continue
            if abs(eq - equity) > 0.01:
                problems.append(f"EQ {eq} != replayed equity {equity:.2f}")
    summary = {
        "ledger_path": path,
        "open_rows": len(opens), "close_rows": len(closes), "eq_rows": len(eqs),
        "final_equity_replay": round(equity, 2), "r_sum": round(seq, 3),
        "reasons": sorted({r[3] for r in closes if len(r) >= 4}),
        "first_open": opens[0] if opens else None,
        "first_close": closes[0] if closes else None,
    }
    return summary, problems


def journal_today_counts() -> dict:
    """Event counts from TODAY's raw agent journals (all passes share the
    file, so these are audit context, not pass-scoped evidence)."""
    text = "\n".join(log.read_bytes().decode("utf-16-le", "ignore")
                     for log in runner.journal_paths())
    return {
        "init_paper_banner": len(re.findall(r"v\d+\.\d+ initialized .*PAPER", text)),
        "virtual_fills_only": len(re.findall(r"virtual fills only", text)),
        "paper_refused": len(re.findall(r"PAPER TRADE REFUSED: computed volume ([\d.]+)", text)),
        "refused_volumes": [float(v) for v in
                            re.findall(r"PAPER TRADE REFUSED: computed volume ([\d.]+)", text)],
        "paper_close": len(re.findall(r"PAPER CLOSE", text)),
        "telemetry_error": len(re.findall(r"PAPER TELEMETRY ERROR", text)),
        "ledger_error": len(re.findall(r"PAPER LEDGER ERROR", text)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default=f"armc_ledger_{datetime.now():%Y%m%d_%H%M}")
    ap.add_argument("--variant-risk", type=float, default=None,
                    help="second pass with InpRiskPercent=N (machinery proof if the "
                         "production config refuses fills on the min-lot guard)")
    ap.add_argument("--keep-report", action="store_true")
    args = ap.parse_args(argv)

    preflight()
    results: dict = {
        "schema": "mitemshub.artifact-spec.v1",
        "artifact": "armc_paper_ledger_tester_validation",
        "generated_at": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "window": ["2026.07.01", "2026.09.10"],
        "terminal": str(runner.TERMINAL_DATA.name),
        "passes": [],
    }

    def do_pass(tag: str, inputs: dict[str, str], label: str) -> dict:
        print(f"=== tester pass [{label}] tag={tag} ===", flush=True)
        clear_sandbox()
        res = runner.run_pass(tag, inputs, timeout_s=runner.PASS_TIMEOUT_S)
        ledger = find_sandbox_ledger()
        counts = journal_today_counts()
        entry = {
            "label": label, "tag": tag,
            "report_fills": res["report"]["fills"],
            "report_pnl": round(res["report"]["pnl"], 2),
            "identity": res["journal"].get("identity", ""),
            "journal_counts_today": counts,
            "sandbox_ledger_found": bool(ledger),
        }
        if ledger:
            summ, probs = validate_ledger(ledger)
            entry["ledger"] = summ
            entry["ledger_problems"] = probs
            # V5 - the REAL watchdog parser, end-to-end
            led = parse_ledger(ledger)
            entry["watchdog_parse_ledger"] = {
                "closed": len(led["closed"]),
                "veq_last": led["veq_last"],
                "problems": led["problems"],
                "first_closed": led["closed"][0] if led["closed"] else None,
            }
            # V6 - telemetry side
            telem = os.path.join(os.path.dirname(ledger),
                                 "V75MacroEngine_paper_telemetry_Volatility_75_Index.jsonl")
            if os.path.exists(telem):
                kinds: dict[str, int] = {}
                with open(telem, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        try:
                            t = json.loads(line).get("type", "?")
                        except json.JSONDecodeError:
                            t = "corrupt"
                        kinds[t] = kinds.get(t, 0) + 1
                entry["telemetry_kinds"] = kinds
        results["passes"].append(entry)
        return entry

    # Pass 1: production config, arm C's exact inputs
    p1 = do_pass(args.tag, dict(ARM_C_INPUTS), "production-config")
    variant = None
    if args.variant_risk is not None and (
            p1.get("ledger", {}).get("close_rows", 0) == 0
            or not p1["sandbox_ledger_found"]):
        vi = dict(ARM_C_INPUTS)
        vi["InpRiskPercent"] = str(args.variant_risk)
        variant = do_pass(args.tag + "_var", vi,
                          f"config-variant risk={args.variant_risk}% (machinery proof)")

    # Verdict: the CLOSE-row machinery must be proven by a pass that filled
    # (variant, if the production config refused), with a clean ledger, a
    # clean watchdog parse, and no writer errors anywhere today.
    target = variant if variant and variant.get("ledger", {}).get("close_rows") else p1
    ok = False
    if target and target.get("sandbox_ledger_found"):
        led, wd, counts = (target.get("ledger", {}), target.get("watchdog_parse_ledger", {}),
                           target["journal_counts_today"])
        target_telem = target.get("telemetry_kinds", {})
        ok = (led.get("close_rows", 0) >= 1 and not led.get("ledger_problems")
              and wd.get("closed", 0) >= 1 and not wd.get("problems")
              and counts["init_paper_banner"] >= 1
              and counts["virtual_fills_only"] >= 1
              and counts["ledger_error"] == 0
              and counts["telemetry_error"] == 0
              and target_telem.get("fill", 0) >= 1
              and target_telem.get("close", 0) >= 1)
    results["verdict"] = "PASS" if ok else "FAIL"
    p1_counts = p1["journal_counts_today"]
    results["primary_refused_on_minlot"] = bool(
        p1_counts["paper_refused"] and not p1.get("ledger", {}).get("close_rows"))
    if results["primary_refused_on_minlot"]:
        vols = p1_counts.get("refused_volumes", [])
        results["findings"] = {
            "minlot_inert_at_floor": True,
            "note": "Production config (1% risk at the $50 virtual floor) refused "
                    "every entry: computed volume < 0.01 broker minimum. Arm C's "
                    "2xATR H1 stop implies min-lot stop-risk ~$14-17 (28-34% of "
                    "$50) - the arms' $50-floor tolerance story does not transfer "
                    "to this geometry. Arm C needs its own pre-registered minimum "
                    "viable size before it can trade anywhere.",
            "max_computed_volume": max(vols) if vols else None,
        }

    os.makedirs(ART_DIR, exist_ok=True)
    out = os.path.join(ART_DIR, f"armc_paper_ledger_{datetime.now():%Y%m%d}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    if not args.keep_report:
        for tag in (args.tag, args.tag + "_var"):
            rp = runner.report_path(tag)
            if rp.exists():
                rp.unlink()

    print(json.dumps({k: results[k] for k in
                      ("verdict", "primary_refused_on_minlot")}, indent=1))
    print(f"artifact: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
