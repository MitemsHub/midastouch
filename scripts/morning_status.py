"""One-command morning status for the V75 paper A/B (read-only, no MT5 needed).

    python scripts/morning_status.py
    python scripts/morning_status.py --days 1 --strict

Answers, in order:
  [1] ARM HEALTH   - per paper-arm terminal: terminal-process count, the EA's
                     last telemetry write age, ledger virtual equity + integrity,
                     and the init-silence canary (banner with no journal
                     processing in its grace window => the loaded-but-dead
                     signature that froze both arms on 2026-09-13/14).
  [2] NIGHT GAPS   - per-terminal journal audit for the last N days (default 3):
                     "connection lost" -> next "authorized" spans, including
                     cross-midnight pairs and still-open gaps.
  [3] LEDGERS      - closed trades per arm, total/mean R, virtual equity, and
                     go-live gate progress (X/30 closed trades per arm, with
                     projected days-to-30 at the observed rate).

The pre-registered gate: >= 30 closed arm-A trades with POSITIVE expectancy
+ tick reconciliation PASS (self-arms at 7d of ledger) + watchdog CERTIFIED.

Exit code 0 always (a status report, not a check); --strict exits 1 when any
arm looks unhealthy (telemetry stale > 2h, no telemetry, ledger problems).

Wire format (EA v26.35 writer, MitemshubAI.mq5 PaperLog):
  OPEN,epoch,ticket,dir,entry,sl,tp,vol,eff_risk,orig_risk,max_hold,tag   (12 fields)
  CLOSE,epoch,ticket,reason,exit,r,pnl,veq                                 (8 fields)
  EQ,veq
Epochs are SECONDS (TimeCurrent).
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import era  # era classification for the gate clock (scripts/era.py)

LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
TELEM = "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl"
# Per-EA file names: arm C is the V75MacroEngine v2.21 paper build, which
# writes its own ledger/telemetry pair (same OPEN/CLOSE/EQ + jsonl formats).
EA_FILES = {
    "MitemshubAI": (LEDGER, TELEM),
    "V75MacroEngine": ("V75MacroEngine_paper_Volatility_75_Index.csv",
                       "V75MacroEngine_paper_telemetry_Volatility_75_Index.jsonl"),
}
TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
MAGICS = {"A_tp18": 7788075, "B_tp24": 7788100, "C_v75": 7788125}
MIN_TRADES = 30
STALE_TELEM_S = 2 * 3600  # telemetry older than this counts as stale
WINDOW_DAYS = 3           # default journal audit window
# Init-silence canary grace, per EA: must exceed one bar interval because a
# healthy EA's first journal line after init can be its first bar event
# (MitemshubAI bars M15 -> 16m; V75MacroEngine bars M30 -> 31m).
CANARY_GRACE_MIN = {"MitemshubAI": 16, "V75MacroEngine": 31}

C = {"g": "\033[92m", "y": "\033[93m", "r": "\033[91m", "b": "\033[94m", "0": "\033[0m", "B": "\033[1m"}


def paint(s: str, *keys: str) -> str:
    if not sys.stdout.isatty():
        return s
    return "".join(C[k] for k in keys) + s + C["0"]


def human_age(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def parse_mql5_log(path: str, day: datetime) -> list[tuple[datetime, str, str]]:
    """Parse an MQL5/Logs journal -> [(ts, channel, message)].

    Line shape: `PP\\t0\\tHH:MM:SS.mmm\\tEA (Sym,TF)\\tmessage` (UTF-16LE; the
    2-char severity prefix is optional). The channel is the 4th tab field, so
    matching on it keeps messages emitted by OTHER EAs out of this EA's
    liveness evidence."""
    out = []
    try:
        with open(path, encoding="utf-16", errors="replace") as f:
            for line in f:
                m = re.match(r"^(?:[A-Z]{2}\t\d\t)?(\d{2}:\d{2}:\d{2})\.\d+\t([^\t]+)\t(.*)$",
                             line.rstrip("\r\n"))
                if not m:
                    continue
                hh, mm, ss = (int(x) for x in m.group(1).split(":"))
                ts = day.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                out.append((ts, m.group(2).strip(), m.group(3).strip()))
    except OSError:
        pass
    return out


def journal_lines_today(t: dict, now_local: datetime) -> list[tuple[datetime, str]]:
    """The arm EA's journal lines from today's MQL5/Logs (channel-filtered)."""
    log = os.path.join(t["dir"], "MQL5", "Logs", f"{now_local:%Y%m%d}.log")
    if not os.path.exists(log):
        return []
    return [(ts, msg) for ts, ch, msg in parse_mql5_log(log, now_local)
            if ch.startswith(t["ea"] + " (")]


def wlost_alerts(t: dict, now_local: datetime) -> list[str]:
    """WLOST quarantine lines from today's arm journal (v26.36/v2.23 writers:
    a twice-failed ledger/telemetry append is printed with the WLOST tag —
    the row never entered the ledger, so file parsers cannot see it)."""
    return [msg for _, msg in journal_lines_today(t, now_local) if "WLOST" in msg]


def init_silence_canary(t: dict, now_local: datetime) -> dict:
    """Canary for the loaded-but-dead EA signature (v27 WIP, 2026-09-13/14:
    printed its init banner, then never processed a bar - three loads on one
    terminal, zero journal lines and zero telemetry after the banner).

    Anchors on the EA's newest init banner in TODAY's MQL5/Logs journal
    (`initialized` / `vX.YZ started`, channel-filtered to the EA's own 4th
    journal field) and demands journal evidence of processing within its
    grace window (one bar interval). Alerts only when the window is empty AND
    nothing followed it either - later processing (e.g. a scheduled quiet
    period between a night init and the next bar) proves the EA is alive, and
    ongoing cadence after that is the telemetry-staleness check's job, not
    this canary's.

    2026-09-15 amendment: with 24/7 collection (session gates off) a quiet
    bar journals nothing, so telemetry is admissible liveness evidence too:
    a telemetry write AFTER the banner proves the EA processed bars even if
    its journal channel is silent. The corpse signature remains exactly:
    banner, then no journal line AND no telemetry write ever.

    Returns {"state": ok|armed|na|alert, "msg": ...} (read-only)."""
    ea = t["ea"]
    grace = CANARY_GRACE_MIN.get(ea, 31)
    lines = journal_lines_today(t, now_local)
    banners = [ts for ts, msg in lines
               if "initialized" in msg or re.search(r"v\d+\.\d+ started", msg)]
    if not banners:
        return {"state": "na", "msg": "canary n/a (no init banner today)"}
    init_ts = banners[-1]
    elapsed_s = (now_local - init_ts).total_seconds()
    if elapsed_s < grace * 60:
        return {"state": "armed",
                "msg": f"canary armed (init {init_ts:%H:%M:%S}, grace {grace}m)"}
    after = [(ts, msg) for ts, msg in lines if ts > init_ts]
    in_window = [ts for ts, _ in after
                 if (ts - init_ts).total_seconds() <= grace * 60]
    if in_window:
        return {"state": "ok",
                "msg": f"canary ok (init {init_ts:%H:%M:%S}, "
                       f"{len(in_window)} journal line(s) within {grace}m)"}
    if after:
        return {"state": "ok",
                "msg": f"canary ok (init {init_ts:%H:%M:%S}, no line within "
                       f"{grace}m - quiet period, resumed {after[0][0]:%H:%M:%S})"}
    # No journal evidence at all - telemetry is the second liveness channel
    # (heartbeats write every bar even when the journal is quiet).
    telem = os.path.join(t["files_dir"], EA_FILES[ea][1])
    if os.path.exists(telem) and os.path.getmtime(telem) > init_ts.timestamp():
        age = (datetime.now().timestamp() - os.path.getmtime(telem)) / 60
        return {"state": "ok",
                "msg": f"canary ok (init {init_ts:%H:%M:%S}, no journal line but "
                       f"telemetry written after init, last {age:.0f}m ago)"}
    return {"state": "alert",
            "msg": f"CANARY: init banner {init_ts:%H:%M:%S} ({human_age(elapsed_s)} ago) "
                   f"with NO journal processing since - loaded-but-dead signature"}


def parse_journal(path: str, day: datetime) -> list[tuple[datetime, str]]:
    """Parse one MT5 terminal journal (UTF-16LE, `HH:MM:SS.mmm\tMsg` lines with
    an optional 2-char severity prefix) -> [(full datetime, message)]."""
    out = []
    try:
        with open(path, encoding="utf-16", errors="replace") as f:
            for line in f:
                m = re.match(r"^(?:[A-Z]{2}\t\d\t)?(\d{2}):(\d{2}):(\d{2})\.\d+\t(.*)$", line.rstrip("\r\n"))
                if not m:
                    continue
                hh, mm, ss, msg = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4).strip()
                ts = day.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                out.append((ts, msg))
    except OSError:
        pass
    return out


def journal_gaps(logs_dir: str, window_start: datetime, now_local: datetime) -> list[dict]:
    """Connection gaps across the whole window as ONE merged stream, so a
    'lost' just before midnight pairs with its 'authorized' after midnight.
    'connection lost'/'no connection' opens a gap; 'authorized' closes it."""
    entries: list[tuple[datetime, str]] = []
    day = window_start
    while day <= now_local:
        entries.extend(parse_journal(os.path.join(logs_dir, f"{day:%Y%m%d}.log"), day))
        day += timedelta(days=1)

    gaps = []
    lost_at = None
    for ts, msg in entries:
        low = msg.lower()
        # journal wording: "connection to <server> lost", "no connection", or
        # "connection to <server> lost because there is no connection" - the
        # invariant is the pair (lost|no connection) ... "authorized"
        opens = ("lost" in low and "connection" in low) or "no connection" in low
        if opens and lost_at is None:
            lost_at = ts
        elif "authorized" in low and lost_at is not None:
            gaps.append({"lost": lost_at, "back": ts, "open": False})
            lost_at = None
    if lost_at is not None:
        gaps.append({"lost": lost_at, "back": None, "open": True})
    return gaps


def terminal_inventory() -> list[dict]:
    """All terminal data folders with a V75 chart profile carrying an arm magic.

    Multiple arms may share one terminal (arm C runs beside arm A on FB9A), so
    every chart is scanned and each arm magic yields its own entry with its own
    telemetry/ledger file names (per-EA, see EA_FILES)."""
    inv = []
    now_epoch = datetime.now().timestamp()
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        if not os.path.isdir(td):
            continue
        for chr_f in glob.glob(os.path.join(td, "MQL5", "Profiles", "Charts", "*", "*.chr")):
            try:
                txt = open(chr_f, encoding="utf-16", errors="replace").read()
            except OSError:
                continue
            if "Volatility 75" not in txt:
                continue
            m = re.search(r"^InpMagic(?:Number)?=(7788075|7788100|7788125)$", txt, re.M)
            if not m:
                continue
            ea = next((e for e in EA_FILES if e in txt), None)
            if ea is None:
                continue
            magic = m.group(1)
            name = next((k for k, v in MAGICS.items() if str(v) == magic), f"?{magic}")
            ledger_name, telem_name = EA_FILES[ea]
            files_dir = os.path.join(td, "MQL5", "Files")
            telem_path = os.path.join(files_dir, telem_name)
            telem_age = (now_epoch - os.path.getmtime(telem_path)) if os.path.exists(telem_path) else None
            inv.append({"name": name, "magic": magic, "ea": ea, "dir": td, "files_dir": files_dir,
                        "telem_age": telem_age, "ledger_path": os.path.join(files_dir, ledger_name),
                        # 2026-09-15: the TickRecorder runs on the MitemshubAI hosts
                        # (one per terminal; V75MacroEngine has no recorder module)
                        "has_tick_recorder": ea == "MitemshubAI"})
    return inv


def terminals_running() -> int:
    """Count of running terminal64.exe via tasklist (no psutil dependency)."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=15).stdout
        return sum(1 for line in out.splitlines() if line.lower().startswith('"terminal64.exe"'))
    except (OSError, subprocess.SubprocessError):
        return -1


def parse_ledger(path: str) -> dict:
    """Closed trades + veq + integrity from the paper ledger (same format the
    A/B adjudicator parses; kept local so this tool stays standalone).
    CLOSE rows carry their line number for era classification (scripts/era.py)."""
    res: dict = {"closed": [], "veq_last": None, "problems": []}
    open_rows: dict[str, str] = {}
    try:
        with open(path) as f:
            for ln, line in enumerate(f, 1):
                parts = line.strip().split(",")
                if not parts:
                    continue
                if parts[0] == "OPEN" and len(parts) >= 12:
                    open_rows[parts[2]] = parts[1]
                elif parts[0] == "ERA":
                    continue   # provenance row (v26.39+/v2.24+); scripts/era.py owns it
                elif parts[0] == "CLOSE" and len(parts) >= 8:
                    open_rows.pop(parts[2], None)
                    res["closed"].append({"epoch": int(parts[1]), "reason": parts[3],
                                          "r": float(parts[5]), "pnl": float(parts[6]),
                                          "veq": float(parts[7]), "line": ln})
                elif parts[0] == "EQ" and len(parts) >= 2:
                    res["veq_last"] = float(parts[1])
    except OSError as e:
        res["problems"].append(f"unreadable: {e}")
        return res
    except (ValueError, IndexError) as e:
        res["problems"].append(f"corrupt row: {e}")
        return res
    if len(open_rows) > 1:
        res["problems"].append(f"{len(open_rows)} OPEN rows without CLOSE (1 live + {len(open_rows) - 1} dangling)")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Morning status for the V75 paper A/B")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS, help="journal audit window (days)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any arm looks unhealthy")
    args = ap.parse_args()

    now_local = datetime.now()
    now_epoch = now_local.timestamp()
    n_running = terminals_running()
    inv = terminal_inventory()
    window_start = (now_local - timedelta(days=args.days)).replace(hour=0, minute=0, second=0, microsecond=0)
    unhealthy = False

    print(paint(f"=== MITEMSHUB MORNING STATUS - {now_local:%Y-%m-%d %H:%M} ===", "B"))

    print(paint("[1] ARM HEALTH", "b"))
    if not inv:
        print("  no terminal data folder with a V75 chart + arm magic found")
        unhealthy = True
    else:
        n_terminals = len({t["dir"] for t in inv})
        print(f"  terminal64.exe processes running: {n_running} ({n_terminals} terminal(s) host {len(inv)} arms)")
        if 0 <= n_running < n_terminals:
            print(paint("    ! fewer terminals running than arms configured", "y"))
    for t in inv:
        age = t["telem_age"]
        if age is None:
            telem_s = paint("no telemetry file", "r")
            unhealthy = True
        else:
            stale = age > STALE_TELEM_S
            telem_s = paint(f"telemetry last write {human_age(age)} ago" + (" STALE" if stale else ""),
                            "y" if stale else "g")
            if stale:
                unhealthy = True
        if os.path.exists(t["ledger_path"]):
            led = parse_ledger(t["ledger_path"])
            veq = led["veq_last"]
            veq_s = f"${veq:,.2f}" if veq is not None else "?"
            state = f"veq {veq_s}, {len(led['closed'])} closed"
            led_s = paint(state, "g" if not led["problems"] else "r")
            if led["problems"]:
                unhealthy = True
                state += "  " + "; ".join(led["problems"])
            print(f"  {t['name']} (magic {t['magic']}): {telem_s} | {led_s}")
        else:
            print(f"  {t['name']} (magic {t['magic']}): {telem_s} | "
                  + paint("no paper ledger yet", "y"))
        can = init_silence_canary(t, now_local)
        can_style = {"alert": "r", "ok": "g"}.get(can["state"])
        can_s = paint(f"      [{can['state'].upper()}] {can['msg']}", can_style) if can_style \
            else f"      [{can['state'].upper()}] {can['msg']}"
        print(can_s)
        if can["state"] == "alert":
            unhealthy = True
        # v26.36/v2.23 writers quarantine a twice-failed append to the journal
        # with the WLOST tag — the row never entered the ledger, so file parsers
        # cannot see it. Surface it (today only; WLOST demands same-day action).
        for msg in wlost_alerts(t, now_local):
            print(paint(f"      [ALERT] {msg}", "r"))
            unhealthy = True
        # 2026-09-15: TickRecorder canary — the arms now record the tick feed
        # (MitemshubAI hosts only; one recorder per terminal covers every arm
        # on that feed). A stale archive silently kills forensic exactness for
        # every future exit, so staleness > 15 min on a 10s flush cadence is an
        # alert, not a note. V75MacroEngine charts have no recorder: skip them.
        if t.get("has_tick_recorder"):
            tf = os.path.join(t["dir"], "MQL5", "Files",
                              "MITEMSHUB_ticks_Volatility_75_Index_"
                              f"{now_local:%Y%m%d}.csv")
            if not os.path.exists(tf):
                print(paint("      [ALERT] TickRecorder ON but today's tick CSV missing", "r"))
                unhealthy = True
            else:
                tick_age = now_epoch - os.path.getmtime(tf)
                if tick_age > 900:
                    print(paint(f"      [ALERT] tick archive stale "
                                f"({human_age(tick_age)} old) — recorder stalled?", "r"))
                    unhealthy = True
                else:
                    print(paint(f"      [ok] tick archive fresh "
                                f"({human_age(tick_age)} old)", "g"))

    print(paint(f"[2] NIGHT GAPS (last {args.days}d, terminal journals)", "b"))
    BLIP_S = 60  # reconnect flaps shorter than this are MT5 server-hopping noise
    for t in inv:
        gaps = journal_gaps(os.path.join(t["dir"], "logs"), window_start, now_local)
        if not gaps:
            print(f"  {t['name']}: no connection gaps in window")
            continue
        major = [g for g in gaps
                 if g["back"] is None or (g["back"] - g["lost"]).total_seconds() >= BLIP_S]
        n_blips = len(gaps) - len(major)
        blip_s = f"  (+{n_blips} sub-{BLIP_S}s reconnect flaps, MT5 access-point hopping)" if n_blips else ""
        if not major:
            print(f"  {t['name']}: no significant gaps{blip_s}")
            continue
        print(f"  {t['name']}:")
        for g in major:
            back_s = "(still open)" if g["back"] is None else f"{g['back']:%H:%M:%S}"
            if g["back"] is None:
                span = f"still open, {human_age((now_local - g['lost']).total_seconds())} so far"
            else:
                span = human_age((g["back"] - g["lost"]).total_seconds())
            print(f"    {g['lost']:%m-%d %H:%M:%S} -> {back_s}  [{span}]{blip_s if g is major[-1] else ''}")

    print(paint("[3] LEDGERS + GO-LIVE GATE", "b"))
    for t in inv:
        if not os.path.exists(t["ledger_path"]):
            print(f"  {t['name']}: 0/{MIN_TRADES} closed trades - gate clock starts at first fill")
            continue
        # Era-aware gate accounting (OPERATING_SUMMARY 2026-09-15 amendment):
        # the clock and the statistic are POST-v26.38 (per-tick fills) only;
        # pre-boundary bar-open-fill trades are shown for continuity but the
        # X/30 count is post-era. V75MacroEngine (arm C) is post-era by design.
        eng = "V75MacroEngine" if t["ea"] == "V75MacroEngine" else "MitemshubAI"
        all_closed = parse_ledger(t["ledger_path"])["closed"]
        era_rows = era.parse_era_rows(t["ledger_path"])
        closed = era.era_filter(all_closed, eng, era.ERA_POST, era_rows)
        pre_n = len(all_closed) - len(closed)
        if not all_closed:
            print(f"  {t['name']}: 0/{MIN_TRADES} closed trades - gate clock starts at first fill")
            continue
        n = len(closed)
        era_note = f" (+{pre_n} pre-era excluded)" if pre_n else ""
        if not closed:
            print(f"  {t['name']}: 0/{MIN_TRADES} closed post-era{era_note} - "
                  f"era clock starts at first post-boundary fill")
            continue
        total_r = sum(c["r"] for c in closed)
        mean_r = total_r / n
        days = max((closed[-1]["epoch"] - closed[0]["epoch"]) / 86400, 1 / 24)
        rate = n / days
        # A rate projected from <3 trades in <12h is noise (a single close
        # would claim "24/day"); never project an ETA from it.
        meaningful = n >= 3 and days >= 0.5
        if n >= MIN_TRADES:
            tail = f"{rate:.1f}/day - data gate MET (post-era)"
        elif meaningful and rate > 0:
            eta = (MIN_TRADES - n) / rate
            tail = f"~{eta:.0f}d to {MIN_TRADES} at {rate:.1f}/day (post-era)"
        else:
            tail = "rate not yet meaningful (too few post-era trades)"
        verdict = "POSITIVE" if mean_r > 0 else paint("NOT positive", "y")
        reasons = {c["reason"]: sum(1 for x in closed if x["reason"] == c["reason"]) for c in closed}
        print(f"  {t['name']}: {n}/{MIN_TRADES} closed post-era{era_note} | totalR {total_r:+.2f} | "
              f"meanR {mean_r:+.3f} ({verdict}) | {tail}")
        print("      exits: " + ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items())))

    print()
    print(paint("Gate reminder (pre-registered):", "b"))
    print(f"  >= {MIN_TRADES} closed arm-A trades with POSITIVE expectancy")
    print("  + tick reconciliation PASS (self-arms at 7d of ledger)")
    print("  + watchdog CERTIFIED  ->  live authorized at the pre-registered size")
    print("  (C_v75 is the V75MacroEngine paper arm: telemetry only, NOT a gate input)")

    if args.strict and unhealthy:
        print(paint("\nSTRICT: unhealthy signals present (see [1])", "r"))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
