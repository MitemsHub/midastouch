"""Build-parity shadow-window harness — arm-E §3's hard start precondition.

The sweep evidence for tp2.0 came from the RESEARCH build
(MitemshubAI_v28). Arm E's forward window may only open once the FORWARD EA
build demonstrates TRADE-SET-LEVEL parity with it: both builds run the
STRATEGY TESTER on the SAME held shadow window with the SAME complete input
surface, and their trade sets are diffed trade by trade. No parity pass, no
window — a forward test of a different engine would be a test of nothing
(ARM_E_TP20_FORWARD_PROPOSAL §3, frozen 2026-09-16).

Design, frozen before first use:
  * Shadow window: a HELD block (default `wf`), never `oos` — refused
    outright. The window is named in the artifact, which is §8's receipt.
  * Inputs: `candidate_inputs("V28_REVERSE_BOTH", tp2.0)` — exactly the §3
    pinned surface — passed verbatim to BOTH passes; only the pass-scoped
    run tags differ (journal addressability, v28_research discipline).
  * Normalization: per trade = (side, entry_time, R). Sides/times come from
    the report's simulated deals (identical timeline both builds); per-trade
    R from each build's own journal `Trade R:` prints. A build that cannot
    produce per-trade R evidence is INCONCLUSIVE, never "passing".
  * Verdict classes (mechanical, fail-closed):
      PASS                      same count, keys align in order, every
                                |dR| <= 0.02 and |dTotalR| <= 0.05
      FAIL_TRADE_SET            count differs or (side, entry_time) mismatch
      FAIL_R_SEQUENCE           keys align but per-trade or cumulative R drifts
      INCONCLUSIVE_ZERO_TRADES  either side produced zero trades
      INCONCLUSIVE_LOW_TRADES   structurally matched but n < 10
      INCONCLUSIVE_EVIDENCE     missing identity, missing R evidence, or
                                report/journal disagreement
  * Input pins: both passes' REPORT dumps (what actually ran, not the INI)
    must carry the §3 values — numeric-normalized ("2" == "2.0").
  * Terminal discipline: the sweep runner's own — identity -> arm inventory
    -> every ledger flat -> stop -> both passes -> relaunch. The forward
    expert's .ex5 must already exist in the tester terminal BEFORE the
    terminal is stopped (never stop a live arm for a run that cannot happen).
  * The research registry is NOT touched: parity is a precondition artifact,
    not a §5 experiment. Receipt: artifacts/v28_research/armE_parity_*.json

Usage:
  python scripts/build_parity.py --forward-expert "MITEMSHUB_AI\\MitemshubAI_v28_fwd"
  python scripts/build_parity.py status-quo   # research-vs-research sanity is
  deliberately NOT offered: two runs of one ex5 always "pass" and certify nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from v75_tester_runner import (  # noqa: E402
    TERMINAL_DATA, _tester_roots, pair_trades, report_inputs, report_stats, run_pass)
from v28_research import (  # noqa: E402
    DEFAULT_GEOMETRY, EA_V28, PASS_TIMEOUT_S, WINDOWS, candidate_inputs)
from v28_sweep_runner import (  # noqa: E402
    data_folder_for_terminal, inventory_arms, relaunch_terminal,
    stop_terminal, terminal_pids_exact, verify_all_flat)

ART = REPO / "artifacts" / "v28_research"

# The per-pass journal segment is tag-addressed: the pass's init banner prints
# "experiment=<run_tag>" (run_experiment feeds the run tag into
# InpExperimentTag), and a single-threaded agent logs one pass at a time, so
# everything from that banner to the next "MACRO started" line belongs to the
# pass. This survives the agent's flush lag that truncated the offset-based
# read (first live run: 13 of 27 Trade R lines captured).
SEG_INIT = re.compile(r"MACRO started.*experiment=(\S+)")
SEG_TRADE_R = re.compile(r"Trade R:\s*([+-]?\d+\.?\d*)")  # %+.4f prints a sign
SEG_CLOSE_R = re.compile(r"CLOSE \S+ ticket=\d+ pnl=[+-]?[\d.]+ R=([+-]?[\d.]+)")
FLUSH_WAIT_S = 60


def agent_lines_today() -> list[str]:
    lines: list[str] = []
    today = datetime.now().strftime("%Y%m%d")
    for root in _tester_roots():
        for log in root.glob(f"Agent-*/logs/{today}.log"):
            try:
                lines += log.read_bytes().decode("utf-16-le", "ignore").splitlines()
            except OSError:
                continue
    return lines


def pass_segment(tag: str) -> dict:
    """Identity + per-trade R evidence for one pass, from its journal segment.

    Trade R lines exist only in builds that print them (the forward build);
    CLOSE-line R values exist in both — so per-trade R evidence comes from
    Trade R when available and CLOSE R otherwise, never from nothing. The
    read is retried while the R count keeps growing (flush lag), then fails
    closed on whatever the segment finally carries.
    """
    deadline = time.monotonic() + FLUSH_WAIT_S
    seg_lines: list[str] = []
    r_vals: list[float] = []
    prev_count = -1
    seen = False
    while True:
        lines = agent_lines_today()
        starts = [i for i, l in enumerate(lines)
                  if "MACRO started" in l and f"experiment={tag}" in l]
        if starts:
            s = starts[-1]
            e = next((i for i in range(s + 1, len(lines))
                      if "MACRO started" in lines[i]), len(lines))
            seg_lines = lines[s:e]
            seen = True
            tr = [float(m.group(1)) for l in seg_lines
                  if (m := SEG_TRADE_R.search(l))]
            r_vals = tr if tr else [
                float(m.group(1)) for l in seg_lines
                if (m := SEG_CLOSE_R.search(l))]
        stable = seen and len(r_vals) == prev_count
        if stable or time.monotonic() > deadline:
            break
        prev_count = len(r_vals)
        time.sleep(2)
    return {"identity": _identity(seg_lines), "r_values": r_vals,
            "segment_lines": len(seg_lines)}


def _identity(seg_lines: list[str]) -> str:
    for l in seg_lines:
        if "MACRO started" in l:
            i = l.find("[")
            return l[i:].strip() if i >= 0 else l.strip()
    return ""

# Frozen tolerances (the v26.38 fill-model parity precedent: fill jitter is
# real but small; 0.02R is ~2% of a 1R risk unit and cumulative drift is
# bounded separately so tolerance cannot be laundered across many trades).
R_TOL = 0.02
TOTAL_R_TOL = 0.05
MIN_PARITY_TRADES = 10          # below this, "same trades" cannot certify "same engine"

# The §3 pin set, checked against what each pass's REPORT says it ran.
INPUT_PINS = {
    "InpStrategyMode": "3",            # V28_REVERSE_BOTH
    "InpStopATRMultiplier": "2.0",
    "InpTargetATRMultiplier": "2.0",
    "InpMaxHoldMinutes": "180",
    "InpRiskFraction": "0.01",
}

PASS = "PASS"
FAIL_TRADE_SET = "FAIL_TRADE_SET"
FAIL_R_SEQUENCE = "FAIL_R_SEQUENCE"
INC_ZERO = "INCONCLUSIVE_ZERO_TRADES"
INC_LOW = "INCONCLUSIVE_LOW_TRADES"
INC_EVIDENCE = "INCONCLUSIVE_EVIDENCE"
EXIT_CODES = {PASS: 0, FAIL_TRADE_SET: 10, FAIL_R_SEQUENCE: 10,
              INC_ZERO: 11, INC_LOW: 11, INC_EVIDENCE: 11}


def artifact_path(ts: str) -> Path:
    return ART / f"armE_parity_{ts}.json"


def _pin_ok(got: str, want: str) -> bool:
    if got == want:
        return True
    try:
        return abs(float(got) - float(want)) < 1e-9
    except (TypeError, ValueError):
        return False


def check_input_pins(per_build: dict[str, dict[str, str]]) -> tuple[bool, list[str]]:
    """Both builds' report-dumped inputs must carry the §3 pins (numeric-
    normalized). A "?" means the report omitted the key — a fail."""
    problems: list[str] = []
    for build, inputs in per_build.items():
        for key, want in INPUT_PINS.items():
            got = inputs.get(key, "?")
            if not _pin_ok(got, want):
                problems.append(f"{build}: {key}={got} (pin {want})")
    return not problems, problems


def normalize_trades(deals: list[list[str]], r_values: list[float]) -> tuple[list[dict] | None, str | None]:
    """Pair the report deals and align each trade with its journal R value.

    Both sides are chronological (the journal prints the close R at close; the
    report lists deals in time order), so index alignment is the contract —
    and a misalignment surfaces as an evidence refusal, never a false match.
    """
    trades = pair_trades(deals)
    if len(r_values) != len(trades):
        return None, (f"journal carries {len(r_values)} per-trade R values for "
                      f"{len(trades)} paired report trades — report/journal "
                      f"disagreement; parity cannot be certified")
    return [{"side": t["side"], "entry_time": t["entry_time"],
             "r": round(r, 4)} for t, r in zip(trades, r_values)], None


def diff_trade_sets(a: list[dict], b: list[dict],
                    r_tol: float = R_TOL, total_tol: float = TOTAL_R_TOL,
                    min_trades: int = MIN_PARITY_TRADES) -> dict:
    """The frozen verdict taxonomy, mechanical from the two trade sets."""
    na, nb = len(a), len(b)
    if na == 0 or nb == 0:
        return {"verdict": INC_ZERO, "evidence": [
            f"trade counts research={na} forward={nb}; a zero-trade side has "
            f"no trade set to certify (fail-closed, same principle as the "
            f"ledger-flatness check)"]}
    if na != nb:
        return {"verdict": FAIL_TRADE_SET, "evidence": [
            f"trade counts differ: research={na} forward={nb}"]}
    for i, (ta, tb) in enumerate(zip(a, b)):
        if ta["side"] != tb["side"] or ta["entry_time"] != tb["entry_time"]:
            misses = []
            for j in range(i, min(i + 5, na)):
                misses.append(f"trade {j}: research ({a[j]['side']}, {a[j]['entry_time']}) "
                              f"vs forward ({b[j]['side']}, {b[j]['entry_time']})")
            return {"verdict": FAIL_TRADE_SET, "evidence":
                    [f"trade-set divergence at index {i}"] + misses}
    if na < min_trades:
        return {"verdict": INC_LOW, "evidence": [
            f"trade sets are structurally identical but n={na} < "
            f"{min_trades}: too few trades to distinguish 'same engine' from "
            f"'same engine that barely trades'"]}
    deltas = [abs(ta["r"] - tb["r"]) for ta, tb in zip(a, b)]
    worst_i = max(range(na), key=lambda j: deltas[j])
    if deltas[worst_i] > r_tol:
        return {"verdict": FAIL_R_SEQUENCE, "evidence": [
            f"per-trade R divergence at index {worst_i}: "
            f"research {a[worst_i]['r']:+.4f} vs forward {b[worst_i]['r']:+.4f} "
            f"(|dR|={deltas[worst_i]:.4f} > {r_tol})"]}
    ta_tot, tb_tot = sum(t["r"] for t in a), sum(t["r"] for t in b)
    if abs(ta_tot - tb_tot) > total_tol:
        return {"verdict": FAIL_R_SEQUENCE, "evidence": [
            f"cumulative R drift: research {ta_tot:+.4f} vs forward "
            f"{tb_tot:+.4f} (|dTotalR|={abs(ta_tot - tb_tot):.4f} > {total_tol})"]}
    return {"verdict": PASS, "evidence": [
        f"n={na} trades aligned in order; max |dR|={max(deltas):.4f} <= {r_tol}; "
        f"totalR research {ta_tot:+.4f} vs forward {tb_tot:+.4f} "
        f"(|d|={abs(ta_tot - tb_tot):.4f} <= {total_tol})"]}


def _expert_exists(data_folder: str | None, expert: str) -> bool:
    if not data_folder:
        return False
    return (Path(os.path.expandvars(data_folder)) / "MQL5" / "Experts"
            / (expert + ".ex5")).exists()


def run_shadow(window: str, research_expert: str, forward_expert: str,
               override: bool = False) -> dict:
    """Full discipline: pins -> ex5 existence -> flat -> stop -> 2 passes ->
    relaunch -> diff -> artifact. Exit code carries the verdict class."""
    if window not in WINDOWS:
        raise SystemExit(f"unknown window {window!r}; known: {list(WINDOWS)}")
    if window == "oos":
        raise SystemExit("REFUSED: the oos block is the spent one-shot window "
                         "and is closed to every re-run, parity included. Use "
                         "a held block (wf/is90/is180).")
    if research_expert == forward_expert:
        raise SystemExit("REFUSED: forward expert equals the research expert — "
                         "two runs of one ex5 always 'pass' and certify nothing.")

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S") + "Z"
    frm, to, _role = WINDOWS[window]
    geometry = {**DEFAULT_GEOMETRY, "tp_atr": 2.0}     # tp2.0, §3's pinned cell
    mode = "V28_REVERSE_BOTH"

    data_folder = data_folder_for_terminal()
    missing = [name for name, exp in (("research", research_expert),
                                      ("forward", forward_expert))
               if not _expert_exists(data_folder, exp)]
    if missing:
        raise SystemExit(f"REFUSED before touching the terminal: no compiled "
                         f"expert(s) {missing} under {data_folder}\\MQL5\\Experts. "
                         f"Compile the forward build first; never stop a live "
                         f"arm for a run that cannot happen.")

    # --- terminal discipline (the sweep runner's own) ------------------------
    pids = terminal_pids_exact()
    arms = inventory_arms(data_folder)
    all_flat, evidence = verify_all_flat(arms)
    record: dict = {
        "ts": now.isoformat(timespec="seconds"),
        "purpose": "arm-E §3 build-parity precondition (shadow window)",
        "window": window, "window_from": frm, "window_to": to,
        "mode": mode, "geometry": geometry,
        "research_expert": research_expert, "forward_expert": forward_expert,
        "tolerances": {"r_tol": R_TOL, "total_r_tol": TOTAL_R_TOL,
                       "min_trades": MIN_PARITY_TRADES},
        "terminal_pids_before": pids,
        "arms": [{"name": a["name"], "magic": a["magic"], "tag": a["tag"],
                  "ledger": os.path.basename(a["ledger"])} for a in arms],
        "flatness": evidence,
    }
    if not arms:
        print("WARNING: no paper arms discovered on the tester terminal — the "
              "flat check has nothing to verify.")
        if not override:
            raise SystemExit("refusing (verify manually, then override).")
    if not all_flat and not override:
        offenders = [e for e in evidence if not e["flat"]]
        print("REFUSED: a hosted paper arm holds an OPEN position:")
        for e in offenders:
            for o in e["open_positions"]:
                print(f"  {e['name']}: ticket {o['ticket']} (ledger line {o['line']})")
        raise SystemExit("close it or override with --i-have-verified-flat.")
    record["override"] = override

    if pids:
        print(f"stopping tester terminal (pids {pids}) …", flush=True)
        if not stop_terminal(pids):
            raise SystemExit("ERROR: terminal did not stop; refusing to run.")
    passes: dict[str, dict] = {}
    try:
        for name, expert in (("research", research_expert),
                             ("forward", forward_expert)):
            tag = f"parity_{name}_{ts}"
            print(f"parity pass [{name}]: {expert} on {window} …", flush=True)
            result = run_pass(tag, candidate_inputs(mode, geometry, tag),
                              dates=(frm, to), timeout_s=PASS_TIMEOUT_S,
                              expert=expert, wait_for_research_line=True)
            rep, journal = result["report"], result["journal"]
            seg = pass_segment(tag)
            trades, err = normalize_trades(rep["deals"], seg["r_values"])
            stats = report_stats(tag)
            passes[name] = {
                "run_tag": tag,
                "identity": seg["identity"],
                "journal_r_count": len(seg["r_values"]),
                "segment_lines": seg["segment_lines"],
                "report_inputs": report_inputs(tag, tuple(INPUT_PINS)),
                "fills": rep["fills"], "exits": rep["exits"],
                "pnl": round(rep["pnl"], 2),
                "trade_pnls": [round(p, 2) for p in rep.get("trade_pnls", [])],
                "total_r_journal": journal["r_sum"],
                "net_profit_report": stats.get("Total Net Profit", ""),
                "trades": trades,
                "evidence_error": err,
            }
            print(f"  [{name}] identity: {seg['identity'][:90] or '(none)'} — "
                  f"{rep['fills']} fills, pnl {rep['pnl']:.2f}, "
                  f"journal R evidence {len(seg['r_values'])}", flush=True)
    finally:
        relaunch_terminal()
        record["relaunched"] = True
        record["terminal_pids_after"] = terminal_pids_exact()

    # --- identity + pins: fail closed before any diff ------------------------
    problems: list[str] = []
    for name in ("research", "forward"):
        p = passes[name]
        if not p["identity"]:
            problems.append(f"{name}: no engine identity line captured — the "
                            f"build that ran cannot be proven")
        if p["evidence_error"]:
            problems.append(f"{name}: {p['evidence_error']} (per-trade R "
                            f"evidence requires the research logging surface)")
    pins_ok, pin_problems = check_input_pins(
        {n: passes[n]["report_inputs"] for n in passes})
    record["input_pins_ok"] = pins_ok
    problems += pin_problems
    if problems:
        record["verdict"] = INC_EVIDENCE
        record["evidence"] = problems
        record["passes"] = passes
        return _finish(record, ts)

    d = diff_trade_sets(passes["research"]["trades"], passes["forward"]["trades"])
    record["verdict"] = d["verdict"]
    record["evidence"] = d["evidence"]
    record["passes"] = passes
    return _finish(record, ts)


def _finish(record: dict, ts: str) -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    out = artifact_path(ts)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1)
    print(f"\nPARITY VERDICT: {record['verdict']}")
    for e in record["evidence"]:
        print(f"  {e}")
    print(f"artifact: {out}")
    if record["verdict"] == PASS:
        print("arm-E §3 precondition: SATISFIED (attach this artifact in §8).")
    elif record["verdict"].startswith("FAIL"):
        print("arm-E §3 precondition: NOT SATISFIED — fix the build, rerun.")
    else:
        print("arm-E §3 precondition: UNPROVEN — inconclusive never opens the "
              "window; fix the evidence and rerun.")
    record["_exit"] = EXIT_CODES[record["verdict"]]
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--window", default="wf", choices=[w for w in WINDOWS],
                    help="held shadow window (oos refused outright)")
    ap.add_argument("--forward-expert", required=True,
                    help=r"forward build, relative to MQL5\Experts "
                         r"(e.g. MITEMSHUB_AI\MitemshubAI_v28_fwd)")
    ap.add_argument("--research-expert", default="MITEMSHUB_AI\\MitemshubAI_v28",
                    help=r"research build (default: the v28 sweep engine)")
    ap.add_argument("--i-have-verified-flat", action="store_true",
                    help="override the ledger-flat refusal (recorded in the artifact)")
    args = ap.parse_args()
    record = run_shadow(args.window, args.research_expert, args.forward_expert,
                        override=args.i_have_verified_flat)
    sys.exit(record["_exit"])


if __name__ == "__main__":
    main()
