"""One-command morning status: the gold paper arm, plus the retained inventory
of the retired V75 paper A/B (read-only, no MT5 needed).

    python scripts/morning_status.py
    python scripts/morning_status.py --days 1 --strict

Sections [1]-[3] are the V75 A/B inventory carried over from the predecessor
program; their magics (A2_fwd/B_tp24/C_v75/D_fwd) cannot see the gold arm, which
is [3b]. On a gold-only machine sections [1]-[3] are normally empty - that is
the expected reading, not a fault. For this program's go/no-go, use
`scripts/live_readiness.py` (docs/MIDASTOUCH_HEALTH_GUIDE.md section 0).

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
  [3b] MIDASTOUCH  - the gold paper arm (MidastouchAI): ledger health, live
                     position, R progress. No telemetry by design — the
                     ledger IS the evidence (same wire format, parse_ledger
                     applies unchanged).

The pre-registered paper gate: >= 30 closed trades on the attached arm with
POSITIVE expectancy + tick reconciliation PASS (self-arms at 7d of ledger)
+ watchdog CERTIFIED. That clock governs promotion out of paper; it does not
validate a strategy. Strategy validation is the separate, frozen walk-forward
gate (docs/GOLD_WFO_PROTOCOL.md section 6), and arming is the arming record
artifacts/live/armed.json - never an input edit.

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
import json
import os
import re
import subprocess
import sys
import time
from typing import Any
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import era  # era classification for the gate clock (scripts/era.py)
import mt5_ops as R  # one parser for "what is attached" — see config_attached_arms()

LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
TELEM = "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl"
# v26.40 arm-tagged names: a second MitemshubAI arm on the same terminal+symbol
# sets InpArmTag, which suffixes EVERY Files output (SymbolTaggedFile). Arm D
# (forward-test of the gated candidate) runs beside arm B on the dedicated
# terminal, so its ledger/telemetry carry the D suffix.
LEDGER_D = "MitemshubAI_paper_Volatility_75_Index_D.csv"
TELEM_D = "MitemshubAI_v23_telemetry_Volatility_75_Index_D.jsonl"
# Per-EA file names: arm C is the V75MacroEngine v2.21 paper build, which
# writes its own ledger/telemetry pair (same OPEN/CLOSE/EQ + jsonl formats).
# Entries are dicts: tagged arms (key "tag") override the default pair.
EA_FILES = {
    "MitemshubAI": {"ledger": LEDGER, "telem": TELEM},
    "V75MacroEngine": {"ledger": "V75MacroEngine_paper_Volatility_75_Index.csv",
                       "telem": "V75MacroEngine_paper_telemetry_Volatility_75_Index.jsonl"},
}
EA_FILES["MitemshubAI"]["tag"] = {"ledger": LEDGER_D, "telem": TELEM_D}
TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
# 2026-09-16: magic 7788075 is now ARM A2 (the v28.10 forward build on the 49E0
# terminal — REVERSE_BOTH tp2.0, $1,000 virtual basis). Arm A (the ORIGINAL
# pullback arm) is retired; its ledger is archived under artifacts/paper_ledgers/.
MAGICS = {"A2_fwd": 7788075, "B_tp24": 7788100, "C_v75": 7788125, "D_fwd": 7788150}
MIN_TRADES = 30
_CLI_ARGS = None   # set by main(); lets helpers read CLI options without threading args through every signature
#: The deal source the [3b] live-fill reconciliation reads, injectable for the same reason
#: `midas_watchdog.live_fill_reconciliation` and `midas_first_fill_packet.build_packet` take
#: one: None means the LIVE TERMINAL, so a caller describing a SYNTHETIC world (the [3b]
#: display tests) must be able to say "this world holds no account deals" without reaching
#: the machine's real account. MEASURED 2026-09-22: the arm's first real fill turned
#: `test_armed_world_marks_the_live_arm_live_and_the_paper_arm_paper` unhealthy — its own
#: verdict depended on whether the arm had traded, which is a property of the machine, not
#: of the code under test.
LIVE_FILL_DEAL_READER = None
STALE_TELEM_S = 2 * 3600  # telemetry older than this counts as stale
WINDOW_DAYS = 3           # default journal audit window
# Broker-vs-UTC offset tracking (health guide §4): the offset is read from
# the offset probe's journal output and from the v1.12+ EA init banner, and
# persisted so a run can flag a DST shift against the last KNOWN value.
OFFSET_STATE_PATH = os.path.join("artifacts", "midas_clock_offset_state.json")
# TimeCurrent/TimeGMT are sampled in separate statements ~instantly apart, so
# a second-boundary crossing between them shifts the derived offset by ±1 min
# (180*60-1 s -> 179 min etc.). A whole-hour offset is "stable" when it sits
# within that 1-minute artifact band; anything else (a real half-hour broker,
# garbage) must not become the DST baseline.
OFFSET_ARTIFACT_MIN = 1
# Journal-retention guard: a ledger heartbeat may lead the today-log's mtime
# by at most this many minutes before the journal is treated as possibly
# rewritten/rotated. Generous — a heartbeat must merely JOURNAL sometimes;
# only a sustained inversion (log older than the book it should narrate)
# flags. 2026-09-17's MT5 log rewrite survived ~hours undetected.
LOG_REWRITE_TOLERANCE_MIN = 90


def _parse_offset_hm(text: str) -> int | None:
    """Server-vs-GMT offset in whole minutes from one journal line.

    Accepts both writers of the same grammar:
      MidasOffsetProbe.mq5:  offset (server-GMT)   = +3 h 00 min
      v1.12+ EA init banner: CLOCK: server=... | GMT=... | offset=+2 h 00 min
    Sign survives (negative offsets are real west-of-UTC brokers); minutes
    are returned so a +2h59m sampling artifact stays distinguishable from a
    true +3h.
    """
    m = re.search(r"offset\s*\(server-GMT\)\s*=\s*([+-]?\d+)\s*h\s*(\d{1,2})\s*min",
                  text)
    if not m:
        m = re.search(r"offset=([+-]?\d+)\s*h\s*(\d{1,2})\s*min", text)
    if not m:
        return None
    sign = 1 if int(m.group(1)) >= 0 else -1
    return int(m.group(1)) * 60 + sign * int(m.group(2))


def _fmt_off(off_min: int) -> str:
    """Mirror the MQL5 writer's rendering (%+d h %02d min, truncation toward
    zero) so status text equals the journal text character-for-character."""
    oh = int(off_min / 60)          # trunc toward zero, like C
    om = abs(off_min) % 60
    return f"{oh:+d} h {om:02d} min"


def server_offset_min(state_path: str = OFFSET_STATE_PATH) -> int | None:
    """The persisted broker-vs-UTC offset in minutes, or None when unrecorded.

    Only for converting a SERVER-stamped epoch (every bar and fill epoch in this
    program) into an age against UTC *now*. Display-only, and it never asserts: a
    missing or unreadable state file returns None so the caller can say the frame is
    unproven instead of ageing two clocks against each other.

    MEASURED 2026-09-22: that is exactly what the [3b] live-position line did — a
    fill acknowledged at server 16:00 (UTC 14:00) printed as `open -1.7h`.
    """
    try:
        with open(state_path, encoding="utf-8") as fh:
            last = json.load(fh).get("last_offset_min")
    except (OSError, ValueError, AttributeError):
        return None
    return int(last) if isinstance(last, (int, float)) else None
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


def probe_offset_readings(term_dirs: list[str], now_local: datetime) -> list[dict]:
    """Offset readings from TODAY's terminal journals (read-only).

    Sources, in the same file: `MidasOffsetProbe` script runs (health guide
    §4 walk-through) and v1.12+ MidastouchAI init banners (self-recording on
    every EA attach). Days-older journals are deliberately NOT scanned: the
    reading of record is the most recent one, and the banner refreshes it on
    every (re)attach — an old probe run must not mask a banner that now
    disagrees.
    """
    out: list[dict] = []
    for td in term_dirs:
        log = os.path.join(td, "MQL5", "Logs", f"{now_local:%Y%m%d}.log")
        for ts, _, msg in parse_mql5_log(log, now_local):
            off = _parse_offset_hm(msg)
            if off is None:
                continue
            # The probe's offset line is `offset (server-GMT)   = ...` (the
            # banner form has no parenthesized field name) — the only
            # reliable per-line fingerprint, since the probe's offset line
            # itself carries no "OFFSET PROBE" marker.
            src = "probe" if "offset (server-GMT)" in msg else "banner"
            out.append({"epoch": ts.timestamp(), "offset_min": off,
                        "source": src, "dir": os.path.basename(td)[:8]})
    return out


def journal_retention_guard(charts: list[tuple[str, str]],
                            now_local: datetime) -> list[tuple[str, str]]:
    """Journal-retention guard (2026-09-18): is TODAY's terminal log really
    today's? One adjudicated line PER TERMINAL (charts carries one tuple per
    arm — the first version emitted N identical alerts for one terminal).

    MT5 can rewrite/rotate the day's journal (2026-09-17: a terminal restart
    rebuilt the log and offset lines recorded at 08:00 were gone by 20:45).
    Offsets, banners, WLOST lines and liveness evidence all come from this
    one file, so a silently replaced journal degrades every reader at once.

    Evidence and adjudication (display-only, per the [3b] health principle):
      * log missing entirely while a ledger exists — ALERT: retention or the
        logging layer is broken; banner/offset/WLOST evidence is unavailable;
      * log mtime within tolerance of the newest ledger — healthy, silent;
      * log mtime LAGGING the newest ledger heartbeat — adjudicate by
        CONTENT, not by the lag alone (2026-09-18 12:26 finding: a quiet
        terminal journals nothing after boot — EQ heartbeats are ledger-only
        file writes, never Prints — so a lagging mtime with today's boot
        banners intact is the QUIET signature, not a rewrite):
          - log still carries MIDASTOUCH init banner(s) — INFO: journal
            intact-but-quiet, boot evidence present;
          - no banner AND a ledger carries an ERA stamp from today — ALERT:
            an EA init happened today but left no journal line: the log was
            rewritten/rotated or logging silently stopped; treat as partial;
          - no banner, no era today — INFO: nothing was expected in it.
    """
    tol_s = LOG_REWRITE_TOLERANCE_MIN * 60
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    midnight = datetime.combine(now_local.date(),
                                datetime.min.time()).timestamp()
    for td, _txt in charts:
        key = os.path.basename(td)[:8]
        if key in seen:
            continue
        seen.add(key)
        log = os.path.join(td, "MQL5", "Logs", f"{now_local:%Y%m%d}.log")
        ledgers = glob.glob(os.path.join(td, "MQL5", "Files",
                                         "MIDASTOUCH_paper_*.csv"))
        if not ledgers:
            continue
        newest_ledger = max(os.path.getmtime(p) for p in ledgers)
        if not os.path.exists(log):
            out.append(("alert", f"journal MISSING for today while ledger(s) "
                        f"exist ({key}) — retention or the logging layer is "
                        "broken; banner/offset/WLOST evidence is unavailable"))
            continue
        log_mtime = os.path.getmtime(log)
        lag_s = newest_ledger - log_mtime
        if lag_s <= tol_s:
            continue
        age_min = lag_s / 60.0
        lag_note = (f"no journal writes for {age_min:.0f} min "
                    f"(newest ledger heartbeat is {age_min:.0f} min newer, "
                    f"tolerance {LOG_REWRITE_TOLERANCE_MIN} min)")
        try:
            raw = open(log, "rb").read()
            text = (raw.decode("utf-16-le", errors="replace")
                    if raw[:2] == b"\xff\xfe"
                    else raw.decode("utf-16", errors="replace")
                    if raw[:2] == b"\xfe\xff"
                    else raw.decode("utf-8", errors="replace"))
            banners = sum(1 for ln in text.splitlines()
                          if "MIDASTOUCH started |" in ln)
        except OSError:
            banners = 0
        era_today = False
        if banners == 0:
            for p in ledgers:
                try:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        era_today = any(
                            r.startswith("ERA,")
                            and r.split(",")[2].replace(".", "", 1).isdigit()
                            and float(r.split(",")[2]) >= midnight
                            for r in fh)
                except OSError:
                    continue
                if era_today:
                    break
        if banners:
            out.append(("info", f"journal QUIET ({key}): {lag_note} — "
                        "EQ heartbeats are ledger-only by design; boot "
                        f"evidence intact ({banners} banner(s)); not a "
                        "retention failure"))
        elif era_today:
            out.append(("alert", f"journal possibly REWRITTEN ({key}): "
                        f"{lag_note}, and an ERA stamp today implies an EA "
                        "init that left NO journal line — the log was "
                        "rewritten/rotated or logging stopped; treat today's "
                        "journal as partial"))
        else:
            out.append(("info", f"journal QUIET ({key}): {lag_note} — no "
                        "banner expected (no ledger era stamp today)"))
    return out


def check_clock_offset(term_dirs: list[str], now_local: datetime,
                       state_path: str = OFFSET_STATE_PATH,
                       verified_rebaseline: int | None = None) -> dict:
    """Broker-vs-UTC offset health: latest reading vs the persisted last one.

    Persisted at artifacts/midas_clock_offset_state.json (same pattern as the
    watchdog state): {last_offset_min, last_seen_epoch, last_source, runs}.
    A DST transition moves the offset by ~60 min, so:
      * readings exist now and the minute-of-hour matches the last value
        (±59s) -> stable; a > 1h jump is flagged as the DST shift;
      * no reading today -> the last persisted value is reported with its age
        (informational; banners refresh it on every EA attach).
    Absorbs a reading into state ONLY when it is a stable whole-hour value
    (|off| mod 60 <= 59s window) — a sampling artifact near the half-hour
    must not become the baseline a DST flag is computed against.

    verified_rebaseline (2026-09-18 go-live): an operator-confirmed offset
    (int, minutes) that was verified OUTSIDE the banner/probe chain — e.g.
    live broker tick epochs vs NTP-checked machine UTC. First call ARMS a
    pending_rebaseline against the observed value; a call whose stable
    reading matches the pending value REWRITES the baseline with the
    verification evidence in last_change (RE-BASELINED alert replaces the
    OFFSET CHANGE flag). A mismatch or a changed value re-arms — the
    baseline never moves on an unverified jump.
    """
    readings = probe_offset_readings(term_dirs, now_local)
    state: dict = {}
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    last_min = state.get("last_offset_min")
    last_seen = state.get("last_seen_epoch")
    alerts: list[str] = []
    latest = readings[-1] if readings else None
    stable_min = None
    if latest and latest["offset_min"] is not None:
        om = latest["offset_min"]
        rem = abs(om) % 60
        if rem <= OFFSET_ARTIFACT_MIN or rem >= 60 - OFFSET_ARTIFACT_MIN:
            stable_min = int(round(om / 60.0)) * 60
        else:
            alerts.append(f"reading {_fmt_off(om)} is not a stable whole-hour "
                          "value (re-run the probe away from a second "
                          "boundary); not updating the DST baseline")
        if stable_min is not None:
            pending = state.get("pending_rebaseline")
            if (verified_rebaseline is not None and pending is not None
                    and pending.get("to_min") == stable_min):
                # External verification completed: rewrite the baseline WITH
                # the evidence — the alert becomes a resolution, the audit
                # chain keeps both legs.
                alerts.append(
                    f"RE-BASELINED (externally verified): broker offset "
                    f"{_fmt_off(pending.get('from_min'))} -> {_fmt_off(stable_min)} confirmed "
                    "by live broker tick epochs vs NTP-checked machine UTC — "
                    "the current reading is the truth; prior baseline "
                    "superseded (see register GO-LIVE EXECUTION BLOCK)")
                state.update({"last_offset_min": stable_min,
                              "last_seen_epoch": latest["epoch"],
                              "last_source": latest["source"],
                              "runs": int(state.get("runs", 0)) + 1})
                state.setdefault("readings", []).append(
                    {"offset_min": om, "source": latest["source"],
                     "epoch": latest["epoch"], "dir": latest["dir"],
                     "verified": "broker-tick-epochs+ntp"})
                state["last_offset_verified"] = {
                    "offset_min": stable_min, "method": "broker-tick-epochs+ntp",
                    "epoch": latest["epoch"]}
                if len(state["readings"]) > 50:
                    state["readings"] = state["readings"][-50:]
                state["last_change"] = {
                    "from_min": last_min, "from_epoch": last_seen,
                    "from_source": state.get("last_source"),
                    "to_offset_min": om, "to_epoch": latest["epoch"],
                    "to_source": latest["source"], "alert": alerts[-1]}
                state.pop("pending_rebaseline", None)
            else:
                if (verified_rebaseline is not None and pending is None
                        and last_min is not None and stable_min != last_min):
                    # A verified change arrives against a stale baseline: arm
                    # the pending state; the NEXT confirmed run commits it.
                    state["pending_rebaseline"] = {
                        "to_min": stable_min, "observed_epoch": latest["epoch"],
                        "source": latest["source"]}
                elif (pending is not None
                      and pending.get("to_min") != stable_min):
                    # Reality moved off the pending value — it is stale and
                    # must never commit on a later coincidence.
                    state.pop("pending_rebaseline", None)
                if last_min is not None and stable_min != last_min:
                    dh = abs(abs(stable_min - last_min) / 60.0)
                    if abs(dh - 1.0) <= 0.02:
                        alerts.append(f"DST SHIFT: broker offset moved "
                                      f"{_fmt_off(last_min)} -> {_fmt_off(stable_min)} "
                                      "(most gold brokers are UTC+2 winter / UTC+3 "
                                      "summer, NY-close-anchored). Re-verify with the "
                                      "probe walk-through (health guide §4).")
                    else:
                        alerts.append(f"OFFSET CHANGE: broker offset moved "
                                      f"{_fmt_off(last_min)} -> {_fmt_off(stable_min)}, "
                                      "not a 1-h DST step - verify before trusting "
                                      "server-stamped rows")
                if (verified_rebaseline is not None and last_min is not None
                        and stable_min == last_min):
                    # Verification CONFIRMS the standing baseline: record the
                    # evidence (the re-baseline path above handles the case
                    # where it disagrees).
                    alerts.append(
                        f"VERIFIED (externally): broker offset "
                        f"{_fmt_off(stable_min)} confirmed by live broker tick "
                        "epochs vs NTP-checked machine UTC — baseline stands "
                        "with verification evidence")
                    state["last_offset_verified"] = {
                        "offset_min": stable_min,
                        "method": "broker-tick-epochs+ntp",
                        "epoch": latest["epoch"]}
            state.update({"last_offset_min": stable_min,
                          "last_seen_epoch": latest["epoch"],
                          "last_source": latest["source"],
                          "runs": int(state.get("runs", 0)) + 1})
            # Audit chain (2026-09-18): persist the RAW reading — value as
            # read (pre-rounding), source, journal epoch, terminal dir —
            # so any DST flag is forever auditable against the exact
            # journal line that produced the baseline.
            state.setdefault("readings", []).append(
                {"offset_min": om, "source": latest["source"],
                 "epoch": latest["epoch"], "dir": latest["dir"]})
            if len(state["readings"]) > 50:
                state["readings"] = state["readings"][-50:]
            if alerts:
                state["last_change"] = {
                    "from_min": last_min, "from_epoch": last_seen,
                    "from_source": state.get("last_source"),
                    "to_offset_min": om, "to_epoch": latest["epoch"],
                    "to_source": latest["source"], "alert": alerts[-1]}
            try:
                os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
            except OSError:
                alerts.append("could not persist offset state (artifacts/ "
                              "unwritable) - DST tracking will not remember")
    if latest is None and last_min is not None:
        age_s = (f"{human_age(now_local.timestamp() - last_seen)} ago"
                 if last_seen else "age unknown - state lacks last_seen_epoch")
        print(f"  clock offset: no reading in today's journal; last known "
              f"{_fmt_off(last_min)} ({age_s}, "
              f"{state.get('last_source', '?')})")
    elif latest is None:
        print(paint("  clock offset: never recorded - run MidasOffsetProbe once "
                    "(health guide §4) so DST shifts can be detected", "y"))
    elif alerts:
        for a in alerts:
            print(paint(f"  clock offset: {a}", "y"))
    else:
        note = ("v1.12 banner, self-recorded on attach" if latest["source"] == "banner"
                else "MidasOffsetProbe run")
        verdict = ("baseline recorded" if last_min is None
                   else "matches last known")
        print(f"  clock offset: {_fmt_off(stable_min if stable_min is not None else latest['offset_min'])} "
              f"server-vs-UTC, {verdict} [{note}]")
    return {"offset_min": latest["offset_min"] if latest else None,
            "source": latest["source"] if latest else None,
            "stable_offset_min": stable_min,
            "last_known_min": last_min,
            "alerts": alerts,
            "readings_today": len(readings)}


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
    names = EA_FILES[ea]
    names = names.get("tag", names) if t.get("tag") else names
    telem = os.path.join(t["files_dir"], names["telem"])
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

    Multiple arms may share one terminal (arm C runs on FB9A; arm A was
    retired there 2026-09-16 — its chart disarmed, ledger archived), so every
    chart is scanned and each arm magic yields its own entry with its own
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
            m = re.search(r"^InpMagic(?:Number)?=(7788075|7788100|7788125|7788150)\s*$", txt, re.M)
            if not m:
                continue
            ea = next((e for e in EA_FILES if e in txt), None)
            if ea is None:
                continue
            magic = m.group(1)
            name = next((k for k, v in MAGICS.items() if str(v) == magic), f"?{magic}")
            # v26.40: an InpArmTag= line on the chart switches the EA to its
            # tagged file pair (SymbolTaggedFile appends the tag to all output).
            tm = re.search(r"^InpArmTag=(\S+)\s*$", txt, re.M)
            tag = tm.group(1) if tm else None
            base = EA_FILES[ea]
            names = base.get("tag", base) if tag else base
            if tag and "tag" not in base:
                raise SystemExit(f"morning_status: EA {ea} has no tagged file names registered for InpArmTag={tag}")
            ledger_name, telem_name = names["ledger"], names["telem"]
            files_dir = os.path.join(td, "MQL5", "Files")
            telem_path = os.path.join(files_dir, telem_name)
            telem_age = (now_epoch - os.path.getmtime(telem_path)) if os.path.exists(telem_path) else None
            inv.append({"name": name, "magic": magic, "ea": ea, "dir": td, "files_dir": files_dir,
                        "telem_age": telem_age, "ledger_path": os.path.join(files_dir, ledger_name),
                        "tag": tag,
                        # 2026-09-15: the TickRecorder runs on the MitemshubAI hosts
                        # (one per terminal; V75MacroEngine has no recorder module).
                        # v26.40: the recorder owns the shared symbol tick file, so it
                        # is enabled on ONE chart per terminal — tagged arms (arm D)
                        # keep it off to avoid double-append.
                        "has_tick_recorder": ea == "MitemshubAI" and tag is None})
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
                    open_rows[R.live_fill_key(parts) or f"line:{ln}"] = parts[1]
                elif parts[0] == "LOPEN" and len(parts) >= 15:
                    # 2026-09-18 go-live: LIVE-path rows. Carried in open_rows so a
                    # dangling LOPEN (a REAL open position) shows as live — keyed on
                    # the identity the row actually carries (R.live_fill_key), because
                    # on a netting fill [2] is 0 and the position id is in the order
                    # field. MEASURED 2026-09-22: keying [2] made the arm's one CLOSED
                    # live fill read as an open position for the rest of the day, and
                    # put "1 OPEN rows without CLOSE" on this tool's own problem list.
                    open_rows[R.live_fill_key(parts) or f"line:{ln}"] = parts[1]
                elif parts[0] == "LCLOSE" and len(parts) >= 6:
                    # pairs the dangling-LOPEN walk only — LCLOSE carries R,
                    # not $ pnl/veq, so it never enters the paper closed list
                    # (the live block prints live closes separately).
                    open_rows.pop(R.live_fill_key(parts), None)
                elif parts[0] == "ERA":
                    continue   # provenance row (v26.39+/v2.24+); scripts/era.py owns it
                elif parts[0] == "CLOSE" and len(parts) >= 8:
                    open_rows.pop(R.live_fill_key(parts), None)
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


_RISK_TAIL_READER = None


def risk_tail_of(parts: list[str]) -> dict:
    """The v1.22 keyed `cfg=<usd>@<pct>` token off a fill or STATE row, {} when absent.

    Parsed by the WIRE-CONTRACT OWNER (`scripts/midas_first_fills_audit.py`) rather than
    re-implemented here, so the token has exactly one grammar in this repository; imported
    lazily so this module keeps its light import surface. Absence means the row predates
    v1.22 (or is a tester row, which never carries it) — not a defect.
    """
    global _RISK_TAIL_READER
    if _RISK_TAIL_READER is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from midas_first_fills_audit import read_risk_tail
        _RISK_TAIL_READER = read_risk_tail
    return _RISK_TAIL_READER(parts)


_STATE_TAIL_READER = None


def state_tail_of(parts: list[str]) -> dict:
    """The v1.27 bar-context stamp off a STATE row, {} when the row carries none.

    Parsed by the WIRE-CONTRACT OWNER (`scripts/midas_first_fills_audit.py`) rather than
    re-implemented here, exactly as `risk_tail_of` is — the STATE row and the OPEN row now
    carry the SAME `StateAppend()` tail, so one parser must read both or the two records can
    come to describe one bar differently. Imported lazily to keep this module's surface light.

    ABSENCE IS NOT A DEFECT: every STATE row written before v1.27 has no tail (and an OPEN row
    before v1.19e either), and a strategy-tester row never will. The sentinels travel as they
    are — `news == "na"` means the EA could not assert the news axis and `hour_utc == -1` means
    no server offset could be vouched for, so a consumer must REFUSE on those rather than
    default them.
    """
    global _STATE_TAIL_READER
    if _STATE_TAIL_READER is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from midas_first_fills_audit import read_state_tail
        _STATE_TAIL_READER = read_state_tail
    return _STATE_TAIL_READER(parts)


def live_grammar_view(path: str) -> dict:
    """Live-arm ledger view: LOPEN/LCLOSE/EQ grammar only.

    The live arm's equity is the BROKER ACCOUNT (not the virtual EQ rows),
    and open positions come from the dangling-LOPEN walk, so [3b] can show
    the real-money arm without lying about either.

    "Dangling" means: no LCLOSE carries the row's identity. This walk used to append
    EVERY LOPEN and never pair any of them, so a closed fill stayed on the list and the
    operator read a live position where the book held none. MEASURED 2026-09-22 on the
    arm's first real fill: `LOPEN,1790092800,0,18874164,0,...` (posid 0 at fill time —
    the order ticket is the position id) with its own
    `LCLOSE,1790093197,18874164,EXTERNAL,4328.76000,0.104` below it printed as
    "LIVE POSITION: SHORT ... open -1.7h" — negative age, because the row's epoch is
    SERVER-stamped while the age was taken against UTC. The identity now comes from the
    one rule all four readers share (mt5_ops.live_fill_key)."""
    out: dict = {"open": [], "lclose_ct": 0, "reasons": [], "problems": [],
                 "lclose_ids": set(), "lclose_r": 0.0}
    opens: dict[str, dict] = {}
    try:
        with open(path) as f:
            for ln, line in enumerate(f, 1):
                parts = line.strip().split(",")
                # EA v1.16 writer (MidastouchAI.mq5 LOPEN PaperLog):
                # LOPEN,epoch,posid,order,deal,dir,entry,sl,tp,lots,risk$,stop,timeout,tag
                # = 14 fields; posid at [2], dir at [5]. Pinned to the MQ5
                # format string by tests/test_midas_golive_grammar.py. v1.22 appends the
                # keyed `cfg=<usd>@<pct>` token LAST, which is where `risk$` stops being the
                # whole answer: it is what was TAKEN, `cfg` is what was CONFIGURED.
                if parts[0] == "LOPEN" and len(parts) >= 14:
                    opens[R.live_fill_key(parts) or f"line:{ln}"] = {
                        "posid": parts[2], "epoch": int(parts[1]),
                        "dir": int(parts[5]), "entry": float(parts[6]),
                        "sl": float(parts[7]), "tp": float(parts[8]),
                        "vol": float(parts[9]), "risk": float(parts[10]),
                        "cfg_risk": risk_tail_of(parts), "line": ln}
                elif parts[0] == "LCLOSE" and len(parts) >= 6:
                    out["lclose_ct"] += 1
                    out["reasons"].append(parts[3])
                    out["lclose_ids"].add(parts[2])
                    try:
                        out["lclose_r"] += float(parts[5])
                    except ValueError:
                        pass   # the count and the id stand; an unreadable R is not fabricated
                    opens.pop(R.live_fill_key(parts), None)
        out["open"] = list(opens.values())
    except OSError as e:
        out["problems"].append(f"unreadable: {e}")
    except (ValueError, IndexError) as e:
        out["problems"].append(f"corrupt row: {e}")
    return out


def risk_basis_text(pos: dict) -> str:
    """One honest sentence about a live fill's CONFIGURED vs TAKEN risk, or "" when the row
    predates the v1.22 stamp.

    `taken` is the LOPEN row's own `risk$` field; `configured` is what the preset asked for.
    They differ whenever the venue's lot step cannot express the budget, in either direction,
    and a reader shown only the first number cannot tell a min-lot fill from a sized one. This
    is a DISCLOSURE, not a rule violation: the venue's granularity is not something the arm
    can breach. The opposite case — the floor lot risking MORE than configured — is a real
    question, and it is named rather than hidden.
    """
    cfg = pos.get("cfg_risk") or {}
    if "cfg_risk_usd" not in cfg:
        return ""
    cfg_usd, pct, taken = cfg["cfg_risk_usd"], cfg["cfg_risk_pct"], pos["risk"]
    if cfg_usd <= 0:
        return f"UNUSABLE: configured ${cfg_usd:.2f} ({pct:.2f}%) is not a budget"
    gap = taken - cfg_usd
    word = ("QUANTISED DOWN" if gap < -0.005
            else "OVERSHOOT" if gap > 0.005 else "AS CONFIGURED")
    return (f"took ${taken:.2f} of ${cfg_usd:.2f} configured ({pct:.2f}% of equity) — "
            f"{word} ({gap:+.2f})")


def print_floor_zones(inv: list[dict], unhealthy: bool) -> bool:
    """[4] The floor-mode boundary chain per engine x symbol, computed from
    live specs + ATR (MT5 python against the running paper terminal) and the
    ledger veq of every inventoried arm. Fail-closed: no terminal/specs/ATR
    means a disclosed UNKNOWN, never a guessed boundary."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from floor_zone import (ARM_BASE_EQUITY, ARM_ENGINE, SYMBOLS,
                                compute_boundary, classify, fetch_symbol_data)
    except Exception as e:
        print(paint(f"  floor-zone module unavailable: {e}", "y"))
        return unhealthy
    engines_needed = sorted({ARM_ENGINE.get(t["name"]) for t in inv
                             if ARM_ENGINE.get(t["name"])})
    if not engines_needed:
        print("  no armed arms inventoried — nothing to bound")
        return unhealthy
    sd = None
    for sym in SYMBOLS:
        sd = fetch_symbol_data(sym)
        if sd is not None:
            break
    if sd is None:
        print(paint("  UNKNOWN boundaries: no running terminal reachable for "
                    "live specs/ATR (start a paper terminal or run during "
                    "the day window)", "y"))
        return unhealthy
    ledgers = {}
    for t in inv:
        led = parse_ledger(t["ledger_path"]) if os.path.exists(t["ledger_path"]) else None
        if led is not None:
            ledgers[t["name"]] = led["veq_last"]
    any_row = False
    for engine in engines_needed:
        b = compute_boundary(engine, sd.symbol, sd)
        if b is None:
            print(paint(f"  {engine}: boundary UNKNOWN (unusable symbol data) — "
                        "fail-closed", "y"))
            unhealthy = True
            continue
        any_row = True
        print(f"  {engine} x {b.symbol}: stop {b.stop_distance:,.0f} -> "
              f"min-lot risk ${b.min_lot_risk:,.2f} | "
              f"floor onset vEq <= ${b.floor_onset_equity:,.2f} | "
              f"STRANGULATION <= ${b.strangulation_equity:,.2f}")
        if b.disclosure:
            print(paint(f"      note: {b.disclosure}", "y"))
        # the halt floor is PER-ARM: window-start equity * (1 - 30%)
        from dataclasses import replace
        for name, veq in sorted(ledgers.items()):
            if ARM_ENGINE.get(name) != engine:
                continue
            base = ARM_BASE_EQUITY.get(name)
            bb = replace(b, halt_equity=base * (1.0 - 0.30)
                         if base is not None else float("nan"))
            v = classify(veq, bb)
            vs = f"${veq:,.2f}" if veq is not None else "?"
            halt_s = (f"${bb.halt_equity:,.2f}"
                      if bb.halt_equity == bb.halt_equity else "?")
            style = {"HALTED": "r", "STRANGULATED": "r", "FLOOR_MODE": "y",
                     "TRADING": "g", "UNKNOWN": "y"}.get(v)
            line = f"      {name}: veq {vs} -> {v} (halt <= {halt_s})"
            print(paint(line, style) if style else line)
            if v in ("HALTED", "STRANGULATED"):
                unhealthy = True
    if not any_row:
        print("  no boundaries computed")
    return unhealthy


def main() -> None:
    ap = argparse.ArgumentParser(description="Morning status: gold paper arm + retained V75 A/B inventory")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS, help="journal audit window (days)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any arm looks unhealthy")
    ap.add_argument("--verified-offset", type=int, default=None, metavar="MIN",
                    help="operator-verified broker offset in minutes "
                         "(e.g. 0 for UTC+0), measured OUTSIDE the banner/probe "
                         "chain (live tick epochs vs NTP). Two runs commit it: "
                         "the first arms the pending re-baseline, the second "
                         "(matching stable reading) rewrites the baseline with "
                         "the evidence. Without it, an offset jump stays a flag.")
    args = ap.parse_args()
    global _CLI_ARGS
    _CLI_ARGS = args

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
        print("    (this inventory tracks the retired V75 A/B magics; the gold")
        print("     arm is [3b] - for gold status run scripts/live_readiness.py)")
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
        if t.get("has_tick_recorder") and t.get("tag") is None:
            # tagged arms share the terminal's single recorder — no canary here.
            # Judge by the LATEST tick file's mtime, not today's date tag: the
            # recorder keeps appending to the previous day's file past local
            # midnight (2026-09-16 00:41 false alarm), so a name match fails
            # every night while the recorder is healthy.
            ticks = glob.glob(os.path.join(t["dir"], "MQL5", "Files",
                                           "MITEMSHUB_ticks_Volatility_75_Index_*.csv"))
            tf = max(ticks, key=os.path.getmtime) if ticks else None
            if tf is None:
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
    unhealthy = print_midas_section() or unhealthy

    print()
    print(paint("[4] FLOOR ZONES (min-lot risk vs budget cap, per engine x symbol)", "b"))
    unhealthy = print_floor_zones(inv, unhealthy)

    print()
    print(paint("Gate reminder (paper clock, pre-registered):", "b"))
    print(f"  >= {MIN_TRADES} closed trades on the attached arm with POSITIVE expectancy")
    print("  + tick reconciliation PASS (self-arms at 7d of ledger)")
    print("  + watchdog CERTIFIED  ->  live authorized at the pre-registered size")
    print("  Strategy validation is the separate, frozen walk-forward gate in")
    print("  docs/GOLD_WFO_PROTOCOL.md section 6 (ALL legs must hold); arming is the")
    print("  record artifacts/live/armed.json. The predecessor program's per-arm")
    print("  attribution (retired with the V75 paper A/B) used to print here.")

    if args.strict and unhealthy:
        print(paint("\nSTRICT: unhealthy signals present (see [1])", "r"))
        sys.exit(1)
    sys.exit(0)


MIDAS_PRESET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "mql5", "MIDASTOUCH", "MidastouchAI_M1_gold.set")


def _parse_input_pairs(text: str) -> tuple[dict[str, str], list[str]]:
    """EA input key=value pairs from .set or .chr text, values verbatim.

    Only lines matching Inp<Key>=<value> count: .set comment lines ('; ...')
    and .chr MT5 group headers ('==== ... ====') fall away naturally. Values
    are stripped but NOT coerced — identity is byte-exact by design, so even
    pure reformatting (2.0 -> 2.00) reports as drift, because the certified
    chain (preset -> splice tool) always produces byte-identical text and any
    other difference means the chart was touched by something else.
    """
    pairs: dict[str, str] = {}
    problems: list[str] = []
    for ln, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^(Inp\w+)=(.*)$", line.strip())
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if k in pairs and pairs[k] != v:
            problems.append(f"duplicate input {k} with conflicting values (line {ln})")
        elif k not in pairs:
            pairs[k] = v
    return pairs, problems


# Pins whose owning build is NEWER than the deployed arms. Keyed by input
# name; each entry documents the deployed version it cannot exist on, the
# owner version it arrived with, and why the pin is legitimate. A missing
# pin NOT listed here is still DRIFT/abort (fail-closed).
DEFERRED_PINS = {
    "InpMaxRiskPct": {
        "deployed": "MIDAS1.10",
        "owner": "MIDAS1.14",
        "why": "amendment-6 min-lot risk cap, python+EA one commit; "
               "v1.10 charts cannot carry it until the next era",
    },
}


def preset_identity(chart_txt: str, preset_path: str | None = None) -> dict:
    """Byte-exact identity check: chart .chr inputs vs the repo .set pins.

    Verdicts: OK (same key set, every value byte-identical), DRIFT (any
    missing/extra key, any value difference, or duplicate/conflicting input
    rows on the chart), UNVERIFIABLE (the repo preset itself is unreadable —
    reported, never silently skipped: a lost pins file is exactly the
    'silent preset loss' this check exists to prevent).
    """
    preset_path = preset_path or MIDAS_PRESET
    chart_pairs, problems = _parse_input_pairs(chart_txt)
    try:
        with open(preset_path, encoding="utf-8", errors="replace") as f:
            preset_txt = f.read()
    except OSError as e:
        return {"verdict": "UNVERIFIABLE", "n_keys": 0, "n_chart_keys": len(chart_pairs),
                "missing": [], "extra": [], "drift": [],
                "problems": [f"repo preset unreadable: {e}"]}
    preset_pairs, more = _parse_input_pairs(preset_txt)
    problems.extend(more)
    missing = sorted(set(preset_pairs) - set(chart_pairs))
    extra = sorted(set(chart_pairs) - set(preset_pairs))
    drift = [(k, chart_pairs[k], preset_pairs[k])
             for k in sorted(set(chart_pairs) & set(preset_pairs))
             if chart_pairs[k] != preset_pairs[k]]

    # Deferred-pin tolerance (2026-09-18, V2-register era law): a repo pin
    # the CHART cannot carry yet is not drift when it belongs to a NEWER
    # build than the arm's running binary. The repo tree legitimately
    # advances in-tree (e.g. InpMaxRiskPct, the v1.14 amendment-6 input)
    # while the deployed arms keep stamping their certified version; a
    # re-splice would touch the chart mid-window and a pin deletion would
    # un-do a registered fix — so the monitor records the deferral instead.
    # ANY missing pin not mapped to a newer-build owner remains DRIFT (an
    # unknown missing key is exactly the silent-preset-loss signature).
    deferred = [k for k in missing if k in DEFERRED_PINS]
    still_missing = [k for k in missing if k not in DEFERRED_PINS]
    # Deferred pins append to problems AFTER the raw parse problems are
    # captured — parse problems (duplicate rows etc.) are never deferred.
    raw_parse_problems = len(problems)
    for k in deferred:
        problems.append(f"deferred pin: chart runs {DEFERRED_PINS[k]['deployed']}, "
                        f"pin belongs to {DEFERRED_PINS[k]['owner']} "
                        f"({DEFERRED_PINS[k]['why']}) — applies at the next era")
    # DRIFT if anything but a PURE deferred-only state: real missing pins,
    # extras, value drift, or any raw parse problem abort. Verdict OK only
    # when the sole note is the deferral itself.
    abort_grade = bool(still_missing or extra or drift or raw_parse_problems)
    verdict = "DRIFT" if abort_grade else "OK"
    if abort_grade:
        return {"verdict": verdict, "n_keys": len(preset_pairs),
                "n_chart_keys": len(chart_pairs), "missing": still_missing,
                "extra": extra, "drift": drift, "problems": problems}
    return {"verdict": "OK", "n_keys": len(preset_pairs),
            "n_chart_keys": len(chart_pairs), "missing": [],
            "extra": extra, "drift": drift, "problems": problems,
            "deferred": deferred}


def config_attached_arms() -> list[tuple[str, str, str]]:
    """Arms a `/config` `[StartUp]` launch attached, which no profile will ever hold.

    MEASURED 2026-09-21, and this was a report that lied: the gold arm was RUNNING — its
    own start-up line in `MQL5\\Logs\\20260921.log`, its ledger written at 01:15 — while
    `[3b]` printed `no MIDASTOUCH chart attached - gold arm not running`. The profile scan
    above cannot see it because MT5 does NOT save a start-up chart. Its own documentation
    is explicit: "during the next start of the platform without the configuration file,
    this chart will not be opened". So the arm that survives an unattended relaunch — the
    one a VPS would run — is exactly the one the profile scan is blind to, and a liveness
    signal that reads like a quiet market is the failure mode this repository keeps
    paying for.

    The fallback therefore reads evidence that does exist: the attach config written by
    `scripts/attach_chart_ea.py --startup-ini`, the staged preset `ExpertParameters`
    resolves to (the file the EA actually loads), and the arm's own ledger name, which
    carries the symbol and the tag. Returns `(terminal_data_folder, chart_like_text,
    note)`; the text is shaped exactly like a `.chr` so the same arm body, preset-identity
    and ledger checks apply unchanged.

    THE PARSING LIVES IN `mt5_ops.startup_attached_arms()` — one implementation, because the
    watchdog needs the same facts, and a second copy of "what counts as attached" is how two
    tools end up disagreeing about whether the arm is running. Measured on 2026-09-21: the
    watchdog reported `no MidastouchAI chart found` at action NONE while this section
    reported the arm attached and its ledger advancing. This function only SHAPES those
    facts for the `.chr`-like consumers below.
    """
    out: list[tuple[str, str, str]] = []
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        if not os.path.isdir(td):
            continue
        for arm in R.startup_attached_arms(td):
            note = (f"{arm['period']} start-up chart (attach config, no saved profile"
                    + (", staged preset present)" if arm["staged_present"]
                       else ", NO STAGED PRESET - RUNNING CODE DEFAULTS)"))
            out.append((td, R.chart_like_text(arm), note))
    return out


def print_midas_section() -> bool:
    """[3b] MIDASTOUCH gold paper portfolio (§14, read-only). The MIDAS EA
    writes no telemetry by design — the ledgers are the evidence — so health
    per arm = chart attached + gold symbol + chart inputs byte-identical to
    the arm's own repo .set + ledger parses + ledger not stale. Every
    MidastouchAI chart on the terminal is an arm of the §14 portfolio.

    TWO WAYS AN ARM IS ATTACHED. A saved profile chart (below) and a `/config`
    start-up launch (`config_attached_arms`) are both real arms, and only the first
    leaves a `.chr` behind — so a chart-less terminal that is demonstrably trading is
    reported from the config route instead of as "not running" (2026-09-21).

    Correlation view (2026-09-17): the portfolio's modes can agree — M1t and
    M1m opened the same-direction position on the same bar on day one — so
    open positions are also grouped by direction within 15 min and the
    clusters are printed. Aggregate exposure is the SUM of the cluster's
    risks, not one arm's; display-only, never a health verdict (the §14
    modes are certified individually).
    """
    charts = []
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        if not os.path.isdir(td):
            continue
        for chr_f in glob.glob(os.path.join(td, "MQL5", "Profiles", "Charts", "*", "*.chr")):
            try:
                txt = open(chr_f, encoding="utf-16", errors="replace").read()
            except OSError:
                continue
            if "MidastouchAI" in txt:
                charts.append((td, txt))
    origin_note: dict[str, str] = {}
    if not charts:
        for td, txt, note in config_attached_arms():
            charts.append((td, txt))
            origin_note[td] = note
    if not charts:
        print("  no MIDASTOUCH chart attached - gold arm not running")
        return False
    try:
        from midas_watchdog import vps_hosting_active
        vps_era = vps_hosting_active()
    except Exception:
        vps_era = os.path.exists(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "artifacts", "midas_vps_hosting.json"))
    if vps_era:
        print(paint("  [3b] VPS HOSTING ERA: local algo is MT5-locked and the LV "
                    "surface lives on the VPS after the operator's sync — local "
                    "LV ledger staleness is EXPECTED, paper arms still collect "
                    "locally; clear artifacts/midas_vps_hosting.json when the "
                    "surface returns", "y"))
    clustered = correlate_midas_positions(collect_midas_positions(charts))
    unhealthy = False
    for i, (td, txt) in enumerate(charts, 1):
        unhealthy |= _print_midas_arm(td, txt, multi=len(charts) > 1,
                                      ordinal=i, positions=clustered,
                                      origin=origin_note.get(td))
    if clustered:
        print(paint("  [3b] correlation: multiple arms hold same-direction "
                    "positions — aggregate exposure is the cluster's SUM, "
                    "not one arm's", "y"))
        for c in clustered:
            print(f"    {c['n']} arms {'LONG' if c['dir'] > 0 else 'SHORT'} "
                  f"opened within 15 min: {', '.join(c['tags'])}")
    # Broker-vs-UTC clock tracking (health guide §4): display-only like the
    # correlation view — a shifted offset never marks an arm unhealthy (the
    # UTC-based gates are correct by construction); it changes how
    # server-stamped provenance must be READ.
    verified_offset_arg = getattr(_CLI_ARGS, "verified_offset", None)
    check_clock_offset([td for td, _ in charts], datetime.now(),
                       state_path=OFFSET_STATE_PATH,
                       verified_rebaseline=verified_offset_arg)
    for kind, msg in journal_retention_guard(charts, datetime.now()):
        if kind == "alert":
            print(paint(f"  journal retention: {msg}", "y"))
        else:
            print(f"  journal: {msg}")
    print_shadow_record()
    return unhealthy


#: The sweep-shadow forward record is quoted from its PUBLISHED artifact and
#: never from the resolver: `scripts/midas_sweep_shadow.py` is research residue
#: and must stay outside the live closure (the surface audit's 0-dangling gate),
#: so this section reads `artifacts/sweep_shadow_forward.json` and imports
#: nothing from the research layer. Tests monkeypatch SHADOW_ART.
SHADOW_ART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "artifacts", "sweep_shadow_forward.json")

#: The coverage alarm record lives in artifacts/live and is MACHINE STATE — a real
#: unacknowledged gap on this host used to leak into every [3b] fixture test that
#: asserts a clean section (measured 2026-09-23: the hibernation gap broke five tests
#: that own no alarm of their own). The path is a module constant like SHADOW_ART so
#: tests can point it at an absent file and stay hermetic; production reads the real
#: record, whose acknowledgement is a human act (live_coverage.ack_alarm).
COV_ALARM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "artifacts", "live", "heartbeat_gap_alarm.json")

#: The VPS-era ingest artifact (scripts/midas_vps_ingest.py writes it) — module
#: constant like COV_ALARM_PATH so fixtures repoint it. In the era the ledger's
#: LCLOSE rows STOP (the EA's ledger lives on MetaQuotes' disk), so the 30-trade
#: tally would freeze at whatever it reached when the era began. This artifact is
#: the venue-attributed delta; the live closed-line folds it in. STALE_H is the
#: maintenance contract: the ingest must run at least daily while the era stands,
#: and an artifact older than a day plus slack means the tally is blind again —
#: the exact "trading without eyes" state the ingest exists to prevent.
VPS_FILLS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "artifacts", "live", "vps_fills.json")
VPS_FILLS_STALE_H = 26
VPS_ERA_ARCHIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "artifacts", "vps_eras")


def _venue_closed_positions(vps_fills_path: str = "",
                            archive_dir: str = "") -> tuple[list, list]:
    """The venue-attributed closed positions the paper gate's fold may count
    (docs/PAPER_GATE_VENUE_FOLD_PREREG_20260923.md — pre-registered before wiring).

    Sources, in recency order: the live artifact's `positions`, its NO-OP-time
    `era_positions_preserved` (the daily task's out-of-era overwrite — §4's
    survival contract), and every archived era artifact (`clear-era` moves the
    marker; its ingested positions stay in the count forever — §4).

    Returns (positions, problems): positions are dicts with `position_id` and `r`
    (None-honest); problems are strings for anything unreadable (contributed as
    zero trades, never guessed — §6)."""
    path = vps_fills_path or VPS_FILLS_PATH
    arch = archive_dir or VPS_ERA_ARCHIVE
    by_id: dict[int, dict] = {}
    problems: list[str] = []

    def absorb(doc: dict, src: str) -> None:
        for p in doc.get("positions") or []:
            pid = p.get("position_id")
            if pid is None:
                continue
            try:
                by_id[int(pid)] = p
            except (TypeError, ValueError):
                problems.append(f"{src}: unreadable position id {pid!r}")
        for p in doc.get("era_positions_preserved") or []:
            pid = p.get("position_id")
            if pid is None:
                continue
            try:
                by_id.setdefault(int(pid), p)
            except (TypeError, ValueError):
                problems.append(f"{src}: unreadable preserved id {pid!r}")

    try:
        with open(path, encoding="utf-8") as fh:
            absorb(json.load(fh), os.path.basename(path))
    except (OSError, ValueError):
        pass   # no artifact yet — zero venue trades is the honest count
    for a in sorted(glob.glob(os.path.join(arch, "*.json"))):
        try:
            with open(a, encoding="utf-8") as fh:
                absorb(json.load(fh), os.path.basename(a))
        except (OSError, ValueError):
            problems.append(f"archived era artifact {os.path.basename(a)} unreadable")
    return list(by_id.values()), problems


def print_shadow_record() -> None:
    """[3b.1] The sweep-shadow forward record, as an artifact quote. Display-only.

    The pre-registered forward verdict (docs/ASIA_SWEEP_FORWARD_PREREG_20260922.md)
    is the resolver's business; this line exists so every morning report shows the
    blind-evidence progress without anyone running the resolver by hand. A missing
    or unreadable artifact is the normal state before rows exist and is reported as
    such — never as an arm problem, and it never touches the unhealthy verdict.
    """
    try:
        with open(SHADOW_ART, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        print("  [3b.1] sweep-shadow: no forward record published yet "
              "(rows accumulate from 07:00Z; the resolver writes the artifact)")
        return
    checks = d.get("checks") or {}
    rule = d.get("rule") or {}
    variant = rule.get("variant", "SWEEP_CONT")
    main = ((d.get("forward") or {}).get("results") or {}).get(variant) or {}
    n = main.get("n") or 0
    cov = checks.get("coverage")
    age = ""
    try:
        hours = (datetime.now(timezone.utc)
                 - datetime.fromisoformat(d.get("ts", ""))).total_seconds() / 3600.0
        age = f", artifact {hours:.1f}h old"
    except (ValueError, TypeError):
        pass
    print(f"  [3b.1] sweep-shadow: {d.get('verdict', '?')} — N={n} of "
          f"{rule.get('n_target', 60)} resolved ({variant}) | EA rows "
          f"{checks.get('rows_total', 0)}, in-window {checks.get('rows_in_window', 0)}, "
          f"coverage {cov if cov is not None else '-'}, "
          f"disagreements {checks.get('n_disagreements', 0)}, "
          f"unmatched {checks.get('n_unmatched', 0)}{age}")


def collect_midas_positions(charts: list[tuple[str, str]]) -> list[dict]:
    """Open positions across the portfolio, from the ledgers' OPEN rows.

    Row grammar (EA writer, MidastouchAI.mq5):
    OPEN,<epoch>,<ticket>,<dir>,fill,sl,tp,lots,eff_risk,orig_risk,max_hold,tag
    — dir is 1 (BUY) or -1 (SELL); epoch is the fill time. A dangling OPEN is
    exactly a live position (the EA restores it on init), so one scan of the
    [3b] charts' ledgers answers "who is exposed right now, which way".
    Corrupt rows are skipped (this is a display aid; the integrity verdicts
    belong to parse_ledger / the parity harness).
    """
    out: list[dict] = []
    for td, txt in charts:
        sym_m = re.search(r"^symbol=(\S+)", txt, re.M)
        tag_m = re.search(r"^InpArmTag=(\S*)\s*$", txt, re.M)
        sym = sym_m.group(1) if sym_m else "?"
        tag = (tag_m.group(1) if tag_m else "") or "M1"
        lp = os.path.join(td, "MQL5", "Files", f"MIDASTOUCH_paper_{sym}_{tag}.csv")
        try:
            with open(lp) as f:
                for line in f:
                    p = line.strip().split(",")
                    if len(p) < 12 or p[0] != "OPEN":
                        continue
                    try:
                        d, epoch = int(p[3]), int(p[1])
                    except ValueError:
                        continue
                    out.append({"tag": tag, "dir": (1 if d > 0 else -1),
                                "epoch": epoch, "ticket": p[2]})
        except OSError:
            continue
    return out


def correlate_midas_positions(positions: list[dict],
                              tolerance_s: int = 900) -> list[dict]:
    """Clusters of >= 2 arms holding the same direction, opened within
    tolerance (default 900 s = one M15 bar — the modes share a signal bar by
    construction). Greedy union on the anchor epoch, same as the pairing
    tools. Pure; returns [] when nothing clusters.
    """
    groups: dict[tuple[int, int], list[str]] = {}
    for pos in sorted(positions, key=lambda x: (x["epoch"], x["tag"])):
        key = next((k for k in groups
                    if k[1] == pos["dir"] and abs(k[0] - pos["epoch"]) <= tolerance_s),
                   None)
        if key is None:
            key = (pos["epoch"], pos["dir"])
            groups[key] = []
        groups[key].append(pos["tag"])
    return [{"dir": d, "open_epoch": e, "n": len(tags), "tags": tags}
            for (e, d), tags in sorted(groups.items()) if len(tags) > 1]


#: The NOFILL row's counters, in the order the EA writes them. The last one (news, the
#: v1.19c stand-down) was APPENDED to a 10-field row, so `zip` over a historical row
#: simply stops early — an old ledger still parses, and a new one reports the gate that
#: can stop trading for days. That asymmetry is the reason this is a named constant
#: rather than an inline tuple: the EA's format test and this reader must move together.
#:
#: MEASURED MISLABEL, 2026-09-21: this tuple named the fields in a DIFFERENT order than
#: the EA writes them — `no_trigger` sat third while the third field is `session` — so
#: every column from three onward was reported under the wrong name: the operator's
#: "why didn't it trade" line attributed session vetoes to the trigger, spread vetoes to
#: the risk cap, and so on. Nothing caught it because the only fixture in the suite used
#: a row whose trailing fields were all ZERO, and a permutation of zeros is invisible.
#: The pin now uses nine distinct values, and NOFILLSUM (below) reuses this same tuple
#: through the same zip, so the two rows cannot drift apart either.
#: The order is the writer's literal argument order in the EA:
#:   signal, mismatch, session, friday, spread, riskcap, breaker, no_trigger, news
#:   (+ v1.27: nodata, appended)
NOFILL_KEYS = ("signal", "mismatch", "session", "friday", "spread", "riskcap",
               # v1.27 appended `nodata` LAST: the row is append-only and positional, so a new
               # counter goes on the end and every reader's index list moves with the writer.
               # It is NOT a refusal: nothing about the arm refused that bar, the engine could
               # not measure a stop for it (`atr <= 0` / `stop <= 0`). Before v1.27 those two
               # returns were not counted at all, so a bar the EA could not price was invisible
               # in the one record built to answer "why didn't it trade".
               "breaker", "no_trigger", "news", "nodata")


#: v1.21 STATE row — the HUD's view, on the record. The order is POSITIONAL and is pinned
#: against the EA's own format literal by tests/test_midas_hud.py, because the NOFILL
#: lesson of 2026-09-21 was that a reader whose key order disagrees with the writer's field
#: order mislabels every column from that point on, invisibly (a permutation of zeros is
#: indistinguishable from a correct reading).
STATE_KEYS = ("sig_ct", "mac", "h4", "h1", "trig", "rsi_x100", "in_session",
              "lots_x100", "risk_x100", "day_pnl", "cap", "floor")


def dir_word(d: int) -> str:
    return "up" if d > 0 else ("down" if d < 0 else "?")


def regime_word(mac: int) -> str:
    if mac == 2:
        return "not measured yet"
    if mac > 0:
        return "BULLISH"
    if mac < 0:
        return "BEARISH"
    return "MIXED (H1/H4 disagree)"


def state_last(path: str) -> dict | None:
    """The most recent STATE row: what the chart's HUD was showing, read from the ledger.

    WHY THE HUD NEEDS A READER AT ALL. A `Comment()` on a chart is not a record: it
    changes with the next tick, it is gone when the terminal is closed, and it cannot be
    audited tomorrow. The EA writes the same numbers into a STATE row, and this renders
    them — so "what did it see at 14:15" is a question the file answers.

    Keys: STATE_KEYS, positional after the prefix and the two epochs. A short row is
    ignored rather than partially believed, and the last COMPLETE row wins.
    """
    last = None
    try:
        with open(path) as fh:
            for line in fh:
                p = line.rstrip("\n").split(",")
                if len(p) < 14 or p[0] != "STATE":
                    continue
                row = {"ct": int(p[1])}
                row.update(zip(STATE_KEYS, (int(p[2]), int(p[3]), int(p[4]), int(p[5]),
                                            int(p[6]), int(p[7]), int(p[8]), int(p[9]),
                                            int(p[10]), float(p[11]), float(p[12]),
                                            float(p[13]))))
                row["cfg_risk"] = risk_tail_of(p)   # v1.22, keyed: not a positional column
                row["state_tail"] = state_tail_of(p)   # v1.27: the bar's own context
                last = row
    except (OSError, ValueError):
        return None
    return last


def state_text(row: dict) -> str:
    """The one rendering of a STATE row, so the CLI and the chart use the same words."""
    cfg = row.get("cfg_risk") or {}
    # The configured-vs-prospective line rides only when the row carries the v1.22 token, and
    # it names the direction: a size the venue's lot step had to cut must not read like one
    # that met the budget.
    quant = ""
    if "cfg_risk_usd" in cfg:
        cfg_usd, taken = cfg["cfg_risk_usd"], row["risk_x100"] / 100
        quant = (f" of ${cfg_usd:.2f} configured ({cfg['cfg_risk_pct']:.2f}%)"
                 + (" QUANTISED DOWN" if taken < cfg_usd - 0.005
                    else " OVERSHOOT" if taken > cfg_usd + 0.005 else " AS CONFIGURED"))
    ctx = state_context_text(row.get("state_tail") or {})
    return (f"H4 {dir_word(row['h4'])} / H1 {dir_word(row['h1'])} -> "
            f"{regime_word(row['mac'])} | trigger "
            f"{'LONG' if row['trig'] > 0 else ('SHORT' if row['trig'] < 0 else 'none')} "
            f"| RSI {row['rsi_x100'] / 100:.1f} | "
            f"{'in session' if row['in_session'] else 'outside session'} | "
            f"{row['lots_x100'] / 100:.2f} lots risk ${row['risk_x100'] / 100:.2f}{quant} | "
            f"day {row['day_pnl']:+.2f} of cap ${row['cap']:.0f} | floor ${row['floor']:.0f}"
            + ctx)


#: v1.27 STATE-row context (`StateAppend()`, the same tail an OPEN row carries).
_SPREAD_HOURS = 24


def state_context_text(tail: dict) -> str:
    """The bar's own context, or "" when the row predates v1.27 (or is malformed).

    THE SENTINELS ARE RENDERED AS SENTINELS, never defaulted. `hour_utc == -1` and
    `news == "na"` are the EA saying it could not assert the axis, and printing them as an
    hour or as "no news" is precisely the confident-wrong-value this program keeps paying for.
    """
    if not tail or "malformed" in tail:
        return ""
    hour = tail.get("hour_utc", -1)
    hour_s = f"{hour:02d}Z" if hour >= 0 else "hour unasserted"
    vol = tail.get("vol_ratio", 0.0)
    vol_s = f"vol x{vol:.2f}" if vol > 0 else "vol unmeasurable"
    news = tail.get("news", "na")
    return (f" | bar context: {hour_s}, {vol_s}, news {news}, "
            f"server offset {tail.get('off_min', -9999)} min")


def spread_hours(path: str) -> dict | None:
    """v1.27 SPREADHOUR: the arm's own spread by UTC hour, or None when it has written none.

    WHY THE LEDGER AND NOT THE CORPUS. The session finding this arm's research produced rests
    on the venue's spread being FLAT at 0.2 pts in every hour — and that flatness was read off
    the data of record, not off the live feed. This reader is the other half: what the arm
    actually measured. Returns the LAST row only (one is written per UTC day), with the hours
    that carry samples, so an hour with no quotes is absent rather than reported as 0.0 —
    which would read as the tightest hour of the day.
    """
    last = None
    try:
        with open(path) as f:
            for line in f:
                p = line.rstrip("\n").split(",")
                # prefix + epoch + day + 24 x (hour, n, mean, max) = 3 + 96 fields.
                if len(p) < 3 + 4 * _SPREAD_HOURS or p[0] != "SPREADHOUR":
                    continue
                try:
                    hours = {}
                    for h in range(_SPREAD_HOURS):
                        base = 3 + 4 * h
                        n = int(p[base + 1])
                        if n > 0:
                            hours[h] = {"n": n, "mean": float(p[base + 2]),
                                        "max_x100": int(p[base + 3])}
                    last = {"epoch": int(p[1]), "day": int(p[2]), "hours": hours}
                except ValueError:
                    continue
    except OSError:
        return None
    return last


def spread_hours_text(row: dict) -> str:
    """One line: hour, sample count and mean spread, tightest-first, spread in POINTS."""
    hours = row.get("hours") or {}
    if not hours:
        return "no quotes sampled"
    ranked = sorted(hours.items(), key=lambda kv: kv[1]["mean"])
    span = f"{ranked[0][1]['mean']:.2f}-{ranked[-1][1]['mean']:.2f}"
    body = ", ".join(f"{h:02d}Z {v['mean']:.2f}({v['n']})" for h, v in ranked[:6])
    return (f"{len(hours)}/24 hours sampled, mean spread {span} pts across them — "
            f"tightest: {body}")


#: v1.28 SWEEPSHADOW — the forward shadow record of the Asian-range sweep continuation.
#: 13 fields: prefix, write, sig_open, utc_day, asian_hi, asian_lo, range_bars, side, first,
#: reclaim, stop_d, off_min, version. `side` is nonzero ONLY on the first sweep of that day
#: on that side, so it IS `SWEEP_CONT`'s direction; the mirror and the textbook reversal
#: read are derivable from the row and are deliberately not stored.
SWEEP_SHADOW_FIELDS = 13


def sweep_shadow_last(path: str) -> dict | None:
    """How much of the forward shadow the arm has recorded, and its last row.

    THE COUNT IS THE POINT, not the last row. A `SWEEPSHADOW` row is written for EVERY
    evaluated bar inside UTC 07-18 — not only when a sweep fired — so `rows` measures how
    much of the window the arm was actually up for, and `fired` is the setup count the
    forward record is accumulating. A reader shown only the last row could not tell "no
    sweeps yet" from "the terminal was down", which is exactly the confusion the coverage
    counter in `scripts/midas_sweep_shadow.py` exists to prevent.

    Returns a dict with zero counts when the book is fine but holds no rows (the honest
    answer on a v1.27 chart), and None only when the ledger cannot be read at all.
    """
    rows = fired = unreadable = 0
    last = None
    try:
        with open(path) as f:
            for line in f:
                if not line.startswith("SWEEPSHADOW,"):
                    continue
                p = line.rstrip("\n").split(",")
                if len(p) != SWEEP_SHADOW_FIELDS:
                    unreadable += 1
                    continue
                try:
                    row = {"write": int(p[1]), "sig_open": int(p[2]), "utc_day": int(p[3]),
                           "asian_hi": float(p[4]), "asian_lo": float(p[5]),
                           "range_bars": int(p[6]), "side": int(p[7]), "first": int(p[8]),
                           "reclaim": int(p[9]), "stop_d": float(p[10]),
                           "off_min": int(p[11]), "version": p[12]}
                except ValueError:
                    unreadable += 1
                    continue
                rows += 1
                if row["side"] != 0:
                    fired += 1
                last = row
    except OSError:
        return None
    return {"rows": rows, "fired": fired, "unreadable": unreadable, "last": last}


def sweep_shadow_text(row: dict) -> str:
    """One line. The frame is printed beside the bar, never subtracted silently."""
    if row.get("rows", 0) == 0:
        return ("no rows yet — the shadow starts on the next evaluated bar inside UTC 07-18"
                + (f" ({row['unreadable']} unreadable row(s) skipped)"
                   if row.get("unreadable") else ""))
    last = row.get("last") or {}
    off = last.get("off_min")
    sig = last.get("sig_open") or 0
    if off is not None and sig and off != STATE_OFF_UNKNOWN:
        when = datetime.fromtimestamp(sig - off * 60, timezone.utc).strftime("%m-%d %H:%M")
        frame = f"{when}Z (server +{off}min)"
    else:
        frame = "frame unasserted"
    return (f"{row['rows']} row(s), {row['fired']} with a sweep (the setup count) — "
            f"last {frame} side {last.get('side')} range "
            f"{last.get('asian_hi'):.2f}/{last.get('asian_lo'):.2f} "
            f"({last.get('range_bars')} bars) stop {last.get('stop_d'):.2f}")


#: The EA's "no offset may be named" sentinel. Repeated here rather than imported from
#: `live_readiness` so this module stays free of the prop layer.
STATE_OFF_UNKNOWN = -9999


#: v1.23 SPEC row — the venue's self-inconsistency as the EA recorded it. Fields are
#: KEYED (`tv=`, `ts=`, `cs=`, `broker=`, `settled=`, `used=`, `ratio=`), so no column
#: order can be misread here; only the row's own UTC epoch is positional after the prefix.
SPEC_FIELDS = ("tv", "ts", "cs", "broker", "settled", "used", "ratio")


def spec_last(path: str) -> dict | None:
    """The most recent SPEC row: the venue spec the EA observed and what it sized on.

    WHY THIS EXISTS. Until v1.23 the EA re-printed `TICK VALUE MISMATCH` from every
    caller of `DollarPerUnitPerLot()` — the 15-minute heartbeat refreshes the HUD and
    writes the STATE row, both of which call it — so the same two static numbers
    repeated all day and buried the very refusals the journal exists to carry. It now
    prints once per session (or when the numbers move) and records those same moments
    as a SPEC row, which is why this reader exists: the journal is allowed to be quiet
    only if the file still answers what the numbers were.

    Keyed fields, so a changed writer or an extended row cannot silently mislabel a
    column (the NOFILL lesson, 2026-09-21). A row missing any field is ignored rather
    than partially believed, and the last COMPLETE row wins.
    """
    best: dict | None = None
    try:
        with open(path) as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) < 3 or p[0] != "SPEC":
                    continue
                try:
                    row: dict = {"ct": int(p[1])}
                    for tok in p[2:]:
                        k, _, v = tok.partition("=")
                        if k in SPEC_FIELDS and v:
                            row[k] = float(v)
                except ValueError:
                    continue
                if all(k in row for k in SPEC_FIELDS):
                    best = row
    except OSError:
        return None
    return best


def spec_text(row: dict) -> str:
    """The one rendering of a SPEC row, so the CLI and the journal use the same words."""
    if row["settled"] > 0:
        return (f"broker tv/ts={row['broker']:.2f} vs order_calc_profit {row['settled']:.2f} per "
                f"price unit (ratio {row['ratio']:.2f}) — venue spec self-inconsistent; "
                f"sized on the settled value")
    return (f"broker tv/ts={row['broker']:.2f} vs contract {row['cs']:.2f} per price unit "
            f"(ratio {row['ratio']:.2f}) — order_calc_profit unavailable; sized on geometry")


def nofill_open_day(path: str) -> dict | None:
    """The census of the UTC day IN PROGRESS, read from the EA's last NOFILLSUM row.

    WHY THIS EXISTS. `nofill_summary` can only report days that have ENDED — the EA
    writes its NOFILL row when the UTC day rolls. On 2026-09-21 that meant a full live
    day of refusals reported nothing, twice over: the row had not rolled yet, AND the
    in-memory counters it would have rolled had been erased by 22 EA restarts. The EA's
    snapshot row fixes the second half (it is written as the counters change and read
    back at init); this reads it, so "why didn't it trade" answers during the day and
    survives the reloads — which is exactly when the operator is asking.

    Keys: the NOFILL_KEYS plus `day` (the UTC day number the counters belong to). The row
    is append-only and positional, so the last COMPLETE row wins and a shorter row is
    ignored rather than partially believed.

    v1.27: THE FLOOR IS THE SAME ONE THE EA USES, and that is deliberate. `DiagRestoreFromLedger`
    refuses a snapshot written before the `nodata` append (12 fields) because restoring it would
    invent a ZERO for the counter it does not carry. If this reader accepted that row it would
    report a day-in-progress the EA had itself DISCARDED — two readers of one row disagreeing
    about whether it counts, which is the R6 lesson. A pre-append row is therefore not a partial
    state here either: it is a shorter complete state, and it is refused.

    v1.27: THE SLICE IS DERIVED FROM THE KEY TUPLE, not written as `12`. `nodata` was
    appended as the tenth counter, so the writer's row is now 13 fields while a v1.26 row is
    12 — and a literal `p[3:12]` would silently read nine of ten counters and report the last
    one as absent. Every consumer that counts fields by hand is one append away from the
    mislabel this module's NOFILL reader was rebuilt to prevent, so the count lives in one
    place. A 9-counter row still parses (zip stops at the shorter side); `nodata` is then
    simply absent rather than zero, which is the honest reading of a row that predates it.
    """
    try:
        best: dict | None = None
        with open(path) as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) < 3 + len(NOFILL_KEYS) or p[0] != "NOFILLSUM":
                    continue
                try:
                    row = {"day": int(p[2]), "epoch": int(p[1])}
                    row.update(zip(NOFILL_KEYS, map(int, p[3:3 + len(NOFILL_KEYS)])))
                except ValueError:
                    continue
                best = row
        return best
    except OSError:
        return None


def nofill_summary(path: str, now_ts: float | None = None) -> dict | None:
    """v1.18 NOFILL diagnostics tail: sum the last 24h of daily NOFILL rows
    (the EA writes one per UTC day; consumers difference consecutive rows
    for intervals, but a daily row IS the interval for [3b])."""
    try:
        cutoff = (now_ts or datetime.now().timestamp()) - 86400
        agg: dict[str, int] = {}
        with open(path) as f:
            for line in f:
                p = line.strip().split(",")
                # v1.27: the counter count comes from NOFILL_KEYS, never a literal, so appending
                # a counter cannot leave a reader behind. This reader is deliberately TOLERANT
                # (prefix, epoch, at least one counter): it is a 24h AGGREGATE over rows that
                # may predate a counter, and zip drops the absent key rather than inventing a
                # zero for it. The strict floor belongs on the SNAPSHOT reader, where a missing
                # field would be restored as a confident zero — see nofill_open_day.
                if len(p) > 2 and p[0] == "NOFILL":
                    try:
                        if int(p[1]) >= cutoff:
                            for key, v in zip(NOFILL_KEYS, map(int, p[2:2 + len(NOFILL_KEYS)])):
                                agg[key] = agg.get(key, 0) + v
                    except ValueError:
                        continue
        return agg or None
    except OSError:
        return None


def _vps_fills_line(vps_era: bool, ledger_closes: int) -> tuple[str | None, bool]:
    """The VPS-era tally fold (runbook §0d), one line for the live closed-block.

    Returns (line, problem). (None, False) out of era — the fold exists only where
    LCLOSE rows cannot. In era: a missing artifact is a yellow note (the marker is
    set BEFORE the migration completes, so a window with nothing to ingest is
    normal), a FAILING or stale artifact is a PROBLEM (the tally is blind again),
    and a healthy one carries the combined tally — ledger LCLOSE rows plus the
    venue-attributed VPS-era closes the ledger can never have.
    """
    if not vps_era:
        return None, False
    try:
        with open(VPS_FILLS_PATH, encoding="utf-8") as fh:
            art = json.load(fh)
    except (OSError, ValueError):
        return (paint("  vps era: no vps_fills.json yet - run scripts/midas_vps_ingest.py "
                      "once the VPS EA is live (the tally cannot fold what was not read)", "y"),
                False)
    if art.get("verdict") == "FAIL":
        first = "; ".join(art.get("problems", [])[:1]) or "unreadable era record"
        return (paint(f"  vps era: ingest FAILED - {first}", "r"), True)
    age_h = None
    try:
        from datetime import datetime as _dt, timezone as _tz
        age_h = (_dt.now(_tz.utc)
                 - _dt.fromisoformat(art["ts"])).total_seconds() / 3600.0
    except (KeyError, ValueError):
        pass
    if age_h is None or age_h > VPS_FILLS_STALE_H:
        return (paint(f"  vps era: vps_fills.json is stale "
                      f"({art.get('ts', 'no timestamp')}) - the tally is not being "
                      f"maintained; run scripts/midas_vps_ingest.py", "r"), True)
    tally = art.get("tally", {})
    n = int(tally.get("closed", 0))
    wins = int(tally.get("wins", 0))
    sr = float(tally.get("sum_r", 0.0))
    if n == 0:
        return (f"  vps era: 0 VPS-era closed position(s) outside the ledger so far "
                f"(artifact {art.get('ts', '?')}Z) - tally {ledger_closes}/{MIN_TRADES} "
                f"unchanged; the fold applies when a VPS position closes", False)
    combined = ledger_closes + n
    return (f"  vps era: {n} VPS-era closed position(s) outside the ledger "
            f"({wins}W/{n - wins}L, sumR {sr:+.2f}) - tally {combined}/{MIN_TRADES} "
            f"includes them", False)


def _print_midas_arm(td: str, txt: str, multi: bool = False,
                     ordinal: int = 1, positions: list[dict] | None = None,
                     origin: str | None = None) -> bool:
    """One arm's health block (the §13-era single-arm body, per arm).

    `origin` is set only for a `/config`-attached arm, which has no `.chr` to read a
    chart period from: it replaces the `chart:` line so the block never claims a period
    it did not observe.
    """
    sym_m = re.search(r"^symbol=(\S+)", txt, re.M)
    period_m = re.search(r"^period_size=(\d+)", txt, re.M)
    tag_m = re.search(r"^InpArmTag=(\S*)\s*$", txt, re.M)
    sym = sym_m.group(1) if sym_m else "?"
    period = period_m.group(1) if period_m else "?"
    tag = (tag_m.group(1) if tag_m else "") or "M1"
    # REAL MONEY is a property of the CHART, not of a tag history. This used to be
    # `tag == "LV"`, which was true when the only live arm was called LV; after the
    # 2026-09-21 arming the live arm is `U25`, and a `tag == "LV"` test would have
    # printed "paper" for an arm placing real orders — the one display error that must
    # never happen. `InpLiveExecution` in the chart text is exactly what the EA is
    # running, so reading it makes the banner and the ledger view follow reality.
    live_m = re.search(r"^InpLiveExecution=(\S+)", txt, re.M)
    chart_live = bool(live_m) and live_m.group(1).strip().lower() == "true"
    is_live = chart_live
    try:
        from midas_watchdog import vps_hosting_active
        vps_era = vps_hosting_active()
    except Exception:
        vps_era = os.path.exists(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "artifacts", "midas_vps_hosting.json"))
    hdr = ("[3b] MIDASTOUCH GOLD ARM (MidastouchAI, LIVE $$$)" if is_live
           else "[3b] MIDASTOUCH GOLD ARM (MidastouchAI, paper)")
    if multi:
        hdr += f" #{ordinal}"
    print(paint(hdr, "b"))
    if origin:
        print(f"  chart: {sym} {origin} | tag {tag} | terminal {os.path.basename(td)[:8]}")
    else:
        print(f"  chart: {sym} M{period} | tag {tag} | terminal {os.path.basename(td)[:8]}")
    problems: list[str] = []
    if "XAU" not in sym.upper() and "GOLD" not in sym.upper():
        problems.append(f"chart symbol {sym} is not gold - charter violation")
    # Preset identity (2026-09-17 discipline): the chart's inputs must be
    # byte-exact against the repo .set. This is the silent-preset-loss guard
    # — the 2026-09-17 drift incidents (mode/session flip, code-defaults
    # reattach) are exactly what it makes impossible to miss again.
    # One reader for "are we live?" (scripts/mt5_ops.py): the repo root is the module's
    # own, because morning_status has no REPO of its own to disagree with.
    arming = R.arming_state(R.REPO)
    try:
        from midas_watchdog import preset_for_tag
        # The pin follows the RECORD: when an arming record exists, the arm is meant to run the
        # LIVE preset, and reporting the paper pin's absence as DRIFT would be this report
        # arguing with the operator's authorisation instead of describing it.
        ppath = preset_for_tag(tag, armed=arming["armed"])
    except ImportError:
        ppath = None
    ident = preset_identity(txt, ppath)
    armed_arm = arming["armed"] and arming["arm"] == tag
    if armed_arm:
        print(paint(f"  ARMED: {arming['summary']}", "r" if arming["override"] else "g"))
    # Two mismatches between the record and the chart, both silent in the other
    # direction and both worth a PROBLEM line: real orders with nothing authorising
    # them, and an authorisation naming an arm that is still inert.
    if chart_live and not armed_arm:
        problems.append(
            "chart declares InpLiveExecution=true but the arming record "
            + (f"names {arming['arm']!r}, not {tag!r}" if arming["armed"]
               else "does not exist (" + str(R.ARMING_RECORD_REL) + ")")
            + " — orders would be placed with no authorisation on file")
    if armed_arm and not chart_live:
        problems.append(
            f"the arming record names this arm ({tag}) but its chart is INERT "
            f"(InpLiveExecution=false) — no real orders are being placed")
    if ident.get("deferred"):
        print(paint(f"  preset: OK ({ident['n_keys']} inputs) — "
                    f"deferred pin(s): {', '.join(ident['deferred'])} "
                    "(newer-build pin; applies at the next era)", "y"))
    elif ident["verdict"] == "OK":
        print(f"  preset: OK ({ident['n_keys']} inputs byte-identical to repo .set)")
    elif ident["verdict"] == "UNVERIFIABLE":
        problems.append("preset identity UNVERIFIABLE: " + "; ".join(ident["problems"]))
    else:
        if ident["missing"]:
            problems.append(f"preset DRIFT: missing from chart: {', '.join(ident['missing'])}")
        if ident["extra"]:
            problems.append(f"preset DRIFT: on chart, not in .set: {', '.join(ident['extra'])}")
        for k, got, want in ident["drift"]:
            problems.append(f"preset DRIFT: {k}={got} (repo pin {want})")
        for p in ident["problems"]:
            problems.append(f"preset DRIFT: {p}")
    ledger_path = os.path.join(td, "MQL5", "Files", f"MIDASTOUCH_paper_{sym}_{tag}.csv")
    if not os.path.exists(ledger_path):
        print(f"  ledger: MISSING ({os.path.basename(ledger_path)}) - EA has not initialized")
        print(paint("  UNHEALTHY: no ledger", "r"))
        return True
    parsed = parse_ledger(ledger_path)
    problems.extend(parsed["problems"])
    lv: dict[str, Any] = live_grammar_view(ledger_path) if is_live else {"open": [], "lclose_ct": 0, "problems": []}
    problems.extend(lv["problems"])
    age_h = (datetime.now().timestamp() - os.path.getmtime(ledger_path)) / 3600
    age_s = f"{age_h:.1f}h" if age_h < 72 else f"{age_h / 24:.1f}d"
    if age_h > 24 * 7:
        if is_live and vps_era:
            problems.append(f"ledger age {age_s} — VPS hosting era: the LV surface "
                            "lives on the VPS; the local copy is frozen by design")
        else:
            problems.append(f"ledger stale {age_s} (no writes)")
    start, live, open_rows = None, None, {}
    try:
        with open(ledger_path) as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 12 and parts[0] == "OPEN":
                    open_rows[parts[2]] = parts
                elif len(parts) >= 8 and parts[0] == "CLOSE":
                    open_rows.pop(parts[2], None)
                elif parts[0] == "EQ" and len(parts) >= 2 and start is None:
                    start = float(parts[1])
    except OSError as e:
        problems.append(f"unreadable: {e}")
    if open_rows:
        r = sorted(open_rows.values(), key=lambda p: int(p[1]))[-1]
        live = (r[3], r[4], (datetime.now().timestamp() - int(r[1])) / 3600)
    veq = parsed["veq_last"]
    veq_s = f"{veq:.2f}" if veq is not None else "n/a"
    start_s = f" (start {start:.2f})" if start is not None else ""
    print(f"  ledger: {os.path.basename(ledger_path)} | age {age_s} | veq {veq_s}{start_s}")
    st = state_last(ledger_path)       # v1.21: the same view the chart's HUD shows
    if st:
        # THE TWO CLOCKS IN THIS ROW ARE DIFFERENT ON PURPOSE, and conflating them is a
        # whole-offset error that reads as a plausible time. The row's own timestamp is UTC
        # (TimeUTCNow); the bar epoch it evaluated is SERVER-stamped, like every bar epoch in
        # this program (the parity work pinned the offset for exactly this reason). So the
        # bar is labelled `server`, not converted here — a conversion needs the era table,
        # and the offset line below already reports the offset this terminal is running.
        written = (datetime.fromtimestamp(st["ct"], timezone.utc).strftime("%m-%d %H:%M")
                   if st["ct"] else "n/a")
        bar = (datetime.fromtimestamp(st["sig_ct"], timezone.utc).strftime("%m-%d %H:%M")
               if st["sig_ct"] else "n/a")
        print(f"  view (ledger STATE, written {written} UTC | last bar {bar} server): "
              f"{state_text(st)}")
    sp = spec_last(ledger_path)        # v1.23: the venue spec the EA last observed
    if sp:
        sp_written = datetime.fromtimestamp(sp["ct"], timezone.utc).strftime("%m-%d %H:%M")
        print(f"  venue spec (ledger SPEC, written {sp_written} UTC): {spec_text(sp)}")
    sh = spread_hours(ledger_path)     # v1.27: the arm measuring its own spread by hour
    if sh:
        sh_day = (datetime.fromtimestamp(sh["epoch"], timezone.utc).strftime("%m-%d")
                  if sh["epoch"] else "n/a")
        print(f"  spread by hour (ledger SPREADHOUR, day {sh_day} UTC): {spread_hours_text(sh)}")
        print("    (record only — no rule reads it; the corpus is flat across hours on this "
              "venue, and this is the live check of that)")
    sw = sweep_shadow_last(ledger_path)   # v1.28: the forward sweep shadow, no order path
    if sw is not None:
        print(f"  sweep shadow (ledger SWEEPSHADOW): {sweep_shadow_text(sw)}")
        print("    (record only — NO order path; resolved against the forward "
              "pre-registration by scripts/midas_sweep_shadow.py)")
    od = nofill_open_day(ledger_path)  # v1.20: the day IN PROGRESS, restart-proof
    if od and od.get("signal"):
        top = sorted(((k, v) for k, v in od.items()
                      if k in NOFILL_KEYS and v), key=lambda kv: -kv[1])[:4]
        print(f"  no-fill (day {od['day']}, running): "
              + ", ".join(f"{k}={v}" for k, v in top)
              + "  (the census so far; it rolls to a NOFILL row at the UTC day change)")
    nf = nofill_summary(ledger_path)   # v1.18: why-no-trade accounting, 24h
    if nf:
        top = sorted(((k, v) for k, v in nf.items() if v), key=lambda kv: -kv[1])[:4]
        line = ", ".join(f"{k}={v}" for k, v in top)
        # The news stand-down is GUARANTEED a place on the line: it is the one gate that
        # can hold entries for days at a time, and a top-4 cut would hide it behind
        # ordinary session/no-trigger counts exactly when the operator needs the reason.
        news = nf.get("news", 0)
        if news and not any(k == "news" for k, _ in top):
            line += (", " if line else "") + f"news={news}"
        # v1.27: `nodata` is guaranteed a place for the mirror-image reason. It is NOT a
        # refusal — nothing about the arm refused those bars, the ENGINE could not measure a
        # stop for them — and it is nonzero only when the feed or history is degraded, which is
        # exactly when a top-4 cut must not be allowed to hide it behind ordinary counts.
        nod = nf.get("nodata", 0)
        if nod and not any(k == "nodata" for k, _ in top):
            line += (", " if line else "") + f"nodata={nod}"
        print("  no-fill (24h): " + line
              + "  (NOFILL diagnostics — reasons the engine did not trade)")
    if is_live:
        # The LIVE arm's block: open positions from dangling LOPEN rows, equity
        # is the BROKER ACCOUNT (the virtual EQ rows are inert in live mode).
        if lv["open"]:
            # ONE CLOCK. The row's epoch is the venue's SERVER clock; `now` is UTC, so the
            # age is only meaningful once the persisted offset is added back (see
            # server_offset_min). Unrecorded offset -> say so rather than print a
            # confident negative age.
            off_min = server_offset_min()
            unproven = "" if off_min is not None else \
                " [frame unproven: no clock offset on record]"
            for o in lv["open"]:
                age_h_o = ((datetime.now().timestamp() + (off_min or 0) * 60)
                           - o["epoch"]) / 3600
                print(paint(f"  LIVE POSITION: {'LONG' if o['dir'] > 0 else 'SHORT'} "
                            f"{o['vol']} lots @ {o['entry']:.2f} | SL {o['sl']:.2f} "
                            f"TP {o['tp']:.2f} | open {age_h_o:.1f}h "
                            f"(timeout 720 min; SL/TP server-side){unproven}", "b"))
                # v1.22: the fill's own configured-vs-taken risk, from the row. Without it
                # the operator reads `risk$` alone and cannot see that the venue's lot step
                # has been halving (or doubling) what the preset asks for.
                note = risk_basis_text(o)
                if note:
                    print(f"                risk {note} (from the LOPEN row)")
            if lv["lclose_ct"]:
                print(f"  (prior live closes counted in the closed line below)")
        else:
            # The window is the EA's InpSessionStartHour..EndHour applied to BAR EPOCHS,
            # i.e. the BROKER SERVER frame - not UTC. The line said "UTC" until
            # 2026-09-22, when the arm's own STATE rows showed the gate classifying server
            # hours 9..14 while real UTC was 07..12: on this venue (UTC+2) "06-20 UTC" was
            # really 04:00-18:00 UTC, two hours of the operator's trading day at each end.
            # Read from the preset rather than restated, so the two cannot drift again.
            sh = re.search(r"(?m)^InpSessionStartHour\s*=\s*(\d+)", txt)
            eh = re.search(r"(?m)^InpSessionEndHour\s*=\s*(\d+)", txt)
            win = (f"{int(sh.group(1)):02d}-{int(eh.group(1)):02d} SERVER"
                   if sh and eh else "its preset window")
            print(f"  live: flat (armed; signals in-session {win} only - the gate classifies "
                  f"bar epochs, so this is NOT UTC)")
        # The venue holds the second copy of what this arm did. A flat ledger is NOT a
        # health claim: it is either "nothing traded yet" or "the EA is not running", and
        # only the account's own deal history can tell those apart
        # (see midas_watchdog.live_fill_reconciliation).
        try:
            from midas_watchdog import live_fill_reconciliation
            mm = re.search(r"(?m)^InpMagic\s*=\s*(\d+)", txt)
            rec = live_fill_reconciliation(ledger_path,
                                          magic=int(mm.group(1)) if mm else 0,
                                          reader=LIVE_FILL_DEAL_READER)
            print(f"  fills: {rec['detail']}")
            if not rec["healthy"]:
                problems.append("live fills: " + rec["detail"])
            # The FIRST fill is captured once, from all three sources, at the moment they
            # describe the same event (see midas_watchdog.record_first_fill).
            try:
                from midas_watchdog import FIRST_FILL_PATH
                if os.path.exists(FIRST_FILL_PATH):
                    with open(FIRST_FILL_PATH, encoding="utf-8") as fh:
                        ff = json.load(fh)
                    print(f"  first fill: {ff.get('recorded_utc', '?')} | ledger "
                          f"{ff.get('ledger_fills')} vs account {ff.get('account_identifiers')}"
                          f" | row: {str(ff.get('first_ledger_row'))[:70]}")
                elif rec.get("account"):
                    problems.append("the account shows fills but no first-fill record was "
                                    "written — run the watchdog")
            except Exception:      # noqa: BLE001 — reporting must never break the block
                pass
        except Exception as exc:      # noqa: BLE001 — never let this mask the block
            problems.append(f"live fills: reconciliation unavailable ({exc})")
    elif live:
        print(f"  live: {live[0]} @ {live[1]} | open {live[2]:.1f}h")
        if positions:
            mine = next((c for c in positions if tag in c["tags"]), None)
            if mine:
                print(f"  live cluster: {mine['n']} arms "
                      f"{'LONG' if mine['dir'] > 0 else 'SHORT'} within 15 min "
                      f"({', '.join(mine['tags'])})")
    else:
        print("  live: flat")
    closed = parsed["closed"]
    if is_live:
        reasons = lv["reasons"]
        breakdown = (", ".join(f"{k}:{reasons.count(k)}" for k in sorted(set(reasons)))
                     if reasons else "none yet")
        print(f"  closed: {lv['lclose_ct']}/{MIN_TRADES} (live LCLOSE rows) "
              f"| exits: {breakdown} | $ realized is on the account, R on the rows")
        # The era fold (runbook §0d): past this line the ledger's LCLOSE rows stop —
        # the EA's ledger lives on MetaQuotes' disk — so the tally continues only
        # through the venue-attributed ingest artifact. A failing or stale artifact
        # is a health problem, not a footnote: the era without eyes is blind again.
        vps_line, vps_bad = _vps_fills_line(vps_era, lv["lclose_ct"])
        if vps_line:
            print(vps_line)
        if vps_bad:
            problems.append("vps era: the tally's ingest artifact is failing or stale")
        # The pre-registered fold (docs/PAPER_GATE_VENUE_FOLD_PREREG_20260923.md):
        # the gate's count is the LEDGER's closes ∪ the venue-attributed closes,
        # by position id — the ledger undercounts its own closes (measured
        # 2026-09-23, amendment 12: one LCLOSE row for three closed positions).
        # The venue-only trades print so the operator can always see how much of
        # the count the ledger did not record; the venue's R's carry the same
        # certified stop denominator, and unknown-R trades count trades but never
        # fabricate R.
        venue_pos, venue_problems = _venue_closed_positions()
        fresh = [p for p in venue_pos
                 if str(p.get("position_id")) not in lv["lclose_ids"]]
        if fresh or venue_problems:
            with_r = [p for p in fresh if p.get("r") is not None]
            sum_r = sum(p["r"] for p in with_r)
            tally_n = lv["lclose_ct"] + len(fresh)
            tally_r = lv["lclose_r"] + sum_r
            print(f"  tally (folded): {tally_n}/{MIN_TRADES} | venue-added {len(fresh)} "
                  f"({sum_r:+.2f}R) | ledger-side R {lv['lclose_r']:+.2f} | "
                  f"combined R {tally_r:+.2f}")
            problems.extend(venue_problems)
    elif closed:
        total_r = sum(c["r"] for c in closed)
        reasons: dict[str, int] = {}
        for c in closed:
            reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
        verdict = "POSITIVE" if total_r > 0 else paint("NOT positive", "y")
        print(f"  closed: {len(closed)}/{MIN_TRADES} | totalR {total_r:+.2f} | "
              f"meanR {total_r / len(closed):+.3f} ({verdict})")
        print("      exits: " + ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items())))
    else:
        print(f"  closed: 0/{MIN_TRADES} - gate clock starts at first fill")
    # v1.09 companion: scripts/midas_watchdog.py watches the EA's 15-min ledger
    # heartbeat and restarts the terminal when it goes stale (flat-checked).
    # Its escalation state must be visible here — an escalated watchdog is an
    # unhealthy arm even when the last record looks quiet.
    try:
        from midas_watchdog import watchdog_summary
        wd_line, wd_bad = watchdog_summary()
        print(f"  watchdog: {wd_line}")
        if wd_bad:
            problems.append(f"watchdog escalated: {wd_line}")
    except ImportError:
        print("  watchdog: midas_watchdog module unavailable")
    # The heartbeat-gap alarm (2026-09-22). The watchdog line above answers "is the arm
    # beating NOW" — it reads the ledger's age at the moment it runs, so it cannot see the
    # hours when it did not run, and on the morning of 2026-09-22 that was 407 consecutive
    # minutes with nothing said about them. This line answers "was anything watching at
    # 03:00", from the recorded pass timeline, and it stays until a human acknowledges it.
    try:
        from live_coverage import alarm_line, prereg
        cov_line = alarm_line(alarm_path=COV_ALARM_PATH)
        if cov_line and "PROBLEM" in cov_line:
            print(paint(f"  coverage: {cov_line}", "r"))
            problems.append(f"heartbeat gap: {cov_line}")
        elif cov_line:
            print(f"  coverage: {cov_line}")
        else:
            rule = prereg()
            print(f"  coverage: no unacknowledged heartbeat-gap alarm "
                  f"(none over {rule['gap_alarm_min']} min between passes, no ledger "
                  f"heartbeat over {rule['heartbeat_alarm_min']} min)")
    except ImportError:
        print("  coverage: live_coverage module unavailable")
    for p in problems:
        print(paint(f"  PROBLEM: {p}", "r"))
    return bool(problems)


if __name__ == "__main__":
    main()
