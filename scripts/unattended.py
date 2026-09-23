#!/usr/bin/env python3
"""Is the arm's supervisor a task that runs whether or not anyone is signed in?

WHY THIS FILE EXISTS. MEASURED 2026-09-22 on this machine:

    $ Get-ScheduledTask -TaskName MitemshubPaperSupervisor | ...
    MitemshubPaperSupervisor | state=Ready | logon=Interactive | runlevel=Limited

and over the previous 25.3 h that task produced 54 supervision passes where 76 were
due (20-min cadence), with **zero** passes in the 01:00-06:00 UTC hours and one gap of
407 minutes — the machine slept from 00:40Z to 07:27Z. The supervisor was not broken;
it was *absent*, because an Interactive-principal task runs only while a human is
signed in, and the arm's market hours are the hours the human is not there.

So "the supervisor is registered" was never the property that mattered. The property is
whether the task would still run at 03:00 with nobody logged on and the host asleep.
That is a fact about the task DEFINITION, it is readable without running anything, and
it is what this module answers — from the task's own XML, which is the scheduler's
account of itself rather than a sentence in an installer.

Three legs, each independently necessary:

  * **LogonType** — `Interactive` means "only while a user is signed in". `S4U` (and
    `Password`) mean "whether or not the user is logged on", which is the requirement.
    This is the leg today's task fails.
  * **a BootTrigger** — a repetition schedule anchored at "now" only exists once
    something started it. A boot trigger is what makes supervision begin at power-on
    with nobody signed in, and what survives the reboot that reaps everything else.
  * **WakeToRun** — a sleeping host runs no task. Without it the schedule is a wish:
    the pass simply does not happen, and (this is the part that hides it) a task that
    cannot start writes no log line either, so the night reads exactly like a quiet
    market.

Deliberately NOT a leg: whether the task is currently Ready/Disabled, and whether it
has ever run. Those are observations about the past; the question here is about 03:00
tonight.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

#: Logon types that mean "runs whether or not the user is signed on". `Interactive`
#: is absent on purpose: it is the defect, not a weaker version of the requirement.
UNATTENDED_LOGON_TYPES = ("s4u", "password", "serviceaccount")

#: ISO-8601 duration -> minutes, for `<Repetition><Interval>`. Only the shapes Task
#: Scheduler emits are handled (P<n>D, PT<n>H, PT<n>M, PT<n>S); an unrecognised shape
#: returns None, which callers must treat as "could not be confirmed", never as 0.
_DUR = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")


def parse_iso_duration_min(text: str) -> float | None:
    """Minutes in an ISO-8601 duration (`PT20M`, `P3650D`, `PT0S`), or None."""
    m = _DUR.match((text or "").strip())
    if not m:
        return None
    d, h, mi, s = (float(g) if g else 0.0 for g in m.groups())
    return d * 1440.0 + h * 60.0 + mi + s / 60.0


def _local(tag: str) -> str:
    """Local name of a possibly-namespaced tag (`{ns}Trigger` -> `Trigger`)."""
    return tag.rsplit("}", 1)[-1]


def task_posture(xml_text: str) -> dict:
    """The task definition's relevant facts, parsed from `Export-ScheduledTask` XML.

    Pure, so it is pinned by tests against the XML of a known-bad task (today's) and a
    known-good one, rather than against whatever the scheduler happens to say.
    """
    out: dict = {
        "logon_type": "", "run_level": "", "user_id": "",
        "boot_trigger": False, "wake_to_run": False, "triggers": [],
        "repetition_interval_min": None, "execution_time_limit": "",
        "multiple_instances": "", "start_when_available": False,
        "parse_error": "",
    }
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        out["parse_error"] = f"task XML unreadable: {exc}"
        return out
    for el in root.iter():
        name = _local(el.tag)
        txt = (el.text or "").strip()
        low = txt.lower()
        if name == "LogonType" and not out["logon_type"]:
            out["logon_type"] = txt
        elif name == "RunLevel" and not out["run_level"]:
            out["run_level"] = txt
        elif name == "UserId" and not out["user_id"]:
            out["user_id"] = txt
        elif name == "BootTrigger":
            out["boot_trigger"] = True
            out["triggers"].append("boot")
        elif name == "CalendarTrigger" or name == "TimeTrigger":
            out["triggers"].append("time")
        elif name == "LogonTrigger":
            out["triggers"].append("logon")
        elif name == "WakeToRun":
            out["wake_to_run"] = out["wake_to_run"] or low == "true"
        elif name == "Interval" and out["repetition_interval_min"] is None:
            out["repetition_interval_min"] = parse_iso_duration_min(txt)
        elif name == "ExecutionTimeLimit":
            out["execution_time_limit"] = txt
        elif name == "MultipleInstancesPolicy":
            out["multiple_instances"] = txt
        elif name == "StartWhenAvailable":
            out["start_when_available"] = low == "true"
    return out


def unattended_verdict(posture: dict) -> tuple[bool, list[str]]:
    """(ok, reasons-it-is-not). Every failing leg is named, not just the first.

    "The supervisor runs whether or not anyone is signed in" is three facts, and a
    report that collapses them into one PASS hides which one to fix — the same
    discipline `live_readiness.add()` applies to its own legs.
    """
    reasons: list[str] = []
    if posture.get("parse_error"):
        reasons.append(posture["parse_error"])
        return False, reasons
    logon = str(posture.get("logon_type", "")).strip().lower()
    if logon not in UNATTENDED_LOGON_TYPES:
        reasons.append(
            f"logon type is {posture.get('logon_type') or 'unreadable'!r}: an "
            f"Interactive-principal task runs only while a user is signed in, and the "
            f"arm's market hours are exactly the hours nobody is")
    if not posture.get("boot_trigger"):
        reasons.append(
            "no BootTrigger: nothing starts supervision at power-on with nobody "
            "signed in (a repetition schedule anchored at 'now' has to have been "
            "started by something)")
    if not posture.get("wake_to_run"):
        reasons.append(
            "WakeToRun is off: a sleeping host runs no task, and a task that cannot "
            "start writes no log line either, so the night reads like a quiet market")
    return (not reasons), reasons


def read_task_posture(name: str, *,
                      runner=subprocess.run) -> tuple[dict | None, str]:
    """`Export-ScheduledTask` for `name` -> (posture, error).

    Three outcomes, kept distinct the way `live_readiness._scheduled_task_target` keeps
    them: a posture, "no such task", and "could not ask". Collapsing the last two
    renders an unanswerable check as a pass.
    """
    try:
        out = runner(["powershell", "-NoProfile", "-Command",
                      f"Export-ScheduledTask -TaskName '{name}'"],
                     capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    text = (out.stdout or "").strip()
    if out.returncode != 0 or not text:
        # PowerShell writes a multi-line error for a task that does not exist, and the
        # useful part is at the top. "Not registered" is kept as its own phrase because
        # callers report it differently from "could not ask": one means the task is
        # absent, the other means the answer is unknown.
        blob = ((out.stderr or "") + " " + (out.stdout or "")).strip()
        if "0x80070002" in blob or "cannot find" in blob.lower() \
                or "does not exist" in blob.lower():
            return None, "not registered"
        return None, (blob.splitlines()[0][:200] if blob else "no output")
    return task_posture(text), ""


def verify_task(name: str, **kw) -> tuple[bool, str]:
    """(ok, one-line detail) for `name` — the shape callers report."""
    posture, err = read_task_posture(name, **kw)
    if posture is None:
        if err == "not registered":
            return False, (f"{name} is not registered: nothing supervises the arm. "
                           f"Register it with scripts/install_paper_task.ps1 -Apply")
        return False, f"could not be read ({err}) — unattended-ness UNCONFIRMED"
    ok, reasons = unattended_verdict(posture)
    if ok:
        return True, (f"logon={posture['logon_type']} runlevel={posture['run_level']} "
                      f"triggers={','.join(posture['triggers']) or 'none'} "
                      f"repeats={posture['repetition_interval_min']}min "
                      f"wake-to-run=on — runs with nobody signed on")
    return False, "; ".join(reasons)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Is this scheduled task unattended?")
    ap.add_argument("task", nargs="?", default="MIDASTOUCH Arm Supervisor",
                    help="scheduled task name")
    ap.add_argument("--xml", help="parse this XML file instead of asking the scheduler")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.xml:
        with open(args.xml, encoding="utf-16" if args.xml.lower().endswith(".xml")
                  else "utf-8", errors="replace") as fh:
            posture, err = task_posture(fh.read()), ""
    else:
        posture, err = read_task_posture(args.task)
    if posture is None:
        print(f"UNCONFIRMED: {args.task}: {err}", file=sys.stderr)
        return 3
    ok, reasons = unattended_verdict(posture)
    if args.json:
        print(json.dumps({"task": args.task, "unattended": ok, "posture": posture,
                          "reasons": reasons}, indent=2))
        return 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {args.task}: "
          f"logon={posture['logon_type'] or '?'} "
          f"runlevel={posture['run_level'] or '?'} "
          f"triggers={','.join(posture['triggers']) or 'none'} "
          f"repeats={posture['repetition_interval_min']}min "
          f"wake-to-run={'on' if posture['wake_to_run'] else 'off'} "
          f"time-limit={posture['execution_time_limit'] or '?'}")
    for r in reasons:
        print(f"  why not: {r}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
