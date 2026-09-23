#!/usr/bin/env python3
"""Can this HOST keep supervising while nobody is watching? (power posture, measured)

WHY THIS FILE EXISTS. MEASURED 2026-09-22 on this machine, with `powercfg`:

    Standby (S0 Low Power Idle) Network Connected     <- the ONLY standby state
    Standby (S3)                                       not available
    Sleep after        AC=0x0 (never)  DC=0x0 (never)
    Hibernate after    AC=0x0 (never)  DC=0x7fffffff (never)
    Allow wake timers  AC=0x0 (DISABLED) DC=0x0 (DISABLED)
    Lid close action   not exposed by powercfg on this build

None of that is visible from inside the program, and all of it decides whether the
supervision the task scheduler promises actually happens. The arm's own record says it
did not: 54 passes in 25.3 h where 76 were due, **zero** passes in the 01:00-06:00 UTC
hours, one gap of 407 minutes (00:40Z -> 07:27Z). "Sleep after = never" was already true
and did not prevent any of it, because a Modern-Standby laptop sleeps on lid close / S0
idle regardless of the idle timer, and with `Allow wake timers` DISABLED a `WakeToRun`
task cannot wake it.

So there are two separate questions and this module answers the second one:

  1. is the supervisor scheduled to run with nobody signed in? -> `scripts/unattended.py`
  2. can THIS HOST hold up its end, or does the schedule evaporate when the lid shuts?
     -> here.

The second answer is not a nicety: it is the difference between "the arm exists 5 hours
a day" and a live arm. It is also the reason a VPS is the correct home for an armed
strategy — a hosted server has no lid, no S0 idle and no user session to lose. This
module reports the posture and prints the exact elevated commands that would change it;
it never changes system state itself (that is the operator's act, and `powercfg
-setacvalueindex` needs elevation this program does not have).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

#: `Current AC Power Setting Index: 0x00000000`
_AC_INDEX = re.compile(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)")
_DC_INDEX = re.compile(r"Current DC Power Setting Index:\s*0x([0-9a-fA-F]+)")
_ALIAS = re.compile(r"GUID Alias:\s*(\S+)", re.I)
_AVAILABLE = re.compile(r"^\s*(Standby \(S\d[^)]*\)|Hibernate|Fast Startup)\s*(.*)$")
_RTCWAKE_NAMES = {0: "Disable", 1: "Enable", 2: "Important Wake Timers Only"}

#: Settings this program asks about, by the alias `powercfg` prints.
WATCHED = ("STANDBYIDLE", "HIBERNATEIDLE", "RTCWAKE")


def parse_query(text: str) -> dict[str, int]:
    """`GUID Alias` -> the AC index that follows it. Pure, so tests pin real output.

    `powercfg -query` prints a setting's alias and then its AC/DC indices; the pairing
    is positional (`powercfg` the tool, not a serializer), so this walks the lines and
    remembers the most recent alias. A setting that appears with no AC line is recorded
    as absent rather than defaulted — the whole point of the powercore check is not to
    invent a value.
    """
    out: dict[str, int] = {}
    cur: str | None = None
    for line in text.splitlines():
        m = _ALIAS.search(line)
        if m:
            cur = m.group(1).upper()
            continue
        m = _AC_INDEX.search(line)
        if m and cur and cur not in out:
            out[cur] = int(m.group(1), 16)
    return out


def parse_available(text: str) -> list[str]:
    """The available sleep states, verbatim from `powercfg -a`."""
    out: list[str] = []
    in_avail = False
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("the following sleep states are available"):
            in_avail = True
            continue
        if low.startswith("the following sleep states are not available"):
            in_avail = False
            continue
        if in_avail and line.strip():
            out.append(line.strip())
    return out


def posture_from(available: str, query: str, lid_query: str = "",
                 lastwake: str = "", *, runner=None) -> dict:
    """The posture, from the raw command outputs (pure — tests use canned text).

    THREE VERDICTS, not two, because the middle one is where this machine actually sits
    after its power settings are fixed, and calling it either PASS or FAIL would be a
    claim the evidence does not support:

      * `hold` — a host this program can reason about from `powercfg`: no S0 Low Power
        Idle, wake timers relevant or unnecessary, timers set to never. A desktop or a
        server. PASS.
      * `cannot` — a measured defect with a measured fix (wake timers disabled, a standing
        sleep/hibernate timer). FAIL, and the fix is printed.
      * `unverified` — nothing measured is wrong, and the rest is not measurable from here:
        S0 Low Power Idle is present, so whether a wake timer actually wakes an S0 host and
        whether the lid policy (unreadable on this build) suspends it are both unknown.
        This is where a fixed laptop lands, and the thing that would promote it to `hold`
        is not a setting — it is **one measured night**
        (`scripts/live_coverage.py`). Reporting it as PASS would be exactly the "looks
        quiet, must be healthy" reading this program keeps paying for.
    """
    avail = parse_available(available)
    vals = parse_query(query)
    sleep_states = " | ".join(avail)
    s0 = any("s0 low power idle" in a.lower() for a in avail)
    standby = vals.get("STANDBYIDLE")
    hibernate = vals.get("HIBERNATEIDLE")
    rtcwake = vals.get("RTCWAKE")
    lid_txt = parse_query(lid_query)
    lid = lid_txt.get("LIDACTION")
    blockers: list[str] = []

    if rtcwake != 1:
        blockers.append(
            f"Allow wake timers = "
            f"{_RTCWAKE_NAMES.get(rtcwake, rtcwake) if rtcwake is not None else 'unknown'} "
            f"on AC: a WakeToRun task cannot wake this host, so a scheduled pass during "
            f"sleep simply does not happen")
    if standby:
        blockers.append(f"Sleep after = {standby} s on AC (not never)")
    if hibernate:
        blockers.append(f"Hibernate after = {hibernate} s on AC (not never)")

    notes: list[str] = []
    if s0:
        lid_note = ("lid-close action not exposed by powercfg on this build" if lid is None
                    else f"lid action AC={lid}")
        if blockers:
            notes.append(
                "S0 Low Power Idle is the only standby state (no S3): the host suspends on "
                f"lid close / idle independently of the 'Sleep after' timer; {lid_note}")
        else:
            notes.append(
                "S0 Low Power Idle is the only standby state (no S3) and wake timers are "
                f"ENABLED: a WakeToRun pass now has the host's permission to wake it, but "
                f"whether a wake timer actually wakes an S0 host - and whether the lid "
                f"policy suspends it at all ({lid_note}) - is NOT observable from "
                f"powercfg. Promote this to PASS with one measured night "
                f"(scripts/live_coverage.py), not with a setting")
    verdict = "cannot" if blockers else ("unverified" if s0 else "hold")
    return {
        "sleep_states": sleep_states, "s0_low_power_idle": s0,
        "sleep_after_ac_s": standby, "hibernate_after_ac_s": hibernate,
        "wake_timers_ac": rtcwake, "wake_timers": _RTCWAKE_NAMES.get(rtcwake, "unknown"),
        "lid_action_ac": lid, "lastwake": (lastwake or "").strip(),
        "verdict": verdict,
        "suitable": verdict == "hold", "problems": blockers + notes,
    }


def read_posture(*, runner=subprocess.run) -> tuple[dict | None, str]:
    """Run the four read-only `powercfg` probes -> (posture, error)."""
    def run(args: list[str]) -> str:
        out = runner(["powercfg", *args], capture_output=True, text=True, timeout=30)
        return (out.stdout or "") + (out.stderr or "")

    try:
        available = run(["-a"])
        query = run(["-query", "SCHEME_CURRENT", "SUB_SLEEP"])
        try:
            lid = run(["-query", "SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION"])
        except (OSError, subprocess.SubprocessError):
            lid = ""
        try:
            lastwake = run(["-lastwake"])
        except (OSError, subprocess.SubprocessError):
            lastwake = ""
    except (OSError, subprocess.SubprocessError, FileNotFoundError) as exc:
        return None, f"powercfg unavailable ({exc})"
    if not available.strip():
        return None, "powercfg returned nothing — the posture is unreadable"
    return posture_from(available, query, lid, lastwake), ""


def fix_commands() -> list[str]:
    """The exact elevated commands that would make the host hold up its end.

    Printed by default; the operator runs them. Each one is here because it was MEASURED
    to be part of the problem on this host, not because it is good practice in general:

      * `RTCWAKE 1` — wake timers are DISABLED (measured 0x0 on AC and DC). Without this,
        the supervisor's `WakeToRun` is a wish: the pass during sleep does not happen, and
        because a task that cannot start writes no log line, the night reads like a quiet
        market. This is the one that turns the scheduled pass into a pass.
      * `LIDACTION 0` — closing the lid is the plausible cause of the 282.8-minute
        midnight hole and it is NOT readable through `powercfg -query` on this build, so it
        is set blind. Writing a value that cannot be read back is stated plainly rather
        than presented as a verified fix; `host_power.py` re-reports UNMEASURABLE for it
        either way.
      * `STANDBYIDLE 0` / `HIBERNATEIDLE 0` — already 0 when measured, and kept in the
        list so the command set is idempotent and self-describing rather than dependent on
        a remembered earlier state.

    AC only, deliberately: the identical DC values would also stop a laptop on battery
    from ever sleeping, which is a decision about battery life that this program has no
    business making on the operator's behalf.
    """
    return [
        "powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1",
        "powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0",
        "powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE 0",
        "powercfg -setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0",
        "powercfg -setactive SCHEME_CURRENT",
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Host power posture (read-only)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix-commands", action="store_true",
                    help="print the elevated commands that would change the posture")
    args = ap.parse_args(argv)

    posture, err = read_posture()
    if posture is None:
        print(f"UNCONFIRMED: {err}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(posture, indent=2))
    else:
        print(f"host power posture (measured, powercfg):")
        print(f"  sleep states     : {posture['sleep_states']}")
        print(f"  sleep after (AC) : {posture['sleep_after_ac_s']} s"
              f"{' (never)' if posture['sleep_after_ac_s'] == 0 else ''}")
        print(f"  hibernate (AC)   : {posture['hibernate_after_ac_s']} s"
              f"{' (never)' if posture['hibernate_after_ac_s'] == 0 else ''}")
        print(f"  wake timers (AC) : {posture['wake_timers']}")
        print(f"  lid action (AC)  : "
              f"{posture['lid_action_ac'] if posture['lid_action_ac'] is not None else 'not exposed by powercfg'}")
        verdict = {"hold": "PASS", "cannot": "FAIL"}.get(posture["verdict"], "UNVERIFIED")
        print(f"  {verdict}: "
              + ("this host can hold supervision through the night"
                 if posture["verdict"] == "hold" else
                 "this host cannot yet be certified for unattended supervision:"))
        for p in posture["problems"]:
            print(f"    - {p}")
    if args.fix_commands and posture["verdict"] != "hold":
        print()
        if posture["verdict"] == "cannot":
            print("  to change it (the operator's act, not this program's):")
            for c in fix_commands():
                print(f"    {c}")
        else:
            print("  no setting is measured wrong on this host. What would promote it to "
                  "PASS is one measured night:")
            print("    python scripts/live_coverage.py        # PASS = certified, GAPPED = the hole")
    return 0 if posture["verdict"] == "hold" else 1


if __name__ == "__main__":
    raise SystemExit(main())
