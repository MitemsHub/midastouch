#!/usr/bin/env python3
"""The ledger-heartbeat-gap alarm, and the night's coverage measurement.

WHY THIS FILE EXISTS. The arm's liveness signal is the ledger's mtime: the EA writes an
`EQ` row at init and every 900 s in every terminal state, so a ledger older than ~2
heartbeats means the arm is dead, hung, or the loaded-but-dead EA signature. The watchdog
reads that number *at the moment it runs* and restarts the terminal when it is stale,
which answers "is the arm beating right now".

It does not answer "was the arm beating at 03:00", and on this machine that was the real
question. MEASURED 2026-09-22 from `artifacts/live/supervisor.log`: 54 supervision passes
in 25.3 h where a 20-minute cadence owes 76, **zero** passes in the 01:00-06:00 UTC hours,
and one gap of **407 minutes** (00:40:20Z -> 07:27:19Z). Nothing noticed, because nothing
was running to notice: the supervisor is a scheduled task whose principal is
`Interactive`, so it exists only while a human is signed in. The 12:32Z watchdog pass the
same day was the *first* pass after the machine woke, six and a half hours after the arm
had been evaluated for the last time; between them the strategy was not refusing anything,
it was not running.

So there are two records, and this module reads both:

  * **supervision coverage** — when a pass actually happened. Gaps here mean the
    supervisor (or the whole machine) was absent, and *no other artifact records that*,
    because a task that cannot start writes no log line either.
  * **heartbeat recency** — the ledger's age as each pass observed it. Gaps here mean the
    EA itself stopped beating while the supervisor kept running: a different fault with a
    different remedy, which is why the two are counted separately.

THE PRE-REGISTERED RULE (frozen 2026-09-22, before the first post-fix night is measured —
see `--prereg`). A window PASSES when no interval between recorded passes exceeds
`GAP_ALARM_MIN` and no observed ledger age exceeds `HEARTBEAT_ALARM_MIN`. Anything else
is GAPPED, and the gap is written where a human will read it. The rule is deliberately
about the *evidence we have* (recorded passes and observed ages) rather than about the
arm's internal state, because an unwritten minute is indistinguishable from a quiet one
and this program does not get to assume the friendly reading.

USAGE
    python scripts/live_coverage.py                 # the most recent complete night
    python scripts/live_coverage.py --hours 24      # the last 24 h instead
    python scripts/live_coverage.py --since ... --until ...   # explicit UTC ISO window
    python scripts/live_coverage.py --json          # machine-readable report
    python scripts/live_coverage.py --prereg        # print the frozen rule
    python scripts/live_coverage.py --alarm-state   # show the outstanding alarm, if any
    python scripts/live_coverage.py --ack           # mark the alarm seen (a human act)

Exit codes: 0 PASS, 1 GAPPED (a human must read the gap), 3 UNCONFIRMED (no record in the
window — a report about a source that was never read is not a pass).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "artifacts")
LIVE = os.path.join(ART, "live")

#: One line per supervision pass, append-only. Written by `scripts/paper_supervisor.py`
#: (the task the scheduler runs with nobody signed in), so its presence over a window is
#: the durable answer to "was anything supervising at 03:00".
HEARTBEAT_PATH = os.path.join(LIVE, "supervision_heartbeat.jsonl")
#: The supervisor's existing human-readable log: the record BEFORE the heartbeat file
#: existed, and still the place a crash lands. Read too, never rewritten.
SUPERVISOR_LOG = os.path.join(LIVE, "supervisor.log")
ALARM_PATH = os.path.join(LIVE, "heartbeat_gap_alarm.json")
ALERTS_LOG = os.path.join(LIVE, "alerts.log")

#: --- THE PRE-REGISTERED RULE (do not tune to make a night pass) ---------------------
#: Must equal the repetition interval the task is registered with
#: (`install_paper_task.ps1 -EveryMinutes`); a test pins the two together.
CADENCE_MIN = 20
#: 2 x cadence: one late firing is scheduler jitter (never an incident), two in a row is
#: the machine being absent. The measured pre-fix gap was 407 min — 10x this.
GAP_ALARM_MIN = 2 * CADENCE_MIN
#: The watchdog's own staleness tier, restated here as a number the report can cite.
#: `tests/test_live_coverage.py` pins it equal to `midas_watchdog.STALE_MIN` so the alarm
#: and the restart policy cannot drift apart.
HEARTBEAT_ALARM_MIN = 35
#: An unacknowledged alarm older than this is no longer surfaced as current (the night it
#: describes is history), but it is never deleted — `--alarm-state` still prints it.
ALARM_TTL_H = 24

#: Two records of the same pass (the watchdog's JSON line and the supervisor's summary
#: line) are emitted seconds apart; two *different* passes are a cadence apart.
MERGE_TOL_S = 90

_SUMMARY = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z\s+(?P<verdict>\w+)\s+action=(?P<action>\S+)")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _epoch(iso: str) -> float | None:
    """UTC epoch seconds from an ISO stamp (`...Z`, `...+00:00`, fractional seconds ok).

    A stamp with NO offset is read as UTC, never as local time. MEASURED 2026-09-22: the
    first version of this function fed the summary log's naive `2026-09-22T07:27:46` into
    `datetime.fromisoformat(...).astimezone(timezone.utc)`, and `astimezone` reads a naive
    datetime as LOCAL time — on this host (UTC+1) that reported every summary line an hour
    early, which moved the 2h04m frozen-mid-pass span to 05:23->06:27 and would have
    reported a night as *better covered* than it was. The log's stamps are UTC by
    construction (`%Y-%m-%dT%H:%M:%SZ`), so a missing offset is not ambiguity to resolve
    with a guess.
    """
    s = (iso or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- parsing

def parse_supervisor_log(text: str) -> list[dict]:
    """Every pass in a supervisor log, from its JSON records AND its summary lines.

    The log carries two lines per pass and they are not redundant: the JSON record holds
    the per-ledger ages, and the summary line is the only thing a crash or an import
    failure leaves behind. A line that parses as neither is skipped, not guessed at.
    """
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _SUMMARY.match(line)
        if m:
            ts = _epoch(m.group("ts"))
            if ts:
                out.append({"ts": ts, "src": "log-summary", "action": m.group("action"),
                            "verdict": m.group("verdict"), "ledger_age_min": None})
            continue
        if line.startswith("{"):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = _epoch(str(rec.get("ts", "")))
            if not ts:
                continue
            ages = [l.get("mtime_age_min") for l in (rec.get("ledgers") or [])
                    if isinstance(l, dict)]
            ages = [a for a in ages if isinstance(a, (int, float))]
            out.append({"ts": ts, "src": "log-json", "action": str(rec.get("action") or ""),
                        "verdict": "", "ledger_age_min": max(ages) if ages else None,
                        "terminal_running": rec.get("terminal_running"),
                        "problem": str(rec.get("problem") or "")})
    return out


def parse_heartbeat(text: str) -> list[dict]:
    """The append-only pass record this module's `record_pass` writes."""
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        ts = _epoch(str(rec.get("utc", "")))
        if ts:
            out.append({"ts": ts, "src": "heartbeat",
                        "action": str(rec.get("action") or ""),
                        "verdict": str(rec.get("verdict") or ""),
                        "ledger_age_min": rec.get("ledger_age_min"),
                        "terminal_running": rec.get("terminal_running"),
                        "problem": ""})
    return out


def merge_timeline(*groups: list[dict]) -> list[dict]:
    """Sort all records by time and collapse records of the SAME pass into one.

    Collapsing is what makes the count honest: the log holds a JSON line and a summary
    line for every pass, and counting both would report twice the supervision that
    happened.

    A record with no verdict is a pass that never COMPLETED: the watchdog prints its JSON
    at the START of a check and the supervisor prints the verdict at the END, so a JSON
    line with no summary line beside it is a check that began and never finished — and
    MEASURED 2026-09-22 there is exactly one, spanning 05:23:13Z -> 07:27:46Z (2h04m): a
    supervision pass FROZEN MID-FLIGHT while the host slept. It is counted (the check did
    run) and flagged, because "the supervisor started and stopped inside a pass" is a
    different night from "the supervisor never started at all".
    """
    rows = sorted((r for g in groups for r in g), key=lambda r: r["ts"])
    merged: list[dict] = []
    for r in rows:
        if merged and abs(r["ts"] - merged[-1]["ts"]) <= MERGE_TOL_S:
            prev = merged[-1]
            prev["ts"] = min(prev["ts"], r["ts"])
            for k, v in r.items():
                if k != "ts" and (prev.get(k) in (None, "") and v not in (None, "")):
                    prev[k] = v
            continue
        merged.append(dict(r))
    for r in merged:
        r["complete"] = bool(r.get("verdict")) or r.get("src") == "heartbeat"
    return merged


def timeline(heartbeat_path: str = HEARTBEAT_PATH,
             log_path: str = SUPERVISOR_LOG) -> list[dict]:
    """The full recorded pass timeline: heartbeat file first, legacy log as fallback.

    Both sources, because the heartbeat file starts empty and the log does not: a window
    that spans the change has passes in each, and reading only the new file would report
    the pre-change hours as unattended when they are merely in the other record. Paths are
    parameters so a test can point them at its own fixtures — the real log must never leak
    into a test run (the same hermeticity rule the LV broker snapshot follows).
    """
    groups: list[dict] = []
    try:
        with open(heartbeat_path, encoding="utf-8", errors="replace") as fh:
            groups.append(parse_heartbeat(fh.read()))
    except OSError:
        pass
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            groups.append(parse_supervisor_log(fh.read()))
    except OSError:
        pass
    return merge_timeline(*groups)


# --------------------------------------------------------------------------- the rule

def analyze(passes: list[dict], since: float, until: float, *,
            cadence_min: float = CADENCE_MIN,
            gap_alarm_min: float = GAP_ALARM_MIN,
            heartbeat_alarm_min: float = HEARTBEAT_ALARM_MIN) -> dict:
    """Apply the frozen rule to one window. Pure: tests pin it on synthetic timelines."""
    span_min = max(0.0, (until - since) / 60.0)
    rows = sorted((p for p in passes if since <= p["ts"] <= until),
                  key=lambda p: p["ts"])
    report: dict = {
        "since_utc": _utc(since), "until_utc": _utc(until),
        "span_hours": round(span_min / 60.0, 2),
        "cadence_min": cadence_min, "gap_alarm_min": gap_alarm_min,
        "heartbeat_alarm_min": heartbeat_alarm_min,
        "n_passes": len(rows),
        "passes_expected": int(span_min // cadence_min) if span_min else 0,
        "unfinished_passes": sum(1 for p in rows if not p.get("complete", True)),
        "gaps": [], "uncovered_min": 0.0, "longest_gap_min": 0.0,
        "max_ledger_age_min": None, "problems": [], "verdict": "PASS",
    }
    if not rows:
        report["verdict"] = "UNCONFIRMED"
        report["problems"].append(
            "no supervision pass is recorded in this window — the window is "
            "unmeasured, which is not the same as covered")
        return report

    points = [since] + [p["ts"] for p in rows] + [until]
    uncovered = 0.0
    longest = 0.0
    for a, b in zip(points, points[1:]):
        gap_min = (b - a) / 60.0
        uncovered += max(0.0, gap_min - cadence_min)
        longest = max(longest, gap_min)
        if gap_min > gap_alarm_min:
            report["gaps"].append({"from_utc": _utc(a), "to_utc": _utc(b),
                                   "minutes": round(gap_min, 1)})
    report["uncovered_min"] = round(uncovered, 1)
    report["longest_gap_min"] = round(longest, 1)
    report["coverage_pct"] = round(100.0 * (1.0 - uncovered / span_min), 1) if span_min else 0.0
    ages = [p["ledger_age_min"] for p in rows if isinstance(p.get("ledger_age_min"),
                                                            (int, float))]
    if ages:
        report["max_ledger_age_min"] = round(max(ages), 1)
        if report["max_ledger_age_min"] > heartbeat_alarm_min:
            report["problems"].append(
                f"the ledger's heartbeat age reached {report['max_ledger_age_min']} min at "
                f"a pass that DID run (> {heartbeat_alarm_min}) — the supervisor was "
                f"present and the arm was not beating")
    if report["gaps"]:
        report["problems"].append(
            f"{len(report['gaps'])} interval(s) longer than {gap_alarm_min} min between "
            f"supervision passes (longest {report['longest_gap_min']} min) — during those "
            f"minutes nothing was watching the arm")
    if report["unfinished_passes"]:
        report["problems"].append(
            f"{report['unfinished_passes']} pass(es) with no verdict: the watchdog printed "
            f"its record and the pass never completed — the host stopped inside the check "
            f"rather than between two of them")
    report["verdict"] = "GAPPED" if report["problems"] else "PASS"
    return report


def prereg() -> dict:
    """The frozen rule, as data, so a report can cite it instead of paraphrasing it."""
    return {
        "frozen_utc": "2026-09-22",
        "pass_rule": (f"a window PASSES iff no interval between recorded supervision "
                      f"passes exceeds {GAP_ALARM_MIN} min and no observed ledger "
                      f"heartbeat age exceeds {HEARTBEAT_ALARM_MIN} min"),
        "cadence_min": CADENCE_MIN, "gap_alarm_min": GAP_ALARM_MIN,
        "heartbeat_alarm_min": HEARTBEAT_ALARM_MIN,
        "why_these": (
            "GAP_ALARM_MIN is 2 x the registered cadence, so a single late firing "
            "(scheduler jitter, a slow terminal query) is never an incident while two "
            "consecutive misses are the machine being absent. HEARTBEAT_ALARM_MIN is the "
            "watchdog's own STALE_MIN, so 'the arm stopped beating' has one definition "
            "in this program. Both were fixed BEFORE the first post-fix night, and the "
            "pre-fix measurement (54 passes/25.3h, 407-min gap, 0 passes 01-06Z) is a "
            "BASELINE, not a test of them."),
        "what_it_cannot_see": (
            "a host that is asleep runs nothing, so the gap is only ever *raised* by the "
            "first pass after the host wakes. The alarm is therefore an after-the-fact "
            "record of a night that was not covered — the durable channel is "
            "artifacts/live/heartbeat_gap_alarm.json, alerts.log and morning_status [3b], "
            "not a push notification this program cannot send."),
    }


# --------------------------------------------------------------------------- the alarm

def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def raise_alarm(alarm: dict, *, alarm_path: str = ALARM_PATH,
                alerts_path: str = ALERTS_LOG) -> bool:
    """Persist `alarm`; return True only when it is a NEW episode.

    Deduped on the episode key (the pass the gap started from, or the heartbeat reading),
    because the first pass after a six-hour hole is not the only pass that can see it: the
    machine may run several passes before a human looks, and an alert channel that repeats
    the same incident every 20 minutes is one nobody reads.
    """
    previous = _read_json(alarm_path)
    if previous.get("episode") == alarm.get("episode") and previous.get("episode"):
        return False
    os.makedirs(os.path.dirname(alarm_path), exist_ok=True)
    with open(alarm_path, "w", encoding="utf-8") as fh:
        json.dump(alarm, fh, indent=2)
    try:
        os.makedirs(os.path.dirname(alerts_path), exist_ok=True)
        with open(alerts_path, "a", encoding="utf-8") as fh:
            fh.write(f"{alarm['raised_utc']} ALARM {alarm['kind']}: {alarm['detail']}\n")
    except OSError:
        pass
    return True


def alarm_state(*, alarm_path: str = ALARM_PATH, now: float | None = None) -> dict:
    """The outstanding alarm plus whether it is still current and still unacked."""
    rec = _read_json(alarm_path)
    if not rec:
        return {"present": False}
    now = time.time() if now is None else now
    raised = _epoch(str(rec.get("raised_utc", "")))
    rec["present"] = True
    rec["unacked"] = not rec.get("acked_utc")
    rec["age_h"] = round((now - raised) / 3600.0, 1) if raised else None
    rec["current"] = bool(rec["unacked"] and raised and
                          (now - raised) <= ALARM_TTL_H * 3600)
    return rec


def ack_alarm(*, alarm_path: str = ALARM_PATH, now: float | None = None) -> str:
    """Mark the outstanding alarm seen. A human act — that is the whole point of it."""
    rec = _read_json(alarm_path)
    if not rec:
        return "no alarm to acknowledge"
    now = time.time() if now is None else now
    rec["acked_utc"] = _utc(now)
    with open(alarm_path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    return f"acknowledged {rec.get('kind', '?')} raised {rec.get('raised_utc')}"


def record_pass(record: dict, *, verdict: str = "OK", now: float | None = None,
                heartbeat_path: str = HEARTBEAT_PATH,
                log_path: str = SUPERVISOR_LOG,
                alarm_path: str = ALARM_PATH,
                alerts_path: str = ALERTS_LOG) -> dict:
    """Record one supervision pass and evaluate the gap rule against the previous one.

    Called by the supervisor itself, so the rule is evaluated by the thing that runs
    unattended rather than by a report someone has to remember to open. Two faults are
    kept apart because their remedies are:

      * `supervision-gap` — no pass happened for over GAP_ALARM_MIN. The machine slept,
        the task failed, or the task was never unattended to begin with. Restarting the
        EA cannot fix it; the schedule can.
      * `ledger-heartbeat-gap` — a pass DID happen and the ledger's own heartbeat age was
        over HEARTBEAT_ALARM_MIN. That is the arm, not the supervisor, and the remedy is
        the watchdog's (which runs in the same pass, so this is a report not an action).

    Returns `{"heartbeat":..., "alarm":..., "alarm_new":bool, "alarm_state":{...}}`.
    """
    now = time.time() if now is None else now
    ages = [l.get("mtime_age_min") for l in (record.get("ledgers") or [])
            if isinstance(l, dict)]
    ages = [a for a in ages if isinstance(a, (int, float))]
    ledger_age = max(ages) if ages else None
    previous = timeline(heartbeat_path, log_path)
    prev_ts = previous[-1]["ts"] if previous else None

    hb = {
        "utc": _utc(now), "action": str(record.get("action") or ""), "verdict": verdict,
        "ledger_age_min": ledger_age,
        "terminal_running": record.get("terminal_running"),
        "armed": bool((record.get("arming") or {}).get("armed")),
        "problem": str(record.get("problem") or "")[:200],
    }
    os.makedirs(os.path.dirname(heartbeat_path), exist_ok=True)
    with open(heartbeat_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(hb) + "\n")

    alarm = None
    if prev_ts is not None and (now - prev_ts) / 60.0 > GAP_ALARM_MIN:
        gap_min = round((now - prev_ts) / 60.0, 1)
        alarm = {
            "episode": f"supervision-gap:{int(prev_ts)}",
            "kind": "supervision-gap", "raised_utc": _utc(now),
            "gap_min": gap_min, "from_utc": _utc(prev_ts), "to_utc": _utc(now),
            "threshold_min": GAP_ALARM_MIN, "cadence_min": CADENCE_MIN,
            "detail": (f"no supervision pass for {gap_min} min "
                       f"({_utc(prev_ts)} -> {_utc(now)}), over the {GAP_ALARM_MIN}-min "
                       f"alarm threshold — nothing was watching the arm for "
                       f"{gap_min} min"),
            "why": ("a host that is asleep runs no task, and a task that cannot start "
                    "writes no log line either; the night therefore reads like a quiet "
                    "market. Check that the arm's supervisor task runs with nobody "
                    "signed in (python scripts/unattended.py) and that this host can "
                    "hold it (python scripts/host_power.py)"),
        }
    elif isinstance(ledger_age, (int, float)) and ledger_age > HEARTBEAT_ALARM_MIN:
        alarm = {
            "episode": f"ledger-heartbeat-gap:{int(now)}",
            "kind": "ledger-heartbeat-gap", "raised_utc": _utc(now),
            "gap_min": round(float(ledger_age), 1), "from_utc": None, "to_utc": _utc(now),
            "threshold_min": HEARTBEAT_ALARM_MIN, "cadence_min": CADENCE_MIN,
            "detail": (f"a pass DID run and the ledger's heartbeat age was "
                       f"{ledger_age} min, over the {HEARTBEAT_ALARM_MIN}-min threshold "
                       f"— the supervisor was present and the arm was not beating"),
            "why": ("the remedy for this one is the watchdog's (same pass), not the "
                    "schedule's: inspect the EA journal and the chart, then "
                    "--reset-state once resolved"),
        }
    new = raise_alarm(alarm, alarm_path=alarm_path, alerts_path=alerts_path) \
        if alarm else False
    return {"heartbeat": hb, "alarm": alarm, "alarm_new": new,
            "alarm_state": alarm_state(alarm_path=alarm_path, now=now)}


def alarm_line(*, alarm_path: str = ALARM_PATH, now: float | None = None) -> str | None:
    """One line for `morning_status [3b]`, or None when nothing is outstanding."""
    st = alarm_state(alarm_path=alarm_path, now=now)
    if not st.get("present"):
        return None
    mark = "PROBLEM" if st.get("current") else "past"
    ack = "" if st.get("unacked") else f" (acknowledged {st.get('acked_utc')})"
    return (f"{mark}: {st.get('kind')} — {st.get('detail')}, raised "
            f"{st.get('raised_utc')}{ack}")


# --------------------------------------------------------------------------- the window

def night_window(now: float | None = None) -> tuple[float, float]:
    """The most recent COMPLETE night: 22:00 -> 08:00 UTC, anchored at the last 08:00Z.

    Gold's own clock, not a guess: the week runs Sun 22:00 -> Fri 21:00 UTC and the
    machine's measured hole (00:40Z -> 07:27Z) sits inside that band. Anchoring on the
    last 08:00Z at or before `now` keeps the window complete by construction, so a report
    run at 05:00 cannot describe a night that has not finished and call the remainder a
    gap.
    """
    now = time.time() if now is None else now
    dt = datetime.fromtimestamp(now, timezone.utc)
    anchor = dt.replace(hour=8, minute=0, second=0, microsecond=0)
    if anchor > dt:
        anchor -= timedelta(days=1)
    return (anchor - timedelta(hours=10)).timestamp(), anchor.timestamp()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--night", action="store_true",
                    help="the most recent complete night (22:00->08:00 UTC); the default")
    ap.add_argument("--hours", type=float, default=None,
                    help="window ending now, this many hours back")
    ap.add_argument("--since", help="window start, ISO UTC (with --until)")
    ap.add_argument("--until", help="window end, ISO UTC")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--prereg", action="store_true", help="print the frozen rule")
    ap.add_argument("--alarm-state", action="store_true",
                    help="show the outstanding alarm and exit")
    ap.add_argument("--ack", action="store_true",
                    help="acknowledge the outstanding alarm (a human act)")
    args = ap.parse_args(argv)

    if args.prereg:
        print(json.dumps(prereg(), indent=2))
        return 0
    if args.ack:
        print(ack_alarm())
        return 0
    if args.alarm_state:
        st = alarm_state()
        if not st.get("present"):
            print("no outstanding heartbeat-gap alarm")
            return 0
        print(json.dumps(st, indent=2))
        return 1 if st.get("current") else 0

    now = time.time()
    if args.since or args.until:
        since, until = _epoch(args.since or ""), _epoch(args.until or "")
        if since is None or until is None:
            print("--since and --until must both be ISO UTC stamps", file=sys.stderr)
            return 2
    elif args.hours is not None:
        since, until = now - args.hours * 3600.0, now
    else:
        since, until = night_window(now)

    report = analyze(timeline(), since, until)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"=== ARM COVERAGE — {report['since_utc']} -> {report['until_utc']} "
              f"({report['span_hours']}h) ===")
        print(f"  passes      : {report['n_passes']} recorded / "
              f"{report['passes_expected']} due at a {report['cadence_min']:.0f}-min cadence")
        print(f"  coverage    : {report.get('coverage_pct', 0.0)}% "
              f"({report['uncovered_min']} min unattended beyond one cadence)")
        print(f"  longest gap : {report['longest_gap_min']} min "
              f"(alarm over {report['gap_alarm_min']:.0f} min)")
        if report["unfinished_passes"]:
            print(f"  unfinished  : {report['unfinished_passes']} pass(es) began and never "
                  f"completed (the host stopped inside the check)")
        print(f"  heartbeat   : worst observed ledger age "
              f"{report['max_ledger_age_min']} min "
              f"(alarm over {report['heartbeat_alarm_min']:.0f} min)")
        for g in report["gaps"]:
            print(f"    GAP {g['minutes']:7.1f} min  {g['from_utc']} -> {g['to_utc']}")
        print(f"  VERDICT: {report['verdict']}")
        for p in report["problems"]:
            print(f"    - {p}")
    return {"PASS": 0, "GAPPED": 1, "UNCONFIRMED": 3}.get(report["verdict"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
