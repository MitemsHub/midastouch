#!/usr/bin/env python3
"""Run every operator diagnostic against an UNREADABLE terminal and assert it refuses.

WHY THIS EXISTS. On 2026-09-19 seven operator scripts were found pinned to MT5
data directories that no longer existed. None of them crashed. They read nothing
and then **reported a verdict anyway** — `confirm-gate-open.ps1` printed a
positive assertion of an OPEN gate, `funnel_diff.py` would have reported
`match (0)` on every row, `demo_watchdog.py` said the account was quiet, and
`atr_drift_monitor.py` fell back to its frozen calibration band and emitted a
within-tolerance reading. A tool that reports a verdict from a path it could not
read is indistinguishable from one reporting green. That is a *class* of defect,
so it needs a class-level test rather than one review pass.

WHAT THIS DOES. Points the tools at an empty terminal root and runs each one. A
script passes only when ALL of these hold:

  1. it exits NON-ZERO — a refusal is not a success;
  2. its output carries a REFUSAL MARKER naming what it could not resolve;
  3. it does **not** traceback. This one is not pedantry: an escaping
     `TerminalNotFound` gives the same exit code while presenting the refusal as
     a crash, and any caller wrapping the script in `except Exception` would file
     a refusal as a bug. The difference between "I refuse" and "I broke" is the
     whole point, so the sweep fails a stack trace;
  4. it writes **nothing** to the artifact paths under watch. Recording a reading
     for a run that measured nothing is reporting a verdict, which is the exact
     defect class this exists to catch.

It restores anything a case did write, so the sweep is safe to run repeatedly and
cannot itself pollute the repo. It exits 0 only when every case refused.

A SWEEP THAT CANNOT FAIL IS WORTHLESS, so there is a positive control: run
`--self-check` to feed the verdict function a script that exits 0, one that
tracebacks, one that writes an artifact, and one that times out, and assert each
is caught. `tests/test_refusal_sweep.py` pins the same function.

Usage:
    python scripts/refusal_sweep.py              # run every case
    python scripts/refusal_sweep.py --self-check # prove the sweep can fail
    python scripts/refusal_sweep.py --only funnel_diff.py
    python scripts/refusal_sweep.py --keep       # do NOT restore what was written
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PY = sys.executable

#: Every path a case could write to. Snapshotted before the sweep and restored
#: after, so the sweep reports writes instead of causing them.
WATCH = (
    ROOT / "artifacts" / "v75_replay",
    ROOT / "artifacts" / "prop_sizing_verification.json",
)

#: An escaping exception means the script broke, not that it refused. Checked as a
#: literal rather than by exit code because both cases exit non-zero.
TRACEBACK = "Traceback (most recent call last)"


@dataclass(frozen=True)
class Case:
    """One operator diagnostic, and how to make its input unreadable."""

    name: str
    args: tuple[str, ...] = ()
    marker: str = ""
    """A substring that must appear in the output — the refusal naming its cause."""
    title: str = ""
    kind: str = "python"
    offline_flag: tuple[str, ...] = ()
    """Appended to force the refusal path where an empty root is not enough."""
    records_refusal: bool = False
    """Declares that this script legitimately WRITES a record of its own refusal.

    Narrow on purpose. The default rule is that a run which could not read its
    input writes nothing, because leaving a reading behind is what a later reader
    mistakes for a measurement (that is exactly what `atr_drift_monitor` was
    doing). A case may opt out, but then it must also declare `write_signals`
    that the written content has to contain — so the exemption is itself
    checked rather than taken on trust.
    """
    write_signals: tuple[str, ...] = ()
    """Substrings the written file must contain for a declared refusal record."""


#: The diagnostics that read a terminal directory. Every one of these must refuse
#: rather than report. Keep this list in step with the §5.2 table in
#: docs/STALE_FLAG_AUDIT_20260919.md.
CASES: tuple[Case, ...] = (
    Case("demo_watchdog.py", marker="cannot resolve",
         title="telemetry verdict from an unreadable root"),
    Case("funnel_diff.py", marker="REFUSING",
         title="replay-vs-live comparison"),
    Case("atr_drift_monitor.py", marker="SKIPPED",
         title="calibration drift reading"),
    Case("midas_drift_drill.py", marker="cannot resolve",
         title="drift drill seeding"),
    Case("go_live_rehearsal.py", marker="REFUSING",
         title="go-live rehearsal"),
    Case("set_chart_preset.py",
         args=("--chart", "Default/chart01.chr",
               "--preset", "mql5/MIDASTOUCH/MidastouchAI_LV_gold.set",
               "--magic", "991001", "--dry-run"),
         marker="cannot resolve", title="chart preset write"),
    Case("verify_sizing_live.py",
         args=("--symbol", "XAUUSD", "--stop-price", "9.89"),
         offline_flag=("--offline",), marker="TERMINAL UNAVAILABLE",
         # This one deliberately leaves a trail of the REFUSAL (no "verdict", no
         # lot size, terminal.available false). That is useful and is not what
         # the write rule guards against, so it is exempt -- and the exemption is
         # verified by requiring the file to say the terminal was unavailable.
         records_refusal=True, write_signals=('"available": false',),
         title="sizing verification (MT5 bridge)"),
    Case("live_readiness.py", offline_flag=("--offline",),
         marker="TERMINAL UNAVAILABLE",
         title="live readiness (MT5 bridge)"),
    Case("confirm-gate-open.ps1", kind="powershell",
         # It now delegates to the shared resolver rather than scanning installs
         # itself, so with an empty root it reports that the ACTIVE ACCOUNT could
         # not be resolved. The "gate is UNKNOWN, not OPEN" wording belongs to the
         # branch where a journal exists but holds no EA evidence, which an empty
         # root never reaches -- matching the wrong branch's string is a mistake
         # this case already made once.
         marker="no MT5 terminal for the ACTIVE ACCOUNT",
         title="gate-state confirmation"),
)


@dataclass
class Result:
    case: Case
    exit_code: int | None
    output: str
    wrote: list[str] = field(default_factory=list)
    timed_out: bool = False
    ok: bool = False
    reason: str = ""


# --------------------------------------------------------------------------- #
# The verdict — pure, so it can be positive-controlled
# --------------------------------------------------------------------------- #


def verdict(case: Case, *, exit_code: int | None, output: str,
            wrote: list[tuple[str, str]] | None = None,
            timed_out: bool = False) -> tuple[bool, str]:
    """Decide whether one case refused properly. Returns (ok, reason).

    Deliberately a pure function over the observed facts: the sweep's own
    soundness is then testable without spawning processes, which is what makes
    the positive control in `--self-check` possible.
    """
    wrote = wrote or []
    if timed_out:
        return False, "timed out — a hung diagnostic is not a refusal"
    if exit_code == 0:
        return False, ("exited 0 — reported SUCCESS from a terminal it could not "
                       "read, which is the defect class this sweep exists for")
    if exit_code is None:
        return False, "did not run"
    if TRACEBACK in output:
        return False, ("raised a traceback instead of refusing — the refusal "
                       "never reaches the operator as a diagnosis, and a wrapper "
                       "catching Exception would file it as a bug")
    if case.marker and case.marker not in output:
        return False, (f"exited {exit_code} but never named what it could not "
                       f"resolve (expected {case.marker!r} in the output)")
    if wrote:
        names = ", ".join(p for p, _ in wrote)
        if not case.records_refusal:
            return False, (f"wrote {names} while unable to read its input — "
                           "recording a reading is reporting a verdict")
        for path, text in wrote:
            if not any(sig in text for sig in case.write_signals):
                return False, (f"wrote {path} on refusal, but the content is not "
                               f"identifiable as a refusal (expected one of "
                               f"{case.write_signals!r}) — a later reader would "
                               f"take it for a result")
    note = f"refused cleanly (exit {exit_code})"
    if wrote:
        note += f"; recorded the refusal in {', '.join(p for p, _ in wrote)}"
    return True, note


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def _empty_root() -> str:
    """A directory with no MetaQuotes/Terminal tree under it at all."""
    return tempfile.mkdtemp(prefix="refusal_sweep_empty_")


def _argv(case: Case, offline: bool = True) -> list[str] | None:
    args = list(case.args)
    if offline:
        args += list(case.offline_flag)
    if case.kind == "powershell":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            return None
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(SCRIPTS / case.name), *args]
    return [PY, str(SCRIPTS / case.name), *args]


def _snapshot() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for target in WATCH:
        if target.is_file():
            out[str(target)] = target.read_bytes()
        elif target.is_dir():
            for p in target.rglob("*"):
                if p.is_file():
                    try:
                        out[str(p)] = p.read_bytes()
                    except OSError:
                        continue
    return out


def _restore(before: dict[str, bytes]) -> None:
    for path_str, content in before.items():
        p = Path(path_str)
        try:
            if not p.is_file() or p.read_bytes() != content:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
        except OSError:
            continue


def run_case(case: Case, empty_root: str, *, timeout: float = 180.0,
             offline: bool = True, keep: bool = False) -> Result:
    argv = _argv(case, offline=offline)
    if argv is None:
        return Result(case=case, exit_code=None,
                      output="powershell is not available on this machine",
                      reason="skipped: no powershell")

    env = dict(os.environ)
    env["APPDATA"] = empty_root          # no MetaQuotes/Terminal tree under it
    env.pop("MITEMSHUB_MT5_ACCOUNT", None)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    before = _snapshot()
    timed_out = False
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), env=env, timeout=timeout,
                              capture_output=True)
        code = proc.returncode
        output = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        code, output, timed_out = None, "", True
    except OSError as exc:
        code, output = None, f"could not execute: {exc}"

    wrote = sorted(
        (str(Path(k).relative_to(ROOT)), v.decode("utf-8", errors="replace"))
        for k, v in _snapshot().items() if before.get(k) != v)
    if not keep:
        _restore(before)

    ok, reason = verdict(case, exit_code=code, output=output, wrote=wrote,
                         timed_out=timed_out)
    return Result(case=case, exit_code=code, output=output,
                  wrote=[p for p, _ in wrote], timed_out=timed_out,
                  ok=ok, reason=reason)


def sweep(only: str | None = None, timeout: float = 180.0,
          keep: bool = False) -> list[Result]:
    empty = _empty_root()
    try:
        results = []
        for case in CASES:
            if only and case.name != only:
                continue
            results.append(run_case(case, empty, timeout=timeout, keep=keep))
        return results
    finally:
        shutil.rmtree(empty, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Positive control
# --------------------------------------------------------------------------- #


def self_check() -> tuple[bool, list[str]]:
    """Prove the verdict function catches each way this sweep could be fooled.

    Without this, a sweep that silently stopped running cases — a renamed script,
    a bad marker, a swallowed exception — would keep printing PASS.
    """
    probe = Case("probe.py", marker="cannot resolve", title="probe")
    declared = Case("probe.py", marker="cannot resolve", title="probe",
                    records_refusal=True, write_signals=('"available": false',))
    trials: tuple[tuple[str, Case, dict, bool], ...] = (
        ("exits 0 while blind", probe,
         dict(exit_code=0, output="all good"), False),
        ("tracebacks instead of refusing", probe,
         dict(exit_code=1, output=TRACEBACK), False),
        ("exits non-zero but silent", probe,
         dict(exit_code=1, output="done"), False),
        ("hangs", probe,
         dict(exit_code=None, output="", timed_out=True), False),
        ("writes a reading anyway", probe,
         dict(exit_code=2, output="cannot resolve",
              wrote=[("artifacts/x.json", '{"verdict": "HOLD"}')]), False),
        ("refuses properly", probe,
         dict(exit_code=2, output="cannot resolve a terminal"), True),
        ("records its refusal, declared", declared,
         dict(exit_code=2, output="cannot resolve",
              wrote=[("artifacts/x.json", '"available": false')]), True),
        ("declared write but no signal", declared,
         dict(exit_code=2, output="cannot resolve",
              wrote=[("artifacts/x.json", '{"lots": 0.37}')]), False),
    )
    lines, all_ok = [], True
    for label, case, kwargs, expect_ok in trials:
        ok, reason = verdict(case, **kwargs)
        hit = ok == expect_ok
        all_ok &= hit
        lines.append(f"  [{'OK ' if hit else 'MISS'}] {label:<32} "
                     f"-> {'pass' if ok else 'fail'}: {reason[:70]}")
    return all_ok, lines


# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="run a single case by script filename")
    ap.add_argument("--self-check", action="store_true",
                    help="prove the sweep can fail, using synthetic cases")
    ap.add_argument("--keep", action="store_true",
                    help="do NOT restore artifacts a case wrote (default: restore)")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.self_check:
        ok, lines = self_check()
        print("REFUSAL SWEEP -- SELF-CHECK (positive control)")
        print("\n".join(lines))
        print(f"\nself-check: {'PASS the sweep can fail' if ok else 'FAIL the sweep is vacuous'}")
        return 0 if ok else 1

    before = _snapshot()
    results = sweep(args.only, timeout=args.timeout, keep=args.keep)
    if not args.keep:
        _restore(before)          # belt and braces; run_case already restored

    if not results:
        print(f"no case matched --only {args.only!r}", file=sys.stderr)
        return 2

    skipped = [r for r in results if r.exit_code is None and "skipped" in r.reason]
    failed = [r for r in results if not r.ok and r not in skipped]

    if args.json:
        print(json.dumps([{"script": r.case.name, "ok": r.ok,
                           "exit": r.exit_code, "reason": r.reason,
                           "wrote": r.wrote} for r in results], indent=2))
    else:
        print("REFUSAL SWEEP — every diagnostic against an unreadable terminal root")
        print(f"  cases: {len(results)}   "
              f"passed: {sum(1 for r in results if r.ok)}   "
              f"failed: {len(failed)}   skipped: {len(skipped)}")
        print()
        for r in results:
            tag = "PASS" if r.ok else ("SKIP" if r in skipped else "FAIL")
            print(f"  [{tag}] {r.case.name:<26} exit={str(r.exit_code):<5} "
                  f"{r.case.title}")
            if r.ok:
                print(f"           {r.reason}")
            else:
                for line in r.reason.splitlines():
                    print(f"           ! {line}")
                tail = [ln for ln in r.output.strip().splitlines() if ln.strip()][-4:]
                for ln in tail:
                    print(f"           | {ln[:130]}")

    if failed:
        print()
        print("The class of defect this sweep exists for is still present: a "
              "diagnostic that could not read its input and did not say so.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
