"""Pre-flight and aftercare for the MetaTrader built-in VPS migration of the arm.

WHY THIS EXISTS (measured 2026-09-23, local journal 12:32:38Z, subscription 6911490):

    6911490: prepare charts to synchronize...
    6911490: 0 charts of 1 prepared to synchronize
    6911490: nothing to synchronize, no any EA or custom indicator, signal for
             '1428765' is not enabled
    6911490: migrate start.ini (716 bytes) -> migration processed

The operator clicked Migrate with the EA running, and the VPS received NOTHING: the
arm's EA chart exists only as a startup-INI attachment (midas_attach.ini) inside the
running process — no saved profile carries it (verified: zero MidastouchAI references
in any .chr under this terminal's Profiles tree), because every sanctioned restart is
`taskkill /F` + attach-INI, and a forced exit never saves a profile. MT5's migration
snapshots the saved/active environment and IGNORES charts without EAs (metatrader5.com,
Virtual Hosting → Migration: "charts without Expert Advisors are ignored"), so it
synced an empty start.ini. The VPS then idled at "0 charts, 0 EAs" all day while the
laptop traded — and when the laptop hibernated (15:28-18:35Z), nothing covered the gap
the VPS was rented to cover.

THE TWO PLANS
    paper-rehearsal : migrate a SECOND chart carrying the PAPER preset with tag VPS.
                      Proves the environment end-to-end (the exact thing that failed)
                      while the laptop EA stays the only live trader. Zero risk: the
                      rehearsed EA has InpLiveExecution=false and its own tag, so it
                      cannot touch the book and writes its own ledger name.
    full-cutover    : migrate the LIVE EA chart itself (the armed record's own preset).
                      MT5 then disables local algo trading BY DESIGN ("When you
                      transfer Expert Advisors, the automated trading function is
                      automatically disabled in the local platform") — the built-in
                      double-execution guard. From that moment the VPS EA is the
                      trader and the laptop is the supervisor; the local LV ledger
                      goes stale EXPECTEDLY (the 2026-09-18 era precedent) because the
                      VPS copy writes to the VPS's own Files. Requires a flat book.

THE DOUBLE-EXECUTION GUARD (what makes either plan safe)
    * MT5's own guard: a successful EA migration locks local algo trading — both
      platforms can never trade the account at once. The guard is verified in
      verify-after by finding its journal line; if it did NOT fire on a full cutover,
      verify-after FAILS and the operator must stop one side manually.
    * The startup-INI conflict, checked by preflight: once the profile carries a LIVE
      EA, a local attach-INI boot would open a SECOND live EA alongside it. For
      full-cutover this is a blocker with the exact fix printed; the era marker then
      makes the local watchdog hands-off (midas_watchdog.vps_hosting_active).

This tool places no orders and arms nothing: migration is clicked by the operator in
the VPS tab; this tool only refuses unsafe moments, verifies what actually happened,
and records the era.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import morning_status as ms  # TERM_ROOT, preset_identity

ART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "artifacts")
ERA_MARKER = os.path.join(ART, "midas_vps_hosting.json")   # same path the watchdog reads
ERA_ARCHIVE = os.path.join(ART, "archive", "vps_eras")
ARMED_PATH = os.path.join(ART, "live", "armed.json")

#: journal signatures, 2026-09-23 measured. The first is the FAILURE this tool exists
#: to prevent; the second is MT5's local algo lock (the double-execution guard firing),
#: in the wording the 2026-09-18 era journal actually used ("automated trading disabled
#: after migration and enabled on virtual hosting").
JOURNAL_SYNCED_NONE = "nothing to synchronize, no any EA or custom indicator"
JOURNAL_MIGRATION_DONE = "migration processed"
JOURNAL_LOCAL_LOCK = "automated trading disabled"

PLAN_PAPER = "paper-rehearsal"
PLAN_FULL = "full-cutover"
PLANS = (PLAN_PAPER, PLAN_FULL)


# --- inputs the checks read ----------------------------------------------------------

def _terminal_root() -> str:
    return ms.TERM_ROOT


def active_profile(term_root: str | None = None) -> str | None:
    """The profile MT5 reopens and the migration snapshots (common.ini ProfileLast)."""
    term_root = term_root or _terminal_root()
    ini = os.path.join(term_root, "config", "common.ini")
    if not os.path.exists(ini):
        return None
    txt = open(ini, encoding="utf-16", errors="replace").read()
    m = re.search(r"^ProfileLast=(.+?)\s*$", txt, re.M)
    return m.group(1) if m else None


def carrier_chart(term_root: str | None = None) -> tuple[str, str] | None:
    """(path, text) of the saved chart that would carry the EA, or None.

    Charts without EAs are ignored by migration (measured: "0 charts of 1"), so the
    carrier must be a PROFILE-SAVED .chr containing the EA — not the startup-INI chart.
    """
    term_root = term_root or _terminal_root()
    profile = active_profile(term_root)
    if not profile:
        return None
    pdir = os.path.join(term_root, "MQL5", "Profiles", "Charts", profile)
    if not os.path.isdir(pdir):
        return None
    for name in sorted(os.listdir(pdir)):
        if not name.endswith(".chr"):
            continue
        p = os.path.join(pdir, name)
        try:
            txt = open(p, encoding="utf-16", errors="replace").read()
        except OSError:
            continue
        if "MidastouchAI" in txt:
            return p, txt
    return None


def _inp_value(txt: str, key: str) -> str | None:
    """The value of an input line, ignoring comments — the .set/.chr files carry
    comment lines that mention keys by name, and a substring check would read those."""
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith(";") or not s.startswith(key + "="):
            continue
        return s.split("=", 1)[1].strip()
    return None


def attach_ini_chart_spawns_ea() -> bool:
    """True when midas_attach.ini would spawn a second EA chart on the next boot."""
    ini = os.path.join(_terminal_root(), "Config", "midas_attach.ini")
    if not os.path.exists(ini):
        return False
    txt = open(ini, encoding="utf-8", errors="replace").read()
    return bool(re.search(r"^\s*Expert\s*=\s*\S", txt, re.M))


def venue_positions() -> list | None:
    """Open positions on the account, or None when the venue cannot be asked."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    try:
        return list(mt5.positions_get() or [])
    finally:
        mt5.shutdown()


def journal_text(day: str | None = None, term_root: str | None = None) -> str:
    """The terminal journal (utf-16) for a UTC day, or '' when absent."""
    term_root = term_root or _terminal_root()
    day = day or datetime.now(timezone.utc).strftime("%Y%m%d")
    p = os.path.join(term_root, "logs", f"{day}.log")
    if not os.path.exists(p):
        return ""
    return open(p, encoding="utf-16", errors="replace").read()


# --- the preflight -------------------------------------------------------------------

def preflight(plan: str, *, positions: list | None = None,
              term_root: str | None = None,
              carrier: tuple[str, str] | None = None,
              attach_ini_spawns: bool | None = None) -> tuple[bool, list[str]]:
    """Refuse the unsafe moments. Returns (ok, lines); ok is False only on a BLOCKER.

    Fail-closed: an askable-but-unasked check (venue unreachable, no arming record)
    blocks the plan rather than passing by default.
    """
    lines: list[str] = [f"plan: {plan}"]
    ok = True

    # 1. The carrier chart. Without it the migration ships nothing — today's failure.
    carrier = carrier or carrier_chart(term_root)
    if carrier is None:
        ok = False
        lines.append("BLOCKER: no profile-saved chart carries MidastouchAI. MT5 migrates "
                     "saved/active charts WITH EAs only ('0 charts of 1 prepared' is the "
                     "signature of this exact failure). Fix: open the EA chart, then "
                     "File -> Profiles -> Save (the profile that opens at boot), and "
                     "re-run this preflight.")
    else:
        path, txt = carrier
        lines.append(f"carrier chart: {path}")

    # 2. The carrier's preset must be the plan's pin, byte for byte.
    if carrier is not None:
        from midas_watchdog import preset_for_tag
        # Each plan has its own pin: the cutover carries the ARMED record's LIVE preset;
        # the rehearsal carries the dedicated VPS rehearsal pin (the paper preset with
        # only InpArmTag=VPS changed — mql5/MIDASTOUCH/MidastouchAI_VPS_gold.set, the
        # name the <tag>_gold convention resolves), because preset_for_tag resolves a
        # tag to its OWN .set, so the byte-identity check and the tag requirement must
        # name the same file.
        tag = "U25" if plan == PLAN_FULL else "VPS"
        want = preset_for_tag(tag, armed=(plan == PLAN_FULL))
        r = ms.preset_identity(carrier[1], preset_path=want)
        if r["verdict"] != "OK":
            ok = False
            lines.append(f"BLOCKER: carrier chart inputs are not byte-identical to the "
                         f"plan's pin {os.path.basename(want)}: {r['verdict']} "
                         f"drift={r['drift']} missing={r['missing']} extra={r['extra']}")
        else:
            lines.append(f"carrier inputs: byte-identical to {os.path.basename(want)} "
                         f"({r['n_keys']} inputs)")
        exec_flag = _inp_value(carrier[1], "InpLiveExecution")
        if plan == PLAN_FULL and exec_flag != "true":
            ok = False
            lines.append("BLOCKER: full-cutover carrier does not say InpLiveExecution=true")
        if plan == PLAN_PAPER:
            if exec_flag != "false":
                ok = False
                lines.append("BLOCKER: rehearsal carrier must be the PAPER preset "
                             "(InpLiveExecution=false) — the laptop EA stays the only "
                             "live trader in this plan")
            if not re.search(r"^InpArmTag=VPS\s*$", carrier[1], re.M):
                ok = False
                lines.append("BLOCKER: rehearsal carrier must run tag VPS (InpArmTag=VPS) "
                             "so its rows land in their own ledger, not the live arm's")

    # 3. The arming record must be the authority for a LIVE handover.
    if plan == PLAN_FULL:
        if not os.path.exists(ARMED_PATH):
            ok = False
            lines.append("BLOCKER: no arming record — a live handover without the record "
                         "naming the preset is the exact bug the hard rules forbid")
        else:
            rec = json.load(open(ARMED_PATH, encoding="utf-8"))
            lines.append(f"arming record: {rec.get('summary', '?')[:80]}")

    # 4. Startup-INI conflict: a boot that spawns a second live EA next to the profile EA.
    spawns = attach_ini_chart_spawns_ea() if attach_ini_spawns is None else attach_ini_spawns
    if plan == PLAN_FULL and spawns:
        ok = False
        ini = os.path.join(_terminal_root(), "Config", "midas_attach.ini")
        lines.append(f"BLOCKER: {ini} still spawns the EA at boot — after a full cutover "
                     f"the profile EA and the startup EA would be a second live EA pair "
                     f"trading one account locally. Fix in the same session as the "
                     f"migration: move the ini aside (rename to midas_attach.ini.vps-era) "
                     f"and boot the terminal plain; restore it when the era ends.")

    # 5. The book. Full cutover needs flat (no position straddles the handover);
    #    rehearsal may run with a position (the laptop EA keeps managing it).
    pos = venue_positions() if positions is None else positions
    if pos is None:
        ok = False
        lines.append("BLOCKER: cannot ask the venue for open positions (MT5 python bridge "
                     "unavailable) — refusing to judge the handover blind")
    elif plan == PLAN_FULL and pos:
        ok = False
        lines.append(f"BLOCKER: the book is not flat ({len(pos)} open position(s)) — a "
                     f"position straddling the cutover changes managers mid-flight. "
                     f"Cut over after SL/TP/timeout has flattened it.")
    elif pos:
        lines.append(f"book: {len(pos)} open position(s) — allowed for {plan}: the laptop "
                     f"EA keeps managing them")
    else:
        lines.append("book: flat")

    lines.append("PREFLIGHT " + ("PASS" if ok else "FAIL"))
    return ok, lines


# --- the aftercare -------------------------------------------------------------------

def verify_after(day: str | None = None, plan: str = PLAN_FULL) -> tuple[bool, list[str]]:
    """Read the LOCAL journal and say what the sync actually moved. Fail-closed."""
    lines: list[str] = []
    txt = journal_text(day)
    if not txt:
        return False, [f"BLOCKER: no terminal journal for {day or 'today'} — nothing to verify"]
    ok = True

    if JOURNAL_SYNCED_NONE in txt:
        ok = False
        lines.append("FAIL: the journal contains 'nothing to synchronize, no any EA' — "
                     "the empty-migration failure happened again; the carrier chart was "
                     "not saved before the click")
    prepared = re.findall(r"(\d+) charts of 1 prepared to synchronize", txt)
    if prepared:
        n = max(int(x) for x in prepared)
        lines.append(f"charts prepared to synchronize: {n} of 1")
        if n < 1:
            ok = False
            lines.append("FAIL: the EA chart was not among the prepared charts")
    else:
        lines.append("no chart-preparation line found (was Migrate clicked?)")
        ok = False
    if JOURNAL_MIGRATION_DONE in txt:
        lines.append("migration processed: yes")
    else:
        lines.append("migration processed: NOT found")
        ok = False

    # The double-execution guard: on a full cutover MT5 MUST have locked local algo.
    guard = JOURNAL_LOCAL_LOCK in txt.lower()
    if plan == PLAN_FULL:
        if guard:
            lines.append("local algo lock (MT5's double-execution guard): FIRED — "
                         "the VPS side is now the trader; mark the era")
        else:
            lines.append("FAIL: no 'automated trading disabled' line — MT5's "
                         "double-execution guard did not fire; a live EA may exist on "
                         "BOTH sides. Stop one side manually before trading continues.")
            ok = False
    else:
        lines.append(f"local algo lock: {'fired (unexpected for a rehearsal — inspect)' if guard else 'not fired (correct: the laptop EA stays live)'}")

    lines.append("VERIFY " + ("PASS" if ok else "FAIL"))
    return ok, lines


# --- the era marker (the watchdog's and morning report's only hosting source) --------

def mark_era(subscription: str, vps: str, plan: str, why: str) -> str:
    rec = {"subscription": subscription, "vps": vps, "plan": plan,
           "marked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "why": why,
           "local_lv_ledger_expected": "stale — the VPS copy writes to the VPS's own Files",
           "set_by": "scripts/midas_vps_migration.py (operator command)"}
    with open(ERA_MARKER, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    return ERA_MARKER


def clear_era() -> str:
    if not os.path.exists(ERA_MARKER):
        return "no era marker present"
    os.makedirs(ERA_ARCHIVE, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = os.path.join(ERA_ARCHIVE, f"midas_vps_hosting_{stamp}.json")
    os.replace(ERA_MARKER, dst)
    return f"era marker archived to {dst}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("preflight", "verify-after", "mark-era", "clear-era"))
    ap.add_argument("--plan", choices=PLANS, default=PLAN_FULL)
    ap.add_argument("--day", help="journal day YYYYMMDD for verify-after (default today UTC)")
    ap.add_argument("--subscription", default="6911490")
    ap.add_argument("--vps", default="VPS Germany 01")
    ap.add_argument("--why", default="operator migration window")
    a = ap.parse_args()

    if a.command == "preflight":
        ok, lines = preflight(a.plan)
    elif a.command == "verify-after":
        ok, lines = verify_after(a.day, a.plan)
    elif a.command == "mark-era":
        print(mark_era(a.subscription, a.vps, a.plan, a.why))
        return 0
    else:
        print(clear_era())
        return 0
    for ln in lines:
        print(ln)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
