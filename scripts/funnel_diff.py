"""NO-GO playbook Step 4, automated: rate-normalized funnel diff (replay vs paper).

Produces the playbook's exact output contract (docs/NO_GO_BRANCH_PLAYBOOK.md §4):
`artifacts/v75_replay/funnel_diff_<date>.json` — the diff table (per counter:
replay count, live count, rates per 1000 signals evaluated, verdict) plus the
provenance both sides need to be trusted.

Frozen verdict rules (from the playbook's known-bad patterns + the 2026-09-15
drill's honesty guards):
  - both sides 0                                -> match (~0 both sides)
  - either raw count < LOW_COUNT_MIN            -> LOW-COUNT: not adjudicable at
    this window (journal retention ~6d vs replay 60d makes small counts noise;
    drill finding F4)
  - rates differ > RATIO_DRIFT x                -> drifted (Outcome B input)
  - else                                        -> match (within regime)
  - account-guard: special. Replay has no account guard (n/a). Every paper
    firing is classified PER FIRING from its own operands + the host arm's
    ledger state at the firing instant (2026-09-16 investigation: a blunt
    post-deploy timestamp rule mis-flagged two correct vetoes):
      position open  AND fleet ~ $0        -> DEFECT (v26.37 mirror blind)
      no position    AND fleet > $0        -> DEFECT (phantom fleet risk)
      otherwise                           -> WORKING (designed veto: the
      account-budget guard refusing a min-lot entry that busts
      InpMaxTotalRiskPct on shrunken virtual equity — the documented
      small-account/strangulation regime, never a strategy defect)
    pre-v26.37-deploy firings stay the closed $0-basis class (informational).
    Any DEFECT flags the row; WORKING vetoes are reported, never flagged.
  - meta-label / time-block / family-throttle: expected ~0 BOTH sides; nonzero
    either side = CONFIG DRIFT (the replay has no meta table either).

Live denominators: the arms share ONE signal stream (measured 09-15,
arm_b_rate_decomposition_20260915.json), so the numerator (both hosts' journals,
which cannot be attributed per-instance from journal text alone) is normalized
by arm A + arm B telemetry sig counts combined. The V75MacroEngine arm (C_v75)
is telemetry-only and NOT part of this diff (different engine, no replay funnel).

Every run also appends a compact row to `funnel_diff_history.json` so journal
expiry can never again silently destroy the counts (drill finding F4).

Usage:
  python scripts/funnel_diff.py                       # defaults: baseline of record
  python scripts/funnel_diff.py --replay <cert_report.json> --no-append
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACT_DIR = os.path.join(ROOT, "artifacts", "v75_replay")

REPLAY_DEFAULT = os.path.join(ARTIFACT_DIR, "cert_report_fresh60_tp18_net.json")
HOSTS = {
    "FB9A": r"%APPDATA%\MetaQuotes\Terminal\FB9A56D617EDDDFE29EE54EBEFFE96C1",
    "71BF": r"%APPDATA%\MetaQuotes\Terminal\71BF6B2AB5548CFBA970FA2F38007C31",
}
TELEMETRY = "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl"

# Engine print strings, grep-verified against the v26.37 source (playbook §4).
# Ordered; each maps a journal regex to the funnel counter it evidences.
PATTERNS = {
    "spread-gate":   re.compile(r"governor spread gate", re.I),
    "risk-cap":      re.compile(r"min-lot risk \$[\d.]+ exceeds cap", re.I),
    "fleet-cap":     re.compile(r"fleet risk \$[\d.]+ \+ new \$[\d.]+ exceeds cap", re.I),
    "paused":        re.compile(r"consecutive-loss breaker", re.I),
    "account-guard": re.compile(r"ACCOUNT GUARD", re.I),
    "auto-disable":  re.compile(r"SUPPRESSED \(probing", re.I),
    "meta-label":    re.compile(r"meta-label gate", re.I),
    "time-block":    re.compile(r"time.?block", re.I),
    "family-throttle": re.compile(r"family.?throttle", re.I),
}
ZERO_EXPECTED_LIVE = ("meta-label", "time-block", "family-throttle")
NO_REPLAY_COUNTER = ("fleet-cap",)   # sim has no such guard

LOW_COUNT_MIN = 5
RATIO_DRIFT = 2.0
# v26.37 deploy (FleetOpenRisk virtual-book mirror) — journal-local time.
V37_DEPLOY = datetime(2026, 9, 15, 12, 19, 45)

# The account-guard journal line carries its own evidence: build tag and the
# three guard operands (fleet risk, candidate risk, cap).
GUARD_LINE = re.compile(
    r"\[v([\d.]+)\].*ACCOUNT GUARD: fleet \$([\d.]+) \+ new \$([\d.]+) "
    r"> cap \$([\d.]+)", re.I)
# ~$0.005 tolerance: the journal prints 2 decimals.
EPS = 0.005


def ledger_for_host(root: str) -> str | None:
    """The arm's paper ledger on this host (tagged file preferred)."""
    files = os.path.join(os.path.expandvars(root), "MQL5", "Files")
    for pat in ("MitemshubAI_paper_*_B.csv", "MitemshubAI_paper_Volatility_75_Index.csv"):
        hits = sorted(glob.glob(os.path.join(files, pat)))
        if hits:
            return hits[-1]
    return None


def ledger_state_at(ledger: str | None, when: datetime) -> tuple[bool, float | None]:
    """Sequential pairing on the single-position paper book: is a position
    open at `when`, and what was the virtual equity after the last CLOSE
    before `when`? (The EA enforces InpSameSymbolMaxPos=1, so OPEN/CLOSE
    sequence pairing is valid.)"""
    if not ledger or not os.path.exists(ledger):
        return False, None
    open_at_t, veq = False, None
    for line in open(ledger, encoding="utf-8", errors="replace"):
        p = line.strip().split(",")
        if len(p) < 8 or p[0] not in ("OPEN", "CLOSE"):
            continue
        try:
            ts = datetime.fromtimestamp(int(p[1]))
            if ts > when:
                break
        except (ValueError, OSError, OverflowError):
            continue
        if p[0] == "OPEN":
            open_at_t = True
        else:
            open_at_t = False
            try:
                veq = float(p[7])
            except ValueError:
                pass
    return open_at_t, veq


def classify_guard_firing(firing: dict) -> tuple[str, list[str]]:
    """The frozen taxonomy, mechanical from the firing's own evidence."""
    notes = []
    if firing.get("post_deploy") is None:
        return "UNCLASSIFIED — firing time unparseable", notes
    if not firing.get("post_deploy", True):
        return "pre-v26.37 (closed $0-basis class)", notes
    fleet, veq = firing.get("fleet", 0.0), firing.get("veq_at_fire")
    open_at_t = firing.get("position_open", False)
    if open_at_t and fleet <= EPS:
        return "DEFECT (mirror blind: position open, fleet read $0)", notes
    if (not open_at_t) and fleet > EPS:
        return "DEFECT (phantom fleet risk: no open position)", notes
    if veq:
        cap_pct = firing["cap"] / veq * 100.0
        new_pct = firing["new"] / veq * 100.0
        notes.append(f"veq ${veq:.2f}; cap = {cap_pct:.1f}% of veq (InpMaxTotalRiskPct=15 "
                     f"expected); new trade = {new_pct:.1f}% of veq")
    else:
        notes.append("virtual equity unavailable (no ledger evidence) — veto accepted "
                     "on operand shape alone")
    return "WORKING (designed veto: account-budget guard on shrunken equity)", notes

LINE_TIME = re.compile(r"^\S*\s+\S+\s+(\d{2}:\d{2}:\d{2})")


def grep_host(host: str, root: str) -> dict:
    """UTF-16 journal greps for one terminal host. Returns per-counter counts,
    the firing timestamps for account-guard, and the journal day window."""
    counts = {k: 0 for k in PATTERNS}
    guard_fire_times: list[str] = []
    guard_details: list[dict] = []
    days: list[str] = []
    logdir = os.path.join(os.path.expandvars(root), "MQL5", "Logs")
    for jf in sorted(glob.glob(os.path.join(logdir, "*.log"))):
        day = os.path.basename(jf)[:8]   # YYYYMMDD (basename is YYYYMMDD.log)
        days.append(day)
        try:
            txt = io.open(jf, encoding="utf-16", errors="replace").read()
        except OSError:
            continue
        for k, pat in PATTERNS.items():
            hits = pat.findall(txt)
            counts[k] += len(hits)
            if k == "account-guard" and hits:
                for line in txt.splitlines():
                    m = pat.search(line)
                    if not m:
                        continue
                    g = GUARD_LINE.search(line)
                    tm = LINE_TIME.match(line)
                    if tm:
                        guard_fire_times.append(f"{day} {tm.group(1)}")
                    if g:
                        guard_details.append({
                            "at": f"{day} {tm.group(1)}" if tm else day,
                            "host": host, "build": g.group(1),
                            "fleet": float(g.group(2)),
                            "new": float(g.group(3)),
                            "cap": float(g.group(4)),
                            "post_deploy": (datetime.strptime(
                                f"{day} {tm.group(1)}", "%Y%m%d %H:%M:%S")
                                >= V37_DEPLOY) if tm else None,
                            "line": line.strip()[:200]})
    return {"counts": counts, "guard_fire_times": guard_fire_times,
            "guard_details": guard_details,
            "journal_days": sorted(set(days))}


def telemetry_sigs(root: str) -> tuple[int, str]:
    """Sig-event count + last-event date from one arm's telemetry (denominator)."""
    f = os.path.join(os.path.expandvars(root), "MQL5", "Files", TELEMETRY)
    if not os.path.exists(f):
        return 0, ""
    n = 0
    last_ts = ""
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "sig":
                n += 1
                last_ts = str(d.get("ts", last_ts))
    return n, last_ts


def load_replay(path: str) -> dict:
    d = json.load(open(path, encoding="utf-8"))
    funnel = d.get("funnel")
    if not isinstance(funnel, dict) or "score" not in funnel:
        raise SystemExit(f"FAIL: {path} has no funnel.score — not a cert report; "
                         "replay normalization is impossible. Refusing to guess.")
    return {"path": path, "tag": d.get("tag", os.path.basename(path)),
            "funnel": funnel}


def verdict(counter: str, replay_n: int, live_n: int,
            replay_rate: float, live_rate: float, live_sig_total: int) -> str:
    if counter in NO_REPLAY_COUNTER:
        return "match (0)" if live_n == 0 else "live-only firing (no replay counter)"
    if replay_n == 0 and live_n == 0:
        return "match (~0 both sides)" if counter in ZERO_EXPECTED_LIVE else "match (0 = 0)"
    if replay_n < LOW_COUNT_MIN or live_n < LOW_COUNT_MIN or live_sig_total == 0:
        return "LOW-COUNT: not adjudicable at this window"
    ratio = (max(replay_rate, live_rate) / max(min(replay_rate, live_rate), 1e-9)) \
        if min(replay_rate, live_rate) > 0 else float("inf")
    return "drifted (>2x rate)" if ratio > RATIO_DRIFT else "match (within regime)"


def run(replay_path: str, append: bool = True) -> dict:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    now = datetime.now(timezone.utc)
    rep = load_replay(replay_path)
    funnel = rep["funnel"]
    score = funnel["score"]

    hosts_out, days_all = {}, []
    for host, root in HOSTS.items():
        r = grep_host(host, root)
        hosts_out[host] = r
        days_all += r["journal_days"]
    live = {k: sum(hosts_out[h]["counts"][k] for h in hosts_out) for k in PATTERNS}

    sigs = {}
    for host, root in HOSTS.items():
        n, last = telemetry_sigs(root)
        sigs[host] = {"sig_events": n, "last_sig": last}
    live_sig_total = sum(s["sig_events"] for s in sigs.values())

    def rr(c):
        return round(1000.0 * c / score, 2) if score else None

    def lr(c):
        return round(1000.0 * c / live_sig_total, 2) if live_sig_total else None

    table = []
    # account-guard firings are classified PER FIRING from their own operands
    # + the host arm's ledger state at the firing instant (2026-09-16: the
    # blunt post-deploy timestamp rule mis-flagged two correct vetoes — the
    # 15% account-budget guard refusing min-lot entries on shrunken virtual
    # equity, i.e. the documented strangulation regime working as designed).
    guard_firings = []
    for h in hosts_out:
        det_by_key = {d["at"]: d for d in hosts_out[h]["guard_details"]}
        for t in hosts_out[h]["guard_fire_times"]:
            try:
                dt = datetime.strptime(t, "%Y%m%d %H:%M:%S")
            except ValueError:
                continue
            det = det_by_key.get(t)
            entry = {"at": t, "host": h}
            if det:
                entry.update({k: det[k] for k in ("build", "fleet", "new", "cap")})
            if det is None:
                entry["class"] = ("pre-v26.37 (closed $0-basis class)" if dt < V37_DEPLOY
                                  else "UNCLASSIFIED — firing line lacked operands")
            elif not det["post_deploy"]:
                entry["class"] = "pre-v26.37 (closed $0-basis class)"
            else:
                pos_open, veq = ledger_state_at(ledger_for_host(HOSTS[h]), dt)
                det["position_open"], det["veq_at_fire"] = pos_open, veq
                cls, notes = classify_guard_firing(det)
                det["class"], det["notes"] = cls, notes
                entry["class"], entry["notes"] = cls, notes
                entry["position_open"], entry["veq_at_fire"] = pos_open, veq
            guard_firings.append(entry)
    if live["account-guard"] and guard_firings:
        bad = [f for f in guard_firings
               if f["class"].startswith(("DEFECT", "UNCLASSIFIED"))]
        working = [f for f in guard_firings if f["class"].startswith("WORKING")]
        if bad:
            guard_verdict = (f"DEFECTIVE — {len(bad)} of {len(guard_firings)} "
                             "firing(s) classified DEFECT/UNCLASSIFIED")
        elif working:
            guard_verdict = ("CLASSIFIED: designed vetoes — account-budget guard "
                             "refusing min-lot entries on shrunken equity "
                             "(strangulation regime), not defects")
        else:
            guard_verdict = ("CLASSIFIED: all firing(s) pre-v26.37 — closed class, "
                             "informational only")
    else:
        guard_verdict = "clean (class closed v26.37)"
    for counter in PATTERNS:
        rn = funnel.get(counter, 0)
        ln = live[counter]
        r_rate, l_rate = rr(rn), lr(ln)
        v = guard_verdict if counter == "account-guard" \
            else verdict(counter, rn, ln, r_rate or 0.0, l_rate or 0.0, live_sig_total)
        if counter in ZERO_EXPECTED_LIVE and (rn > 0 or ln > 0):
            v = "CONFIG DRIFT — expected ~0 both sides"
        row = {"counter": counter, "replay": rn, "replay_rate_per_1k": r_rate,
               "live": ln, "live_rate_per_1k": l_rate, "verdict": v}
        if counter == "account-guard":
            row["verdict"] = guard_verdict
            if guard_firings:
                row["firings"] = guard_firings
        table.append(row)

    out = {
        "schema": "v75_funnel_diff/1",
        "generated_utc": now.isoformat(timespec="seconds"),
        "playbook_step": "docs/NO_GO_BRANCH_PLAYBOOK.md §4 (automated)",
        "replay": {"path": rep["path"], "tag": rep["tag"], "funnel": funnel,
                   "signal_denominator": score},
        "live": {"per_host": {h: {"counts": hosts_out[h]["counts"],
                                  "journal_days": hosts_out[h]["journal_days"],
                                  "guard_details": hosts_out[h]["guard_details"]}
                              for h in hosts_out},
                 "signal_denominators": sigs, "signal_denominator_total": live_sig_total,
                 "note": "journals cannot be attributed per-instance (same EA/symbol "
                         "on both hosts); numerator = both hosts, denominator = A+B "
                         "telemetry sig events (shared stream, measured 09-15)"},
        "comparability": {
            "journal_window": [min(days_all), max(days_all)] if days_all else None,
            "replay_window": "fresh 60-day certified window",
            "F4": "journal retention < paper history < replay window; LOW-COUNT "
                  "rows are window-limited, not evidence of drift"},
        "table": table,
    }

    print(f"=== FUNNEL DIFF {now:%Y-%m-%d %H:%M} ===")
    print(f"replay: {rep['tag']} (score={score}) | live: {live_sig_total} sig events "
          f"({out['comparability']['journal_window']})")
    for row in table:
        print(f"  {row['counter']:<15} replay {row['replay']:>5} "
              f"({row['replay_rate_per_1k']}) | live {row['live']:>3} "
              f"({row['live_rate_per_1k']}) -> {row['verdict']}")
        for f in row.get("firings", []):
            ops = (f" [v{f.get('build', '?')} fleet ${f.get('fleet', '?')} + new "
                   f"${f.get('new', '?')} > cap ${f.get('cap', '?')}]")
            print(f"      firing {f['at']}: {f['class']}{ops}")
    drifted = [r["counter"] for r in table if r["verdict"].startswith(("drifted", "DEFECTIVE", "CONFIG", "live-only"))]
    print(f"  summary: {len(drifted)} flagged" + (f": {', '.join(drifted)}" if drifted else " — funnel clean"))

    if append:
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        outp = os.path.join(ARTIFACT_DIR, f"funnel_diff_{now:%Y%m%d}.json")
        json.dump(out, open(outp, "w", encoding="utf-8"), indent=1)
        hist_p = os.path.join(ARTIFACT_DIR, "funnel_diff_history.json")
        hist = []
        if os.path.exists(hist_p):
            try:
                hist = json.load(open(hist_p, encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                hist = []
        hist = hist if isinstance(hist, list) else []
        hist.append({"generated_utc": out["generated_utc"],
                     "replay_tag": rep["tag"], "replay_score": score,
                     "live_sig_total": live_sig_total,
                     "journal_window": out["comparability"]["journal_window"],
                     "live_counts": live, "flagged": drifted})
        json.dump(hist, open(hist_p, "w", encoding="utf-8"), indent=1)
        print(f"  artifact: {outp}\n  history: {hist_p} (row #{len(hist)})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replay", default=REPLAY_DEFAULT,
                    help="cert_report_*.json carrying the replay funnel dict")
    ap.add_argument("--no-append", action="store_true",
                    help="read-only: print the table, write nothing")
    args = ap.parse_args()
    run(args.replay, append=not args.no_append)


if __name__ == "__main__":
    main()
