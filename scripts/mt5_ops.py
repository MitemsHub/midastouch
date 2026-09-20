#!/usr/bin/env python3
"""MT5 terminal operations for the LIVE Upcomers install — no research engine attached.

WHY THIS MODULE EXISTS. The operator chain (watchdog, parity harness) needed four
things from MT5 and nothing more: the data folder, the exe path, the running PIDs, and
"is every paper book flat?". It got them from `v28_sweep_runner`, the V75 indices sweep
runner — a module belonging to a program that closed. That import was not harmless:

  * the exe it pinned was the V75 TESTER install (`MitemshubMT5_B\\terminal64.exe`),
    not the Upcomers install, so `stop_terminal()` and `relaunch_terminal()` acted on
    the wrong terminal — or on nothing, once that install was gone;
  * `data_folder_for_terminal()` matched installs by that same pinned directory, so
    the gold arm's ledger flatness was being read out of a dead tree;
  * it made the indices engine impossible to delete, so the live program's shutdown
    path was hostage to a module nobody maintained.

Generalising was the available fix, and all of it already exists elsewhere in this
repo: `mt5_terminals.resolve_terminal()` identifies an install by the ACCOUNT NUMBER
in its journals and refuses rather than defaulting. This module is that resolver plus
the four primitives, with the closing program removed.

FAILURE DISCIPLINE. Two different questions, two different answers, deliberately:

  * `data_folder_for_terminal()` returns ``None`` when nothing resolves. Callers
    already treat ``None`` as "cannot verify" and refuse loudly (the watchdog reports
    a problem and skips the act it was about to take).
  * PIDs and process control RAISE `MT5OpsUnavailable` when the install is unknown.
    Returning ``[]`` here would be read as "the terminal is not running" — a false
    negative that turns a failed lookup into a successful stop. Unknown is not empty.

Reads and process control only: no strategy, no research, no venue rules.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import time

import mt5_terminals

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Stop/relaunch windows. A terminal that is gone within a minute is stopped; one that
#: is not is reported as such rather than waited on forever.
STOP_WAIT_S = 60
RELAUNCH_SETTLE_S = 20

#: The EA family whose paper books this module gates on. Only charts carrying this
#: string are inventoried — the indices engines used to be inventoried too, and every
#: one of their ledgers is now a file that will never be written again.
EA_MARKER = "MidastouchAI"


class MT5OpsUnavailable(RuntimeError):
    """The live terminal could not be identified, so no process action is safe."""


def terminal_exe_or_unknown() -> str:
    """The live exe for DISPLAY, or a phrase naming why it is unknown.

    For records and messages, where an exception would lose the report. Anything
    that acts on the terminal must use `terminal_exe()`.
    """
    try:
        return terminal_exe()
    except MT5OpsUnavailable as exc:
        return f"unknown ({exc})"


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def data_folder_for_terminal() -> str | None:
    """The live terminal's data folder, by account identity, or ``None``.

    ``None`` is a real answer: it means no install names the active account, and the
    caller must report that rather than operate on a guess. The name is the one the
    operator chain already calls this by; only the resolution behind it changed.
    """
    try:
        td, _why = mt5_terminals.resolve_terminal()
    except mt5_terminals.TerminalNotFound:
        return None
    return str(td)


def terminal_exe() -> str:
    """The executable of the live install, read from its own ``origin.txt``.

    Raises `MT5OpsUnavailable` when the install cannot be identified. Callers that
    only need a display string want `terminal_exe_or_unknown()`.

    ``origin.txt`` records the INSTALL DIRECTORY, not the exe path. MT5 writes it
    UTF-16 with a BOM; a utf-8 read silently garbles it into replacement characters,
    which is how a wrong-path match appears to succeed.
    """
    td = data_folder_for_terminal()
    if not td:
        raise MT5OpsUnavailable(
            "no terminal names the active account, so its executable is unknown "
            f"({mt5_terminals.load_account_registry().status()})")
    origin = os.path.join(td, "origin.txt")
    try:
        raw = open(origin, "rb").read()
    except OSError as exc:
        raise MT5OpsUnavailable(f"cannot read {origin}: {exc}")
    text = raw.decode("utf-16", errors="replace") \
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else raw.decode("utf-8", errors="replace")
    install_dir = text.strip().rstrip("\\/")
    exe = os.path.join(install_dir, "terminal64.exe")
    if not os.path.isfile(exe):
        raise MT5OpsUnavailable(
            f"origin.txt of {os.path.basename(td)} names {install_dir}, which holds "
            f"no terminal64.exe")
    return exe


# --------------------------------------------------------------------------- #
# Process control
# --------------------------------------------------------------------------- #

def terminal_pids_exact() -> list[int]:
    """PIDs of terminal64.exe processes whose executable path matches the live install.

    Case-insensitive full-path equality: other MT5 installs on this machine belong to
    accounts we do not trade and must never match, however recently they were touched.
    """
    want = os.path.normcase(terminal_exe())
    raw = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
         "Where-Object {$_.ExecutablePath} | ForEach-Object "
         "{$_.ExecutablePath + '|' + $_.ProcessId})"],
        capture_output=True, text=True, timeout=30).stdout
    pids: list[int] = []
    for line in raw.splitlines():
        if "|" not in line:
            continue
        exe, _, pid = line.strip().rpartition("|")
        if os.path.normcase(exe) == want and pid.strip().isdigit():
            pids.append(int(pid))
    return pids


def stop_terminal(pids: list[int]) -> bool:
    """Taskkill the given PIDs, then wait until none of them remain."""
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline:
        if not terminal_pids_exact():
            return True
        time.sleep(2)
    return not terminal_pids_exact()


def relaunch_terminal() -> None:
    """Relaunch the live terminal detached; equity/state restore on EA init."""
    subprocess.Popen([terminal_exe()], close_fds=True)
    time.sleep(RELAUNCH_SETTLE_S)


# --------------------------------------------------------------------------- #
# Paper books
# --------------------------------------------------------------------------- #

def inventory_arms(data_folder: str | None) -> list[dict]:
    """The gold EA's paper arms hosted by the terminal, from its chart profiles.

    Same discovery method as ``morning_status.terminal_inventory``: a chart whose
    ``.chr`` names the EA and carries both a symbol and a magic yields one arm entry
    with its ledger path (``InpArmTag`` switches the EA to tagged file names).

    Only `EA_MARKER` charts are inventoried. An occupant that is not a gold arm is
    not an occupant of this program's books.
    """
    arms: list[dict] = []
    if not data_folder:
        return arms
    pattern = os.path.join(data_folder, "MQL5", "Profiles", "Charts", "*", "*.chr")
    for chr_f in sorted(glob.glob(pattern)):
        try:
            txt = open(chr_f, encoding="utf-16", errors="replace").read()
        except OSError:
            continue
        if EA_MARKER not in txt:
            continue
        sym_m = re.search(r"^symbol=(\S+)", txt, re.M)
        magic_m = re.search(r"^InpMagic(?:Number)?=(\d{7})\s*$", txt, re.M)
        if not sym_m or not magic_m:
            continue
        magic = magic_m.group(1)
        tag_m = re.search(r"^InpArmTag=(\S+)\s*$", txt, re.M)
        tag = tag_m.group(1) if tag_m else None
        suffix = f"_{tag}" if tag else ""
        arms.append({
            "magic": magic,
            "name": tag or f"unknown_{magic}",
            "tag": tag,
            "chart": os.path.basename(chr_f),
            "ledger": os.path.join(data_folder, "MQL5", "Files",
                                   f"MIDASTOUCH_paper_{sym_m.group(1)}{suffix}.csv"),
        })
    return arms


def ledger_flatness(path: str) -> dict:
    """Is this paper ledger flat? Flat = zero OPEN rows without a CLOSE.

    Mirrors the EA's own restore rule (PaperInit adopts a dangling OPEN as a live
    virtual position), so flat here means exactly "the EA would restore nothing on the
    next init". ERA/EQ provenance rows are ignored; an unreadable or corrupt ledger
    FAILS CLOSED (flat=False with a problem recorded) — nothing proceeds on a book
    that could not be read.
    """
    res: dict = {"flat": False, "open_positions": [], "problems": [],
                 "rows": 0, "era_stamps": 0, "closed": 0}
    open_rows: dict[str, tuple[str, int]] = {}
    try:
        with open(path) as f:
            for ln, line in enumerate(f, 1):
                res["rows"] += 1
                parts = line.strip().split(",")
                if not parts:
                    continue
                if parts[0] == "OPEN" and len(parts) >= 12:
                    open_rows[parts[2]] = (parts[1], ln)
                elif parts[0] == "CLOSE" and len(parts) >= 8:
                    open_rows.pop(parts[2], None)
                    res["closed"] += 1
                elif parts[0] == "ERA":
                    res["era_stamps"] += 1
                elif parts[0] == "LOPEN" and len(parts) >= 14:
                    # A dangling LOPEN is a REAL-MONEY position (14 fields, keyed on
                    # [2] = posid). No session may stop the terminal over a live trade.
                    open_rows[parts[2]] = (parts[1], ln)
                elif parts[0] == "LCLOSE" and len(parts) >= 6:
                    # LCLOSE pairs the LOPEN (posid at [2]) and carries R, not $.
                    open_rows.pop(parts[2], None)
                    res["closed"] += 1
    except FileNotFoundError:
        res["problems"].append("ledger missing (arm never initialized?)")
        return res
    except OSError as e:
        res["problems"].append(f"unreadable: {e}")
        return res
    except (ValueError, IndexError) as e:
        res["problems"].append(f"corrupt row: {e}")
        return res
    res["open_positions"] = [
        {"ticket": t, "epoch": e, "line": n} for t, (e, n) in open_rows.items()]
    # A real paper book always carries an era stamp, a trade, or both. A file with no
    # recognizable row is either not a ledger or not yet initialized — never flat.
    if res["rows"] == 0 or (not res["closed"] and not res["era_stamps"]
                            and not res["open_positions"]):
        res["problems"].append(
            "no recognizable ledger rows (ERA/OPEN/CLOSE/LOPEN/LCLOSE)")
        res["flat"] = False
        return res
    res["flat"] = not res["open_positions"]
    return res


def verify_all_flat(arms: list[dict]) -> tuple[bool, list[dict]]:
    """Every arm's ledger must exist and be flat. Fails closed on problems.

    An EMPTY arm list returns ``(True, [])`` — vacuous truth, unchanged from the
    behaviour this was extracted from. Callers must therefore treat "no arms
    inventoried" as its own finding (the watchdog does, via the data folder check):
    zero books is not the same as zero open trades.
    """
    all_flat, evidence = True, []
    for arm in arms:
        f = ledger_flatness(arm["ledger"])
        arm["flatness"] = f
        evidence.append({"name": arm["name"], "magic": arm["magic"],
                         "tag": arm["tag"], "ledger": arm["ledger"], **f})
        if not f["flat"]:
            all_flat = False
    return all_flat, evidence
