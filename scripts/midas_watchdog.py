"""MIDASTOUCH gold-arm watchdog — the ledger's mtime IS the liveness signal.

WHY. The MidastouchAI EA (v1.07+) touches its paper ledger with an EQ row
every 900 s (OnTimer heartbeat), in every terminal state where the process is
alive — market open, daily break, weekend. That makes the ledger's mtime the
one number that answers "is the gold arm actually running?" A ledger older
than ~2 heartbeats means one of: terminal process dead, terminal hung, or the
loaded-but-dead EA signature (init banner, no processing) that froze the V75
arms on 2026-09-13/14. The M1 arm has no other monitor and no scheduled
tasks (all disabled at the 2026-09-16 closeout), so nothing else would ever
notice. This watchdog closes that hole.

ACTION, in order (each step only when the previous one is exhausted):
  1. WAIT        — ledger age within STALE_MIN + GRACE_MIN (one missed
                   heartbeat + poll headroom is normal, never an incident).
  2. RESTUP      — stop (PID-exact) and relaunch the gold terminal, but ONLY
                   after the flat check passes: zero OPEN rows without a CLOSE
                   (the EA would restore nothing), ledger readable, at least
                   one recognizable row. This is v28_sweep_runner's ledger
                   discipline verbatim — never hard-stop a book we cannot
                   prove is flat. An open paper position with a stale ledger
                   is reported, not restarted (force --force to override).
  3. ESCALATE    — after MAX_RESTUPS consecutive stale-triggered restups
                   without an observed recovery, stop restarting (a restart
                   loop cannot fix a broken EA build or a bad chart) and say
                   so loudly. morning_status [3b] surfaces this as a PROBLEM.
  4. DRIFT       — independent of staleness: the terminal journal's LATEST
                   init banner is compared against the repo preset pins
                   (mode / session / execution / exec-model). A mismatch —
                   e.g. the EA re-attached with code defaults (found live
                   2026-09-17 11:11: mode=1, $1000 basis, 25 min after the
                   pinned restore) — is remediated by the same flat-checked
                   restart, with the pins re-spliced into the chart BEFORE
                   relaunch (a defaults-running instance would clobber the
                   chart with defaults on graceful exit; taskkill /F does not
                   let it). execution=LIVE in the banner is drift by
                   definition — the paper arm must never run live. Shares
                   the escalation counter so a serial re-attacher cannot
                   turn into a restart war.

GUARDS:
  * Weekend (local Sat/Sun) with a flat book: a dead EA over a closed market
    misses nothing — reported as WAIT-WEEKEND, no restart (policy, not
    laziness; --force overrides).
  * PAUSE marker (scripts/.midas_watchdog_paused): parity/tester sessions run
    on the SAME terminal install (midas_parity.py stop/starts it). A watchdog
    restart mid-parity would wreck the pass. While the marker exists the
    watchdog only observes: `--pause` / `--resume`.

USAGE:
    python scripts/midas_watchdog.py                # one check + act
    python scripts/midas_watchdog.py --loop 600     # every 10 min (the .bat)
    python scripts/midas_watchdog.py --dry-run      # report, never act
    python scripts/midas_watchdog.py --status       # state summary, read-only
    python scripts/midas_watchdog.py --pause|--resume|--reset-state

State/artifacts: artifacts/midas_watchdog_state.json (counters),
artifacts/midas_watchdog_last_action.json (last full record). morning_status
section [3b] reads the state file for its watchdog line.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from mt5_ops import (  # noqa: E402  (the LIVE install, by account identity)
    MT5OpsUnavailable, data_folder_for_terminal, relaunch_terminal, stop_terminal,
    terminal_exe_or_unknown, terminal_pids_exact)


def _live_pids() -> list[int] | None:
    """PIDs of the live terminal, or None when its identity cannot be resolved.

    None is deliberately NOT the same as []: [] means "resolved, and it is not
    running", which authorises a relaunch. None means we do not know which install we
    would be acting on, and acting anyway is how a stop lands on the wrong terminal.
    """
    try:
        return terminal_pids_exact()
    except MT5OpsUnavailable:
        return None

REPO_PRESET = os.path.join(REPO, "mql5", "MIDASTOUCH", "MidastouchAI_M1_gold.set")
#: kept for callers that want the frozen baseline by name rather than by tag


def preset_for_tag(tag: str) -> str:
    """The pinned preset for an arm tag (§14 portfolio).

    Resolved by the tag the ARM reports, read out of the presets themselves. The
    file name is not the tag: the account's arm carries `InpArmTag=U25` while its
    file is `MidastouchAI_upcomers_gold.set`, so a name-only lookup failed to pin the
    one arm that matters here — the chart tag was derived from the EA, the preset
    was looked up as a filename, and the two silently disagreed.

    Falls back to the MidastouchAI_<tag>_gold.set convention, which is how the
    legacy M1 arm is named. Missing file -> the caller observes without pin
    enforcement (§12 rule).
    """
    preset_dir = os.path.join(REPO, "mql5", "MIDASTOUCH")
    try:
        names = sorted(os.listdir(preset_dir))
    except OSError:
        names = []
    for name in names:
        if not (name.startswith("MidastouchAI_") and name.endswith("_gold.set")):
            continue
        path = os.path.join(preset_dir, name)
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("InpArmTag=") and s.split("=", 1)[1].strip() == tag:
                        return path
        except OSError:
            continue
    return os.path.join(preset_dir, f"MidastouchAI_{tag}_gold.set")

ART = os.path.join(REPO, "artifacts")
STATE_PATH = os.path.join(ART, "midas_watchdog_state.json")
LAST_PATH = os.path.join(ART, "midas_watchdog_last_action.json")
PAUSE_MARKER = os.path.join(REPO, "scripts", ".midas_watchdog_paused")
INSTANCE_LOCK = os.path.join(ART, "midas_watchdog.lock")
VPS_HOSTING_MARKER = os.path.join(ART, "midas_vps_hosting.json")

STALE_MIN = 35        # > 2 heartbeats (EA OnTimer = 15 min) = stale
GRACE_MIN = 10        # extra headroom beyond STALE_MIN before acting
MAX_RESTUPS = 3       # consecutive restups without observed recovery -> escalate
WEEKEND_DAYS = (5, 6)  # local-time Sat/Sun: closed market, flat book -> no restart
NEW_STATE: dict = {"consecutive_restups": 0, "restups_total": 0,
                   "last_restup_ts": None, "last_ok_ts": None}


# --- single-instance guard (the supervisor must never be two) --------------------

def acquire_instance_lock() -> int | None:
    """Exclusive lock on artifacts/midas_watchdog.lock for the --loop life.

    WHY. Reboot-survival via the MIDAS logon task (or any future autostart)
    means there is more than one way a watchdog gets started, and a second
    concurrent loop would double every decision: two terminals stopped and
    relaunched against one another, interleaved state writes. The lock is
    held on an OS handle, so a crashed watchdog releases it automatically —
    there is no stale lock to clean, ever. Returns the fd, or None when
    another loop already supervises (the caller exits loudly). One-shot
    commands (single check, --dry-run, --status, --pause/--resume) never
    take the lock: they must stay usable while a loop runs.
    """
    os.makedirs(ART, exist_ok=True)
    fd: int | None = None
    try:
        fd = os.open(INSTANCE_LOCK, os.O_CREAT | os.O_RDWR)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)   # byte 0, non-blocking
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        os.write(fd, str(os.getpid()).encode())
        return fd
    except OSError:
        if fd is not None:
            os.close(fd)
        return None


def release_instance_lock(fd: int) -> None:
    """Unlock + close (best effort — process exit releases it anyway)."""
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


# --- discovery ----------------------------------------------------------------

def midas_arms(data_folder: str | None) -> list[dict]:
    """All gold arms on the terminal (§14 portfolio): every chart .chr
    mentioning MidastouchAI -> its own ledger path
    MIDASTOUCH_paper_<sym>_<tag>.csv. Discovery is tag-driven, so adding an
    arm to the portfolio needs no tooling change."""
    if not data_folder:
        return []
    out = []
    for chr_f in sorted(glob.glob(os.path.join(data_folder, "MQL5", "Profiles",
                                               "Charts", "*", "*.chr"))):
        try:
            txt = open(chr_f, encoding="utf-16", errors="replace").read()
        except OSError:
            continue
        if "MidastouchAI" not in txt:
            continue
        sym_m = re.search(r"^symbol=(\S+)", txt, re.M)
        tag_m = re.search(r"^InpArmTag=(\S*)\s*$", txt, re.M)
        sym = sym_m.group(1) if sym_m else ""
        tag = (tag_m.group(1) if tag_m else "") or "M1"
        out.append({"chart": chr_f,
                    "symbol": sym,
                    "tag": tag,
                    "ledger": os.path.join(data_folder, "MQL5", "Files",
                                           f"MIDASTOUCH_paper_{sym}_{tag}.csv")})
    return out


def midas_arm(data_folder: str | None) -> dict | None:
    """Single-arm discovery (§13-era, kept for compatibility and tests):
    the first MidastouchAI chart found."""
    if not data_folder:
        return None
    for chr_f in sorted(glob.glob(os.path.join(data_folder, "MQL5", "Profiles",
                                               "Charts", "*", "*.chr"))):
        try:
            txt = open(chr_f, encoding="utf-16", errors="replace").read()
        except OSError:
            continue
        if "MidastouchAI" not in txt:
            continue
        sym_m = re.search(r"^symbol=(\S+)", txt, re.M)
        tag_m = re.search(r"^InpArmTag=(\S*)\s*$", txt, re.M)
        sym = sym_m.group(1) if sym_m else ""
        tag = (tag_m.group(1) if tag_m else "") or "M1"
        return {"chart": chr_f,
                "symbol": sym,
                "tag": tag,
                "ledger": os.path.join(data_folder, "MQL5", "Files",
                                       f"MIDASTOUCH_paper_{sym}_{tag}.csv")}
    return None


def ledger_health(ledger: str, now_s: float) -> dict:
    """mtime age + flatness + row sanity in one read.

    Flat = zero OPEN rows without a CLOSE (the EA's own restore rule: a
    dangling OPEN would be adopted as a live virtual position on the next
    init, so a restart while "open" would freeze mid-trade bookkeeping).
    A ledger with no recognizable row at all is a problem, never silently
    "flat" — the same fail-closed rule v28_sweep_runner applies to research.
    """
    res: dict = {"exists": False, "mtime_age_min": None, "flat": False,
                 "open_positions": [], "problems": [], "closed": 0, "eras": 0}
    try:
        mtime = os.path.getmtime(ledger)
    except OSError as e:
        res["problems"].append(f"ledger missing/unreadable: {e}")
        return res
    res["exists"] = True
    res["mtime_age_min"] = round((now_s - mtime) / 60.0, 1)
    opens: dict[str, int] = {}
    try:
        with open(ledger, encoding="utf-8", errors="replace") as f:
            for ln, line in enumerate(f, 1):
                parts = line.strip().split(",")
                if not parts or not parts[0]:
                    continue
                if parts[0] == "OPEN" and len(parts) >= 12:
                    opens[parts[2]] = ln
                elif parts[0] == "CLOSE" and len(parts) >= 8:
                    opens.pop(parts[2], None)
                    res["closed"] += 1
                elif parts[0] == "LOPEN" and len(parts) >= 14:
                    # 2026-09-18 go-live: the LIVE path appends LOPEN/LCLOSE
                    # rows (LCLOSE[2] is the posid, matching LOPEN[2]). A
                    # dangling LOPEN is a LIVE REAL-MONEY position — exactly
                    # what the flat gate exists to protect. 14 fields per the
                    # EA v1.16 writer (epoch,posid,order,deal,dir,...); keyed
                    # on [2] = posid. Pinned to the MQ5 format string by
                    # tests/test_midas_golive_grammar.py.
                    opens[parts[2]] = ln
                elif parts[0] == "LCLOSE" and len(parts) >= 6:
                    opens.pop(parts[2], None)
                    res["closed"] += 1
                elif parts[0] == "ERA":
                    res["eras"] += 1
    except OSError as e:
        res["problems"].append(f"unreadable mid-scan: {e}")
        return res
    res["open_positions"] = [{"ticket": t, "line": n} for t, n in opens.items()]
    # Fail closed on a file that carries no recognizable ledger row at all:
    # a real paper book always has an era stamp, a trade, or both (v1.09+ even
    # touches EQ on every init/heartbeat). A file with nothing recognizable is
    # either not a ledger or not yet initialized — never treat an unverifiable
    # book as flat: it must not pass the restart gate.
    if res["closed"] == 0 and res["eras"] == 0 and not opens:
        res["problems"].append("no recognizable ledger rows (ERA/OPEN/CLOSE/LOPEN/LCLOSE)")
        return res
    res["flat"] = not opens
    return res


# --- config drift (banner vs pinned preset) -------------------------------------

def _parse_preset_pins(path: str = REPO_PRESET) -> dict:
    """The pins an arm must run under, from its repo preset (single source)."""
    import set_chart_preset as scp
    vals = scp.parse_preset(path)
    return {
        "mode": int(vals.get("InpMode", "0")),
        "session": (int(vals.get("InpSessionStartHour", "6")),
                    int(vals.get("InpSessionEndHour", "20"))),
        "execution": "LIVE" if vals.get("InpLiveExecution", "false").lower() == "true" else "PAPER",
        "exec_model": "BAR" if vals.get("InpBarModel", "false").lower() == "true" else "PERTICK",
    }


def recent_banners(data_folder: str | None) -> list[str]:
    """Every 'MIDASTOUCH started' banner in the newest journal that has one.

    §14 hardening (2026-09-18): banners are OBSERVATION ONLY. Five charts
    print identical `mode=… | session=…` text with no arm tag, so banner
    matching cannot attribute a boot to an arm and cannot manufacture drift
    (the 09:05 phantom storm: the LV matcher grabbed a paper arm's PAPER
    banner). Config identity is adjudicated exclusively by the chart's
    <inputs> block — the same source morning status [3b] byte-verifies.
    This reader is kept for diagnostics and tests; the check() decision
    path never calls it.
    """
    if not data_folder:
        return []
    logs = sorted(glob.glob(os.path.join(data_folder, "MQL5", "Logs", "*.log")),
                  key=os.path.getmtime)
    for lp in reversed(logs):
        try:
            raw = open(lp, "rb").read()
        except OSError:
            continue
        text = raw.decode("utf-16-le", errors="replace") if raw[:2] in (b"\xff\xfe",) \
            else raw.decode("utf-16", errors="replace") if raw[:2] in (b"\xfe\xff",) \
            else raw.decode("utf-8", errors="replace")
        banners = [ln for ln in text.splitlines() if "MIDASTOUCH started |" in ln]
        if banners:
            return banners
    return []


# banners_for_pins/banner_drift were REMOVED (2026-09-18 §14 hardening):
# banner-text matching could not attribute a boot among five identically-
# labelled charts and manufactured the 09:05 phantom ESCALATE. The chart
# file is the identity source; midas_verdict.py stays the only version
# consumer (§1 law): version transitions are adjudicated exclusively by
# its telemetry-only-per-V2-register exemption walk — never here.


def latest_banner(data_folder: str | None) -> str | None:
    """The newest single banner (diagnostics; NOT in the decision path)."""
    b = recent_banners(data_folder)
    return b[-1] if b else None


def resplice_pins(arm: dict, pins_src: str | None = None) -> str | None:
    """Re-splice the arm's repo preset into its chart (terminal must be DOWN).

    Uses set_chart_preset's own parser/writer (the certified splice), with a
    timestamped backup and a re-parse verify. Returns the backup path or None.
    The preset is the ARM's own (§14: preset_for_tag), not a shared file.
    """
    import set_chart_preset as scp
    vals = scp.parse_preset(pins_src or preset_for_tag(arm["tag"]))
    if not vals:
        return None
    cpath = arm["chart"]
    if not os.path.exists(cpath):
        return None
    txt = scp.read_chr(cpath)
    m = re.search(r"<inputs>([\s\S]*?)</inputs>", txt)
    if not m:
        return None
    bak = f"{cpath}.bak_watchdog_{datetime.now():%Y%m%d_%H%M%S}"
    open(bak, "wb").write(open(cpath, "rb").read())
    new_block = "<inputs>\n" + "".join(f"{k}={v}\n" for k, v in vals.items()) + "</inputs>"
    scp.write_chr(cpath, txt[:m.start()] + new_block + txt[m.end():])
    back = scp.read_chr(cpath)
    mb = re.search(r"<inputs>([\s\S]*?)</inputs>", back)
    got = dict(l.split("=", 1) for l in mb.group(1).splitlines() if "=" in l) if mb else {}
    if any(got.get(k, "").strip() != v for k, v in vals.items()):
        open(cpath, "wb").write(open(bak, "rb").read())  # restore on verify fail
        return None
    return bak


# --- decision (pure; tests pin this) -------------------------------------------

def decide(h: dict, state: dict, now_s: float, force: bool = False) -> tuple[str, list[str], dict]:
    """The whole policy in one function. Returns (action, problems, new_state).

    Actions: NONE (fresh/recovered), WAIT (inside grace), WAIT-WEEKEND,
    RESTUP, ESCALATE, SKIP-OPEN-POSITION, PAUSED is handled by the caller.
    """
    problems = list(h["problems"])
    new_state = dict(state)
    if not h["exists"] or problems:
        # Missing or malformed book: a restart cannot fix either (an EA that
        # cannot init writes nothing) — surface, never loop.
        if not h["exists"]:
            problems.append("no ledger — arm never initialized; run morning "
                            "status and fix the chart, do not restart blindly")
        return "NONE", problems, new_state

    age = h["mtime_age_min"] or 0.0
    if age <= STALE_MIN:
        # Fresh: an observed heartbeat is also the recovery signal — a clean
        # poll after restups proves the restart fixed it, so the escalation
        # counter resets here and only here.
        if new_state.get("consecutive_restups", 0) > 0:
            new_state["consecutive_restups"] = 0
            problems.append(f"RECOVERED after {new_state.get('restups_total', 0)} "
                            "lifetime restup(s) — counter reset")
        new_state["last_ok_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return "NONE", problems, new_state

    if age <= STALE_MIN + GRACE_MIN:
        return "WAIT", problems, new_state

    is_weekend = datetime.fromtimestamp(now_s).weekday() in WEEKEND_DAYS
    if is_weekend and h["flat"] and not force:
        return "WAIT-WEEKEND", problems, new_state

    if not h["flat"] and not force:
        problems.append("open paper position with a stale ledger — restart "
                        "would freeze mid-trade bookkeeping; investigate, or "
                        "override with --force after verifying the book")
        return "SKIP-OPEN-POSITION", problems, new_state

    if new_state.get("consecutive_restups", 0) >= MAX_RESTUPS:
        problems.append(f"stale beyond {STALE_MIN + GRACE_MIN} min after "
                        f"{new_state['consecutive_restups']} consecutive "
                        "restups without recovery — restarting cannot fix "
                        "this; inspect the EA journal/build, then "
                        "`--reset-state` once resolved")
        return "ESCALATE", problems, new_state

    new_state["consecutive_restups"] = new_state.get("consecutive_restups", 0) + 1
    new_state["restups_total"] = new_state.get("restups_total", 0) + 1
    new_state["last_restup_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return "RESTUP", problems, new_state


# --- state + records ------------------------------------------------------------

def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            s = json.load(f)
        return {**NEW_STATE, **s}
    except (OSError, ValueError):
        return dict(NEW_STATE)


def save_state(s: dict) -> None:
    os.makedirs(ART, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)


def save_record(record: dict) -> None:
    os.makedirs(ART, exist_ok=True)
    with open(LAST_PATH, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)


def watchdog_summary() -> tuple[str, bool]:
    """One line for morning_status [3b]: (text, unhealthy)."""
    if not os.path.exists(STATE_PATH):
        return ("no watchdog state yet (never run) — start it: "
                "python scripts/midas_watchdog.py --loop 600 (or start_midas_watchdog.bat)", False)
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return "watchdog state unreadable", True
    restups = s.get("consecutive_restups", 0)
    line = f"{restups} consecutive restup(s), {s.get('restups_total', 0)} lifetime"
    if s.get("last_restup_ts"):
        line += f", last restup {s['last_restup_ts']}"
    elif s.get("last_ok_ts"):
        line += f", last fresh ledger {s['last_ok_ts']}"
    return line, restups >= MAX_RESTUPS


# --- the check -------------------------------------------------------------------

def vps_hosting_active() -> bool:
    """Is the MT5 Virtual-Hosting era active (operator-managed marker)?

    2026-09-18 12:46 journal: 'automated trading disabled after migration
    and enabled on virtual hosting' — while hosting is active MT5 locks
    LOCAL algo trading off by design (local EA + VPS EA would both trade
    the same hedging account), and after the operator's sync the LV ledger
    stops advancing (the VPS copy writes to the VPS's own Files). Local
    restart remediation is meaningless in this era: the terminal is
    healthy, the surface moved. The operator sets/clears
    artifacts/midas_vps_hosting.json around migration windows — the only
    honest source, since MT5 exposes no API for hosting state.
    """
    return os.path.exists(VPS_HOSTING_MARKER)


def check(now_s: float | None = None, dry_run: bool = False,
          force: bool = False) -> dict:
    """One portfolio poll (§14). Per-arm liveness + per-arm drift with ONE
    portfolio-wide remediation: all arms share the terminal, so (a) any
    remediation is a stop of everyone — gated on the flatness of EVERY
    ledger, and (b) each arm's pinned boot is attributed by matching its
    own mode/session pins against the journal's newest banner for that
    mode. Counter semantics unchanged (one shared escalation counter;
    §14 keeps the policy — an arm that keeps breaking the book escalates
    the terminal)."""
    now_s = time.time() if now_s is None else now_s
    record: dict = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "terminal_exe": terminal_exe_or_unknown()}
    state = load_state()

    if os.path.exists(PAUSE_MARKER):
        record["action"] = "PAUSED"
        record["problem"] = "pause marker present (parity/tester session?) — observing only"
        print(json.dumps(record))
        save_record(record)
        return record

    if vps_hosting_active():
        record["action"] = "VPS-HOSTING"
        record["problem"] = ("VPS hosting active (operator marker) — local algo is "
                             "MT5-locked and the LV surface lives on the VPS after "
                             "the operator's sync; observing only, no local "
                             "remediation (paper arms still collect locally)")
        print(json.dumps(record))
        save_record(record)
        return record

    df = data_folder_for_terminal()
    arms = midas_arms(df)
    if not arms:
        record["action"] = "NONE"
        record["problem"] = (f"no MidastouchAI chart found on the gold terminal "
                             f"({terminal_exe_or_unknown()}) — is the arm attached?")
        print(json.dumps(record))
        save_record(record)
        return record

    record["arms"] = [{"symbol": a["symbol"], "tag": a["tag"],
                       "ledger": os.path.basename(a["ledger"])} for a in arms]

    # --- portfolio-wide ledger health (drives the shared restart policy) ---
    ledgers = []
    for a in arms:
        lh = ledger_health(a["ledger"], now_s)
        ledgers.append({**lh, "tag": a["tag"]})
        if lh["problems"]:
            record.setdefault("ledger_problems", {})[a["tag"]] = lh["problems"]
    worst = max((l["mtime_age_min"] or 0.0) for l in ledgers)
    record["ledgers"] = [{k: l[k] for k in ("tag", "exists", "mtime_age_min", "flat")}
                         for l in ledgers]
    live_pids = _live_pids()
    record["terminal_running"] = None if live_pids is None else bool(live_pids)
    if live_pids is None:
        # Unknown is not "not running": the old code recorded False here, which
        # reads as a cleanly absent terminal and hides an unresolvable install.
        record.setdefault("problems", []).append(
            "live terminal identity unresolved — running-state unknown")

    # --- per-arm config drift: the CHART FILE is the identity source
    # (2026-09-18 §14 hardening). Banner text is structurally ambiguous for
    # this portfolio — five charts print identical
    # `mode=… | session=06-20 | execution=…` text with no arm tag — so
    # banner matching cannot attribute a drifted boot (the 09:05 phantom
    # storm: LV's LIVE-only matcher grabbed a paper arm's PAPER banner).
    # The chart's own <inputs> block is unambiguous per arm and is the same
    # source morning status [3b] byte-verifies (which caught the real
    # 09:57 drift). The banner stays as OBSERVATION: unattributable/absent
    # banners must never manufacture drift; the chart check cannot miss
    # the incident class (the EA runs what the chart says, and the chart
    # IS what we verify).
    pin_err: str | None = None
    drift: list[str] = []
    drift_arms: list[dict] = []
    try:
        from morning_status import preset_identity
        for a in arms:
            try:
                pins_src = preset_for_tag(a["tag"])
            except FileNotFoundError:
                continue                       # unpinned arm: observe only (§12)
            try:
                chart_txt = open(a["chart"], encoding="utf-16", errors="replace").read()
            except OSError as e:
                pin_err = f"chart unreadable for [{a['tag']}]: {e} — observing"
                continue
            ident = preset_identity(chart_txt, pins_src)
            if ident["verdict"] == "DRIFT":
                # preset_identity already applied the deferred-pin tolerance;
                # a DRIFT verdict here means genuine, actionable drift
                for k, got, want in ident.get("drift", []):
                    drift.append(f"[{a['tag']}] chart {k}={got} (repo pin {want})")
                for x in ident.get("missing", []):
                    drift.append(f"[{a['tag']}] chart missing pin: {x}")
                for x in ident.get("extra", []):
                    drift.append(f"[{a['tag']}] chart extra input: {x}")
                for p in ident.get("problems", []):
                    drift.append(f"[{a['tag']}] chart identity: {p}")
                drift_arms.append(a)
    except Exception as e:                      # pins/charts unreadable: observe only
        pin_err = f"pin check unavailable: {e} — observing, not acting"
        record["pin_check_error"] = str(e)

    action = None
    problems: list[str] = []
    if drift:
        record["drift"] = drift
        if state.get("consecutive_restups", 0) >= MAX_RESTUPS:
            action = "ESCALATE"
            problems = drift
        else:
            action = "DRIFT"
            problems = drift
            state["consecutive_restups"] = state.get("consecutive_restups", 0) + 1
            state["restups_total"] = state.get("restups_total", 0) + 1
            state["last_restup_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        # shared staleness policy on the WORST ledger: one terminal, one
        # restart fixes every arm's liveness at once
        h = {"exists": all(l["exists"] for l in ledgers),
             "mtime_age_min": worst,
             "flat": all(l["flat"] for l in ledgers),
             "problems": [p for l in ledgers for p in l["problems"]]}
        action, problems, new_state = decide(h, state, now_s, force=force)
        state = new_state
        if pin_err:
            problems = problems + [pin_err]
        if action == "RESTUP":
            record["restup_tags"] = [l["tag"] for l in ledgers if not l["exists"] or
                                     (l["mtime_age_min"] or 0) > STALE_MIN + GRACE_MIN]
    record["action"] = action
    if problems:
        record["problems"] = problems
    if action in ("RESTUP", "DRIFT"):
        if dry_run:
            record["action"] = f"{action} (dry-run: not executed)"
        else:
            # THE §14 GATE: every ledger in the portfolio must be flat —
            # the stop freezes ALL arms' bookkeeping, not one arm's.
            not_flat = [l["tag"] for l in ledgers if not l["flat"]]
            if not_flat and not force:
                record["action"] = "SKIP-OPEN-POSITION"
                record["problems"] = (record.get("problems") or []) + [
                    f"open paper position on {','.join(not_flat)} — restart would "
                    "freeze mid-trade bookkeeping; investigate, or --force after "
                    "verifying the book"]
                # Counter semantics (2026-09-18 fix): the restup did NOT
                # happen — the gate refused it — so it must not count toward
                # escalation. The pre-gate DRIFT decision incremented both
                # counters; roll them back (the 09:05 skip had pushed the
                # state to a phantom ESCALATE).
                state["consecutive_restups"] = max(
                    0, state.get("consecutive_restups", 0) - 1)
                state["restups_total"] = max(0, state.get("restups_total", 0) - 1)
            else:
                pids = _live_pids()
                record["pids_before"] = pids
                # None (unresolved) must not fall through to a relaunch: ok starts
                # False so the only way into the relaunch is a resolved terminal.
                ok = False
                if pids is None:
                    record["problems"] = problems + [
                        "live terminal identity unresolved — refusing to stop or "
                        "relaunch an install that was not resolved"]
                else:
                    ok = True if not pids else stop_terminal(pids)
                if ok:
                    if action == "DRIFT":
                        baks = []
                        for a in drift_arms:
                            bak = resplice_pins(a)
                            baks.append(os.path.basename(bak) if bak else None)
                        record["respliced_backup"] = [b for b in baks if b]
                        if not any(baks):
                            record["problems"] = problems + ["pin re-splice FAILED — "
                                                             "relaunching anyway; re-check the banner"]
                    relaunch_terminal()
                    record["relaunched"] = True
                else:
                    record["relaunched"] = False
                    record["problems"] = problems + ["stop_terminal failed — terminal "
                                                     "still running after the wait window"]
    save_state(state)
    record["state"] = {k: state.get(k) for k in NEW_STATE}
    print(json.dumps(record))
    save_record(record)
    return record


# --- CLI --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="MIDASTOUCH gold-arm watchdog")
    ap.add_argument("--loop", type=int, default=0,
                    help="poll every N seconds instead of once")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen; never restart")
    ap.add_argument("--force", action="store_true",
                    help="override the weekend and open-position guards")
    ap.add_argument("--status", action="store_true",
                    help="print the state summary and exit (read-only)")
    ap.add_argument("--pause", action="store_true",
                    help="create the pause marker (parity sessions) and exit")
    ap.add_argument("--resume", action="store_true",
                    help="remove the pause marker and exit")
    ap.add_argument("--reset-state", action="store_true",
                    help="clear escalation counters (after fixing an escalated arm)")
    args = ap.parse_args()

    if args.pause:
        open(PAUSE_MARKER, "w").write(datetime.now(timezone.utc).isoformat() + "\n")
        print(f"paused — marker at {PAUSE_MARKER}")
        return
    if args.resume:
        if os.path.exists(PAUSE_MARKER):
            os.remove(PAUSE_MARKER)
        print("resumed")
        return
    if args.reset_state:
        s = dict(NEW_STATE, restups_total=load_state().get("restups_total", 0))
        save_state(s)
        print(f"state reset (lifetime restups kept): {json.dumps(s)}")
        return
    if args.status:
        line, bad = watchdog_summary()
        print(("! " if bad else "") + line)
        return

    if args.loop:
        lock_fd = acquire_instance_lock()
        if lock_fd is None:
            print(f"midas_watchdog: another loop already supervises the gold arms "
                  f"(lock held: {INSTANCE_LOCK}) — exiting")
            return
        print(f"midas_watchdog: loop every {args.loop}s — Ctrl+C to stop", flush=True)
        try:
            while True:
                check(dry_run=args.dry_run, force=args.force)
                time.sleep(args.loop)
        finally:
            release_instance_lock(lock_fd)
    else:
        check(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
