#!/usr/bin/env python3
"""MIDASTOUCH §13 monthly forward-verdict tool (per-arm adjudication).

    python scripts/midas_verdict.py                # every ledger-bearing arm
    python scripts/midas_verdict.py --tag M1t      # one arm
    python scripts/midas_verdict.py --json         # machine artifact

The closeout registered this tool as the next small one — "thresholds already
frozen, so the tool can never redefine them." That is its design law:

  * **The gates live here as read-only constants.** Values are the §13 /
    Amendment 4 rulebook (docs/MIDASTOUCH_PROTOCOL.md, frozen 2026-09-17 with
    the ledger at zero fills; §14 keeps them verbatim per arm):
        VALIDATED         n >= 60 AND totalR > 0 AND DD <= 25% AND meanR >= 0.05
        REJECTED          n >= 60 AND (totalR < 0 OR DD > 30% OR meanR <= 0)
        CONTINUE-UNPROVEN everything else (n < 60, or the gray zones:
                          meanR in (0, 0.05) with positive R and calm DD;
                          DD in (25%, 30%] with positive R)
  * **Statistics are R-denominated, post-era closes only.** CLOSE rows carry
    their line number; the positional era rule of scripts/era.py classifies
    them (rows below the first well-formed ERA stamp carry the stamp's era,
    everything else falls to the frozen boundary epoch). The MIDASTOUCH
    writer stamps at init, so a mixed-era ledger is theoretically possible —
    the tool filters rather than assumes.
  * **The verdict is computed, never stored.** No artifact to drift: every
    reading recomputes from the ledger of record, and a one-line reference to
    this file satisfies the monthly §13 note. `--json` emits the full
    evidence record (per-arm metrics, per-arm structural state, read stamp)
    for closeout/protocol citations.
  * **Version discipline is structural, not decorative.** Two guards answer
    the §13 abort rows before any verdict is printed:
      - preset identity ([3b] `preset_identity`): the chart's live inputs
        must be byte-exact against the arm's repo .set — the silent-preset-
        loss guard from the 2026-09-17 drift incidents. DRIFT or
        UNVERIFIABLE is abort-grade; a chart file that cannot be located
        reports UNVERIFIABLE too (fail-closed, never a guessed OK).
      - watchdog escalation (§12): 3+ consecutive restups or a DRIFT action
        in artifacts/midas_watchdog_last_action.json aborts the window.
    Abort = the arm's window is INVALID as evidence (§13: a polluted window
    is never judged). The tool never re-accrues or archives anything — the
    §12 certified chain owns remediation; this tool only refuses to bless.
  * **Discovery is tag-driven** (§14): every `MIDASTOUCH_paper_<sym>_<tag>`
    ledger on the gold terminal is an arm. A missing ledger is a loud skip
    (an arm whose EA never initialized has no window to judge), and the
    single-arm mode fails loudly when the requested tag has no ledger.

Only the MIDASTOUCH ledgers are read. Nothing writes terminal or repo state.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

# --- frozen §13 gates (read-only; changing these values is an amendment) ------
MIN_N = 60          # trades before the window can be judged at all
DD_MAX = 25.0       # % of virtual equity, peak-to-trough, VALIDATED ceiling
DD_ABORT = 30.0     # % — beyond this the window is REJECTED
MEAN_R_MIN = 0.05   # R per trade, VALIDATED floor
GATES = {"MIN_N": MIN_N, "DD_MAX": DD_MAX, "DD_ABORT": DD_ABORT,
         "MEAN_R_MIN": MEAN_R_MIN}          # artifact/export form (frozen)

VALIDATED, REJECTED = "VALIDATED", "REJECTED"
CONTINUE = "CONTINUE-UNPROVEN"
VERDICTS = (VALIDATED, REJECTED, CONTINUE)

import era  # noqa: E402  (positional era classification, scripts/era.py)

# V2 register §1 (docs/MIDASTOUCH_V2_REGISTER.md, 2026-09-17): a telemetry-
# only build stamps this citation into its ERA note. A version change whose
# transition is so cited cannot have altered any CLOSE row's R nor the set of
# trades given identical ticks — exactly the never-abort class. The citation
# must sit ON THE ERA ROW WHERE THE NEW VERSION FIRST APPEARS (the writer
# stamps it at init), so a transition is exempt only when the walk finds the
# citation at that exact boundary; anything else stays abort-grade.
TELEMETRY_ONLY_NOTE = "telemetry-only-per-V2-register"
TELEMETRY_ONLY_NOTE_DOC = "docs/MIDASTOUCH_V2_REGISTER.md"
from midas_watchdog import (  # noqa: E402
    MAX_RESTUPS, data_folder_for_terminal, midas_arms, preset_for_tag)
import morning_status as ms  # noqa: E402  ([3b] preset_identity + parse_ledger)

WATCHDOG_STATE = os.path.join(REPO, "artifacts", "midas_watchdog_state.json")
WATCHDOG_LAST = os.path.join(REPO, "artifacts", "midas_watchdog_last_action.json")
PROTOCOL_DOC = "docs/MIDASTOUCH_PROTOCOL.md"   # §13 (Amendment 4) / §14


# --- the frozen rulebook --------------------------------------------------------

def verdict(n: int, total_r: float, max_dd_pct: float, mean_r: float) -> str:
    """§13 Amendment 4 mapping, verbatim. Pure — tests pin every boundary."""
    if n < MIN_N:
        return CONTINUE
    if total_r > 0 and max_dd_pct <= DD_MAX and mean_r >= MEAN_R_MIN:
        return VALIDATED
    if total_r < 0 or max_dd_pct > DD_ABORT or mean_r <= 0:
        return REJECTED
    return CONTINUE


# --- ledger statistics ----------------------------------------------------------

def _telemetry_only(row: dict) -> bool:
    """True iff the ERA row's note field carries the register §1 citation."""
    return TELEMETRY_ONLY_NOTE in (row.get("era") or "")


def _unexempted_version_changes(era_rows: list[dict]) -> list[str]:
    """Walk the era stamps; report each version change not exempted by §1.

    The rule (docs/MIDASTOUCH_V2_REGISTER.md §1): a version change from A to B
    is exempt from the §13 version-change abort ONLY when the ERA row that
    FIRST shows B carries the telemetry-only citation in its note field —
    exactly where the v1.13 writer stamps it (at init, mid-ledger). Reasoning:
    the abort exists to stop comparing trades made under different decision
    logic; a cited telemetry-only build cannot have altered any CLOSE row's R
    nor the set of trades given identical ticks, so the statistics of record
    are untouched. Fail-closed by construction:
      * a new version whose first stamp lacks the citation aborts;
      * a citation on a NON-transition stamp (same-version re-stamp, e.g. a
        restart) is ignored — citing a version that was already running proves
        nothing about when the binary changed;
      * the exemption does not launder the whole ledger: an exempted A→B and
        a later uncited B→C still abort on the B→C leg.
    Every transition — exempted or not — is returned in the evidence record so
    the audit trail never loses a version change to the exemption.
    """
    prev: str | None = None
    unexempted: list[str] = []
    for row in era_rows:
        version = row.get("version") or ""
        if not version:
            continue
        if prev is not None and version != prev:
            if not _telemetry_only(row):
                unexempted.append(f"{prev}->{version} (line {row.get('line')}, "
                                  "first stamp lacks the register §1 citation)")
        prev = version
    return unexempted


def _version_transitions(era_rows: list[dict]) -> list[dict]:
    """Evidence record: every version transition with its exemption state."""
    prev: str | None = None
    transitions: list[dict] = []
    for row in era_rows:
        version = row.get("version") or ""
        if not version:
            continue
        if prev is not None and version != prev:
            transitions.append({
                "from": prev, "to": version, "line": row.get("line"),
                "telemetry_exempt": _telemetry_only(row),
                "note": row.get("era") or "",
            })
        prev = version
    return transitions


def arm_statistics(path: str) -> dict:
    """R statistics from one gold ledger, post-era CLOSE rows only.

    CLOSE,<epoch>,<ticket>,<reason>,<exit>,<r>,<pnl>,<veq>  (8 fields).
    The midastouchai family is per-tick in all eras (scripts/era.py), so the
    era filter reduces to the family rule — but the ERA stamps are still read
    for what they really carry here: the EA VERSION. Distinct versions in one
    ledger = a version change mid-window = the §13 structural abort row.
    Drawdown runs on the CLOSE-veq path, peak-to-trough, exactly like
    armd_accrual (the closed-trade path; floating DD is not in the ledger —
    the OPEN row carries pre-trade equity only by construction). Two
    hardening refinements over the accrual tracker, both fail-closed:
      * a CLOSE whose veq is <= 0 poisons the DD denominator — the window is
        polluted (structural abort), not silently mis-measured;
      * an unreadable/unparseable row aborts the read (never a guessed n).
    """
    closes: list[dict] = []
    era_rows = era.parse_era_rows(path)
    problems: list[str] = []
    versions = sorted({r["version"] for r in era_rows if r.get("version")})
    if len(versions) > 1:
        unexempted = _unexempted_version_changes(era_rows)
        if unexempted:
            problems.append(
                "EA version change in ledger: " + ", ".join(versions) + " — "
                "structural abort (§13: a version change is never a "
                "continuation; archive and re-accrue on a fresh ledger; "
                "unexempted transitions: " + "; ".join(unexempted) + ")")
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            parts = line.strip().split(",")
            if not parts or parts[0] != "CLOSE":
                continue
            if len(parts) < 8:
                problems.append(f"line {ln}: CLOSE row too short ({len(parts)} fields)")
                continue
            try:
                epoch, r, veq = int(parts[1]), float(parts[5]), float(parts[7])
            except ValueError:
                problems.append(f"line {ln}: unparseable CLOSE epoch/r/veq")
                continue
            closes.append({"epoch": epoch, "reason": parts[3],
                           "r": r, "veq": veq, "line": ln})
    post = [c for c in closes
            if era.era_of_trade("midastouchai", c, era_rows) == era.ERA_POST]
    n = len(post)
    total_r = sum(c["r"] for c in post)
    wins = sum(1 for c in post if c["r"] > 0)
    dd = 0.0
    peak = None
    for c in post:
        if c["veq"] <= 0:
            problems.append(f"line {c['line']}: CLOSE veq {c['veq']} — DD denominator "
                            "nonpositive, window polluted")
            continue
        peak = c["veq"] if peak is None else max(peak, c["veq"])
        dd = max(dd, (peak - c["veq"]) / peak * 100.0)
    return {"ledger": os.path.basename(path),
            "n": n, "total_r": round(total_r, 4),
            "mean_r": round(total_r / n, 4) if n else 0.0,
            "wins": wins, "max_dd_pct": round(dd, 2),
            "last_close_epoch": post[-1]["epoch"] if post else None,
            "era_versions": versions, "era_rows": len(era_rows),
            "version_transitions": _version_transitions(era_rows),
            "problems": problems}


# --- structural-abort state (§13 abort rows; §12 + [3b] are the evidence) -------

def _json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data: dict | None = json.load(f)
            return data
    except (OSError, ValueError):
        return None


def watchdog_abort() -> dict:
    """§12 watchdog state -> abort evidence for this window.

    Escalation is state-backed (consecutive_restups >= 3, the same constant
    morning_status [3b] reads); a DRIFT/ESCALATE last action is abort-grade
    even when the counter has since been reset. Absence of artifacts is
    reported, never guessed about.
    """
    st = _json(WATCHDOG_STATE)
    last = _json(WATCHDOG_LAST)
    problems: list[str] = []
    if st is None:
        problems.append("watchdog state missing — §12 liveness is unverifiable")
    else:
        if st.get("consecutive_restups", 0) >= MAX_RESTUPS:
            problems.append(f"watchdog escalated: {st['consecutive_restups']} "
                            "consecutive restups without recovery")
    if last is not None and last.get("action") in ("DRIFT", "ESCALATE"):
        problems.append(f"watchdog last action {last['action']} "
                        f"(drift remediation on record)")
    return {"problems": problems}


def preset_abort(chart_path: str, tag: str) -> dict:
    """[3b] preset identity vs the arm's repo .set -> abort evidence.

    UNVERIFIABLE (unreadable/missing pins or chart) is abort-grade here too:
    an unidentifiable arm is exactly the 'silent preset loss' the check
    exists to prevent, so the window stops rather than guesses.

    Deferred pins (2026-09-18 era law): a repo pin owned by a NEWER build
    than the arm's running binary is recorded EVIDENCE (`notes`), never an
    abort — the tree legitimately advances in-tree while the §13 window
    runs on the certified deployed version. Unknown missing pins still
    abort (fail-closed: only pins in morning_status.DEFERRED_PINS defer).
    """
    try:
        chart_txt = open(chart_path, encoding="utf-16", errors="replace").read()
    except OSError as e:
        return {"problems": [f"chart unreadable: {e}"], "notes": [],
                "verdict": "UNVERIFIABLE"}
    ident = ms.preset_identity(chart_txt, preset_for_tag(tag))
    problems: list[str] = []
    notes: list[str] = []
    if ident.get("deferred"):
        notes.append("preset deferred pin: " + ", ".join(ident["deferred"]))
    if ident["verdict"] != "OK":
        if ident["missing"]:
            problems.append(f"preset DRIFT: missing from chart: {', '.join(ident['missing'])}")
        if ident["extra"]:
            problems.append(f"preset DRIFT: on chart, not in .set: {', '.join(ident['extra'])}")
        for k, got, want in ident["drift"]:
            problems.append(f"preset DRIFT: {k}={got} (repo pin {want})")
        for p in ident["problems"]:
            problems.append(f"preset identity: {p}")
    return {"verdict": ident["verdict"], "n_keys": ident["n_keys"],
            "problems": problems, "notes": notes}


def arms(data_folder: str | None = None) -> list[dict]:
    """Ledger-bearing gold arms (tag-driven discovery, midas_watchdog.midas_arms).

    A chart with no ledger yet is skipped loudly (EA never initialized — no
    window exists to judge); a ledger FILE no chart claims is reported as an
    orphan (matched by path — the filename embeds the symbol, so the arm's
    tag never equals the basename).
    """
    df = data_folder if data_folder is not None else data_folder_for_terminal()
    known = midas_arms(df)
    out: list[dict] = []
    for a in known:
        if os.path.exists(a["ledger"]):
            out.append(a)
        else:
            print(f"  [{a['tag']}] ledger missing (EA never initialized) — no window to judge",
                  file=sys.stderr)
    claimed = {os.path.normpath(a["ledger"]) for a in known}
    for lp in glob.glob(os.path.join(df or "", "MQL5", "Files", "MIDASTOUCH_paper_*.csv")):
        if os.path.normpath(lp) not in claimed:
            print(f"  orphan ledger {os.path.basename(lp)} — no chart attached; "
                  "not judged (structural question, not a statistics question)",
                  file=sys.stderr)
    return out


# --- per-arm adjudication -------------------------------------------------------

def adjudicate(tag: str, ledger: str, chart: str) -> dict:
    """One arm's §13 reading: statistics + structural state + verdict.

    The verdict key is ALWAYS present. A structural abort reports
    CONTINUE-UNPROVEN + `abort: true` + the reasons, in BOTH directions —
    §13: "a polluted window is never judged". A VALIDATED under pollution
    would be evidence-laundering, and a REJECTED under pollution cannot
    retire the family either: the drift abort means the EA may not even
    have run the arm's strategy (the 11:11 code-defaults incident), and
    §13's own remediation is archive + re-accrue from zero, so the family
    always gets its clean window. Until the certified chain fixes the
    structure, the window shows CONTINUE with the abort reason loud.
    """
    stats = arm_statistics(ledger)
    wd = watchdog_abort()
    pre = preset_abort(chart, tag)
    abort_reasons = wd["problems"] + pre["problems"] + stats["problems"]
    v = verdict(stats["n"], stats["total_r"], stats["max_dd_pct"], stats["mean_r"])
    if abort_reasons:
        v = CONTINUE
    return {"tag": tag, "verdict": v, "abort": bool(abort_reasons),
            "abort_reasons": abort_reasons, "notes": pre.get("notes", []),
            "stats": stats,
            "preset": pre, "watchdog": wd,
            "gates": dict(GATES), "doc": PROTOCOL_DOC}


# --- reporting ------------------------------------------------------------------

def paint(text: str, color: str = "") -> str:
    """ANSI paint for terminals that render it; plain elsewhere."""
    if not color:
        return text
    codes = {"r": "\033[31m", "g": "\033[32m", "b": "\033[34m", "y": "\033[33m"}
    return f"{codes.get(color, '')}{text}\033[0m"


def _print_row(a: dict) -> None:
    s = a["stats"]
    print(f"[13] {a['tag']}: n={s['n']}/{MIN_N} totalR={s['total_r']:+.2f} "
          f"meanR={s['mean_r']:+.3f} DD={s['max_dd_pct']:.1f}% wins={s['wins']}")
    if a["abort"]:
        print(paint("  STRUCTURAL ABORT - window invalid as evidence:", "y"))
        for r in a["abort_reasons"]:
            print(paint(f"    - {r}", "y"))
    line = f"  §13 VERDICT: {a['verdict']}"
    if a["abort"]:
        line += " (aborted window — never adjudicated)"
    color = ("y" if a["abort"] else
             "g" if a["verdict"] == VALIDATED else
             "r" if a["verdict"] == REJECTED else "b")
    print(paint(line, color))
    if a["abort"]:
        print("  structural fix -> archive the ledger (§13), re-accrue from zero")
    elif s["n"] < MIN_N:
        print(f"  gate clock: {s['n']}/{MIN_N} post-era closed trades — "
              f"first monthly reading 2026-10-01")
    else:
        print(f"  gates: n>={MIN_N}, totalR>0, DD<={DD_MAX:.0f}%, "
              f"meanR>={MEAN_R_MIN} ({PROTOCOL_DOC} §13/§14 — frozen)")


def run(tag: str | None = None, data_folder: str | None = None) -> dict:
    """The tool's whole read. Returns {read_at, gates, doc, arms: {tag: ...}}."""
    now = datetime.now(timezone.utc)
    if tag:
        cands = [a for a in arms(data_folder) if a["tag"] == tag]
        if not cands:
            raise SystemExit(f"no ledger-bearing gold arm with tag {tag!r} "
                             f"(check the chart is attached and the EA initialized)")
        arm_list = cands
    else:
        arm_list = arms(data_folder)
        if not arm_list:
            raise SystemExit("no gold-arm ledgers found on the terminal "
                             "(nothing has initialized; nothing to judge)")
    out: dict = {"read_at": now.isoformat(timespec="seconds"),
                 "gates": dict(GATES), "doc": PROTOCOL_DOC, "arms": {}}
    for a in arm_list:
        reading = adjudicate(a["tag"], a["ledger"], a["chart"])
        out["arms"][a["tag"]] = reading
        _print_row(reading)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="MIDASTOUCH §13 monthly forward verdict")
    ap.add_argument("--tag", default=None,
                    help="one arm (default: every ledger-bearing arm)")
    ap.add_argument("--json", action="store_true",
                    help="print the full evidence record as JSON")
    args = ap.parse_args()
    out = run(tag=args.tag)
    if args.json:
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
