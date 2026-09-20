"""Pins for the MQL5 synthetic call executor.

Two things are tested here, and neither is a formality.

**It compiles.** Nothing else in this repo can catch an MQL5 syntax error, and
`metaeditor64.exe /compile:` can — so this suite runs the real compiler and fails
on any error or warning. It is skipped (not silently passed) when MetaEditor is
not installed, because a compile test that quietly does nothing is worse than no
compile test.

**The disposition policy is right.** Compiling cannot tell whether a call file is
archived at the *correct* moments, and that is the whole point of the change: a
call file left in place is an execution trigger. So the terminal dispositions
(executed / expired / held_back) must all pass through `ConcludeCall`, and the
transient ones (rejected) must NOT — archiving a rejected call would discard an
instruction that is still valid and that must retry.

Background, measured on this machine 2026-09-19: the state file said
`status":"rejected"` with `retcode:10026` (auto-trading off), so `OnInit`
deliberately did not restore the call id, while a proven buy call sat in
Common\\Files. Only its expiry date stopped it firing; `expiry_epoch: 0` (which the
parser documents as "no expiry") would have let it through on the next attach.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "mql5" / "SynthCallExecutor.mq5"

#: Where MetaEditor usually lives. The one that matters is the install the
#: terminal actually runs from, so this is discovered rather than assumed.
METAEDITOR_CANDIDATES = (
    Path(r"C:\Program Files\MetaTrader 5\metaeditor64.exe"),
    Path(r"C:\Program Files\MetaTrader 5 Terminal\metaeditor64.exe"),
)


def _metaeditor() -> Path | None:
    for p in METAEDITOR_CANDIDATES:
        if p.is_file():
            return p
    env = os.environ.get("METAEDITOR")
    if env and Path(env).is_file():
        return Path(env)
    return None


def _source() -> str:
    return EXECUTOR.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# The disposition policy
# --------------------------------------------------------------------------- #

#: Calls that will never be acted on again -> the file must be archived.
TERMINAL = ("executed", "expired", "held_back")

#: Calls that must be retried -> the file must stay for the next poll.
TRANSIENT = ("rejected",)


def test_terminal_dispositions_go_through_conclude():
    """Concluding is what archives; a terminal status written without it leaks."""
    src = _source()
    for status in TERMINAL:
        assert f'ConcludeCall("{status}"' in src, (
            f"{status!r} must be concluded (dedupe + archive + record), not just "
            f"recorded, or the call file stays in place as an execution trigger")


def test_transient_dispositions_never_archive():
    """A rejected order is still a valid instruction; discarding it loses the trade."""
    src = _source()
    for status in TRANSIENT:
        assert f'ConcludeCall("{status}"' not in src, (
            f"{status!r} must NOT be concluded -- it has to retry until expiry")
        assert f'SaveState("{status}"' in src, (
            f"{status!r} must still be recorded so the operator can see it")


def test_execute_call_concludes_on_acceptance_only():
    """Success archives; the failure paths inside ExecuteCall must not."""
    src = _source()
    body = src.split("bool ExecuteCall(", 1)[1].split("\n//+---", 1)[0]
    assert 'ConcludeCall("executed"' in body, "acceptance must conclude the call"
    # every early failure path returns false before reaching the conclude
    first_conclude = body.index('ConcludeCall("executed"')
    for marker in ("order failed for", "position not found"):
        assert marker in body, marker
        assert body.index(marker) < first_conclude, (
            f"{marker!r} must return false BEFORE the conclude, or a failed order "
            f"would archive a call that still has to retry")


def test_the_archive_rename_is_actually_performed():
    """A policy that never renames the file is not a fix."""
    src = _source()
    assert "FileMove(InpCallFile, FILE_COMMON" in src
    assert "FILE_COMMON | FILE_REWRITE" in src
    assert "ARCHIVE FAILED" in src, "a failed rename must be loud"


def test_restart_dedupe_only_remembers_what_is_provably_finished():
    """The lesson from the field: remembering a rejected call stalls the pass."""
    src = _source()
    init = src.split("int OnInit()", 1)[1]
    assert 'prevStatus == "executed"' in init
    assert 'prevArchived == "true"' in init
    assert 'prevStatus == "rejected"' not in init, (
        "a rejected call must not be remembered at init -- that is the observed "
        "forward-pass stall (retcode 10026 clears without the call changing)")


def test_archiving_can_be_disabled_but_says_so():
    src = _source()
    assert "InpArchiveProcessed = true" in src, "must default ON"
    assert "archiving DISABLED" in src, "and must be loud when turned off"


def test_an_unparseable_call_file_is_not_destroyed():
    """The emitter writes atomically, so an unreadable file is not ours.

    Renaming it away could destroy another consumer's input; leaving it silently
    could hide a trigger. So it is left, and warned about once.
    """
    src = _source()
    assert 'callId == ""' in src
    assert "not acting on it, not archiving it" in src


# --------------------------------------------------------------------------- #
# It compiles -- the only MQL5 check available
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(_metaeditor() is None,
                    reason="MetaEditor64 not installed; cannot compile MQL5")
def test_the_executor_compiles_clean():
    meta = _metaeditor()
    with tempfile.TemporaryDirectory(prefix="mq5build_") as tmp:
        log = Path(tmp) / "compile.log"
        # The path is quoted INSIDE the switch, and the whole thing goes through a
        # shell. Passing an argv list instead lets Windows' argument quoting wrap
        # the entire "/compile:C:\... file.mq5" token in quotes, at which point
        # MetaEditor no longer recognises the switch and reports
        # "error 208: unsupported file extension" against a truncated path.
        cmd = f'"{meta}" /compile:"{EXECUTOR}" /log:"{log}"'
        proc = subprocess.run(cmd, shell=True, capture_output=True, timeout=300)
        assert log.is_file(), (
            f"MetaEditor produced no log (exit {proc.returncode}); stdout="
            f"{proc.stdout[:400]!r}")
        text = log.read_bytes().decode("utf-16", errors="replace")
        assert "unsupported file extension" not in text, (
            "MetaEditor could not parse the invocation, not the source -- check "
            f"the quoting in this test. Log:\n{text[:400]}")
    # Match diagnostics specifically. The summary line itself reads
    # "Result: 0 errors, 0 warnings", so a substring test on "error" flags a
    # successful build -- which it did on the first run of this test.
    diag = [ln for ln in text.splitlines() if not ln.strip().startswith("Result:")]
    errors = [ln for ln in diag if re.search(r"\berror\s+\d+", ln)]
    warnings = [ln for ln in diag if re.search(r"\bwarning\s+\d+", ln)]
    result = next((ln.strip() for ln in text.splitlines() if ln.startswith("Result:")), "")
    assert not errors, "MQL5 compile errors:\n" + "\n".join(errors)
    assert not warnings, "MQL5 compile warnings:\n" + "\n".join(warnings)
    assert "0 errors" in result, f"unexpected compiler result line: {result!r}"


def test_the_compiled_artifact_is_gitignored():
    """The compile test writes an .ex5 next to the source, so it must not be tracked."""
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
    assert "mql5/*.ex5" in gi, (
        "test_the_executor_compiles_clean writes mql5/SynthCallExecutor.ex5; "
        "without an ignore rule that build output becomes a tracked file")
